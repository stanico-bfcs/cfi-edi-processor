from __future__ import annotations

import csv
import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from edi_processor.models.processing import FileProcessingResult


class TransactionReportService:
    def __init__(self, logs_directory: Path) -> None:
        self.logs_directory = logs_directory

    def write_report(
        self,
        results: list[FileProcessingResult],
        run_id: str,
        completed_at: datetime,
    ) -> tuple[Path, Path]:
        output_dir = self.logs_directory / "transaction_counts" / completed_at.strftime("%m-%d-%Y")
        output_dir.mkdir(parents=True, exist_ok=True)
        rows = [result for result in results if result.transaction_count is not None]
        total = sum(result.transaction_count or 0 for result in rows)
        payload = {
            "runId": run_id,
            "completedAt": completed_at.isoformat(timespec="seconds"),
            "totalTransactionCount": total,
            "files": [asdict(result) for result in rows],
        }

        json_path = output_dir / f"{run_id}_transaction_counts.json"
        csv_path = output_dir / f"{run_id}_transaction_counts.csv"
        json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        self._write_csv(csv_path, rows, total)
        return json_path, csv_path

    def _write_csv(
        self,
        path: Path,
        results: list[FileProcessingResult],
        total: int,
    ) -> None:
        with path.open("w", encoding="utf-8", newline="") as file:
            writer = csv.DictWriter(
                file,
                fieldnames=(
                    "provider_key",
                    "file_name",
                    "status",
                    "transaction_count",
                    "transaction_count_message",
                    "received_date",
                ),
            )
            writer.writeheader()
            for result in results:
                writer.writerow(
                    {
                        "provider_key": result.provider_key,
                        "file_name": result.file_name,
                        "status": result.status,
                        "transaction_count": result.transaction_count,
                        "transaction_count_message": result.transaction_count_message,
                        "received_date": result.received_date,
                    }
                )
            writer.writerow(
                {
                    "provider_key": "",
                    "file_name": "TOTAL",
                    "status": "",
                    "transaction_count": total,
                    "transaction_count_message": "",
                    "received_date": "",
                }
            )
