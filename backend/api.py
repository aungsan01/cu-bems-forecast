from __future__ import annotations
"""FastAPI interface for the validated CU-BEMS inference pipeline.

Run from PROJECT root:
    python -m uvicorn backend.api:app --host 127.0.0.1 --port 8000   (from the app folder)
"""
import io
import os
from functools import lru_cache
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

import pandas as pd
from fastapi import FastAPI, HTTPException, UploadFile, File, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .predict import EnergyForecaster

APP_ROOT = Path(__file__).resolve().parents[1]  # folder that contains backend/, frontend/, models/, data/
from .preprocessing import hourly_from_raw_floors
from .activities import ActivityInput, init_db, list_activities, save_activity, delete_activity

MAX_UPLOAD = 20 * 1024 * 1024


@asynccontextmanager
async def lifespan(app: FastAPI):
    models_dir = Path(os.getenv("CU_BEMS_MODELS_DIR", str(APP_ROOT / "models")))
    app.state.forecaster = EnergyForecaster(models_dir)
    init_db()
    yield


app = FastAPI(title="CU-BEMS Energy Forecasting API", version="1.0.0", lifespan=lifespan)
# Local development only. Set allowed frontends explicitly before public deployment.
origins = os.getenv("CU_BEMS_CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",")
app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["GET", "POST", "DELETE"], allow_headers=["Content-Type"])


@app.get("/health")
def health(request: Request):
    return {"status": "ok", "models_loaded": len(request.app.state.forecaster.models), "horizons_hours": [1, 6, 12, 24], "manager_notes_enabled": True}


@app.post("/predict/upload")
async def predict_upload(request: Request, file: UploadFile = File(...)):
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(400, detail="Upload a .csv file")
    raw = await file.read(MAX_UPLOAD + 1)
    if len(raw) > MAX_UPLOAD:
        raise HTTPException(413, detail="CSV exceeds the 20 MB upload limit")
    try:
        data = pd.read_csv(io.BytesIO(raw))
        return request.app.state.forecaster.predict_latest(data)
    except (ValueError, KeyError, pd.errors.ParserError, UnicodeDecodeError) as exc:
        raise HTTPException(422, detail=str(exc)) from exc


@app.post("/predict/demo")
def predict_demo(request: Request):
    try:
        data = _load_demo_hourly()
        return request.app.state.forecaster.predict_latest(data)
    except (ValueError, FileNotFoundError, KeyError) as exc:
        raise HTTPException(422, detail=str(exc)) from exc


# Interactive dashboard: measured history and forecasts at a chosen historical origin.
class DemoSelection(BaseModel):
    origin: Optional[str] = None


def _load_demo_hourly():
    """Historical 2019 demo data.

    If CU_BEMS_DEMO_HOURLY_CSV points to the pre-processed hourly file (created
    once with hourly_from_raw_floors from the raw 2019 floor CSVs), load it;
    this is identical to processing the raw files but much faster and smaller.
    Otherwise fall back to processing the raw floor CSVs.
    """
    csv_path = os.getenv("CU_BEMS_DEMO_HOURLY_CSV", str(APP_ROOT / "data" / "cu_bems_2019_hourly.csv"))
    if csv_path and Path(csv_path).is_file():
        return pd.read_csv(csv_path, parse_dates=["Date"], float_precision="round_trip")
    return hourly_from_raw_floors(os.getenv("CU_BEMS_DEMO_FLOOR_DIR", "Dataset/CU-Beams"))


@lru_cache(maxsize=1)
def _demo_hourly():
    return _load_demo_hourly()


