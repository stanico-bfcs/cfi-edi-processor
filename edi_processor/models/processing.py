from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FileProcessingResult:
    provider_key: str
    file_name: str
    status: str
    message: str | None = None
    transaction_count: int | None = None
    transaction_count_message: str | None = None
    received_date: str | None = None
