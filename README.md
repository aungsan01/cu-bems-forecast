---
title: CU-BEMS Energy Demand Forecasting
emoji: ⚡
colorFrom: purple
colorTo: yellow
sdk: docker
app_port: 7860
pinned: false
---

# CU-BEMS Energy Demand Forecasting – Deployed Model

Web dashboard and API for our CPDSAI project **"Reliable Multi-Horizon Smart Building Energy Demand
Forecasting Using Machine Learning"** (Asian Institute of Technology, August 2026 semester).

The app deploys our **four trained LightGBM models**, which forecast the whole-building electricity demand
(kW) of the CU-BEMS seven-floor building **1, 6, 12 and 24 hours ahead**.

## Full machine-learning pipeline

| Stage | Where |
|---|---|
| Data collection | CU-BEMS dataset (Kaggle, Miller): 1-minute floor data, 2018–2019 |
| Preprocessing | `backend/preprocessing.py` – floors aggregated to hourly building demand; a minute counts only if all power sensors are present, an hour needs ≥ 45 valid minutes and all 7 floors; missing values are **never** set to zero |
| Feature engineering | Demand lags (1–168 h), 24 h/168 h rolling statistics, calendar features, Thai holiday of the target date, temperature/humidity/lux at the forecast time (no future values) |
| Training & evaluation | Project notebooks: rolling-origin validation, baselines (persistence, previous-day, previous-week), MAE/RMSE/R², nMAE, CV(RMSE), peak-hour analysis |
| **Deployment** | This app: FastAPI backend + web dashboard, packaged with Docker |

## What the dashboard does

- **Historical mode (2019):** choose a forecast time and compare the 1/6/12/24 h forecasts with the measured demand.
- **Simulation mode (2026):** forecasts from *synthetic* input data (not real measurements).
- **Upload:** forecast from your own hourly CSV with columns `Date, building_demand, temperature, humidity, lux`
  (at least 169 consecutive hourly rows).
- Plain-language insights, missing-data warnings, holiday context and advisory recommendations.

## Project structure

```
backend/      FastAPI app (api.py), model loading (predict.py), preprocessing.py, manager notes (activities.py)
frontend/     Dashboard (index.html, app.js, styles.css) – served by the same app
models/       lightgbm_1h/6h/12h/24h.joblib + model_metadata.json
data/         cu_bems_2019_hourly.csv (pre-processed from the raw 2019 floor CSVs with backend/preprocessing.py)
              cu_bems_simulated_2026.csv (synthetic data for the simulation mode)
Dockerfile    Container for deployment (Hugging Face Spaces / any Docker host)
```

`data/cu_bems_2019_hourly.csv` (≈0.7 MB) is identical to running `hourly_from_raw_floors()` on the
raw 2019 floor files (≈540 MB): 8,747 hourly rows, 4,338 with a valid building demand. The raw data is
not included; download it from Kaggle (CU-BEMS) if needed.

## API endpoints

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/health` | Status and number of loaded models (should be 4) |
| POST | `/predict/demo` | Forecast from the latest 2019 hour |
| POST | `/analyze/demo`, `/analyze/simulated`, `/analyze/upload` | Dashboard forecasts (historical / simulated / uploaded CSV) |
| GET | `/available-times` | Selectable forecast times |
| GET/POST | `/activities` | Manager notes |
| GET | `/docs` | Interactive API documentation (Swagger) |

## Run on your laptop

Requires **Python 3.11 or 3.12**.

**Windows (PowerShell, inside this folder):**
```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python check_setup.py        # should print "Loaded 4 models" and four forecasts
run_local.bat                # or: python -m uvicorn backend.api:app --host 127.0.0.1 --port 8000
```

**macOS / Linux:**
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python check_setup.py
./run_local.sh
```

Open **http://127.0.0.1:8000** (dashboard) and **http://127.0.0.1:8000/docs** (API).

## Deploy to Hugging Face Spaces (free)

1. Create a free account at huggingface.co.
2. **New Space** → name it (e.g. `cu-bems-forecast`) → SDK **Docker** → template **Blank** → hardware **CPU basic (free)** → Public → *Create Space*.
3. In the Space: **Files → Add file → Upload files** → drag in **all files and folders of this project**
   (`README.md`, `Dockerfile`, `requirements.txt`, `backend/`, `frontend/`, `models/`, `data/`, …) → *Commit*.
4. Wait for the build (a few minutes; see the **Logs** tab). When it shows **Running**, open the app.
   Public URL: `https://<your-username>-cu-bems-forecast.hf.space`

The same `Dockerfile` also works on other Docker hosts (e.g. Render): `docker build -t cu-bems . && docker run -p 7860:7860 cu-bems`.

## Notes and limitations

- Models were trained on 2019 CU-BEMS data and predict **building demand in kW**; results may not transfer to other buildings or years.
- Manager notes are stored in a temporary database on Hugging Face and are reset when the Space restarts.
- `.joblib` files use pickle – only load model files from a trusted source.
- Recommendations are advisory, not device-control instructions.

**Authors:** Aung San Lin (st126669), Dakchhyeta Bade Shrestha (st126671) · **Advisor:** Dr. Chantri Polprasert
