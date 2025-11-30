# Bereinigte Version des Skripts
# - Kein LabelEncoder mehr
# - Edge-ID-Mapping wird aus CSV erzeugt und gespeichert
# - Mapping wird beim Netz-Scan geladen
# - Unbekannte Edges werden übersprungen

import os
import math
import joblib
import numpy as np
import pandas as pd
import torch
import torch.nn as nn
from torch.utils.data import DataLoader, TensorDataset
from sklearn.cluster import KMeans

import matplotlib.pyplot as plt
import plotly.express as px

import sumolib

# ============================================================
# 0) KONFIGURATION
# ============================================================

CSV_LOG_FILE = "model_log_data.csv"
NET_FILE = "osm.net.xml.gz"

MODEL_FILE = "charging_model.pt"
MAPPING_FILE = "edge_mapping.pkl"
XML_FILE = "generated_charging.add.xml"

LANE_SAMPLE_STEP = 10.0
TOP_N_LOCATIONS = 30
TRAIN_EPOCHS = 40
DEVICE = "cpu"

GENERATE_HEATMAP = True
GENERATE_PLOTLY = True
USE_CLUSTERING = True
NUM_CLUSTERS = 10
DO_ROUTE_ANALYSIS = True


# ============================================================
# 1) NEURONALES NETZ
# ============================================================

class ChargingNet(nn.Module):
    def __init__(self):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(7, 64),
            nn.ReLU(),
            nn.Linear(64, 32),
            nn.ReLU(),
            nn.Linear(32, 1),
            nn.Sigmoid()
        )

    def forward(self, x):
        return self.net(x)


# ============================================================
# 2) TRAINING
# ============================================================

def train_ml_model():
    print(f"Trainiere Modell auf {CSV_LOG_FILE}")

    df = pd.read_csv(CSV_LOG_FILE)
    print(df)

    # Mapping aus CSV extrahieren
    print("Baue Edge-ID-Mapping auf ...")
    edge_mapping = {}

    for eid, enc in zip(df["edge_id"], df["edge_id_enc"]):
        if eid not in edge_mapping:
            edge_mapping[eid] = int(enc)

    joblib.dump(edge_mapping, MAPPING_FILE)
    print(f"Mapping gespeichert: {MAPPING_FILE} (Einträge: {len(edge_mapping)})")

    # Features
    X = df[["x", "y", "lane_offset", "speed", "soc", "is_charging", "edge_id_enc"]].values
    y = df[["charging_score"]].values

    X_tensor = torch.tensor(X, dtype=torch.float32)
    y_tensor = torch.tensor(y, dtype=torch.float32)

    dataset = TensorDataset(X_tensor, y_tensor)
    loader = DataLoader(dataset, batch_size=256, shuffle=True)

    model = ChargingNet().to(DEVICE)
    opt = torch.optim.Adam(model.parameters(), lr=0.001)
    loss_fn = nn.MSELoss()

    for epoch in range(TRAIN_EPOCHS):
        for xb, yb in loader:
            xb = xb.to(DEVICE)
            yb = yb.to(DEVICE)
            pred = model(xb)
            loss = loss_fn(pred, yb)

            opt.zero_grad()
            loss.backward()
            opt.step()

        print(f"Epoch {epoch+1}/{TRAIN_EPOCHS}, loss={loss.item():.4f}")

    torch.save(model.state_dict(), MODEL_FILE)
    print(f"Modell gespeichert unter {MODEL_FILE}")


# ============================================================
# 3) NETZ SCHÄTZEN / LOCATION-SCORING
# ============================================================

def scan_network_and_score():
    print(f"Lese Netz: {NET_FILE}")
    net = sumolib.net.readNet(NET_FILE)

    print(f"Lade Modell: {MODEL_FILE}")
    model = ChargingNet().to(DEVICE)
    model.load_state_dict(torch.load(MODEL_FILE, map_location=DEVICE))
    model.eval()

    print(f"Lade Edge-ID-Mapping: {MAPPING_FILE}")
    edge_mapping = joblib.load(MAPPING_FILE)

    scored_positions = []

    for lane_id in net.getLaneIDs():
        lane = net.getLane(lane_id)
        length = lane.getLength()
        edge = lane.getEdge().getID()

        # Falls Edge nicht im Mapping ist: skip
        if edge not in edge_mapping:
            continue

        edge_enc = edge_mapping[edge]

        d = 0.0
        while d < length:
            x, y = lane.getPositionAt(d)

            speed = lane.getSpeed()
            soc = 0.5
            is_charging = 0

            feat = torch.tensor([[x, y, d, speed, soc, is_charging, edge_enc]],
                                dtype=torch.float32, device=DEVICE)

            with torch.no_grad():
                score = model(feat).item()

            scored_positions.append((score, x, y, lane_id, d))
            d += LANE_SAMPLE_STEP

    print(f"Bewertete Positionen: {len(scored_positions)}")
    return scored_positions


