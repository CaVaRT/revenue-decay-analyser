from __future__ import annotations

import argparse
import json
from datetime import date, datetime
from pathlib import Path
import re
from urllib.parse import urlparse

import numpy as np
import pandas as pd

from src.common.config import ROOT_DIR


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


def parse_month(value: str) -> pd.Timestamp:
    text = value.strip()
    parsed = datetime.strptime(text, "%Y-%m")
    return pd.Timestamp(parsed.year, parsed.month, 1)


def month_start(ts: pd.Series) -> pd.Series:
    return ts.dt.to_period("M").dt.to_timestamp()


def require_columns(df: pd.DataFrame, required: list[str], *, file_label: str) -> None:
    missing = [column for column in required if column not in df.columns]
    if missing:
        joined = ", ".join(missing)
        raise ValueError(f"{file_label} is missing required columns: {joined}")


def pick_first_column(columns: list[str], candidates: list[str]) -> str | None:
    lowered = {column.lower(): column for column in columns}
    for candidate in candidates:
        if candidate.lower() in lowered:
            return lowered[candidate.lower()]
    return None


def infer_page_type(page_path: str) -> str:
    path = normalize_page_path(page_path).lower()
    if path in {"", "/"}:
        return "home"
    if path in {"/(not set)", "/not-set"}:
        return "not_set"

    segments = [segment for segment in path.strip("/").split("/") if segment]
    if not segments:
        return "home"
    first = segments[0]
    slug = segments[1] if len(segments) >= 2 else ""
    text = " ".join(segments)

    if path.endswith(".php") or first in {
        "cart",
        "basket",
        "checkout",
        "account",
        "account.php",
        "login",
        "register",
        "search",
    }:
        return "transactional"

    if first in {"sleep-hub", "guides", "guide", "blog", "content", "advice", "inspiration", "news", "authors"}:
        return "content"

    if first == "mattresses":
        return "category_mattresses"

    if first == "beds":
        return "category_beds"

    if first == "headboards":
        return "category_headboards"

    if first in {"bedroom-furniture", "furniture"}:
        return "category_furniture"

    if first in {"bedding", "pillows", "duvets", "mattress-toppers"}:
        return "category_bedding"

    if first in {"sale", "clearance"}:
        return "category_sale"

    if first == "kids":
        return "category_kids"

    if first == "brands":
        return "category_brands"

    if first == "products":
        product_text = f"{slug} {text}".lower()
        if any(token in product_text for token in {"mattress", "mattresses", "ortho", "pillowtop"}):
            return "product_mattresses"
        if any(token in product_text for token in {"headboard", "headboards"}):
            return "product_headboards"
        if any(
            token in product_text
            for token in {
                "pillow",
                "duvet",
                "protector",
                "topper",
                "bedding",
            }
        ):
            return "product_bedding"
        if any(
            token in product_text
            for token in {
                "wardrobe",
                "chest",
                "drawer",
                "bedside",
                "furniture",
            }
        ):
            return "product_furniture"
        if any(
            token in product_text
            for token in {
                "bed",
                "divan",
                "frame",
                "ottoman",
                "adjustable",
                "tv-bed",
                "sofa-bed",
            }
        ):
            return "product_beds"
        return "products"

    if first in {"stores", "store", "store-locator"}:
        return "store"
    if first == "store-finder":
        return "store"
    if len(segments) >= 2 and re.match(r"^\d", segments[1]):
        return "store"
    if len(segments) == 2 and first not in {
        "products",
        "mattresses",
        "beds",
        "headboards",
        "bedroom-furniture",
        "furniture",
        "sleep-hub",
        "guides",
        "guide",
        "blog",
        "content",
    } and re.search(r"\d", segments[1]):
        return "store"

    if first in {
        "privacy-policy",
        "terms-and-conditions",
        "cookie-policy",
        "returns-and-refunds",
        "delivery-information",
        "guarantee",
        "finance-terms",
    }:
        return "policy"

    if first in {
        "contact-us",
        "about-us",
        "interest-free-credit",
        "finance",
        "our-stores",
        "customer-service",
        "assembly-guides",
        "5-year-bed-guarantee",
    }:
        return "info"

    return "other"


