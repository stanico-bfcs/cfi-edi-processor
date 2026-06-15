from __future__ import annotations

import logging
import re
import time
from pathlib import Path

from edi_processor.config import PublishSettings
from edi_processor.models.inbox_observation import InboxObservationResult


class InboxObserverService:
    def __init__(self, settings: PublishSettings) -> None:
        self.settings = settings
        self.logger = logging.getLogger(__name__)

    def observe(
        self,
        expected_file_name: str,
        inbox_directory: Path,
        run_id: str,
        provider_key: str,
        dry_run: bool,
    ) -> InboxObservationResult:
        if not self.settings.observe_inbox:
            return InboxObservationResult(
                expected_file_name=expected_file_name,
                observed_path=None,
                status="disabled",
                message="INBOX observation is disabled.",
            )

        if dry_run:
            self.logger.info(
                f"Would observe INBOX for {expected_file_name}",
                extra={
                    "run_id": run_id,
                    "provider": provider_key,
                    "file_name": expected_file_name,
                    "status": "inbox_observation_planned",
                },
            )
            return InboxObservationResult(
                expected_file_name=expected_file_name,
                observed_path=None,
                status="planned",
            )

        deadline = time.monotonic() + self.settings.inbox_observation_timeout_seconds
        while time.monotonic() <= deadline:
            observed = self._find_observed_file(expected_file_name, inbox_directory)
            if observed is not None:
                if observed.stat().st_size == 0:
                    self.logger.error(
                        f"Observed zero-byte INBOX file: {observed}",
                        extra={
                            "run_id": run_id,
                            "provider": provider_key,
                            "file_name": expected_file_name,
                            "status": "inbox_observed_zero_byte",
                            "error": "INBOX_ZERO_BYTE",
                        },
                    )
                    return InboxObservationResult(
                        expected_file_name=expected_file_name,
                        observed_path=observed,
                        status="observed_zero_byte",
                        message="Quantum Choice pickup produced a zero-byte INBOX file.",
                    )

                self.logger.info(
                    f"Observed INBOX file: {observed}",
                    extra={
                        "run_id": run_id,
                        "provider": provider_key,
                        "file_name": expected_file_name,
                        "status": "inbox_observed_non_empty",
                    },
                )
                return InboxObservationResult(
                    expected_file_name=expected_file_name,
                    observed_path=observed,
                    status="observed_non_empty",
                )

            time.sleep(self.settings.inbox_observation_interval_seconds)

        return InboxObservationResult(
            expected_file_name=expected_file_name,
            observed_path=None,
            status="timeout",
            message="Timed out waiting for Quantum Choice pickup in INBOX.",
        )

    def _find_observed_file(self, expected_file_name: str, inbox_directory: Path) -> Path | None:
        if not inbox_directory.exists():
            return None

        exact = inbox_directory / expected_file_name
        if exact.exists() and exact.is_file():
            return exact

        expected = Path(expected_file_name)
        pattern = re.compile(
            rf"^{re.escape(expected.stem)}_\(\d+\){re.escape(expected.suffix)}$",
            re.IGNORECASE,
        )
        matches = [
            path
            for path in inbox_directory.iterdir()
            if path.is_file() and pattern.match(path.name)
        ]
        if not matches:
            return None

        return max(matches, key=lambda path: path.stat().st_mtime)