# ============================================================
# 4) STANDORTE AUSWÄHLEN
# ============================================================

def select_top_locations(scored_positions):
    scored_positions.sort(reverse=True, key=lambda x: x[0])

    if USE_CLUSTERING:
        print("Wende KMeans-Clustering an ...")
        top_for_cluster = scored_positions[:NUM_CLUSTERS * 5]
        coords = np.array([[p[1], p[2]] for p in top_for_cluster])

        kmeans = KMeans(n_clusters=NUM_CLUSTERS, n_init=10)
        kmeans.fit(coords)
        centers = kmeans.cluster_centers_()

        cluster_best = []
        for cx, cy in centers:
            best = None
            best_dist = 9999999
            for s, x, y, lane_id, d in scored_positions:
                dist = math.hypot(x - cx, y - cy)
                if dist < best_dist:
                    best = (s, x, y, lane_id, d)
                    best_dist = dist
            cluster_best.append(best)

        cluster_best.sort(reverse=True, key=lambda x: x[0])

        if len(cluster_best) < TOP_N_LOCATIONS:
            needed = TOP_N_LOCATIONS - len(cluster_best)
            cluster_best.extend(scored_positions[:needed])

        selected = cluster_best[:TOP_N_LOCATIONS]

    else:
        selected = scored_positions[:TOP_N_LOCATIONS]

    print("Ausgewählte Standorte:")
    for s, x, y, lane_id, d in selected:
        print(f"Score={s:.3f}  ({x:.1f}, {y:.1f})  lane={lane_id}, offset={d:.1f}")

    return selected


# ============================================================
# 5) XML GENERIEREN
# ============================================================

def generate_charging_xml(best_locations):
    with open(XML_FILE, "w", encoding="utf-8") as f:
        f.write("<additional>\n")
        for i, (score, x, y, lane_id, offset) in enumerate(best_locations):
            start_pos = max(offset - 2.0, 0.0)
            end_pos = offset + 2.0

            f.write(
                f'  <chargingStation id="cs_{i}" lane="{lane_id}" '
                f'startPos="{start_pos:.2f}" endPos="{end_pos:.2f}" '
                f'power="22000" efficiency="1.0"/>\n'
            )
        f.write("</additional>\n")

    print(f"XML generiert: {XML_FILE}")


# ============================================================
# 6) VISUALISIERUNG
# ============================================================

def create_heatmap(scored_positions):
    xs = [p[1] for p in scored_positions]
    ys = [p[2] for p in scored_positions]
    scores = [p[0] for p in scored_positions]

    plt.figure(figsize=(8,6))
    sc = plt.scatter(xs, ys, c=scores, s=4)
    plt.colorbar(sc, label="Score")
    plt.title("Charging Suitability Heatmap")
    plt.xlabel("x")
    plt.ylabel("y")
    plt.tight_layout()
    plt.savefig("heatmap.png", dpi=200)
    plt.close()

    print("Heatmap gespeichert: heatmap.png")


def create_plotly_viewer(scored_positions):
    df = pd.DataFrame([{ "score": p[0], "x": p[1], "y": p[2], "lane_id": p[3], "offset": p[4] } for p in scored_positions])

    fig = px.scatter(
        df, x="x", y="y", color="score",
        hover_data=["lane_id", "offset"],
        title="Charging Suitability"
    )
    fig.write_html("charging_map.html")

    print("Plotly Viewer gespeichert: charging_map.html")


# ============================================================
# 7) ROUTENANALYSE (optional)
# ============================================================

def analyze_routes():
    if not os.path.exists(CSV_LOG_FILE):
        print("Keine CSV-Datei für Routenanalyse.")
        return

    df = pd.read_csv(CSV_LOG_FILE)

    grouped = df.groupby("edge_id").agg(
        mean_soc=("soc", "mean"),
        min_soc=("soc", "min"),
        mean_score=("charging_score", "mean"),
        count=("veh_id", "count")
    ).reset_index()

    grouped.to_csv("route_analysis.csv", index=False)
    print("Routenanalyse gespeichert: route_analysis.csv")


# ============================================================
# 8) MAIN
# ============================================================

def main():
    train_ml_model()
    scored_positions = scan_network_and_score()
    best_locations = select_top_locations(scored_positions)
    generate_charging_xml(best_locations)

    if GENERATE_HEATMAP:
        create_heatmap(scored_positions)
    if GENERATE_PLOTLY:
        create_plotly_viewer(scored_positions)
    if DO_ROUTE_ANALYSIS:
        analyze_routes()

    print("\nFERTIG. Du kannst die XML-Datei nun in SUMO einbinden.\n")


if __name__ == "__main__":
    main()