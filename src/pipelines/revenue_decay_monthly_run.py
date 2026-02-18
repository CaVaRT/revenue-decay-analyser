from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

from src.common.config import ROOT_DIR


def parse_date(text: str) -> date:
    return datetime.strptime(text.strip(), "%Y-%m-%d").date()


def parse_month(text: str) -> tuple[int, int]:
    parsed = datetime.strptime(text.strip(), "%Y-%m")
    return parsed.year, parsed.month


def month_end(year: int, month: int) -> date:
    if month == 12:
        return date(year + 1, 1, 1) - timedelta(days=1)
    return date(year, month + 1, 1) - timedelta(days=1)


def previous_complete_month(today: date | None = None) -> tuple[date, date]:
    current = today or date.today()
    first_of_current = date(current.year, current.month, 1)
    end_prev = first_of_current - timedelta(days=1)
    start_prev = date(end_prev.year, end_prev.month, 1)
    return start_prev, end_prev


def run_command(command: list[str], *, cwd: Path) -> None:
    result = subprocess.run(command, cwd=str(cwd), check=False)
    if result.returncode != 0:
        raise RuntimeError(f"Command failed ({result.returncode}): {' '.join(command)}")


def run(args: argparse.Namespace) -> None:
    python_exe = Path(args.python_exe)
    if not python_exe.exists():
        raise FileNotFoundError(f"Python executable not found: {python_exe}")

    if args.target_month:
        year, month = parse_month(args.target_month)
        pull_start = date(year, month, 1)
        pull_end = month_end(year, month)
    else:
        pull_start, pull_end = previous_complete_month()

    history_start_date = parse_date(args.history_start_date)
    history_start_month = args.history_start_month or f"{history_start_date.year:04d}-{history_start_date.month:02d}"
    run_end_month = f"{pull_end.year:04d}-{pull_end.month:02d}"
    history_label = history_start_month.replace("-", "_")
    end_label = run_end_month.replace("-", "_")

    scoring_output_dir = Path(args.scoring_output_root) / f"revenue_decay_scoring_{history_label}_to_{end_label}"
    chart_output_dir = Path(args.chart_output_root) / f"revenue_decay_chart_pack_{history_label}_to_{end_label}"
    chunk_root = Path(args.chunk_root)
    combined_output_dir = Path(args.combined_output_dir)
    model_output_dir = Path(args.model_output_dir)

    chunk_command = [
        str(python_exe),
        "scripts/run_revenue_decay_chunked_pull.py",
        "--start-date",
        pull_start.isoformat(),
        "--end-date",
        pull_end.isoformat(),
        "--months-per-chunk",
        str(args.months_per_chunk),
        "--resume",
        "--combine-all-existing-chunks",
        "--combine-start-date",
        history_start_date.isoformat(),
        "--combine-end-date",
        pull_end.isoformat(),
        "--model-start-month",
        history_start_month,
        "--model-end-month",
        run_end_month,
        "--chunk-root",
        str(chunk_root),
        "--combined-output-dir",
        str(combined_output_dir),
        "--model-output-dir",
        str(model_output_dir),
        "--ga4-auth-mode",
        args.ga4_auth_mode,
        "--ga4-property-id",
        args.ga4_property_id,
        "--ga4-country",
        args.ga4_country,
        "--ga4-service-account-file",
        args.ga4_service_account_file,
        "--ga4-oauth-client-secrets-file",
        args.ga4_oauth_client_secrets_file,
        "--ga4-oauth-token-file",
        args.ga4_oauth_token_file,
        "--gsc-site-url",
        args.gsc_site_url,
        "--gsc-country-code",
        args.gsc_country_code,
        "--gsc-service-account-file",
        args.gsc_service_account_file,
    ]
    if args.page_type_csv:
        chunk_command.extend(["--page-type-csv", args.page_type_csv])

    run_command(chunk_command, cwd=ROOT_DIR)

    model_input_csv = model_output_dir / "model_input_monthly.csv"
    gsc_summary_json = combined_output_dir / "gsc_summary.json"

    scoring_command = [
        str(python_exe),
        "scripts/run_revenue_decay_scoring.py",
        "--input-model-csv",
        str(model_input_csv),
        "--gsc-summary-json",
        str(gsc_summary_json),
        "--start-month",
        history_start_month,
        "--end-month",
        run_end_month,
        "--top-n",
        str(args.top_n_scoring),
        "--output-dir",
        str(scoring_output_dir),
    ]
    run_command(scoring_command, cwd=ROOT_DIR)

    chart_command = [
        str(python_exe),
        "scripts/run_revenue_decay_chart_pack.py",
        "--scores-csv",
        str(scoring_output_dir / "decay_scores_all_pages.csv"),
        "--monthly-adjusted-csv",
        str(scoring_output_dir / "monthly_adjusted_signals.csv"),
        "--top-n-overall",
        str(args.top_n_overall),
        "--top-n-per-page-type",
        str(args.top_n_per_page_type),
        "--max-page-types-facet",
        str(args.max_page_types_facet),
        "--trend-pages-count",
        str(args.trend_pages_count),
        "--output-dir",
        str(chart_output_dir),
        "--pptx-title",
        args.pptx_title,
    ]
    if not args.no_pptx:
        chart_command.append("--export-pptx")
    if args.lumar_pages_csv:
        chart_command.extend(["--lumar-pages-csv", args.lumar_pages_csv])
    if args.lumar_issues_csv:
        chart_command.extend(["--lumar-issues-csv", args.lumar_issues_csv])
    run_command(chart_command, cwd=ROOT_DIR)

    summary = {
        "run_date_utc": datetime.utcnow().isoformat() + "Z",
        "run_month": run_end_month,
        "window": {
            "history_start_date": history_start_date.isoformat(),
            "pull_start_date": pull_start.isoformat(),
            "pull_end_date": pull_end.isoformat(),
            "history_start_month": history_start_month,
            "scoring_end_month": run_end_month,
        },
        "commands": {
            "chunked_pull": chunk_command,
            "scoring": scoring_command,
            "chart_pack": chart_command,
        },
        "outputs": {
            "chunk_root": str(chunk_root),
            "combined_output_dir": str(combined_output_dir),
            "model_output_dir": str(model_output_dir),
            "scoring_output_dir": str(scoring_output_dir),
            "chart_output_dir": str(chart_output_dir),
            "pptx": (
                str(chart_output_dir / "revenue_decay_attention_pack.pptx")
                if not args.no_pptx
                else None
            ),
        },
    }
    summary_out = chart_output_dir / "monthly_run_summary.json"
    summary_out.parent.mkdir(parents=True, exist_ok=True)
    summary_out.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print(f"Wrote: {summary_out}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "One-command monthly revenue-decay automation: pulls latest month, "
            "rebuilds combined/model inputs from stored chunks, then runs scoring and chart pack."
        )
    )
    parser.add_argument(
        "--target-month",
        default="",
        help="Optional target month in YYYY-MM. Defaults to last completed month.",
    )
    parser.add_argument(
        "--history-start-date",
        default="2024-10-01",
        help="Start date for retained historical panel (YYYY-MM-DD).",
    )
    parser.add_argument(
        "--history-start-month",
        default="",
        help="Optional start month override for scoring/model input (YYYY-MM).",
    )
    parser.add_argument(
        "--months-per-chunk",
        type=int,
        default=1,
        help="Months per new pull chunk. Default 1 for monthly incremental updates.",
    )
    parser.add_argument(
        "--python-exe",
        default=str(ROOT_DIR / "venv" / "Scripts" / "python.exe"),
        help="Python executable used to run sub-pipelines.",
    )
    parser.add_argument(
        "--chunk-root",
        default=str(ROOT_DIR / "data" / "interim" / "revenue_decay_radar_chunks"),
        help="Chunk storage directory.",
    )
    parser.add_argument(
        "--combined-output-dir",
        default=str(ROOT_DIR / "data" / "interim" / "revenue_decay_radar_combined"),
        help="Combined GA4/GSC output directory.",
    )
    parser.add_argument(
        "--model-output-dir",
        default=str(ROOT_DIR / "data" / "interim" / "revenue_decay_radar_model_input"),
        help="Model input output directory.",
    )
    parser.add_argument(
        "--scoring-output-root",
        default=str(ROOT_DIR / "reports" / "analysis" / "revenue_decay_radar"),
        help="Root directory for scoring output folders.",
    )
    parser.add_argument(
        "--chart-output-root",
        default=str(ROOT_DIR / "reports" / "analysis" / "revenue_decay_radar"),
        help="Root directory for chart pack output folders.",
    )
    parser.add_argument(
        "--page-type-csv",
        default="",
        help="Optional page type mapping CSV path.",
    )

    parser.add_argument(
        "--top-n-scoring",
        type=int,
        default=300,
        help="Top-N output size for scoring.",
    )
    parser.add_argument(
        "--top-n-overall",
        type=int,
        default=20,
        help="Top-N overall pages for chart pack.",
    )
    parser.add_argument(
        "--top-n-per-page-type",
        type=int,
        default=10,
        help="Top-N pages per page type for chart pack.",
    )
    parser.add_argument(
        "--max-page-types-facet",
        type=int,
        default=8,
        help="Max page types for facet chart.",
    )
    parser.add_argument(
        "--trend-pages-count",
        type=int,
        default=2,
        help="Trend panel page count.",
    )
    parser.add_argument(
        "--no-pptx",
        action="store_true",
        help="Disable PPTX generation.",
    )
    parser.add_argument(
        "--pptx-title",
        default="Revenue Decay Radar: Pages Requiring Attention",
        help="PPTX title text.",
    )
    parser.add_argument(
        "--lumar-pages-csv",
        default="",
        help="Optional Lumar pages CSV for diagnostic chart/exports.",
    )
    parser.add_argument(
        "--lumar-issues-csv",
        default="",
        help="Optional Lumar issue categories CSV for chart output.",
    )

    parser.add_argument(
        "--ga4-auth-mode",
        choices=["service_account", "oauth"],
        default="oauth",
        help="GA4 auth mode.",
    )
    parser.add_argument(
        "--ga4-property-id",
        default="",
        help="GA4 property ID.",
    )
    parser.add_argument(
        "--ga4-country",
        default="",
        help="GA4 country filter value.",
    )
    parser.add_argument(
        "--ga4-service-account-file",
        default=str(ROOT_DIR / "secrets" / "credentials" / "ga4_service_account.json"),
        help="GA4 service account file path.",
    )
    parser.add_argument(
        "--ga4-oauth-client-secrets-file",
        default=str(ROOT_DIR / "secrets" / "ga4_oauth" / "credentials.json"),
        help="GA4 OAuth client secrets file path.",
    )
    parser.add_argument(
        "--ga4-oauth-token-file",
        default=str(ROOT_DIR / "secrets" / "ga4_oauth" / "token.pickle"),
        help="GA4 OAuth token file path.",
    )
    parser.add_argument(
        "--gsc-site-url",
        default="",
        help="GSC property URL.",
    )
    parser.add_argument(
        "--gsc-country-code",
        default="all",
        help="GSC country code filter.",
    )
    parser.add_argument(
        "--gsc-service-account-file",
        default=str(ROOT_DIR / "secrets" / "credentials" / "gsc_service_account.json"),
        help="GSC service account file path.",
    )
    return parser


if __name__ == "__main__":
    parser = build_parser()
    try:
        run(parser.parse_args())
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1)
