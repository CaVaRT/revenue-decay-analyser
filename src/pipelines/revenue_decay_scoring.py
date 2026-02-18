from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from src.common.config import ROOT_DIR


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


def to_bool_series(series: pd.Series) -> pd.Series:
    if pd.api.types.is_bool_dtype(series):
        return series.fillna(False)
    normalized = series.astype(str).str.strip().str.lower()
    return normalized.isin({"true", "1", "yes", "y", "t"})


def first_non_empty(values: pd.Series, default: str = "unknown") -> str:
    cleaned = (
        values.astype("string")
        .str.strip()
        .replace({"": pd.NA, "<NA>": pd.NA, "nan": pd.NA, "None": pd.NA})
        .dropna()
    )
    if cleaned.empty:
        return default
    return str(cleaned.iloc[0])


def build_month_index(month_series: pd.Series) -> pd.Series:
    min_month = pd.to_datetime(month_series.min())
    return (month_series.dt.year - min_month.year) * 12 + (month_series.dt.month - min_month.month)


def robust_theil_sen_slope(x: np.ndarray, y: np.ndarray) -> float:
    slopes: list[float] = []
    n = len(x)
    for i in range(n - 1):
        for j in range(i + 1, n):
            denom = x[j] - x[i]
            if denom == 0:
                continue
            slopes.append((y[j] - y[i]) / denom)
    if not slopes:
        raise ValueError("No valid slope pairs for Theil-Sen.")
    return float(np.median(slopes))


def compute_slope(x: np.ndarray, y: np.ndarray) -> tuple[float, str]:
    mask = np.isfinite(x) & np.isfinite(y)
    xx = x[mask]
    yy = y[mask]
    if len(xx) < 2:
        return np.nan, "insufficient"
    if np.all(xx == xx[0]):
        return np.nan, "insufficient"
    if len(xx) == 2:
        slope = float((yy[1] - yy[0]) / (xx[1] - xx[0]))
        return slope, "two_point"
    try:
        return robust_theil_sen_slope(xx, yy), "theil_sen"
    except Exception:
        try:
            slope, _ = np.polyfit(xx, yy, 1)
            return float(slope), "polyfit_fallback"
        except Exception:
            return np.nan, "failed"


def compute_seasonality_factors(
    df: pd.DataFrame,
    *,
    metric_col: str,
    output_col: str,
) -> pd.DataFrame:
    by_type_month = (
        df.groupby(["page_type", "month_of_year"], as_index=False)[metric_col]
        .mean()
        .rename(columns={metric_col: "type_month_mean"})
    )
    by_type = (
        df.groupby(["page_type"], as_index=False)[metric_col]
        .mean()
        .rename(columns={metric_col: "type_overall_mean"})
    )
    factors = by_type_month.merge(by_type, on="page_type", how="left")
    factors[output_col] = np.where(
        (factors["type_month_mean"] > 0) & (factors["type_overall_mean"] > 0),
        factors["type_month_mean"] / factors["type_overall_mean"],
        1.0,
    )
    factors[output_col] = pd.to_numeric(factors[output_col], errors="coerce").fillna(1.0)
    factors[output_col] = factors[output_col].clip(lower=0.2, upper=5.0)
    return factors[["page_type", "month_of_year", output_col]]


def rank_to_0_1(series: pd.Series) -> pd.Series:
    values = pd.to_numeric(series, errors="coerce").fillna(0.0)
    if values.nunique() <= 1:
        return pd.Series(0.0, index=values.index)
    return values.rank(method="average", pct=True).clip(lower=0.0, upper=1.0)


def severity_band(score: float) -> str:
    if score >= 80:
        return "Critical"
    if score >= 60:
        return "High"
    if score >= 40:
        return "Medium"
    if score >= 20:
        return "Low"
    return "Monitor"


