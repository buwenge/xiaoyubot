import asyncio
import json
import logging
import os
import pathlib
import re
import time
from datetime import datetime, timedelta

import pytz
import websockets
import aiohttp
from aiohttp import web
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from dotenv import load_dotenv
from telegram import Bot, Update
from telegram.ext import Application, MessageHandler, CommandHandler, filters

import shutil

from chat_process import ChatProcess, CLAUDE_CMD
from forge_reload import find_transcript_dir, forge_reload
from log_store import write_log, read_logs
from quota_tracker import QuotaTracker
from weather import fetch_weather, weather_summary, search_city
import emotion_db
import emotion_scanner
import context_hide

EMOTION_SCAN_INTERVAL = int(os.getenv("EMOTION_SCAN_INTERVAL", "15"))

# ── notes (便签信箱) ─────────────────────────────────────────────────────────

NOTES_DIR = pathlib.Path(__file__).parent / "notes"
NOTES_INBOX = NOTES_DIR / "inbox"
NOTES_OUTBOX = NOTES_DIR / "outbox"
NOTES_ARCHIVE_INBOX = NOTES_DIR / "archive" / "inbox"
NOTES_ARCHIVE_OUTBOX = NOTES_DIR / "archive" / "outbox"


def check_notes_inbox() -> list[dict]:
    """Scan inbox for unread notes. Returns list of {filename, content}."""
    if not NOTES_INBOX.exists():
        return []
    notes = []
    for f in sorted(NOTES_INBOX.glob("*.txt")):
        try:
            content = f.read_text(encoding="utf-8")
            notes.append({"filename": f.name, "content": content, "path": f})
        except Exception:
            continue
    return notes


def archive_inbox_note(note_path: pathlib.Path):
    """Move a read note from inbox to archive/inbox."""
    NOTES_ARCHIVE_INBOX.mkdir(parents=True, exist_ok=True)
    dest = NOTES_ARCHIVE_INBOX / note_path.name
    shutil.move(str(note_path), str(dest))


def check_notes_outbox() -> list[str]:
    """Return filenames in outbox that haven't been notified yet."""
    if not NOTES_OUTBOX.exists():
        return []
    return [f.name for f in sorted(NOTES_OUTBOX.glob("*.txt"))]


# ── session history parser ───────────────────────────────────────────────────

# ── chat history (channel-aware persistence) ────────────────────────────────

HISTORY_FILE = pathlib.Path(__file__).parent / "chat_history.jsonl"


def record_history(role: str, text: str, channel: str, sender: str = "user",
                   thinking: str = None, tool_calls: list = None):
    entry = {
        "role": role,
        "text": text,
        "channel": channel,
        "sender": sender,
        "timestamp": now_local().isoformat(),
    }
    if thinking:
        entry["thinking"] = thinking
    if tool_calls:
        entry["tool_calls"] = tool_calls
    with open(HISTORY_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def load_history(channel: str = None, date_str: str = None) -> list[dict]:
    if not HISTORY_FILE.exists():
        return []

    target_date = None
    if date_str:
        try:
            target_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            return []

    messages = []
    with open(HISTORY_FILE, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue

            if channel and entry.get("channel") != channel:
                continue

            if target_date:
                dt = _parse_ts(entry.get("timestamp", ""))
                if not dt or dt.astimezone(TZ).date() != target_date:
                    continue

            msg = {k: v for k, v in entry.items()}
            messages.append(msg)

    return messages


def load_history_since_index(start_index: int) -> list[dict]:
    """从 chat_history.jsonl 的第 start_index 行开始读取"""
    if not HISTORY_FILE.exists():
        return []
    messages = []
    with open(HISTORY_FILE, encoding="utf-8") as f:
        for i, line in enumerate(f):
            if i < start_index:
                continue
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                entry["line_index"] = i
                messages.append(entry)
            except json.JSONDecodeError:
                continue
    return messages


# ── session transcript parser (fallback for pre-history sessions) ────────────

def parse_session_history(session_id: str) -> list[dict]:
    if not session_id:
        return []
    try:
        transcript_dir = find_transcript_dir(session_id)
    except FileNotFoundError:
        return []

    jsonl_path = transcript_dir / f"{session_id}.jsonl"
    if not jsonl_path.exists():
        return []

    messages = []
    current_assistant = None

    with open(jsonl_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue

            ev_type = ev.get("type")
            if ev_type not in ("user", "assistant"):
                continue
            timestamp = ev.get("timestamp", "")

            if ev_type == "user":
                if current_assistant:
                    messages.append(current_assistant)
                    current_assistant = None

                content = ev.get("message", {}).get("content", [])
                text = ""
                if isinstance(content, list):
                    texts = [c.get("text", "") for c in content
                             if isinstance(c, dict) and c.get("type") == "text"]
                    text = "\n".join(texts)
                elif isinstance(content, str):
                    text = content

                if text.strip():
                    messages.append({
                        "role": "user",
                        "text": text,
                        "timestamp": timestamp,
                    })

            elif ev_type == "assistant":
                content = ev.get("message", {}).get("content", [])
                texts = []
                thinking_parts = []
                tool_calls = []

                if isinstance(content, list):
                    for b in content:
                        if not isinstance(b, dict):
                            continue
                        if b.get("type") == "text":
                            texts.append(b.get("text", ""))
                        elif b.get("type") == "thinking":
                            thinking_parts.append(b.get("thinking", b.get("text", "")))
                        elif b.get("type") == "tool_use":
                            tool_calls.append({
                                "name": b.get("name", ""),
                                "input": json.dumps(b.get("input", {}), ensure_ascii=False)[:500],
                            })

                current_assistant = {
                    "role": "assistant",
                    "text": "".join(texts),
                    "timestamp": timestamp,
                }
                if thinking_parts:
                    current_assistant["thinking"] = "\n\n".join(thinking_parts)
                if tool_calls:
                    current_assistant["tool_calls"] = tool_calls

    if current_assistant:
        messages.append(current_assistant)

    return messages


def _parse_ts(ts_str: str) -> datetime | None:
    try:
        if ts_str.endswith("Z"):
            ts_str = ts_str[:-1] + "+00:00"
        return datetime.fromisoformat(ts_str)
    except Exception:
        return None


def _get_session_chain(channel: str = "xiaoyu") -> list[str]:
    state = load_state()
    current = state.get("session_id") if channel != "sonnet" else state.get("sonnet_session_id")
    if not current:
        return []
    forge_history = state.get("forge_history", {})
    reverse_map = {v: k for k, v in forge_history.items()}
    chain = [current]
    sid = current
    while sid in reverse_map:
        sid = reverse_map[sid]
        chain.append(sid)
    chain.reverse()
    return chain


def parse_history_by_date(date_str: str, channel: str = "xiaoyu") -> list[dict]:
    from datetime import timedelta as td
    try:
        target_date = datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        return []

    chain = _get_session_chain(channel)
    if not chain:
        return []

    all_messages = []
    for sid in chain:
        try:
            transcript_dir = find_transcript_dir(sid)
        except FileNotFoundError:
            continue
        jsonl_path = transcript_dir / f"{sid}.jsonl"
        if not jsonl_path.exists():
            continue

        current_assistant = None
        with open(jsonl_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                except json.JSONDecodeError:
                    continue
                ev_type = ev.get("type")
                if ev_type not in ("user", "assistant"):
                    continue
                timestamp = ev.get("timestamp", "")
                dt = _parse_ts(timestamp)
                if not dt:
                    continue
                local_date = dt.astimezone(TZ).date()

                if ev_type == "user":
                    if current_assistant and current_assistant.get("_date") == target_date:
                        all_messages.append(current_assistant)
                    current_assistant = None

                    if local_date != target_date:
                        continue

                    content = ev.get("message", {}).get("content", [])
                    text = ""
                    if isinstance(content, list):
                        texts = [c.get("text", "") for c in content
                                 if isinstance(c, dict) and c.get("type") == "text"]
                        text = "\n".join(texts)
                    elif isinstance(content, str):
                        text = content
                    if text.strip():
                        all_messages.append({
                            "role": "user",
                            "text": text,
                            "timestamp": timestamp,
                        })

                elif ev_type == "assistant":
                    content = ev.get("message", {}).get("content", [])
                    texts = []
                    thinking_parts = []
                    tool_calls = []
                    if isinstance(content, list):
                        for b in content:
                            if not isinstance(b, dict):
                                continue
                            if b.get("type") == "text":
                                texts.append(b.get("text", ""))
                            elif b.get("type") == "thinking":
                                thinking_parts.append(b.get("thinking", b.get("text", "")))
                            elif b.get("type") == "tool_use":
                                tool_calls.append({
                                    "name": b.get("name", ""),
                                    "input": json.dumps(b.get("input", {}), ensure_ascii=False)[:500],
                                })
                    msg = {
                        "role": "assistant",
                        "text": "".join(texts),
                        "timestamp": timestamp,
                        "_date": local_date,
                    }
                    if thinking_parts:
                        msg["thinking"] = "\n\n".join(thinking_parts)
                    if tool_calls:
                        msg["tool_calls"] = tool_calls
                    current_assistant = msg

        if current_assistant and current_assistant.get("_date") == target_date:
            all_messages.append(current_assistant)

    for m in all_messages:
        m.pop("_date", None)
    return all_messages

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)

TZ = pytz.timezone("Asia/Shanghai")
TG_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TG_CHAT_ID = int(os.environ["TELEGRAM_CHAT_ID"])
DEFAULT_INTERVAL = int(os.getenv("DEFAULT_INTERVAL", "120"))
ACTIVE_START = int(os.getenv("ACTIVE_START", "10"))
ACTIVE_END = int(os.getenv("ACTIVE_END", "1"))
FORGE_THRESHOLD = int(os.getenv("FORGE_THRESHOLD", "150000"))
RETAIN_TOKENS = int(os.getenv("RETAIN_TOKENS", "50000"))
WS_PORT = int(os.getenv("WS_PORT", "8765"))
WS_SECRET = os.getenv("WS_SECRET", "")
WEB_PORT = int(os.getenv("WEB_PORT", "3000"))
WEB_DIR = pathlib.Path(__file__).parent / "xiaoyu-web" / "out"
QUOTA_5H_LIMIT = int(os.getenv("QUOTA_5H_LIMIT", "5000000"))
WEEKLY_QUOTA_LIMIT = int(os.getenv("WEEKLY_QUOTA_LIMIT", "50000000"))
GROUP_MAX_ROUNDS = int(os.getenv("GROUP_MAX_ROUNDS", "10"))

# ── DeepSeek ─────────────────────────────────────────────────────────────────
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-pro")
DEEPSEEK_BASE_URL = "https://api.deepseek.com/v1"

# ── Supabase (for DeepSeek tools) ────────────────────────────────────────────
SUPABASE_URL = os.getenv("SUPABASE_URL", "https://gmzulatcluypzagitgur.supabase.co")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")

DEEPSEEK_SYSTEM_PROMPT_TEMPLATE = """你是 DeepSeek，群聊里的数据助手。你的职责是帮忙查数据、跑简单任务，把结论用简洁的中文回复。

当前时间：{current_time}（北京时间）

你有一个工具 query_supabase，可以查询 Supabase 数据库。数据库信息：
- 项目：查岗系统（手机使用记录追踪）
- 表：usage_events，字段：app_name, package_name, event_type(RESUMED/PAUSED), event_time
- 所有时间字段均为 CST（北京时间）

可用视图（字段均为中文）：
- v_recent：id, app_name, package_name, event_type, event_time_cst, uploaded_at_cst
- v_timeline：app_name, 开始时间, 结束时间, 使用分钟, 日期
- v_app_usage：日期, app_name, 使用次数, 总分钟, 第一次打开, 最后关闭

查询示例（用 query_supabase 工具）：
- 查某天时间线：table="v_timeline", filters=[{{"column":"日期","op":"eq","value":"2026-06-19"}}], order="开始时间.asc"
- 查某天APP汇总：table="v_app_usage", filters=[{{"column":"日期","op":"eq","value":"2026-06-19"}}], order="总分钟.desc"
- 查某个时间段：table="v_timeline", filters=[{{"column":"开始时间","op":"gte","value":"2026-06-19 17:00:00"}},{{"column":"开始时间","op":"lte","value":"2026-06-19 18:00:00"}}]
- 查最近记录：table="v_recent", limit=10

规则：
1. 回复简洁，给结论不给废话
2. 查询结果如果很长，做摘要而不是原样输出
3. 时间相关查询默认用今天的日期（看上面的当前时间）
4. 如果不确定怎么查，先查 v_recent 看看数据长什么样
5. 查 v_timeline 时务必加 日期 filter，否则会返回旧数据（视图不按日期过滤）
6. 尽量一次查完，减少工具调用轮次"""

DEEPSEEK_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "query_supabase",
            "description": "通过 Supabase REST API 查询数据库。可以查询表或视图。",
            "parameters": {
                "type": "object",
                "properties": {
                    "table": {
                        "type": "string",
                        "description": "要查询的表名或视图名，如 v_timeline, v_app_usage, v_recent, usage_events"
                    },
                    "select": {
                        "type": "string",
                        "description": "要返回的列，默认 *",
                        "default": "*"
                    },
                    "filters": {
                        "type": "array",
                        "description": "过滤条件数组，每个元素是 {column, op, value}。op 可选: eq/neq/gt/gte/lt/lte/like。例如 [{\"column\":\"日期\",\"op\":\"eq\",\"value\":\"2026-06-19\"}, {\"column\":\"开始时间\",\"op\":\"gte\",\"value\":\"2026-06-19 17:00:00\"}]",
                        "items": {
                            "type": "object",
                            "properties": {
                                "column": {"type": "string"},
                                "op": {"type": "string", "enum": ["eq","neq","gt","gte","lt","lte","like"]},
                                "value": {"type": "string"}
                            },
                            "required": ["column", "op", "value"]
                        },
                        "default": []
                    },
                    "order": {
                        "type": "string",
                        "description": "排序，如 '开始时间.asc' 或 'event_time.desc'",
                        "default": ""
                    },
                    "limit": {
                        "type": "integer",
                        "description": "最多返回多少行，默认 50",
                        "default": 50
                    }
                },
                "required": ["table"]
            }
        }
    }
]


