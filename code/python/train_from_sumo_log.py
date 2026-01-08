"""
train_from_sumo_log.py

Train a small neural network on SUMO merged log to predict a continuous
'suitability score' for placing charging stations.

Usage examples (PowerShell):
python ./code/python/train_from_sumo_log.py --log generated_files/logs/sumo_merged_output.csv
python ./code/python/train_from_sumo_log.py --log generated_files/logs/sumo_merged_output.csv --net generated_files/osm.net.xml --scan

Outputs:
- charging_model.pt           (PyTorch state_dict)
- scaler.pkl                  (StandardScaler)
- edge_mapping.pkl            (mapping lane/edge -> int)
- scored_positions.csv        (if --scan)
- generated_charging.add.xml  (if --scan and net available)
"""
import os
import math
import argparse
import joblib
import numpy as np
import pandas as pd
from sklearn.neighbors import KDTree
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import train_test_split

import torch
import torch.nn as nn
from torch.utils.data import DataLoader, TensorDataset

try:
    import sumolib
except Exception:
    sumolib = None

# ---------------------------
# Defaults / config
# ---------------------------
DEFAULT_LOG = "generated_files/logs/sumo_merged_output.csv"
MODEL_FILE = "charging_model.pt"
SCALER_FILE = "scaler.pkl"
MAPPING_FILE = "edge_mapping.pkl"
SCORED_CSV = "generated_files/logs/scored_positions.csv"
XML_OUT = "generated_charging.add.xml"

RADIUS_M = 50.0      # neighborhood radius (meters) for density label
SIM_HOURS = 1.0      # used later if you estimate chargers
DEVICE = "cpu"
EPOCHS = 40
BATCH_SIZE = 512
LR = 1e-3
TEST_SIZE = 0.2
RANDOM_STATE = 42

# ---------------------------
# Network
# ---------------------------
class SuitabilityNet(nn.Module):
    def __init__(self, in_features):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(in_features, 64),
            nn.ReLU(),
            nn.Linear(64, 32),
            nn.ReLU(),
            nn.Linear(32, 1),
            nn.Sigmoid()  # output in [0,1]
        )

    def forward(self, x):
        return self.net(x)

# ---------------------------
# Helpers
# ---------------------------
def detect_charging_row(row):
    # energyCharged column present? treat >0 as charging
    if "energyCharged" in row.index and pd.notnull(row["energyCharged"]):
        try:
            if float(row["energyCharged"]) > 0:
                return True
        except Exception:
            pass
    # fallback: charging_station column not empty
    if "charging_station" in row.index and pd.notnull(row["charging_station"]) and str(row["charging_station"]) != "":
        return True
    return False

def build_edge_mapping(series):
    # map lane/edge string to int
    unique = series.dropna().unique()
    mapping = {}
    for i, v in enumerate(sorted(unique)):
        mapping[v] = i
    return mapping

def compute_spatial_density(df_coords, radius=RADIUS_M):
    """
    df_coords: numpy array Nx2 of x,y for points that are charging events
    Returns: density per original point (we will compute for all rows by querying KDTree)
    """
    if len(df_coords) == 0:
        return np.array([])
    tree = KDTree(df_coords)
    # for each point query how many charging events in radius
    counts = tree.query_radius(df_coords, r=radius, count_only=True)
    return counts

def make_labels(df, radius=RADIUS_M):
    """
    Create a continuous label in [0,1]:
      - rows with direct charging event => label 1.0
      - other rows => normalized local charging density (0..1)
    """
    # make boolean charging mask
    charging_mask = df.apply(detect_charging_row, axis=1).values

    coords = df[["x","y"]].to_numpy()
    # Build KDTree on charging events only
    charging_coords = coords[charging_mask]
    if len(charging_coords) == 0:
        # fallback: label = 1 for explicit charging rows, else 0
        labels = charging_mask.astype(float)
        return labels

    # For each row (all coords) compute number of charging events within radius
    tree = KDTree(charging_coords)
    # query counts for all coords (search in charging_coords)
    # Trick: query_radius with array yields for each sample in 'coords' counts of neighbors in charging_coords
    counts = tree.query_radius(coords, r=radius, count_only=True)
    counts = np.array(counts, dtype=float)

    # normalize counts to [0,1]
    if counts.max() > 0:
        norm = counts / counts.max()
    else:
        norm = counts

    # override label for actual charging rows to 1.0 (they are highest priority)
    labels = norm
    labels[charging_mask] = 1.0
    return labels

