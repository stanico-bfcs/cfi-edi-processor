from __future__ import annotations

import csv
import logging
from datetime import datetime
from pathlib import Path

from edi_processor.models.file_submission import FileSubmission
from edi_processor.models.preprocessing import PreprocessingResult


class PreprocessingService:
    headers = (
        "PatientName",
        "Sex",
        "BirthDate",
        "RC",
        "DrugName",
        "RXNumber",
        "RXDate",
        "Quantity",
        "DS",
        "Doctor",
        "DoctorNumber",
        "DType",
        "PolicyNumber",
        "NDCNumber",
        "Type",
        "STCode",
        "InCareOf",
        "Manufacturer",
        "PriorAuth",
        "Tax",
        "Total",
        "CoPay",
        "Balance",
    )

    def __init__(self, working_directory: Path) -> None:
        self.working_directory = working_directory
        self.logger = logging.getLogger(__name__)

    def preprocess(
        self,
        submission: FileSubmission,
        run_id: str,
    ) -> PreprocessingResult:
        settings = submission.provider.preprocessing
        if not settings.enabled:
            return PreprocessingResult(submission=submission, succeeded=True)

        if settings.kind != "fixedReportToCsv":
            return PreprocessingResult(
                submission=submission,
                succeeded=False,
                message=f"Unsupported preprocessing kind: {settings.kind}",
                error_code="PREPROCESSING_KIND_UNSUPPORTED",
            )

        try:
            rows = self._parse_fixed_report(submission.path)
        except ValueError as exc:
            return PreprocessingResult(
                submission=submission,
                succeeded=False,
                message=str(exc),
                error_code="FIXED_REPORT_PARSE_FAILED",
            )

        output_path = self._output_path(submission, run_id)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("w", encoding="utf-8", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=self.headers)
            writer.writeheader()
            writer.writerows(rows)

        processed_submission = FileSubmission(
            provider=submission.provider,
            path=output_path,
            received_date=submission.received_date,
        )
        self.logger.info(
            f"Preprocessed fixed report to CSV: {output_path}",
            extra={
                "run_id": run_id,
                "provider": submission.provider.key,
                "file_name": submission.file_name,
                "status": "preprocessing_completed",
            },
        )
        return PreprocessingResult(
            submission=processed_submission,
            succeeded=True,
            output_path=output_path,
        )

    def _parse_fixed_report(self, path: Path) -> list[dict[str, str]]:
        lines = self._read_lines(path)
        rows: list[dict[str, str]] = []
        row_index = 0

        while row_index < len(lines):
            line = lines[row_index]
            if "P8C80B19131006" in line:
                row_index += 9
                continue
            if not line.strip():
                row_index += 1
                continue
            if row_index + 3 >= len(lines):
                raise ValueError(f"Incomplete fixed report claim block near line {row_index + 1}.")

            cols1 = lines[row_index]
            cols2 = lines[row_index + 1]
            cols3 = lines[row_index + 2]
            cols4 = lines[row_index + 3]
            balances = [item for item in cols1[101:].strip().split(" ") if item]
            if len(balances) < 4:
                row_index += 1
                continue

            block_size = 5 if cols4.strip() else 4
            quantity_parts = [item for item in cols3[49:].strip().split(" ") if item]
            quantity = quantity_parts[0] if quantity_parts else ""
            days_supply = quantity_parts[1] if len(quantity_parts) > 1 else ""

            rows.append(
                {
                    "PatientName": cols1[0:21].strip(),
                    "Sex": cols1[21:22].strip(),
                    "BirthDate": cols3[0:20].strip(),
                    "RC": cols1[25:26].strip(),
                    "DrugName": cols1[30:50].strip(),
                    "RXNumber": cols1[50:69].strip(),
                    "RXDate": cols2[50:69].strip(),
                    "Quantity": quantity,
                    "DS": days_supply,
                    "Doctor": cols1[69:101].strip(),
                    "DoctorNumber": cols2[69:101].strip(),
                    "DType": cols3[69:101].strip(),
                    "PolicyNumber": cols2[0:21].strip(),
                    "NDCNumber": cols2[30:50].strip(),
                    "Type": cols3[20:30].strip(),
                    "STCode": cols3[30:49].strip(),
                    "InCareOf": cols4[0:21].strip(),
                    "Manufacturer": cols4[30:50].strip(),
                    "PriorAuth": cols4[50:69].strip(),
                    "Tax": balances[0],
                    "Total": balances[1],
                    "CoPay": balances[2],
                    "Balance": balances[3],
                }
            )
            row_index += block_size

        if not rows:
            raise ValueError("No claim rows were parsed from the fixed report.")
        return rows

    def _read_lines(self, path: Path) -> list[str]:
        try:
            return path.read_text(encoding="utf-8-sig").splitlines()
        except UnicodeDecodeError:
            return path.read_text(encoding="cp1252").splitlines()

    def _output_path(self, submission: FileSubmission, run_id: str) -> Path:
        date_folder = datetime.now().strftime("%m-%d-%Y")
        output_dir = (
            self.working_directory
            / "preprocessed"
            / date_folder
            / run_id
            / submission.provider.key
        )
        return output_dir / f"{submission.path.stem}.csv"