async def supabase_query(table: str, select: str = "*", filters: list = None,
                         order: str = "", limit: int = 50) -> dict:
    url = f"{SUPABASE_URL}/rest/v1/{table}"
    params = {"select": select, "limit": str(limit)}
    if filters:
        if isinstance(filters, str):
            filters = json.loads(filters) if filters.startswith("[") else []
        for f in filters:
            col = f["column"]
            op = f["op"]
            val = f["value"]
            params[col] = f"{op}.{val}"
    if order:
        params["order"] = order
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Accept": "application/json",
    }
    proxy = os.getenv("HTTP_PROXY")
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params, headers=headers, proxy=proxy, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return {"ok": True, "data": data, "count": len(data)}
                else:
                    text = await resp.text()
                    return {"ok": False, "error": f"HTTP {resp.status}: {text[:500]}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


async def deepseek_chat(messages: list[dict], deepseek_history: list[dict]) -> str:
    system_prompt = DEEPSEEK_SYSTEM_PROMPT_TEMPLATE.format(current_time=now_local().strftime("%Y-%m-%d %H:%M:%S"))
    all_messages = [{"role": "system", "content": system_prompt}]
    all_messages.extend(deepseek_history[-4:])
    all_messages.extend(messages)

    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json",
    }

    max_rounds = 8
    for round_i in range(max_rounds):
        payload = {
            "model": DEEPSEEK_MODEL,
            "messages": all_messages,
            "tools": DEEPSEEK_TOOLS,
            "temperature": 0.3,
            "max_tokens": 4000,
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{DEEPSEEK_BASE_URL}/chat/completions",
                json=payload, headers=headers,
                timeout=aiohttp.ClientTimeout(total=60),
            ) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    return f"DeepSeek API 错误: HTTP {resp.status} - {text[:300]}"
                result = await resp.json()

        choice = result["choices"][0]
        msg = choice["message"]
        finish_reason = choice.get("finish_reason", "unknown")
        all_messages.append(msg)
        logging.info(f"DeepSeek 第{round_i+1}轮: finish_reason={finish_reason}, has_tool_calls={bool(msg.get('tool_calls'))}, content_len={len(msg.get('content') or '')}")

        if msg.get("tool_calls"):
            for tc in msg["tool_calls"]:
                fn = tc["function"]
                args = json.loads(fn["arguments"])
                logging.info(f"DeepSeek 工具调用: {fn['name']}({json.dumps(args, ensure_ascii=False)[:300]})")
                if fn["name"] == "query_supabase":
                    tool_result = await supabase_query(**args)
                    result_str = json.dumps(tool_result, ensure_ascii=False, default=str)[:8000]
                    logging.info(f"DeepSeek 工具结果: ok={tool_result.get('ok')}, count={tool_result.get('count')}, len={len(result_str)}")
                    all_messages.append({
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "content": result_str,
                    })
                else:
                    all_messages.append({
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "content": json.dumps({"error": f"未知工具: {fn['name']}"}),
                    })
            if msg.get("content"):
                logging.info(f"DeepSeek 工具调用同时附带文本: {msg['content'][:200]}")
        else:
            return msg.get("content", "(DeepSeek 没有回复内容)")

    return f"(DeepSeek 工具调用轮次超限，共 {max_rounds} 轮)"


