from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

from edi_processor.config import ProviderSettings


@dataclass(frozen=True)
class FileSubmission:
    provider: ProviderSettings
    path: Path
    received_date: date | None = None

    @property
    def file_name(self) -> str:
        return self.path.name


@dataclass(frozen=True)
class ArchivePlan:
    submission: FileSubmission
    destination: Path
    enabled: bool


@dataclass(frozen=True)
class PrefixResult:
    submission: FileSubmission
    is_valid: bool
    message: str | None = None
    error_code: str | None = None


@dataclass(frozen=True)
class StagingResult:
    submission: FileSubmission
    succeeded: bool
    message: str | None = None
    error_code: str | None = None
