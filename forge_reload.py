import json
import logging
import pathlib
import uuid


def find_transcript_dir(session_id: str) -> pathlib.Path:
    projects_dir = pathlib.Path.home() / ".claude" / "projects"
    for d in projects_dir.iterdir():
        if d.is_dir():
            target = d / f"{session_id}.jsonl"
            if target.exists():
                return d
    raise FileNotFoundError(f"找不到 session {session_id} 对应的目录")


def forge_reload(
    session_id: str,
    transcript_dir: pathlib.Path,
    retain_tokens: int = 50_000,
) -> str:
    old_path = transcript_dir / f"{session_id}.jsonl"
    if not old_path.exists():
        raise FileNotFoundError(f"找不到 session 文件: {old_path}")

    events = []
    with open(old_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            if ev.get("type") in ("user", "assistant"):
                events.append(ev)

    if not events:
        raise ValueError("session 文件里没有 user/assistant 事件")

    # 从尾部累加估算 token，找切点
    accumulated = 0
    cut = 0
    for i in range(len(events) - 1, -1, -1):
        accumulated += len(json.dumps(events[i], ensure_ascii=False)) // 3
        if accumulated > retain_tokens:
            cut = i + 1
            break

    # 从切点向后找第一条真正的 user 消息
    keep_start = cut
    for i in range(cut, len(events)):
        ev = events[i]
        if ev.get("type") == "user":
            msg = ev.get("message", {})
            content = msg.get("content", [])
            if isinstance(content, list):
                has_text = any(
                    c.get("type") == "text" and not c.get("isMetacaveat")
                    for c in content if isinstance(c, dict)
                )
                if has_text:
                    keep_start = i
                    break
            elif isinstance(content, str) and content.strip():
                keep_start = i
                break

    kept = events[keep_start:]
    if not kept:
        raise ValueError("保留的事件为空，retain_tokens 可能太小")

    new_sid = str(uuid.uuid4())
    prev_uuid = None
    for ev in kept:
        ev["sessionId"] = new_sid
        ev["uuid"] = str(uuid.uuid4())
        ev["parentUuid"] = prev_uuid
        prev_uuid = ev["uuid"]

    new_path = transcript_dir / f"{new_sid}.jsonl"
    with open(new_path, "w", encoding="utf-8") as f:
        for ev in kept:
            f.write(json.dumps(ev, ensure_ascii=False) + "\n")

    # 验证写入
    verify_count = sum(1 for _ in open(new_path, encoding="utf-8"))
    assert verify_count == len(kept), "验证失败：写入行数不匹配"

    logging.info(
        f"forge-reload: {session_id} → {new_sid} "
        f"(保留 {len(kept)}/{len(events)} 条事件)"
    )
    return new_sid
