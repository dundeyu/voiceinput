"""本地词汇修正建议收集。"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass(frozen=True)
class VocabularySuggestion:
    """一条词汇修正建议。"""

    wrong_text: str
    suggested_text: str
    note: str
    created_at: str


class VocabularySuggestionStore:
    """将建议以 JSONL 方式追加保存到本地。"""

    def __init__(self, suggestions_path: Path):
        self.suggestions_path = suggestions_path

    def record(self, wrong_text: str, suggested_text: str, note: str = "") -> VocabularySuggestion:
        suggestion = VocabularySuggestion(
            wrong_text=wrong_text.strip(),
            suggested_text=suggested_text.strip(),
            note=note.strip(),
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        self.suggestions_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.suggestions_path, "a", encoding="utf-8") as file:
            file.write(json.dumps(asdict(suggestion), ensure_ascii=False) + "\n")
        return suggestion

    def list_recent(self, limit: int = 50) -> list[VocabularySuggestion]:
        if limit <= 0 or not self.suggestions_path.exists():
            return []

        suggestions: list[VocabularySuggestion] = []
        with open(self.suggestions_path, "r", encoding="utf-8") as file:
            for raw_line in file:
                line = raw_line.strip()
                if not line:
                    continue
                payload = json.loads(line)
                suggestions.append(
                    VocabularySuggestion(
                        wrong_text=str(payload.get("wrong_text", "")).strip(),
                        suggested_text=str(payload.get("suggested_text", "")).strip(),
                        note=str(payload.get("note", "")).strip(),
                        created_at=str(payload.get("created_at", "")).strip(),
                    )
                )

        return suggestions[-limit:][::-1]

    def remove(self, wrong_text: str, suggested_text: str, created_at: str) -> bool:
        if not self.suggestions_path.exists():
            return False

        removed = False
        kept_lines: list[str] = []
        with open(self.suggestions_path, "r", encoding="utf-8") as file:
            for raw_line in file:
                line = raw_line.strip()
                if not line:
                    continue
                payload = json.loads(line)
                matches = (
                    str(payload.get("wrong_text", "")).strip() == wrong_text.strip()
                    and str(payload.get("suggested_text", "")).strip() == suggested_text.strip()
                    and str(payload.get("created_at", "")).strip() == created_at.strip()
                )
                if matches and not removed:
                    removed = True
                    continue
                kept_lines.append(json.dumps(payload, ensure_ascii=False))

        if removed:
            self.suggestions_path.write_text(
                "".join(f"{line}\n" for line in kept_lines),
                encoding="utf-8",
            )
        return removed
