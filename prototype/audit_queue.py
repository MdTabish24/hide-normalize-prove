"""Gateway-side durable audit queue. Its own SQLite file: no lock contention with run state.

Enqueue never waits for the collector. Per-run sequence numbers (gw_seq) are
assigned here, so the collector can drop retried duplicates and detect gaps.
Nothing is deleted unless delivered: undeliverable entries move to audit_dead
and the run is flagged audit_incomplete (column `unavailable`).
"""
import json
import sqlite3
import threading
from contextlib import closing, contextmanager
from pathlib import Path


SCHEMA = """
CREATE TABLE IF NOT EXISTS audit_state (
    run_id TEXT PRIMARY KEY, unavailable INTEGER NOT NULL DEFAULT 0,
    reason TEXT, next_seq INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS audit_outbox (
    id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL,
    path TEXT NOT NULL, payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS audit_dead (
    id INTEGER PRIMARY KEY, run_id TEXT NOT NULL, path TEXT NOT NULL,
    payload TEXT NOT NULL, reason TEXT NOT NULL
);
"""


class AuditQueue:
    def __init__(self, path, max_entries=10000, wal=False):
        self.path, self.max_entries, self.wal = Path(path), max_entries, wal
        # Enqueue (event loop) and the shipper (worker thread) would otherwise
        # collide in SQLite's busy-wait, which measured multi-second stalls.
        # One process-local lock keeps every wait to a few milliseconds.
        self.lock = threading.Lock()
        with self.connect() as db:
            db.executescript(SCHEMA)

    @contextmanager
    def connect(self):
        with self.lock, closing(sqlite3.connect(self.path, timeout=5)) as db, db:
            if self.wal:  # LOOP_OFFLOAD: cheaper commits; a crash may lose the last events, which the collector sees as a gap.
                db.execute("PRAGMA journal_mode=WAL")
                db.execute("PRAGMA synchronous=NORMAL")
            db.execute("BEGIN IMMEDIATE")
            yield db

    @staticmethod
    def _flag(db, run_id, reason):
        db.execute("UPDATE audit_state SET unavailable=1, reason=COALESCE(reason, ?) WHERE run_id=?", (reason, run_id))

    def enqueue(self, run_id, path, payload, enabled=True):
        """Returns the queued row id, or None when the run was flagged instead."""
        with self.connect() as db:
            db.execute("INSERT OR IGNORE INTO audit_state(run_id) VALUES (?)", (run_id,))
            if not enabled:
                self._flag(db, run_id, "collector not configured")
                return None
            if path == "/append":
                seq = db.execute("SELECT next_seq FROM audit_state WHERE run_id=?", (run_id,)).fetchone()[0]
                db.execute("UPDATE audit_state SET next_seq=next_seq+1 WHERE run_id=?", (run_id,))
                payload = dict(payload, gw_seq=seq)
            if db.execute("SELECT COUNT(*) FROM audit_outbox").fetchone()[0] >= self.max_entries:
                # The sequence number stays consumed, so the collector sees the gap too.
                self._flag(db, run_id, "queue full")
                return None
            return db.execute("INSERT INTO audit_outbox(run_id,path,payload) VALUES (?,?,?)",
                              (run_id, path, json.dumps(payload, separators=(",", ":")))).lastrowid

    def head(self, limit=1):
        with self.connect() as db:
            rows = db.execute("SELECT id,run_id,path,payload FROM audit_outbox ORDER BY id LIMIT ?", (limit,)).fetchall()
        return rows if limit > 1 else (rows[0] if rows else None)

    def ack(self, row_id):
        with self.connect() as db:
            db.execute("DELETE FROM audit_outbox WHERE id=?", (row_id,))

    def ack_many(self, row_ids):
        """One transaction for a delivered batch."""
        with self.connect() as db:
            db.executemany("DELETE FROM audit_outbox WHERE id=?", [(row_id,) for row_id in row_ids])

    def dead_letter(self, row_ids, reason):
        with self.connect() as db:
            for row_id in row_ids:
                row = db.execute("SELECT id,run_id,path,payload FROM audit_outbox WHERE id=?", (row_id,)).fetchone()
                if row:
                    db.execute("INSERT INTO audit_dead(id,run_id,path,payload,reason) VALUES (?,?,?,?,?)", (*row, reason))
                    db.execute("DELETE FROM audit_outbox WHERE id=?", (row_id,))
                    self._flag(db, row[1], reason)

    def failed(self, run_id):
        with self.connect() as db:
            row = db.execute("SELECT unavailable FROM audit_state WHERE run_id=?", (run_id,)).fetchone()
        return bool(row and row[0])

    def counts(self):
        with self.connect() as db:
            return {"pending": db.execute("SELECT COUNT(*) FROM audit_outbox").fetchone()[0],
                    "dead": db.execute("SELECT COUNT(*) FROM audit_dead").fetchone()[0],
                    "incomplete_runs": db.execute("SELECT COUNT(*) FROM audit_state WHERE unavailable=1").fetchone()[0]}
