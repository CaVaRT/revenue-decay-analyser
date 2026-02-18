from __future__ import annotations

import argparse
import json
import os
import pickle
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse

import pandas as pd
from google.api_core.exceptions import PermissionDenied
from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.analytics.data_v1beta import BetaAnalyticsDataClient
from google.analytics.data_v1beta.types import (
    DateRange,
    Dimension,
    Filter,
    FilterExpression,
    FilterExpressionList,
    Metric,
    RunReportRequest,
)
from google.oauth2.credentials import Credentials as UserCredentials
from google.oauth2 import service_account
from google_auth_oauthlib.flow import InstalledAppFlow

from src.common.config import ROOT_DIR, load_env_file


DEFAULT_SCOPES = ("https://www.googleapis.com/auth/analytics.readonly",)


@dataclass(frozen=True)
class Ga4RequestConfig:
    property_id: str
    start_date: str
    end_date: str
    page_dimension: str
    ga4_country: str | None = None
    limit: int = 100_000


def normalize_property_id(raw: str) -> str:
    value = raw.strip()
    if value.startswith("properties/"):
        return value.split("/", 1)[1]
    return value


def parse_date_or_relative(value: str) -> str:
    value = value.strip()
    if value.endswith("daysAgo") or value == "today" or value == "yesterday":
        return value
    datetime.strptime(value, "%Y-%m-%d")
    return value


def resolve_default_dates() -> tuple[str, str]:
    today = date.today()
    end = today - timedelta(days=1)
    start = end - timedelta(days=365)
    return start.isoformat(), end.isoformat()


def normalize_page_path(raw: str) -> str:
    text = str(raw or "").strip()
    if not text:
        return ""
    if "://" in text:
        parsed = urlparse(text)
        path = parsed.path or "/"
    else:
        # GA4 landing page dimensions usually return a path; keep robust for full URL-like values.
        parsed = urlparse(f"https://dummy{text if text.startswith('/') else '/' + text}")
        path = parsed.path or "/"
    normalized = path.rstrip("/")
    return normalized or "/"


def require_columns(df: pd.DataFrame, required: list[str], *, file_label: str) -> None:
    missing = [column for column in required if column not in df.columns]
    if missing:
        joined = ", ".join(missing)
        raise ValueError(f"{file_label} is missing required columns: {joined}")


def build_service_account_client(service_account_file: Path) -> BetaAnalyticsDataClient:
    credentials = service_account.Credentials.from_service_account_file(
        str(service_account_file),
        scopes=list(DEFAULT_SCOPES),
    )
    return BetaAnalyticsDataClient(credentials=credentials)


def load_oauth_credentials(
    *,
    oauth_client_secrets_file: Path,
    oauth_token_file: Path,
    allow_oauth_login: bool,
) -> UserCredentials:
    credentials: UserCredentials | None = None
    if oauth_token_file.exists():
        with oauth_token_file.open("rb") as token:
            loaded = pickle.load(token)
        if isinstance(loaded, UserCredentials):
            credentials = loaded

    if credentials and credentials.valid:
        return credentials

    if credentials and credentials.expired and credentials.refresh_token:
        try:
            credentials.refresh(Request())
        except RefreshError as exc:
            if allow_oauth_login:
                credentials = None
            else:
                raise ValueError(
                    "OAuth token refresh failed (invalid_grant). "
                    "Rerun with --allow-oauth-login to re-authenticate and refresh token."
                ) from exc
    if credentials and credentials.valid:
        oauth_token_file.parent.mkdir(parents=True, exist_ok=True)
        with oauth_token_file.open("wb") as token:
            pickle.dump(credentials, token)
        return credentials

    if not allow_oauth_login:
        raise ValueError(
            "OAuth token is missing/invalid. Provide a valid --oauth-token-file or rerun "
            "with --allow-oauth-login to complete browser auth."
        )

    if not oauth_client_secrets_file.exists():
        raise FileNotFoundError(
            f"OAuth client secrets file not found: {oauth_client_secrets_file}"
        )
    flow = InstalledAppFlow.from_client_secrets_file(
        str(oauth_client_secrets_file),
        scopes=list(DEFAULT_SCOPES),
    )
    credentials = flow.run_local_server(port=0)
    oauth_token_file.parent.mkdir(parents=True, exist_ok=True)
    with oauth_token_file.open("wb") as token:
        pickle.dump(credentials, token)
    return credentials


