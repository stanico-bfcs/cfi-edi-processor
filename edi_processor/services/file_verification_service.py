from __future__ import annotations

import time
from pathlib import Path

from edi_processor.models.file_verification import FileVerificationResult


class FileVerificationService:
    def verify_non_empty_stable(
        self,
        path: Path,
        stability_checks: int,
        stability_interval_seconds: float,
    ) -> FileVerificationResult:
        if not path.exists():
            return FileVerificationResult(
                path=path,
                succeeded=False,
                error_code="FILE_MISSING",
                message="Expected output file does not exist.",
            )

        if path.stat().st_size == 0:
            return FileVerificationResult(
                path=path,
                succeeded=False,
                error_code="FILE_EMPTY",
                message="Expected output file is zero bytes.",
            )

        if not self._is_stable(path, stability_checks, stability_interval_seconds):
            return FileVerificationResult(
                path=path,
                succeeded=False,
                error_code="FILE_NOT_STABLE",
                message="Expected output file is not stable.",
            )

        return FileVerificationResult(path=path, succeeded=True)

    def _is_stable(
        self,
        path: Path,
        stability_checks: int,
        stability_interval_seconds: float,
    ) -> bool:
        previous_size: int | None = None
        stable_count = 0

        for _ in range(stability_checks):
            if not path.exists():
                return False

            current_size = path.stat().st_size
            if current_size > 0 and current_size == previous_size:
                stable_count += 1
            else:
                stable_count = 0

            previous_size = current_size
            if stable_count >= max(1, stability_checks - 1):
                return True

            time.sleep(stability_interval_seconds)

        return False
