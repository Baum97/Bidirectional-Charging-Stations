import sys, os, math, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pandas as pd
from power_grid_manager import PowerGridManager
import train_traci
from train_traci import process_sumo_log_no_stations, RETAINED

d = sys.argv[1]
mgr = PowerGridManager.load(os.path.join(d, "power_grid.pkl"))
process_sumo_log_no_stations(
    os.path.join(d, "sumo_merged_output.csv"),
    os.path.join(d, "clusters_fast.csv"),
    os.path.join(d, "clusters_fast.geojson"),
    os.path.join(d, "clusters_fast.add.xml"),
    os.path.join(d, "osm.net.xml.gz"),
    os.path.join(d, "clusters_fast_heatmap.json"),
    power_grid_manager=mgr, fast_mode=True,
    existing_stations_file=os.path.join(d, "osm.chargingstations.xml"),
)
csv = pd.read_csv(os.path.join(d, "clusters_fast.csv")).set_index("cluster_id")
# sim hours from log
log = pd.read_csv(os.path.join(d, "sumo_merged_output.csv"), usecols=["time"])
sim_hours = max((log.time.max()-log.time.min())/3600.0, 1/3600)
GAP=300.0; TARGET=80.0; CAP_KWH=80.0; CHARGER_KW=50.0; UTIL=0.75
rows=[]
for cid, pts in RETAINED:
    p = pts.sort_values(["veh_id","time"])
    visits=[]
    for v, g in p.groupby("veh_id"):
        t=g["time"].values; soc=g["soc_percent"].values
        start=0
        for i in range(1,len(t)+1):
            if i==len(t) or t[i]-t[i-1]>GAP:
                seg=soc[start:i]
                visits.append((v, float(seg.min())))
                start=i
    kwh=sum(max(0.0,(TARGET-s))/100.0*CAP_KWH for _,s in visits)
    cp=math.ceil((kwh/sim_hours)/(CHARGER_KW*UTIL)) if kwh>0 else 0
    cap=float(csv.loc[cid,"grid_capacity_kw"])
    cp=min(cp,int(cap/CHARGER_KW))
    rows.append(dict(cid=cid, visits=len(visits), vehicles=len({v for v,_ in visits}),
        soc=float(csv.loc[cid,"mean_soc"]), rad=float(csv.loc[cid,"radius_m"]),
        kwh=kwh, cp=cp, cap=cap, quality=csv.loc[cid,"grid_quality"],
        dist=float(csv.loc[cid,"grid_distance_m"]), samples=int(csv.loc[cid,"count_low_soc"])))
df=pd.DataFrame(rows).sort_values("kwh",ascending=False)
pd.set_option("display.width",200)
print(f"\n### {d}  sim_hours={sim_hours:.3f}")
print(df.to_string(index=False,float_format=lambda x:f"{x:.1f}"))
print(f"\nclusters={len(df)} visits={df.visits.sum()} vehicles(sum)={df.vehicles.sum()} kwh={df.kwh.sum():.1f} cp={df.cp.sum()} samples={df.samples.sum()}")
print(f"mean_soc={df.soc.mean():.1f}+-{df.soc.std():.1f} radius={df.rad.mean():.1f}+-{df.rad.std():.1f}")
print("grid:", df.quality.value_counts().to_dict(), "cap:", df.cap.value_counts().to_dict())
print(f"grid distance mean={df.dist.mean():.0f} max={df.dist.max():.0f}")
print(f"top2 visit share={100*df.visits.head(2).sum()/df.visits.sum():.0f}% energy share={100*df.kwh.head(2).sum()/df.kwh.sum():.0f}%")
print(f"single-visit clusters={int((df.visits==1).sum())}")
df.to_csv(os.path.join(d,"visit_table.csv"),index=False)
