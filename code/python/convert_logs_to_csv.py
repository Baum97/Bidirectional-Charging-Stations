import gzip
import xml.etree.ElementTree as ET
import pandas as pd
from collections import defaultdict

# ----------------------------------------------------------
# Log file and data paths
# ----------------------------------------------------------
FCD_FILE = "generated_files/logs/fcd_output.xml.gz"
BATTERY_FILE = "generated_files/logs/battery_output.xml.gz"
ADDITIONAL_FILE = "combined_additional.xml"
OUTPUT_CSV = "generated_files/logs/sumo_merged_output.csv"

# Speicher
fcd_data = []
unique_edge_ids = {}
battery_data = defaultdict(dict)

# ----------------------------------------------------------
# 0) Charging-Station fetch data
# ----------------------------------------------------------
print("Loading charging stations...")

charging_stations = []

try:
    tree = ET.parse(ADDITIONAL_FILE)
    root = tree.getroot()

    for cs in root.findall(".//chargingStation"):
        charging_stations.append({
            "id": cs.get("id"),
            "lane": cs.get("lane"),
            "startPos": float(cs.get("startPos")),
            "endPos": float(cs.get("endPos"))
        })

    print(f"Found {len(charging_stations)} charging stations.")

except Exception as e:
    print("Could not load additional file:", e)


def find_station(lane, pos):
    """Return charging station ID if vehicle is inside one."""
    for cs in charging_stations:
        if cs["lane"] == lane and cs["startPos"] <= pos <= cs["endPos"]:
            return cs["id"]
    return None


# ----------------------------------------------------------
# 1) FCD-Data
# ----------------------------------------------------------
print("Reading FCD data...")

with gzip.open(FCD_FILE, "rt") as f:
    tree = ET.parse(f)

root = tree.getroot()

for timestep in root.findall("timestep"):
    t = float(timestep.get("time"))

    for veh in timestep.findall("vehicle"):
        lane_id = veh.get("lane")

        # numerischen Edge-ID Index erzeugen
        if lane_id not in unique_edge_ids:
            unique_edge_ids[lane_id] = len(unique_edge_ids)

        fcd_data.append({
            "time": t,
            "veh_id": veh.get("id"),
            "x": float(veh.get("x")),
            "y": float(veh.get("y")),
            "speed": float(veh.get("speed")),
            "pos": float(veh.get("pos")),
            "lane": lane_id,
            "edge": unique_edge_ids[lane_id],
            "road": veh.get("road"),
        })

df_fcd = pd.DataFrame(fcd_data)
print(f"FCD rows: {len(df_fcd)}")


# ----------------------------------------------------------
# 2) Battery-Daten (SOC, Charging)
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
    [(t, vid, vals["soc"], vals["max_battery"], vals["energyConsumed"],
      vals["energyRegenerated"], vals["energyCharged"])
     for (t, vid), vals in battery_data.items()],
    columns=["time", "veh_id", "soc", "max_battery", "energyConsumed",
             "energyRegenerated", "energyCharged"]
)

print(f"Battery rows: {len(df_bat)}")


# ----------------------------------------------------------
# 3) MERGE
# ----------------------------------------------------------
print("Merging data...")

df = pd.merge(df_fcd, df_bat, on=["time", "veh_id"], how="left")

# SOC %
df["soc_percent"] = 100 * df["soc"] / df["max_battery"]


# ----------------------------------------------------------
# 4) Charging-Station-Erkennung
# ----------------------------------------------------------
print("Detecting charging events...")

def detect_charging(row):
    # lädt, wenn energyCharged > 0 oder SOC steigt
    is_charging = False

    if row["energyCharged"] not in (None, 0):
        if row["energyCharged"] > 0:
            is_charging = True

    if not is_charging:
        return None

    # passende Station finden
    return find_station(row["lane"], row["pos"])


df["charging_station"] = df.apply(detect_charging, axis=1)


# ----------------------------------------------------------
# 5) Speichern
# ----------------------------------------------------------
df.to_csv(OUTPUT_CSV, index=False)

print("\nCSV written:", OUTPUT_CSV)
print("Total rows:", len(df))