def build_oauth_client(
    *,
    oauth_client_secrets_file: Path,
    oauth_token_file: Path,
    allow_oauth_login: bool,
) -> BetaAnalyticsDataClient:
    credentials = load_oauth_credentials(
        oauth_client_secrets_file=oauth_client_secrets_file,
        oauth_token_file=oauth_token_file,
        allow_oauth_login=allow_oauth_login,
    )
    return BetaAnalyticsDataClient(credentials=credentials)


def combine_and_filters(expressions: list[FilterExpression]) -> FilterExpression | None:
    if not expressions:
        return None
    if len(expressions) == 1:
        return expressions[0]
    return FilterExpression(and_group=FilterExpressionList(expressions=expressions))


def run_report_paged(
    client: BetaAnalyticsDataClient,
    *,
    property_id: str,
    start_date: str,
    end_date: str,
    dimensions: list[str],
    metrics: list[str],
    filter_expressions: list[FilterExpression] | None = None,
    limit: int = 100_000,
) -> pd.DataFrame:
    rows: list[dict[str, str]] = []
    offset = 0
    combined_filter = combine_and_filters(filter_expressions or [])
    while True:
        request = RunReportRequest(
            property=f"properties/{property_id}",
            date_ranges=[DateRange(start_date=start_date, end_date=end_date)],
            dimensions=[Dimension(name=name) for name in dimensions],
            metrics=[Metric(name=name) for name in metrics],
            dimension_filter=combined_filter,
            limit=limit,
            offset=offset,
            keep_empty_rows=False,
        )
        response = client.run_report(request)
        if not response.rows:
            break

        for row in response.rows:
            record: dict[str, str] = {}
            for i, dimension_name in enumerate(dimensions):
                record[dimension_name] = row.dimension_values[i].value
            for i, metric_name in enumerate(metrics):
                record[metric_name] = row.metric_values[i].value
            rows.append(record)

        if len(response.rows) < limit:
            break
        offset += limit

    return pd.DataFrame(rows)


def organic_search_filter() -> FilterExpression:
    return FilterExpression(
        filter=Filter(
            field_name="sessionDefaultChannelGroup",
            string_filter=Filter.StringFilter(
                match_type=Filter.StringFilter.MatchType.EXACT,
                value="Organic Search",
            ),
        )
    )


def ga4_country_filter(country: str) -> FilterExpression:
    return FilterExpression(
        filter=Filter(
            field_name="country",
            string_filter=Filter.StringFilter(
                match_type=Filter.StringFilter.MatchType.EXACT,
                value=country,
            ),
        )
    )


def fetch_ga4_organic_sessions_revenue(
    client: BetaAnalyticsDataClient,
    config: Ga4RequestConfig,
) -> pd.DataFrame:
    filters = [organic_search_filter()]
    if config.ga4_country:
        filters.append(ga4_country_filter(config.ga4_country))

    df = run_report_paged(
        client,
        property_id=config.property_id,
        start_date=config.start_date,
        end_date=config.end_date,
        dimensions=["date", config.page_dimension],
        metrics=["sessions", "totalRevenue"],
        filter_expressions=filters,
        limit=config.limit,
    )
    if df.empty:
        return pd.DataFrame(
            columns=[
                "date",
                "landing_page_raw",
                "page_path",
                "organic_sessions",
                "organic_revenue",
            ]
        )

    df = df.rename(
        columns={
            config.page_dimension: "landing_page_raw",
            "sessions": "organic_sessions",
            "totalRevenue": "organic_revenue",
        }
    )
    df["date"] = pd.to_datetime(df["date"], format="%Y%m%d", errors="coerce")
    df["organic_sessions"] = pd.to_numeric(df["organic_sessions"], errors="coerce").fillna(0.0)
    df["organic_revenue"] = pd.to_numeric(df["organic_revenue"], errors="coerce").fillna(0.0)
    df["page_path"] = df["landing_page_raw"].map(normalize_page_path)
    df = (
        df.groupby(["date", "page_path"], as_index=False)[["organic_sessions", "organic_revenue"]]
        .sum()
        .sort_values(["date", "page_path"])
    )
    return df