def prepare_features(df, edge_mapping):
    """
    Create numeric feature matrix from dataframe.
    Features used:
      - x, y
      - pos (position along lane) -> 'pos' column exists in convert script
      - speed
      - soc_percent (or soc scaled)
      - energyCharged (if present)
      - edge_enc (mapped from 'lane' or 'edge' column) -> numeric id
      - hour_of_day (from time)
    """
    # ensure columns exist and convert types
    df = df.copy()
    # choose lane key: prefer 'lane' (string lane id), if not present use 'edge' numeric col
    lane_key = None
    if "lane" in df.columns:
        lane_key = "lane"
    elif "edge" in df.columns:
        lane_key = "edge"
    else:
        lane_key = None

    # edge encoding
    if lane_key:
        df["edge_key"] = df[lane_key].astype(str).fillna("NA")
    else:
        df["edge_key"] = "NA"

    df["edge_enc"] = df["edge_key"].map(lambda v: edge_mapping.get(v, -1)).astype(float)

    # numeric columns
    for col in ["x","y","pos","speed","soc_percent","energyCharged","energy_delta_kwh"]:
        if col not in df.columns:
            df[col] = 0.0

    # time -> hour of day (0..23)
    if "time" in df.columns:
        df["hour"] = (df["time"] % 86400) / 3600.0
    else:
        df["hour"] = 0.0

    feat_cols = ["x","y","pos","speed","soc_percent","energyCharged","edge_enc","hour"]
    X = df[feat_cols].fillna(0.0).astype(float).to_numpy()
    return X, feat_cols

# ---------------------------
# Training pipeline
# ---------------------------
def train_model(csv_path, netfile=None, do_scan=False, radius=RADIUS_M,
                epochs=EPOCHS, batch_size=BATCH_SIZE, lr=LR, test_size=TEST_SIZE):
    print("Reading CSV:", csv_path)
    df = pd.read_csv(csv_path)

    # drop rows without coordinates
    df = df.dropna(subset=["x","y"])
    df = df.reset_index(drop=True)

    print("Rows:", len(df))

    # build mapping for lane/edge
    lane_source = "lane" if "lane" in df.columns else ("edge" if "edge" in df.columns else None)
    if lane_source:
        edge_mapping = build_edge_mapping(df[lane_source].astype(str))
    else:
        edge_mapping = {"NA": 0}
    print("Edge mapping entries:", len(edge_mapping))
    joblib.dump(edge_mapping, MAPPING_FILE)

    # create labels
    print("Creating labels (spatial density + explicit charging)...")
    labels = make_labels(df, radius=radius)
    df["charging_score"] = labels

    # features
    X_raw, feat_cols = prepare_features(df, edge_mapping)
    y_raw = df["charging_score"].astype(float).to_numpy().reshape(-1,1)

    # train/test split
    X_train, X_test, y_train, y_test = train_test_split(X_raw, y_raw, test_size=test_size, random_state=RANDOM_STATE)
    print("Train/Test:", X_train.shape[0], X_test.shape[0])

    # scaler
    scaler = StandardScaler()
    X_train_s = scaler.fit_transform(X_train)
    X_test_s = scaler.transform(X_test)
    joblib.dump(scaler, SCALER_FILE)

    # PyTorch datasets
    Xtr = torch.tensor(X_train_s, dtype=torch.float32)
    ytr = torch.tensor(y_train, dtype=torch.float32)
    Xte = torch.tensor(X_test_s, dtype=torch.float32)
    yte = torch.tensor(y_test, dtype=torch.float32)

    train_ds = TensorDataset(Xtr, ytr)
    train_loader = DataLoader(train_ds, batch_size=batch_size, shuffle=True)

    model = SuitabilityNet(in_features=X_train_s.shape[1]).to(DEVICE)
    opt = torch.optim.Adam(model.parameters(), lr=lr)
    loss_fn = nn.MSELoss()

    print("Starting training ...")
    for ep in range(epochs):
        model.train()
        total_loss = 0.0
        for xb, yb in train_loader:
            xb = xb.to(DEVICE)
            yb = yb.to(DEVICE)
            pred = model(xb)
            loss = loss_fn(pred, yb)
            opt.zero_grad()
            loss.backward()
            opt.step()
            total_loss += loss.item() * xb.size(0)
        avg_loss = total_loss / Xtr.size(0)
        # eval on test (simple)
        model.eval()
        with torch.no_grad():
            pred_test = model(Xte.to(DEVICE)).cpu().numpy()
            # yte is a torch.Tensor — convert to numpy to allow numpy arithmetic
            yte_np = yte.cpu().numpy()
            test_mse = float(((pred_test - yte_np)**2).mean())
        print(f"Epoch {ep+1}/{epochs}: train_loss={avg_loss:.6f} test_mse={test_mse:.6f}")

    # save model
    torch.save(model.state_dict(), MODEL_FILE)
    print("Model saved to", MODEL_FILE)
    print("Scaler saved to", SCALER_FILE)
    print("Edge mapping saved to", MAPPING_FILE)

    # Optional: scan network and score positions
    if do_scan:
        print("Scanning network and scoring positions ...")
        net = None
        if netfile and os.path.exists(netfile) and sumolib:
            try:
                net = sumolib.net.readNet(netfile)
                print("Loaded network:", netfile)
            except Exception as e:
                print("Could not read network:", e)
                net = None
        scored_positions = scan_and_score_network(model, scaler, edge_mapping, net)
        if scored_positions:
            df_scored = pd.DataFrame(scored_positions, columns=["score","x","y","lane","pos"])
            df_scored.to_csv(SCORED_CSV, index=False)
            print("Scored positions saved to", SCORED_CSV)
            # write XML
            write_charging_xml(df_scored.sort_values("score", ascending=False).head(50), XML_OUT, net)
            print("XML written:", XML_OUT)

