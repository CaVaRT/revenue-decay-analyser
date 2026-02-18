# Revenue Decay Scoring Usage

This pipeline scores page-level decay risk from the merged model input table.

## What It Does
- Reads `model_input_monthly.csv` from the model-input pipeline.
- Computes seasonality factors by `page_type x month_of_year` for:
  - revenue
  - clicks
- Builds adjusted signals:
  - `rev_adj = log1p(revenue / revenue_seasonality_factor)`
  - `clicks_adj = log1p(clicks / clicks_seasonality_factor)`
- Computes page trends using all available months:
  - `slope_rev` (Theil-Sen; polyfit fallback)
  - `slope_clicks` (Theil-Sen; polyfit fallback)
- Keeps latest YoY deltas as separate signals:
  - `revenue_yoy_delta`
  - `clicks_yoy_delta`
- Produces final score:
  - `score_base = 0.65*rev_decay + 0.35*click_decay`
  - adjusted by confidence factor (history + GA4 coverage + GSC coverage + volume)
  - multiplied by optional global GSC click coverage ratio from GSC summary

## Files Involved
- Pipeline: `src/pipelines/revenue_decay_scoring.py`
- Entrypoint: `scripts/run_revenue_decay_scoring.py`
- Default output root: `reports/analysis/revenue_decay_radar/`

## Required Input
- Model input monthly file:
  - `data/interim/revenue_decay_radar_model_input/model_input_monthly.csv`
- Optional GSC summary for coverage adjustment:
  - `data/interim/revenue_decay_radar_combined/gsc_summary.json`

## Run Command
```powershell
.\venv\Scripts\python.exe scripts\run_revenue_decay_scoring.py `
  --input-model-csv data\interim\revenue_decay_radar_model_input\model_input_monthly.csv `
  --gsc-summary-json data\interim\revenue_decay_radar_combined\gsc_summary.json `
  --output-dir reports\analysis\revenue_decay_radar\revenue_decay_scoring_2024_10_to_2026_01 `
  --start-month 2024-10 `
  --end-month 2026-01 `
  --top-n 300
```

## Main Outputs
- `decay_scores_all_pages.csv`
  - scored full page list
- `decay_scores_top_pages.csv`
  - top `N` pages by `decay_score`
- `decay_pages_losing_revenue_and_clicks.csv`
  - pages where both `slope_rev < 0` and `slope_clicks < 0`
- `seasonality_factors_page_type_month.csv`
  - seasonality factors used for revenue and clicks normalization
- `monthly_adjusted_signals.csv`
  - page-month adjusted signals and factors
- `summary.json`
  - run metadata, counts, score distribution, and config

## Key Fields In Output
- `decay_score` (0-100): final priority score.
- `severity`: `Critical`, `High`, `Medium`, `Low`, `Monitor`.
- `slope_rev`, `slope_clicks`: trend features from adjusted signals.
- `revenue_yoy_delta`, `clicks_yoy_delta`: latest YoY signals.
- `losing_revenue_and_clicks`: boolean signal for dual decline.
- `confidence_factor`: confidence adjustment (history/coverage/volume).

## Notes
- Works with GSC retention constraints for your property.
- With short history windows, the pipeline still runs, but confidence falls.
- If GSC page-level coverage vs property totals is low, score confidence is reduced.