def allowed_country_values(country_filter: str) -> set[str]:
    normalized = country_filter.strip().lower()
    base = {normalized}
    if normalized in {"united kingdom", "uk", "great britain", "gb", "gbr"}:
        base.update({"united kingdom", "uk", "great britain", "gb", "gbr"})
    return base


def resolve_gsc_country_column(columns: list[str]) -> str | None:
    candidates = []
    for column in columns:
        lowered = column.strip().lower()
        if lowered in {"country", "country_code", "countrycode"}:
            candidates.append(column)
    return candidates[0] if candidates else None


def load_gsc_clicks(gsc_csv: Path, *, country_filter: str | None) -> tuple[pd.DataFrame, str | None]:
    header = pd.read_csv(gsc_csv, nrows=0)
    header_columns = list(header.columns)
    country_column = resolve_gsc_country_column(header_columns)
    usecols = ["page", "date", "clicks"]
    if country_filter:
        if not country_column:
            raise ValueError(
                f"{gsc_csv} has no country column, but country filtering is required for GSC clicks. "
                "Provide a GSC export with country dimension (e.g., country/countryCode), "
                "or disable the GSC country filter with --gsc-country ''."
            )
        usecols.append(country_column)

    gsc = pd.read_csv(gsc_csv, usecols=usecols)
    require_columns(gsc, ["page", "date", "clicks"], file_label=str(gsc_csv))
    if country_filter and country_column:
        allowed = allowed_country_values(country_filter)
        normalized_country = gsc[country_column].astype(str).str.strip().str.lower()
        gsc = gsc[normalized_country.isin(allowed)].copy()
    gsc["date"] = pd.to_datetime(gsc["date"], errors="coerce")
    gsc["organic_clicks_gsc"] = pd.to_numeric(gsc["clicks"], errors="coerce").fillna(0.0)
    gsc["page_path"] = gsc["page"].map(normalize_page_path)
    gsc = (
        gsc.groupby(["date", "page_path"], as_index=False)[["organic_clicks_gsc"]]
        .sum()
        .sort_values(["date", "page_path"])
    )
    return gsc, country_column


def month_start(ts: pd.Series) -> pd.Series:
    return ts.dt.to_period("M").dt.to_timestamp()


