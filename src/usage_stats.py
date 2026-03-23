"""文本输入统计持久化。"""

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path


@dataclass(frozen=True)
class UsageSnapshot:
    """当前统计快照。"""

    today_chars: int
    total_chars: int


class UsageStatsStore:
    """管理每日与历史累计字符统计。"""

    def __init__(self, stats_path: Path):
        self.stats_path = stats_path

    def record_input(self, char_count: int, today: date | None = None) -> UsageSnapshot:
        """记录一次成功输入并返回最新统计。"""
        today = today or date.today()
        payload = self._load()
        current_day = today.isoformat()

        daily = payload.setdefault("daily_chars", {})
        daily[current_day] = int(daily.get(current_day, 0)) + char_count
        payload["total_chars"] = int(payload.get("total_chars", 0)) + char_count

        self._save(payload)
        return UsageSnapshot(today_chars=daily[current_day], total_chars=payload["total_chars"])

    def _load(self) -> dict:
        if not self.stats_path.exists():
            return {"total_chars": 0, "daily_chars": {}}

        try:
            with open(self.stats_path, "r", encoding="utf-8") as file:
                payload = json.load(file)
        except (json.JSONDecodeError, OSError, TypeError, ValueError):
            return {"total_chars": 0, "daily_chars": {}}

        if not isinstance(payload, dict):
            return {"total_chars": 0, "daily_chars": {}}

        daily = payload.get("daily_chars")
        if not isinstance(daily, dict):
            daily = {}

        normalized_daily = {}
        for key, value in daily.items():
            try:
                normalized_daily[str(key)] = int(value)
            except (TypeError, ValueError):
                continue

        try:
            total_chars = int(payload.get("total_chars", 0))
        except (TypeError, ValueError):
            total_chars = 0

        return {"total_chars": total_chars, "daily_chars": normalized_daily}

    def _save(self, payload: dict) -> None:
        self.stats_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.stats_path, "w", encoding="utf-8") as file:
            json.dump(payload, file, ensure_ascii=False, indent=2)
