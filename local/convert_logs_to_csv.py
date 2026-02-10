def process_sumo_logs(fcd_file, battery_file, additional_file, output):
    import gzip
    import xml.etree.ElementTree as ET
    import pandas as pd
    from collections import defaultdict

    # Speicher
    fcd_data = []
    unique_edge_ids = {}
    battery_data = defaultdict(dict)

    # ----------------------------------------------------------
    # 0) Charging-Station fetch data
    # ----------------------------------------------------------
    charging_stations = []

    try:
        import os
        tree = ET.parse(additional_file)
        root = tree.getroot()
        base_dir = os.path.dirname(additional_file)

        # Load charging stations directly from this file
        for cs in root.findall(".//chargingStation"):
            charging_stations.append({
                "id": cs.get("id"),
                "lane": cs.get("lane"),
                "startPos": float(cs.get("startPos")),
                "endPos": float(cs.get("endPos"))
            })

        # Follow <include> tags to load stations from referenced files
        for include in root.findall(".//include"):
            href = include.get("href")
            if href and ("chargingstation" in href.lower() or "wallbox" in href.lower() or "suggested" in href.lower()):
                included_file = os.path.join(base_dir, href)
                if os.path.exists(included_file):
                    try:
                        inc_tree = ET.parse(included_file)
                        inc_root = inc_tree.getroot()
                        for cs in inc_root.findall(".//chargingStation"):
                            charging_stations.append({
                                "id": cs.get("id"),
                                "lane": cs.get("lane"),
                                "startPos": float(cs.get("startPos")),
                                "endPos": float(cs.get("endPos"))
                            })
                    except Exception:
                        pass  # Skip files that can't be parsed

        if charging_stations:
            print(f"  Loaded {len(charging_stations)} charging stations for analysis")

    except Exception:
        pass  # Not critical - analysis works without station mapping

    def find_station(lane, pos):
        """Return charging station ID if vehicle is inside one."""
        for cs in charging_stations:
            if cs["lane"] == lane and cs["startPos"] <= pos <= cs["endPos"]:
                return cs["id"]
        return None

    # ----------------------------------------------------------
    # 1) FCD-Data
    # ----------------------------------------------------------
    with gzip.open(fcd_file, "rt") as f:
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

    # ----------------------------------------------------------
    # 2) Battery-Daten (SOC, Charging)
    # ----------------------------------------------------------

    def get_float_safe(element, key):
        val = element.get(key)
        return float(val) if val is not None else None

    with gzip.open(battery_file, "rt") as f:
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

    # ----------------------------------------------------------
    # 3) MERGE
    # ----------------------------------------------------------

    df = pd.merge(df_fcd, df_bat, on=["time", "veh_id"], how="left")

    # SOC %
    df["soc_percent"] = 100 * df["soc"] / df["max_battery"]

    # ----------------------------------------------------------
    # 4) Charging-Station-Erkennung
    # ----------------------------------------------------------
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
    df.to_csv(output, index=False)