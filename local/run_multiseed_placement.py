import sys, os, json, shutil, subprocess, time, csv
import statistics as st

LOCAL = os.path.dirname(os.path.abspath(__file__))
SCEN = os.path.join(LOCAL, "..", "data", "scenarios")
SRC = os.environ.get("BIFLEX_SRC_SCENARIO",
                     os.path.join(SCEN, "scenario_branch_day"))
PY_EXE = sys.executable

sys.path.insert(0, LOCAL)
os.chdir(LOCAL)

import xml.etree.ElementTree as ET
import biflex_local_runner as R
from mainGenerateTrips import generate_trips
from generate_private_wallboxes import generate_private_wallboxes
from power_grid_manager import PowerGridManager
from convert_logs_to_csv import process_sumo_logs
from train_from_sumo_log_no_stations import process_sumo_log_no_stations

SEEDS = [42, 43, 44, 45, 46]
RESULTS = os.path.join(SCEN, "multiseed_results.json")
results = json.load(open(RESULTS)) if os.path.exists(RESULTS) else {}

COPY_FILES = ("test_name_bbox.osm.xml", "osm.net.xml.gz", "power_grid.pkl",
              "osm.chargingstations.xml", "poi_offices.csv", "poi_others.csv",
              "poi_residential.csv", "poi_offices_edges.csv",
              "poi_others_edges.csv", "poi_residential_edges.csv")


def build_base(seed):
    d = os.path.join(SCEN, "ms_s%d_base" % seed)
    if os.path.exists(d):
        shutil.rmtree(d)
    os.makedirs(d)
    for f in COPY_FILES:
        shutil.copy(os.path.join(SRC, f), os.path.join(d, f))
    p = json.load(open(os.path.join(SRC, "sim_params.json")))
    p["duration"] = 86400
    p["random_seed"] = seed
    json.dump(p, open(os.path.join(d, "sim_params.json"), "w"), indent=2)

    net = os.path.join(d, "osm.net.xml.gz")
    edges = [os.path.join(d, f) for f in ("poi_residential_edges.csv",
                                          "poi_offices_edges.csv",
                                          "poi_others_edges.csv")]
    trips = generate_trips(net, edges, d, sim_params=p)
    R.copy_default_combined_additional(os.path.basename(d))
    R.copy_vehicle_types_additional(os.path.basename(d))

    persons = []
    for v in ET.parse(trips).getroot().findall("vehicle"):
        e = v.find("route").get("edges", "").split()
        if e:
            persons.append({"id": v.get("id"), "home": e[0],
                            "vehicle_type": v.get("type"),
                            "has_ev": v.get("type").startswith("veh_ev")})
    generate_private_wallboxes(net, persons, d, trips_file=trips)

    ca = os.path.join(d, "combined_additional.xml")
    t = ET.parse(ca)
    root = t.getroot()
    for inc in list(root.findall("include")):
        if inc.get("href") == "private_wallboxes.xml":
            root.remove(inc)
    for inc in root.findall("include"):
        if inc.get("href") == "vehicle_types.add.xml":
            inc.set("href", "wallbox_vehicle_types.add.xml")
    t.write(ca, encoding="utf-8", xml_declaration=True)

    R.create_sumo_config(net, trips, "combined_additional.xml", d,
                         stationfinder_radius=int(p.get("stationfinder_radius", 3000)),
                         duration=86400)
    json.dump({"max_grid_power_kw": 1500.0, "area_km2": 1.0,
               "power_density_kw_per_km2": 1500, "bbox": None},
              open(os.path.join(d, "grid_config.json"), "w"), indent=2)
    return d, len(persons)


