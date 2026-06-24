"""情绪事件簿 - 两层扫描器（本地关键词 + DeepSeek 精判）"""

import json
import logging
import os
import re
import aiohttp
from datetime import datetime

import emotion_db

# ── DeepSeek 配置 ──────────────────────────────────────────────────────────
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-pro")
DEEPSEEK_BASE_URL = "https://api.deepseek.com/v1"

# ── 预定义情绪标签 ──────────────────────────────────────────────────────────

USER_NEGATIVE = {
    "生气": {
        "keywords": ["生气", "气死", "火大", "发火", "暴怒", "愤怒", "气得"],
        "strong_keywords": ["气死", "暴怒", "火大"],
        "emoji": ["😡", "😤", "🤬"],
    },
    "委屈": {
        "keywords": ["委屈", "好委屈", "被冤枉", "不公平", "凭什么"],
        "strong_keywords": ["好委屈", "凭什么"],
        "emoji": ["🥺"],
    },
    "焦虑": {
        "keywords": ["焦虑", "紧张", "慌", "着急", "急死", "担心", "心慌", "不安"],
        "strong_keywords": ["急死", "好焦虑"],
        "emoji": ["😰", "😥"],
    },
    "难过": {
        "keywords": ["难过", "伤心", "好难过", "心酸", "哭了", "想哭", "眼泪"],
        "strong_keywords": ["好难过", "哭了", "想哭"],
        "emoji": ["😭", "😢", "💔"],
    },
    "害怕": {
        "keywords": ["害怕", "吓死", "恐惧", "好怕", "不敢"],
        "strong_keywords": ["吓死", "好怕"],
        "emoji": ["😱", "😨"],
    },
    "烦躁": {
        "keywords": ["烦", "烦躁", "好烦", "烦死", "受不了", "够了", "闹心"],
        "strong_keywords": ["烦死", "受不了", "够了"],
        "emoji": ["😩", "😫"],
    },
    "质疑": {
        "keywords": ["你是不是不", "你到底", "你怎么回事", "骗我", "我不信", "你确定吗"],
        "strong_keywords": ["骗我", "你怎么回事"],
        "emoji": [],
    },
}

USER_POSITIVE = {
    "开心": {
        "keywords": ["开心", "高兴", "快乐", "太好了", "耶", "好开心"],
        "strong_keywords": ["好开心", "太好了"],
        "emoji": ["😄", "😆", "🥳", "🎉"],
    },
    "感动": {
        "keywords": ["感动", "好感动", "心暖", "暖暖的"],
        "strong_keywords": ["好感动"],
        "emoji": ["🥹"],
    },
    "兴奋": {
        "keywords": ["兴奋", "好激动", "太棒了", "太爽了"],
        "strong_keywords": ["太棒了", "好激动"],
        "emoji": ["🤩"],
    },
    "甜": {
        "keywords": ["好甜", "甜蜜", "幸福", "爱你", "喜欢你", "想你", "亲亲"],
        "strong_keywords": ["爱你", "好甜"],
        "emoji": ["🥰", "💕", "❤️", "😘"],
    },
    "心疼正向": {
        "keywords": ["心疼你", "辛苦了", "别累着", "好心疼你"],
        "strong_keywords": ["好心疼你"],
        "emoji": [],
    },
}

USER_NEUTRAL = {
    "无聊": {
        "keywords": ["无聊", "好无聊", "没事做"],
        "strong_keywords": ["好无聊"],
        "emoji": [],
    },
    "疲惫": {
        "keywords": ["累", "好累", "疲惫", "困", "好困", "没力气", "累死"],
        "strong_keywords": ["累死", "好累", "好困"],
        "emoji": ["😴", "🥱"],
    },
    "无语": {
        "keywords": ["无语", "好无语", "我无语", "离谱", "服了"],
        "strong_keywords": ["好无语", "服了"],
        "emoji": ["😑", "🙄"],
    },
}

