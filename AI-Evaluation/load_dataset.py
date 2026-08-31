
from pathlib import Path
import sqlite3
import joblib
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.impute import SimpleImputer
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

CSV_FILE = "homagama_chilli_field_monitor_3km_evaluation.csv"
DB_FILE = "field_data.db"
MODEL_FILE = "isolation_forest.joblib"

FEATURES = [
    "soil_moisture","soil_temperature","ec","ph",
    "nitrogen","phosphorus","potassium",
    "air_temperature","humidity"
]

df = pd.read_csv(CSV_FILE)

for name in [DB_FILE, MODEL_FILE]:
    p = Path(name)
    if p.exists():
        p.unlink()

normal = df[df["evaluation_label"] == 0].copy()

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

# Plain-language AI insight for each row.
def insight(row):
    if int(row["anomaly"]) == 1:
        return "Unusual combination of field measurements detected compared with the learned baseline."
    return "Measurements are consistent with the learned field baseline."

df["insight"] = df.apply(insight, axis=1)

con = sqlite3.connect(DB_FILE)
df.to_sql("readings", con, if_exists="replace", index=False)
con.close()
joblib.dump(model, MODEL_FILE)

truth = df["evaluation_label"].astype(int)
pred = df["anomaly"].astype(int)
tp = int(((truth==1)&(pred==1)).sum())
tn = int(((truth==0)&(pred==0)).sum())
fp = int(((truth==0)&(pred==1)).sum())
fn = int(((truth==1)&(pred==0)).sum())
precision = tp/(tp+fp) if tp+fp else 0
recall = tp/(tp+fn) if tp+fn else 0
f1 = 2*precision*recall/(precision+recall) if precision+recall else 0
accuracy = (tp+tn)/len(df)
specificity = tn/(tn+fp) if tn+fp else 0
balanced_accuracy = (recall + specificity)/2

print(f"Loaded rows: {len(df)}")
print(f"Evaluation anomaly rows: {int(truth.sum())}")
print(f"Detected anomaly rows: {int(pred.sum())}")
print(f"Accuracy:          {accuracy:.3f}")
print(f"Balanced Accuracy: {balanced_accuracy:.3f}")
print(f"Precision:         {precision:.3f}")
print(f"Recall:    {recall:.3f}")
print(f"F1 score:  {f1:.3f}")
print()
print("Now run:")
print("python -m streamlit run dashboard.py --server.address 0.0.0.0")
