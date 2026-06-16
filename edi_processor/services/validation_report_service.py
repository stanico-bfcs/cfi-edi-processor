from __future__ import annotations

import csv
import json
import logging
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from edi_processor.config import ProviderMetadataSettings
from edi_processor.models.file_submission import FileSubmission
from edi_processor.models.validation import ValidationResult


class ValidationReportService:
    def __init__(
        self,
        reports_directory: Path,
        source_root: Path,
        provider_metadata: ProviderMetadataSettings,
    ) -> None:
        self.reports_directory = reports_directory
        self.source_root = source_root
        self.provider_metadata = provider_metadata
        self.logger = logging.getLogger(__name__)

    def write_reports(
        self,
        submission: FileSubmission,
        source_submission: FileSubmission,
        result: ValidationResult,
        run_id: str,
    ) -> tuple[Path, Path]:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_dir = self._report_directory(source_submission)
        report_dir.mkdir(parents=True, exist_ok=True)

        safe_stem = self._safe_stem(submission.path.stem)
        base_name = f"{timestamp}_{submission.provider.key}_{safe_stem}_validation"
        json_path = self._unique_destination(report_dir / f"{base_name}.json")
        csv_path = self._unique_destination(report_dir / f"{base_name}.csv")

        payload = {
            "run_id": run_id,
            "provider_key": submission.provider.key,
            "provider_name": submission.provider.name,
            "file_name": submission.file_name,
            "file_path": str(submission.path),
            "issue_count": len(result.issues),
            "issues": [asdict(issue) for issue in result.issues],
        }
        json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=True), encoding="utf-8")

        with csv_path.open("w", encoding="utf-8", newline="") as file:
            writer = csv.DictWriter(
                file,
                fieldnames=[
                    "severity",
                    "error_code",
                    "row_number",
                    "field_name",
                    "message",
                    "raw_value",
                    "suggested_fix",
                ],
            )
            writer.writeheader()
            for issue in result.issues:
                writer.writerow(asdict(issue))

        self.logger.info(
            f"Wrote validation reports for {submission.file_name}",
            extra={
                "run_id": run_id,
                "provider": submission.provider.key,
                "file_name": submission.file_name,
                "status": "validation_report_written",
            },
        )
        return json_path, csv_path

    def _report_directory(self, submission: FileSubmission) -> Path:
        if not self.provider_metadata.enabled:
            return self.reports_directory / datetime.now().strftime("%m-%d-%Y")

        return (
            self.source_root
            / submission.provider.folder
            / self.provider_metadata.folder_name
            / datetime.now().strftime(self.provider_metadata.date_format)
            / self._safe_path_component(submission.file_name)
        )

    def _safe_stem(self, value: str) -> str:
        safe = "".join(character if character.isalnum() else "_" for character in value)
        return safe.strip("_") or "file"

    def _safe_path_component(self, value: str) -> str:
        invalid = '<>:"/\\|?*'
        safe = "".join(
            "_" if character in invalid or ord(character) < 32 else character
            for character in value
        )
        return safe.strip(" .") or "file"

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
