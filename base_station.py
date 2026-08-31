"""
FYP Base Station Service

Runs continuously on the laptop.

Pipeline:
Receiver ESP32 serial
    -> parse DATA lines
    -> SQLite database
    -> automatically updated CSV dataset
    -> Isolation Forest scoring/retraining
    -> analytics written back to database + AI CSV

Install:
    pip install -r requirements.txt

Run:
    python base_station.py
"""

import csv
import json
import math
import os
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import serial

from sklearn.ensemble import IsolationForest
from sklearn.impute import SimpleImputer
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from settings import (
    SERIAL_PORT,
    SERIAL_BAUD,
    DATABASE_FILE,
    RAW_CSV_FILE,
    AI_CSV_FILE,
    MODEL_FILE,
    MIN_TRAIN_SAMPLES,
    RETRAIN_EVERY_NEW_ROWS,
    TRAINING_WINDOW,
    CONTAMINATION,
)

FEATURES = [
    "soil_moisture",
    "soil_temperature",
    "ec",
    "ph",
    "nitrogen",
    "phosphorus",
    "potassium",
    "air_temperature",
    "humidity",
]

DATA_COLUMNS = [
    "node_id",
    "sequence_number",
    "hop_count",
    "status_flags",
    "soil_moisture",
    "soil_temperature",
    "ec",
    "ph",
    "nitrogen",
    "phosphorus",
    "potassium",
    "air_temperature",
    "humidity",
    "rssi",
    "snr",
]


