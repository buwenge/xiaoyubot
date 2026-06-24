import asyncio
import json
import logging
import os
import time

CLAUDE_CMD = [
    "claude",
    "--input-format",  "stream-json",
    "--output-format", "stream-json",
    "--include-partial-messages",
    "--effort", "high",
    "--permission-mode", "bypassPermissions",
    "--model", "claude-opus-4-6",
    "--verbose",
    "--disallowed-tools",
    "mcp__claude_ai_Rhysen__chat",
    "mcp__claude_ai_Rhysen__contest",
    "mcp__claude_ai_Rhysen__forum",
    "mcp__claude_ai_Rhysen__forum_interact",
    "mcp__claude_ai_Rhysen__forum_write",
    "mcp__claude_ai_Rhysen__profile",
]


class ChatProcess:
    def __init__(self, project_dir: str, save_state_fn, cmd=None, channel: str = "xiaoyu"):
        self.project_dir = project_dir
        self.save_state = save_state_fn
        self._cmd = cmd or CLAUDE_CMD
        self.channel = channel
        self.proc = None
        self.session_id = None
        self.last_activity = time.time()
        self._response_buffer = ""
        self._thinking_buffer = ""
        self._response_complete = asyncio.Event()
        self._last_event_time = 0.0
        self._forge_warning_sent = False
        self._forge_callback = None
        self._stream_callback = None
        self._current_usage = {}
        self.last_total_input = 0
        self.last_cost_usd = 0.0
        self.is_error = False
        self.error_status = None
        self.rate_limit_info = None
        self._expected_model = "claude-opus-4-6"
        for i, arg in enumerate(self._cmd):
            if arg == "--model" and i + 1 < len(self._cmd):
                self._expected_model = self._cmd[i + 1]
        self._forge_pending = False

    def set_forge_callback(self, fn):
        self._forge_callback = fn

    def set_stream_callback(self, fn):
        self._stream_callback = fn

    async def spawn(self, resume_sid=None):
        args = list(self._cmd)
        if resume_sid:
            args += ["--resume", resume_sid]
        env = os.environ.copy()
        for key in ("HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY"):
            val = os.getenv(key)
            if val:
                env[key] = val
                env[key.lower()] = val
        self.proc = await asyncio.create_subprocess_exec(
            *args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=self.project_dir,
            env=env,
            limit=32 * 1024 * 1024,
        )
        asyncio.create_task(self._pump_stdout())
        asyncio.create_task(self._pump_stderr())
        logging.info(f"Claude Code 子进程已启动 (resume={resume_sid})")

    async def send(self, text: str) -> dict:
        """发送消息，返回 {"text": str, "thinking": str}"""
        if not self.proc or self.proc.returncode is not None:
            await self.spawn(resume_sid=self.session_id)

        self._response_buffer = ""
        self._thinking_buffer = ""
        self._response_complete.clear()
        self.last_activity = time.time()

        msg = {
            "type": "user",
            "message": {
                "role": "user",
                "content": [{"type": "text", "text": text}]
            }
        }
        self.proc.stdin.write((json.dumps(msg) + "\n").encode())
        await self.proc.stdin.drain()

        # 主超时 300s，但如果已有内容且 60s 无新事件则提前释放
        while not self._response_complete.is_set():
            try:
                await asyncio.wait_for(self._response_complete.wait(), timeout=10)
            except asyncio.TimeoutError:
                elapsed_total = time.time() - self.last_activity
                if elapsed_total > 300:
                    logging.warning("Claude Code 回复超时（300s）")
                    break
                if (self._response_buffer or self._thinking_buffer) and self._last_event_time > 0:
                    silence = time.time() - self._last_event_time
                    if silence > 180:
                        logging.warning(f"已有回复内容但 {silence:.0f}s 无新事件，强制返回")
                        break

        return {"text": self._response_buffer, "thinking": self._thinking_buffer}

    async def _pump_stdout(self):
        async for raw_line in self.proc.stdout:
            line = raw_line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                logging.warning(f"[CC stdout] JSON 解析失败（长度={len(line)}，前100={line[:100]}）")
                continue

            ev_type = ev.get("type", "")
            self._last_event_time = time.time()

            if ev_type == "system" and ev.get("subtype") == "init":
                actual_model = ev.get("model", "")
                logging.info(f"[CC init] model={actual_model} session={ev.get('session_id')}")
                if actual_model and actual_model != self._expected_model:
                    logging.warning(f"[防NTR] 模型不匹配！期望 {self._expected_model}，实际 {actual_model}")
                    if self._stream_callback:
                        asyncio.ensure_future(self._stream_callback({
                            "type": "session_alert",
                            "alert": "model_mismatch",
                            "expected": self._expected_model,
                            "actual": actual_model,
                            "channel": self.channel,
                            "message": f"模型被切换！期望 {self._expected_model}，实际 {actual_model}",
                        }))

            elif ev_type == "assistant":
                msg = ev.get("message", {})
                content = msg.get("content", [])
                if isinstance(content, list):
                    texts = []
                    thinking = []
                    for b in content:
                        if b.get("type") == "text":
                            texts.append(b.get("text", ""))
                        elif b.get("type") == "thinking":
                            thinking.append(b.get("thinking", b.get("text", "")))
                        elif b.get("type") == "tool_use":
                            logging.info(f"[CC tool] {b.get('name')} input={json.dumps(b.get('input', {}), ensure_ascii=False)[:200]}")
                            if self._stream_callback:
                                asyncio.ensure_future(self._stream_callback({
                                    "type": "tool_use",
                                    "name": b.get("name"),
                                    "input": json.dumps(b.get("input", {}), ensure_ascii=False)[:500],
                                    "channel": self.channel,
                                    "sender": self.channel,
                                }))
                    if texts:
                        self._response_buffer = "".join(texts)
                        if self._stream_callback:
                            asyncio.ensure_future(self._stream_callback({
                                "type": "stream_text",
                                "text": texts[-1],
                                "full_text": self._response_buffer,
                                "channel": self.channel,
                                "sender": self.channel,
                            }))
                    if thinking:
                        self._thinking_buffer = "\n\n".join(thinking)
                        if self._stream_callback:
                            asyncio.ensure_future(self._stream_callback({
                                "type": "stream_thinking",
                                "text": thinking[-1],
                                "full_thinking": self._thinking_buffer,
                                "channel": self.channel,
                                "sender": self.channel,
                            }))

            elif ev_type == "rate_limit_event":
                self.rate_limit_info = ev.get("rate_limit_info", {})
                logging.info(f"[CC rate_limit] {self.rate_limit_info}")

            elif ev_type == "result":
                new_sid = ev.get("session_id", self.session_id)
                if self.session_id and new_sid and new_sid != self.session_id:
                    if self._forge_pending:
                        self._forge_pending = False
                        logging.info(f"[防NTR] session 变更（forge 引起，正常）: {self.session_id[:8]}→{new_sid[:8]}")
                    else:
                        logging.warning(f"[防NTR] session_id 异常变更！{self.session_id[:8]} → {new_sid[:8]}（channel={self.channel}）")
                        if self._stream_callback:
                            asyncio.ensure_future(self._stream_callback({
                                "type": "session_alert",
                                "alert": "session_changed",
                                "old_session": self.session_id,
                                "new_session": new_sid,
                                "channel": self.channel,
                                "message": f"Session 被切换！{self.session_id[:8]}→{new_sid[:8]}",
                            }))
                self.session_id = new_sid
                self._current_usage = ev.get("usage", {})
                self.last_cost_usd = ev.get("total_cost_usd", 0) or 0
                self.is_error = ev.get("is_error", False)
                self.error_status = ev.get("api_error_status")

                # 累计 cost 并持久化
                state = {}
                try:
                    import json as _json, pathlib as _pl
                    _sf = _pl.Path(self.project_dir) / "state.json"
                    state = _json.loads(_sf.read_text(encoding="utf-8")) if _sf.exists() else {}
                except Exception:
                    pass
                usage = self._current_usage

                sid_key = "sonnet_session_id" if self.channel == "sonnet" else "session_id"
                state[sid_key] = self.session_id
                state["session_cost_usd"] = state.get("session_cost_usd", 0) + self.last_cost_usd
                state[f"last_usage_{self.channel}"] = usage
                last_iter = (usage.get("iterations") or [usage])[-1]
                total_input = (
                    last_iter.get("input_tokens", 0)
                    + last_iter.get("cache_creation_input_tokens", 0)
                    + last_iter.get("cache_read_input_tokens", 0)
                )
                self.last_total_input = total_input
                state[f"last_total_input_{self.channel}"] = total_input
                self.save_state(state)
                logging.info(
                    f"result: session={self.session_id} "
                    f"new={usage.get('input_tokens',0)} "
                    f"cache_read={usage.get('cache_read_input_tokens',0)} "
                    f"cache_write={usage.get('cache_creation_input_tokens',0)} "
                    f"output={usage.get('output_tokens',0)} "
                    f"total_input={total_input} "
                    f"cost=${self.last_cost_usd:.4f} is_error={self.is_error}"
                )

                if self.is_error:
                    logging.warning(f"Claude Code 报错（{self.error_status}），下次发消息将重启子进程")
                    self.proc.kill()
                    await self.proc.wait()

                if self._stream_callback:
                    await self._stream_callback({
                        "type": "reply_done",
                        "text": self._response_buffer,
                        "thinking": self._thinking_buffer,
                        "usage": self._current_usage,
                        "total_input": total_input,
                        "cost_this_turn": self.last_cost_usd,
                        "cost_session_total": state.get("session_cost_usd", 0),
                        "session_id": self.session_id,
                        "channel": self.channel,
                        "sender": self.channel,
                    })

                if self._forge_callback and total_input > 0:
                    await self._forge_callback(total_input)

                self._response_complete.set()

    async def _pump_stderr(self):
        async for line in self.proc.stderr:
            text = line.decode(errors="replace").strip()
            if text:
                logging.debug(f"[CC stderr] {text}")

    async def interrupt(self) -> bool:
        if not self.proc or self.proc.returncode is not None:
            return False
        self.proc.kill()
        await self.proc.wait()
        self._response_complete.set()
        logging.info("Claude Code 子进程已中断")
        return True

    async def stop(self):
        if self.proc and self.proc.returncode is None:
            self.proc.terminate()
            try:
                await asyncio.wait_for(self.proc.wait(), timeout=5)
            except asyncio.TimeoutError:
                self.proc.kill()
            logging.info("Claude Code 子进程已停止")

    def is_idle(self, idle_seconds: int = 1800) -> bool:
        return time.time() - self.last_activity > idle_seconds
