# Revenue Decay Chart Pack Usage

Generates focused reporting charts, correlation diagnostics, optional Lumar diagnostics, and an optional PPTX attention pack.

## Files

- Pipeline: `src/pipelines/revenue_decay_chart_pack.py`
- Entrypoint: `scripts/run_revenue_decay_chart_pack.py`

## Inputs

- `decay_scores_all_pages.csv`
- `monthly_adjusted_signals.csv`
- optional `lumar_issues.csv` (issue category list)
- optional `lumar_pages.csv` (page-level Lumar crawl export)

## Example Command

```powershell
venv\Scripts\python.exe scripts\run_revenue_decay_chart_pack.py `
  --scores-csv reports\analysis\revenue_decay_radar\revenue_decay_scoring_2024_10_to_2026_01\decay_scores_all_pages.csv `
  --monthly-adjusted-csv reports\analysis\revenue_decay_radar\revenue_decay_scoring_2024_10_to_2026_01\monthly_adjusted_signals.csv `
  --lumar-pages-csv data\raw\lumar\lumar_pages.csv `
  --output-dir reports\analysis\revenue_decay_radar\revenue_decay_chart_pack_2024_10_to_2026_01 `
  --export-pptx
```

## Outputs

Charts (`charts/`):
- `top_20_risk_pages_overall.png`
- `top_10_risk_pages_by_page_type.png`
- `risk_score_distribution.png`
- `severity_distribution.png`
- `trend_panels_most_valuable_at_risk.png`
- `trend_correlation_scatter.png`
- `trend_quadrant_distribution.png`
- optional: `lumar_diagnostic_issue_signals.png`
- optional: `lumar_issue_categories.png`

CSV exports (`exports/`):
- `top_20_risk_pages_overall.csv`
- `top_10_risk_pages_by_page_type.csv`
- `most_valuable_at_risk_pages.csv`
- `trend_quadrant_summary.csv`
- `pages_both_down.csv`
- `pages_clicks_down_revenue_stable_up.csv`
- `pages_revenue_down_clicks_stable_up.csv`
- optional: `top_20_risk_pages_overall_with_lumar_diagnostics.csv`
- optional: `lumar_diagnostic_issue_summary.csv`
- optional: `lumar_issue_categories_top20.csv`

Run summary:
- `summary.json`

Optional PPTX:
- `revenue_decay_attention_pack.pptx`

## New Flags

- `--lumar-pages-csv`: joins Lumar page-level diagnostics by normalized URL path.
- `--lumar-issues-csv`: creates issue-category chart if you have category aggregates.
- `--export-pptx`: exports a slide deck from generated charts and tables.
- `--pptx-output`: custom output path for the deck.
- `--pptx-title`: custom deck title.
