import asyncio
import json
import logging
import os
import pathlib
import re
from datetime import datetime, timedelta

import pytz
import websockets
from aiohttp import web
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from dotenv import load_dotenv
from telegram import Bot, Update
from telegram.ext import Application, MessageHandler, CommandHandler, filters

from chat_process import ChatProcess, CLAUDE_CMD
from forge_reload import find_transcript_dir, forge_reload
from log_store import write_log, read_logs
from quota_tracker import QuotaTracker
from weather import fetch_weather, weather_summary, search_city


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

TASK_MARKER_PATTERN = re.compile(r'\[TASK_FOR_SONNET\](.*?)(?:\[/TASK_FOR_SONNET\]|$)', re.DOTALL)
TASK_KEYWORD_PATTERN = re.compile(r'(?:让|叫|请)\s*(?:Sonnet|sonnet|牛马)\s*(?:去|来|帮忙)?')


def detect_and_extract_task(text: str) -> str | None:
    m = TASK_MARKER_PATTERN.search(text)
    if m:
        return m.group(1).strip()
    if TASK_KEYWORD_PATTERN.search(text):
        return text
    return None


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


def set_next_wake(minutes: int, user_set: bool = False):
    wake_time = now_local() + timedelta(minutes=minutes)
    save_state({
        "next_wake": wake_time.isoformat(),
        "wake_is_user_set": user_set,
    })
    msg = f"下次唤醒：{wake_time.strftime('%H:%M')}（{minutes}分钟后）"
    logging.info(msg)
    write_log("info", "wake", msg)


def defer_to_active_start():
    wake_time = next_active_start()
    save_state({
        "next_wake": wake_time.isoformat(),
        "wake_is_user_set": False,
    })
    msg = f"非活跃时段，推迟到 {wake_time.strftime('%m-%d %H:%M')}"
    logging.info(msg)
    write_log("info", "wake", msg)


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
    result = {
        "action": "none",
        "content": "",
        "title": "",
        "summary": "",
        "next_minutes": DEFAULT_INTERVAL,
    }
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("ACTION:"):
            result["action"] = line[7:].strip().lower()
        elif line.startswith("CONTENT:"):
            result["content"] = line[8:].strip()
        elif line.startswith("TITLE:"):
            result["title"] = line[6:].strip()
        elif line.startswith("SUMMARY:"):
            result["summary"] = line[8:].strip()
        elif line.startswith("NEXT_WAKE:"):
            m = re.search(r"(\d+)", line)
            if m:
                result["next_minutes"] = int(m.group(1))
    return result


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
                        if text.startswith("@sonnet ") or text.startswith("@Sonnet "):
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
                    usage_sonnet = chat_sonnet._current_usage or st.get("last_usage_sonnet", {})
                    total_input_sonnet = chat_sonnet.last_total_input
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
                    await websocket.send(json.dumps({
                        "type": "history",
                        "messages": history_msgs,
                        "channel": channel,
                        "date": date,
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

    # ── message processor ─────────────────────────────────────────────────────

    async def message_processor():
        nonlocal group_auto_active, group_round_count
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
                text = f"[当前时间：{now_str}]\n{text}"

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

                reply, nw = extract_next_wake(result["text"])
                if nw:
                    set_next_wake(nw, user_set=True)
                await send_reply(bot, reply, thinking=result["thinking"])
                await log_and_broadcast("info", "message", f"回复已发送（{source_channel}）", {"text": reply[:100]})

                record_history("assistant", reply, source_channel, sender="xiaoyu",
                               thinking=result.get("thinking"))

                # 群聊自动路由：检测小予是否派活给 Sonnet
                if is_group or group_auto_active:
                    task = detect_and_extract_task(result["text"])
                    if task:
                        group_auto_active = True
                        group_round_count += 1
                        if group_round_count > GROUP_MAX_ROUNDS:
                            group_auto_active = False
                            group_round_count = 0
                            await ws_broadcast({"type": "group_auto_status", "active": False, "round": 0, "max_rounds": GROUP_MAX_ROUNDS, "reason": "max_rounds"})
                        else:
                            await ws_broadcast({"type": "group_auto_status", "active": True, "round": group_round_count, "max_rounds": GROUP_MAX_ROUNDS})
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

        wakeup_msg = (
            f"{new_session_tag}"
            f"[WAKEUP]\n"
            f"现在是 {now_str}，距离上次聊天已经过去了 {silence}。\n"
            f"{weather_line}"
            f"这是你的自由时间。请按照 CLAUDE.md 中的唤醒行为规则回复。"
        )

        try:
            await log_and_broadcast("info", "wake", f"唤醒执行（沉默 {silence}）")
            result = await chat.send(wakeup_msg)
            parsed = parse_wakeup_reply(result["text"])

            display_text = parsed["content"] if parsed["action"] == "message" and parsed["content"] else result["text"]
            record_history("assistant", display_text, "xiaoyu", sender="xiaoyu",
                           thinking=result.get("thinking"))

            if parsed["action"] == "message" and parsed["content"]:
                ok = await send_reply(bot, parsed["content"], thinking=result["thinking"])
                if not ok:
                    state = load_state()
                    state["pending_notice"] = f"网络波动了，刚才 {now_local().strftime('%H:%M')} 想找你，但消息没发出去。"
                    save_state(state)
                    await log_and_broadcast("warning", "error", "唤醒消息发送失败")

            await log_and_broadcast("info", "activity", f"唤醒结果：action={parsed['action']}")
            set_next_wake(parsed["next_minutes"])
        except Exception as e:
            logging.error(f"唤醒流程失败: {e}")
            await log_and_broadcast("error", "error", f"唤醒流程失败: {e}")
            set_next_wake(DEFAULT_INTERVAL)

    # ── idle reclaim ──────────────────────────────────────────────────────────

    async def idle_check():
        if chat_sonnet.is_idle(idle_seconds=1800) and chat_sonnet.proc and chat_sonnet.proc.returncode is None:
            await chat_sonnet.stop()
            await log_and_broadcast("info", "activity", "Sonnet 子进程因空闲 30 分钟已回收")

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
    scheduler.start()

    set_next_wake(DEFAULT_INTERVAL)

    proc_task = asyncio.create_task(message_processor())
    sonnet_task = asyncio.create_task(sonnet_processor())

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
            ws_server.close()
            await ws_server.wait_closed()
            scheduler.shutdown()
            await chat.stop()
            await chat_sonnet.stop()
            await app.updater.stop()
            await app.stop()


if __name__ == "__main__":
    asyncio.run(main())
