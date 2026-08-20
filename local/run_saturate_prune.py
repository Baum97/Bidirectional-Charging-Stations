import sys, os, json, shutil, subprocess, time, csv, tempfile
import statistics as st

LOCAL = os.path.dirname(os.path.abspath(__file__))
SCEN = os.path.join(LOCAL, "..", "data", "scenarios")
PY_EXE = sys.executable

sys.path.insert(0, LOCAL)
os.chdir(LOCAL)

import xml.etree.ElementTree as ET
import biflex_local_runner as R
from mainGenerateChargingStations import generate_charging_stations
from convert_logs_to_csv import process_sumo_logs

SEEDS = [42, 43, 44, 45, 46]
ITERATIONS = 3
MIN_LANE = 50
THRESHOLD = 0.05
RESULTS = os.path.join(SCEN, "saturate_prune_results.json")
results = json.load(open(RESULTS)) if os.path.exists(RESULTS) else {}


def run_traci(d):
    env = dict(os.environ, PYTHONHASHSEED="0", PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
    t0 = time.time()
    subprocess.run([PY_EXE, os.path.join(LOCAL, "performativeMainSim2.py"), d],
                   check=True, capture_output=True, env=env)
    return time.time() - t0


def metrics(d, label):
    v = json.load(open(os.path.join(d, "traci_logs", "v2g_summary.json")))
    last, ever = {}, {}
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
        "label": label, "agents": N, "cs_in_net": len(cs),
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
    if key in results:
        print("[skip] seed %d done" % seed, flush=True)
        continue

    base = os.path.join(SCEN, "ms_s%d_base" % seed)
    if not os.path.exists(base):
        print("[wait] base scenario for seed %d missing, skipping" % seed, flush=True)
        continue

    d = os.path.join(SCEN, "ms_s%d_sp" % seed)
    if os.path.exists(d):
        shutil.rmtree(d)
    shutil.copytree(base, d, ignore=shutil.ignore_patterns(
        "traci_logs", "fcd_output.xml.gz", "battery_output.xml.gz",
        "veh_routes.xml.gz", "sumo_merged_output.csv", "chargingstations.xml",
        "no_station_*", "suggested_*"))
    cfg = os.path.join(d, "sim.sumocfg")
    s = open(cfg, encoding="utf-8").read()
    open(cfg, "w", encoding="utf-8").write(s.replace(os.path.basename(base), os.path.basename(d)))

    # --- saturate: candidate station on every viable road segment
    tmp = tempfile.mkdtemp()
    generated = generate_charging_stations(os.path.join(d, "osm.net.xml.gz"), tmp, MIN_LANE)
    sat_file = os.path.join(d, "saturated_cs.add.xml")
    shutil.copy(generated, sat_file)
    shutil.rmtree(tmp, ignore_errors=True)

    ca = os.path.join(d, "combined_additional.xml")
    t = ET.parse(ca)
    root = t.getroot()
    ET.SubElement(root, "include", href="saturated_cs.add.xml")
    t.write(ca, encoding="utf-8", xml_declaration=True)

    protected = [c.get("id") for c in
                 ET.parse(os.path.join(d, "osm.chargingstations.xml")).getroot().findall("chargingStation")]
    n_sat = len(ET.parse(sat_file).getroot().findall("chargingStation"))
    print("=== seed %d: saturated with %d candidates (+%d existing)" % (seed, n_sat, len(protected)), flush=True)

    iters = []
    for it in range(1, ITERATIONS + 1):
        rt = run_traci(d)
        process_sumo_logs(os.path.join(d, "fcd_output.xml.gz"),
                          os.path.join(d, "battery_output.xml.gz"),
                          os.path.join(d, "osm.chargingstations.xml"),
                          os.path.join(d, "sumo_merged_output.csv"))
        m = metrics(d, "sp_iter%d" % it)
        m["runtime_s"] = round(rt)
        m["candidates_before_prune"] = len(ET.parse(sat_file).getroot().findall("chargingStation"))
        print("    iter %d: %d stations in net, %d sess, %.1f kWh, SoC %.1f" %
              (it, m["cs_in_net"], m["pub_sessions"], m["pub_kwh"], m["soc_end_mean"]), flush=True)
        if it < ITERATIONS:
            kept, removed = R.prune_underutilized_stations(d, sat_file, THRESHOLD, protected)
            m["pruned"] = removed
            m["candidates_after_prune"] = kept
            print("    iter %d: pruned %s, kept %s candidates" % (it, removed, kept), flush=True)
        iters.append(m)

    results[key] = {"saturated_candidates": n_sat, "existing": len(protected), "iterations": iters}
    json.dump(results, open(RESULTS, "w"), indent=2)

print("ALL DONE")
