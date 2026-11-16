"""SQLite-backed, manager-supplied activities. Does not modify model predictions."""
import os
import sqlite3
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Optional, List
from pydantic import BaseModel, Field, validator

# Keep notes in the dashboard project even if the server's working directory changes.
PROJECT_DB = Path(__file__).resolve().parents[1] / "manager_activities.sqlite3"
DB_PATH = Path(os.getenv("CU_BEMS_ACTIVITY_DB", str(PROJECT_DB)))
TYPES = {"Classrooms fully occupied", "University event / seminar", "Examination", "Extended laboratory usage", "Maintenance", "Other"}

class ActivityInput(BaseModel):
    data_mode: str = "simulation"
    category: str = "University event / seminar"
    date: date
    start_time: str
    end_time: str
    notes: str = Field(default="", max_length=500)
    repeat: str = "none"  # none, weekly
    repeat_until: Optional[date] = None

    @validator("data_mode")
    def valid_mode(cls, value):
        if value not in ("historical", "simulation", "upload"):
            raise ValueError("Invalid data mode")
        return value

    @validator("category")
    def valid_category(cls, value):
        if value not in TYPES: raise ValueError("Unknown activity category")
        return value

    @validator("start_time", "end_time")
    def valid_time(cls, value):
        try: datetime.strptime(value, "%H:%M")
        except ValueError: raise ValueError("Use a 24-hour time like 13:00")
        return value

    @validator("repeat")
    def valid_repeat(cls, value):
        if value not in ("none", "weekly"): raise ValueError("Repeat must be none or weekly")
        return value

    @validator("repeat_until", always=True)
    def valid_range(cls, value, values):
        day = values.get("date")
        if values.get("start_time") and values.get("end_time") and values["start_time"] >= values["end_time"]:
            raise ValueError("End time must be later than start time; use separate entries for overnight activities")
        if values.get("repeat") == "weekly":
            if not value: raise ValueError("Choose a repeat-until date")
            if day and (value < day or value > day + timedelta(days=90)):
                raise ValueError("Weekly repetition can cover up to 90 days")
        return value


def connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(DB_PATH))
    con.row_factory = sqlite3.Row
    return con

def init_db():
    with connect() as con:
        con.execute("""CREATE TABLE IF NOT EXISTS activities (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          data_mode TEXT NOT NULL,
          category TEXT NOT NULL,
          day TEXT NOT NULL,
          start_time TEXT NOT NULL,
          end_time TEXT NOT NULL,
          notes TEXT NOT NULL DEFAULT '',
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""")
        con.execute("CREATE INDEX IF NOT EXISTS idx_activities_mode_day ON activities(data_mode,day)")

def list_activities(mode, start=None, end=None):
    init_db()
    sql = "SELECT * FROM activities WHERE data_mode = ?"
    args = [mode]
    if start:
        sql += " AND day >= ?"
        args.append(start)
    if end:
        sql += " AND day <= ?"
        args.append(end)
    sql += " ORDER BY day DESC, start_time ASC, id DESC LIMIT 600"
    with connect() as con:
        return [dict(row) for row in con.execute(sql, args).fetchall()]

def save_activity(payload):
    init_db()
    days = [payload.date]
    if payload.repeat == "weekly":
        d = payload.date + timedelta(days=7)
        while d <= payload.repeat_until:
            days.append(d)
            d += timedelta(days=7)
    inserted = []
    with connect() as con:
        for day in days:
            cursor = con.execute("INSERT INTO activities (data_mode,category,day,start_time,end_time,notes) VALUES (?,?,?,?,?,?)", (
                payload.data_mode, payload.category, day.isoformat(), payload.start_time, payload.end_time, payload.notes.strip()))
            inserted.append(cursor.lastrowid)
    return {"created": len(inserted), "ids": inserted}

def delete_activity(activity_id):
    init_db()
    with connect() as con:
        cursor = con.execute("DELETE FROM activities WHERE id = ?",(activity_id,))
        return cursor.rowcount > 0
