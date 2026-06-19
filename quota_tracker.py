import json
import pathlib
import time
from collections import deque

QUOTA_FILE = pathlib.Path(__file__).parent / "quota_history.jsonl"
WINDOW_5H = 5 * 3600
WINDOW_WEEKLY = 7 * 24 * 3600


class QuotaTracker:
    def __init__(self):
        self.records: deque = deque()
        self._load()

    def _load(self):
        if not QUOTA_FILE.exists():
            return
        cutoff = time.time() - WINDOW_WEEKLY
        with open(QUOTA_FILE, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if rec.get("timestamp", 0) >= cutoff:
                    self.records.append(rec)

    def record(self, input_tokens: int, output_tokens: int, cache_read: int, cache_write: int):
        entry = {
            "timestamp": time.time(),
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cache_read": cache_read,
            "cache_write": cache_write,
        }
        self.records.append(entry)
        with open(QUOTA_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
        self._prune()

    def _prune(self):
        cutoff = time.time() - WINDOW_WEEKLY
        while self.records and self.records[0].get("timestamp", 0) < cutoff:
            self.records.popleft()

    def _calc_window(self, window_seconds: int, limit: int) -> dict:
        now = time.time()
        cutoff = now - window_seconds
        window_records = [r for r in self.records if r.get("timestamp", 0) >= cutoff]
        total_input = sum(
            r.get("input_tokens", 0) + r.get("cache_read", 0) + r.get("cache_write", 0)
            for r in window_records
        )
        total_output = sum(r.get("output_tokens", 0) for r in window_records)

        oldest_ts = min((r["timestamp"] for r in window_records), default=now)
        refresh_remaining = max(0, oldest_ts + window_seconds - now)

        return {
            "window_input_tokens": total_input,
            "window_output_tokens": total_output,
            "limit": limit,
            "percentage": round(total_input / limit * 100, 1) if limit > 0 else 0,
            "window_start": cutoff,
            "record_count": len(window_records),
            "refresh_remaining_seconds": round(refresh_remaining),
        }

    def get_usage(self, limit: int) -> dict:
        self._prune()
        return self._calc_window(WINDOW_5H, limit)

    def get_weekly_usage(self, limit: int) -> dict:
        self._prune()
        return self._calc_window(WINDOW_WEEKLY, limit)
