# CFI EDI Processor

Structured Python migration for the legacy PowerShell EDI processing flow.

## Current Pilot Scope

The first live pilot provider is `Kirk_Pharmacy`. Live processing is intentionally guarded so a scheduled task cannot accidentally process every provider.

The runtime flow is:

```text
discover provider files
prefix/skip checks
duplicate TPM batch check
preprocess when configured
validate submitted X12 files when configured
validate flat files
count transactions
run converter
verify converter output
publish safely to INCOMING
optionally observe INBOX
archive original provider file
write run summary
```

`Doctors_Hospital` is configured with `autoProcess: false` and will not be discovered until enabled in config.

## Local Setup

Create local config files from the examples:

```powershell
Copy-Item appsettings.json.example appsettings.json
Copy-Item .env.example .env
```

`appsettings.json` is ignored by git and may contain local paths, routing, and non-secret operational values. Keep `appsettings.json.example` structurally aligned with it but use dummy values.

`.env` is ignored by git and is where credentials belong:

```text
SMTP_USERNAME=
SMTP_PASSWORD=
TPM_DB_USERNAME=
TPM_DB_PASSWORD=
```

## Important Config Areas

`runtime.liveProviderAllowList`

Providers allowed to run live. Keep this narrow during pilot, currently `Kirk_Pharmacy`.

`runtime.failOnFileStatuses`

File statuses that should make a live run return exit code `2`.

`paths`

Configure source provider root, QDS processor folders, `C:\Files\INCOMING`, `C:\Files\INBOX`, logs, templates, and converter output folders.

`duplicateCheck`

Optional TPM duplicate check against `batch.file_name`. The default `matchMode: "contains"` mirrors the legacy query:

```sql
select file_name from batch where file_name like '%{file_name}%'
```

`email`

Email delivery is disabled unless both config enables it and the CLI uses `--allow-email`.

`transactionReports`

Writes one transaction count report per run. Set `sendEmail: true` and configure `recipients` to send the report to the SFTP inbox. Email still requires global `email.enabled: true` and the CLI `--allow-email` switch.

Flat files are counted by configured data rows. HSA, Health City, and other 837 files are counted by X12 `CLM` claim segments.

`x12Validation`

Checks submitted X12 files before converter execution. This currently protects HSA, Health City, and any future provider using 837/X12 input.

The date-of-service rule validates `DTP*472*RD8*YYYYMMDD-YYYYMMDD` segments. Files are rejected with `x12_validation_failed` when the through date is earlier than the from date, for example:

```text
DTP*472*RD8*20260601-20260501~
```

`receivedDateOverrides`

Reads optional received date overrides from:

```text
{sourceRoot}\CFI-Admin\received_dates.csv
```

CSV format:

```csv
provider,file_name,received_date
HSA,H0000006_CAYMANFIRST_20260609_3252194.837i,2026-06-15
```

If a current file matches by provider and exact file name, the generated X12 is updated before publish:

- `ISA09` = `YYMMDD`
- `GS04` = `YYYYMMDD`
- `BHT04` = `YYYYMMDD`

If no override exists, the generated X12 is not modified. The CSV is deleted after a non-dry run only when it parsed successfully.

## Dry Run

Use dry-run for inspection. It loads config, discovers files, runs validation/planning paths, writes logs and summaries, but does not perform live converter/publish/archive side effects.

```powershell
python main.py --dry-run
```

Provider-scoped dry-run:

```powershell
python main.py --dry-run --provider Kirk_Pharmacy
```

Use the safe example config:

```powershell
python main.py --dry-run --config appsettings.json.example
```

## Live Pilot Command

Only run live after paths, converters, duplicate check, and notification settings are confirmed.

```powershell
python main.py --allow-live --provider Kirk_Pharmacy
```

Live runs require:

- `--allow-live`
- at least one `--provider`
- provider listed in `runtime.liveProviderAllowList`

Email sending additionally requires:

