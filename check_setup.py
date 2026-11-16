"""Quick check (no web server): loads the 4 models and makes one forecast.

Run from this folder:  python check_setup.py
If this works, the app will work too.
"""
import json
from pathlib import Path

import pandas as pd

from backend.predict import EnergyForecaster

root = Path(__file__).resolve().parent
forecaster = EnergyForecaster(root / "models")
print(f"Loaded {len(forecaster.models)} models: horizons {sorted(forecaster.models)} h")
data = pd.read_csv(root / "data" / "cu_bems_2019_hourly.csv", parse_dates=["Date"], float_precision="round_trip")
print(f"Loaded {len(data)} hourly rows ({int(data['building_demand'].notna().sum())} with valid demand)")
print(json.dumps(forecaster.predict_latest(data), indent=2, default=str))
print("\nSetup OK - now run the app (run_local.bat on Windows, ./run_local.sh on macOS/Linux).")
