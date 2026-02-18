# Revenue Decay Model Input Usage

Builds the model-ready monthly table by merging:
- GA4 monthly sessions/revenue
- GSC monthly clicks/impressions

## Files

- Pipeline: `src/pipelines/revenue_decay_model_input.py`
- Entrypoint: `scripts/run_revenue_decay_model_input.py`

## Output Schema

`model_input_monthly.csv` contains:
- `page`
- `month`
- `revenue`
- `clicks`
- `sessions`
- `impressions`
- `lumar_signals` (placeholder for later enrichment)
- `page_type` (URL-inferred by default; mapping file can override)
- `page_type_source` (`inferred` or `mapped`)
- `has_ga4_data`
- `has_gsc_data`

## Main Outputs

- `model_input_monthly.csv`
- `model_input_quality_summary.json`

## Example Command (UK Jan 2026)

```powershell
venv\Scripts\python.exe scripts\run_revenue_decay_model_input.py `
  --ga4-monthly-csv data\interim\revenue_decay_radar_chunk1_jan2026_uk\ga4_organic_page_monthly_compare.csv `
  --gsc-monthly-csv data\interim\revenue_decay_radar_chunk1_jan2026_gsc_uk_v2\gsc_organic_page_monthly.csv `
  --gsc-summary-json data\interim\revenue_decay_radar_chunk1_jan2026_gsc_uk_v2\summary.json `
  --start-month 2026-01 `
  --end-month 2026-01 `
  --output-dir data\interim\revenue_decay_radar_chunk1_jan2026_model_input_uk
```

## Optional Inputs

- `--page-type-csv` mapping file:
  - accepted path columns: `page_path`, `page`, `path`, `url`
  - accepted type columns: `page_type`, `type`, `template`, `category`
- `--start-month`, `--end-month` in `YYYY-MM`

## Default URL-Based Page Type Rules

- `/mattresses/...` -> `category_mattresses`
- `/beds/...` -> `category_beds`
- `/products/...` -> `products` or product subtypes:
  - `product_beds`
  - `product_mattresses`
  - `product_headboards`
  - `product_bedding`
  - `product_furniture`
- `/sleep-hub/...`, `/guides/...`, `/blog/...` -> `content`

## Quality Summary Highlights

`model_input_quality_summary.json` reports:
- source overlap and page coverage
- totals for sessions/revenue/clicks/impressions
- inferred vs mapped page type usage
- GSC page-vs-property reconciliation if GSC summary is provided
