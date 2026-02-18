# Revenue Decay Analyser

Page-level organic performance decay analyser for SEO teams.

## What It Does

- Pulls monthly GA4 + GSC page data
- Rebuilds a historical panel from stored monthly chunks
- De-seasonalizes revenue and clicks by `page_type x month_of_year`
- Computes robust trend slopes (Theil-Sen with fallback)
- Scores pages by decay risk
- Exports charts + a PPTX attention pack

## One Command (Monthly)

```powershell
venv\Scripts\python.exe scripts\run_revenue_decay_monthly_run.py --history-start-date 2024-10-01
```

## Setup

1. Create a venv and install dependencies:
   - `python -m venv venv`
   - `venv\Scripts\python.exe -m pip install -r requirements.decay_analyser.txt`
2. Copy `.env.example` to `.env` and set:
   - `GA4_PROPERTY_ID`
   - `GSC_SITE_URL`
   - credentials file paths in `secrets/`
3. Run the monthly command above.

## Docs

- `docs/REVENUE_DECAY_ANALYSER_MANUAL.md`
- `docs/REVENUE_DECAY_GITHUB_PUBLISH_SECURITY.md`
