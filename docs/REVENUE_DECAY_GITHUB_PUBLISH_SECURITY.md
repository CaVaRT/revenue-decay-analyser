# Revenue Decay App: Secure GitHub Publish Guide

Use this guide when you want to publish only the decay analyser code safely.

## Goal

Publish a **clean code-only repo** with:
- no secrets
- no tokens
- no client credentials
- no customer data extracts
- no generated reports

## Recommended Method (Safest)

Export a fresh clean repo folder and publish that folder as a new Git repo.

```powershell
venv\Scripts\python.exe scripts\export_revenue_decay_app.py `
  --output-dir ..\revenue-decay-analyser-public `
  --overwrite
```

Then:

```powershell
cd ..\revenue-decay-analyser-public
git init
git add .
git commit -m "Initial commit: revenue decay analyser"
git branch -M main
git remote add origin <your-new-github-repo-url>
git push -u origin main
```

This avoids leaking historical commits from your larger local repo.

## If You Publish From Current Repo (Higher Risk)

Only do this if you fully understand Git history risks.

1. Ensure ignores are in place:
- `secrets/`
- `.env*`
- `data/`
- `reports/`
- tokens and credential files

2. Check staged files before commit:

```powershell
git status
git diff --cached --name-only
```

3. Scan tracked files for obvious secrets:

```powershell
rg -n "BEGIN PRIVATE KEY|client_secret|token.pickle|AIza|oauth|service_account" .
```

4. Scan Git history for leaked secrets:
- Use `trufflehog` or `gitleaks` against full history.

If leaks are found in history, rotate credentials and rewrite history before publishing.

## Credential Hardening

- Use separate Google credentials for shared/open repos.
- Keep API scopes read-only:
  - GA4: `analytics.readonly`
  - GSC: `webmasters.readonly`
- Never commit:
  - `secrets/*.json`
  - OAuth token files (`*.pickle`)
  - `.env` files

## Data Safety

Do not publish:
- GA4/GSC raw exports
- intermediate model CSVs
- PPTX reports with business data

Keep all generated outputs local (`data/`, `reports/`) and ignored.

## Minimal Publish Contents

For this app, share only:
- `src/common/config.py`
- `src/pipelines/ga4_organic_seo_extract.py`
- `src/pipelines/gsc_organic_page_extract.py`
- `src/pipelines/revenue_decay_*.py`
- `scripts/run_*.py` for decay analyser
- `requirements.decay_analyser.txt`
- docs under `docs/REVENUE_DECAY_*`

## Pre-Publish Checklist

- [ ] Exported to a fresh clean folder
- [ ] No `secrets/` folder present
- [ ] No `data/` or `reports/` content present
- [ ] No `.env` real values present
- [ ] Secret scan completed
- [ ] Credentials rotated if anything was ever exposed
