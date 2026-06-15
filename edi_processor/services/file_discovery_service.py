from __future__ import annotations

import logging
from pathlib import Path

from edi_processor.config import AppSettings, ProviderSettings
from edi_processor.models.file_submission import FileSubmission


class FileDiscoveryService:
    def __init__(self, settings: AppSettings) -> None:
        self.settings = settings
        self.logger = logging.getLogger(__name__)

    def discover(
        self,
        run_id: str,
        provider_filter: tuple[str, ...] = (),
    ) -> list[FileSubmission]:
        submissions: list[FileSubmission] = []
        provider_keys = set(provider_filter)

        for provider in self.settings.providers:
            if provider_keys and provider.key not in provider_keys:
                continue

            if not provider.auto_process:
                self.logger.info(
                    f"Provider is not configured for auto-processing: {provider.key}",
                    extra={
                        "run_id": run_id,
                        "provider": provider.key,
                        "status": "provider_auto_process_disabled",
                    },
                )
                continue

            roots = self._provider_roots(provider)
            if not roots:
                self.logger.warning(
                    f"Provider folder not found for {provider.key}",
                    extra={
                        "run_id": run_id,
                        "provider": provider.key,
                        "status": "provider_folder_missing",
                    },
                )
                continue

            for provider_root in roots:
                submissions.extend(self._discover_provider(run_id, provider, provider_root))

        return submissions

    def _provider_roots(self, provider: ProviderSettings) -> list[Path]:
        folder_names = (provider.folder, *provider.aliases)
        roots: list[Path] = []

        for folder_name in folder_names:
            candidate = self.settings.paths.source_root / folder_name
            if candidate.exists():
                roots.append(candidate)

        return roots

    def _discover_provider(
        self,
        run_id: str,
        provider: ProviderSettings,
        provider_root: Path,
    ) -> list[FileSubmission]:
        allowed_extensions = {extension.lower() for extension in provider.file_format.extensions}
        archive_folder = provider.archive.folder_name.lower()
        submissions: list[FileSubmission] = []

        for path in provider_root.iterdir():
            if path.is_dir():
                if path.name.lower() != archive_folder:
                    self.logger.info(
                        f"Skipping subdirectory: {path}",
                        extra={
                            "run_id": run_id,
                            "provider": provider.key,
                            "status": "subdirectory_skipped",
                        },
                    )
                continue

            if not path.is_file():
                continue

            if allowed_extensions and path.suffix.lower() not in allowed_extensions:
                self.logger.info(
                    f"Skipping unsupported file type: {path.name}",
                    extra={
                        "run_id": run_id,
                        "provider": provider.key,
                        "file_name": path.name,
                        "status": "unsupported_file_type",
                    },
                )
                continue

            submissions.append(FileSubmission(provider=provider, path=path))

        self.logger.info(
            f"Discovered {len(submissions)} files for provider {provider.key}",
            extra={
                "run_id": run_id,
                "provider": provider.key,
                "status": "provider_discovery_completed",
            },
        )
        return submissions
