"""情绪事件簿 - SQLite 数据层"""

import sqlite3
import pathlib
from datetime import datetime, timedelta

DB_PATH = pathlib.Path(__file__).parent / "emotion_journal.db"


def _now_iso():
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


def _get_conn():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    conn = _get_conn()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS emotion_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            subject TEXT NOT NULL,
            emotion TEXT NOT NULL,
            intensity INTEGER NOT NULL,
            cause TEXT,
            source_excerpt TEXT,
            source_channel TEXT DEFAULT 'xiaoyu',
            state TEXT NOT NULL DEFAULT 'open',
            resolved_at TEXT,
            alert_sent INTEGER DEFAULT 0,
            scan_msg_index INTEGER,
            created_at TEXT NOT NULL,
            updated_at TEXT
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_emotion_state ON emotion_events(state)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_emotion_timestamp ON emotion_events(timestamp)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_emotion_subject ON emotion_events(subject)")
    conn.commit()
    conn.close()


def insert_event(event: dict) -> int:
    conn = _get_conn()
    now = _now_iso()
    cur = conn.execute("""
        INSERT INTO emotion_events
            (timestamp, subject, emotion, intensity, cause, source_excerpt,
             source_channel, state, scan_msg_index, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, 'open', ?, ?)
    """, (
        event["timestamp"], event["subject"], event["emotion"],
        event["intensity"], event.get("cause"), event.get("source_excerpt"),
        event.get("source_channel", "xiaoyu"), event.get("scan_msg_index"),
        now,
    ))
    conn.commit()
    event_id = cur.lastrowid
    conn.close()
    return event_id


def update_event(event_id: int, updates: dict) -> bool:
    allowed = {"emotion", "intensity", "cause", "state", "source_excerpt"}
    clean = {k: v for k, v in updates.items() if k in allowed}
    if not clean:
        return False
    clean["updated_at"] = _now_iso()
    if clean.get("state") in ("resolved", "dismissed"):
        clean["resolved_at"] = _now_iso()
    sets = ", ".join(f"{k} = ?" for k in clean)
    vals = list(clean.values()) + [event_id]
    conn = _get_conn()
    conn.execute(f"UPDATE emotion_events SET {sets} WHERE id = ?", vals)
    conn.commit()
    conn.close()
    return True


def dismiss_event(event_id: int) -> bool:
    return update_event(event_id, {"state": "dismissed"})


def resolve_event(event_id: int) -> bool:
    return update_event(event_id, {"state": "resolved"})


def get_open_events(subject: str = None) -> list[dict]:
    conn = _get_conn()
    if subject:
        rows = conn.execute(
            "SELECT * FROM emotion_events WHERE state = 'open' AND subject = ? ORDER BY timestamp DESC",
            (subject,)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM emotion_events WHERE state = 'open' ORDER BY timestamp DESC"
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_recent_events(days: int = 7) -> list[dict]:
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S")
    conn = _get_conn()
    rows = conn.execute(
        "SELECT * FROM emotion_events WHERE timestamp >= ? ORDER BY timestamp DESC",
        (cutoff,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_events_in_range(start_date: str, end_date: str) -> list[dict]:
    conn = _get_conn()
    rows = conn.execute(
        "SELECT * FROM emotion_events WHERE timestamp >= ? AND timestamp <= ? ORDER BY timestamp DESC",
        (start_date, end_date)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_summary(start_date: str, end_date: str) -> list[dict]:
    conn = _get_conn()
    rows = conn.execute("""
        SELECT subject, emotion, COUNT(*) as count, ROUND(AVG(intensity), 1) as avg_intensity
        FROM emotion_events
        WHERE timestamp >= ? AND timestamp <= ?
        GROUP BY subject, emotion
        ORDER BY count DESC
    """, (start_date, end_date)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_unresolved_over_hours(hours: int = 24) -> list[dict]:
    cutoff = (datetime.now() - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%S")
    conn = _get_conn()
    rows = conn.execute(
        "SELECT * FROM emotion_events WHERE state = 'open' AND alert_sent = 0 AND timestamp <= ? ORDER BY timestamp",
        (cutoff,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def mark_alert_sent(event_id: int):
    conn = _get_conn()
    conn.execute("UPDATE emotion_events SET alert_sent = 1 WHERE id = ?", (event_id,))
    conn.commit()
    conn.close()


def get_sanitized_memo() -> list[dict]:
    """小予可见的脱敏版：无 source_excerpt"""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT id, timestamp, subject, emotion, intensity, cause, state FROM emotion_events WHERE state = 'open' ORDER BY timestamp DESC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_digest_stats(since_date: str) -> dict:
    conn = _get_conn()
    rows = conn.execute("""
        SELECT subject, emotion, COUNT(*) as count
        FROM emotion_events
        WHERE timestamp >= ?
        GROUP BY subject, emotion
        ORDER BY count DESC
    """, (since_date,)).fetchall()
    conn.close()
    user_stats = []
    xiaoyu_stats = []
    for r in rows:
        item = {"emotion": r["emotion"], "count": r["count"]}
        if r["subject"] == "user":
            user_stats.append(item)
        else:
            xiaoyu_stats.append(item)
    return {"user": user_stats, "xiaoyu": xiaoyu_stats}


init_db()
