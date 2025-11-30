import gzip
import xml.etree.ElementTree as ET
import pandas as pd
from collections import defaultdict

# Pfade anpassen
FCD_FILE = "generated_files/logs/fcd_output.xml.gz"
BATTERY_FILE = "generated_files/logs/battery_output.xml.gz"
OUTPUT_CSV = "generated_files/logs/sumo_merged_output.csv"

# Speicherfreundliche Strukturen
fcd_data = []
unique_edge_ids = {}
battery_data = defaultdict(dict)

# ----------------------------------------------------------
# 1) FCD-DATEI EINLESEN (time, veh_id, pos, speed, edge, lane)
# ----------------------------------------------------------
print("Reading FCD data...")

with gzip.open(FCD_FILE, "rt") as f:
    tree = ET.parse(f)
root = tree.getroot()

for timestep in root.findall("timestep"):
    t = float(timestep.get("time"))

    for veh in timestep.findall("vehicle"):
        edge_id = veh.get("lane") 
        if  edge_id not in unique_edge_ids[edge_id]:
            uid = len(unique_edge_ids)
            unique_edge_ids[edge_id] = uid
        else:
            uid = unique_edge_ids[edge_id]

        fcd_data.append({
            "time": t,
            "veh_id": veh.get("id"),
            "x": float(veh.get("x")),
            "y": float(veh.get("y")),
            "speed": float(veh.get("speed")),
            "pos": float(veh.get("pos")),
            "lane": veh.get("lane"),
            "edge": uid,
            "road": veh.get("road"),
        })

df_fcd = pd.DataFrame(fcd_data)
print(f"FCD rows: {len(df_fcd)}")


# ----------------------------------------------------------
# 2) BATTERY-DATEI EINLESEN (SOC, consumption, emissions)
# ----------------------------------------------------------
print("Reading Battery data...")

def get_float_safe(element, key):
    val = element.get(key)
    return float(val) if val is not None else None

with gzip.open(BATTERY_FILE, "rt") as f:
    tree = ET.parse(f)
root = tree.getroot()

for timestep in root.findall("timestep"):
    t = float(timestep.get("time"))

    for bat in timestep.findall("vehicle"):
        veh_id = bat.get("id")
        battery_data[(t, veh_id)] = {
            "soc": get_float_safe(bat, "actualBatteryCapacity"),
            "max_battery": get_float_safe(bat, "maximumBatteryCapacity"),
            "energyConsumed": get_float_safe(bat, "totalEnergyConsumed"),
            "energyRegenerated": get_float_safe(bat, "totalEnergyRegenerated"),
            "energyCharged": get_float_safe(bat, "energyCharged"),
        }

df_bat = pd.DataFrame(
    [(t, vid, *vals.values()) for (t, vid), vals in battery_data.items()],
    columns=["time", "veh_id", "soc", "max_battery", "energyConsumed", "fuel", "co2"]
)


print(f"Battery rows: {len(df_bat)}")


# ----------------------------------------------------------
# 3) MERGE FCD + BATTERY
# ----------------------------------------------------------
print("Merging data...")

df = pd.merge(df_fcd, df_bat, on=["time", "veh_id"], how="left")

# SOC normalisieren
df["soc_percent"] = 100 * df["soc"] / df["max_battery"]


# ----------------------------------------------------------
# 4) SPEICHERN ALS CSV
# ----------------------------------------------------------
df.to_csv(OUTPUT_CSV, index=False)
print(f"\nCSV written: {OUTPUT_CSV}")
print(f"Total rows: {len(df)}")
