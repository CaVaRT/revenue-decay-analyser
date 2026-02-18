# Revenue Decay Chunked Pull Usage

Runs resilient historical pulls for revenue-decay modeling:
- GA4 sessions/revenue (chunked)
- GSC clicks/impressions (chunked)
- Combined monthly outputs
- Model input build

## Files

- Pipeline: `src/pipelines/revenue_decay_chunked_pull.py`
- Entrypoint: `scripts/run_revenue_decay_chunked_pull.py`

## Why This Exists

- GSC has limited historical retention (typically last 16 months).
- Long API windows can fail mid-run.
- Chunking by a few months lets you resume safely and avoid restarting everything.

## Recommended Window

- Start: `2024-10-01` (fits 16-month GSC history for Jan 2026 and avoids pre-GA4 era)
- End: last day of latest completed month (example: `2026-01-31`)

## Standard Command

```powershell
venv\Scripts\python.exe scripts\run_revenue_decay_chunked_pull.py `
  --start-date 2024-10-01 `
  --end-date 2026-01-31 `
  --months-per-chunk 3 `
  --resume
```

## Key Options

- `--months-per-chunk`: default `3`
- `--resume`: skip chunks already pulled
- `--ga4-country`: default empty (no country filter)
- `--gsc-country-code`: default `all` (no country filter)
- `--gsc-site-url`: your GSC property URL (required via arg or `.env`)
- `--combine-all-existing-chunks`: rebuild combined/model outputs from all stored chunks
- `--combine-start-date` / `--combine-end-date`: bound historical window when combining existing chunks
- `--model-start-month` / `--model-end-month`: force model input month window

Required:
- `GA4_PROPERTY_ID` via `.env` or `--ga4-property-id`
- `GSC_SITE_URL` via `.env` or `--gsc-site-url`

## Outputs

Chunked raw outputs:
- `data/interim/revenue_decay_radar_chunks/<chunk>/ga4/*`
- `data/interim/revenue_decay_radar_chunks/<chunk>/gsc/*`

Combined outputs:
- `data/interim/revenue_decay_radar_combined/ga4_organic_page_monthly_compare.csv`
- `data/interim/revenue_decay_radar_combined/gsc_organic_page_monthly.csv`
- `data/interim/revenue_decay_radar_combined/gsc_property_totals_daily.csv`
- `data/interim/revenue_decay_radar_combined/gsc_summary.json`
- `data/interim/revenue_decay_radar_combined/chunked_pull_summary.json`

Model input:
- `data/interim/revenue_decay_radar_model_input/model_input_monthly.csv`
- `data/interim/revenue_decay_radar_model_input/model_input_quality_summary.json`
