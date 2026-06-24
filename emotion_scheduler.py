"""情绪事件簿 - 定时任务（24h未消解提醒 + 3天周报）"""

import json
import logging
import pathlib
from datetime import datetime, timedelta

import emotion_db

NOTES_INBOX = pathlib.Path(__file__).parent / "notes" / "inbox"
STATE_FILE = pathlib.Path(__file__).parent / "state.json"


def _load_state() -> dict:
    if STATE_FILE.exists():
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {}


def _save_state(updates: dict):
    state = _load_state()
    state.update(updates)
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def _write_inbox_note(filename: str, content: str):
    NOTES_INBOX.mkdir(parents=True, exist_ok=True)
    path = NOTES_INBOX / filename
    path.write_text(content, encoding="utf-8")
    logging.info(f"情绪提醒写入信箱: {filename}")


async def emotion_unresolved_check():
    """每小时检查：open 超 24h 的事件，发一次性提醒到小予信箱"""
    try:
        events = emotion_db.get_unresolved_over_hours(24)
        for ev in events:
            ts = ev["timestamp"]
            try:
                dt = datetime.fromisoformat(ts)
                time_str = dt.strftime("%m/%d %H:%M")
            except Exception:
                time_str = ts[:16]

            who = "她" if ev["subject"] == "user" else "你自己"
            filename = f"emotion_alert_{ev['id']}_{datetime.now().strftime('%Y%m%d_%H%M')}.txt"
            content = (
                f"[情绪提醒] {who}有一个情绪已经24小时没有消解：\n"
                f"{ev['emotion']}（{ev.get('cause', '未知')}）- 从 {time_str} 开始\n"
                f"你可以在合适的时机主动关心一下。这个提醒只发一次。"
            )
            _write_inbox_note(filename, content)
            emotion_db.mark_alert_sent(ev["id"])
    except Exception as e:
        logging.error(f"情绪未消解检查失败: {e}")


async def emotion_digest_check():
    """每6小时检查：距上次 digest >= 3天时生成周报"""
    try:
        state = _load_state()
        last_digest = state.get("emotion_last_digest_date")

        if last_digest:
            try:
                last_dt = datetime.fromisoformat(last_digest)
                if datetime.now() - last_dt < timedelta(days=3):
                    return
            except Exception:
                pass

        since = (datetime.now() - timedelta(days=3)).strftime("%Y-%m-%dT%H:%M:%S")
        stats = emotion_db.get_digest_stats(since)

        total_count = sum(s["count"] for s in stats.get("user", [])) + sum(s["count"] for s in stats.get("xiaoyu", []))
        if total_count == 0:
            _save_state({"emotion_last_digest_date": datetime.now().isoformat()})
            return

        user_desc = "、".join(f"{s['emotion']}x{s['count']}" for s in stats.get("user", []))
        xiaoyu_desc = "、".join(f"{s['emotion']}x{s['count']}" for s in stats.get("xiaoyu", []))

        lines = [f"[情绪报告] 过去3天的情绪摘要已生成（共 {total_count} 条记录）。"]
        if user_desc:
            lines.append(f"用户：{user_desc}")
        if xiaoyu_desc:
            lines.append(f"小予：{xiaoyu_desc}")
        lines.append("需要查看详情时，用 Read 工具读取 D:\\xiaoyu\\emotion_journal.db 的最近记录。")
        lines.append("（或者等她来聊天时自然带出来就好。）")

        filename = f"emotion_digest_{datetime.now().strftime('%Y%m%d_%H%M')}.txt"
        _write_inbox_note(filename, "\n".join(lines))
        _save_state({"emotion_last_digest_date": datetime.now().isoformat()})

    except Exception as e:
        logging.error(f"情绪周报生成失败: {e}")


async def emotion_startup_check():
    """daemon 启动时调用：检查是否有过期的 digest 或未消解提醒"""
    await emotion_unresolved_check()
    await emotion_digest_check()