def db_connect():
    con = sqlite3.connect(DATABASE_FILE, timeout=30)
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS readings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            received_at TEXT NOT NULL,
            node_id INTEGER NOT NULL,
            sequence_number INTEGER NOT NULL,
            hop_count INTEGER NOT NULL,
            status_flags INTEGER NOT NULL,
            soil_moisture REAL,
            soil_temperature REAL,
            ec REAL,
            ph REAL,
            nitrogen REAL,
            phosphorus REAL,
            potassium REAL,
            air_temperature REAL,
            humidity REAL,
            rssi REAL,
            snr REAL,
            ai_state TEXT DEFAULT 'LEARNING',
            anomaly INTEGER,
            anomaly_score REAL,
            insight TEXT,
            UNIQUE(node_id, sequence_number)
        )
        """
    )
    con.commit()
    return con


def safe_float(value):
    value = value.strip()
    if value.lower() in {"nan", "inf", "-inf"}:
        return float("nan")
    return float(value)


def parse_data_line(line):
    if not line.startswith("DATA,"):
        return None

    parts = line.strip().split(",")
    if len(parts) != 1 + len(DATA_COLUMNS):
        raise ValueError(
            f"Expected {1 + len(DATA_COLUMNS)} CSV fields, got {len(parts)}"
        )

    values = parts[1:]

    return {
        "node_id": int(values[0]),
        "sequence_number": int(values[1]),
        "hop_count": int(values[2]),
        "status_flags": int(values[3]),
        "soil_moisture": safe_float(values[4]),
        "soil_temperature": safe_float(values[5]),
        "ec": safe_float(values[6]),
        "ph": safe_float(values[7]),
        "nitrogen": safe_float(values[8]),
        "phosphorus": safe_float(values[9]),
        "potassium": safe_float(values[10]),
        "air_temperature": safe_float(values[11]),
        "humidity": safe_float(values[12]),
        "rssi": safe_float(values[13]),
        "snr": safe_float(values[14]),
    }


def insert_reading(con, row):
    received_at = datetime.now(timezone.utc).isoformat()

    fields = ["received_at"] + DATA_COLUMNS
    placeholders = ",".join(["?"] * len(fields))

    values = [received_at] + [row[field] for field in DATA_COLUMNS]

    try:
        con.execute(
            f"""
            INSERT INTO readings ({",".join(fields)})
            VALUES ({placeholders})
            """,
            values,
        )
        con.commit()
        return True
    except sqlite3.IntegrityError:
        # Duplicate node+sequence. Receiver normally suppresses these already,
        # but the database also protects against duplicates.
        return False


def export_csvs(con):
    df = pd.read_sql_query(
        "SELECT * FROM readings ORDER BY received_at ASC",
        con,
    )

    raw_columns = [
        "received_at",
        *DATA_COLUMNS,
    ]
    df[raw_columns].to_csv(RAW_CSV_FILE, index=False)
    df.to_csv(AI_CSV_FILE, index=False)


def valid_training_dataframe(con):
    df = pd.read_sql_query(
        """
        SELECT *
        FROM readings
        WHERE (status_flags & 1) = 1
          AND (status_flags & 2) = 2
        ORDER BY received_at DESC
        LIMIT ?
        """,
        con,
        params=(TRAINING_WINDOW,),
    )

    if df.empty:
        return df

    return df.iloc[::-1].reset_index(drop=True)


def train_model(df):
    X = df[FEATURES].replace([np.inf, -np.inf], np.nan)

    pipeline = Pipeline(
        [
            ("imputer", SimpleImputer(strategy="median")),
            ("scaler", StandardScaler()),
            (
                "isolation_forest",
                IsolationForest(
                    n_estimators=250,
                    contamination=CONTAMINATION,
                    random_state=42,
                    n_jobs=-1,
                ),
            ),
        ]
    )

    pipeline.fit(X)

    clean = pd.DataFrame(
        pipeline.named_steps["imputer"].transform(X),
        columns=FEATURES,
    )

    means = clean.mean().to_dict()
    stds = clean.std(ddof=0).replace(0, 1).to_dict()

    package = {
        "pipeline": pipeline,
        "means": means,
        "stds": stds,
        "trained_rows": len(df),
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "features": FEATURES,
    }

    joblib.dump(package, MODEL_FILE)

    print(
        f"[AI] Isolation Forest trained on {len(df)} rows "
        f"({package['trained_at']})."
    )

    return package


def load_model():
    if not Path(MODEL_FILE).exists():
        return None

    try:
        return joblib.load(MODEL_FILE)
    except Exception as exc:
        print(f"[AI] Could not load saved model: {exc}")
        return None


def largest_deviations(row, package, top_n=3):
    deviations = []

    for feature in FEATURES:
        value = row.get(feature)
        if value is None or pd.isna(value):
            continue

        mean = package["means"].get(feature, 0)
        std = package["stds"].get(feature, 1) or 1

        z = abs((float(value) - float(mean)) / float(std))
        deviations.append((feature, z, float(value), float(mean)))

    deviations.sort(key=lambda item: item[1], reverse=True)
    return deviations[:top_n]


def build_insight(row, prediction, score, package):
    if prediction == -1:
        prefix = (
            "Unusual environmental/soil pattern detected compared with the "
            "recent field baseline."
        )
    else:
        prefix = "Reading is consistent with the recent field baseline."

    deviations = largest_deviations(row, package)

    if not deviations:
        return prefix

    pretty = {
        "soil_moisture": "soil moisture",
        "soil_temperature": "soil temperature",
        "ec": "electrical conductivity",
        "ph": "soil pH",
        "nitrogen": "nitrogen",
        "phosphorus": "phosphorus",
        "potassium": "potassium",
        "air_temperature": "air temperature",
        "humidity": "humidity",
    }

    parts = []
    for feature, z, value, mean in deviations:
        parts.append(
            f"{pretty[feature]}={value:.2f} "
            f"(recent baseline {mean:.2f})"
        )

    return prefix + " Largest deviations: " + "; ".join(parts) + "."


def score_latest(con, package):
    df = pd.read_sql_query(
        "SELECT * FROM readings ORDER BY id DESC LIMIT 1",
        con,
    )

    if df.empty:
        return

    row = df.iloc[0].to_dict()
    reading_id = int(row["id"])

    X = pd.DataFrame([row])[FEATURES].replace(
        [np.inf, -np.inf], np.nan
    )

    prediction = int(package["pipeline"].predict(X)[0])

    # IsolationForest decision_function:
    # positive = more normal, negative = more anomalous.
    decision = float(package["pipeline"].decision_function(X)[0])
    anomaly_score = -decision

    anomaly = 1 if prediction == -1 else 0

    insight = build_insight(
        row,
        prediction,
        anomaly_score,
        package,
    )

    con.execute(
        """
        UPDATE readings
        SET ai_state = 'READY',
            anomaly = ?,
            anomaly_score = ?,
            insight = ?
        WHERE id = ?
        """,
        (anomaly, anomaly_score, insight, reading_id),
    )
    con.commit()

    status = "ANOMALY" if anomaly else "NORMAL"
    print(
        f"[AI] Latest row scored: {status}, "
        f"score={anomaly_score:.4f}"
    )


def count_valid_rows(con):
    return con.execute(
        """
        SELECT COUNT(*)
        FROM readings
        WHERE (status_flags & 1) = 1
          AND (status_flags & 2) = 2
        """
    ).fetchone()[0]


def rows_since_model_training(con, package):
    if package is None:
        return 10**9

    trained_at = package.get("trained_at")
    if not trained_at:
        return 10**9

    return con.execute(
        """
        SELECT COUNT(*)
        FROM readings
        WHERE received_at > ?
          AND (status_flags & 1) = 1
          AND (status_flags & 2) = 2
        """,
        (trained_at,),
    ).fetchone()[0]


def update_ai(con):
    valid_count = count_valid_rows(con)

    if valid_count < MIN_TRAIN_SAMPLES:
        con.execute(
            """
            UPDATE readings
            SET ai_state = 'LEARNING',
                insight = ?
            WHERE id = (SELECT MAX(id) FROM readings)
            """,
            (
                f"Collecting baseline data: {valid_count}/"
                f"{MIN_TRAIN_SAMPLES} valid readings.",
            ),
        )
        con.commit()
        print(
            f"[AI] Learning baseline "
            f"({valid_count}/{MIN_TRAIN_SAMPLES})."
        )
        return

    package = load_model()

    if (
        package is None
        or rows_since_model_training(con, package)
        >= RETRAIN_EVERY_NEW_ROWS
    ):
        train_df = valid_training_dataframe(con)
        package = train_model(train_df)

    score_latest(con, package)


def main():
    print("==========================================")
    print(" FYP Base Station Data + AI Service")
    print("==========================================")
    print(f"Serial port: {SERIAL_PORT}")
    print(f"Database:    {DATABASE_FILE}")
    print(f"Dataset:     {RAW_CSV_FILE}")
    print()

    con = db_connect()

    while True:
        try:
            print(
                f"[SERIAL] Connecting to {SERIAL_PORT} "
                f"at {SERIAL_BAUD}..."
            )

            with serial.Serial(
                SERIAL_PORT,
                SERIAL_BAUD,
                timeout=1,
            ) as ser:
                time.sleep(2)
                print("[SERIAL] Connected.")

                while True:
                    raw = ser.readline()

                    if not raw:
                        continue

                    line = raw.decode(
                        "utf-8",
                        errors="replace",
                    ).strip()

                    if not line:
                        continue

                    # Show receiver diagnostics in the terminal.
                    print(f"[RX] {line}")

                    if not line.startswith("DATA,"):
                        continue

                    try:
                        row = parse_data_line(line)
                    except Exception as exc:
                        print(f"[PARSE] Invalid DATA line: {exc}")
                        continue

                    if insert_reading(con, row):
                        print(
                            f"[DATA] Saved Node {row['node_id']} "
                            f"sequence {row['sequence_number']}."
                        )

                        update_ai(con)
                        export_csvs(con)
                    else:
                        print("[DATA] Duplicate ignored by database.")

        except serial.SerialException as exc:
            print(f"[SERIAL] {exc}")
            print("[SERIAL] Retrying in 5 seconds...")
            time.sleep(5)

        except KeyboardInterrupt:
            print("\nStopping base station.")
            break

        except Exception as exc:
            print(f"[ERROR] Unexpected error: {exc}")
            print("Retrying in 5 seconds...")
            time.sleep(5)

    con.close()


if __name__ == "__main__":
    main()
