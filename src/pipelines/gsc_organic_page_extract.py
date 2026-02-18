from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse

import pandas as pd
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from src.common.config import ROOT_DIR, load_env_file


DEFAULT_SCOPES = ("https://www.googleapis.com/auth/webmasters.readonly",)
DEFAULT_SITE_URL = ""
DEFAULT_COUNTRY_CODE = "all"


@dataclass(frozen=True)
class GscRequestConfig:
    site_url: str
    start_date: str
    end_date: str
    country_code: str | None
    row_limit: int = 25_000


def parse_date(value: str) -> str:
    parsed = datetime.strptime(value.strip(), "%Y-%m-%d")
    return parsed.date().isoformat()


def resolve_default_dates() -> tuple[str, str]:
    today = date.today()
    end = today - timedelta(days=1)
    start = end - timedelta(days=365)
    return start.isoformat(), end.isoformat()


def normalize_site_url(raw: str) -> str:
    value = raw.strip()
    if not value:
        return ""
    if value.startswith("sc-domain:"):
        return value
    if not value.startswith(("http://", "https://")):
        raise ValueError(
            "GSC site URL must be a URL-prefix property (e.g., https://www.example.com/) "
            "or a domain property (e.g., sc-domain:example.com)."
        )
    return value if value.endswith("/") else f"{value}/"


def normalize_country_code(raw: str | None) -> str | None:
    text = (raw or "").strip().lower()
    if not text:
        return None
    if text in {"all", "*", "none"}:
        return None
    synonyms = {
        "united kingdom": "gbr",
        "uk": "gbr",
        "great britain": "gbr",
        "gb": "gbr",
        "gbr": "gbr",
    }
    return synonyms.get(text, text)


def normalize_page_path(raw: str) -> str:
    text = str(raw or "").strip()
    if not text:
        return ""
    if "://" in text:
        parsed = urlparse(text)
        path = parsed.path or "/"
    else:
        parsed = urlparse(f"https://dummy{text if text.startswith('/') else '/' + text}")
        path = parsed.path or "/"
    normalized = path.rstrip("/")
    return normalized or "/"


def month_start(ts: pd.Series) -> pd.Series:
    return ts.dt.to_period("M").dt.to_timestamp()


def build_service(service_account_file: Path):
    credentials = service_account.Credentials.from_service_account_file(
        str(service_account_file),
        scopes=list(DEFAULT_SCOPES),
    )
    return build("searchconsole", "v1", credentials=credentials, cache_discovery=False)


def build_country_filter(country_code: str | None) -> list[dict[str, object]] | None:
    if not country_code:
        return None
    return [
        {
            "groupType": "and",
            "filters": [
                {
                    "dimension": "country",
                    "operator": "equals",
                    "expression": country_code,
                }
            ],
        }
    ]


def run_query_paged(service, config: GscRequestConfig) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    start_row = 0
    country_filters = build_country_filter(config.country_code)
    while True:
        request_body: dict[str, object] = {
            "startDate": config.start_date,
            "endDate": config.end_date,
            "dimensions": ["date", "page"],
            "rowLimit": config.row_limit,
            "startRow": start_row,
            "type": "web",
        }
        if country_filters:
            request_body["dimensionFilterGroups"] = country_filters

        response = (
            service.searchanalytics()
            .query(siteUrl=config.site_url, body=request_body)
            .execute()
        )
        batch = response.get("rows", [])
        if not batch:
            break

        for row in batch:
            keys = row.get("keys", [])
            if len(keys) != 2:
                continue
            rows.append(
                {
                    "date": keys[0],
                    "page_raw": keys[1],
                    "organic_clicks_gsc": float(row.get("clicks", 0.0)),
                    "organic_impressions_gsc": float(row.get("impressions", 0.0)),
                }
            )

        if len(batch) < config.row_limit:
            break
        start_row += config.row_limit

    if not rows:
        return pd.DataFrame(
            columns=[
                "date",
                "page_path",
                "organic_clicks_gsc",
                "organic_impressions_gsc",
            ]
        )

    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df["page_path"] = df["page_raw"].map(normalize_page_path)
    for column in ("organic_clicks_gsc", "organic_impressions_gsc"):
        df[column] = pd.to_numeric(df[column], errors="coerce").fillna(0.0)
    df = (
        df.groupby(["date", "page_path"], as_index=False)[
            ["organic_clicks_gsc", "organic_impressions_gsc"]
        ]
        .sum()
        .sort_values(["date", "page_path"])
    )
    return df


