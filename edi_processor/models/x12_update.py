from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class X12DateUpdateResult:
    path: Path
    succeeded: bool
    updated_segments: int = 0
    message: str | None = None
    error_code: str | None = None
