from __future__ import annotations

import logging
import shutil
from datetime import datetime
from pathlib import Path

from edi_processor.models.file_submission import ArchivePlan, FileSubmission


class ArchiveService:
    def __init__(self) -> None:
        self.logger = logging.getLogger(__name__)

    def plan(self, submission: FileSubmission, now: datetime) -> ArchivePlan:
        provider = submission.provider
        date_folder = now.strftime(provider.archive.date_format)
        destination = (
            submission.path.parent
            / provider.archive.folder_name
            / date_folder
            / submission.file_name
        )
        return ArchivePlan(
            submission=submission,
            destination=destination,
            enabled=provider.archive.enabled,
        )

    def execute(self, plan: ArchivePlan, run_id: str, dry_run: bool) -> None:
        provider_key = plan.submission.provider.key
        file_name = plan.submission.file_name

        if not plan.enabled:
            self.logger.info(
                f"Archive disabled for {file_name}",
                extra={
                    "run_id": run_id,
                    "provider": provider_key,
                    "file_name": file_name,
                    "status": "archive_disabled",
                },
            )
            return

        if dry_run:
            self.logger.info(
                f"Would archive {plan.submission.path} to {plan.destination}",
                extra={
                    "run_id": run_id,
                    "provider": provider_key,
                    "file_name": file_name,
                    "status": "archive_planned",
                },
            )
            return

        plan.destination.parent.mkdir(parents=True, exist_ok=True)
        destination = self._unique_destination(plan.destination)
        shutil.move(str(plan.submission.path), str(destination))
        self.logger.info(
            f"Archived {file_name} to {destination}",
            extra={
                "run_id": run_id,
                "provider": provider_key,
                "file_name": file_name,
                "status": "archived",
            },
        )

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
