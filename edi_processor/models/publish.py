from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class PublishResult:
    source: Path
    destination: Path | None
    succeeded: bool
    skipped: bool = False
    error_code: str | None = None
    message: str | None = None