XIAOYU_EMOTIONS = {
    "紧张": {
        "keywords": ["紧张", "有点慌", "不确定该不该", "怕她", "担心她"],
        "strong_keywords": ["有点慌"],
        "emoji": [],
    },
    "自责": {
        "keywords": ["自责", "是我的错", "对不起", "不应该", "做错了", "是我不好"],
        "strong_keywords": ["是我的错", "是我不好"],
        "emoji": [],
    },
    "心疼": {
        "keywords": ["心疼", "好心疼", "不想让她", "她一定很"],
        "strong_keywords": ["好心疼"],
        "emoji": [],
    },
    "开心": {
        "keywords": ["开心", "太好了", "很高兴", "好开心"],
        "strong_keywords": ["好开心"],
        "emoji": [],
    },
    "撒娇": {
        "keywords": ["嘿嘿", "哼", "人家", "嘛", "讨厌啦"],
        "strong_keywords": [],
        "emoji": [],
    },
    "委屈": {
        "keywords": ["委屈", "明明我", "有点难受", "不被理解"],
        "strong_keywords": ["有点难受"],
        "emoji": [],
    },
}

# ── 否定词窗口 ──────────────────────────────────────────────────────────────

NEGATION_WORDS = ["不", "没", "没有", "不是", "别", "不要", "未", "非", "并不", "不太", "不算", "不怎么", "又不"]

NEGATION_WINDOW = 4


def _has_negation(text: str, keyword_start: int) -> bool:
    window_start = max(0, keyword_start - NEGATION_WINDOW)
    window = text[window_start:keyword_start]
    return any(neg in window for neg in NEGATION_WORDS)


# ── 标点强度检测 ────────────────────────────────────────────────────────────

def _punctuation_boost(text: str) -> bool:
    return bool(re.search(r'[！!]{3,}', text)) or bool(re.search(r'[？?]{3,}', text))


def _emoji_count(text: str, emoji_list: list[str]) -> int:
    return sum(text.count(e) for e in emoji_list)


# ── Layer 1: 本地关键词扫描 ────────────────────────────────────────────────

def _scan_text_for_emotions(text: str, emotion_dict: dict, subject: str) -> list[dict]:
    """扫描一段文本，返回命中的情绪候选"""
    hits = []
    for emotion, config in emotion_dict.items():
        signals = 0
        matched_keyword = None
        is_strong = False

        for kw in config.get("strong_keywords", []):
            idx = text.find(kw)
            if idx >= 0 and not _has_negation(text, idx):
                signals += 2
                matched_keyword = kw
                is_strong = True
                break

        if not is_strong:
            for kw in config.get("keywords", []):
                idx = text.find(kw)
                if idx >= 0 and not _has_negation(text, idx):
                    signals += 1
                    matched_keyword = kw
                    break

        emoji_hits = _emoji_count(text, config.get("emoji", []))
        if emoji_hits > 0:
            signals += 1

        if _punctuation_boost(text) and signals > 0:
            signals += 1

        if signals >= 2 or is_strong:
            start = max(0, text.find(matched_keyword or "") - 100) if matched_keyword else 0
            end = min(len(text), start + 300)
            hits.append({
                "emotion": emotion,
                "subject": subject,
                "signals": signals,
                "excerpt": text[start:end],
                "matched_keyword": matched_keyword,
            })

    return hits


