"""
上下文隐藏：从 session JSONL 中移除指定消息，让小予下次 resume 时看不到。
支持恢复（unhide）。
"""

import json
import logging
import pathlib
from datetime import datetime, timedelta

from forge_reload import find_transcript_dir

HIDDEN_DIR = pathlib.Path(__file__).parent / "hidden_archive"
HIDDEN_DIR.mkdir(exist_ok=True)

logger = logging.getLogger(__name__)


def _parse_ts(ts_str: str) -> datetime | None:
    try:
        if ts_str.endswith("Z"):
            ts_str = ts_str[:-1] + "+00:00"
        return datetime.fromisoformat(ts_str)
    except Exception:
        return None


def _match_entry(entry: dict, target_ts: str, target_role: str,
                 tolerance_seconds: float = 10.0) -> bool:
    entry_type = entry.get("type")
    if target_role == "user" and entry_type != "user":
        return False
    if target_role == "assistant" and entry_type != "assistant":
        return False

    entry_ts = entry.get("timestamp", "")
    t1 = _parse_ts(entry_ts)
    t2 = _parse_ts(target_ts)
    if not t1 or not t2:
        return False
    return abs((t1 - t2).total_seconds()) < tolerance_seconds


def hide_messages(session_id: str, messages_to_hide: list[dict]) -> dict:
    """
    从 session JSONL 中移除指定消息。

    messages_to_hide: [{ timestamp, role, text_preview? }]
    返回: { success, removed_count, archive_id }
    """
    if not session_id:
        return {"success": False, "error": "没有活跃的 session"}

    try:
        transcript_dir = find_transcript_dir(session_id)
    except FileNotFoundError:
        return {"success": False, "error": f"找不到 session {session_id}"}

    jsonl_path = transcript_dir / f"{session_id}.jsonl"
    if not jsonl_path.exists():
        return {"success": False, "error": "session 文件不存在"}

    entries = []
    with open(jsonl_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    indices_to_remove = set()

    for target in messages_to_hide:
        ts = target.get("timestamp", "")
        role = target.get("role", "")

        for i, entry in enumerate(entries):
            if i in indices_to_remove:
                continue
            if _match_entry(entry, ts, role):
                indices_to_remove.add(i)
                msg_id = entry.get("message", {}).get("id")
                if msg_id and role == "assistant":
                    for j, other in enumerate(entries):
                        if j != i and other.get("message", {}).get("id") == msg_id:
                            indices_to_remove.add(j)
                break

    if not indices_to_remove:
        return {"success": True, "removed_count": 0, "message": "没有找到匹配的消息"}

    removed = [entries[i] for i in sorted(indices_to_remove)]
    kept = [entries[i] for i in range(len(entries)) if i not in indices_to_remove]

    prev_uuid = None
    for entry in kept:
        entry["parentUuid"] = prev_uuid
        prev_uuid = entry.get("uuid")

    archive_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    archive_path = HIDDEN_DIR / f"{session_id}_{archive_id}.jsonl"
    archive_meta = {
        "session_id": session_id,
        "archive_id": archive_id,
        "hidden_at": datetime.now().isoformat(),
        "removed_indices": sorted(indices_to_remove),
        "total_entries_before": len(entries),
    }
    with open(archive_path, "w", encoding="utf-8") as f:
        f.write(json.dumps(archive_meta, ensure_ascii=False) + "\n")
        for entry in removed:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    with open(jsonl_path, "w", encoding="utf-8") as f:
        for entry in kept:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    logger.info(f"context-hide: session {session_id}, 移除 {len(removed)} 条, archive={archive_id}")
    return {"success": True, "removed_count": len(removed), "archive_id": archive_id}


def unhide_messages(session_id: str, timestamps_to_restore: list[str]) -> dict:
    """
    从存档中恢复消息到 session JSONL。

    timestamps_to_restore: 要恢复的消息的 timestamp 列表
    """
    if not session_id:
        return {"success": False, "error": "没有活跃的 session"}

    archive_files = sorted(HIDDEN_DIR.glob(f"{session_id}_*.jsonl"), reverse=True)
    if not archive_files:
        return {"success": False, "error": "没有找到存档"}

    try:
        transcript_dir = find_transcript_dir(session_id)
    except FileNotFoundError:
        return {"success": False, "error": f"找不到 session {session_id}"}

    jsonl_path = transcript_dir / f"{session_id}.jsonl"

    entries_to_restore = []
    restore_timestamps = set(timestamps_to_restore)

    for af in archive_files:
        with open(af, encoding="utf-8") as f:
            lines = f.readlines()
        if len(lines) < 2:
            continue
        for line in lines[1:]:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            entry_ts = entry.get("timestamp", "")
            for target_ts in restore_timestamps:
                t1 = _parse_ts(entry_ts)
                t2 = _parse_ts(target_ts)
                if t1 and t2 and abs((t1 - t2).total_seconds()) < 10:
                    entries_to_restore.append(entry)
                    break

    if not entries_to_restore:
        return {"success": True, "restored_count": 0, "message": "没有找到匹配的存档消息"}

    current_entries = []
    if jsonl_path.exists():
        with open(jsonl_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    current_entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue

    all_entries = current_entries + entries_to_restore
    all_entries.sort(key=lambda e: _parse_ts(e.get("timestamp", "")) or datetime.min)

    prev_uuid = None
    for entry in all_entries:
        entry["parentUuid"] = prev_uuid
        prev_uuid = entry.get("uuid")

    with open(jsonl_path, "w", encoding="utf-8") as f:
        for entry in all_entries:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    logger.info(f"context-unhide: session {session_id}, 恢复 {len(entries_to_restore)} 条")
    return {"success": True, "restored_count": len(entries_to_restore)}
