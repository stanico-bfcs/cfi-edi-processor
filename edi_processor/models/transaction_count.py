from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TransactionCountResult:
    count: int | None
    method: str
    succeeded: bool = True
    message: str | None = None
