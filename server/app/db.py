"""SQLite persistence. Receipts are append-only (hash-chained, UPDATE/DELETE blocked by triggers)."""
import hashlib
import json
import sqlite3
import time
import uuid
from contextlib import contextmanager
from typing import Any, Optional

from . import config, crypto

SCHEMA = """
CREATE TABLE IF NOT EXISTS profiles (
    id TEXT PRIMARY KEY,
    ciphertext BLOB NOT NULL,
    created_at REAL NOT NULL,
    wipe_after REAL
);
CREATE TABLE IF NOT EXISTS audits (
    id TEXT PRIMARY KEY,
    created_at REAL NOT NULL,
    profile_id TEXT,
    inputs TEXT NOT NULL,
    result TEXT,
    status TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    audit_id TEXT NOT NULL,
    profile_id TEXT,
    playbook_id TEXT NOT NULL,
    status TEXT NOT NULL,
    state TEXT NOT NULL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS receipts (
    id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL UNIQUE,
    audit_id TEXT NOT NULL,
    tracking_code TEXT NOT NULL,
    pdf_path TEXT,
    payload TEXT NOT NULL,
    created_at REAL NOT NULL,
    prev_hash TEXT NOT NULL,
    record_hash TEXT NOT NULL
);
CREATE TRIGGER IF NOT EXISTS receipts_no_update BEFORE UPDATE ON receipts
BEGIN SELECT RAISE(ABORT, 'receipts are immutable'); END;
CREATE TRIGGER IF NOT EXISTS receipts_no_delete BEFORE DELETE ON receipts
BEGIN SELECT RAISE(ABORT, 'receipts are immutable'); END;
"""


@contextmanager
def connect():
    conn = sqlite3.connect(config.DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init() -> None:
    with connect() as c:
        c.execute("PRAGMA journal_mode=WAL")      # concurrent agent threads + API requests
        c.executescript(SCHEMA)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


# ---------- profiles (encrypted) ----------
def save_profile(profile: dict) -> str:
    pid = new_id("prf")
    with connect() as c:
        c.execute("INSERT INTO profiles VALUES (?,?,?,NULL)", (pid, crypto.encrypt_json(profile), time.time()))
    return pid


def load_profile(pid: Optional[str]) -> Optional[dict]:
    if not pid:
        return None
    with connect() as c:
        row = c.execute("SELECT ciphertext FROM profiles WHERE id=?", (pid,)).fetchone()
    return crypto.decrypt_json(row["ciphertext"]) if row else None


def update_profile(pid: str, profile: dict) -> None:
    with connect() as c:
        c.execute("UPDATE profiles SET ciphertext=? WHERE id=?", (crypto.encrypt_json(profile), pid))


def schedule_profile_wipe(pid: Optional[str]) -> None:
    if pid:
        with connect() as c:
            c.execute("UPDATE profiles SET wipe_after=? WHERE id=? AND wipe_after IS NULL",
                      (time.time() + config.RETENTION_HOURS * 3600, pid))


def purge_expired_profiles() -> int:
    with connect() as c:
        cur = c.execute("DELETE FROM profiles WHERE wipe_after IS NOT NULL AND wipe_after <= ?", (time.time(),))
        return cur.rowcount


# ---------- audits ----------
def create_audit(inputs: dict, profile_id: Optional[str]) -> str:
    aid = new_id("aud")
    with connect() as c:
        c.execute("INSERT INTO audits VALUES (?,?,?,?,NULL,?)",
                  (aid, time.time(), profile_id, json.dumps(inputs), "ingested"))
    return aid


def set_audit_result(aid: str, result: dict, status: str) -> None:
    with connect() as c:
        c.execute("UPDATE audits SET result=?, status=? WHERE id=?", (json.dumps(result), status, aid))


def get_audit(aid: str) -> Optional[dict]:
    with connect() as c:
        row = c.execute("SELECT * FROM audits WHERE id=?", (aid,)).fetchone()
    return _audit_row(row) if row else None


def list_audits(limit: int = 50) -> list[dict]:
    with connect() as c:
        rows = c.execute("SELECT * FROM audits ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
    return [_audit_row(r) for r in rows]


def delete_audit(aid: str) -> None:
    """Remove an internal warm-up audit so the public console only shows real visitors' checks."""
    with connect() as c:
        c.execute("DELETE FROM audits WHERE id=?", (aid,))


def _audit_row(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"], "created_at": row["created_at"], "profile_id": row["profile_id"],
        "inputs": json.loads(row["inputs"]), "result": json.loads(row["result"]) if row["result"] else None,
        "status": row["status"],
    }


# ---------- tasks ----------
def save_task(task: dict) -> None:
    with connect() as c:
        c.execute(
            """INSERT INTO tasks VALUES (?,?,?,?,?,?,?,?)
               ON CONFLICT(id) DO UPDATE SET status=excluded.status, state=excluded.state,
               updated_at=excluded.updated_at""",
            (task["id"], task["audit_id"], task.get("profile_id"), task["playbook_id"], task["status"],
             json.dumps(task), task["created_at"], time.time()),
        )


def get_task(tid: str) -> Optional[dict]:
    with connect() as c:
        row = c.execute("SELECT state FROM tasks WHERE id=?", (tid,)).fetchone()
    return json.loads(row["state"]) if row else None


def list_tasks(limit: int = 50) -> list[dict]:
    with connect() as c:
        rows = c.execute("SELECT state FROM tasks ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
    return [json.loads(r["state"]) for r in rows]


# ---------- receipts (append-only, hash chained) ----------
def add_receipt(task_id: str, audit_id: str, tracking_code: str, pdf_path: Optional[str], payload: dict) -> dict:
    existing = get_receipt(task_id)
    if existing:
        return existing
    with connect() as c:
        last = c.execute("SELECT record_hash FROM receipts ORDER BY created_at DESC LIMIT 1").fetchone()
        prev_hash = last["record_hash"] if last else "GENESIS"
        created = time.time()
        body = json.dumps({"task_id": task_id, "audit_id": audit_id, "tracking_code": tracking_code,
                           "payload": payload, "created_at": created, "prev_hash": prev_hash}, sort_keys=True)
        record_hash = hashlib.sha256(body.encode()).hexdigest()
        rid = new_id("rcp")
        c.execute("INSERT INTO receipts VALUES (?,?,?,?,?,?,?,?,?)",
                  (rid, task_id, audit_id, tracking_code, pdf_path, json.dumps(payload), created, prev_hash, record_hash))
    return get_receipt(task_id)


def get_receipt(task_id: str) -> Optional[dict]:
    with connect() as c:
        row = c.execute("SELECT * FROM receipts WHERE task_id=?", (task_id,)).fetchone()
    if not row:
        return None
    d = dict(row)
    d["payload"] = json.loads(d["payload"])
    return d


def verify_receipt_chain() -> bool:
    with connect() as c:
        rows = c.execute("SELECT * FROM receipts ORDER BY created_at ASC").fetchall()
    prev = "GENESIS"
    for r in rows:
        body = json.dumps({"task_id": r["task_id"], "audit_id": r["audit_id"], "tracking_code": r["tracking_code"],
                           "payload": json.loads(r["payload"]), "created_at": r["created_at"],
                           "prev_hash": r["prev_hash"]}, sort_keys=True)
        if r["prev_hash"] != prev or hashlib.sha256(body.encode()).hexdigest() != r["record_hash"]:
            return False
        prev = r["record_hash"]
    return True
