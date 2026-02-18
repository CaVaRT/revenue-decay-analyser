from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd

from src.common.config import ROOT_DIR


@dataclass(frozen=True)
class ChunkRange:
    start_date: date
    end_date: date

    @property
    def key(self) -> str:
        return f"{self.start_date.isoformat()}_to_{self.end_date.isoformat()}"


CHUNK_NAME_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})_to_(\d{4}-\d{2}-\d{2})$")


def parse_date(text: str) -> date:
    return datetime.strptime(text.strip(), "%Y-%m-%d").date()


def parse_month(text: str) -> tuple[int, int]:
    parsed = datetime.strptime(text.strip(), "%Y-%m")
    return parsed.year, parsed.month


def last_day_of_month(year: int, month: int) -> date:
    if month == 12:
        return date(year + 1, 1, 1) - timedelta(days=1)
    return date(year, month + 1, 1) - timedelta(days=1)


def add_months(year: int, month: int, delta_months: int) -> tuple[int, int]:
    idx = (year * 12 + (month - 1)) + delta_months
    new_year = idx // 12
    new_month = (idx % 12) + 1
    return new_year, new_month


def month_start(d: date) -> date:
    return date(d.year, d.month, 1)


def month_end(d: date) -> date:
    return last_day_of_month(d.year, d.month)


def default_end_date() -> date:
    today = date.today()
    first_of_current_month = date(today.year, today.month, 1)
    return first_of_current_month - timedelta(days=1)


def build_chunk_ranges(
    *,
    start_date: date,
    end_date: date,
    months_per_chunk: int,
) -> list[ChunkRange]:
    if start_date > end_date:
        raise ValueError("start_date cannot be after end_date")
    if months_per_chunk <= 0:
        raise ValueError("months_per_chunk must be >= 1")

    ranges: list[ChunkRange] = []
    cursor = month_start(start_date)
    while cursor <= end_date:
        chunk_start = max(cursor, start_date)
        end_year, end_month = add_months(cursor.year, cursor.month, months_per_chunk - 1)
        candidate_end = last_day_of_month(end_year, end_month)
        chunk_end = min(candidate_end, end_date)
        ranges.append(ChunkRange(start_date=chunk_start, end_date=chunk_end))
        cursor = chunk_end + timedelta(days=1)
    return ranges


def parse_chunk_name(chunk_name: str) -> ChunkRange | None:
    match = CHUNK_NAME_RE.match(chunk_name.strip())
    if not match:
        return None
    start_text, end_text = match.groups()
    start = parse_date(start_text)
    end = parse_date(end_text)
    if start > end:
        return None
    return ChunkRange(start_date=start, end_date=end)


def list_existing_chunk_dirs(
    chunk_root: Path,
    *,
    combine_start: date | None = None,
    combine_end: date | None = None,
) -> list[Path]:
    if not chunk_root.exists():
        return []

    selected: list[tuple[ChunkRange, Path]] = []
    for child in chunk_root.iterdir():
        if not child.is_dir():
            continue
        parsed = parse_chunk_name(child.name)
        if not parsed:
            continue
        if combine_start and parsed.end_date < combine_start:
            continue
        if combine_end and parsed.start_date > combine_end:
            continue
        selected.append((parsed, child))

    selected.sort(key=lambda item: (item[0].start_date, item[0].end_date))
    return [path for _, path in selected]


def run_command(command: list[str], *, cwd: Path) -> None:
    result = subprocess.run(command, cwd=str(cwd), check=False)
    if result.returncode != 0:
        joined = " ".join(command)
        raise RuntimeError(f"Command failed ({result.returncode}): {joined}")


def combine_ga4_monthly(chunk_dirs: list[Path]) -> pd.DataFrame:
    parts: list[pd.DataFrame] = []
    for chunk_dir in chunk_dirs:
        path = chunk_dir / "ga4" / "seo_organic_page_monthly.csv"
        if not path.exists():
            continue
        df = pd.read_csv(path)
        if df.empty:
            continue
        if not {"month", "page_path", "organic_sessions", "organic_revenue"}.issubset(df.columns):
            raise ValueError(f"Unexpected GA4 monthly schema: {path}")
        subset = df[["month", "page_path", "organic_sessions", "organic_revenue"]].copy()
        subset["month"] = pd.to_datetime(subset["month"], errors="coerce")
        subset["organic_sessions"] = pd.to_numeric(
            subset["organic_sessions"], errors="coerce"
        ).fillna(0.0)
        subset["organic_revenue"] = pd.to_numeric(
            subset["organic_revenue"], errors="coerce"
        ).fillna(0.0)
        parts.append(subset)
    if not parts:
        return pd.DataFrame(
            columns=["month", "page_path", "organic_sessions", "organic_revenue"]
        )
    all_df = pd.concat(parts, ignore_index=True)
    return (
        all_df.groupby(["month", "page_path"], as_index=False)[
            ["organic_sessions", "organic_revenue"]
        ]
        .sum()
        .sort_values(["month", "page_path"])
    )