def run_property_totals_daily(service, config: GscRequestConfig) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    start_row = 0
    country_filters = build_country_filter(config.country_code)
    while True:
        request_body: dict[str, object] = {
            "startDate": config.start_date,
            "endDate": config.end_date,
            "dimensions": ["date"],
            "rowLimit": config.row_limit,
            "startRow": start_row,
            "type": "web",
        }
        if country_filters:
            request_body["dimensionFilterGroups"] = country_filters

        response = (
            service.searchanalytics()
            .query(siteUrl=config.site_url, body=request_body)
            .execute()
        )
        batch = response.get("rows", [])
        if not batch:
            break

        for row in batch:
            keys = row.get("keys", [])
            if len(keys) != 1:
                continue
            rows.append(
                {
                    "date": keys[0],
                    "property_clicks_gsc": float(row.get("clicks", 0.0)),
                    "property_impressions_gsc": float(row.get("impressions", 0.0)),
                }
            )

        if len(batch) < config.row_limit:
            break
        start_row += config.row_limit

    if not rows:
        return pd.DataFrame(
            columns=["date", "property_clicks_gsc", "property_impressions_gsc"]
        )

    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    for column in ("property_clicks_gsc", "property_impressions_gsc"):
        df[column] = pd.to_numeric(df[column], errors="coerce").fillna(0.0)
    df = (
        df.groupby(["date"], as_index=False)[
            ["property_clicks_gsc", "property_impressions_gsc"]
        ]
        .sum()
        .sort_values(["date"])
    )
    return df


def run(args: argparse.Namespace) -> None:
    load_env_file()

    site_url = normalize_site_url(args.site_url or os.getenv("GSC_SITE_URL", ""))
    if not site_url:
        raise ValueError(
            "GSC site URL is required (--site-url or GSC_SITE_URL). "
            "Example: https://www.example.com/"
        )

    service_account_file = Path(
        args.service_account_file
        or os.getenv("GSC_SERVICE_ACCOUNT_FILE", "")
        or str(ROOT_DIR / "secrets" / "credentials" / "gsc_service_account.json")
    )
    if not service_account_file.exists():
        raise FileNotFoundError(
            f"GSC service account file not found: {service_account_file}"
        )

    start_date = parse_date(args.start_date)
    end_date = parse_date(args.end_date)
    country_code = normalize_country_code(args.country_code)
    if country_code and len(country_code) != 3:
        raise ValueError(
            "--country-code must be a 3-letter code (e.g., gbr) or a known synonym "
            "(United Kingdom, UK, GB)."
        )

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    config = GscRequestConfig(
        site_url=site_url,
        start_date=start_date,
        end_date=end_date,
        country_code=country_code,
        row_limit=args.api_page_size,
    )

    service = build_service(service_account_file)
    try:
        gsc_daily = run_query_paged(service, config)
        property_totals_daily = run_property_totals_daily(service, config)
    except HttpError as exc:
        raise ValueError(
            "GSC API request failed. Validate site property access for the service account "
            f"and ensure Search Console API is enabled. Original error: {exc}"
        ) from exc

    if gsc_daily.empty:
        raise ValueError("GSC API returned no rows for the selected date range/filter.")
    if property_totals_daily.empty:
        raise ValueError(
            "GSC API returned no property-level daily totals for the selected date range/filter."
        )

    gsc_daily["month"] = month_start(gsc_daily["date"])
    gsc_monthly = (
        gsc_daily.groupby(["month", "page_path"], as_index=False)[
            ["organic_clicks_gsc", "organic_impressions_gsc"]
        ]
        .sum()
        .sort_values(["month", "page_path"])
    )

    page_daily_totals = (
        gsc_daily.groupby(["date"], as_index=False)[
            ["organic_clicks_gsc", "organic_impressions_gsc"]
        ]
        .sum()
        .rename(
            columns={
                "organic_clicks_gsc": "page_clicks_gsc",
                "organic_impressions_gsc": "page_impressions_gsc",
            }
        )
    )
    property_recon_daily = property_totals_daily.merge(
        page_daily_totals,
        on="date",
        how="left",
    )
    for column in ("page_clicks_gsc", "page_impressions_gsc"):
        property_recon_daily[column] = pd.to_numeric(
            property_recon_daily[column], errors="coerce"
        ).fillna(0.0)
    property_recon_daily["clicks_coverage_pct"] = (
        property_recon_daily["page_clicks_gsc"]
        / property_recon_daily["property_clicks_gsc"].replace(0, pd.NA)
        * 100.0
    )
    property_recon_daily["impressions_coverage_pct"] = (
        property_recon_daily["page_impressions_gsc"]
        / property_recon_daily["property_impressions_gsc"].replace(0, pd.NA)
        * 100.0
    )
    for column in ("clicks_coverage_pct", "impressions_coverage_pct"):
        property_recon_daily[column] = (
            pd.to_numeric(property_recon_daily[column], errors="coerce")
            .round(4)
        )

    daily_out = output_dir / "gsc_organic_page_daily.csv"
    monthly_out = output_dir / "gsc_organic_page_monthly.csv"
    property_totals_daily_out = output_dir / "property_totals_daily.csv"
    gsc_daily.to_csv(daily_out, index=False)
    gsc_monthly.to_csv(monthly_out, index=False)
    property_recon_daily.to_csv(property_totals_daily_out, index=False)

    page_clicks_total = float(gsc_daily["organic_clicks_gsc"].sum())
    page_impressions_total = float(gsc_daily["organic_impressions_gsc"].sum())
    property_clicks_total = float(property_totals_daily["property_clicks_gsc"].sum())
    property_impressions_total = float(property_totals_daily["property_impressions_gsc"].sum())
    clicks_coverage_pct = (
        round((page_clicks_total / property_clicks_total) * 100.0, 4)
        if property_clicks_total
        else None
    )
    impressions_coverage_pct = (
        round((page_impressions_total / property_impressions_total) * 100.0, 4)
        if property_impressions_total
        else None
    )

    summary = {
        "site_url": site_url,
        "service_account_file": str(service_account_file),
        "date_range": {"start_date": start_date, "end_date": end_date},
        "country_code_filter": country_code,
        "rows": {
            "daily_rows": int(len(gsc_daily)),
            "monthly_rows": int(len(gsc_monthly)),
            "unique_page_paths_daily": int(gsc_daily["page_path"].nunique()),
            "unique_page_paths_monthly": int(gsc_monthly["page_path"].nunique()),
        },
        "totals": {
            "clicks": page_clicks_total,
            "impressions": page_impressions_total,
        },
        "property_totals": {
            "clicks": property_clicks_total,
            "impressions": property_impressions_total,
        },
        "coverage": {
            "clicks_pct_page_rows_vs_property": clicks_coverage_pct,
            "impressions_pct_page_rows_vs_property": impressions_coverage_pct,
            "daily_clicks_coverage_min_pct": (
                round(
                    float(property_recon_daily["clicks_coverage_pct"].dropna().min()),
                    4,
                )
                if property_recon_daily["clicks_coverage_pct"].notna().any()
                else None
            ),
            "daily_clicks_coverage_median_pct": (
                round(
                    float(property_recon_daily["clicks_coverage_pct"].dropna().median()),
                    4,
                )
                if property_recon_daily["clicks_coverage_pct"].notna().any()
                else None
            ),
        },
        "outputs": {
            "daily_csv": str(daily_out),
            "monthly_csv": str(monthly_out),
            "property_totals_daily_csv": str(property_totals_daily_out),
        },
    }
    summary_out = output_dir / "summary.json"
    summary_out.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print(f"Wrote: {daily_out}")
    print(f"Wrote: {monthly_out}")
    print(f"Wrote: {property_totals_daily_out}")
    print(f"Wrote: {summary_out}")


