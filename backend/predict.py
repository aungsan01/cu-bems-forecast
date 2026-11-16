"""Load exported CU-BEMS models and predict from an hourly demand history."""
from pathlib import Path
import json
import joblib
import numpy as np
import pandas as pd
from .preprocessing import HORIZONS, add_features, target_holiday_flag, validate_hourly

ROOT = Path(__file__).resolve().parents[1]


class EnergyForecaster:
    def __init__(self, model_dir=None):
        self.model_dir = Path(model_dir) if model_dir is not None else ROOT / "models"
        metadata_path = self.model_dir / "model_metadata.json"
        if not metadata_path.exists():
            raise FileNotFoundError(f"Missing {metadata_path}. Copy the five exported model files into models/")
        self.metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        self.models = {}
        for h in HORIZONS:
            cfg = self.metadata["models"][str(h)]
            filename = self.model_dir / cfg["filename"]
            self.models[h] = joblib.load(filename)  # only load your own trusted files
            expected = list(cfg["features_in_order"])
            actual = list(getattr(self.models[h], "feature_name_", expected))
            if actual != expected:
                raise ValueError(f"Feature mismatch for {h}h model: {actual} != {expected}")

    def predict_latest(self, hourly_data):
        data = validate_hourly(hourly_data)
        # The current origin should be a valid, fully observed demand hour.
        # The notebook's lags use t-1 and earlier; current demand isn't itself
        # a model feature, but it ensures there is an observed forecast origin.
        data = add_features(data)
        # The original floor files may end with missing-demand hours. Select
        # the latest *observed* origin rather than forecasting from a missing
        # endpoint or filling missing values with zero. Historical NaNs in
        # feature windows are still passed to LightGBM, as during training.
        observed = data.loc[data["building_demand"].notna()]
        if observed.empty:
            raise ValueError("No valid building-demand observation found in the hourly dataset")
        row = observed.tail(1).copy()
        origin = pd.Timestamp(row["Date"].iloc[0])
        last_hour = pd.Timestamp(data["Date"].iloc[-1])
        skipped_hours = int((last_hour - origin) / pd.Timedelta(hours=1))
        demand_lag_cols = [f"lag_{lag}h" for lag in (1, 2, 3, 6, 12, 24, 48, 168)]
        if row[demand_lag_cols].notna().sum(axis=1).iloc[0] == 0:
            raise ValueError(
                "Latest observed hour has no usable demand-history lags; "
                "cannot generate a meaningful forecast"
            )
        output = {
            "forecast_origin": origin.isoformat(),
            "last_input_timestamp": last_hour.isoformat(),
            "skipped_trailing_missing_hours": skipped_hours,
            "origin_is_last_input_hour": skipped_hours == 0,
            "unit": "kW", "forecasts": []
        }
        for h in HORIZONS:
            cfg = self.metadata["models"][str(h)]
            holiday_col = f"target_is_holiday_{h}h"
            row[holiday_col] = target_holiday_flag(origin, h)
            cols = cfg["features_in_order"]
            missing = [c for c in cols if c not in row.columns]
            if missing:
                raise ValueError(f"{h}h missing model features: {missing}")
            x = row[cols]  # exact feature names AND order saved with the model
            y = float(self.models[h].predict(x)[0])
            if not np.isfinite(y):
                raise RuntimeError(f"{h}h model returned non-finite result")
            output["forecasts"].append({
                "horizon_hours": h,
                "target_datetime": (origin + pd.Timedelta(hours=h)).isoformat(),
                "target_is_holiday": int(row[holiday_col].iloc[0]),
                "predicted_demand_kw": round(y, 4),
            })
        output["missing_historical_demand_hours"] = int(data["building_demand"].isna().sum())
        return output


def predict_from_hourly_csv(csv_path, model_dir=None):
    data = pd.read_csv(csv_path)
    return EnergyForecaster(model_dir).predict_latest(data)
