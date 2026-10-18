"""
Lagring i en lokal SQLite-database (én fil: data/aksjeradar.db).

Tabeller:
  prices     – daglige kurser per aksje
  snapshots  – fundamentaldata/analytikerdata/innsidehandler per aksje (JSON) med tidsstempel
  scores     – resultatet av hver kjøring, per aksje (JSON)
  ideas      – idékategoriene fra hver kjøring (JSON)
"""
from __future__ import annotations

import json
import math
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

SCHEMA = """
CREATE TABLE IF NOT EXISTS prices (
    ticker TEXT, date TEXT, open REAL, high REAL, low REAL, close REAL, volume REAL,
    PRIMARY KEY (ticker, date)
);
CREATE TABLE IF NOT EXISTS snapshots (
    kind TEXT, ticker TEXT, fetched_at TEXT, payload TEXT,
    PRIMARY KEY (kind, ticker)
);
CREATE TABLE IF NOT EXISTS scores (
    run_date TEXT, ticker TEXT, payload TEXT,
    PRIMARY KEY (run_date, ticker)
);
CREATE TABLE IF NOT EXISTS ideas (
    run_date TEXT PRIMARY KEY, payload TEXT
);
"""


def clean_for_json(obj):
    """Gjør numpy-tall, NaN og datoer om til noe json.dumps forstår."""
    if isinstance(obj, dict):
        return {str(k): clean_for_json(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [clean_for_json(v) for v in obj]
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating, float)):
        v = float(obj)
        return None if (math.isnan(v) or math.isinf(v)) else v
    if isinstance(obj, (pd.Timestamp, datetime)):
        return obj.strftime("%Y-%m-%d")
    if obj is pd.NaT:
        return None
    return obj


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class Storage:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.executescript(SCHEMA)

    # ---------- kurser ----------
    def save_prices(self, ticker: str, df: pd.DataFrame) -> None:
        rows = [
            (
                ticker,
                pd.Timestamp(idx).strftime("%Y-%m-%d"),
                float(r["Open"]), float(r["High"]), float(r["Low"]), float(r["Close"]),
                float(r["Volume"]) if not pd.isna(r["Volume"]) else 0.0,
            )
            for idx, r in df.iterrows()
            if not pd.isna(r["Close"])
        ]
        self.conn.executemany(
            "INSERT OR REPLACE INTO prices VALUES (?,?,?,?,?,?,?)", rows
        )
        self.conn.commit()

    def load_prices(self, ticker: str) -> pd.DataFrame:
        df = pd.read_sql_query(
            "SELECT date, open, high, low, close, volume FROM prices WHERE ticker=? ORDER BY date",
            self.conn, params=(ticker,),
        )
        if df.empty:
            return df
        df["date"] = pd.to_datetime(df["date"])
        df = df.set_index("date")
        df.columns = ["Open", "High", "Low", "Close", "Volume"]
        return df

    # ---------- snapshots (fundamental/analytiker/innsider) ----------
    def save_snapshot(self, kind: str, ticker: str, payload: dict) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO snapshots VALUES (?,?,?,?)",
            (kind, ticker, now_iso(), json.dumps(clean_for_json(payload), ensure_ascii=False)),
        )
        self.conn.commit()

    def load_snapshot(self, kind: str, ticker: str) -> tuple[dict | None, float | None]:
        """Returnerer (payload, alder i dager) – eller (None, None) hvis ingenting finnes."""
        row = self.conn.execute(
            "SELECT fetched_at, payload FROM snapshots WHERE kind=? AND ticker=?", (kind, ticker)
        ).fetchone()
        if not row:
            return None, None
        fetched = datetime.strptime(row[0], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        age_days = (datetime.now(timezone.utc) - fetched).total_seconds() / 86400
        return json.loads(row[1]), age_days

    # ---------- scores ----------
    def save_scores(self, run_date: str, table: pd.DataFrame) -> None:
        rows = []
        for rec in table.to_dict(orient="records"):
            rows.append((run_date, rec["ticker"], json.dumps(clean_for_json(rec), ensure_ascii=False)))
        self.conn.execute("DELETE FROM scores WHERE run_date=?", (run_date,))
        self.conn.executemany("INSERT OR REPLACE INTO scores VALUES (?,?,?)", rows)
        self.conn.commit()

    def load_scores(self, run_date: str | None = None) -> pd.DataFrame:
        if run_date is None:
            dates = self.run_dates()
            if not dates:
                return pd.DataFrame()
            run_date = dates[0]
        rows = self.conn.execute(
            "SELECT payload FROM scores WHERE run_date=?", (run_date,)
        ).fetchall()
        if not rows:
            return pd.DataFrame()
        df = pd.DataFrame([json.loads(r[0]) for r in rows])
        if "score" in df.columns:
            df = df.sort_values("score", ascending=False).reset_index(drop=True)
        return df

    def run_dates(self) -> list[str]:
        rows = self.conn.execute(
            "SELECT DISTINCT run_date FROM scores ORDER BY run_date DESC"
        ).fetchall()
        return [r[0] for r in rows]

    # ---------- ideer ----------
    def save_ideas(self, run_date: str, ideas: dict) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO ideas VALUES (?,?)",
            (run_date, json.dumps(clean_for_json(ideas), ensure_ascii=False)),
        )
        self.conn.commit()

    def load_ideas(self, run_date: str) -> dict:
        row = self.conn.execute("SELECT payload FROM ideas WHERE run_date=?", (run_date,)).fetchone()
        return json.loads(row[0]) if row else {}

    def close(self) -> None:
        self.conn.close()