def combine_gsc_monthly(chunk_dirs: list[Path]) -> pd.DataFrame:
    parts: list[pd.DataFrame] = []
    for chunk_dir in chunk_dirs:
        path = chunk_dir / "gsc" / "gsc_organic_page_monthly.csv"
        if not path.exists():
            continue
        df = pd.read_csv(path)
        if df.empty:
            continue
        if not {"month", "page_path", "organic_clicks_gsc", "organic_impressions_gsc"}.issubset(
            df.columns
        ):
            raise ValueError(f"Unexpected GSC monthly schema: {path}")
        subset = df[
            ["month", "page_path", "organic_clicks_gsc", "organic_impressions_gsc"]
        ].copy()
        subset["month"] = pd.to_datetime(subset["month"], errors="coerce")
        subset["organic_clicks_gsc"] = pd.to_numeric(
            subset["organic_clicks_gsc"], errors="coerce"
        ).fillna(0.0)
        subset["organic_impressions_gsc"] = pd.to_numeric(
            subset["organic_impressions_gsc"], errors="coerce"
        ).fillna(0.0)
        parts.append(subset)
    if not parts:
        return pd.DataFrame(
            columns=["month", "page_path", "organic_clicks_gsc", "organic_impressions_gsc"]
        )
    all_df = pd.concat(parts, ignore_index=True)
    return (
        all_df.groupby(["month", "page_path"], as_index=False)[
            ["organic_clicks_gsc", "organic_impressions_gsc"]
        ]
        .sum()
        .sort_values(["month", "page_path"])
    )


def combine_gsc_property_totals_daily(chunk_dirs: list[Path]) -> pd.DataFrame:
    parts: list[pd.DataFrame] = []
    for chunk_dir in chunk_dirs:
        path = chunk_dir / "gsc" / "property_totals_daily.csv"
        if not path.exists():
            continue
        df = pd.read_csv(path)
        if df.empty:
            continue
        required = {
            "date",
            "property_clicks_gsc",
            "property_impressions_gsc",
            "page_clicks_gsc",
            "page_impressions_gsc",
        }
        if not required.issubset(df.columns):
            raise ValueError(f"Unexpected GSC property totals schema: {path}")
        subset = df[list(required)].copy()
        subset["date"] = pd.to_datetime(subset["date"], errors="coerce")
        for column in required - {"date"}:
            subset[column] = pd.to_numeric(subset[column], errors="coerce").fillna(0.0)
        parts.append(subset)

    if not parts:
        return pd.DataFrame(
            columns=[
                "date",
                "property_clicks_gsc",
                "property_impressions_gsc",
                "page_clicks_gsc",
                "page_impressions_gsc",
                "clicks_coverage_pct",
                "impressions_coverage_pct",
            ]
        )

    all_df = (
        pd.concat(parts, ignore_index=True)
        .groupby("date", as_index=False)[
            [
                "property_clicks_gsc",
                "property_impressions_gsc",
                "page_clicks_gsc",
                "page_impressions_gsc",
            ]
        ]
        .sum()
        .sort_values("date")
    )
    all_df["clicks_coverage_pct"] = (
        all_df["page_clicks_gsc"] / all_df["property_clicks_gsc"].replace(0, pd.NA) * 100.0
    )
    all_df["impressions_coverage_pct"] = (
        all_df["page_impressions_gsc"]
        / all_df["property_impressions_gsc"].replace(0, pd.NA)
        * 100.0
    )
    all_df["clicks_coverage_pct"] = pd.to_numeric(
        all_df["clicks_coverage_pct"], errors="coerce"
    ).round(4)
    all_df["impressions_coverage_pct"] = pd.to_numeric(
        all_df["impressions_coverage_pct"], errors="coerce"
    ).round(4)
    return all_df