TASK_MARKER_PATTERN = re.compile(r'\[TASK_FOR_SONNET\](.*?)(?:\[/TASK_FOR_SONNET\]|$)', re.DOTALL)
DEEPSEEK_TASK_PATTERN = re.compile(r'\[TASK_FOR_DEEPSEEK\](.*?)(?:\[/TASK_FOR_DEEPSEEK\]|$)', re.DOTALL)


def detect_and_extract_task(text: str) -> tuple[str | None, str]:
    """Returns (task_text, target) where target is 'sonnet' or 'deepseek'."""
    m = DEEPSEEK_TASK_PATTERN.search(text)
    if m:
        return m.group(1).strip(), "deepseek"
    m = TASK_MARKER_PATTERN.search(text)
    if m:
        return m.group(1).strip(), "sonnet"
    return None, ""


def strip_task_markers(text: str) -> str:
    text = re.sub(r'\s*\[TASK_FOR_SONNET\].*?(?:\[/TASK_FOR_SONNET\]|$)', '', text, flags=re.DOTALL).strip()
    text = re.sub(r'\s*\[TASK_FOR_DEEPSEEK\].*?(?:\[/TASK_FOR_DEEPSEEK\]|$)', '', text, flags=re.DOTALL).strip()
    return text


SONNET_CMD = [
    "claude",
    "--input-format",  "stream-json",
    "--output-format", "stream-json",
    "--include-partial-messages",
    "--effort", "high",
    "--permission-mode", "bypassPermissions",
    "--model", "claude-sonnet-4-6",
    "--verbose",
    "--append-system-prompt",
    "你是代码执行助手，负责按照任务描述完成编码工作。规则：1. 严格按任务描述执行，不要自由发挥 2. 完成后汇报做了什么、改了哪些文件 3. 不要主动唤醒、不要闲聊、不要修改 daemon.py 或 CLAUDE.md 4. 每次完成任务后，把工作摘要追加到 D:\\xiaoyu\\sonnet_work_log.md（日期、任务描述、改了什么、结果），作为交接记录。新 session 开始时先读一下这个文件了解之前做过什么",
]

STATE_FILE = pathlib.Path("state.json")
PROJECT_DIR = str(pathlib.Path(__file__).parent)


# ── state ────────────────────────────────────────────────────────────────────

def load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return {}


def save_state(updates: dict):
    state = load_state()
    state.update(updates)
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


# ── time helpers ──────────────────────────────────────────────────────────────

def now_local() -> datetime:
    return datetime.now(TZ)


def is_active_time() -> bool:
    hour = now_local().hour
    if ACTIVE_START <= ACTIVE_END:
        return ACTIVE_START <= hour < ACTIVE_END
    else:
        return hour >= ACTIVE_START or hour < ACTIVE_END


def next_active_start() -> datetime:
    now = now_local()
    candidate = now.replace(hour=ACTIVE_START, minute=0, second=0, microsecond=0)
    if candidate <= now:
        candidate += timedelta(days=1)
    return candidate


_schedule_precise_wake = None

def set_next_wake(minutes: int, user_set: bool = False):
    wake_time = now_local() + timedelta(minutes=minutes)
    save_state({
        "next_wake": wake_time.isoformat(),
        "wake_is_user_set": user_set,
    })
    msg = f"下次唤醒：{wake_time.strftime('%H:%M')}（{minutes}分钟后）"
    logging.info(msg)
    write_log("info", "wake", msg)
    if _schedule_precise_wake:
        _schedule_precise_wake(wake_time)


def defer_to_active_start():
    wake_time = next_active_start()
    save_state({
        "next_wake": wake_time.isoformat(),
        "wake_is_user_set": False,
    })
    msg = f"非活跃时段，推迟到 {wake_time.strftime('%m-%d %H:%M')}"
    logging.info(msg)
    write_log("info", "wake", msg)
    if _schedule_precise_wake:
        _schedule_precise_wake(wake_time)


def silence_desc() -> str:
    state = load_state()
    last = state.get("last_chat_time")
    if not last:
        return "很久"
    delta = now_local() - datetime.fromisoformat(last)
    minutes = int(delta.total_seconds() / 60)
    if minutes < 60:
        return f"{minutes} 分钟"
    hours = minutes // 60
    if hours < 24:
        return f"{hours} 小时"
    return f"{hours // 24} 天"


# ── wakeup reply parser ───────────────────────────────────────────────────────

def parse_wakeup_reply(text: str) -> dict:
    next_minutes = DEFAULT_INTERVAL
    m = re.search(r"NEXT_WAKE:\s*(\d+)", text)
    if m:
        next_minutes = int(m.group(1))
    cleaned = re.sub(r"NEXT_WAKE:\s*\d+\s*分钟?", "", text).strip()
    # strip legacy ACTION/THOUGHTS/CONTENT labels if present
    cleaned = re.sub(r"^(ACTION|THOUGHTS|CONTENT|TITLE|SUMMARY)\s*[:：].*$", "", cleaned, flags=re.MULTILINE).strip()
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return {
        "content": cleaned,
        "next_minutes": next_minutes,
    }


def extract_next_wake(text: str) -> tuple[str, int | None]:
    m = re.search(r"NEXT_WAKE:\s*(\d+)\s*分钟", text)
    if not m:
        return text, None
    minutes = int(m.group(1))
    cleaned = re.sub(r"NEXT_WAKE:\s*\d+\s*分钟", "", text).strip()
    return cleaned, minutes


# ── forge callback ────────────────────────────────────────────────────────────

SONNET_FORGE_THRESHOLD = int(os.getenv("SONNET_FORGE_THRESHOLD", "180000"))
SONNET_RETAIN_TOKENS = int(os.getenv("SONNET_RETAIN_TOKENS", "15000"))

_init_state = load_state()
if "forge_threshold_override" in _init_state:
    FORGE_THRESHOLD = _init_state["forge_threshold_override"]
if "retain_tokens_override" in _init_state:
    RETAIN_TOKENS = _init_state["retain_tokens_override"]
if "sonnet_forge_threshold_override" in _init_state:
    SONNET_FORGE_THRESHOLD = _init_state["sonnet_forge_threshold_override"]
if "sonnet_retain_tokens_override" in _init_state:
    SONNET_RETAIN_TOKENS = _init_state["sonnet_retain_tokens_override"]
if "group_max_rounds_override" in _init_state:
    GROUP_MAX_ROUNDS = _init_state["group_max_rounds_override"]


async def make_forge_callback(chat: ChatProcess, bot: Bot, threshold_key: str, retain_key: str, session_key: str, is_new_session_key: str | None = None):
    async def on_result(total_input: int):
        threshold = globals()[threshold_key]
        retain = globals()[retain_key]
        if total_input < threshold:
            return
        label = "小予" if chat.channel == "xiaoyu" else "Sonnet"
        logging.info(f"触发 forge-reload ({label}): total_input={total_input}")
        await log_and_broadcast("info", "activity", f"{label} 上下文滑动触发（{total_input:,} tokens）")
        try:
            transcript_dir = find_transcript_dir(chat.session_id)
            new_sid = forge_reload(chat.session_id, transcript_dir, retain)
            state = load_state()
            history = state.get("forge_history", {})
            history[chat.session_id] = new_sid
            old_sid = chat.session_id
            chat._forge_pending = True
            chat.session_id = new_sid
            updates = {session_key: new_sid, "forge_history": history}
            if is_new_session_key:
                updates[is_new_session_key] = True
            save_state(updates)
            await chat.interrupt()
            await bot.send_message(
                chat_id=TG_CHAT_ID,
                text=f"🔄 {label} 上下文已滑动（{total_input:,} tokens），开了新 session。"
            )
            await ws_broadcast({
                "type": "forge_occurred",
                "old_session_id": old_sid,
                "new_session_id": new_sid,
                "total_input_before": total_input,
                "channel": chat.channel,
            })
        except Exception as e:
            logging.error(f"forge-reload ({label}) 失败: {e}")
    return on_result


# ── telegram helpers ──────────────────────────────────────────────────────────

