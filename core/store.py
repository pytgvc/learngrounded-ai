"""SQLite storage: knowledge base chunks, questions, attempts, chat history
and per-topic mastery. Built into Python, nothing extra to install."""
import json
import sqlite3
import time
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "learngrounded.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS chunks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT, kind TEXT, location TEXT, text TEXT, topic TEXT
);
CREATE TABLE IF NOT EXISTS questions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    qtype TEXT, prompt TEXT, options TEXT, answer TEXT, explanation TEXT,
    topic TEXT, source TEXT, location TEXT, chunk_id INTEGER,
    difficulty TEXT, fingerprint TEXT UNIQUE, verified INTEGER
);
CREATE TABLE IF NOT EXISTS attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    question_id INTEGER, topic TEXT, correct INTEGER, given TEXT,
    mode TEXT, ts REAL
);
CREATE TABLE IF NOT EXISTS mastery (
    topic TEXT PRIMARY KEY, p_known REAL, attempts INTEGER, correct INTEGER,
    last_seen REAL
);
CREATE TABLE IF NOT EXISTS chat (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    role TEXT, content TEXT, citations TEXT, mode TEXT, ts REAL
);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    full_name TEXT NOT NULL,
    username TEXT NOT NULL UNIQUE COLLATE NOCASE,
    email TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password_hash TEXT NOT NULL,
    created REAL
);
CREATE TABLE IF NOT EXISTS figures (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT, location TEXT, section TEXT, mime TEXT, path TEXT UNIQUE,
    status TEXT, description TEXT, chunk_id INTEGER
);
"""


def connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    return con


def get_meta(key, default=None):
    with connect() as con:
        row = con.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return json.loads(row["value"]) if row else default


def set_meta(key, value):
    with connect() as con:
        con.execute("INSERT OR REPLACE INTO meta(key,value) VALUES(?,?)",
                    (key, json.dumps(value)))


def insert_chunks(chunks):
    """Stores chunks and returns their new database ids, in order."""
    ids = []
    with connect() as con:
        for c in chunks:
            cur = con.execute(
                "INSERT INTO chunks(source,kind,location,text,topic) VALUES(?,?,?,?,?)",
                (c["source"], c["kind"], c["location"], c["text"], c.get("topic") or "General"))
            ids.append(cur.lastrowid)
    return ids


def all_chunks():
    with connect() as con:
        return [dict(r) for r in con.execute("SELECT * FROM chunks ORDER BY id")]


def get_chunk(chunk_id):
    with connect() as con:
        row = con.execute("SELECT * FROM chunks WHERE id=?", (chunk_id,)).fetchone()
        return dict(row) if row else None


def reset_all():
    with connect() as con:
        for t in ["chunks", "questions", "attempts", "mastery", "chat", "meta", "figures"]:
            con.execute(f"DELETE FROM {t}")


def add_chat(role, content, citations=None, mode="grounded"):
    with connect() as con:
        con.execute("INSERT INTO chat(role,content,citations,mode,ts) VALUES(?,?,?,?,?)",
                    (role, content, json.dumps(citations or []), mode, time.time()))


def recent_chat(limit=50):
    with connect() as con:
        rows = con.execute("SELECT * FROM chat ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        out = [dict(r) for r in reversed(rows)]
        for r in out:
            r["citations"] = json.loads(r["citations"] or "[]")
        return out
