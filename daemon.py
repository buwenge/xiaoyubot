import asyncio
import json
import logging
import os
import pathlib
import re
from datetime import datetime, timedelta

import pytz
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from dotenv import load_dotenv
from telegram import Bot, Update
from telegram.ext import Application, MessageHandler, CommandHandler, filters

from chat_process import ChatProcess
from forge_reload import find_transcript_dir, forge_reload

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
    logging.info(f"下次唤醒：{wake_time.strftime('%H:%M')}（{minutes}分钟后）")


def defer_to_active_start():
    wake_time = next_active_start()
    save_state({
        "next_wake": wake_time.isoformat(),
        "wake_is_user_set": False,
    })
    logging.info(f"非活跃时段，推迟到 {wake_time.strftime('%m-%d %H:%M')}")


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

async def make_forge_callback(chat: ChatProcess):
    async def on_result(total_input: int):
        if total_input < FORGE_THRESHOLD:
            return
        logging.info(f"触发 forge-reload: total_input={total_input}")
        try:
            transcript_dir = find_transcript_dir(chat.session_id)
            new_sid = forge_reload(chat.session_id, transcript_dir, RETAIN_TOKENS)
            state = load_state()
            history = state.get("forge_history", {})
            history[chat.session_id] = new_sid
            chat.session_id = new_sid
            save_state({"session_id": new_sid, "forge_history": history})
            await chat.interrupt()
            await bot.send_message(
                chat_id=TG_CHAT_ID,
                text=f"🔄 上下文已滑动（{total_input:,} tokens），开了新 session，记忆库里的都还在。"
            )
        except Exception as e:
            logging.error(f"forge-reload 失败: {e}")
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


# ── main ──────────────────────────────────────────────────────────────────────

async def main():
    state = load_state()

    chat = ChatProcess(project_dir=PROJECT_DIR, save_state_fn=save_state)
    if state.get("session_id"):
        chat.session_id = state["session_id"]

    forge_cb = await make_forge_callback(chat)
    chat.set_forge_callback(forge_cb)

    bot = Bot(token=TG_BOT_TOKEN)
    message_queue: asyncio.Queue = asyncio.Queue()

    # ── handlers ──────────────────────────────────────────────────────────────

    async def handle_message(update: Update, context):
        if not update.message or update.effective_chat.id != TG_CHAT_ID:
            return
        await message_queue.put(update.message.text or "")

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
            save_state({"session_id": new_sid, "forge_history": history})
            await chat.interrupt()
            await update.message.reply_text(f"forge 完成，新 session: {new_sid[:8]}…")
        except Exception as e:
            await update.message.reply_text(f"forge 失败: {e}")

    async def handle_usage(update: Update, context):
        if update.effective_chat.id != TG_CHAT_ID:
            return
        usage = chat._current_usage
        if not usage:
            await update.message.reply_text("暂无 usage 数据。")
            return
        total = (
            usage.get("input_tokens", 0)
            + usage.get("cache_creation_input_tokens", 0)
            + usage.get("cache_read_input_tokens", 0)
        )
        pct = total / 200_000 * 100
        await update.message.reply_text(
            f"context 占用：{total:,} tokens（约 {pct:.1f}%）\n"
            f"forge 阈值：{FORGE_THRESHOLD:,}"
        )

    # ── message processor ─────────────────────────────────────────────────────

    async def message_processor():
        while True:
            text = await message_queue.get()
            save_state({"last_chat_time": now_local().isoformat()})

            # 补发之前因网络问题没发出的通知
            state = load_state()
            if state.get("pending_notice"):
                ok = await _send_with_retry(bot, state["pending_notice"])
                if ok:
                    save_state({"pending_notice": None})
            try:
                result = await chat.send(text)
                reply, nw = extract_next_wake(result["text"])
                if nw:
                    set_next_wake(nw, user_set=True)
                await send_reply(bot, reply, thinking=result["thinking"])
            except Exception as e:
                logging.error(f"消息处理失败: {e}")
                await bot.send_message(chat_id=TG_CHAT_ID, text="（出了点问题，请稍后再试）")

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

        wakeup_msg = (
            f"[WAKEUP]\n"
            f"现在是 {now_str}，距离上次聊天已经过去了 {silence}。\n"
            f"这是你的自由时间。请按照 CLAUDE.md 中的唤醒行为规则回复。"
        )

        try:
            result = await chat.send(wakeup_msg)
            parsed = parse_wakeup_reply(result["text"])

            if parsed["action"] == "message" and parsed["content"]:
                ok = await send_reply(bot, parsed["content"], thinking=result["thinking"])
                if not ok:
                    # 记录发送失败，下次网络恢复时补通知
                    state = load_state()
                    state["pending_notice"] = f"网络波动了，刚才 {now_local().strftime('%H:%M')} 想找你，但消息没发出去。"
                    save_state(state)

            set_next_wake(parsed["next_minutes"])
        except Exception as e:
            logging.error(f"唤醒流程失败: {e}")
            set_next_wake(DEFAULT_INTERVAL)

    # ── idle reclaim ──────────────────────────────────────────────────────────

    async def idle_check():
        if chat.is_idle(idle_seconds=1800):
            await chat.stop()
            logging.info("子进程因空闲 30 分钟已回收，session_id 保留")

    # ── app setup ─────────────────────────────────────────────────────────────

    app = Application.builder().token(TG_BOT_TOKEN).build()
    app.add_handler(CommandHandler("stop", handle_stop))
    app.add_handler(CommandHandler("forge", handle_forge))
    app.add_handler(CommandHandler("usage", handle_usage))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    scheduler = AsyncIOScheduler(timezone=TZ)
    scheduler.add_job(scheduled_wake_check, "interval", minutes=5)
    scheduler.add_job(idle_check, "interval", minutes=5)
    scheduler.start()

    set_next_wake(DEFAULT_INTERVAL)

    proc_task = asyncio.create_task(message_processor())

    async with app:
        await app.initialize()
        await app.start()
        await app.updater.start_polling()
        logging.info("小予 daemon 已启动")
        try:
            await asyncio.Event().wait()
        finally:
            proc_task.cancel()
            scheduler.shutdown()
            await chat.stop()
            await app.updater.stop()
            await app.stop()


if __name__ == "__main__":
    asyncio.run(main())