def build_parser() -> argparse.ArgumentParser:
    default_start, default_end = resolve_default_dates()
    parser = argparse.ArgumentParser(
        description=(
            "Extract GSC page-level daily clicks/impressions and optional country filter."
        )
    )
    parser.add_argument(
        "--site-url",
        default=DEFAULT_SITE_URL,
        help=(
            "GSC site property. URL-prefix example: https://www.example.com/. "
            "Domain property example: sc-domain:example.com."
        ),
    )
    parser.add_argument(
        "--service-account-file",
        default="",
        help="Path to GSC service account JSON key.",
    )
    parser.add_argument(
        "--start-date",
        default=default_start,
        help="Start date in YYYY-MM-DD format.",
    )
    parser.add_argument(
        "--end-date",
        default=default_end,
        help="End date in YYYY-MM-DD format.",
    )
    parser.add_argument(
        "--country-code",
        default=DEFAULT_COUNTRY_CODE,
        help=(
            "Optional GSC country filter (3-letter code). "
            "Use 'all' for no country filter."
        ),
    )
    parser.add_argument(
        "--output-dir",
        default=str(ROOT_DIR / "data" / "interim" / "revenue_decay_radar_gsc"),
        help="Directory for extracted daily/monthly GSC datasets.",
    )
    parser.add_argument(
        "--api-page-size",
        type=int,
        default=25_000,
        help="GSC API page size for pagination (max 25,000).",
    )
    return parser


if __name__ == "__main__":
    parser = build_parser()
    run(parser.parse_args())
