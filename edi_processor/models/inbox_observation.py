from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class InboxObservationResult:
    expected_file_name: str
    observed_path: Path | None
    status: str
    message: str | None = None

    @property
    def succeeded(self) -> bool:
        return self.status == "observed_non_empty"