def run(args: argparse.Namespace) -> None:
    start_date = parse_date(args.start_date)
    end_date = parse_date(args.end_date)
    if args.combine_all_existing_chunks:
        combine_start = parse_date(args.combine_start_date) if args.combine_start_date else None
        combine_end = parse_date(args.combine_end_date) if args.combine_end_date else end_date
        if combine_start and combine_end and combine_start > combine_end:
            raise ValueError("combine_start_date cannot be after combine_end_date.")
    else:
        combine_start = None
        combine_end = end_date

    chunk_ranges = build_chunk_ranges(
        start_date=start_date,
        end_date=end_date,
        months_per_chunk=args.months_per_chunk,
    )
    python_exe = Path(args.python_exe)
    if not python_exe.exists():
        raise FileNotFoundError(f"Python executable not found: {python_exe}")

    chunk_root = Path(args.chunk_root)
    chunk_root.mkdir(parents=True, exist_ok=True)
    combined_output_dir = Path(args.combined_output_dir)
    combined_output_dir.mkdir(parents=True, exist_ok=True)
    model_output_dir = Path(args.model_output_dir)
    model_output_dir.mkdir(parents=True, exist_ok=True)

    chunk_status: list[dict[str, object]] = []
    for chunk in chunk_ranges:
        chunk_dir = chunk_root / chunk.key
        ga4_dir = chunk_dir / "ga4"
        gsc_dir = chunk_dir / "gsc"
        ga4_daily = ga4_dir / "seo_organic_page_daily.csv"
        ga4_monthly = ga4_dir / "seo_organic_page_monthly.csv"
        gsc_daily = gsc_dir / "gsc_organic_page_daily.csv"
        gsc_monthly = gsc_dir / "gsc_organic_page_monthly.csv"
        gsc_property = gsc_dir / "property_totals_daily.csv"

        chunk_dir.mkdir(parents=True, exist_ok=True)
        ga4_dir.mkdir(parents=True, exist_ok=True)
        gsc_dir.mkdir(parents=True, exist_ok=True)

        ready = (
            ga4_daily.exists()
            and ga4_monthly.exists()
            and gsc_daily.exists()
            and gsc_monthly.exists()
            and gsc_property.exists()
        )
        if ready and args.resume:
            chunk_status.append(
                {
                    "chunk": chunk.key,
                    "status": "skipped_existing",
                    "start_date": chunk.start_date.isoformat(),
                    "end_date": chunk.end_date.isoformat(),
                }
            )
            continue

        ga4_command = [
            str(python_exe),
            "scripts/run_ga4_organic_seo_extract.py",
            "--auth-mode",
            args.ga4_auth_mode,
            "--property-id",
            args.ga4_property_id,
            "--start-date",
            chunk.start_date.isoformat(),
            "--end-date",
            chunk.end_date.isoformat(),
            "--ga4-country",
            args.ga4_country,
            "--clicks-source",
            "prefer_gsc",
            "--gsc-clicks-csv",
            str(chunk_dir / "_missing_gsc_clicks.csv"),
            "--output-dir",
            str(ga4_dir),
        ]
        if args.ga4_auth_mode == "oauth":
            ga4_command.extend(
                [
                    "--oauth-client-secrets-file",
                    args.ga4_oauth_client_secrets_file,
                    "--oauth-token-file",
                    args.ga4_oauth_token_file,
                ]
            )
        else:
            ga4_command.extend(
                [
                    "--service-account-file",
                    args.ga4_service_account_file,
                ]
            )

        gsc_command = [
            str(python_exe),
            "scripts/run_gsc_organic_page_extract.py",
            "--site-url",
            args.gsc_site_url,
            "--service-account-file",
            args.gsc_service_account_file,
            "--start-date",
            chunk.start_date.isoformat(),
            "--end-date",
            chunk.end_date.isoformat(),
            "--country-code",
            args.gsc_country_code,
            "--output-dir",
            str(gsc_dir),
        ]

        run_command(ga4_command, cwd=ROOT_DIR)
        run_command(gsc_command, cwd=ROOT_DIR)

        chunk_status.append(
            {
                "chunk": chunk.key,
                "status": "pulled",
                "start_date": chunk.start_date.isoformat(),
                "end_date": chunk.end_date.isoformat(),
                "ga4_dir": str(ga4_dir),
                "gsc_dir": str(gsc_dir),
            }
        )

    if args.combine_all_existing_chunks:
        chunk_dirs = list_existing_chunk_dirs(
            chunk_root,
            combine_start=combine_start,
            combine_end=combine_end,
        )
        if not chunk_dirs:
            raise ValueError(
                f"No existing chunks available in {chunk_root} for requested combine range."
            )
        combine_source = "all_existing_chunks"
    else:
        chunk_dirs = [chunk_root / chunk.key for chunk in chunk_ranges]
        combine_source = "requested_chunks"

    ga4_combined = combine_ga4_monthly(chunk_dirs)
    gsc_combined = combine_gsc_monthly(chunk_dirs)
    gsc_property_totals = combine_gsc_property_totals_daily(chunk_dirs)

    ga4_combined_out = combined_output_dir / "ga4_organic_page_monthly_compare.csv"
    gsc_combined_out = combined_output_dir / "gsc_organic_page_monthly.csv"
    gsc_property_out = combined_output_dir / "gsc_property_totals_daily.csv"
    ga4_combined.to_csv(ga4_combined_out, index=False)
    gsc_combined.to_csv(gsc_combined_out, index=False)
    gsc_property_totals.to_csv(gsc_property_out, index=False)

    page_clicks_total = float(gsc_combined["organic_clicks_gsc"].sum()) if not gsc_combined.empty else 0.0
    page_impressions_total = (
        float(gsc_combined["organic_impressions_gsc"].sum()) if not gsc_combined.empty else 0.0
    )
    property_clicks_total = (
        float(gsc_property_totals["property_clicks_gsc"].sum())
        if not gsc_property_totals.empty
        else 0.0
    )
    property_impressions_total = (
        float(gsc_property_totals["property_impressions_gsc"].sum())
        if not gsc_property_totals.empty
        else 0.0
    )
    coverage_clicks = (
        round((page_clicks_total / property_clicks_total) * 100.0, 4)
        if property_clicks_total
        else None
    )
    coverage_impressions = (
        round((page_impressions_total / property_impressions_total) * 100.0, 4)
        if property_impressions_total
        else None
    )
    gsc_summary = {
        "site_url": args.gsc_site_url,
        "country_code_filter": args.gsc_country_code,
        "date_range": {
            "start_date": (
                combine_start.isoformat()
                if combine_start
                else start_date.isoformat()
            ),
            "end_date": (
                combine_end.isoformat()
                if combine_end
                else end_date.isoformat()
            ),
        },
        "rows": {
            "monthly_rows": int(len(gsc_combined)),
            "daily_property_rows": int(len(gsc_property_totals)),
            "unique_page_paths_monthly": int(gsc_combined["page_path"].nunique())
            if not gsc_combined.empty
            else 0,
        },
        "totals": {"clicks": page_clicks_total, "impressions": page_impressions_total},
        "property_totals": {
            "clicks": property_clicks_total,
            "impressions": property_impressions_total,
        },
        "coverage": {
            "clicks_pct_page_rows_vs_property": coverage_clicks,
            "impressions_pct_page_rows_vs_property": coverage_impressions,
            "daily_clicks_coverage_min_pct": (
                round(float(gsc_property_totals["clicks_coverage_pct"].dropna().min()), 4)
                if not gsc_property_totals.empty
                and gsc_property_totals["clicks_coverage_pct"].notna().any()
                else None
            ),
            "daily_clicks_coverage_median_pct": (
                round(float(gsc_property_totals["clicks_coverage_pct"].dropna().median()), 4)
                if not gsc_property_totals.empty
                and gsc_property_totals["clicks_coverage_pct"].notna().any()
                else None
            ),
        },
        "outputs": {
            "monthly_csv": str(gsc_combined_out),
            "property_totals_daily_csv": str(gsc_property_out),
        },
    }
    gsc_summary_out = combined_output_dir / "gsc_summary.json"
    gsc_summary_out.write_text(json.dumps(gsc_summary, indent=2), encoding="utf-8")

    default_model_start_date = combine_start or start_date
    default_model_end_date = combine_end or end_date
    model_start_month = args.model_start_month or (
        f"{default_model_start_date.year:04d}-{default_model_start_date.month:02d}"
    )
    model_end_month = args.model_end_month or (
        f"{default_model_end_date.year:04d}-{default_model_end_date.month:02d}"
    )

    model_command = [
        str(python_exe),
        "scripts/run_revenue_decay_model_input.py",
        "--ga4-monthly-csv",
        str(ga4_combined_out),
        "--gsc-monthly-csv",
        str(gsc_combined_out),
        "--gsc-summary-json",
        str(gsc_summary_out),
        "--start-month",
        model_start_month,
        "--end-month",
        model_end_month,
        "--output-dir",
        str(model_output_dir),
    ]
    if args.page_type_csv:
        model_command.extend(["--page-type-csv", args.page_type_csv])
    run_command(model_command, cwd=ROOT_DIR)

    summary = {
        "run_date_utc": datetime.utcnow().isoformat() + "Z",
        "settings": {
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "months_per_chunk": args.months_per_chunk,
            "ga4_country": args.ga4_country,
            "gsc_country_code": args.gsc_country_code,
            "gsc_site_url": args.gsc_site_url,
            "resume": args.resume,
            "combine_all_existing_chunks": args.combine_all_existing_chunks,
            "combine_start_date": combine_start.isoformat() if combine_start else None,
            "combine_end_date": combine_end.isoformat() if combine_end else None,
            "combine_source": combine_source,
            "model_start_month": model_start_month,
            "model_end_month": model_end_month,
        },
        "chunks": chunk_status,
        "outputs": {
            "chunk_root": str(chunk_root),
            "combined_output_dir": str(combined_output_dir),
            "ga4_monthly_csv": str(ga4_combined_out),
            "gsc_monthly_csv": str(gsc_combined_out),
            "gsc_property_totals_daily_csv": str(gsc_property_out),
            "gsc_summary_json": str(gsc_summary_out),
            "model_output_dir": str(model_output_dir),
        },
    }
    summary_out = combined_output_dir / "chunked_pull_summary.json"
    summary_out.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print(f"Wrote: {ga4_combined_out}")
    print(f"Wrote: {gsc_combined_out}")
    print(f"Wrote: {gsc_property_out}")
    print(f"Wrote: {gsc_summary_out}")
    print(f"Wrote: {summary_out}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run chunked GA4+GSC pulls, persist each chunk, then merge into combined "
            "monthly files and model input."
        )
    )
    parser.add_argument(
        "--start-date",
        default="2024-10-01",
        help="Inclusive start date in YYYY-MM-DD.",
    )
    parser.add_argument(
        "--end-date",
        default=default_end_date().isoformat(),
        help="Inclusive end date in YYYY-MM-DD. Defaults to last day of previous month.",
    )
    parser.add_argument(
        "--months-per-chunk",
        type=int,
        default=3,
        help="How many months per chunk pull.",
    )
    parser.add_argument(
        "--python-exe",
        default=str(ROOT_DIR / "venv" / "Scripts" / "python.exe"),
        help="Python executable used to run pipeline scripts.",
    )
    parser.add_argument(
        "--chunk-root",
        default=str(ROOT_DIR / "data" / "interim" / "revenue_decay_radar_chunks"),
        help="Directory to store per-chunk GA4/GSC outputs.",
    )
    parser.add_argument(
        "--combined-output-dir",
        default=str(ROOT_DIR / "data" / "interim" / "revenue_decay_radar_combined"),
        help="Directory for combined GA4/GSC merged pull outputs.",
    )
    parser.add_argument(
        "--model-output-dir",
        default=str(ROOT_DIR / "data" / "interim" / "revenue_decay_radar_model_input"),
        help="Directory for model input outputs.",
    )
    parser.add_argument(
        "--page-type-csv",
        default="",
        help="Optional page type mapping CSV for model input build.",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Skip chunk pulls when expected chunk files already exist.",
    )
    parser.add_argument(
        "--combine-all-existing-chunks",
        action="store_true",
        help=(
            "Combine model inputs from all existing chunk folders in --chunk-root "
            "(optionally bounded by --combine-start-date/--combine-end-date) instead "
            "of only the chunks requested in this run."
        ),
    )
    parser.add_argument(
        "--combine-start-date",
        default="",
        help=(
            "Optional inclusive lower bound for combining existing chunks (YYYY-MM-DD). "
            "Used only with --combine-all-existing-chunks."
        ),
    )
    parser.add_argument(
        "--combine-end-date",
        default="",
        help=(
            "Optional inclusive upper bound for combining existing chunks (YYYY-MM-DD). "
            "Defaults to --end-date."
        ),
    )
    parser.add_argument(
        "--model-start-month",
        default="",
        help=(
            "Optional model input start month (YYYY-MM). If omitted, derived from run "
            "start/combine start."
        ),
    )
    parser.add_argument(
        "--model-end-month",
        default="",
        help=(
            "Optional model input end month (YYYY-MM). If omitted, derived from run "
            "end/combine end."
        ),
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
        help="GA4 service account key file path.",
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
        help="GSC property URL (URL-prefix or sc-domain).",
    )
    parser.add_argument(
        "--gsc-country-code",
        default="all",
        help="GSC country code filter. Use 'all' for no country filter.",
    )
    parser.add_argument(
        "--gsc-service-account-file",
        default=str(ROOT_DIR / "secrets" / "credentials" / "gsc_service_account.json"),
        help="GSC service account key file path.",
    )
    return parser


if __name__ == "__main__":
    parser = build_parser()
    try:
        run(parser.parse_args())
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1)
