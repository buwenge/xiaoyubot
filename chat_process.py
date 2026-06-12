import asyncio
import json
import logging
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
]


class ChatProcess:
    def __init__(self, project_dir: str, save_state_fn):
        self.project_dir = project_dir
        self.save_state = save_state_fn
        self.proc = None
        self.session_id = None
        self.last_activity = time.time()
        self._response_buffer = ""
        self._thinking_buffer = ""
        self._response_complete = asyncio.Event()
        self._forge_callback = None
        self._current_usage = {}
        self.last_cost_usd = 0.0
        self.is_error = False
        self.error_status = None

    def set_forge_callback(self, fn):
        self._forge_callback = fn

    async def spawn(self, resume_sid=None):
        args = list(CLAUDE_CMD)
        if resume_sid:
            args += ["--resume", resume_sid]
        self.proc = await asyncio.create_subprocess_exec(
            *args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=self.project_dir,
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

        try:
            await asyncio.wait_for(self._response_complete.wait(), timeout=300)
        except asyncio.TimeoutError:
            logging.warning("Claude Code 回复超时（300s）")

        return {"text": self._response_buffer, "thinking": self._thinking_buffer}

    async def _pump_stdout(self):
        async for raw_line in self.proc.stdout:
            line = raw_line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue

            ev_type = ev.get("type", "")

            if ev_type == "system" and ev.get("subtype") == "init":
                logging.info(f"[CC init] model={ev.get('model')} session={ev.get('session_id')}")

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
                    if texts:
                        self._response_buffer = "".join(texts)
                    if thinking:
                        self._thinking_buffer = "\n\n".join(thinking)

            elif ev_type == "result":
                self.session_id = ev.get("session_id", self.session_id)
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
                state["session_id"] = self.session_id
                state["session_cost_usd"] = state.get("session_cost_usd", 0) + self.last_cost_usd
                self.save_state(state)

                usage = self._current_usage
                total_input = (
                    usage.get("input_tokens", 0)
                    + usage.get("cache_creation_input_tokens", 0)
                    + usage.get("cache_read_input_tokens", 0)
                )
                logging.info(
                    f"result: session={self.session_id} "
                    f"new={usage.get('input_tokens',0)} "
                    f"cache_read={usage.get('cache_read_input_tokens',0)} "
                    f"cache_write={usage.get('cache_creation_input_tokens',0)} "
                    f"output={usage.get('output_tokens',0)} "
                    f"total_input={total_input} "
                    f"cost=${self.last_cost_usd:.4f} is_error={self.is_error}"
                )

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
