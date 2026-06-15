from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from edi_processor.models.file_submission import FileSubmission


@dataclass(frozen=True)
class PreprocessingResult:
    submission: FileSubmission
    succeeded: bool
    output_path: Path | None = None
    message: str | None = None
    error_code: str | None = None
