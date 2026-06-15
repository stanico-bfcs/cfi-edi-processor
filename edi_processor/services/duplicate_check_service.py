from __future__ import annotations

import logging
import os
import re

from edi_processor.config import DuplicateCheckSettings
from edi_processor.models.duplicate_check import DuplicateCheckResult
from edi_processor.models.file_submission import FileSubmission


class DuplicateCheckService:
    def __init__(self, settings: DuplicateCheckSettings) -> None:
        self.settings = settings
        self.logger = logging.getLogger(__name__)

    def check(self, submission: FileSubmission, run_id: str) -> DuplicateCheckResult:
        if not self.settings.enabled:
            return DuplicateCheckResult(is_duplicate=False)

        if not self._is_safe_identifier(self.settings.table) or not self._is_safe_identifier(
            self.settings.file_name_column
        ):
            return DuplicateCheckResult(
                is_duplicate=False,
                succeeded=False,
                message="Duplicate check table or column name is not a safe SQL identifier.",
                error_code="DUPLICATE_CHECK_INVALID_CONFIG",
            )

        try:
            import pyodbc
        except ImportError:
            return self._unavailable("pyodbc is not installed.")

        try:
            with pyodbc.connect(self._connection_string(), timeout=10) as connection:
                cursor = connection.cursor()
                query, parameter = self._query(submission.file_name)
                cursor.execute(query, parameter)
                row = cursor.fetchone()
        except Exception as exc:
            return self._unavailable(str(exc))

        if row is None:
            self.logger.info(
                "No duplicate batch record found",
                extra={
                    "run_id": run_id,
                    "provider": submission.provider.key,
                    "file_name": submission.file_name,
                    "status": "duplicate_not_found",
                },
            )
            return DuplicateCheckResult(is_duplicate=False)

        message = f"Duplicate batch record found for file: {submission.file_name}"
        self.logger.warning(
            message,
            extra={
                "run_id": run_id,
                "provider": submission.provider.key,
                "file_name": submission.file_name,
                "status": "duplicate_found",
            },
        )
        return DuplicateCheckResult(is_duplicate=True, message=message)

    def _connection_string(self) -> str:
        parts = [
            f"DRIVER={{{self.settings.driver}}}",
            f"SERVER={self.settings.server}",
            f"DATABASE={self.settings.database}",
        ]
        if self.settings.trusted_connection:
            parts.append("Trusted_Connection=yes")
        else:
            username = os.environ.get(self.settings.username_env, "")
            password = os.environ.get(self.settings.password_env, "")
            parts.extend((f"UID={username}", f"PWD={password}"))
        return ";".join(parts)

    def _query(self, file_name: str) -> tuple[str, str]:
        table = self.settings.table
        column = self.settings.file_name_column
        if self.settings.match_mode == "exact":
            return f"select top 1 {column} from {table} where {column} = ?", file_name
        return f"select top 1 {column} from {table} where {column} like ?", f"%{file_name}%"

    def _unavailable(self, message: str) -> DuplicateCheckResult:
        return DuplicateCheckResult(
            is_duplicate=False,
            succeeded=not self.settings.fail_on_unavailable,
            message=f"Duplicate check unavailable: {message}",
            error_code="DUPLICATE_CHECK_UNAVAILABLE",
        )

    def _is_safe_identifier(self, value: str) -> bool:
        return bool(re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)?", value))