def _dashboard_payload(forecaster, data, requested_origin=None, window_hours=168):
    data = data.copy()
    data["Date"] = pd.to_datetime(data["Date"])
    data = data.sort_values("Date").reset_index(drop=True)
    observed = data.loc[data["building_demand"].notna()]
    if observed.empty:
        raise ValueError("No observed building demand values available")
    if requested_origin:
        origin = pd.Timestamp(requested_origin)
        if origin not in set(observed["Date"]):
            raise ValueError("Selected timestamp has no valid measured demand. Choose an observed timestamp.")
        data_for_forecast = data.loc[data["Date"] <= origin].copy()
    else:
        origin = pd.Timestamp(observed["Date"].iloc[-1])
        # Keep the complete input for the normal demo, including trailing NaNs.
        data_for_forecast = data
    forecast = forecaster.predict_latest(data_for_forecast)
    history_start = origin - pd.Timedelta(hours=window_hours)
    history = data.loc[(data["Date"] >= history_start) & (data["Date"] <= origin), ["Date", "building_demand"]].copy()
    # Add missing clock timestamps for charting only. Never use this grid for model inputs.
    history = history.set_index("Date").reindex(pd.date_range(history_start, origin, freq="h"))
    history_points = [{"datetime": t.isoformat(), "actual_demand_kw": None if pd.isna(v) else round(float(v), 4)} for t,v in history["building_demand"].items()]
    valid = history["building_demand"].dropna()
    prev_hour = history.loc[origin-pd.Timedelta(hours=1),"building_demand"] if origin-pd.Timedelta(hours=1) in history.index else float("nan")
    prev_day = history.loc[origin-pd.Timedelta(hours=24),"building_demand"] if origin-pd.Timedelta(hours=24) in history.index else float("nan")
    current = float(history.loc[origin,"building_demand"])
    def safe(v): return None if pd.isna(v) else round(float(v), 4)
    forecast["history"] = history_points
    forecast["observations"] = {
        "current_kw": safe(current),
        "previous_hour_kw": safe(prev_hour),
        "same_hour_yesterday_kw": safe(prev_day),
        "last_24h_average_kw": safe(history.loc[origin-pd.Timedelta(hours=23):origin,"building_demand"].mean()),
        "last_24h_valid_hours": int(history.loc[origin-pd.Timedelta(hours=23):origin,"building_demand"].notna().sum()),
        "history_window_hours": window_hours,
        "history_valid_points": int(valid.shape[0])
    }
    # Explanations based only on measured observations and forecast outputs.
    def delta_pct(value, reference):
        if value is None or reference is None or reference <= 0:
            return None
        return round((value / reference - 1) * 100, 1)

    current_value = safe(current)
    yesterday_value = safe(prev_day)
    previous_value = safe(prev_hour)
    one_day_change = delta_pct(current_value, yesterday_value)
    one_hour_change = delta_pct(current_value, previous_value)

    # Compare each model result with observed demand from the same clock hour
    # in the preceding week. Thresholds require at least four valid observations.
    historical_comparisons = []
    for item in forecast.get("forecasts", []):
        target_time = pd.Timestamp(item["target_datetime"])
        comparable = history.loc[
            (history.index < origin) &
            (history.index.hour == target_time.hour), "building_demand"
        ].dropna()
        baseline = float(comparable.median()) if len(comparable) >= 4 else None
        percentile_90 = float(comparable.quantile(.90)) if len(comparable) >= 4 else None
        projected = float(item["predicted_demand_kw"])
        historical_comparisons.append({
            "horizon_hours": item["horizon_hours"],
            "reference_median_kw": safe(baseline),
            "reference_p90_kw": safe(percentile_90),
            "reference_count": int(len(comparable)),
            "forecast_vs_usual_pct": delta_pct(projected, baseline),
            "above_usual_high": bool(percentile_90 is not None and projected > percentile_90),
        })

    advice = []
    if one_day_change is not None:
        adjective = "lower" if one_day_change < -5 else "higher" if one_day_change > 5 else "similar"
        phrasing = (f"Measured demand is {abs(one_day_change):g}% {adjective} than at the same hour yesterday."
                    if adjective != "similar" else "Measured demand is close to the same hour yesterday.")
        advice.append({"type":"comparison", "title":"Compared with yesterday", "explanation":phrasing,
                       "action":"Review the demand history for unusual changes; a difference alone does not identify the cause."})
    else:
        advice.append({"type":"comparison", "title":"Yesterday's comparison unavailable",
                       "explanation":"There is no valid reading for the same hour yesterday.",
                       "action":"Avoid drawing conclusions from a missing comparison."})

    holiday_forecasts = [item for item in forecast.get("forecasts",[]) if item.get("target_is_holiday")]
    if holiday_forecasts:
        horizons = ", ".join(str(item["horizon_hours"]) + "h" for item in holiday_forecasts)
        advice.append({"type":"holiday", "title":"Holiday in the forecast window",
                       "explanation":f"The {horizons} forecast time falls on a flagged public holiday. This does not confirm a building closure.",
                       "action":"Check planned occupancy and review lighting and cooling schedules in unused rooms; maintain essential services."})

    elevated = [r["horizon_hours"] for r in historical_comparisons if r["above_usual_high"]]
    if elevated:
        advice.append({"type":"demand", "title":"Higher-than-usual demand predicted",
                       "explanation":"Predicted demand exceeds the recent 90th percentile for a comparable hour at: " + ", ".join(f"{h}h" for h in elevated) + ".",
                       "action":"Review planned high-load activities and equipment schedules; this is a warning, not proof of waste."})
    elif all(r["reference_count"] >= 4 for r in historical_comparisons):
        advice.append({"type":"demand", "title":"No unusual high-demand signal",
                       "explanation":"None of the forecasts exceeds the recent 90th percentile for its clock hour.",
                       "action":"Continue routine monitoring; no special action is indicated by this rule."})
    else:
        advice.append({"type":"demand", "title":"Not enough comparable readings",
                       "explanation":"Some forecast hours have fewer than four matching historical measurements.",
                       "action":"Treat high/low comparisons cautiously until more data are available."})

    if forecast.get("missing_historical_demand_hours", 0) > 0:
        advice.append({"type":"quality", "title":"Some sensor readings are missing",
                       "explanation":"The historical dataset contains gaps. Forecasts may be less dependable when recent inputs are incomplete.",
                       "action":"Check missing sensor readings before making major operational changes."})

    forecast["insights"] = {
        "measured_change_vs_yesterday_pct": one_day_change,
        "measured_change_vs_previous_hour_pct": one_hour_change,
        "forecast_comparisons": historical_comparisons,
        "recommendations": advice,
        "disclaimer": "Advisory suggestions only. No equipment is controlled; no cause or savings are guaranteed."
    }
    forecast["historical_only"] = True
    forecast["requested_origin"] = requested_origin or None
    return forecast


