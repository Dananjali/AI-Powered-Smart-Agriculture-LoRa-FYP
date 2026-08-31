"""
FYP Base Station Service

Runs continuously on the laptop.

Pipeline:
Receiver ESP32 serial
    -> parse DATA lines
    -> SQLite database
    -> automatically updated CSV dataset
    -> Isolation Forest scoring/retraining
    -> dashboard

This version does not record timestamps.

Packet sequence numbers may restart at 0 after a complete transmitter
power cycle. The base station therefore stores:
- sequence_number: genuine transmitter packet sequence
- session_id: acquisition session
- sample_index: continuous order across all stored samples

Install:
    pip install -r requirements.txt

Run:
    python base_station.py
"""

import sqlite3
import time
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

PACKET_COLUMNS = [
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

    existing_table = con.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='readings'"
    ).fetchone()

    if existing_table:
        columns = [
            row[1]
            for row in con.execute("PRAGMA table_info(readings)").fetchall()
        ]

        required_new_columns = {"sample_index", "session_id", "sequence_number"}

        if "received_at" in columns or not required_new_columns.issubset(columns):
            con.close()
            raise SystemExit(
                "\nOld/incompatible field_data.db detected.\n"
                "Delete field_data.db once, then run base_station.py again.\n"
                "A new session-aware database will be created automatically."
            )

        # An evaluation database created by load_dataset.py intentionally has
        # a different structure from the live collection database.
        if "id" not in columns:
            con.close()
            raise SystemExit(
                "\nThe current field_data.db is an evaluation database created by "
                "load_dataset.py.\n"
                "Do not append live packets to it. Delete field_data.db and "
                "isolation_forest.joblib before starting live collection."
            )

    con.execute(
        """
        CREATE TABLE IF NOT EXISTS readings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sample_index INTEGER NOT NULL UNIQUE,
            session_id INTEGER NOT NULL,
            test_phase TEXT NOT NULL DEFAULT 'live_monitoring',
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
            UNIQUE(node_id, session_id, sequence_number)
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
    if len(parts) != 1 + len(PACKET_COLUMNS):
        raise ValueError(
            f"Expected {1 + len(PACKET_COLUMNS)} CSV fields, got {len(parts)}"
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


def next_sample_index(con):
    row = con.execute(
        "SELECT MAX(sample_index) FROM readings"
    ).fetchone()

    if row is None or row[0] is None:
        return 0

    return int(row[0]) + 1


def determine_session_id(con, node_id, incoming_sequence):
    """
    A complete transmitter power cycle normally restarts the packet sequence at 0.

    If the latest stored packet for this node had a non-zero sequence and the new
    packet starts again at 0, open a new acquisition session. Otherwise preserve
    the current session.
    """
    row = con.execute(
        """
        SELECT session_id, sequence_number
        FROM readings
        WHERE node_id = ?
        ORDER BY id DESC
        LIMIT 1
        """,
        (node_id,),
    ).fetchone()

    if row is None:
        return 0

    last_session, last_sequence = int(row[0]), int(row[1])

    if int(incoming_sequence) == 0 and last_sequence > 0:
        return last_session + 1

    return last_session


def insert_reading(con, row):
    session_id = determine_session_id(
        con,
        row["node_id"],
        row["sequence_number"],
    )

    sample_index = next_sample_index(con)

    fields = [
        "sample_index",
        "session_id",
        "test_phase",
        *PACKET_COLUMNS,
    ]

    values = [
        sample_index,
        session_id,
        "live_monitoring",
        *[row[field] for field in PACKET_COLUMNS],
    ]

    placeholders = ",".join(["?"] * len(fields))

    try:
        con.execute(
            f"""
            INSERT INTO readings ({",".join(fields)})
            VALUES ({placeholders})
            """,
            values,
        )
        con.commit()
        return True, sample_index, session_id

    except sqlite3.IntegrityError:
        return False, None, session_id


def export_csvs(con):
    df = pd.read_sql_query(
        "SELECT * FROM readings ORDER BY sample_index ASC",
        con,
    )

    raw_columns = [
        "sample_index",
        "session_id",
        "test_phase",
        *PACKET_COLUMNS,
    ]

    df[raw_columns].to_csv(RAW_CSV_FILE, index=False)

    ai_export = df.drop(columns=["id"], errors="ignore")
    ai_export.to_csv(AI_CSV_FILE, index=False)


def valid_training_dataframe(con):
    df = pd.read_sql_query(
        """
        SELECT *
        FROM readings
        WHERE (status_flags & 1) = 1
          AND (status_flags & 2) = 2
        ORDER BY sample_index DESC
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
        "trained_through_sample_index": int(df["sample_index"].max()),
        "features": FEATURES,
    }

    joblib.dump(package, MODEL_FILE)

    print(
        f"[AI] Isolation Forest trained on {len(df)} rows "
        f"through sample {package['trained_through_sample_index']}."
    )

    return package


def load_model():
    if not Path(MODEL_FILE).exists():
        return None

    try:
        package = joblib.load(MODEL_FILE)

        # load_dataset.py saves a standalone evaluation pipeline.
        # Ignore it here and train the live base-station package instead.
        if not isinstance(package, dict) or "pipeline" not in package:
            return None

        return package

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
        "SELECT * FROM readings ORDER BY sample_index DESC LIMIT 1",
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

    trained_through = package.get("trained_through_sample_index")
    if trained_through is None:
        return 10**9

    return con.execute(
        """
        SELECT COUNT(*)
        FROM readings
        WHERE sample_index > ?
          AND (status_flags & 1) = 1
          AND (status_flags & 2) = 2
        """,
        (int(trained_through),),
    ).fetchone()[0]


def update_ai(con):
    valid_count = count_valid_rows(con)

    if valid_count < MIN_TRAIN_SAMPLES:
        con.execute(
            """
            UPDATE readings
            SET ai_state = 'LEARNING',
                insight = ?
            WHERE sample_index = (SELECT MAX(sample_index) FROM readings)
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
    print("Sample ordering: continuous sample index")
    print("Packet sequence: preserved per acquisition session")
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

                    print(f"[RX] {line}")

                    if not line.startswith("DATA,"):
                        continue

                    try:
                        row = parse_data_line(line)
                    except Exception as exc:
                        print(f"[PARSE] Invalid DATA line: {exc}")
                        continue

                    inserted, sample_index, session_id = insert_reading(con, row)

                    if inserted:
                        print(
                            f"[DATA] Saved sample {sample_index}: "
                            f"Node {row['node_id']}, "
                            f"session {session_id}, "
                            f"packet sequence {row['sequence_number']}."
                        )

                        update_ai(con)
                        export_csvs(con)
                    else:
                        print("[DATA] Duplicate ignored within the current session.")

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
