from __future__ import annotations

import logging
import shutil
from datetime import datetime
from pathlib import Path

from edi_processor.models.file_submission import FileSubmission, StagingResult


class StagingService:
    def __init__(self, working_directory: Path) -> None:
        self.working_directory = working_directory
        self.logger = logging.getLogger(__name__)

    def stage(self, submission: FileSubmission, run_id: str) -> StagingResult:
        destination_dir = (
            self.working_directory
            / "staged"
            / datetime.now().strftime("%m-%d-%Y")
            / run_id
            / submission.provider.key
        )
        destination = self._unique_destination(destination_dir / submission.file_name)

        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(submission.path, destination)
        except OSError as exc:
            self.logger.error(
                f"Could not stage provider file: {exc}",
                extra={
                    "run_id": run_id,
                    "provider": submission.provider.key,
                    "file_name": submission.file_name,
                    "status": "staging_failed",
                    "error": "STAGING_COPY_FAILED",
                },
            )
            return StagingResult(
                submission=submission,
                succeeded=False,
                message=str(exc),
                error_code="STAGING_COPY_FAILED",
            )

        staged_submission = FileSubmission(
            provider=submission.provider,
            path=destination,
            received_date=submission.received_date,
        )
        self.logger.info(
            f"Staged provider file: {destination}",
            extra={
                "run_id": run_id,
                "provider": submission.provider.key,
                "file_name": submission.file_name,
                "status": "file_staged",
                "staged_path": str(destination),
            },
        )
        return StagingResult(submission=staged_submission, succeeded=True)

    def _unique_destination(self, destination: Path) -> Path:
        if not destination.exists():
            return destination

        stem = destination.stem
        suffix = destination.suffix
        parent = destination.parent
        counter = 1

        while True:
            candidate = parent / f"{stem}_({counter}){suffix}"
            if not candidate.exists():
                return candidate
            counter += 1