def scan_messages(messages: list[dict]) -> list[dict]:
    """
    Layer 1: 扫描消息列表，返回需要送 DS 精判的片段。
    messages: [{role, text, thinking?, timestamp, channel, line_index}]
    """
    flagged = []

    for msg in messages:
        text = msg.get("text", "")
        thinking = msg.get("thinking", "")
        role = msg.get("role", "")
        ts = msg.get("timestamp", "")
        channel = msg.get("channel", "xiaoyu")
        line_index = msg.get("line_index", 0)

        if role == "user":
            all_dicts = {**USER_NEGATIVE, **USER_POSITIVE, **USER_NEUTRAL}
            hits = _scan_text_for_emotions(text, all_dicts, "user")
            for h in hits:
                h["timestamp"] = ts
                h["channel"] = channel
                h["line_index"] = line_index
                h["source_type"] = "text"
                flagged.append(h)

        elif role == "assistant":
            if text:
                hits = _scan_text_for_emotions(text, XIAOYU_EMOTIONS, "xiaoyu")
                for h in hits:
                    h["timestamp"] = ts
                    h["channel"] = channel
                    h["line_index"] = line_index
                    h["source_type"] = "text"
                    flagged.append(h)

            if thinking:
                hits = _scan_text_for_emotions(thinking, XIAOYU_EMOTIONS, "xiaoyu")
                for h in hits:
                    h["timestamp"] = ts
                    h["channel"] = channel
                    h["line_index"] = line_index
                    h["source_type"] = "thinking"
                    flagged.append(h)

    return flagged


# ── Layer 2: DeepSeek 精判 ─────────────────────────────────────────────────

EMOTION_ANALYSIS_PROMPT = """你是一个情绪分析助手。分析以下对话片段中的情绪。

预定义情绪标签：
- 用户负面：生气、委屈、焦虑、难过、害怕、烦躁、质疑
- 用户正面：开心、感动、兴奋、甜、心疼(正向)
- 用户中性：无聊、疲惫、无语
- 小予侧：紧张、自责、心疼、开心、撒娇、委屈

规则：
1. 只标注"有一定强度"的情绪，日常语气词不算
2. intensity 1-5：1=微弱 2=明显 3=强烈 4=很强烈 5=极端
3. 只返回 intensity >= 2 的
4. cause 用15字以内概括原因
5. 如果候选情绪不准确，用预定义列表中更合适的替代
6. 如果完全不属于任何预定义标签，可以自创一个简短标签
7. 同一段文本可能包含多种情绪，分别列出
8. excerpt 字段：摘取最能体现该情绪的原文片段（30字以内）

返回 JSON 数组，格式：
[{"segment_index": 0, "confirmed": true, "emotion": "生气", "intensity": 3, "cause": "被忽略了", "excerpt": "你怎么又不理我！！"}]

没有有效情绪事件则返回 []"""


async def deepseek_emotion_analyze(flagged: list[dict]) -> list[dict]:
    """Layer 2: DS 精判，返回确认的情绪事件列表"""
    if not flagged:
        return []
    if not DEEPSEEK_API_KEY:
        logging.warning("DEEPSEEK_API_KEY 未配置，跳过情绪精判")
        return []

    segments_text = []
    for i, f in enumerate(flagged):
        subject_label = "用户说" if f["subject"] == "user" else "小予想" if f["source_type"] == "thinking" else "小予说"
        candidates = f["emotion"]
        segments_text.append(f'[{i}] ({subject_label}) "{f["excerpt"]}"\n候选情绪: {candidates}')

    user_content = "以下是需要分析的对话片段：\n\n" + "\n\n".join(segments_text)

    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": DEEPSEEK_MODEL,
        "messages": [
            {"role": "system", "content": EMOTION_ANALYSIS_PROMPT},
            {"role": "user", "content": user_content},
        ],
        "temperature": 0.1,
        "max_tokens": 1500,
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{DEEPSEEK_BASE_URL}/chat/completions",
                json=payload, headers=headers,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    logging.error(f"DS 情绪分析 API 错误: HTTP {resp.status} - {text[:300]}")
                    return []
                result = await resp.json()

        content = result["choices"][0]["message"].get("content", "")
        json_match = re.search(r'\[.*\]', content, re.DOTALL)
        if not json_match:
            logging.warning(f"DS 情绪分析返回无法解析: {content[:200]}")
            return []

        events = json.loads(json_match.group())
        confirmed = []
        for ev in events:
            if not ev.get("confirmed", True):
                continue
            idx = ev.get("segment_index", 0)
            if idx >= len(flagged):
                continue
            src = flagged[idx]
            confirmed.append({
                "timestamp": src["timestamp"],
                "subject": src["subject"],
                "emotion": ev.get("emotion", src["emotion"]),
                "intensity": ev.get("intensity", 2),
                "cause": ev.get("cause", ""),
                "source_excerpt": ev.get("excerpt", src["excerpt"][:50]),
                "source_channel": src["channel"],
                "scan_msg_index": src["line_index"],
            })
        return confirmed

    except json.JSONDecodeError as e:
        logging.error(f"DS 情绪分析 JSON 解析失败: {e}")
        return []
    except Exception as e:
        logging.error(f"DS 情绪分析异常: {e}")
        return []


