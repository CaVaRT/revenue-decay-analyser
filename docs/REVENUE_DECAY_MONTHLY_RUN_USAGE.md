# Revenue Decay Monthly Automation Usage

Runs the full monthly workflow in one command:
- incremental data pull (latest month)
- combine historical chunks
- model input refresh
- scoring
- chart pack and PPTX

## Files

- Pipeline: `src/pipelines/revenue_decay_monthly_run.py`
- Entrypoint: `scripts/run_revenue_decay_monthly_run.py`

## Default Behavior

- If `--target-month` is not provided, it uses the **last completed month**.
- Example: if run on **March 1, 2026**, it targets **February 2026** (`2026-02`).
- Pull step fetches the target month and then recombines all stored chunk history from `--history-start-date` onward.

## Required Configuration

Before running, provide:
- GA4 property ID (`GA4_PROPERTY_ID` in `.env` or `--ga4-property-id`)
- GSC site URL (`GSC_SITE_URL` in `.env` or `--gsc-site-url`)
- valid credential files under `secrets/`

## One-Command Run

```powershell
venv\Scripts\python.exe scripts\run_revenue_decay_monthly_run.py `
  --history-start-date 2024-10-01
```

## Optional Target Month

```powershell
venv\Scripts\python.exe scripts\run_revenue_decay_monthly_run.py `
  --target-month 2026-02 `
  --history-start-date 2024-10-01
```

## Main Outputs

- Combined/model:
  - `data/interim/revenue_decay_radar_combined/*`
  - `data/interim/revenue_decay_radar_model_input/*`
- Scoring folder:
  - `reports/analysis/revenue_decay_radar/revenue_decay_scoring_<history_start>_to_<target_month>/`
- Chart pack folder:
  - `reports/analysis/revenue_decay_radar/revenue_decay_chart_pack_<history_start>_to_<target_month>/`
  - `revenue_decay_attention_pack.pptx`
  - `summary.json`
  - `monthly_run_summary.json`

## Useful Flags

- `--months-per-chunk 1` (default): monthly incremental pulls
- `--no-pptx`: skip PPTX generation
- `--page-type-csv <path>`: apply manual page type mapping
- `--lumar-pages-csv <path>`: optional diagnostic exports/charts
