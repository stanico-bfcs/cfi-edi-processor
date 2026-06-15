from __future__ import annotations

import logging
import shutil
import time
from pathlib import Path

from edi_processor.config import PublishSettings
from edi_processor.models.publish import PublishResult


class IncomingPublishService:
    def __init__(self, settings: PublishSettings) -> None:
        self.settings = settings
        self.logger = logging.getLogger(__name__)

    def publish(
        self,
        source: Path,
        incoming_directory: Path,
        run_id: str,
        provider_key: str,
        dry_run: bool,
    ) -> PublishResult:
        destination = self._unique_destination(incoming_directory / source.name)

        if dry_run:
            self.logger.info(
                f"Would publish {source} to {destination}",
                extra={
                    "run_id": run_id,
                    "provider": provider_key,
                    "file_name": source.name,
                    "status": "publish_planned",
                },
            )
            return PublishResult(source=source, destination=destination, succeeded=True, skipped=True)

        if not source.exists():
            return self._failed(source, destination, "SOURCE_MISSING", "Source file does not exist.")

        if source.stat().st_size == 0:
            return self._failed(source, destination, "SOURCE_EMPTY", "Source file is zero bytes.")

        stable = self._wait_for_stable_file(source)
        if not stable:
            return self._failed(
                source,
                destination,
                "SOURCE_NOT_STABLE",
                "Source file was not stable before publish.",
            )

        incoming_directory.mkdir(parents=True, exist_ok=True)
        temp_destination = self._unique_destination(destination.with_name(f"{destination.name}{self.settings.temp_suffix}"))

        for attempt in range(1, self.settings.max_retries + 1):
            try:
                shutil.copy2(source, temp_destination)
                if temp_destination.stat().st_size != source.stat().st_size:
                    temp_destination.unlink(missing_ok=True)
                    raise OSError("Published temp file size does not match source size.")

                temp_destination.replace(destination)
                self.logger.info(
                    f"Published {source.name} to {destination}",
                    extra={
                        "run_id": run_id,
                        "provider": provider_key,
                        "file_name": source.name,
                        "status": "published",
                    },
                )
                return PublishResult(source=source, destination=destination, succeeded=True)
            except OSError as exc:
                if attempt >= self.settings.max_retries:
                    temp_destination.unlink(missing_ok=True)
                    return self._failed(source, destination, "PUBLISH_FAILED", str(exc))
                time.sleep(self.settings.retry_delay_seconds)

        return self._failed(source, destination, "PUBLISH_FAILED", "Publish failed.")

    def _wait_for_stable_file(self, source: Path) -> bool:
        previous_size: int | None = None
        stable_count = 0

        for _ in range(self.settings.stability_checks):
            if not source.exists():
                return False

            current_size = source.stat().st_size
            if current_size > 0 and current_size == previous_size:
                stable_count += 1
            else:
                stable_count = 0

            previous_size = current_size
            if stable_count >= max(1, self.settings.stability_checks - 1):
                return True

            time.sleep(self.settings.stability_interval_seconds)

        return False

    def _failed(
        self,
        source: Path,
        destination: Path,
        error_code: str,
        message: str,
    ) -> PublishResult:
        self.logger.error(message)
        return PublishResult(
            source=source,
            destination=destination,
            succeeded=False,
            error_code=error_code,
            message=message,
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