def scan_and_score_network(model, scaler, edge_mapping, net, sample_step=10.0):
    """
    For each lane in net sample positions every sample_step meters and score them.
    Requires: model (nn.Module), scaler (StandardScaler), edge_mapping mapping lane->int
    """
    if net is None:
        print("No network provided or sumolib missing; skipping scan.")
        return []

    model.eval()
    scored = []
    for lane_id in net.getLaneIDs():
        try:
            lane = net.getLane(lane_id)
        except Exception:
            continue
        length = lane.getLength()
        edge_key = lane.getID()
        if edge_key not in edge_mapping:
            # skip unknown lanes (could extend mapping if desired)
            continue
        enc = float(edge_mapping[edge_key])
        d = 0.0
        speed = lane.getSpeed() if hasattr(lane, "getSpeed") else 0.0
        while d < length:
            x,y = lane.getPositionAt(d)
            # features in same order as prepare_features
            feat = np.array([[x, y, d, speed, 50.0, 0.0, enc, 12.0]], dtype=float)  # soc_percent=50 default, energyCharged=0, hour=12
            feat_s = scaler.transform(feat)
            with torch.no_grad():
                inp = torch.tensor(feat_s, dtype=torch.float32)
                score = float(model(inp).cpu().numpy().squeeze())
            scored.append((score, x, y, lane_id, d))
            d += sample_step
    print("Scored positions:", len(scored))
    return scored

def write_charging_xml(df_top, out_xml, net=None, station_length=4.0, charger_kw=50.0):
    """
    df_top: DataFrame with columns score,x,y,lane,pos
    net: sumolib net object (optional) — if provided attach lane ids
    """
    with open(out_xml, "w", encoding="utf-8") as f:
        f.write("<additional>\n")
        for i, row in df_top.iterrows():
            lane = row.get("lane", "")
            pos = float(row.get("pos", 0.0))
            start = max(pos - station_length/2, 0.0)
            end = pos + station_length/2
            power = int(charger_kw * 1000)
            if lane:
                f.write(f'  <chargingStation id="autocs_{i}" lane="{lane}" startPos="{start:.2f}" endPos="{end:.2f}" power="{power}" efficiency="0.95"/>\n')
            else:
                f.write(f'  <!-- autocs_{i} at ({row["x"]:.1f},{row["y"]:.1f}) score={row["score"]:.3f} -->\n')
        f.write("</additional>\n")

# ---------------------------
# CLI
# ---------------------------
def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--log", default=DEFAULT_LOG, help="Path to sumo_merged_output.csv")
    p.add_argument("--net", default=None, help="Path to SUMO net xml (optional, for scanning)")
    p.add_argument("--scan", action="store_true", help="After training, scan net and produce scored positions & xml")
    p.add_argument("--radius", type=float, default=RADIUS_M, help="Radius for label density in meters")
    p.add_argument("--epochs", type=int, default=EPOCHS, help="Number of training epochs")
    p.add_argument("--batch-size", type=int, default=BATCH_SIZE, help="Batch size for training")
    p.add_argument("--lr", type=float, default=LR, help="Learning rate")
    return p.parse_args()

if __name__ == "__main__":
    args = parse_args()
    train_model(args.log, netfile=args.net, do_scan=args.scan, radius=args.radius,
                epochs=args.epochs, batch_size=args.batch_size, lr=args.lr)