@app.post("/analyze/demo")
def analyze_demo(selection: DemoSelection, request: Request):
    try:
        return _dashboard_payload(request.app.state.forecaster, _demo_hourly(), selection.origin)
    except (ValueError, KeyError, FileNotFoundError, TypeError) as exc:
        raise HTTPException(422, detail=str(exc)) from exc


@app.post("/analyze/upload")
async def analyze_upload(request: Request, file: UploadFile = File(...)):
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(400, detail="Upload a .csv file")
    raw = await file.read(MAX_UPLOAD + 1)
    if len(raw) > MAX_UPLOAD:
        raise HTTPException(413, detail="CSV exceeds the 20 MB upload limit")
    try:
        data = pd.read_csv(io.BytesIO(raw))
        return _dashboard_payload(request.app.state.forecaster, data)
    except (ValueError, KeyError, pd.errors.ParserError, UnicodeDecodeError) as exc:
        raise HTTPException(422, detail=str(exc)) from exc


# Separate educational simulation; readings are NOT actual 2026 observations.
@lru_cache(maxsize=1)
def _simulated_hourly():
    path = Path(os.getenv("CU_BEMS_SIM_CSV", str(APP_ROOT / "data" / "cu_bems_simulated_2026.csv")))
    if not path.is_file():
        raise FileNotFoundError(f"Simulation data missing: {path}. Extract the simulation ZIP into PROJECT root.")
    return pd.read_csv(path)


@app.post("/analyze/simulated")
def analyze_simulated(selection: DemoSelection, request: Request):
    try:
        result = _dashboard_payload(
            request.app.state.forecaster, _simulated_hourly(), selection.origin
        )
        result["data_mode"] = "simulation"
        result["source_label"] = "Synthetic CU-BEMS-style hourly data, November 2026"
        result["historical_only"] = False
        result["simulation_notice"] = (
            "DEMO ONLY: Input readings are synthetic, derived from altered 2019 patterns. "
            "Forecast values are real outputs of the saved model applied to synthetic inputs; "
            "they are not verified actual or live 2026 electricity demand."
        )
        return result
    except (ValueError, KeyError, FileNotFoundError, TypeError) as exc:
        raise HTTPException(422, detail=str(exc)) from exc


@app.get("/activities")
def get_activities(mode: str = "simulation"):
    if mode not in ("simulation", "historical", "upload"):
        raise HTTPException(400, detail="Invalid data mode")
    return {"activities": list_activities(mode)}


@app.post("/activities", status_code=201)
def create_activity(activity: ActivityInput):
    return save_activity(activity)


@app.post("/activities/{activity_id}/remove")
def remove_activity_via_post(activity_id: int):
    if not delete_activity(activity_id):
        raise HTTPException(404, detail="Activity not found")
    return {"deleted": True}


@app.delete("/activities/{activity_id}")
def remove_activity(activity_id: int):
    if not delete_activity(activity_id):
        raise HTTPException(404, detail="Activity not found")
    return {"deleted": True}


@app.get("/available-times")
def available_times(mode: str = "historical"):
    if mode not in ("historical", "simulation"):
        raise HTTPException(400, detail="Mode must be historical or simulation")
    try:
        data = _simulated_hourly() if mode == "simulation" else _demo_hourly()
        data = data.loc[data["building_demand"].notna(), ["Date"]].copy()
        data["Date"] = pd.to_datetime(data["Date"])
        groups = {}
        for dt in data["Date"]:
            groups.setdefault(dt.strftime("%Y-%m-%d"), set()).add(dt.strftime("%H:%M"))
        return {"mode": mode, "dates": {day: sorted(hours) for day, hours in sorted(groups.items())}}
    except (ValueError, KeyError, FileNotFoundError) as exc:
        raise HTTPException(422, detail=str(exc)) from exc


# Serve the dashboard from the same app, so the whole project has one URL.
# Mounted last, so all API routes above take priority.
from fastapi.staticfiles import StaticFiles  # noqa: E402

_frontend_dir = Path(os.getenv("CU_BEMS_FRONTEND_DIR", str(APP_ROOT / "frontend")))
if _frontend_dir.is_dir():
    app.mount("/", StaticFiles(directory=str(_frontend_dir), html=True), name="dashboard")