def run(args: argparse.Namespace) -> None:
    input_csv = Path(args.input_model_csv)
    if not input_csv.exists():
        raise FileNotFoundError(f"Model input CSV not found: {input_csv}")

    data = pd.read_csv(input_csv)
    require_columns(
        data,
        ["page", "month", "revenue", "clicks", "sessions", "page_type"],
        file_label=str(input_csv),
    )

    if "has_ga4_data" not in data.columns:
        data["has_ga4_data"] = True
    if "has_gsc_data" not in data.columns:
        data["has_gsc_data"] = True

    data = data.copy()
    data["month"] = pd.to_datetime(data["month"], errors="coerce")
    data["month"] = month_start(data["month"])
    data["page"] = data["page"].astype(str).str.strip()
    data["page_type"] = data["page_type"].map(lambda v: first_non_empty(pd.Series([v])))
    for column in ("revenue", "clicks", "sessions"):
        data[column] = pd.to_numeric(data[column], errors="coerce").fillna(0.0)
    if "impressions" in data.columns:
        data["impressions"] = pd.to_numeric(data["impressions"], errors="coerce").fillna(0.0)
    else:
        data["impressions"] = 0.0
    data["has_ga4_data"] = to_bool_series(data["has_ga4_data"])
    data["has_gsc_data"] = to_bool_series(data["has_gsc_data"])

    if args.start_month:
        start_month = parse_month(args.start_month)
        data = data[data["month"] >= start_month].copy()
    if args.end_month:
        end_month = parse_month(args.end_month)
        data = data[data["month"] <= end_month].copy()
    if data.empty:
        raise ValueError("No rows left after month filters.")

    grouped = (
        data.groupby(["page", "month"], as_index=False)
        .agg(
            {
                "revenue": "sum",
                "clicks": "sum",
                "sessions": "sum",
                "impressions": "sum",
                "page_type": first_non_empty,
                "has_ga4_data": "max",
                "has_gsc_data": "max",
            }
        )
        .sort_values(["page", "month"])
        .reset_index(drop=True)
    )
    grouped["month_of_year"] = grouped["month"].dt.month
    grouped["month_index"] = build_month_index(grouped["month"])

    rev_factors = compute_seasonality_factors(
        grouped,
        metric_col="revenue",
        output_col="revenue_seasonality_factor",
    )
    click_factors = compute_seasonality_factors(
        grouped,
        metric_col="clicks",
        output_col="clicks_seasonality_factor",
    )
    grouped = grouped.merge(rev_factors, on=["page_type", "month_of_year"], how="left")
    grouped = grouped.merge(click_factors, on=["page_type", "month_of_year"], how="left")
    grouped["revenue_seasonality_factor"] = pd.to_numeric(
        grouped["revenue_seasonality_factor"], errors="coerce"
    ).fillna(1.0)
    grouped["clicks_seasonality_factor"] = pd.to_numeric(
        grouped["clicks_seasonality_factor"], errors="coerce"
    ).fillna(1.0)

    grouped["rev_adj"] = np.log1p(grouped["revenue"] / grouped["revenue_seasonality_factor"])
    grouped["clicks_adj"] = np.log1p(grouped["clicks"] / grouped["clicks_seasonality_factor"])

    latest_month = grouped["month"].max()
    prev_year_month = latest_month - pd.DateOffset(years=1)
    max_month_count = int(grouped["month"].nunique())

    rows: list[dict[str, object]] = []
    for page, subset in grouped.groupby("page"):
        subset = subset.sort_values("month")
        x = subset["month_index"].to_numpy(dtype=float)
        rev_y = subset["rev_adj"].to_numpy(dtype=float)
        click_y = subset["clicks_adj"].to_numpy(dtype=float)

        slope_rev, slope_rev_method = compute_slope(x, rev_y)
        slope_clicks, slope_clicks_method = compute_slope(x, click_y)

        total_revenue = float(subset["revenue"].sum())
        total_clicks = float(subset["clicks"].sum())
        total_sessions = float(subset["sessions"].sum())
        months_observed = int(len(subset))
        months_with_ga4 = int(subset["has_ga4_data"].sum())
        months_with_gsc = int(subset["has_gsc_data"].sum())

        latest_row = subset[subset["month"] == latest_month]
        prev_year_row = subset[subset["month"] == prev_year_month]

        latest_revenue = float(latest_row["revenue"].sum()) if not latest_row.empty else np.nan
        latest_clicks = float(latest_row["clicks"].sum()) if not latest_row.empty else np.nan
        prev_year_revenue = float(prev_year_row["revenue"].sum()) if not prev_year_row.empty else np.nan
        prev_year_clicks = float(prev_year_row["clicks"].sum()) if not prev_year_row.empty else np.nan

        revenue_yoy_delta = np.nan
        clicks_yoy_delta = np.nan
        if (
            not latest_row.empty
            and not prev_year_row.empty
            and bool(latest_row["has_ga4_data"].iloc[0])
            and bool(prev_year_row["has_ga4_data"].iloc[0])
            and prev_year_revenue > 0
        ):
            revenue_yoy_delta = float((latest_revenue - prev_year_revenue) / prev_year_revenue)
        if (
            not latest_row.empty
            and not prev_year_row.empty
            and bool(latest_row["has_gsc_data"].iloc[0])
            and bool(prev_year_row["has_gsc_data"].iloc[0])
            and prev_year_clicks > 0
        ):
            clicks_yoy_delta = float((latest_clicks - prev_year_clicks) / prev_year_clicks)

        rows.append(
            {
                "page": page,
                "page_type": first_non_empty(subset["page_type"]),
                "months_observed": months_observed,
                "months_with_ga4": months_with_ga4,
                "months_with_gsc": months_with_gsc,
                "total_revenue": total_revenue,
                "total_clicks": total_clicks,
                "total_sessions": total_sessions,
                "slope_rev": slope_rev,
                "slope_clicks": slope_clicks,
                "slope_rev_method": slope_rev_method,
                "slope_clicks_method": slope_clicks_method,
                "latest_month": latest_month.date().isoformat(),
                "latest_revenue": latest_revenue,
                "latest_clicks": latest_clicks,
                "prev_year_revenue": prev_year_revenue,
                "prev_year_clicks": prev_year_clicks,
                "revenue_yoy_delta": revenue_yoy_delta,
                "clicks_yoy_delta": clicks_yoy_delta,
            }
        )

    scored = pd.DataFrame(rows)
    if scored.empty:
        raise ValueError("No page-level rows available for scoring.")

    scored["rev_decay_raw"] = (-pd.to_numeric(scored["slope_rev"], errors="coerce")).clip(lower=0.0)
    scored["click_decay_raw"] = (
        -pd.to_numeric(scored["slope_clicks"], errors="coerce")
    ).clip(lower=0.0)

    scored["rev_decay"] = rank_to_0_1(scored["rev_decay_raw"])
    scored["click_decay"] = rank_to_0_1(scored["click_decay_raw"])
    scored["score_base"] = 0.65 * scored["rev_decay"] + 0.35 * scored["click_decay"]

    scored["history_factor"] = (
        pd.to_numeric(scored["months_observed"], errors="coerce").fillna(0.0) / max_month_count
    ).clip(lower=0.0, upper=1.0)
    scored["ga4_coverage_factor"] = (
        pd.to_numeric(scored["months_with_ga4"], errors="coerce").fillna(0.0) / max_month_count
    ).clip(lower=0.0, upper=1.0)
    scored["gsc_coverage_factor"] = (
        pd.to_numeric(scored["months_with_gsc"], errors="coerce").fillna(0.0) / max_month_count
    ).clip(lower=0.0, upper=1.0)

    rev_p95 = float(scored["total_revenue"].quantile(0.95)) if not scored.empty else 0.0
    click_p95 = float(scored["total_clicks"].quantile(0.95)) if not scored.empty else 0.0
    rev_scale = np.log1p(rev_p95) if rev_p95 > 0 else 1.0
    click_scale = np.log1p(click_p95) if click_p95 > 0 else 1.0
    scored["revenue_volume_factor"] = (
        np.log1p(pd.to_numeric(scored["total_revenue"], errors="coerce").fillna(0.0)) / rev_scale
    ).clip(lower=0.0, upper=1.0)
    scored["click_volume_factor"] = (
        np.log1p(pd.to_numeric(scored["total_clicks"], errors="coerce").fillna(0.0)) / click_scale
    ).clip(lower=0.0, upper=1.0)
    scored["volume_factor"] = 0.6 * scored["revenue_volume_factor"] + 0.4 * scored["click_volume_factor"]

    base_confidence = (
        0.35 * scored["history_factor"]
        + 0.25 * scored["ga4_coverage_factor"]
        + 0.25 * scored["gsc_coverage_factor"]
        + 0.15 * scored["volume_factor"]
    )

    global_gsc_click_coverage_ratio = 1.0
    gsc_summary_json = Path(args.gsc_summary_json) if args.gsc_summary_json else None
    if gsc_summary_json:
        if not gsc_summary_json.exists():
            raise FileNotFoundError(f"GSC summary JSON not found: {gsc_summary_json}")
        gsc_summary = json.loads(gsc_summary_json.read_text(encoding="utf-8"))
        pct = (
            gsc_summary.get("coverage", {})
            .get("clicks_pct_page_rows_vs_property")
        )
        if pct is not None:
            global_gsc_click_coverage_ratio = max(0.0, min(float(pct) / 100.0, 1.0))

    scored["confidence_factor"] = (base_confidence * global_gsc_click_coverage_ratio).clip(
        lower=0.0, upper=1.0
    )
    scored["decay_score"] = (scored["score_base"] * scored["confidence_factor"] * 100.0).round(4)

    scored["losing_revenue_and_clicks"] = (
        (pd.to_numeric(scored["slope_rev"], errors="coerce") < 0)
        & (pd.to_numeric(scored["slope_clicks"], errors="coerce") < 0)
    )
    scored["latest_yoy_both_negative"] = (
        (pd.to_numeric(scored["revenue_yoy_delta"], errors="coerce") < 0)
        & (pd.to_numeric(scored["clicks_yoy_delta"], errors="coerce") < 0)
    )
    scored["severity"] = scored["decay_score"].map(severity_band)

    scored = scored.sort_values("decay_score", ascending=False).reset_index(drop=True)
    top = scored.head(args.top_n).copy()
    both_loss = scored[scored["losing_revenue_and_clicks"]].copy()

    seasonality_out = (
        grouped[
            [
                "page_type",
                "month_of_year",
                "revenue_seasonality_factor",
                "clicks_seasonality_factor",
            ]
        ]
        .drop_duplicates()
        .sort_values(["page_type", "month_of_year"])
        .reset_index(drop=True)
    )
    adjusted_monthly_out = grouped[
        [
            "page",
            "page_type",
            "month",
            "revenue",
            "clicks",
            "sessions",
            "impressions",
            "revenue_seasonality_factor",
            "clicks_seasonality_factor",
            "rev_adj",
            "clicks_adj",
            "has_ga4_data",
            "has_gsc_data",
        ]
    ].copy()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    all_out = output_dir / "decay_scores_all_pages.csv"
    top_out = output_dir / "decay_scores_top_pages.csv"
    both_loss_out = output_dir / "decay_pages_losing_revenue_and_clicks.csv"
    seasonality_out_path = output_dir / "seasonality_factors_page_type_month.csv"
    adjusted_monthly_out_path = output_dir / "monthly_adjusted_signals.csv"

    scored.to_csv(all_out, index=False)
    top.to_csv(top_out, index=False)
    both_loss.to_csv(both_loss_out, index=False)
    seasonality_out.to_csv(seasonality_out_path, index=False)
    adjusted_monthly_out.to_csv(adjusted_monthly_out_path, index=False)

    summary = {
        "run_date_utc": datetime.utcnow().isoformat() + "Z",
        "inputs": {
            "input_model_csv": str(input_csv),
            "gsc_summary_json": str(gsc_summary_json) if gsc_summary_json else None,
        },
        "analysis_window": {
            "min_month": grouped["month"].min().date().isoformat(),
            "max_month": grouped["month"].max().date().isoformat(),
            "month_count": max_month_count,
        },
        "counts": {
            "pages_in_panel": int(len(scored)),
            "pages_losing_revenue_and_clicks": int(len(both_loss)),
            "top_n": int(min(args.top_n, len(scored))),
        },
        "score_distribution": {
            "score_min": float(scored["decay_score"].min()),
            "score_median": float(scored["decay_score"].median()),
            "score_max": float(scored["decay_score"].max()),
        },
        "settings": {
            "weights": {"rev_decay": 0.65, "click_decay": 0.35},
            "global_gsc_click_coverage_ratio": global_gsc_click_coverage_ratio,
            "confidence_components": {
                "history": 0.35,
                "ga4_coverage": 0.25,
                "gsc_coverage": 0.25,
                "volume": 0.15,
            },
        },
        "outputs": {
            "all_pages_csv": str(all_out),
            "top_pages_csv": str(top_out),
            "losing_revenue_and_clicks_csv": str(both_loss_out),
            "seasonality_factors_csv": str(seasonality_out_path),
            "monthly_adjusted_signals_csv": str(adjusted_monthly_out_path),
        },
    }
    summary_out = output_dir / "summary.json"
    summary_out.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print(f"Wrote: {all_out}")
    print(f"Wrote: {top_out}")
    print(f"Wrote: {both_loss_out}")
    print(f"Wrote: {seasonality_out_path}")
    print(f"Wrote: {adjusted_monthly_out_path}")
    print(f"Wrote: {summary_out}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Score page-level revenue/click decay using de-seasonalized monthly signals and robust trend slopes."
        )
    )
    parser.add_argument(
        "--input-model-csv",
        default=str(
            ROOT_DIR / "data" / "interim" / "revenue_decay_radar_model_input" / "model_input_monthly.csv"
        ),
        help="Model input monthly CSV (from revenue_decay_model_input pipeline).",
    )
    parser.add_argument(
        "--gsc-summary-json",
        default=str(ROOT_DIR / "data" / "interim" / "revenue_decay_radar_combined" / "gsc_summary.json"),
        help="Optional GSC summary JSON for global click coverage adjustment.",
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
        "--top-n",
        type=int,
        default=300,
        help="Number of top pages to output.",
    )
    parser.add_argument(
        "--output-dir",
        default=str(ROOT_DIR / "reports" / "analysis" / "revenue_decay_radar" / "scoring"),
        help="Output directory for scored outputs.",
    )
    return parser


if __name__ == "__main__":
    parser = build_parser()
    run(parser.parse_args())
