"""CU-BEMS preprocessing, ported from the final forecasting notebook.

The historical demand feature engineering uses row shifts and rolling windows,
EXACTLY as the supplied training notebook does. The notebook omitted 13 raw
hourly timestamps in 2019 and does not reindex them. To match the already trained
models, this module preserves the same sparse timestamp sequence.
IMPORTANT: for a robust future version, correct the training notebook to use
a continuous hourly index and retrain. The current exported models reflect the
original notebook behavior near omitted timestamps.
"""
from pathlib import Path
import re
import numpy as np
import pandas as pd

FLOORS = [str(i) for i in range(1, 8)]
MIN_VALID_MINUTES_PER_HOUR = 45
HORIZONS = (1, 6, 12, 24)
ENV_COLUMNS = ("temperature", "humidity", "lux")


def _datetime(series):
    # Accept the CSV's mixture of timestamp formats on pandas versions with
    # or without the `format="mixed"` feature.
    try:
        return pd.to_datetime(series, format="mixed", errors="coerce")
    except (ValueError, TypeError):
        return pd.to_datetime(series, errors="coerce")


def identify_columns(frame):
    cols = frame.columns
    return (
        [x for x in cols if "(kW)" in x],
        [x for x in cols if "(degC)" in x],
        [x for x in cols if "(RH%)" in x],
        [x for x in cols if "(lux)" in x],
    )


def hourly_from_raw_floors(dataset_dir):
    """Reproduce notebook floor-demand and environment aggregation from CSVs.

    Returns the same (potentially sparse) hourly grid as the training notebook.
    2019 floor files correspond to the training setup.
    """
    dataset_dir = Path(dataset_dir)
    # The saved models were trained on 2019 CU-BEMS. Do not combine 2018
    # files with 2019 files when both are present in the user's directory.
    files = sorted(dataset_dir.glob("2019Floor*.csv"))
    if not files:
        raise FileNotFoundError(f"No 2019Floor*.csv files found in {dataset_dir}")
    floor_parts = []
    env_parts = []
    seen_floors = set()
    for file in files:
        match = re.search(r"Floor(\d+)", file.name)
        if not match:
            continue
        floor = match.group(1)
        if floor not in FLOORS:
            continue
        # Mirror the notebook's 2019 modelling year. Other years can be used
        # only via an explicit folder consisting of exactly that input year.
        data = pd.read_csv(file)
        if "Date" not in data:
            raise ValueError(f"{file.name}: missing Date column")
        data["Date"] = _datetime(data["Date"])
        data = data.dropna(subset=["Date"]).sort_values("Date")
        power, temps, rhs, luxs = identify_columns(data)
        if not power:
            raise ValueError(f"{file.name}: no (kW) power columns")
        seen_floors.add(floor)
        complete = data[power].notna().all(axis=1)
        data["floor_demand"] = np.where(complete, data[power].sum(axis=1), np.nan)
        data["valid_minute"] = data["floor_demand"].notna().astype(int)
        hourly = data.set_index("Date")[["floor_demand", "valid_minute"]].resample("1h").agg(
            {"floor_demand": "mean", "valid_minute": "sum"}
        ).reset_index()
        hourly.loc[hourly["valid_minute"] < MIN_VALID_MINUTES_PER_HOUR, "floor_demand"] = np.nan
        hourly["Floor"] = floor
        floor_parts.append(hourly)
        if floor != "1":
            # Same time-t environmental aggregation as notebook, without
            # imputing missing sensors.
            for name, source in zip(ENV_COLUMNS, (temps, rhs, luxs)):
                data[name] = data[source].mean(axis=1) if source else np.nan
            env = data.set_index("Date")[list(ENV_COLUMNS)].resample("1h").mean().reset_index()
            env_parts.append(env)

    if seen_floors != set(FLOORS):
        raise ValueError(f"Expected Floors 1–7, found {sorted(seen_floors)}")
    floor_hourly = pd.concat(floor_parts, ignore_index=True)
    # Same pivot and min_count=7 target rule as notebook.
    wide = floor_hourly.pivot_table(index="Date", columns="Floor", values="floor_demand", aggfunc="first")
    if not set(FLOORS).issubset(wide.columns):
        raise ValueError("Some floors have no valid demand observations")
    wide = wide[FLOORS].sort_index()
    # IMPORTANT: match the trained notebook exactly. Its pivot_table also
    # omits timestamps where every floor has NaN demand. Therefore do not
    # reindex to a continuous hourly grid here, or historical lag features
    # will differ from those used to train the saved models.
    # The notebook has 13 such missing timestamps during 2019.
    result = pd.DataFrame({"Date": wide.index, "building_demand": wide.sum(axis=1, min_count=7).values})
    if not env_parts:
        raise ValueError("No environmental data for Floors 2–7")
    env_building = pd.concat(env_parts, ignore_index=True).groupby("Date")[list(ENV_COLUMNS)].mean().reset_index()
    combined = result.merge(env_building, on="Date", how="left")
    return validate_hourly(combined)


