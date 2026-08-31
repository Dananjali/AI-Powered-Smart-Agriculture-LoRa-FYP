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

top1, top2 = st.columns([5, 1])
with top2:
    if st.button("🔄 Refresh data", use_container_width=True):
        st.rerun()

if not Path(DB_FILE).exists():
    st.warning("No field database found. Run the data loader or base-station service first.")
    st.stop()

con = sqlite3.connect(DB_FILE)
df = pd.read_sql_query("SELECT * FROM readings", con)
con.close()

if df.empty:
    st.info("Waiting for readings.")
    st.stop()

if "sequence_number" not in df.columns:
    st.error("The database does not contain a sequence_number column.")
    st.stop()

df["sequence_number"] = pd.to_numeric(df["sequence_number"], errors="coerce")
df = df.dropna(subset=["sequence_number"]).copy()

if df.empty:
    st.error("No valid sequence numbers were found in the database.")
    st.stop()

# sample_index is the continuous plotting/order index across all acquisition sessions.
# It is intentionally separate from the transmitter packet sequence, which may reset
# to 0 after a complete power cycle.
if "sample_index" not in df.columns:
    if "id" in df.columns:
        df = df.sort_values("id").reset_index(drop=True)
    else:
        df = df.reset_index(drop=True)
    df["sample_index"] = range(len(df))

df["sample_index"] = pd.to_numeric(df["sample_index"], errors="coerce")
df = df.dropna(subset=["sample_index"]).copy()
df = df.sort_values("sample_index").reset_index(drop=True)

# Evaluation datasets can identify field/home phases. Live collection databases
# use a generic live session label unless the user later assigns a phase.
if "test_phase" not in df.columns:
    if "session_id" in df.columns:
        df["test_phase"] = df["session_id"].apply(lambda x: f"session_{int(x) + 1}")
    else:
        df["test_phase"] = "monitoring"

phase_values = [str(x) for x in df["test_phase"].dropna().unique().tolist()]
phase_options = ["All data"] + phase_values

selected_phase = st.selectbox(
    "Monitoring phase",
    phase_options,
    index=0,
)

if selected_phase == "All data":
    view_df = df.copy()
else:
    view_df = df[df["test_phase"].astype(str) == selected_phase].copy()

if view_df.empty:
    st.warning("No data is available for the selected monitoring phase.")
    st.stop()

view_df = view_df.sort_values("sample_index").reset_index(drop=True)
latest = view_df.iloc[-1]


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

    if ph < 5.5:
        alerts.append(("warning", "Soil pH is too acidic for the preferred chilli range"))
        actions.append("Confirm pH with a soil test before making a liming correction.")
    elif ph > 6.8:
        alerts.append(("warning", "Soil pH is above the preferred chilli range"))
        actions.append("Confirm the reading and review soil amendments/fertilizer practices.")

    if ec > 1500:
        alerts.append(("warning", "Electrical conductivity is unusually high"))
        actions.append("Check for fertilizer/salt concentration and verify with a soil test if it persists.")

    low_nutrients = []
    if n < 40:
        low_nutrients.append("nitrogen (N)")
    if p < 35:
        low_nutrients.append("phosphorus (P)")
    if k < 125:
        low_nutrients.append("potassium (K)")

    if low_nutrients:
        alerts.append(("warning", "Nutrient readings are low: " + ", ".join(low_nutrients)))
        actions.append(
            "Review the fertilizer plan for this patch and confirm with a soil/lab test "
            "before applying additional fertilizer."
        )

    if at > 32:
        alerts.append(("warning", "Air temperature is high"))
        actions.append("Watch for heat stress and ensure adequate root-zone moisture.")

    if rh > 92:
        alerts.append(("info", "Humidity is very high"))
        actions.append(
            "Inspect foliage regularly because prolonged high humidity can favour disease development."
        )

    if not alerts:
        return "good", ["Field conditions are within the current advisory bands."], [
            "Continue normal monitoring and follow the existing irrigation and fertilizer schedule."
        ]

    severity_rank = {"info": 1, "warning": 2, "urgent": 3}
    overall = max((a[0] for a in alerts), key=lambda x: severity_rank[x])
    return overall, [a[1] for a in alerts], list(dict.fromkeys(actions))


overall, messages, actions = farmer_advice(latest)

if overall == "good":
    st.success("✅ FIELD STATUS: Conditions look good")
elif overall == "urgent":
    st.error("🚨 FIELD STATUS: Action recommended")
else:
    st.warning("⚠️ FIELD STATUS: Attention recommended")

left, right = st.columns([2, 1])

with left:
    st.subheader("What the farmer should know")
    for message in messages:
        st.write("• " + message)

    st.markdown("**Recommended next steps**")
    for action in actions:
        st.write("• " + action)

    if int(latest.get("anomaly", 0)) == 1:
        st.warning("AI check: this reading pattern is unusual compared with the learned baseline.")
    else:
        st.info("AI check: this reading pattern is consistent with the learned baseline.")

