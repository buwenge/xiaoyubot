import json
import pathlib
from datetime import datetime

LOG_FILE = pathlib.Path(__file__).parent / "logs.jsonl"


def write_log(level: str, category: str, message: str, detail: dict = None) -> dict:
    entry = {
        "timestamp": datetime.now().isoformat(),
        "level": level,
        "category": category,
        "message": message,
    }
    if detail:
        entry["detail"] = detail
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry


def read_logs(filter_category: str = "all", limit: int = 50) -> list:
    if not LOG_FILE.exists():
        return []
    logs = []
    with open(LOG_FILE, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if filter_category != "all" and entry.get("category") != filter_category:
                continue
            logs.append(entry)
    return logs[-limit:]