def load_ga4_monthly(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    require_columns(
        df,
        ["month", "page_path", "organic_sessions", "organic_revenue"],
        file_label=str(path),
    )
    df = df.copy()
    df["month"] = pd.to_datetime(df["month"], errors="coerce")
    df["month"] = month_start(df["month"])
    df["page_path"] = df["page_path"].map(normalize_page_path)
    df["sessions"] = pd.to_numeric(df["organic_sessions"], errors="coerce").fillna(0.0)
    df["revenue"] = pd.to_numeric(df["organic_revenue"], errors="coerce").fillna(0.0)
    result = (
        df.groupby(["month", "page_path"], as_index=False)[["sessions", "revenue"]]
        .sum()
        .sort_values(["month", "page_path"])
    )
    return result


def load_gsc_monthly(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    require_columns(df, ["month", "page_path"], file_label=str(path))
    clicks_column = pick_first_column(
        list(df.columns),
        ["organic_clicks_gsc", "organic_clicks", "clicks"],
    )
    impressions_column = pick_first_column(
        list(df.columns),
        ["organic_impressions_gsc", "organic_impressions", "impressions"],
    )
    if not clicks_column:
        raise ValueError(
            f"{path} must include clicks column (organic_clicks_gsc / organic_clicks / clicks)."
        )

    df = df.copy()
    df["month"] = pd.to_datetime(df["month"], errors="coerce")
    df["month"] = month_start(df["month"])
    df["page_path"] = df["page_path"].map(normalize_page_path)
    df["clicks"] = pd.to_numeric(df[clicks_column], errors="coerce").fillna(0.0)
    if impressions_column:
        df["impressions"] = pd.to_numeric(df[impressions_column], errors="coerce").fillna(0.0)
    else:
        df["impressions"] = 0.0

    result = (
        df.groupby(["month", "page_path"], as_index=False)[["clicks", "impressions"]]
        .sum()
        .sort_values(["month", "page_path"])
    )
    return result


def load_page_type_map(path: Path | None) -> pd.DataFrame:
    if not path:
        return pd.DataFrame(columns=["page_path", "page_type"])
    df = pd.read_csv(path)
    path_column = pick_first_column(list(df.columns), ["page_path", "page", "path", "url"])
    type_column = pick_first_column(list(df.columns), ["page_type", "type", "template", "category"])
    if not path_column or not type_column:
        raise ValueError(
            f"{path} must contain page path and page type columns. "
            "Accepted path cols: page_path/page/path/url; type cols: page_type/type/template/category."
        )
    mapped = df[[path_column, type_column]].copy()
    mapped.columns = ["page_path", "page_type"]
    mapped["page_path"] = mapped["page_path"].map(normalize_page_path)
    mapped["page_type"] = mapped["page_type"].astype(str).str.strip()
    mapped = mapped[mapped["page_path"] != ""]
    mapped = mapped.drop_duplicates(subset=["page_path"], keep="first")
    return mapped


def run(args: argparse.Namespace) -> None:
    ga4_monthly_csv = Path(args.ga4_monthly_csv)
    gsc_monthly_csv = Path(args.gsc_monthly_csv)
    gsc_summary_json = Path(args.gsc_summary_json) if args.gsc_summary_json else None
    page_type_csv = Path(args.page_type_csv) if args.page_type_csv else None

    if not ga4_monthly_csv.exists():
        raise FileNotFoundError(f"GA4 monthly CSV not found: {ga4_monthly_csv}")
    if not gsc_monthly_csv.exists():
        raise FileNotFoundError(f"GSC monthly CSV not found: {gsc_monthly_csv}")
    if gsc_summary_json and not gsc_summary_json.exists():
        raise FileNotFoundError(f"GSC summary JSON not found: {gsc_summary_json}")
    if page_type_csv and not page_type_csv.exists():
        raise FileNotFoundError(f"Page type CSV not found: {page_type_csv}")

    ga4 = load_ga4_monthly(ga4_monthly_csv)
    gsc = load_gsc_monthly(gsc_monthly_csv)
    page_type_map = load_page_type_map(page_type_csv)

    if args.start_month:
        start_month = parse_month(args.start_month)
        ga4 = ga4[ga4["month"] >= start_month].copy()
        gsc = gsc[gsc["month"] >= start_month].copy()
    if args.end_month:
        end_month = parse_month(args.end_month)
        ga4 = ga4[ga4["month"] <= end_month].copy()
        gsc = gsc[gsc["month"] <= end_month].copy()

    merged = ga4.merge(gsc, on=["month", "page_path"], how="outer", indicator=True)
    for column in ("sessions", "revenue", "clicks", "impressions"):
        merged[column] = pd.to_numeric(merged[column], errors="coerce").fillna(0.0)

    merged["has_ga4_data"] = merged["_merge"].isin(["left_only", "both"])
    merged["has_gsc_data"] = merged["_merge"].isin(["right_only", "both"])
    merged["page"] = merged["page_path"]
    merged["lumar_signals"] = pd.NA
    merged["page_type_inferred"] = merged["page_path"].map(infer_page_type)

    if not page_type_map.empty:
        merged = merged.merge(page_type_map, on="page_path", how="left")
    if "page_type" not in merged.columns:
        merged["page_type"] = pd.NA
    merged["page_type"] = (
        merged["page_type"]
        .astype("string")
        .replace("", pd.NA)
    )
    merged["page_type"] = merged["page_type"].fillna(merged["page_type_inferred"]).fillna("unknown")
    merged["page_type_source"] = np.where(
        merged["page_type"].eq(merged["page_type_inferred"]),
        "inferred",
        "mapped",
    )

    output = merged[
        [
            "page",
            "month",
            "revenue",
            "clicks",
            "sessions",
            "impressions",
            "lumar_signals",
            "page_type",
            "page_type_source",
            "has_ga4_data",
            "has_gsc_data",
        ]
    ].copy()
    output = output.sort_values(["month", "page"]).reset_index(drop=True)

    ga4_pages = set(ga4["page_path"].dropna().astype(str).unique())
    gsc_pages = set(gsc["page_path"].dropna().astype(str).unique())
    shared_pages = ga4_pages.intersection(gsc_pages)

    gsc_summary_data: dict[str, object] | None = None
    if gsc_summary_json:
        gsc_summary_data = json.loads(gsc_summary_json.read_text(encoding="utf-8"))

    summary = {
        "run_date_utc": datetime.utcnow().isoformat() + "Z",
        "inputs": {
            "ga4_monthly_csv": str(ga4_monthly_csv),
            "gsc_monthly_csv": str(gsc_monthly_csv),
            "gsc_summary_json": str(gsc_summary_json) if gsc_summary_json else None,
            "page_type_csv": str(page_type_csv) if page_type_csv else None,
        },
        "analysis_window": {
            "min_month": output["month"].min().date().isoformat() if not output.empty else None,
            "max_month": output["month"].max().date().isoformat() if not output.empty else None,
            "month_count": int(output["month"].nunique()) if not output.empty else 0,
        },
        "counts": {
            "rows_model_input": int(len(output)),
            "unique_pages_model_input": int(output["page"].nunique()),
            "rows_with_ga4_data": int(output["has_ga4_data"].sum()),
            "rows_with_gsc_data": int(output["has_gsc_data"].sum()),
            "rows_with_both_data": int((output["has_ga4_data"] & output["has_gsc_data"]).sum()),
            "rows_with_clicks_gt_zero": int((output["clicks"] > 0).sum()),
            "rows_with_revenue_gt_zero": int((output["revenue"] > 0).sum()),
        },
        "coverage": {
            "ga4_unique_pages": int(len(ga4_pages)),
            "gsc_unique_pages": int(len(gsc_pages)),
            "shared_unique_pages": int(len(shared_pages)),
            "ga4_page_coverage_by_gsc_pct": (
                round((len(shared_pages) / len(ga4_pages)) * 100.0, 4) if ga4_pages else None
            ),
            "gsc_page_coverage_by_ga4_pct": (
                round((len(shared_pages) / len(gsc_pages)) * 100.0, 4) if gsc_pages else None
            ),
        },
        "totals": {
            "sessions": float(output["sessions"].sum()),
            "revenue": float(output["revenue"].sum()),
            "clicks": float(output["clicks"].sum()),
            "impressions": float(output["impressions"].sum()),
        },
        "page_type_distribution_top10": (
            output["page_type"].value_counts(dropna=False).head(10).to_dict()
            if not output.empty
            else {}
        ),
        "page_type_source_distribution": (
            output["page_type_source"].value_counts(dropna=False).to_dict()
            if not output.empty
            else {}
        ),
        "gsc_reconciliation": (
            {
                "property_totals_clicks": gsc_summary_data.get("property_totals", {}).get("clicks"),
                "property_totals_impressions": gsc_summary_data.get("property_totals", {}).get("impressions"),
                "page_rows_clicks_pct_of_property": gsc_summary_data.get("coverage", {}).get(
                    "clicks_pct_page_rows_vs_property"
                ),
                "page_rows_impressions_pct_of_property": gsc_summary_data.get("coverage", {}).get(
                    "impressions_pct_page_rows_vs_property"
                ),
            }
            if gsc_summary_data
            else None
        ),
    }

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    out_csv = output_dir / "model_input_monthly.csv"
    out_summary = output_dir / "model_input_quality_summary.json"
    output.to_csv(out_csv, index=False)
    out_summary.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print(f"Wrote: {out_csv}")
    print(f"Wrote: {out_summary}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build model-ready monthly table by merging GA4 monthly and GSC monthly page data."
    )
    parser.add_argument(
        "--ga4-monthly-csv",
        default=str(ROOT_DIR / "data" / "interim" / "revenue_decay_radar" / "seo_organic_page_monthly.csv"),
        help="GA4 monthly CSV (must include month,page_path,organic_sessions,organic_revenue).",
    )
    parser.add_argument(
        "--gsc-monthly-csv",
        default=str(ROOT_DIR / "data" / "interim" / "revenue_decay_radar_gsc" / "gsc_organic_page_monthly.csv"),
        help="GSC monthly CSV (must include month,page_path and clicks column).",
    )
    parser.add_argument(
        "--gsc-summary-json",
        default="",
        help="Optional GSC extractor summary JSON for reconciliation context.",
    )
    parser.add_argument(
        "--page-type-csv",
        default="",
        help="Optional page type mapping CSV. Example columns: page_path,page_type.",
    )
    parser.add_argument(
        "--start-month",
        default="",
        help="Optional inclusive start month in YYYY-MM format.",
    )
    parser.add_argument(
        "--end-month",
        default="",
        help="Optional inclusive end month in YYYY-MM format.",
    )
    parser.add_argument(
        "--output-dir",
        default=str(ROOT_DIR / "data" / "interim" / "revenue_decay_radar_model_input"),
        help="Output directory for model input CSV and quality summary.",
    )
    return parser


if __name__ == "__main__":
    parser = build_parser()
    run(parser.parse_args())
