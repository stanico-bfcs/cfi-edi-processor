from __future__ import annotations

import csv
import logging
from datetime import date, datetime
from pathlib import Path

from edi_processor.config import PathSettings, ReceivedDateOverrideSettings
from edi_processor.models.file_submission import FileSubmission
from edi_processor.models.received_date_override import ReceivedDateOverrides


class ReceivedDateOverrideService:
    def __init__(
        self,
        paths: PathSettings,
        settings: ReceivedDateOverrideSettings,
    ) -> None:
        self.paths = paths
        self.settings = settings
        self.logger = logging.getLogger(__name__)

    def load(self, run_id: str) -> ReceivedDateOverrides:
        path = self._path()
        if not self.settings.enabled or not path.exists():
            return ReceivedDateOverrides(source_path=path, values={}, parsed_successfully=True)

        values: dict[tuple[str, str], date] = {}
        messages: list[str] = []
        parsed_successfully = True

        try:
            with path.open("r", encoding="utf-8-sig", newline="") as file:
                reader = csv.DictReader(file)
                for row_number, row in enumerate(reader, start=2):
                    provider = (row.get("provider") or "").strip()
                    file_name = (row.get("file_name") or "").strip()
                    raw_date = (row.get("received_date") or "").strip()

                    if not provider or not file_name or not raw_date:
                        parsed_successfully = False
                        messages.append(f"Row {row_number}: provider, file_name, and received_date are required.")
                        continue

                    key = (provider, file_name)
                    if key in values:
                        parsed_successfully = False
                        messages.append(f"Row {row_number}: duplicate override for {provider}/{file_name}.")
                        continue

                    try:
                        values[key] = datetime.strptime(
                            raw_date,
                            self.settings.date_format,
                        ).date()
                    except ValueError:
                        parsed_successfully = False
                        messages.append(
                            f"Row {row_number}: received_date '{raw_date}' does not match {self.settings.date_format}."
                        )
        except OSError as exc:
            parsed_successfully = False
            messages.append(str(exc))

        for message in messages:
            self.logger.warning(
                message,
                extra={"run_id": run_id, "status": "received_date_override_warning"},
            )

        self.logger.info(
            f"Loaded {len(values)} received date overrides from {path}",
            extra={"run_id": run_id, "status": "received_date_overrides_loaded"},
        )
        return ReceivedDateOverrides(
            source_path=path,
            values=values,
            parsed_successfully=parsed_successfully,
            messages=tuple(messages),
        )

    def apply(
        self,
        submissions: list[FileSubmission],
        overrides: ReceivedDateOverrides,
        run_id: str,
    ) -> list[FileSubmission]:
        updated: list[FileSubmission] = []
        for submission in submissions:
            received_date = overrides.find(submission.provider.key, submission.file_name)
            if received_date is None:
                updated.append(submission)
                continue

            self.logger.info(
                f"Applying received date override {received_date.isoformat()} to {submission.file_name}",
                extra={
                    "run_id": run_id,
                    "provider": submission.provider.key,
                    "file_name": submission.file_name,
                    "status": "received_date_override_applied",
                },
            )
            updated.append(
                FileSubmission(
                    provider=submission.provider,
                    path=submission.path,
                    received_date=received_date,
                )
            )
        return updated

    def cleanup(
        self,
        overrides: ReceivedDateOverrides,
        run_id: str,
        dry_run: bool,
    ) -> None:
        if (
            not self.settings.enabled
            or self.settings.cleanup != "delete"
            or dry_run
            or not overrides.parsed_successfully
            or not overrides.source_path.exists()
        ):
            return

        overrides.source_path.unlink()
        self.logger.info(
            f"Deleted received date override file: {overrides.source_path}",
            extra={"run_id": run_id, "status": "received_date_override_deleted"},
        )

    def _path(self) -> Path:
        return self.paths.source_root / self.settings.admin_folder_name / self.settings.file_name
