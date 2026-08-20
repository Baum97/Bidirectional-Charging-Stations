"""Continue the Saturate-and-Prune loop from its current state (49 candidates)
for three further prune iterations, to trace the accessibility/station-count curve."""
import sys, os, json, subprocess, time, csv
import statistics as st

LOCAL = os.path.dirname(os.path.abspath(__file__))
SCEN = os.path.join(LOCAL, "..", "data", "scenarios")
PY_EXE = sys.executable

sys.path.insert(0, LOCAL)
os.chdir(LOCAL)

import xml.etree.ElementTree as ET
import biflex_local_runner as R
from convert_logs_to_csv import process_sumo_logs

SEEDS = [42, 43, 44, 45, 46]
EXTRA_ITERATIONS = 3
THRESHOLD = 0.05
RESULTS = os.path.join(SCEN, "saturate_prune_results.json")
results = json.load(open(RESULTS))


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
    d = os.path.join(SCEN, "ms_s%d_sp" % seed)
    sat_file = os.path.join(d, "saturated_cs.add.xml")
    if not os.path.exists(sat_file):
        print("[skip] %s missing" % d, flush=True)
        continue

    entry = results[key]
    done_extra = len([i for i in entry["iterations"] if i["label"].startswith("sp_iter")]) - 3
    if done_extra >= EXTRA_ITERATIONS:
        print("[skip] seed %d already extended" % seed, flush=True)
        continue

    protected = [c.get("id") for c in
                 ET.parse(os.path.join(d, "osm.chargingstations.xml")).getroot().findall("chargingStation")]
    start = len(entry["iterations"])
    print("=== seed %d: continuing from %d candidates" %
          (seed, len(ET.parse(sat_file).getroot().findall("chargingStation"))), flush=True)

    for k in range(EXTRA_ITERATIONS):
        it = start + k + 1
        kept, removed = R.prune_underutilized_stations(d, sat_file, THRESHOLD, protected)
        print("    prune -> %s candidates left (removed %s)" % (kept, removed), flush=True)
        if not kept:
            print("    no candidates left, stopping", flush=True)
            break
        rt = run_traci(d)
        process_sumo_logs(os.path.join(d, "fcd_output.xml.gz"),
                          os.path.join(d, "battery_output.xml.gz"),
                          os.path.join(d, "osm.chargingstations.xml"),
                          os.path.join(d, "sumo_merged_output.csv"))
        m = metrics(d, "sp_iter%d" % it)
        m["runtime_s"] = round(rt)
        m["candidates"] = kept
        print("    iter %d: %d stations, %d sess, %.1f kWh, SoC %.1f, <20%% %.1f" %
              (it, m["cs_in_net"], m["pub_sessions"], m["pub_kwh"],
               m["soc_end_mean"], m["below20"]), flush=True)
        entry["iterations"].append(m)
        json.dump(results, open(RESULTS, "w"), indent=2)

print("ALL DONE")
