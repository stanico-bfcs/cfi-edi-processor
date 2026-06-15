from __future__ import annotations

import csv
import json
from collections import Counter
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from edi_processor.models.processing import FileProcessingResult


class ProcessingSummaryService:
    def __init__(self, logs_directory: Path) -> None:
        self.logs_directory = logs_directory

    def write_summary(
        self,
        results: list[FileProcessingResult],
        run_id: str,
        dry_run: bool,
        started_at: datetime,
        completed_at: datetime,
        exit_code: int,
    ) -> tuple[Path, Path]:
        output_dir = self.logs_directory / "runs" / completed_at.strftime("%m-%d-%Y")
        output_dir.mkdir(parents=True, exist_ok=True)
        status_counts = Counter(result.status for result in results)
        summary = {
            "runId": run_id,
            "dryRun": dry_run,
            "startedAt": started_at.isoformat(timespec="seconds"),
            "completedAt": completed_at.isoformat(timespec="seconds"),
            "durationSeconds": round((completed_at - started_at).total_seconds(), 3),
            "exitCode": exit_code,
            "totalFiles": len(results),
            "statusCounts": dict(sorted(status_counts.items())),
            "files": [asdict(result) for result in results],
        }

        json_path = output_dir / f"{run_id}_summary.json"
        csv_path = output_dir / f"{run_id}_files.csv"
        json_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
        self._write_csv(csv_path, results)
        return json_path, csv_path

    def _write_csv(self, path: Path, results: list[FileProcessingResult]) -> None:
        with path.open("w", encoding="utf-8", newline="") as file:
            writer = csv.DictWriter(
                file,
                fieldnames=(
                    "provider_key",
                    "file_name",
                    "status",
                    "message",
                    "transaction_count",
                    "transaction_count_message",
                    "received_date",
                ),
            )
            writer.writeheader()
            for result in results:
                writer.writerow(asdict(result))