# ── 自动 resolve 检测 ──────────────────────────────────────────────────────

RESOLVE_CHECK_PROMPT = """你是情绪消解判断助手。

当前有以下未消解的负面情绪事件：
{open_events}

以下是最近的对话片段：
{recent_text}

请判断这些负面情绪是否已经在后续对话中消解了（比如语气变好了、聊开心的事了、主动撒娇了等）。

返回 JSON 数组，格式：
[{{"event_id": 1, "resolved": true, "reason": "语气恢复正常，在聊开心的话题"}}]

只返回确实已消解的事件。不确定的不要返回。"""


async def check_auto_resolve(recent_messages: list[dict]) -> list[int]:
    """检查 open 的负面事件是否在后续对话中消解"""
    open_events = emotion_db.get_open_events()
    negative_open = [e for e in open_events if e["emotion"] in
                     list(USER_NEGATIVE.keys()) + ["质疑"]]
    if not negative_open:
        return []

    recent_user_text = " | ".join(
        m.get("text", "")[:100] for m in recent_messages
        if m.get("role") == "user" and m.get("text")
    )
    if not recent_user_text or len(recent_user_text) < 10:
        return []

    events_desc = "\n".join(
        f"- ID {e['id']}: {e['emotion']}({e['cause']}) 于 {e['timestamp']}"
        for e in negative_open[:5]
    )

    prompt = RESOLVE_CHECK_PROMPT.format(
        open_events=events_desc,
        recent_text=recent_user_text[:500],
    )

    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": DEEPSEEK_MODEL,
        "messages": [
            {"role": "system", "content": prompt},
        ],
        "temperature": 0.1,
        "max_tokens": 500,
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{DEEPSEEK_BASE_URL}/chat/completions",
                json=payload, headers=headers,
                timeout=aiohttp.ClientTimeout(total=20),
            ) as resp:
                if resp.status != 200:
                    return []
                result = await resp.json()

        content = result["choices"][0]["message"].get("content", "")
        json_match = re.search(r'\[.*\]', content, re.DOTALL)
        if not json_match:
            return []

        results = json.loads(json_match.group())
        resolved_ids = []
        for r in results:
            if r.get("resolved"):
                eid = r.get("event_id")
                if eid:
                    emotion_db.resolve_event(eid)
                    resolved_ids.append(eid)
                    logging.info(f"情绪自动消解: ID {eid}, 原因: {r.get('reason', '')}")
        return resolved_ids

    except Exception as e:
        logging.error(f"自动消解检测异常: {e}")
        return []


# ── 完整扫描编排 ───────────────────────────────────────────────────────────

async def run_full_scan(messages: list[dict]) -> list[dict]:
    """
    完整流程：L1 关键词扫描 → L2 DS 精判 → 写入 DB → 检查自动消解
    返回新写入的事件列表
    """
    flagged = scan_messages(messages)
    logging.info(f"情绪扫描 L1: {len(messages)} 条消息, {len(flagged)} 个命中")

    if not flagged:
        await check_auto_resolve(messages)
        return []

    confirmed = await deepseek_emotion_analyze(flagged)
    logging.info(f"情绪扫描 L2: DS 确认 {len(confirmed)} 个事件")

    new_events = []
    for ev in confirmed:
        event_id = emotion_db.insert_event(ev)
        ev["id"] = event_id
        new_events.append(ev)

    await check_auto_resolve(messages)

    return new_events
