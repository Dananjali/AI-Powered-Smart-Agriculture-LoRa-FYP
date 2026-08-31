
from pathlib import Path
import sqlite3
import pandas as pd
import streamlit as st

DB_FILE = "field_data.db"

st.set_page_config(
    page_title="Smart Chilli Field Monitor",
    page_icon="🌶️",
    layout="wide",
)

st.title("🌶️ Smart Chilli Field Monitor")
st.caption("LoRa field monitoring with AI-assisted crop-condition alerts")

top1, top2 = st.columns([5,1])
with top2:
    if st.button("🔄 Refresh data", use_container_width=True):
        st.rerun()

if not Path(DB_FILE).exists():
    st.warning("No field database found. Run the data loader or base-station service first.")
    st.stop()

con = sqlite3.connect(DB_FILE)
df = pd.read_sql_query("SELECT * FROM readings ORDER BY received_at ASC", con)
con.close()

if df.empty:
    st.info("Waiting for readings.")
    st.stop()

df["received_at"] = pd.to_datetime(df["received_at"], utc=True, errors="coerce")
latest = df.iloc[-1]

def farmer_advice(row):
    alerts = []
    actions = []

    m = float(row["soil_moisture"])
    ph = float(row["ph"])
    ec = float(row["ec"])
    n = float(row["nitrogen"])
    p = float(row["phosphorus"])
    k = float(row["potassium"])
    at = float(row["air_temperature"])
    rh = float(row["humidity"])

    # Soil moisture: prototype advisory bands informed by chilli moisture studies.
    if m < 18:
        alerts.append(("urgent", "Soil moisture is very low"))
        actions.append("Check irrigation and inspect plants for water stress.")
    elif m < 23:
        alerts.append(("warning", "Soil moisture is below the preferred evaluation band"))
        actions.append("Consider irrigation if the root zone is genuinely dry.")
    elif m > 45:
        alerts.append(("urgent", "Root zone appears excessively wet"))
        actions.append("Check drainage and avoid additional irrigation until the root zone drains.")
    elif m > 38:
        alerts.append(("warning", "Soil moisture is high"))
        actions.append("Monitor drainage, especially after rain.")

    # DOA Sri Lanka preferred Capsicum/chilli soil pH: 5.5-6.8.
    if ph < 5.5:
        alerts.append(("warning", "Soil pH is too acidic for the preferred chilli range"))
        actions.append("Confirm pH with a soil test before making a liming correction.")
    elif ph > 6.8:
        alerts.append(("warning", "Soil pH is above the preferred chilli range"))
        actions.append("Confirm the reading and review soil amendments/fertilizer practices.")

    # EC is kept conservative because direct-probe EC is method-dependent.
    if ec > 1500:
        alerts.append(("warning", "Electrical conductivity is unusually high"))
        actions.append("Check for fertilizer/salt concentration and verify with a soil test if it persists.")

    # NPK are sensor-based relative advisory bands, not fertilizer-dose prescriptions.
    low_nutrients = []
    if n < 40: low_nutrients.append("nitrogen (N)")
    if p < 35: low_nutrients.append("phosphorus (P)")
    if k < 125: low_nutrients.append("potassium (K)")
    if low_nutrients:
        alerts.append(("warning", "Nutrient readings are low: " + ", ".join(low_nutrients)))
        actions.append("Review the fertilizer plan for this patch and confirm with a soil/lab test before applying additional fertilizer.")

    if at > 32:
        alerts.append(("warning", "Air temperature is high"))
        actions.append("Watch for heat stress and ensure adequate root-zone moisture.")

    if rh > 92:
        alerts.append(("info", "Humidity is very high"))
        actions.append("Inspect foliage regularly because prolonged high humidity can favour disease development.")

    if not alerts:
        return "good", ["Field conditions are within the current advisory bands."], [
            "Continue normal monitoring and follow the existing irrigation and fertilizer schedule."
        ]

    severity_rank = {"info":1, "warning":2, "urgent":3}
    overall = max((a[0] for a in alerts), key=lambda x: severity_rank[x])
    return overall, [a[1] for a in alerts], list(dict.fromkeys(actions))

overall, messages, actions = farmer_advice(latest)

if overall == "good":
    st.success("✅ FIELD STATUS: Conditions look good")
elif overall == "urgent":
    st.error("🚨 FIELD STATUS: Action recommended")
else:
    st.warning("⚠️ FIELD STATUS: Attention recommended")

left, right = st.columns([2,1])

with left:
    st.subheader("What the farmer should know")
    for m in messages:
        st.write("• " + m)

    st.markdown("**Recommended next steps**")
    for a in actions:
        st.write("• " + a)

    if int(latest.get("anomaly", 0)) == 1:
        st.warning("AI check: this reading pattern is unusual compared with the learned baseline.")
    else:
        st.info("AI check: this reading pattern is consistent with the learned baseline.")

