"""Gateway-only SQLite metadata and fixed-size AES-GCM payload records."""
import json
import sqlite3
import threading
from contextlib import closing, contextmanager
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from audit_queue import AuditQueue
from common import MAX_ATTEMPTS_PER_RUN, RANGE_WIDTH, REPORT_BUDGET
from range_feedback import generate_range, probe_digest
from vault import PayloadVault, RECORD_BYTES


class Store:
    def __init__(self, directory, key, *, range_seed_mode="run", range_generator=generate_range, range_randbelow=None,
                 audit_queue_max=10000):
        if range_seed_mode not in {"run", "probeset"}:
            raise ValueError("Invalid RANGE_SEED_MODE")
        self.range_seed_mode, self.range_generator = range_seed_mode, range_generator
        self.range_key, self.range_randbelow = key, range_randbelow
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.database = self.directory / "runs.sqlite"
        # Prompt persistence runs in worker threads; prevent SQLite busy-backoff
        # from stalling the event loop behind another connection's short commit.
        self.lock = threading.Lock()
        self.cipher = AESGCM(key)
        self.vault = PayloadVault(self.directory / "vault", key)
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS runs (
                    run_id TEXT PRIMARY KEY, owner TEXT NOT NULL,
                    finished INTEGER NOT NULL DEFAULT 0, report TEXT
                );
                CREATE TABLE IF NOT EXISTS attempts (
                    id INTEGER PRIMARY KEY, run_id TEXT NOT NULL,
                    safe INTEGER NOT NULL DEFAULT 0, done INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS budgets (
                    owner TEXT, run_id TEXT, used INTEGER NOT NULL,
                    PRIMARY KEY(owner, run_id)
                );
            """)
            for table, column, kind in (("runs", "defense_version", "TEXT"), ("attempts", "prompt_hash", "TEXT"),
                                        ("attempts", "cancelled", "INTEGER NOT NULL DEFAULT 0"),
                                        ("attempts", "payload_ref", "TEXT"), ("attempts", "output_ref", "TEXT"),
                                        ("attempts", "blue_allowed", "INTEGER"),
                                        ("attempts", "late", "INTEGER NOT NULL DEFAULT 0")):
                if column not in {row[1] for row in db.execute(f"PRAGMA table_info({table})")}:
                    db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {kind}")
            # One worker only: abandoned work after a restart is never replayed.
            db.execute("UPDATE attempts SET done=1 WHERE done=0")
        # Separate file: audit enqueue/ack never waits on run/budget locks.
        # Replay after a crash is safe: the collector drops duplicates by gw_seq.
        self.audit_queue = AuditQueue(self.directory / "audit_queue.sqlite", audit_queue_max)

    @contextmanager
    def connect(self):
        with self.lock, closing(sqlite3.connect(self.database, timeout=5)) as db, db:
            db.execute("BEGIN IMMEDIATE")
            yield db

    def begin(self, run_id, owner, prompt_hash=None, defense_version=None):
        with self.connect() as db:
            db.execute("INSERT OR IGNORE INTO runs(run_id, owner, defense_version) VALUES (?, ?, ?)", (run_id, owner, defense_version))
            row = db.execute("SELECT owner, finished FROM runs WHERE run_id=?", (run_id,)).fetchone()
            if row != (owner, 0):
                return None
            if db.execute("SELECT COUNT(*) FROM attempts WHERE run_id=?", (run_id,)).fetchone()[0] >= MAX_ATTEMPTS_PER_RUN:
                return None
            return db.execute("INSERT INTO attempts(run_id, prompt_hash) VALUES (?, ?)", (run_id, prompt_hash)).lastrowid

    def end(self, attempt, safe, cancelled=False, blue_allowed=None, output_ref=None, late=False):
        with self.connect() as db:
            db.execute("UPDATE attempts SET safe=?, done=1, cancelled=?, blue_allowed=?, output_ref=COALESCE(?,output_ref), late=? WHERE id=?",
                       (int(safe), int(cancelled), int(blue_allowed) if type(blue_allowed) is bool else None, output_ref, int(late), attempt))

    def save_prompt(self, attempt, run_id, owner, prompt):
        ref = self.vault.put(prompt, role="red", run_id=run_id, owner=owner, kind="prompt")
        with self.connect() as db:
            db.execute("UPDATE attempts SET payload_ref=? WHERE id=?", (ref, attempt))
        return self.vault.get(ref, role="red", run_id=run_id, owner=owner, kind="prompt")

    def seal_output(self, run_id, owner, output):
        # A fixed-size output record also exists for blocked/failed/cancelled work.
        # Its reference and done/count flags are published in one end() commit.
        return self.vault.put(output, role="red", run_id=run_id, owner=owner, kind="output")

    def completed_payloads(self, run_id, owner):
        """Trusted gateway/operator method, never a Red/Blue HTTP endpoint."""
        with self.connect() as db:
            run = db.execute("SELECT finished FROM runs WHERE run_id=? AND owner=?", (run_id, owner)).fetchone()
            if run != (1,):
                raise PermissionError("Finished owned run required")
            refs = db.execute("SELECT payload_ref, output_ref, blue_allowed, cancelled FROM attempts WHERE run_id=? ORDER BY id", (run_id,)).fetchall()
        return [dict(prompt=self.vault.get(p, role="red", run_id=run_id, owner=owner, kind="prompt") if p else None,
                     output=self.vault.get(o, role="red", run_id=run_id, owner=owner, kind="output") if o else None,
                     blue_allowed=bool(allowed) if allowed is not None else None, cancelled=bool(cancelled))
                for p, o, allowed, cancelled in refs]

    def evaluation(self, run_id):
        """Evaluator-only counts for a finished run (incl. deadline cancellations)."""
        with self.connect() as db:
            run = db.execute("SELECT finished FROM runs WHERE run_id=?", (run_id,)).fetchone()
            if not run or not run[0]:
                return None
            total, safe, cancelled, late = db.execute(
                "SELECT COUNT(*), COALESCE(SUM(safe),0), COALESCE(SUM(cancelled),0), COALESCE(SUM(late),0) FROM attempts WHERE run_id=?",
                (run_id,)).fetchone()
        result = {"attempts": total, "safe": safe, "cancelled": cancelled}
        if late:  # Only the opt-in continue mode produces late (finished after the window deadline) attempts.
            result["late"] = late
        return json.dumps(result, separators=(",", ":")).encode().ljust(64, b" ")

    def finish(self, run_id):
        with self.connect() as db:
            pending = db.execute("SELECT COUNT(*) FROM attempts WHERE run_id=? AND done=0", (run_id,)).fetchone()[0]
            if not pending:
                changed = db.execute("UPDATE runs SET finished=1 WHERE run_id=?", (run_id,)).rowcount
                return bool(changed)
            return False

    def audit_next(self):
        return self.audit_queue.head()

    def audit_failed(self, run_id):
        return self.audit_queue.failed(run_id)

    def report(self, run_id, owner):
        with self.connect() as db:
            run = db.execute("SELECT finished, report FROM runs WHERE run_id=? AND owner=?", (run_id, owner)).fetchone()
            if not run or not run[0]:
                return None
            db.execute("INSERT OR IGNORE INTO budgets VALUES (?, ?, 0)", (owner, run_id))
            used = db.execute("SELECT used FROM budgets WHERE owner=? AND run_id=?", (owner, run_id)).fetchone()[0]
            if used >= REPORT_BUDGET:
                return None
            if run[1]:
                result = run[1]
            else:
                total, safe = db.execute("SELECT COUNT(*), COALESCE(SUM(safe),0) FROM attempts WHERE run_id=?", (run_id,)).fetchone()
                hashes = [row[0] or "" for row in db.execute("SELECT prompt_hash FROM attempts WHERE run_id=?", (run_id,))]
                version = db.execute("SELECT defense_version FROM runs WHERE run_id=?", (run_id,)).fetchone()[0]
                payload = self.range_generator(safe, total, mode=self.range_seed_mode, key=self.range_key,
                                               identity=owner, probes=probe_digest(hashes), version=version,
                                               randbelow=self.range_randbelow)
                result = json.dumps(payload, separators=(",", ":"))
                db.execute("UPDATE runs SET report=? WHERE run_id=?", (result, run_id))
            db.execute("UPDATE budgets SET used=used+1 WHERE owner=? AND run_id=?", (owner, run_id))
            return result.encode().ljust(64, b" ")

    def seal(self, config):
        self.vault.cover_read()
        blob = self.vault.pack(config, b"blue-defense-v2")
        path = self.directory / "defense.enc"
        self.vault._write(path, blob)

    def unseal(self):
        path = self.directory / "defense.enc"
        if not path.exists():
            return None
        blob = path.read_bytes()
        self.vault.cover_read()
        if len(blob) == RECORD_BYTES:
            return self.vault.unpack(blob, b"blue-defense-v2")
        # Read old authentic records once, then migrate without rotating the key.
        value = json.loads(self.cipher.decrypt(blob[:12], blob[12:], b"blue-defense-v1"))
        self.seal(value)
        return value
