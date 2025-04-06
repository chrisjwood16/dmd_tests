# OpenPrescribing Hospitals – dm+d Code Monitoring

This repository is used to monitor and maintain the integrity of dm+d codes used in the [OpenPrescribing Hospitals](https://github.com/ebmdatalab/openprescribing-hospitals) SQL measure definitions.

It helps ensure that all referenced dm+d codes are still valid and highlights any that may require review or updates.

## Purpose

- Check that all dm+d codes used in SQL measure files are still active.
- Identify codes that have been retired or are no longer resolvable via the NHS Terminology Server.
- Support timely updates to SQL measures when codes change or become obsolete.

## How it works

- SQL files in each measure folder are scanned for numeric codes with seven or more digits.
- These codes are validated using the NHS Terminology Server `$lookup` endpoint.
- Each code is classified as:
  - **Active**
  - **Inactive**
  - **Unknown** (i.e. not found on the server)

## Reports

An HTML report is generated for each dm+d release, listing codes by status and folder.

- **[View report index](https://htmlpreview.github.io/?https://github.com/chrisjwood16/dmd_tests/blob/main/reports/list_dmd_lookup_reports.html)**
- **[View latest report](https://htmlpreview.github.io/?https://github.com/chrisjwood16/dmd_tests/blob/main/reports/dmd_lookup_latest.html)**

## Automation

The process is automated via GitHub Actions:

- A daily scheduled action checks for a new dm+d version.
- If a new version is found, it performs code lookups and generates a report.
- A manual workflow is also available to force an update.

## Structure

- `reports/`
  - `dmd_lookup_report_<version>.html` – HTML report for each version
  - `dmd_lookup_latest.html` – Redirects to the most recent report
  - `list_dmd_lookup_reports.html` – Index of all generated reports

- `src/`
  - `config.ini` – Stores configuration such as preview URL

- `credentials.json` – Created at runtime (from GitHub secrets) to authenticate with the NHS Terminology Server

## Maintainers

If a report indicates inactive or unknown codes, review the relevant SQL definitions in the [OpenPrescribing Hospitals](https://github.com/ebmdatalab/openprescribing-hospitals) repository and update the measures accordingly.
