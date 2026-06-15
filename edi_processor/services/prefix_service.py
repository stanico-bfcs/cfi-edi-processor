from __future__ import annotations

import logging
from pathlib import Path

from edi_processor.models.file_submission import FileSubmission, PrefixResult
from edi_processor.services.excel_reader import ExcelReader


class PrefixService:
    def __init__(self) -> None:
        self.logger = logging.getLogger(__name__)
        self.excel_reader = ExcelReader()

    def apply(self, submission: FileSubmission, run_id: str, dry_run: bool) -> PrefixResult:
        rule = submission.provider.prefix
        file_name = submission.file_name

        if not rule.values:
            return PrefixResult(submission=submission, is_valid=True)

        if file_name.startswith(rule.values):
            self.logger.info(
                f"File already has a valid prefix: {file_name}",
                extra={
                    "run_id": run_id,
                    "provider": submission.provider.key,
                    "file_name": file_name,
                    "status": "prefix_already_valid",
                },
            )
            return PrefixResult(submission=submission, is_valid=True)

        if rule.add_if_missing and len(rule.values) == 1:
            prefixed_name = f"{rule.values[0]}{file_name}"
            return self._rename(submission, prefixed_name, run_id, dry_run)

        derived_prefix = self._derive_prefix(submission)
        if derived_prefix:
            prefixed_name = f"{derived_prefix}{file_name}"
            return self._rename(submission, prefixed_name, run_id, dry_run)

        derive_error = self._derive_prefix_error(submission)
        if derive_error:
            self.logger.error(
                derive_error,
                extra={
                    "run_id": run_id,
                    "provider": submission.provider.key,
                    "file_name": file_name,
                    "status": "prefix_failed",
                    "error": "PREFIX_DERIVATION_FAILED",
                },
            )
            return PrefixResult(
                submission=submission,
                is_valid=False,
                message=derive_error,
                error_code="PREFIX_DERIVATION_FAILED",
            )

        if rule.reject_if_missing:
            message = "File is missing a required provider prefix and cannot be safely auto-prefixed."
            self.logger.error(
                message,
                extra={
                    "run_id": run_id,
                    "provider": submission.provider.key,
                    "file_name": file_name,
                    "status": "prefix_failed",
                    "error": "PREFIX_MISSING",
                },
            )
            return PrefixResult(
                submission=submission,
                is_valid=False,
                message=message,
                error_code="PREFIX_MISSING",
            )

        self.logger.info(
            f"No prefix action configured for {file_name}",
            extra={
                "run_id": run_id,
                "provider": submission.provider.key,
                "file_name": file_name,
                "status": "prefix_unchanged",
            },
        )
        return PrefixResult(submission=submission, is_valid=True)

    def _rename(
        self,
        submission: FileSubmission,
        prefixed_name: str,
        run_id: str,
        dry_run: bool,
    ) -> PrefixResult:
        destination = self._unique_destination(submission.path.with_name(prefixed_name))

        if dry_run:
            self.logger.info(
                f"Would rename {submission.file_name} to {destination.name}",
                extra={
                    "run_id": run_id,
                    "provider": submission.provider.key,
                    "file_name": submission.file_name,
                    "status": "prefix_rename_planned",
                },
            )
            return PrefixResult(submission=submission, is_valid=True)

        submission.path.rename(destination)
        renamed = FileSubmission(
            provider=submission.provider,
            path=destination,
            received_date=submission.received_date,
        )
        self.logger.info(
            f"Renamed {submission.file_name} to {destination.name}",
            extra={
                "run_id": run_id,
                "provider": submission.provider.key,
                "file_name": destination.name,
                "status": "prefix_renamed",
            },
        )
        return PrefixResult(submission=renamed, is_valid=True)

    def _derive_prefix(self, submission: FileSubmission) -> str | None:
        rule = submission.provider.prefix
        if not rule.derive_from:
            return None

        matches = self._derive_matches(submission)
        if len(matches) == 1:
            return next(iter(matches))
        return None

    def _derive_prefix_error(self, submission: FileSubmission) -> str | None:
        rule = submission.provider.prefix
        if not rule.derive_from:
            return None

        matches = self._derive_matches(submission)
        if len(matches) > 1 and rule.reject_if_multiple_locations:
            return "File contains multiple locations and cannot be safely prefixed."
        if len(matches) > 1:
            return "File contains multiple possible prefixes and cannot be safely prefixed."
        if not matches:
            return f"Could not determine prefix from configured source: {rule.derive_from}."
        return None

    def _derive_matches(self, submission: FileSubmission) -> set[str]:
        derive_from = submission.provider.prefix.derive_from or ""
        if derive_from.startswith("column:"):
            return self._location_matches(submission)
        if derive_from == "sheetName":
            return self._sheet_name_matches(submission)
        return set()

    def _sheet_name_matches(self, submission: FileSubmission) -> set[str]:
        if submission.path.suffix.lower() != ".xlsx":
            return set()

        sheet_names = self.excel_reader.sheet_names(submission.path)
        matches: set[str] = set()
        for sheet_name in sheet_names:
            normalized_sheet = sheet_name.lower()
            for prefix in submission.provider.prefix.values:
                code = prefix.rstrip("_")
                if prefix.lower() in normalized_sheet or code.lower() in normalized_sheet:
                    matches.add(prefix)

        return matches

    def _location_matches(self, submission: FileSubmission) -> set[str]:
        derive_from = submission.provider.prefix.derive_from or ""
        config = self._parse_derive_from(derive_from)
        if not config:
            return set()

        rows = self.excel_reader.read_rows(submission.path)
        column_index = self._column_to_index(config["column"])
        if column_index <= 0:
            return set()

        start_row = int(config["row"])
        locations = config["locations"]
        matches: set[str] = set()

        for row in rows[start_row - 1 :]:
            if len(row) < column_index:
                continue
            value = row[column_index - 1].strip().lower()
            if not value:
                continue
            for location_name, prefix in locations.items():
                if location_name.lower() in value:
                    matches.add(prefix)

        return matches

    def _parse_derive_from(self, value: str) -> dict | None:
        parts = {}
        for item in value.split(","):
            if ":" not in item:
                continue
            key, raw = item.split(":", 1)
            parts[key.strip()] = raw.strip()

        if "column" not in parts or "row" not in parts or "locations" not in parts:
            return None

        locations = {}
        for mapping in parts["locations"].split(";"):
            if "=" not in mapping:
                continue
            location_name, prefix = mapping.split("=", 1)
            locations[location_name.strip()] = prefix.strip()

        return {
            "column": parts["column"].strip(),
            "row": parts["row"].strip(),
            "locations": locations,
        }

    def _column_to_index(self, column: str) -> int:
        index = 0
        for character in column.strip():
            if not character.isalpha():
                return 0
            index = index * 26 + (ord(character.upper()) - ord("A") + 1)
        return index

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
