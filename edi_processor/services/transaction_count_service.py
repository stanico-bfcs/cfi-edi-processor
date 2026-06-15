from __future__ import annotations

import csv
import re
from pathlib import Path

from edi_processor.config import ValidationSchema
from edi_processor.models.file_submission import FileSubmission
from edi_processor.models.transaction_count import TransactionCountResult
from edi_processor.services.excel_reader import ExcelReader


class TransactionCountService:
    def __init__(self, schemas: dict[str, ValidationSchema]) -> None:
        self.schemas = schemas
        self.excel_reader = ExcelReader()

    def count(self, submission: FileSubmission) -> TransactionCountResult:
        if self._should_count_x12(submission):
            return self._count_x12_claims(submission.path)

        schema = self._schema(submission)
        if schema is None:
            return TransactionCountResult(
                count=None,
                method="none",
                succeeded=False,
                message="No validation schema is configured for transaction counting.",
            )

        if schema.file_type == "xlsx":
            return self._count_rows(self.excel_reader.read_rows(submission.path), schema, "xlsx_rows")

        if schema.file_type == "csv":
            return self._count_delimited_rows(submission.path, schema)

        return TransactionCountResult(
            count=None,
            method=schema.file_type,
            succeeded=False,
            message=f"Transaction counting is not implemented for file type: {schema.file_type}.",
        )

    def _should_count_x12(self, submission: FileSubmission) -> bool:
        suffix = submission.path.suffix.lower()
        return submission.provider.converter == "convert837ITo837P" or suffix in {".837i", ".837p"}

    def _schema(self, submission: FileSubmission) -> ValidationSchema | None:
        schema_key = submission.provider.validation.schema
        if not schema_key:
            return None
        return self.schemas.get(schema_key)

    def _count_x12_claims(self, path: Path) -> TransactionCountResult:
        content = self._read_text(path)
        count = len(re.findall(r"(^|[~\r\n])\s*CLM\*", content))
        return TransactionCountResult(count=count, method="x12_clm_segments")

    def _count_delimited_rows(
        self,
        path: Path,
        schema: ValidationSchema,
    ) -> TransactionCountResult:
        try:
            lines = self._read_text(path).splitlines()
            rows = list(csv.reader(lines, delimiter=schema.delimiter or ",", strict=True))
        except csv.Error as exc:
            return self._count_physical_lines(lines, schema, str(exc))

        return self._count_rows(rows, schema, "csv_rows")

    def _count_rows(
        self,
        rows: list[list[str]],
        schema: ValidationSchema,
        method: str,
    ) -> TransactionCountResult:
        header_index = (schema.header_row or 1) - 1
        data_start_index = (schema.data_start_row or header_index + 2) - 1
        count = 0

        for row in rows[data_start_index:]:
            if any(value.strip() for value in row):
                count += 1

        return TransactionCountResult(count=count, method=method)

    def _count_physical_lines(
        self,
        lines: list[str],
        schema: ValidationSchema,
        message: str,
    ) -> TransactionCountResult:
        header_index = (schema.header_row or 1) - 1
        data_start_index = (schema.data_start_row or header_index + 2) - 1
        count = sum(1 for line in lines[data_start_index:] if line.strip())
        return TransactionCountResult(
            count=count,
            method="physical_data_lines_after_csv_error",
            message=f"CSV parse failed while counting; used physical line count fallback: {message}",
        )

    def _read_text(self, path: Path) -> str:
        try:
            return path.read_text(encoding="utf-8-sig")
        except UnicodeDecodeError:
            return path.read_text(encoding="cp1252")
