from __future__ import annotations

import logging
import shutil
import subprocess
import time
from datetime import datetime
from pathlib import Path

from edi_processor.config import ConverterSettings, PathSettings
from edi_processor.models.conversion import ConversionResult


class ConverterService:
    def __init__(self, paths: PathSettings, converters: ConverterSettings) -> None:
        self.paths = paths
        self.converters = converters
        self.logger = logging.getLogger(__name__)

    def run_converter(
        self,
        converter_key: str,
        input_file: Path,
        provider_key: str,
        run_id: str,
        dry_run: bool,
        expected_result_files: tuple[Path, ...] = (),
    ) -> ConversionResult:
        executable = self._converter_path(converter_key)
        return self.run_executable(
            converter_key=converter_key,
            executable=executable,
            arguments=(input_file,),
            working_directory=executable.parent,
            provider_key=provider_key,
            input_file=input_file,
            run_id=run_id,
            dry_run=dry_run,
            expected_result_files=expected_result_files,
        )

    def run_executable(
        self,
        converter_key: str,
        executable: Path,
        arguments: tuple[Path | str, ...],
        working_directory: Path,
        provider_key: str,
        input_file: Path,
        run_id: str,
        dry_run: bool,
        expected_result_files: tuple[Path, ...] = (),
    ) -> ConversionResult:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_dir = self.paths.converter_logs_directory / datetime.now().strftime("%m-%d-%Y")
        log_dir.mkdir(parents=True, exist_ok=True)
        safe_stem = self._safe_stem(input_file.stem)
        console_log_path = log_dir / f"{timestamp}_{provider_key}_{converter_key}_{safe_stem}_console.log"

        if dry_run:
            self.logger.info(
                f"Would run converter {converter_key} for {input_file}",
                extra={
                    "run_id": run_id,
                    "provider": provider_key,
                    "file_name": input_file.name,
                    "status": "converter_planned",
                },
            )
            return ConversionResult(
                converter_key=converter_key,
                exit_code=None,
                console_log_path=console_log_path,
                skipped=True,
            )

        started = time.perf_counter()
        try:
            completed = subprocess.run(
                [str(executable), *(str(argument) for argument in arguments)],
                cwd=working_directory,
                capture_output=True,
                text=True,
                timeout=self.converters.timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            duration = time.perf_counter() - started
            console_log_path.write_text(
                self._format_console_output(exc.stdout, exc.stderr),
                encoding="utf-8",
            )
            return ConversionResult(
                converter_key=converter_key,
                exit_code=None,
                console_log_path=console_log_path,
                duration_seconds=duration,
                timed_out=True,
                error_message=f"Converter timed out after {self.converters.timeout_seconds} seconds.",
            )
        except OSError as exc:
            duration = time.perf_counter() - started
            console_log_path.write_text(str(exc), encoding="utf-8")
            return ConversionResult(
                converter_key=converter_key,
                exit_code=None,
                console_log_path=console_log_path,
                duration_seconds=duration,
                error_message=str(exc),
            )

        duration = time.perf_counter() - started
        console_log_path.write_text(
            self._format_console_output(completed.stdout, completed.stderr),
            encoding="utf-8",
        )
        result_logs = self._collect_result_logs(
            expected_result_files=expected_result_files,
            log_dir=log_dir,
            timestamp=timestamp,
            provider_key=provider_key,
            converter_key=converter_key,
            input_stem=safe_stem,
        )

        self.logger.info(
            f"Converter {converter_key} exited with code {completed.returncode}",
            extra={
                "run_id": run_id,
                "provider": provider_key,
                "file_name": input_file.name,
                "status": "converter_completed",
            },
        )
        return ConversionResult(
            converter_key=converter_key,
            exit_code=completed.returncode,
            console_log_path=console_log_path,
            result_log_paths=tuple(result_logs),
            duration_seconds=duration,
        )

    def _converter_path(self, converter_key: str) -> Path:
        paths = {
            "rxFlatfileTo837P": self.converters.rx_flatfile_to_837p,
            "convert837ITo837P": self.converters.convert_837i_to_837p,
        }
        try:
            return paths[converter_key]
        except KeyError as exc:
            raise ValueError(f"Unknown converter key: {converter_key}") from exc

    def _collect_result_logs(
        self,
        expected_result_files: tuple[Path, ...],
        log_dir: Path,
        timestamp: str,
        provider_key: str,
        converter_key: str,
        input_stem: str,
    ) -> list[Path]:
        collected: list[Path] = []

        for result_file in expected_result_files:
            if not result_file.exists():
                continue

            destination = log_dir / (
                f"{timestamp}_{provider_key}_{converter_key}_{input_stem}_{result_file.name}"
            )
            destination = self._unique_destination(destination)
            shutil.move(str(result_file), str(destination))
            collected.append(destination)

        return collected

    def _format_console_output(self, stdout: str | bytes | None, stderr: str | bytes | None) -> str:
        stdout_text = self._to_text(stdout)
        stderr_text = self._to_text(stderr)
        return f"[stdout]\n{stdout_text}\n[stderr]\n{stderr_text}\n"

    def _to_text(self, value: str | bytes | None) -> str:
        if value is None:
            return ""
        if isinstance(value, bytes):
            return value.decode("utf-8", errors="replace")
        return value

    def _safe_stem(self, value: str) -> str:
        safe = "".join(character if character.isalnum() else "_" for character in value)
        return safe.strip("_") or "file"

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
