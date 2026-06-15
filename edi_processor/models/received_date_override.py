from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path


@dataclass(frozen=True)
class ReceivedDateOverrides:
    source_path: Path
    values: dict[tuple[str, str], date]
    parsed_successfully: bool
    messages: tuple[str, ...] = ()

    def find(self, provider_key: str, file_name: str) -> date | None:
        return self.values.get((provider_key, file_name))