def validate_hourly(data):
    """Validate already-prepared hourly data, e.g. a website-uploaded CSV."""
    required = ["Date", "building_demand", *ENV_COLUMNS]
    missing = [c for c in required if c not in data.columns]
    if missing:
        raise ValueError(f"Missing hourly columns: {missing}")
    data = data[required].copy()
    data["Date"] = _datetime(data["Date"])
    if data["Date"].isna().any():
        raise ValueError("Invalid Date timestamps")
    if data["Date"].duplicated().any():
        raise ValueError("Duplicate hourly timestamps")
    data = data.sort_values("Date").reset_index(drop=True)
    if not (data["Date"].dt.minute.eq(0) & data["Date"].dt.second.eq(0)).all():
        raise ValueError("Timestamps must be on the hour")
    if len(data) < 169:
        raise ValueError("At least 169 hourly rows are required for the 168h lag")
    # The training notebook does NOT restore all missing clock hours.
    # Allow sparse timestamps to reproduce the feature values it learned.
    # This is backward compatibility for the already-trained models, not
    # a recommendation for future time-series model training.
    gaps = data["Date"].diff().dropna()
    if (gaps <= pd.Timedelta(0)).any():
        raise ValueError("Date must be strictly increasing")
    for c in ["building_demand", *ENV_COLUMNS]:
        data[c] = pd.to_numeric(data[c], errors="coerce")
    return data


def add_features(frame):
    """Notebook-consistent feature construction on its sparse hourly rows."""
    data = validate_hourly(frame)
    for lag in (1, 2, 3, 6, 12, 24, 48, 168):
        data[f"lag_{lag}h"] = data["building_demand"].shift(lag)
    shifted = data["building_demand"].shift(1)
    for window in (24, 168):
        rolling = shifted.rolling(window)
        data[f"rolling_mean_{window}h"] = rolling.mean()
        data[f"rolling_std_{window}h"] = rolling.std()
        data[f"rolling_min_{window}h"] = rolling.min()
        data[f"rolling_max_{window}h"] = rolling.max()
    data["hour"] = data["Date"].dt.hour
    data["day_of_week"] = data["Date"].dt.dayofweek
    data["is_weekend"] = (data["day_of_week"] >= 5).astype(int)
    data["day_of_month"] = data["Date"].dt.day
    data["month"] = data["Date"].dt.month
    return data


def target_holiday_flag(origin, horizon):
    """Use target calendar day (NOT origin calendar day), in Thailand."""
    try:
        import holidays
    except ImportError as exc:
        raise ImportError("Install dependencies: pip install -r backend/requirements.txt") from exc
    target = pd.Timestamp(origin) + pd.Timedelta(hours=int(horizon))
    th = holidays.country_holidays("TH", years=[target.year])
    return int(target.date() in th)