def run_traci(d):
    env = dict(os.environ, PYTHONHASHSEED="0", PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
    t0 = time.time()
    subprocess.run([PY_EXE, os.path.join(LOCAL, "performativeMainSim2.py"), d],
                   check=True, capture_output=True, env=env)
    return time.time() - t0


def convert(d):
    process_sumo_logs(os.path.join(d, "fcd_output.xml.gz"),
                      os.path.join(d, "battery_output.xml.gz"),
                      os.path.join(d, "osm.chargingstations.xml"),
                      os.path.join(d, "sumo_merged_output.csv"))


def metrics(d, label):
    v = json.load(open(os.path.join(d, "traci_logs", "v2g_summary.json")))
    last = {}
    ever = {}
    for r in csv.DictReader(open(os.path.join(d, "sumo_merged_output.csv"))):
        try:
            s = float(r["soc_percent"])
        except Exception:
            continue
        last[r["veh_id"]] = s
        ever[r["veh_id"]] = min(ever.get(r["veh_id"], 1e9), s)
    L = list(last.values())
    N = len(L)
    cs = ET.parse(os.path.join(d, "chargingstations.xml")).getroot().findall("chargingStation")
    return {
        "label": label, "agents": N, "evs": v["total_evs"], "cs_in_net": len(cs),
        "pub_sessions": v["charging"]["public"]["sessions"],
        "pub_vehicles": v["charging"]["public"]["unique_vehicles"],
        "pub_kwh": round(v["charging"]["public"]["total_energy_kwh"], 1),
        "wb_sessions": v["charging"]["wallbox"]["sessions"],
        "wb_kwh": round(v["charging"]["wallbox"]["total_energy_kwh"], 1),
        "v2g_kwh": v["v2g"]["total_discharged_kwh"],
        "peak_kw": v["grid"]["peak_usage_kw"],
        "soc_end_mean": round(sum(L) / N, 1),
        "soc_end_med": round(st.median(L), 1),
        "soc_end_std": round(st.stdev(L), 1),
        "below20": round(100 * sum(1 for x in L if x < 20) / N, 1),
        "below10_ever": round(100 * sum(1 for x in ever.values() if x < 10) / N, 1),
        "depleted": round(100 * sum(1 for x in ever.values() if x <= 0) / N, 1),
    }


for seed in SEEDS:
    key = "s%d" % seed
    if key in results and "clustering" in results[key]:
        print("[skip] seed %d already done" % seed, flush=True)
        continue

    print("=== seed %d: building scenario" % seed, flush=True)
    d, npers = build_base(seed)
    print("    %d persons; running baseline" % npers, flush=True)
    rt = run_traci(d)
    convert(d)
    base = metrics(d, "baseline")
    base["runtime_s"] = round(rt)
    print("    baseline: %d sess, %.1f kWh, SoC %.1f" %
          (base["pub_sessions"], base["pub_kwh"], base["soc_end_mean"]), flush=True)

    gm = PowerGridManager.load(os.path.join(d, "power_grid.pkl"))
    process_sumo_log_no_stations(
        os.path.join(d, "sumo_merged_output.csv"),
        os.path.join(d, "no_station_charging_suggestions.csv"),
        os.path.join(d, "no_station_areas.geojson"),
        os.path.join(d, "suggested_charging_stations.add.xml"),
        os.path.join(d, "osm.net.xml.gz"),
        os.path.join(d, "no_station_heatmap.json"),
        power_grid_manager=gm, fast_mode=True,
        existing_stations_file=os.path.join(d, "osm.chargingstations.xml"))

    dc = os.path.join(SCEN, "ms_s%d_clust" % seed)
    if os.path.exists(dc):
        shutil.rmtree(dc)
    shutil.copytree(d, dc, ignore=shutil.ignore_patterns(
        "traci_logs", "fcd_output.xml.gz", "battery_output.xml.gz",
        "veh_routes.xml.gz", "sumo_merged_output.csv", "chargingstations.xml"))
    cfg = os.path.join(dc, "sim.sumocfg")
    s = open(cfg, encoding="utf-8").read()
    open(cfg, "w", encoding="utf-8").write(s.replace(os.path.basename(d), os.path.basename(dc)))

    gcs, _ = R.generate_cs_from_polygons(os.path.join(dc, "no_station_areas.geojson"),
                                         dc, os.path.join(dc, "osm.net.xml.gz"))
    n_new = 0
    if gcs and os.path.exists(gcs):
        n_new = len(ET.parse(gcs).getroot().findall("chargingStation"))
        ca = os.path.join(dc, "combined_additional.xml")
        t = ET.parse(ca)
        root = t.getroot()
        ET.SubElement(root, "include", href="generated_cs.add.xml")
        t.write(ca, encoding="utf-8", xml_declaration=True)
    print("    clustering: %d candidate stations; running" % n_new, flush=True)
    rt = run_traci(dc)
    convert(dc)
    clus = metrics(dc, "clustering")
    clus["runtime_s"] = round(rt)
    clus["new_stations"] = n_new
    print("    clustering: %d sess, %.1f kWh, SoC %.1f" %
          (clus["pub_sessions"], clus["pub_kwh"], clus["soc_end_mean"]), flush=True)

    results[key] = {"baseline": base, "clustering": clus}
    json.dump(results, open(RESULTS, "w"), indent=2)

print("ALL DONE")