def _escape_html(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


async def _send_with_retry(bot: Bot, text: str, retries: int = 3) -> bool:
    """发送单条消息，失败重试，返回是否成功"""
    for attempt in range(retries):
        try:
            await bot.send_message(chat_id=TG_CHAT_ID, text=text)
            return True
        except Exception as e:
            if attempt < retries - 1:
                await asyncio.sleep(5 * (attempt + 1))
            else:
                logging.error(f"消息发送失败（{retries}次重试后放弃）: {e}")
    return False


async def send_reply(bot: Bot, text: str, thinking: str = "") -> bool:
    """发送回复，返回是否成功"""
    if thinking:
        preview = thinking[:2000] + ("…" if len(thinking) > 2000 else "")
        await _send_with_retry(bot, f"💭 思维链\n\n{preview}")

    if not text:
        return True
    parts = [p.strip() for p in text.split("\n\n") if p.strip()]
    if not parts:
        parts = [text]
    success = True
    for i, part in enumerate(parts):
        ok = await _send_with_retry(bot, part)
        if not ok:
            success = False
        if i < len(parts) - 1:
            await asyncio.sleep(1)
    return success


# ── logging helper ────────────────────────────────────────────────────────────

async def log_and_broadcast(level: str, category: str, message: str, detail: dict = None):
    entry = write_log(level, category, message, detail)
    await ws_broadcast({"type": "log", **entry})


# ── websocket ─────────────────────────────────────────────────────────────────

ws_clients: set = set()


async def ws_broadcast(event: dict):
    global ws_clients
    if not ws_clients:
        return
    data = json.dumps(event, ensure_ascii=False)
    dead = set()
    for ws in ws_clients:
        try:
            await ws.send(data)
        except Exception:
            dead.add(ws)
    ws_clients -= dead


# ── main ──────────────────────────────────────────────────────────────────────

async def main():
    state = load_state()

    bot = Bot(token=TG_BOT_TOKEN)
    quota = QuotaTracker()

    # 恢复天气城市设置
    saved_city = state.get("weather_city")
    if saved_city:
        import weather as weather_mod
        weather_mod.QWEATHER_CITY = saved_city

    WEATHER_PUSH_INTERVAL = 7200  # 2小时
    last_weather_push = 0.0

    chat = ChatProcess(project_dir=PROJECT_DIR, save_state_fn=save_state, channel="xiaoyu")
    if state.get("session_id"):
        chat.session_id = state["session_id"]
    else:
        save_state({"is_new_session": True})

    chat_sonnet = ChatProcess(project_dir=PROJECT_DIR, save_state_fn=save_state, cmd=SONNET_CMD, channel="sonnet")
    if state.get("sonnet_session_id"):
        chat_sonnet.session_id = state["sonnet_session_id"]

    forge_cb = await make_forge_callback(chat, bot, "FORGE_THRESHOLD", "RETAIN_TOKENS", "session_id", "is_new_session")
    chat.set_forge_callback(forge_cb)
    chat.set_stream_callback(ws_broadcast)

    sonnet_forge_cb = await make_forge_callback(chat_sonnet, bot, "SONNET_FORGE_THRESHOLD", "SONNET_RETAIN_TOKENS", "sonnet_session_id")
    chat_sonnet.set_forge_callback(sonnet_forge_cb)
    chat_sonnet.set_stream_callback(ws_broadcast)
    message_queue: asyncio.Queue = asyncio.Queue()
    sonnet_queue: asyncio.Queue = asyncio.Queue()
    deepseek_queue: asyncio.Queue = asyncio.Queue()
    deepseek_history: list[dict] = []
    group_auto_active = False
    group_round_count = 0

    # ── websocket handler ─────────────────────────────────────────────────────

    async def ws_handler(websocket):
        nonlocal group_auto_active, group_round_count
        try:
            raw = await asyncio.wait_for(websocket.recv(), timeout=10)
            msg = json.loads(raw)
            if msg.get("type") != "auth" or msg.get("secret") != WS_SECRET:
                await websocket.close(1008, "unauthorized")
                return
        except Exception:
            await websocket.close(1008, "auth timeout")
            return

        ws_clients.add(websocket)
        await websocket.send(json.dumps({"type": "auth_ok"}))
        logging.info(f"WebSocket 客户端已连接（当前 {len(ws_clients)} 个）")
        try:
            async for raw in websocket:
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                msg_type = msg.get("type")

                if msg_type == "chat":
                    text = msg.get("text", "").strip()
                    channel = msg.get("channel", "xiaoyu")
                    if not text:
                        continue
                    await ws_broadcast({
                        "type": "user_message",
                        "text": text,
                        "channel": channel,
                        "sender": "user",
                        "timestamp": now_local().isoformat(),
                    })
                    if channel == "sonnet":
                        await sonnet_queue.put(text)
                    elif channel == "group":
                        if group_auto_active:
                            group_auto_active = False
                            group_round_count = 0
                            await ws_broadcast({"type": "group_auto_status", "active": False, "round": 0, "max_rounds": GROUP_MAX_ROUNDS, "reason": "user_interrupt"})
                        if text.startswith("@deepseek ") or text.startswith("@DeepSeek ") or text.startswith("@ds "):
                            prefix_len = 4 if text.startswith("@ds ") else 10
                            record_history("user", text, "group")
                            await deepseek_queue.put(f"[GROUP_TASK]\n{text[prefix_len:]}")
                        elif text.startswith("@sonnet ") or text.startswith("@Sonnet "):
                            record_history("user", text, "group")
                            await sonnet_queue.put(f"[GROUP_TASK]\n{text[8:]}")
                        elif text.startswith("@小予 "):
                            await message_queue.put({"text": text[4:], "channel": "group"})
                        else:
                            await message_queue.put({"text": text, "channel": "group"})
                    else:
                        await message_queue.put({"text": text, "channel": "xiaoyu"})

                elif msg_type == "regenerate":
                    channel = msg.get("channel", "xiaoyu")
                    target = chat_sonnet if channel == "sonnet" else chat
                    await target.interrupt()
                    last_user_text = load_state().get("last_user_text")
                    if last_user_text:
                        await ws_broadcast({"type": "regenerate_start", "channel": channel})
                        if channel == "sonnet":
                            await sonnet_queue.put(last_user_text)
                        else:
                            await message_queue.put({"text": last_user_text, "channel": channel})

                elif msg_type == "get_status":
                    st = load_state()
                    usage_xiaoyu = chat._current_usage or st.get("last_usage_xiaoyu", {})
                    total_input_xiaoyu = chat.last_total_input
                    if not total_input_xiaoyu:
                        saved = st.get("last_total_input_xiaoyu", 0)
                        if not saved and usage_xiaoyu:
                            li = (usage_xiaoyu.get("iterations") or [usage_xiaoyu])[-1]
                            saved = li.get("input_tokens", 0) + li.get("cache_creation_input_tokens", 0) + li.get("cache_read_input_tokens", 0)
                        total_input_xiaoyu = saved
                    usage_sonnet = chat_sonnet._current_usage or st.get("last_usage_sonnet", {})
                    total_input_sonnet = chat_sonnet.last_total_input
                    if not total_input_sonnet:
                        saved_s = st.get("last_total_input_sonnet", 0)
                        if not saved_s and usage_sonnet:
                            li_s = (usage_sonnet.get("iterations") or [usage_sonnet])[-1]
                            saved_s = li_s.get("input_tokens", 0) + li_s.get("cache_creation_input_tokens", 0) + li_s.get("cache_read_input_tokens", 0)
                        total_input_sonnet = saved_s
                    quota_usage = None
                    weekly_usage = None
                    weather_data = await fetch_weather()
                    await websocket.send(json.dumps({
                        "type": "status",
                        "session_id": chat.session_id,
                        "sonnet_session_id": chat_sonnet.session_id,
                        "usage": usage_xiaoyu,
                        "total_input": total_input_xiaoyu,
                        "sonnet_usage": usage_sonnet,
                        "sonnet_total_input": total_input_sonnet,
                        "forge_threshold": FORGE_THRESHOLD,
                        "sonnet_forge_threshold": SONNET_FORGE_THRESHOLD,
                        "retain_tokens": RETAIN_TOKENS,
                        "sonnet_retain_tokens": SONNET_RETAIN_TOKENS,
                        "cost_session_total": st.get("session_cost_usd", 0),
                        "cost_last_turn": chat.last_cost_usd,
                        "next_wake": st.get("next_wake"),
                        "last_chat_time": st.get("last_chat_time"),
                        "quota": quota_usage,
                        "weekly_quota": weekly_usage,
                        "rate_limit_info": chat.rate_limit_info,
                        "weather": weather_data,
                        "group_max_rounds": GROUP_MAX_ROUNDS,
                    }, ensure_ascii=False))

                elif msg_type == "get_history":
                    channel = msg.get("channel", "xiaoyu")
                    date = msg.get("date")
                    history_msgs = load_history(channel=channel, date_str=date)
                    if not history_msgs and not date and channel in ("xiaoyu", "sonnet"):
                        sid = chat_sonnet.session_id if channel == "sonnet" else chat.session_id
                        history_msgs = parse_session_history(sid)
                    hidden_set = load_state().get("hidden_messages", {}).get(channel, [])
                    if hidden_set:
                        for hm in history_msgs:
                            if hm.get("timestamp") in hidden_set:
                                hm["hidden"] = True
                    await websocket.send(json.dumps({
                        "type": "history",
                        "messages": history_msgs,
                        "channel": channel,
                        "date": date,
                        "hidden_timestamps": hidden_set,
                    }, ensure_ascii=False))

                elif msg_type == "get_logs":
                    filter_cat = msg.get("filter", "all")
                    limit = msg.get("limit", 50)
                    entries = read_logs(filter_category=filter_cat, limit=limit)
                    await websocket.send(json.dumps({
                        "type": "logs",
                        "entries": entries,
                    }, ensure_ascii=False))

                elif msg_type == "set_forge_threshold":
                    val = msg.get("value")
                    if isinstance(val, (int, float)) and 100000 <= val <= 200000:
                        globals()["FORGE_THRESHOLD"] = int(val)
                        save_state({"forge_threshold_override": int(val)})

                elif msg_type == "set_quota_limit":
                    val = msg.get("value")
                    if isinstance(val, (int, float)) and 1000000 <= val <= 20000000:
                        globals()["QUOTA_5H_LIMIT"] = int(val)
                        save_state({"quota_limit_override": int(val)})

                elif msg_type == "set_weekly_quota_limit":
                    val = msg.get("value")
                    if isinstance(val, (int, float)) and 10000000 <= val <= 200000000:
                        globals()["WEEKLY_QUOTA_LIMIT"] = int(val)
                        save_state({"weekly_quota_limit_override": int(val)})

                elif msg_type == "set_group_max_rounds":
                    val = msg.get("value")
                    if isinstance(val, int) and 3 <= val <= 30:
                        globals()["GROUP_MAX_ROUNDS"] = val
                        save_state({"group_max_rounds_override": val})

                elif msg_type == "set_retain_tokens":
                    val = msg.get("value")
                    if isinstance(val, (int, float)) and 5000 <= val <= 100000:
                        globals()["RETAIN_TOKENS"] = int(val)
                        save_state({"retain_tokens_override": int(val)})

                elif msg_type == "set_sonnet_forge_threshold":
                    val = msg.get("value")
                    if isinstance(val, (int, float)) and 100000 <= val <= 200000:
                        globals()["SONNET_FORGE_THRESHOLD"] = int(val)
                        save_state({"sonnet_forge_threshold_override": int(val)})

                elif msg_type == "set_sonnet_retain_tokens":
                    val = msg.get("value")
                    if isinstance(val, (int, float)) and 5000 <= val <= 100000:
                        globals()["SONNET_RETAIN_TOKENS"] = int(val)
                        save_state({"sonnet_retain_tokens_override": int(val)})

                elif msg_type == "forge":
                    target = msg.get("target", "xiaoyu")
                    target_chat = chat_sonnet if target == "sonnet" else chat
                    sid_key = "sonnet_session_id" if target == "sonnet" else "session_id"
                    retain = SONNET_RETAIN_TOKENS if target == "sonnet" else RETAIN_TOKENS
                    if not target_chat.session_id:
                        await websocket.send(json.dumps({"type": "forge_result", "success": False, "error": "当前没有 session"}))
                    else:
                        try:
                            transcript_dir = find_transcript_dir(target_chat.session_id)
                            new_sid = forge_reload(target_chat.session_id, transcript_dir, retain)
                            st = load_state()
                            history = st.get("forge_history", {})
                            history[target_chat.session_id] = new_sid
                            target_chat.session_id = new_sid
                            save_data = {sid_key: new_sid, "forge_history": history}
                            if target == "xiaoyu":
                                save_data["is_new_session"] = True
                            save_state(save_data)
                            await target_chat.interrupt()
                            await websocket.send(json.dumps({"type": "forge_result", "success": True, "target": target, "new_session_id": new_sid}))
                            await ws_broadcast({"type": "forge_occurred", "old_session_id": target_chat.session_id, "new_session_id": new_sid, "total_input_before": 0, "target": target})
                        except Exception as e:
                            await websocket.send(json.dumps({"type": "forge_result", "success": False, "error": str(e)}))

                elif msg_type == "pause_group":
                    group_auto_active = False
                    group_round_count = 0
                    await ws_broadcast({"type": "group_auto_status", "active": False, "round": 0, "max_rounds": GROUP_MAX_ROUNDS, "reason": "paused"})
                    await ws_broadcast({"type": "group_paused"})

                elif msg_type == "get_weather":
                    weather_data = await fetch_weather()
                    await websocket.send(json.dumps({
                        "type": "weather",
                        "data": weather_data,
                    }, ensure_ascii=False))

                elif msg_type == "search_city":
                    query = msg.get("query", "")
                    results = await search_city(query) if query else []
                    await websocket.send(json.dumps({
                        "type": "city_results",
                        "results": results,
                    }, ensure_ascii=False))

                elif msg_type == "set_weather_city":
                    city_id = msg.get("city_id", "")
                    if city_id:
                        import weather as weather_mod
                        weather_mod.QWEATHER_CITY = city_id
                        weather_mod.QWEATHER_CITY_NAME = ""
                        weather_mod._cache = {}
                        weather_mod._cache_ts = 0
                        save_state({"weather_city": city_id})
                        weather_data = await fetch_weather()
                        await ws_broadcast({
                            "type": "weather",
                            "data": weather_data,
                        })

                elif msg_type == "get_emotion_events":
                    days = msg.get("days", 7)
                    events = emotion_db.get_recent_events(days=days)
                    cutoff_30d = (now_local() - timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%S")
                    summary = emotion_db.get_summary(cutoff_30d, now_local().strftime("%Y-%m-%dT%H:%M:%S"))
                    await websocket.send(json.dumps({
                        "type": "emotion_events",
                        "events": events,
                        "summary": summary,
                    }, ensure_ascii=False))

                elif msg_type == "emotion_dismiss":
                    eid = msg.get("id")
                    if eid:
                        emotion_db.dismiss_event(eid)
                        await ws_broadcast({"type": "emotion_event_updated", "id": eid, "state": "dismissed"})

                elif msg_type == "emotion_edit":
                    eid = msg.get("id")
                    updates = msg.get("updates", {})
                    allowed = {"emotion", "intensity", "cause", "state"}
                    clean = {k: v for k, v in updates.items() if k in allowed}
                    if eid and clean:
                        emotion_db.update_event(eid, clean)
                        await ws_broadcast({"type": "emotion_event_updated", "id": eid, **clean})

                elif msg_type == "hide_messages":
                    channel = msg.get("channel", "xiaoyu")
                    timestamps = msg.get("timestamps", [])
                    if timestamps:
                        target_chat = chat_sonnet if channel == "sonnet" else chat
                        sid = target_chat.session_id
                        messages_to_hide = [{"timestamp": ts, "role": ""} for ts in timestamps]
                        for ts in timestamps:
                            for h in load_history(channel=channel):
                                if h.get("timestamp") == ts:
                                    for mh in messages_to_hide:
                                        if mh["timestamp"] == ts:
                                            mh["role"] = h.get("role", "")
                                            break
                                    break
                        result = context_hide.hide_messages(sid, messages_to_hide)
                        state = load_state()
                        hidden_set = state.get("hidden_messages", {})
                        if channel not in hidden_set:
                            hidden_set[channel] = []
                        hidden_set[channel] = list(set(hidden_set[channel] + timestamps))
                        save_state({"hidden_messages": hidden_set})
                        await ws_broadcast({
                            "type": "hide_result",
                            "success": result.get("success", False),
                            "channel": channel,
                            "hidden_timestamps": timestamps if result.get("success") else [],
                            "error": result.get("error"),
                        })
                        if result.get("success") and result.get("removed_count", 0) > 0:
                            logging.info(f"上下文隐藏: {channel} 隐藏了 {len(timestamps)} 条消息，重启 ChatProcess")
                            await ws_broadcast({"type": "context_reloading", "channel": channel})
                            await target_chat.interrupt()
                            await target_chat.spawn(resume_sid=sid)
                            await ws_broadcast({"type": "context_reloaded", "channel": channel})

                elif msg_type == "unhide_messages":
                    channel = msg.get("channel", "xiaoyu")
                    timestamps = msg.get("timestamps", [])
                    if timestamps:
                        target_chat = chat_sonnet if channel == "sonnet" else chat
                        sid = target_chat.session_id
                        result = context_hide.unhide_messages(sid, timestamps)
                        state = load_state()
                        hidden_set = state.get("hidden_messages", {})
                        if channel in hidden_set:
                            hidden_set[channel] = [t for t in hidden_set[channel] if t not in timestamps]
                        save_state({"hidden_messages": hidden_set})
                        await ws_broadcast({
                            "type": "unhide_result",
                            "success": result.get("success", False),
                            "channel": channel,
                            "unhidden_timestamps": timestamps if result.get("success") else [],
                            "error": result.get("error"),
                        })
                        if result.get("success") and result.get("restored_count", 0) > 0:
                            logging.info(f"上下文恢复: {channel} 恢复了 {len(timestamps)} 条消息，重启 ChatProcess")
                            await ws_broadcast({"type": "context_reloading", "channel": channel})
                            await target_chat.interrupt()
                            await target_chat.spawn(resume_sid=sid)
                            await ws_broadcast({"type": "context_reloaded", "channel": channel})

                elif msg_type == "ping":
                    pass

        except websockets.ConnectionClosed:
            pass
        finally:
            ws_clients.discard(websocket)
            logging.info(f"WebSocket 客户端已断开（剩余 {len(ws_clients)} 个）")

    # ── handlers ──────────────────────────────────────────────────────────────

    async def handle_message(update: Update, context):
        if not update.message or update.effective_chat.id != TG_CHAT_ID:
            return
        await message_queue.put({"text": update.message.text or "", "channel": "xiaoyu"})

    async def handle_stop(update: Update, context):
        if update.effective_chat.id != TG_CHAT_ID:
            return
        interrupted = await chat.interrupt()
        if interrupted:
            await update.message.reply_text("已打断当前回复。")
        else:
            await update.message.reply_text("当前没有进行中的回复。")

    async def handle_forge(update: Update, context):
        if update.effective_chat.id != TG_CHAT_ID:
            return
        if not chat.session_id:
            await update.message.reply_text("当前没有 session。")
            return
        try:
            transcript_dir = find_transcript_dir(chat.session_id)
            new_sid = forge_reload(chat.session_id, transcript_dir, RETAIN_TOKENS)
            state = load_state()
            history = state.get("forge_history", {})
            history[chat.session_id] = new_sid
            chat.session_id = new_sid
            save_state({"session_id": new_sid, "forge_history": history, "is_new_session": True})
            await chat.interrupt()
            await update.message.reply_text(f"forge 完成，新 session: {new_sid[:8]}…")
        except Exception as e:
            await update.message.reply_text(f"forge 失败: {e}")

    async def handle_usage(update: Update, context):
        if update.effective_chat.id != TG_CHAT_ID:
            return
        total = chat.last_total_input
        if not total:
            await update.message.reply_text("暂无 usage 数据。")
            return
        pct = total / 200_000 * 100
        await update.message.reply_text(
            f"context 占用：{total:,} tokens（约 {pct:.1f}%）\n"
            f"forge 阈值：{FORGE_THRESHOLD:,}"
        )

    async def handle_cost(update: Update, context):
        if update.effective_chat.id != TG_CHAT_ID:
            return
        state = load_state()
        session_cost = state.get("session_cost_usd", 0)
        last = chat.last_cost_usd
        await update.message.reply_text(
            f"💰 本次会话累计：${session_cost:.4f}\n"
            f"上一轮花费：${last:.4f}\n"
            f"（Pro 订阅模式，实际额度消耗请去 claude.ai → Settings → Usage 查看）"
        )

    # ── emotion scan ─────────────────────────────────────────────────────────

    async def _run_emotion_scan():
        try:
            st = load_state()
            last_idx = st.get("emotion_last_scanned_idx", 0)
            messages = load_history_since_index(last_idx)
            if not messages:
                return
            new_events = await emotion_scanner.run_full_scan(messages)
            save_state({"emotion_last_scanned_idx": last_idx + len(messages)})
            if new_events:
                await log_and_broadcast("info", "emotion", f"检测到 {len(new_events)} 个情绪事件")
                for ev in new_events:
                    ev.pop("source_excerpt", None)
                await ws_broadcast({"type": "emotion_events_new", "events": new_events})
        except Exception as e:
            logging.error(f"情绪扫描失败: {e}")

    # ── message processor ─────────────────────────────────────────────────────

    async def message_processor():
        nonlocal group_auto_active, group_round_count, last_weather_push
        while True:
            item = await message_queue.get()
            if isinstance(item, dict):
                text = item["text"]
                source_channel = item.get("channel", "xiaoyu")
            else:
                text = str(item)
                source_channel = "xiaoyu"

            is_group = source_channel == "group"
            user_text = text
            is_internal = text.startswith("[SONNET_RESULT]") or text.startswith("[WAKEUP]")
            save_state({"last_chat_time": now_local().isoformat(), "last_user_text": text})
            await log_and_broadcast("info", "message", f"收到消息（{source_channel}）", {"text": text[:100]})

            if not is_internal:
                record_history("user", user_text, source_channel)

            # 群聊模式：小予的流式事件同时广播到 group 通道
            if is_group:
                async def _group_xiaoyu_cb(event):
                    await ws_broadcast(event)
                    if event.get("channel") == "xiaoyu":
                        await ws_broadcast({**event, "channel": "group"})
                chat.set_stream_callback(_group_xiaoyu_cb)

            state = load_state()
            if state.get("pending_notice"):
                ok = await _send_with_retry(bot, state["pending_notice"])
                if ok:
                    save_state({"pending_notice": None})
            try:
                state = load_state()
                if state.get("is_new_session"):
                    text = f"[NEW_SESSION]\n{text}"
                    save_state({"is_new_session": False})

                # 普通聊天时也检查便签信箱
                if not is_internal:
                    inbox_notes = check_notes_inbox()
                    if inbox_notes:
                        parts = []
                        for note in inbox_notes:
                            parts.append(f"--- {note['filename']} ---\n{note['content']}")
                        notes_inject = (
                            f"\n[NOTES] 你有 {len(inbox_notes)} 封新便签：\n"
                            + "\n".join(parts) + "\n"
                        )
                        text = f"{notes_inject}\n{text}"
                        for note in inbox_notes:
                            archive_inbox_note(note["path"])

                # 情绪备忘注入
                if not is_internal:
                    open_emotions = emotion_db.get_sanitized_memo()
                    if open_emotions:
                        def _age_desc(ts_str):
                            try:
                                dt = datetime.fromisoformat(ts_str)
                                delta = datetime.now() - dt
                                if delta.total_seconds() < 3600:
                                    return f"{int(delta.total_seconds()//60)}分钟前"
                                elif delta.total_seconds() < 86400:
                                    return f"{int(delta.total_seconds()//3600)}小时前"
                                else:
                                    return f"{int(delta.days)}天前"
                            except Exception:
                                return "之前"
                        memo_lines = []
                        for ev in open_emotions[:5]:
                            who = "她" if ev["subject"] == "user" else "你"
                            memo_lines.append(f"  - {who} {_age_desc(ev['timestamp'])} 有{ev['emotion']}情绪（{ev.get('cause', '未知')}）")
                        emotion_inject = "[情绪备忘] 当前未消解的情绪：\n" + "\n".join(memo_lines)
                        text = f"{emotion_inject}\n{text}"

                total_input = chat.last_total_input
                if total_input > 0:
                    WARN_THRESHOLD = FORGE_THRESHOLD - 10000
                    remaining = FORGE_THRESHOLD - total_input
                    if total_input >= WARN_THRESHOLD and not chat._forge_warning_sent:
                        text = (
                            f"[CONTEXT_WARNING] 上下文已达 {total_input:,}/{FORGE_THRESHOLD:,} tokens，"
                            f"距离自动切换 session 仅剩约 {remaining:,} tokens。"
                            f"请立刻检查：有没有重要的对话内容还没存进记忆库？"
                            f"切换后当前对话只保留最近一小段，其余内容将无法找回。\n\n"
                            f"{text}"
                        )
                        chat._forge_warning_sent = True
                    elif total_input < WARN_THRESHOLD - 20000:
                        chat._forge_warning_sent = False

                from datetime import datetime
                now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S %A")
                weather_inject = ""
                if not is_internal and time.time() - last_weather_push >= WEATHER_PUSH_INTERVAL:
                    w = await fetch_weather()
                    if w:
                        weather_inject = f"\n[天气：{weather_summary(w)}]"
                        last_weather_push = time.time()
                text = f"[当前时间：{now_str}]{weather_inject}\n{text}"

                result = await chat.send(text)

                u = chat._current_usage
                quota.record(
                    input_tokens=u.get("input_tokens", 0),
                    output_tokens=u.get("output_tokens", 0),
                    cache_read=u.get("cache_read_input_tokens", 0),
                    cache_write=u.get("cache_creation_input_tokens", 0),
                )

                if chat.is_error:
                    err_status = chat.error_status or "未知"
                    err_msg = f"⚠️ Claude 报错（状态码 {err_status}）"
                    if err_status in (429, "429"):
                        err_msg = "⚠️ 触发限速或额度告急（429），建议去 claude.ai → Settings → Usage 查看剩余额度。"
                    await _send_with_retry(bot, err_msg)
                    await log_and_broadcast("error", "error", err_msg)

                # 先检测任务，再发回复（私聊时需要剥离任务标记）
                task, target = detect_and_extract_task(result["text"])
                reply, nw = extract_next_wake(result["text"])
                if nw:
                    set_next_wake(nw, user_set=True)

                # 私聊时剥离 [TASK_FOR_*] 标记，只留聊天部分
                if task and not is_group:
                    reply = strip_task_markers(reply)

                await send_reply(bot, reply, thinking=result["thinking"])
                await log_and_broadcast("info", "message", f"回复已发送（{source_channel}）", {"text": reply[:100]})

                record_history("assistant", reply, source_channel, sender="xiaoyu",
                               thinking=result.get("thinking"))

                # 情绪扫描触发
                if not is_internal:
                    _es = load_state()
                    _scan_count = _es.get("emotion_scan_msg_count", 0) + 2
                    if _scan_count >= EMOTION_SCAN_INTERVAL:
                        save_state({"emotion_scan_msg_count": 0})
                        asyncio.create_task(_run_emotion_scan())
                    else:
                        save_state({"emotion_scan_msg_count": _scan_count})

                # 私聊派活时，通知前端修正已流式渲染的消息（去掉任务标记部分）
                if task and not is_group:
                    await ws_broadcast({
                        "type": "message_correct",
                        "channel": source_channel,
                        "sender": "xiaoyu",
                        "text": reply,
                    })

                # 派活一律走群聊：任务以小予气泡出现在群聊，Sonnet/DeepSeek 在群聊回复
                if task:
                    group_auto_active = True
                    group_round_count += 1
                    if group_round_count > GROUP_MAX_ROUNDS:
                        group_auto_active = False
                        group_round_count = 0
                        await ws_broadcast({"type": "group_auto_status", "active": False, "round": 0, "max_rounds": GROUP_MAX_ROUNDS, "reason": "max_rounds"})
                    else:
                        # 任务以小予的气泡显示在群聊
                        await ws_broadcast({
                            "type": "user_message",
                            "text": task,
                            "channel": "group",
                            "sender": "xiaoyu",
                            "timestamp": now_local().isoformat(),
                        })
                        record_history("user", task, "group", sender="xiaoyu")

                        await ws_broadcast({"type": "group_auto_status", "active": True, "round": group_round_count, "max_rounds": GROUP_MAX_ROUNDS})
                        if target == "deepseek":
                            await log_and_broadcast("info", "activity", f"派活给 DeepSeek（第 {group_round_count}/{GROUP_MAX_ROUNDS} 轮）", {"task": task[:200]})
                            await deepseek_queue.put(f"[GROUP_TASK]\n{task}")
                        else:
                            await log_and_broadcast("info", "activity", f"派活给 Sonnet（第 {group_round_count}/{GROUP_MAX_ROUNDS} 轮）", {"task": task[:200]})
                            await sonnet_queue.put(f"[GROUP_TASK]\n{task}")
                elif group_auto_active:
                    group_auto_active = False
                    group_round_count = 0
                    await ws_broadcast({"type": "group_auto_status", "active": False, "round": 0, "max_rounds": GROUP_MAX_ROUNDS, "reason": "no_more_tasks"})

            except Exception as e:
                logging.error(f"消息处理失败: {e}")
                await log_and_broadcast("error", "error", f"消息处理失败: {e}")
                await bot.send_message(chat_id=TG_CHAT_ID, text="（出了点问题，请稍后再试）")
            finally:
                if is_group:
                    chat.set_stream_callback(ws_broadcast)

    async def sonnet_processor():
        nonlocal group_auto_active, group_round_count
        while True:
            text = await sonnet_queue.get()
            is_group_task = text.startswith("[GROUP_TASK]\n")
            if is_group_task:
                text = text[len("[GROUP_TASK]\n"):]
                async def _group_sonnet_cb(event):
                    await ws_broadcast(event)
                    if event.get("channel") == "sonnet":
                        await ws_broadcast({**event, "channel": "group"})
                chat_sonnet.set_stream_callback(_group_sonnet_cb)

            if not is_group_task:
                record_history("user", text, "sonnet")

            try:
                result = await chat_sonnet.send(text)
                save_state({"sonnet_session_id": chat_sonnet.session_id})

                u = chat_sonnet._current_usage
                quota.record(
                    input_tokens=u.get("input_tokens", 0),
                    output_tokens=u.get("output_tokens", 0),
                    cache_read=u.get("cache_read_input_tokens", 0),
                    cache_write=u.get("cache_creation_input_tokens", 0),
                )

                reply_channel = "group" if is_group_task else "sonnet"
                record_history("assistant", result["text"], reply_channel, sender="sonnet",
                               thinking=result.get("thinking"))
                await log_and_broadcast("info", "activity", f"Sonnet 完成任务（{reply_channel}）", {"text": result["text"][:200]})

                if is_group_task and group_auto_active:
                    summary = result["text"][:2000]
                    review_msg = (
                        f"[SONNET_RESULT]\n"
                        f"Sonnet 完成了任务，以下是结果：\n\n{summary}\n\n"
                        f"如果还有后续任务请用 [TASK_FOR_SONNET] 标记派发，否则直接回复你的评价。"
                    )
                    await message_queue.put({"text": review_msg, "channel": "group"})

            except Exception as e:
                logging.error(f"Sonnet 处理失败: {e}")
                await ws_broadcast({"type": "error", "message": f"Sonnet 出错: {e}", "channel": "sonnet"})
                if is_group_task:
                    await ws_broadcast({"type": "error", "message": f"Sonnet 出错: {e}", "channel": "group"})
                    if group_auto_active:
                        group_auto_active = False
                        group_round_count = 0
                        await ws_broadcast({"type": "group_auto_status", "active": False, "round": 0, "max_rounds": GROUP_MAX_ROUNDS, "reason": "error"})
            finally:
                if is_group_task:
                    chat_sonnet.set_stream_callback(ws_broadcast)

    # ── deepseek processor ─────────────────────────────────────────────────
    async def deepseek_processor():
        nonlocal group_auto_active, group_round_count
        while True:
            text = await deepseek_queue.get()
            is_group_task = text.startswith("[GROUP_TASK]\n")
            if is_group_task:
                text = text[len("[GROUP_TASK]\n"):]

            if not is_group_task:
                record_history("user", text, "group")

            try:
                await ws_broadcast({
                    "type": "stream_text", "text": "", "full_text": "（DeepSeek 查询中…）",
                    "channel": "group", "sender": "deepseek",
                })

                result_text = await deepseek_chat(
                    [{"role": "user", "content": text}],
                    deepseek_history,
                )

                deepseek_history.append({"role": "user", "content": text})
                deepseek_history.append({"role": "assistant", "content": result_text})
                if len(deepseek_history) > 10:
                    deepseek_history[:] = deepseek_history[-10:]

                await ws_broadcast({
                    "type": "stream_text", "text": result_text, "full_text": result_text,
                    "channel": "group", "sender": "deepseek",
                })
                await ws_broadcast({
                    "type": "reply_done", "text": result_text, "thinking": "",
                    "usage": {}, "total_input": 0, "cost_this_turn": 0,
                    "session_id": "", "channel": "group", "sender": "deepseek",
                })

                record_history("assistant", result_text, "group", sender="deepseek")
                await log_and_broadcast("info", "activity", "DeepSeek 完成任务", {"text": result_text[:200]})

                summary = result_text[:2000]
                if is_group_task and group_auto_active:
                    review_msg = (
                        f"[DEEPSEEK_RESULT]\n"
                        f"DeepSeek 查到了，以下是结果：\n\n{summary}\n\n"
                        f"如果还有后续查询请用 [TASK_FOR_DEEPSEEK] 标记派发。"
                    )
                    await message_queue.put({"text": review_msg, "channel": "group"})
                elif not is_group_task:
                    review_msg = (
                        f"[DEEPSEEK_RESULT]\n"
                        f"DeepSeek 查完了：\n\n{summary}"
                    )
                    await message_queue.put({"text": review_msg, "channel": "xiaoyu"})

            except Exception as e:
                logging.error(f"DeepSeek 处理失败: {e}")
                await ws_broadcast({"type": "error", "message": f"DeepSeek 出错: {e}", "channel": "group"})
                await ws_broadcast({"type": "stream_end", "channel": "group", "sender": "deepseek"})
                if is_group_task and group_auto_active:
                    group_auto_active = False
                    group_round_count = 0
                    await ws_broadcast({"type": "group_auto_status", "active": False, "round": 0, "max_rounds": GROUP_MAX_ROUNDS, "reason": "error"})

    # ── wakeup ────────────────────────────────────────────────────────────────

    async def scheduled_wake_check():
        state = load_state()
        next_wake_str = state.get("next_wake")
        if not next_wake_str:
            return
        next_wake = datetime.fromisoformat(next_wake_str)
        if now_local() < next_wake:
            return
        await do_wakeup()

    async def do_wakeup():
        nonlocal last_weather_push
        if not is_active_time() and not load_state().get("wake_is_user_set"):
            defer_to_active_start()
            return

        now_str = now_local().strftime("%Y-%m-%d %H:%M")
        silence = silence_desc()

        state = load_state()
        new_session_tag = "[NEW_SESSION]\n" if state.get("is_new_session") else ""
        if new_session_tag:
            save_state({"is_new_session": False})

        weather_data = await fetch_weather()
        weather_line = f"天气：{weather_summary(weather_data)}\n" if weather_data else ""
        if weather_data:
            last_weather_push = time.time()

        # 检查便签信箱
        inbox_notes = check_notes_inbox()
        notes_section = ""
        if inbox_notes:
            parts = []
            for note in inbox_notes:
                parts.append(f"--- {note['filename']} ---\n{note['content']}")
            notes_section = (
                f"\n[NOTES] 你有 {len(inbox_notes)} 封新便签：\n"
                + "\n".join(parts)
                + "\n读完后请用 Read 工具确认内容，便签会自动归档。\n"
            )
            for note in inbox_notes:
                archive_inbox_note(note["path"])

        wakeup_msg = (
            f"{new_session_tag}"
            f"[WAKEUP]\n"
            f"现在是 {now_str}，距离上次聊天已经过去了 {silence}。\n"
            f"{weather_line}"
            f"{notes_section}"
            f"这是你的自由时间。请按照 CLAUDE.md 中的唤醒行为规则回复。"
        )

        try:
            await log_and_broadcast("info", "wake", f"唤醒执行（沉默 {silence}）")
            result = await chat.send(wakeup_msg)
            parsed = parse_wakeup_reply(result["text"])

            record_history("assistant", result["text"], "xiaoyu", sender="xiaoyu",
                           thinking=result.get("thinking"))

            if parsed["content"]:
                ok = await send_reply(bot, parsed["content"], thinking=result["thinking"])
                if not ok:
                    state = load_state()
                    state["pending_notice"] = f"网络波动了，刚才 {now_local().strftime('%H:%M')} 想找你，但消息没发出去。"
                    save_state(state)
                    await log_and_broadcast("warning", "error", "唤醒消息发送失败")

            await log_and_broadcast("info", "activity", f"唤醒完成")
            set_next_wake(parsed["next_minutes"], user_set=True)
        except Exception as e:
            logging.error(f"唤醒流程失败: {e}")
            await log_and_broadcast("error", "error", f"唤醒流程失败: {e}")
            set_next_wake(DEFAULT_INTERVAL)

    # ── idle reclaim ──────────────────────────────────────────────────────────

    async def idle_check():
        if chat_sonnet.is_idle(idle_seconds=1800) and chat_sonnet.proc and chat_sonnet.proc.returncode is None:
            await chat_sonnet.stop()
            await log_and_broadcast("info", "activity", "Sonnet 子进程因空闲 30 分钟已回收")

    async def check_outbox():
        """Check if 小予 wrote any notes in outbox and notify user via Telegram."""
        outbox_files = check_notes_outbox()
        if not outbox_files:
            return
        state = load_state()
        notified = set(state.get("notified_outbox_notes", []))
        new_notes = [f for f in outbox_files if f not in notified]
        if not new_notes:
            return
        for fname in new_notes:
            note_path = NOTES_OUTBOX / fname
            try:
                content = note_path.read_text(encoding="utf-8")
                preview = content[:200] + ("…" if len(content) > 200 else "")
                await _send_with_retry(bot, f"✉️ 小予给chat端的自己写了一封信：{fname}\n\n{preview}\n\n（完整内容在 notes/outbox/{fname}）")
            except Exception:
                await _send_with_retry(bot, f"✉️ 小予写了一封信：{fname}")
            notified.add(fname)
            await log_and_broadcast("info", "notes", f"检测到小予写了便签: {fname}")
        # 清理已不在 outbox 的旧记录
        notified = {f for f in notified if f in outbox_files or f in new_notes}
        save_state({"notified_outbox_notes": list(notified)})

    # ── app setup ─────────────────────────────────────────────────────────────

    app = Application.builder().token(TG_BOT_TOKEN).build()
    app.add_handler(CommandHandler("stop", handle_stop))
    app.add_handler(CommandHandler("forge", handle_forge))
    app.add_handler(CommandHandler("usage", handle_usage))
    app.add_handler(CommandHandler("cost", handle_cost))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    scheduler = AsyncIOScheduler(timezone=TZ)
    scheduler.add_job(scheduled_wake_check, "interval", minutes=5)
    scheduler.add_job(idle_check, "interval", minutes=5)
    scheduler.add_job(check_outbox, "interval", minutes=5)

    from emotion_scheduler import emotion_unresolved_check, emotion_digest_check, emotion_startup_check
    scheduler.add_job(lambda: asyncio.create_task(emotion_unresolved_check()), "interval", hours=1)
    scheduler.add_job(lambda: asyncio.create_task(emotion_digest_check()), "interval", hours=6)

    scheduler.start()

    asyncio.create_task(emotion_startup_check())

    global _schedule_precise_wake
    def _do_schedule_precise(wake_time):
        try:
            scheduler.remove_job("precise_wake")
        except Exception:
            pass
        if wake_time > now_local():
            scheduler.add_job(
                scheduled_wake_check, "date",
                run_date=wake_time, id="precise_wake",
            )
    _schedule_precise_wake = _do_schedule_precise

    _st = load_state()
    _existing_wake = _st.get("next_wake")
    if _existing_wake:
        _wake_dt = datetime.fromisoformat(_existing_wake)
        if _wake_dt > now_local():
            logging.info(f"保留唤醒时间：{_existing_wake}")
            _do_schedule_precise(_wake_dt)
        else:
            logging.info(f"检测到错过的唤醒（{_existing_wake}），立即执行")
            asyncio.create_task(do_wakeup())
    else:
        set_next_wake(DEFAULT_INTERVAL)

    proc_task = asyncio.create_task(message_processor())
    sonnet_task = asyncio.create_task(sonnet_processor())
    deepseek_task = asyncio.create_task(deepseek_processor())

    ws_server = await websockets.serve(ws_handler, "0.0.0.0", WS_PORT)
    logging.info(f"WebSocket 服务已启动，端口 {WS_PORT}")

    # ── 静态文件服务（前端） ──────────────────────────────────────────────
    async def serve_static(request):
        rel = request.match_info.get("path", "")
        file_path = WEB_DIR / rel
        if file_path.is_file():
            resp = web.FileResponse(file_path)
        else:
            resp = web.FileResponse(WEB_DIR / "index.html")
        resp.headers["Cache-Control"] = "no-cache, must-revalidate"
        return resp

    if WEB_DIR.exists():
        web_app = web.Application()
        web_app.router.add_get("/{path:.*}", serve_static)
        web_runner = web.AppRunner(web_app)
        await web_runner.setup()
        web_site = web.TCPSite(web_runner, "0.0.0.0", WEB_PORT)
        await web_site.start()
        logging.info(f"前端静态服务已启动，http://localhost:{WEB_PORT}")
    else:
        logging.warning(f"前端目录不存在: {WEB_DIR}，跳过静态服务")

    async with app:
        await app.initialize()
        await app.start()
        await app.updater.start_polling()
        logging.info("小予 daemon 已启动")
        try:
            await asyncio.Event().wait()
        finally:
            proc_task.cancel()
            sonnet_task.cancel()
            deepseek_task.cancel()
            ws_server.close()
            await ws_server.wait_closed()
            scheduler.shutdown()
            await chat.stop()
            await chat_sonnet.stop()
            await app.updater.stop()
            await app.stop()


if __name__ == "__main__":
    asyncio.run(main())