with right:
    st.subheader("System & Link Health")

    rssi = pd.to_numeric(pd.Series([latest.get("rssi")]), errors="coerce").iloc[0]
    snr = pd.to_numeric(pd.Series([latest.get("snr")]), errors="coerce").iloc[0]

    if pd.notna(rssi) and pd.notna(snr):
        if rssi > -110 and snr > -5:
            link = "Good"
        elif rssi > -120 and snr > -10:
            link = "Usable"
        else:
            link = "Weak / marginal"

        st.metric("LoRa link", link)
        st.write(f"RSSI: **{rssi:.0f} dBm**")
        st.write(f"SNR: **{snr:.1f} dB**")
    else:
        st.metric("LoRa link", "No link data")
        st.write("RSSI: **N/A**")
        st.write("SNR: **N/A**")

    if "node_id" in latest.index and pd.notna(latest["node_id"]):
        st.write(f"Node: **{int(latest['node_id'])}**")

    st.write(f"Packet sequence: **{int(latest['sequence_number'])}**")
    st.write(f"Overall sample: **{int(latest['sample_index'])}**")

st.divider()

st.subheader("Latest Sensor Readings")
c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Soil moisture", f"{latest['soil_moisture']:.1f} %")
c2.metric("Soil temperature", f"{latest['soil_temperature']:.1f} °C")
c3.metric("Soil pH", f"{latest['ph']:.2f}")
c4.metric("Air temperature", f"{latest['air_temperature']:.1f} °C")
c5.metric("Humidity", f"{latest['humidity']:.1f} %")

c6, c7, c8, c9 = st.columns(4)
c6.metric("EC", f"{latest['ec']:.0f} µS/cm")
c7.metric("Nitrogen (N)", f"{latest['nitrogen']:.0f}")
c8.metric("Phosphorus (P)", f"{latest['phosphorus']:.0f}")
c9.metric("Potassium (K)", f"{latest['potassium']:.0f}")

st.caption(
    f"Selected phase: {latest['test_phase']} | "
    f"Packet sequence: {int(latest['sequence_number'])} | "
    f"Overall sample index: {int(latest['sample_index'])}"
)

st.divider()

st.subheader("Trends")

window_label = st.selectbox(
    "Samples to display",
    ["Last 50", "Last 100", "Last 250", "Last 500", "All samples"],
    index=4,
)

window_map = {
    "Last 50": 50,
    "Last 100": 100,
    "Last 250": 250,
    "Last 500": 500,
}

if window_label == "All samples":
    recent = view_df.copy()
else:
    recent = view_df.tail(window_map[window_label]).copy()

recent = recent.sort_values("sample_index")

st.markdown("**Soil moisture & humidity**")
st.line_chart(
    recent.set_index("sample_index")[["soil_moisture", "humidity"]]
)

st.markdown("**Temperature**")
st.line_chart(
    recent.set_index("sample_index")[["soil_temperature", "air_temperature"]]
)

st.markdown("**Soil chemistry**")
st.line_chart(
    recent.set_index("sample_index")[["ph", "ec"]]
)

st.markdown("**Nutrient readings**")
st.line_chart(
    recent.set_index("sample_index")[["nitrogen", "phosphorus", "potassium"]]
)

st.caption(
    "Trend-chart x-axis: continuous sample index. "
    "Packet sequence numbers may restart after a complete transmitter power cycle."
)

st.divider()

st.subheader("AI Model Evaluation")
if "evaluation_label" in view_df.columns and "anomaly" in view_df.columns:
    eval_df = view_df.dropna(subset=["evaluation_label", "anomaly"]).copy()

    if not eval_df.empty:
        truth = eval_df["evaluation_label"].astype(int)
        pred = eval_df["anomaly"].astype(int)

        tp = int(((truth == 1) & (pred == 1)).sum())
        tn = int(((truth == 0) & (pred == 0)).sum())
        fp = int(((truth == 0) & (pred == 1)).sum())
        fn = int(((truth == 1) & (pred == 0)).sum())

        accuracy = (tp + tn) / len(eval_df) if len(eval_df) else 0
        precision = tp / (tp + fp) if tp + fp else 0
        recall = tp / (tp + fn) if tp + fn else 0
        specificity = tn / (tn + fp) if tn + fp else 0
        balanced_accuracy = (recall + specificity) / 2
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0

        a, b, c, d = st.columns(4)
        a.metric("Overall Accuracy", f"{accuracy * 100:.1f}%")
        b.metric("Balanced Accuracy", f"{balanced_accuracy * 100:.1f}%")
        c.metric("Anomaly Recall", f"{recall * 100:.1f}%")
        d.metric("F1 Score", f"{f1 * 100:.1f}%")

        st.caption(
            "Performance shown here is based on the labelled evaluation records "
            "available for the selected monitoring phase."
        )

st.divider()

with st.expander("Detailed data"):
    detail_cols = [
        "sample_index",
        "test_phase",
        "session_id",
        "node_id",
        "sequence_number",
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
        "anomaly",
        "anomaly_score",
    ]
    present = [c for c in detail_cols if c in view_df.columns]
    detail = view_df[present].sort_values("sample_index", ascending=False)
    st.dataframe(detail, use_container_width=True, height=500)

st.caption(
    "Prototype dashboard. Agronomic messages are decision-support prompts; "
    "confirm major fertilizer or soil-correction decisions with field inspection "
    "and appropriate soil testing."
)
