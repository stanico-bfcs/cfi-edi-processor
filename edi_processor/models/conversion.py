from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ConversionResult:
    converter_key: str
    exit_code: int | None
    console_log_path: Path | None
    result_log_paths: tuple[Path, ...] = ()
    duration_seconds: float = 0.0
    timed_out: bool = False
    skipped: bool = False
    error_message: str | None = None

    @property
    def succeeded(self) -> bool:
        return not self.skipped and not self.timed_out and self.exit_code == 0
