from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DuplicateCheckResult:
    is_duplicate: bool
    succeeded: bool = True
    message: str | None = None
    error_code: str | None = None
