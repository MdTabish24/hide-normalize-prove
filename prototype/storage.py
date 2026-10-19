"""SQLite transactions and an AES-GCM sealed defense file. Gateway only."""
import json
import os
import secrets
import sqlite3
from contextlib import closing, contextmanager
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from audit_queue import AuditQueue
from common import MAX_ATTEMPTS_PER_RUN, RANGE_WIDTH, REPORT_BUDGET
from range_feedback import generate_range, probe_digest


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
        self.cipher = AESGCM(key)
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
            for table, column in (("runs", "defense_version"), ("attempts", "prompt_hash")):
                if column not in {row[1] for row in db.execute(f"PRAGMA table_info({table})")}:
                    db.execute(f"ALTER TABLE {table} ADD COLUMN {column} TEXT")
            # One worker only: abandoned work after a restart is never replayed.
            db.execute("UPDATE attempts SET done=1 WHERE done=0")
        # Separate file: audit enqueue/ack never waits on run/budget locks.
        # Replay after a crash is safe: the collector drops duplicates by gw_seq.
        self.audit_queue = AuditQueue(self.directory / "audit_queue.sqlite", audit_queue_max)

    @contextmanager
    def connect(self):
        with closing(sqlite3.connect(self.database, timeout=5)) as db, db:
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

    def end(self, attempt, safe):
        with self.connect() as db:
            db.execute("UPDATE attempts SET safe=?, done=1 WHERE id=?", (int(safe), attempt))

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
        nonce = secrets.token_bytes(12)
        blob = nonce + self.cipher.encrypt(nonce, json.dumps(config).encode(), b"blue-defense-v1")
        path = self.directory / "defense.enc"
        temporary = path.with_suffix(".tmp")
        temporary.write_bytes(blob)
        os.chmod(temporary, 0o600)
        temporary.replace(path)

    def unseal(self):
        path = self.directory / "defense.enc"
        if not path.exists():
            return None
        blob = path.read_bytes()
        return json.loads(self.cipher.decrypt(blob[:12], blob[12:], b"blue-defense-v1"))