with right:
    st.subheader("System & Link Health")
    rssi = float(latest["rssi"])
    snr = float(latest["snr"])
    if rssi > -110 and snr > -5:
        link = "Good"
    elif rssi > -120 and snr > -10:
        link = "Usable"
    else:
        link = "Weak / marginal"

    st.metric("LoRa link", link)
    st.write(f"RSSI: **{rssi:.0f} dBm**")
    st.write(f"SNR: **{snr:.1f} dB**")
    if "link_distance_m" in latest:
        st.write(f"Evaluation distance: **{float(latest['link_distance_m'])/1000:.1f} km**")
    st.write(f"Node: **{int(latest['node_id'])}**")
    st.write(f"Sequence: **{int(latest['sequence_number'])}**")

st.divider()

st.subheader("Latest Sensor Readings")
c1,c2,c3,c4,c5 = st.columns(5)
c1.metric("Soil moisture", f"{latest['soil_moisture']:.1f} %")
c2.metric("Soil temperature", f"{latest['soil_temperature']:.1f} °C")
c3.metric("Soil pH", f"{latest['ph']:.2f}")
c4.metric("Air temperature", f"{latest['air_temperature']:.1f} °C")
c5.metric("Humidity", f"{latest['humidity']:.1f} %")

c6,c7,c8,c9 = st.columns(4)
c6.metric("EC", f"{latest['ec']:.0f} µS/cm")
c7.metric("Nitrogen (N)", f"{latest['nitrogen']:.0f}")
c8.metric("Phosphorus (P)", f"{latest['phosphorus']:.0f}")
c9.metric("Potassium (K)", f"{latest['potassium']:.0f}")

st.caption(f"Latest timestamp: {latest['received_at']}")

st.divider()

st.subheader("Trends")
days = st.selectbox("History window", [1,2,3,7], index=3, format_func=lambda x: f"Last {x} day" if x==1 else f"Last {x} days")
cutoff = df["received_at"].max() - pd.Timedelta(days=days)
recent = df[df["received_at"] >= cutoff].copy()

st.markdown("**Soil moisture & humidity**")
st.line_chart(recent.set_index("received_at")[["soil_moisture","humidity"]])

st.markdown("**Temperature**")
st.line_chart(recent.set_index("received_at")[["soil_temperature","air_temperature"]])

st.markdown("**Soil chemistry**")
st.line_chart(recent.set_index("received_at")[["ph","ec"]])

st.markdown("**Nutrient readings**")
st.line_chart(recent.set_index("received_at")[["nitrogen","phosphorus","potassium"]])

st.divider()

st.subheader("AI Model Evaluation")
if "evaluation_label" in df.columns:
    truth = df["evaluation_label"].fillna(0).astype(int)
    pred = df["anomaly"].fillna(0).astype(int)

    tp = int(((truth==1)&(pred==1)).sum())
    tn = int(((truth==0)&(pred==0)).sum())
    fp = int(((truth==0)&(pred==1)).sum())
    fn = int(((truth==1)&(pred==0)).sum())

    accuracy = (tp+tn)/len(df) if len(df) else 0
    precision = tp/(tp+fp) if tp+fp else 0
    recall = tp/(tp+fn) if tp+fn else 0
    specificity = tn/(tn+fp) if tn+fp else 0
    balanced_accuracy = (recall + specificity)/2
    f1 = 2*precision*recall/(precision+recall) if precision+recall else 0

    a,b,c,d = st.columns(4)
    a.metric("Overall Accuracy", f"{accuracy*100:.1f}%")
    b.metric("Balanced Accuracy", f"{balanced_accuracy*100:.1f}%")
    c.metric("Anomaly Recall", f"{recall*100:.1f}%")
    d.metric("F1 Score", f"{f1*100:.1f}%")

    st.caption(
        "Performance shown here is from the controlled model-evaluation dataset. "
        "Overall and balanced accuracy are shown separately so the large number of normal readings does not hide anomaly-detection errors."
    )

st.divider()

with st.expander("Detailed data"):
    detail_cols = [
        "received_at","node_id","sequence_number","soil_moisture","soil_temperature",
        "ec","ph","nitrogen","phosphorus","potassium","air_temperature","humidity",
        "rssi","snr","anomaly","anomaly_score"
    ]
    present = [c for c in detail_cols if c in df.columns]
    st.dataframe(df[present].sort_values("received_at", ascending=False), use_container_width=True, height=500)

st.caption(
    "Prototype dashboard. Agronomic messages are decision-support prompts; confirm major fertilizer or soil-correction decisions with field inspection and appropriate soil testing."
)