```powershell
python main.py --allow-live --allow-email --provider Kirk_Pharmacy
```

## Exit Codes

`0`

Run completed without configured live failure statuses. Dry-runs also return `0`.

`1`

Unexpected run-level crash caught by the CLI.

`2`

Live run completed, but one or more files ended in a configured failure status such as validation failure, duplicate skip, converter failure, publish failure, or INBOX observation failure.

## Logs And Artifacts

Structured JSONL run logs:

```text
logs/{run_id}.jsonl
```

Run summaries:

```text
logs/runs/{MM-DD-YYYY}/{run_id}_summary.json
logs/runs/{MM-DD-YYYY}/{run_id}_files.csv
```

Validation reports:

```text
logs/validation/{MM-DD-YYYY}/
```

Rendered provider notifications:

```text
logs/notifications/{MM-DD-YYYY}/
```

Transaction count reports:

```text
logs/transaction_counts/{MM-DD-YYYY}/{run_id}_transaction_counts.json
logs/transaction_counts/{MM-DD-YYYY}/{run_id}_transaction_counts.csv
```

Converter console/result logs:

```text
logs/converters/{MM-DD-YYYY}/
```

Preprocessed work files:

```text
work/preprocessed/{MM-DD-YYYY}/{run_id}/{provider}/
```

## Task Scheduler

For Python-based pilot runs, configure Task Scheduler with:

Program:

```text
python
```

Arguments:

```text
main.py --allow-live --provider Kirk_Pharmacy
```

Start in:

```text
C:\Path\To\cfi-edi-processor
```

## PyInstaller Packaging

Install build dependencies:

```powershell
python -m pip install ".[build]"
```

Build the executable:

```powershell
.\scripts\build_exe.ps1 -Clean
```

The packaged app is written to:

```text
dist\cfi-edi-processor\cfi-edi-processor.exe
```

The bundle includes:

- `templates\`
- `appsettings.json.example`
- `.env.example`

It does not include local `appsettings.json` or `.env`. Place those beside the `.exe` or pass explicit paths:

```powershell
.\dist\cfi-edi-processor\cfi-edi-processor.exe --config C:\EDI\config\appsettings.json --env-file C:\EDI\config\.env --dry-run --provider Kirk_Pharmacy
```

For the packaged Task Scheduler version, set Program to:

```text
C:\Path\To\dist\cfi-edi-processor\cfi-edi-processor.exe
```

Arguments:

```text
--config C:\EDI\config\appsettings.json --env-file C:\EDI\config\.env --allow-live --provider Kirk_Pharmacy
```

Start in:

```text
C:\Path\To\dist\cfi-edi-processor
```

## Pilot Checklist

1. Confirm `appsettings.json` has correct real paths.
2. Confirm `runtime.liveProviderAllowList` only includes `Kirk_Pharmacy`.
3. Confirm `duplicateCheck` settings and ODBC driver availability if duplicate checking is enabled.
4. Confirm converter executable paths.
5. Run `python main.py --dry-run --provider Kirk_Pharmacy`.
6. Review `logs/runs/{date}/{run_id}_summary.json`.
7. Confirm validation reports are expected or fix provider data/rules.
8. Run live with `python main.py --allow-live --provider Kirk_Pharmacy`.
9. Review run summary, converter logs, `INCOMING`, and archive folder.
10. Confirm transaction count reports are generated under `logs/transaction_counts`.
11. If using received date overrides, confirm `CFI-Admin\received_dates.csv` is deleted after a successful non-dry run.
12. Keep email disabled until notification routing is intentionally verified.
13. When ready, set `transactionReports.sendEmail: true`, configure the SFTP inbox recipient, and run with `--allow-email`.

## Current Known Deferred Items

- Real converter integration verification is intentionally skipped for now.
- Doctors Hospital direct 837P publish and mixed 837I/837P routing remains future work.
- Post-import QC reporting queries from legacy scripts are not part of the first workflow slice.