def run(args: argparse.Namespace) -> None:
    load_env_file()

    auth_mode = (args.auth_mode or "service_account").strip().lower()
    if auth_mode not in {"service_account", "oauth"}:
        raise ValueError("--auth-mode must be one of: service_account, oauth")

    property_id = normalize_property_id(
        args.property_id or os.getenv("GA4_PROPERTY_ID", "").strip()
    )
    if not property_id:
        raise ValueError("GA4 property ID is required (--property-id or GA4_PROPERTY_ID).")

    service_account_file = Path(
        args.service_account_file
        or os.getenv("GA4_SERVICE_ACCOUNT_FILE", "")
        or str(ROOT_DIR / "secrets" / "credentials" / "ga4_service_account.json")
    )
    oauth_client_secrets_file = Path(
        args.oauth_client_secrets_file
        or os.getenv("GA4_OAUTH_CLIENT_SECRETS_FILE", "")
        or str(ROOT_DIR / "secrets" / "ga4_oauth" / "credentials.json")
    )
    oauth_token_file = Path(
        args.oauth_token_file
        or os.getenv("GA4_OAUTH_TOKEN_FILE", "")
        or str(ROOT_DIR / "secrets" / "ga4_oauth" / "token.pickle")
    )

    if auth_mode == "service_account" and not service_account_file.exists():
        raise FileNotFoundError(f"Service account file not found: {service_account_file}")
    if auth_mode == "oauth" and not oauth_client_secrets_file.exists():
        raise FileNotFoundError(
            f"OAuth client secrets file not found: {oauth_client_secrets_file}"
        )

    if args.start_date and args.end_date:
        start_date = parse_date_or_relative(args.start_date)
        end_date = parse_date_or_relative(args.end_date)
    else:
        start_date, end_date = resolve_default_dates()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    gsc_country = (args.gsc_country or "").strip() or None
    ga4_country = (args.ga4_country or "").strip() or None

    config = Ga4RequestConfig(
        property_id=property_id,
        start_date=start_date,
        end_date=end_date,
        page_dimension=args.page_dimension,
        ga4_country=ga4_country,
        limit=args.api_page_size,
    )

    if auth_mode == "service_account":
        client = build_service_account_client(service_account_file)
    else:
        client = build_oauth_client(
            oauth_client_secrets_file=oauth_client_secrets_file,
            oauth_token_file=oauth_token_file,
            allow_oauth_login=args.allow_oauth_login,
        )

    try:
        ga4_daily = fetch_ga4_organic_sessions_revenue(client, config)
    except PermissionDenied as exc:
        message = str(exc)
        if "SERVICE_DISABLED" in message or "disabled" in message.lower():
            raise ValueError(
                "GA4 Data API is disabled for the current Google Cloud project. "
                "Enable analyticsdata.googleapis.com in Google Cloud Console, then retry."
            ) from exc
        raise ValueError(
            "Current credentials do not have GA4 property access or API permission. "
            "Grant Viewer access on the target property and retry."
        ) from exc

    if ga4_daily.empty:
        raise ValueError(
            "GA4 returned no Organic Search sessions/revenue rows for the selected date range."
        )

    merged = ga4_daily.copy()

    gsc_source = None
    gsc_country_column = None
    gsc_daily: pd.DataFrame | None = None
    clicks_source = args.clicks_source
    if clicks_source in {"prefer_gsc", "gsc_only"} and args.gsc_clicks_csv:
        gsc_csv = Path(args.gsc_clicks_csv)
        if gsc_csv.exists():
            gsc_daily, gsc_country_column = load_gsc_clicks(gsc_csv, country_filter=gsc_country)
            merged = merged.merge(gsc_daily, on=["date", "page_path"], how="left")
            gsc_source = str(gsc_csv)
        elif args.require_gsc_clicks:
            raise FileNotFoundError(f"GSC clicks CSV not found: {gsc_csv}")
        elif clicks_source == "gsc_only":
            raise FileNotFoundError(f"GSC clicks CSV not found for gsc_only mode: {gsc_csv}")
        else:
            merged["organic_clicks_gsc"] = pd.NA
    else:
        merged["organic_clicks_gsc"] = pd.NA

    if "organic_clicks_gsc" not in merged.columns:
        merged["organic_clicks_gsc"] = pd.NA

    merged["organic_clicks"] = merged["organic_clicks_gsc"]
    merged["organic_clicks_source"] = merged["organic_clicks_gsc"].notna().map(
        {True: "GSC", False: "missing"}
    )

    merged = merged.sort_values(["date", "page_path"]).reset_index(drop=True)
    merged["month"] = month_start(merged["date"])

    path_match = {
        "ga4_unique_page_paths": int(ga4_daily["page_path"].nunique()),
        "gsc_unique_page_paths": int(gsc_daily["page_path"].nunique()) if gsc_daily is not None else None,
        "shared_unique_page_paths": None,
        "ga4_path_coverage_by_gsc_pct": None,
    }
    if gsc_daily is not None:
        ga4_paths = set(ga4_daily["page_path"].dropna().astype(str).unique())
        gsc_paths = set(gsc_daily["page_path"].dropna().astype(str).unique())
        shared = ga4_paths.intersection(gsc_paths)
        path_match["shared_unique_page_paths"] = int(len(shared))
        path_match["ga4_path_coverage_by_gsc_pct"] = (
            round((len(shared) / len(ga4_paths)) * 100.0, 2) if ga4_paths else None
        )

    monthly = (
        merged.groupby(["month", "page_path"], as_index=False)[
            ["organic_sessions", "organic_revenue", "organic_clicks"]
        ]
        .sum(min_count=1)
        .sort_values(["month", "page_path"])
    )

    daily_out = output_dir / "seo_organic_page_daily.csv"
    monthly_out = output_dir / "seo_organic_page_monthly.csv"
    merged.to_csv(daily_out, index=False)
    monthly.to_csv(monthly_out, index=False)

    summary = {
        "property_id": property_id,
        "auth_mode": auth_mode,
        "service_account_file": str(service_account_file) if auth_mode == "service_account" else None,
        "oauth_client_secrets_file": str(oauth_client_secrets_file) if auth_mode == "oauth" else None,
        "oauth_token_file": str(oauth_token_file) if auth_mode == "oauth" else None,
        "date_range": {"start_date": start_date, "end_date": end_date},
        "ga4_page_dimension": args.page_dimension,
        "ga4_country_filter": ga4_country,
        "rows": {
            "daily_rows": int(len(merged)),
            "monthly_rows": int(len(monthly)),
        },
        "clicks": {
            "clicks_source_mode": clicks_source,
            "gsc_clicks_source": gsc_source,
            "gsc_country_filter": gsc_country,
            "gsc_country_column": gsc_country_column,
            "rows_with_clicks": int(merged["organic_clicks"].notna().sum()),
        },
        "path_match": path_match,
        "outputs": {"daily_csv": str(daily_out), "monthly_csv": str(monthly_out)},
    }
    summary_out = output_dir / "summary.json"
    summary_out.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print(f"Wrote: {daily_out}")
    print(f"Wrote: {monthly_out}")
    print(f"Wrote: {summary_out}")


