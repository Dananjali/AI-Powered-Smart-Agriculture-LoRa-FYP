"""
Load the combined field/home evaluation dataset into field_data.db and
run the Isolation Forest.

Design:
- sequence_number is the genuine packet sequence produced by the transmitter.
- sequence_number may restart at 0 after a complete transmitter power cycle.
- sample_index is created automatically and remains continuous across the full
  combined dataset so dashboard graphs preserve the original row order.
- If test_phase is not already present, the first sequence-number reset is used
  to separate field_evaluation from home_monitoring.

No timestamp is required.

Usage:
    python load_dataset.py
or:
    python load_dataset.py your_dataset.csv
or:
    python load_dataset.py your_dataset.xlsx
"""

import sys
from pathlib import Path
import sqlite3

import joblib
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.impute import SimpleImputer
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

DB_FILE = "field_data.db"
MODEL_FILE = "isolation_forest.joblib"

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

GENERATED_NAMES = {
    "field_data.csv",
    "field_data_with_ai.csv",
}


def choose_dataset():
    if len(sys.argv) > 1:
        path = Path(sys.argv[1])
        if not path.exists():
            raise SystemExit(f"Could not find dataset: {path}")
        return path

    preferred = [
        Path("Field+HomeEvaluationDataset.xlsx"),
        Path("Field_HomeEvaluationDataset.xlsx"),
        Path("field_home_evaluation_dataset.xlsx"),
        Path("field_home_evaluation_dataset.csv"),
        Path("evaluation_dataset.csv"),
    ]

    for path in preferred:
        if path.exists():
            return path

    candidates = []
    for pattern in ("*.csv", "*.xlsx"):
        for path in Path(".").glob(pattern):
            if path.name not in GENERATED_NAMES:
                candidates.append(path)

    candidates = sorted(set(candidates))

    if len(candidates) == 1:
        return candidates[0]

    if not candidates:
        raise SystemExit(
            "No dataset found. Put the CSV/XLSX in this folder or run:\n"
            "python load_dataset.py your_dataset.xlsx"
        )

    names = "\n".join(f"  - {p.name}" for p in candidates)
    raise SystemExit(
        "More than one possible dataset was found.\n"
        "Run the loader with the file you want, for example:\n"
        "python load_dataset.py your_dataset.xlsx\n\n"
        f"Available files:\n{names}"
    )


def read_dataset(path):
    suffix = path.suffix.lower()

    if suffix == ".csv":
        return pd.read_csv(path)

    if suffix == ".xlsx":
        return pd.read_excel(path)

    raise SystemExit("Dataset must be a .csv or .xlsx file.")


def infer_test_phases(sequence_numbers):
    """
    First acquisition session = field_evaluation.
    The first genuine sequence reset = home_monitoring.
    Any additional resets are labelled session_3, session_4, ...
    """
    phases = []
    current_phase = "field_evaluation"
    session_number = 1
    previous = None

    for seq in sequence_numbers:
        seq = int(seq)

        if previous is not None and seq < previous:
            session_number += 1
            if session_number == 2:
                current_phase = "home_monitoring"
            else:
                current_phase = f"session_{session_number}"

        phases.append(current_phase)
        previous = seq

    return phases


dataset_path = choose_dataset()
df = read_dataset(dataset_path)

# Remove old time columns if they are still present.
for time_column in ("received_at", "timestamp"):
    if time_column in df.columns:
        df = df.drop(columns=[time_column])

required = ["sequence_number", "evaluation_label", *FEATURES]
missing = [column for column in required if column not in df.columns]
if missing:
    raise SystemExit(
        "Dataset is missing required columns:\n  - "
        + "\n  - ".join(missing)
    )

# Preserve the spreadsheet/CSV row order exactly.
df["sequence_number"] = pd.to_numeric(df["sequence_number"], errors="coerce")
df = df.dropna(subset=["sequence_number"]).reset_index(drop=True)

if "node_id" not in df.columns:
    df["node_id"] = 1

# Continuous order across all sessions. Do not manually create this column.
df["sample_index"] = range(len(df))

# Keep an explicit acquisition session number as well.
session_ids = []
session_id = 0
previous = None

for seq in df["sequence_number"]:
    seq = int(seq)
    if previous is not None and seq < previous:
        session_id += 1
    session_ids.append(session_id)
    previous = seq

df["session_id"] = session_ids

# If the user did not manually provide phase labels, infer them from the
# first sequence reset.
if "test_phase" not in df.columns:
    df["test_phase"] = infer_test_phases(df["sequence_number"])

for name in (DB_FILE, MODEL_FILE):
    path = Path(name)
    if path.exists():
        path.unlink()

normal = df[df["evaluation_label"] == 0].copy()

if normal.empty:
    raise SystemExit(
        "No normal baseline rows were found. evaluation_label must use 0 for normal rows."
    )

model = Pipeline([
    ("imputer", SimpleImputer(strategy="median")),
    ("scaler", StandardScaler()),
    ("isolation_forest", IsolationForest(
        n_estimators=400,
        contamination=0.04,
        random_state=42,
        n_jobs=-1,
    )),
])

model.fit(normal[FEATURES])

df["anomaly"] = (model.predict(df[FEATURES]) == -1).astype(int)
df["anomaly_score"] = -model.decision_function(df[FEATURES])
df["ai_state"] = "READY"


def insight(row):
    if int(row["anomaly"]) == 1:
        return (
            "Unusual combination of field measurements detected compared "
            "with the learned baseline."
        )
    return "Measurements are consistent with the learned field baseline."


df["insight"] = df.apply(insight, axis=1)

con = sqlite3.connect(DB_FILE)
df.to_sql("readings", con, if_exists="replace", index=False)
con.close()

joblib.dump(model, MODEL_FILE)

truth = df["evaluation_label"].astype(int)
pred = df["anomaly"].astype(int)

tp = int(((truth == 1) & (pred == 1)).sum())
tn = int(((truth == 0) & (pred == 0)).sum())
fp = int(((truth == 0) & (pred == 1)).sum())
fn = int(((truth == 1) & (pred == 0)).sum())

precision = tp / (tp + fp) if tp + fp else 0
recall = tp / (tp + fn) if tp + fn else 0
f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0
accuracy = (tp + tn) / len(df)
specificity = tn / (tn + fp) if tn + fp else 0
balanced_accuracy = (recall + specificity) / 2

print(f"Dataset: {dataset_path.name}")
print(f"Loaded rows: {len(df)}")
print(f"Overall sample index: 0 to {len(df) - 1}")
print()

phase_summary = (
    df.groupby("test_phase", sort=False)
    .agg(
        rows=("sample_index", "count"),
        first_sample=("sample_index", "min"),
        last_sample=("sample_index", "max"),
        first_sequence=("sequence_number", "first"),
        last_sequence=("sequence_number", "last"),
    )
)

print("Detected monitoring phases:")
print(phase_summary.to_string())
print()

print(f"Evaluation anomaly rows: {int(truth.sum())}")
print(f"Detected anomaly rows: {int(pred.sum())}")
print(f"Accuracy:          {accuracy:.3f}")
print(f"Balanced Accuracy: {balanced_accuracy:.3f}")
print(f"Precision:         {precision:.3f}")
print(f"Recall:            {recall:.3f}")
print(f"F1 score:          {f1:.3f}")
print()
print("Now run:")
print("python -m streamlit run dashboard.py --server.address 0.0.0.0")