def build_parser() -> argparse.ArgumentParser:
    default_start, default_end = resolve_default_dates()
    parser = argparse.ArgumentParser(
        description=(
            "Extract SEO-only organic sessions/revenue from GA4 API and combine with GSC organic clicks."
        )
    )
    parser.add_argument(
        "--auth-mode",
        choices=["service_account", "oauth"],
        default="service_account",
        help="Authentication mode for GA4 API.",
    )
    parser.add_argument(
        "--property-id",
        default="",
        help="GA4 property ID (numeric ID or properties/<ID>).",
    )
    parser.add_argument(
        "--service-account-file",
        default="",
        help="Path to GA4 service account JSON key.",
    )
    parser.add_argument(
        "--oauth-client-secrets-file",
        default="",
        help="Path to OAuth client secrets JSON (installed app credentials).",
    )
    parser.add_argument(
        "--oauth-token-file",
        default="",
        help="Path to OAuth token pickle file.",
    )
    parser.add_argument(
        "--allow-oauth-login",
        action="store_true",
        help="Allow interactive browser OAuth login if token is missing/invalid.",
    )
    parser.add_argument(
        "--start-date",
        default=default_start,
        help="Start date (YYYY-MM-DD) or GA4 relative value (e.g., 365daysAgo).",
    )
    parser.add_argument(
        "--end-date",
        default=default_end,
        help="End date (YYYY-MM-DD) or GA4 relative value (e.g., yesterday).",
    )
    parser.add_argument(
        "--page-dimension",
        default="landingPagePlusQueryString",
        help="GA4 landing page dimension. Usually landingPagePlusQueryString.",
    )
    parser.add_argument(
        "--ga4-country",
        default="",
        help="Optional GA4 country filter (dimension: country). Example: 'United Kingdom'.",
    )
    parser.add_argument(
        "--output-dir",
        default=str(ROOT_DIR / "data" / "interim" / "revenue_decay_radar"),
        help="Directory for extracted daily/monthly SEO organic datasets.",
    )
    parser.add_argument(
        "--gsc-clicks-csv",
        default=str(ROOT_DIR / "data" / "interim" / "merged_data" / "raw_merged.csv"),
        help="GSC CSV used for organic clicks merge.",
    )
    parser.add_argument(
        "--clicks-source",
        choices=["prefer_gsc", "gsc_only"],
        default="gsc_only",
        help="Click handling mode. prefer_gsc keeps compatibility and behaves like gsc_only.",
    )
    parser.add_argument(
        "--clicks-country",
        default="",
        help="Deprecated and ignored. GA4 click extraction has been removed.",
    )
    parser.add_argument(
        "--gsc-country",
        default="",
        help="Optional country filter for GSC clicks. Leave empty to keep all countries.",
    )
    parser.add_argument(
        "--require-gsc-clicks",
        action="store_true",
        help="Fail if --gsc-clicks-csv file is missing.",
    )
    parser.add_argument(
        "--api-page-size",
        type=int,
        default=100_000,
        help="GA4 API page size for pagination.",
    )
    return parser


if __name__ == "__main__":
    parser = build_parser()
    run(parser.parse_args())
