"""
generate_stations_from_log.py

Liest model_log_data.csv, findet optimale Ladestations-Standorte mittels:
- DBSCAN-Clustering auf Lade-Events
- Flächenausgabe (Bufferzonen um Cluster)
- Heuristische Schätzung benötigter Ladepunkte pro Cluster
- Optional: SUMO-XML-Export mit Lane-Zuordnung via sumolib

Ausgabe:
  - charging_suggestions.csv: Cluster-Zentren + Schätzung
  - charging_areas.geojson: Polygone für Visualisierung
  - generated_charging.add.xml: SUMO additional (falls sumolib verfügbar)
"""

import os
import math
import argparse
import json
import pandas as pd
import numpy as np
from sklearn.cluster import DBSCAN
from scipy.spatial import ConvexHull

try:
    import sumolib
    HAS_SUMOLIB = True
except ImportError:
    HAS_SUMOLIB = False
    print("WARNING: sumolib not available, skipping Lane-ID detection")


# ============================================================
# HELPERS
# ============================================================

def read_log(path):
    """Read and normalize CSV columns."""
    df = pd.read_csv(path)
    
    # normalize column names
    col_map = {
        'position_x': 'x', 'pos_x': 'x',
        'position_y': 'y', 'pos_y': 'y',
    }
    for old, new in col_map.items():
        if old in df.columns:
            df = df.rename(columns={old: new})
    
    # ensure numeric
    df['x'] = pd.to_numeric(df['x'], errors='coerce')
    df['y'] = pd.to_numeric(df['y'], errors='coerce')
    
    return df


def cluster_charging_events(df, eps=30, min_samples=3, debug=False):
    """
    Find charging hotspots via DBSCAN.
    
    Args:
        df: DataFrame with x, y columns and (optionally) is_charging/charging
        eps: DBSCAN eps (meters)
        min_samples: DBSCAN min_samples
        debug: verbose output
    
    Returns:
        list of dicts: [{'cluster': int, 'x': float, 'y': float, 'count': int, 'rows': df, ...}, ...]
    """
    # keep only charging events if column exists
    if 'is_charging' in df.columns:
        df_ch = df[df['is_charging'] == True].copy()
    elif 'charging' in df.columns:
        df_ch = df[df['charging'] == True].copy()
    else:
        print("WARNING: no is_charging/charging column, using all data")
        df_ch = df.copy()
    
    if debug:
        print(f"Total rows: {len(df)}, Charging events: {len(df_ch)}")
    
    coords = df_ch[['x','y']].dropna().values
    if len(coords) == 0:
        print("ERROR: No valid coordinates found in charging events")
        return []
    
    # DBSCAN clustering
    db = DBSCAN(eps=eps, min_samples=min_samples).fit(coords)
    df_ch = df_ch.reset_index(drop=True)
    df_ch['cluster'] = db.labels_
    
    if debug:
        n_clusters = len(set(db.labels_)) - (1 if -1 in db.labels_ else 0)
        n_noise = list(db.labels_).count(-1)
        print(f"Clusters found: {n_clusters}, Noise points: {n_noise}")
    
    clusters = []
    for label in sorted(df_ch['cluster'].unique()):
        if label == -1:  # skip noise
            continue
        
        subset = df_ch[df_ch['cluster'] == label]
        cx = subset['x'].mean()
        cy = subset['y'].mean()
        count = len(subset)
        
        # aggregate statistics
        stats = {
            'cluster': label,
            'x': cx,
            'y': cy,
            'count': count,
            'rows': subset,
        }
        
        # optional: mean SOC if available
        if 'soc' in subset.columns:
            stats['mean_soc'] = subset['soc'].mean()
        
        # optional: mean speed if available
        if 'speed' in subset.columns:
            stats['mean_speed'] = subset['speed'].mean()
        
        # optional: sum energy if available
        if 'energy_delta_kwh' in subset.columns:
            stats['total_energy_kwh'] = subset['energy_delta_kwh'].sum()
        elif 'energy_delta' in subset.columns:
            # rough conversion if only power is logged
            stats['total_energy_kwh'] = (subset['energy_delta'].sum() / 3600.0)
        
        clusters.append(stats)
    
    clusters.sort(key=lambda c: c['count'], reverse=True)
    return clusters


def estimate_chargers(cluster, sim_total_hours=1.0, avg_session_kwh=25.0, 
                      charger_kw=50.0, utilization=0.75, debug=False):
    """
    Estimate number of chargers needed for a cluster.
    
    Heuristic:
      - Energy per hour = events_per_hour * avg_session_kwh (or total_energy if available)
      - Capacity per charger = charger_kw * utilization
      - Required chargers = ceil(energy_per_hour / capacity_per_charger)
    
    Args:
        cluster: dict with 'count', 'total_energy_kwh' (optional)
        sim_total_hours: simulation duration in hours
        avg_session_kwh: assumed energy per charging event (if total_energy_kwh not in cluster)
        charger_kw: power rating per charger
        utilization: target utilization (0..1)
        debug: verbose
    
    Returns:
        int: estimated number of chargers
    """
    # prefer actual energy if available
    if 'total_energy_kwh' in cluster and cluster['total_energy_kwh'] > 0.1:
        energy_kwh_per_hour = cluster['total_energy_kwh'] / sim_total_hours
        if debug:
            print(f"  Using measured energy: {cluster['total_energy_kwh']:.2f} kWh -> {energy_kwh_per_hour:.2f} kWh/h")
    else:
        events_per_hour = cluster['count'] / sim_total_hours
        energy_kwh_per_hour = events_per_hour * avg_session_kwh
        if debug:
            print(f"  Using estimated energy: {cluster['count']} events -> {energy_kwh_per_hour:.2f} kWh/h")
    
    capacity_kwh_per_hour_per_charger = charger_kw * utilization
    n = math.ceil(energy_kwh_per_hour / capacity_kwh_per_hour_per_charger) if capacity_kwh_per_hour_per_charger > 0 else 1
    
    return max(1, n)


def create_buffered_polygon(cluster, buffer_radius=50):
    """
    Create a simple circular buffer around cluster center.
    Returns list of (x, y) points representing a polygon.
    """
    cx, cy = cluster['x'], cluster['y']
    n_points = 32
    points = []
    for i in range(n_points):
        angle = 2 * math.pi * i / n_points
        px = cx + buffer_radius * math.cos(angle)
        py = cy + buffer_radius * math.sin(angle)
        points.append([px, py])
    points.append(points[0])  # close polygon
    return points


def find_nearest_lane(net, x, y, search_radius=100):
    """
    Find nearest lane within radius using sumolib.
    Returns lane or None.
    """
    if not HAS_SUMOLIB or not net:
        return None
    
    try:
        lane = net.getNearestLane((x, y))
        if lane:
            return lane
    except Exception:
        pass
    
    return None


def write_csv(clusters, out_csv, sim_hours=1.0, avg_kwh=25.0, charger_kw=50.0, util=0.75):
    """Write charging_suggestions.csv."""
    rows = []
    for i, c in enumerate(clusters):
        est = estimate_chargers(c, sim_hours, avg_kwh, charger_kw, util)
        rows.append({
            'cluster_id': i,
            'center_x': c['x'],
            'center_y': c['y'],
            'event_count': c['count'],
            'estimated_chargers': est,
            'mean_soc': c.get('mean_soc', None),
            'mean_speed': c.get('mean_speed', None),
            'total_energy_kwh': c.get('total_energy_kwh', None),
        })
    
    df = pd.DataFrame(rows)
    df.to_csv(out_csv, index=False)
    print(f"[OK] Written: {out_csv}")
    return df


def write_geojson(clusters, out_geojson, buffer_radius=50):
    """Write charging_areas.geojson with buffered polygons."""
    features = []
    
    for i, c in enumerate(clusters):
        polygon = create_buffered_polygon(c, buffer_radius=buffer_radius)
        
        feature = {
            "type": "Feature",
            "properties": {
                "cluster_id": i,
                "event_count": c['count'],
                "center_x": c['x'],
                "center_y": c['y'],
                "mean_soc": c.get('mean_soc', None),
                "total_energy_kwh": c.get('total_energy_kwh', None),
            },
            "geometry": {
                "type": "Polygon",
                "coordinates": [polygon]
            }
        }
        features.append(feature)
    
    geojson = {
        "type": "FeatureCollection",
        "features": features
    }
    
    with open(out_geojson, 'w') as f:
        json.dump(geojson, f, indent=2)
    
    print(f"[OK] Written: {out_geojson}")


def write_sumo_xml(clusters, out_xml, netfile=None, sim_hours=1.0, avg_kwh=25.0, 
                   charger_kw=50.0, util=0.75):
    """
    Write SUMO additional XML with charging stations.
    Tries to attach to lanes via sumolib if available.
    """
    net = None
    if netfile and os.path.exists(netfile) and HAS_SUMOLIB:
        try:
            net = sumolib.net.readNet(netfile)
            print(f"[OK] Loaded network: {netfile}")
        except Exception as e:
            print(f"[WARN] Could not load network: {e}")
    
    with open(out_xml, "w", encoding="utf-8") as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n')
        f.write('<additional>\n')
        
        for i, c in enumerate(clusters):
            est = estimate_chargers(c, sim_hours, avg_kwh, charger_kw, util)
            cs_id = f"cs_{i}"
            
            lane_id = None
            start_pos = 0.0
            end_pos = 2.0
            
            if net:
                lane = find_nearest_lane(net, c['x'], c['y'])
                if lane:
                    lane_id = lane.getID()
                    try:
                        length = lane.getLength()
                        start_pos = max(0.0, length / 2 - 5.0)
                        end_pos = min(length, length / 2 + 5.0)
                    except Exception:
                        pass
            
            power_w = int(charger_kw * 1000)
            
            if lane_id:
                f.write(
                    f'  <chargingStation id="{cs_id}" lane="{lane_id}" '
                    f'startPos="{start_pos:.2f}" endPos="{end_pos:.2f}" '
                    f'power="{power_w}" efficiency="0.95"/>\n'
                )
            else:
                # fallback: comment with coordinates
                f.write(
                    f'  <!-- {cs_id} at ({c["x"]:.1f}, {c["y"]:.1f}) '
                    f'est_chargers={est} (no lane mapping) -->\n'
                )
        
        f.write('</additional>\n')
    
    print(f"[OK] Written: {out_xml}")


# ============================================================
# MAIN
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description="Generate optimal charging station locations from simulation log"
    )
    parser.add_argument(
        "--log", 
        default="C:\\Users\\erikw\\Desktop\\AIM\\bilfex-container\\data\\scenarios\\test13\\sumo_merged_output.csv",
        help="Path to model_log_data.csv"
    )
    parser.add_argument(
        "--net",
        default="C:\\Users\\erikw\\Desktop\\AIM\\bilfex-container\\data\\scenarios\\test13\\osm.net.xml.gz", # NOTE
        help="Path to SUMO network file (for lane attachment)"
    )
    parser.add_argument(
        "--eps",
        type=float,
        default=30.0,
        help="DBSCAN eps in meters (spatial clustering radius)"
    )
    parser.add_argument(
        "--min-samples",
        type=int,
        default=3,
        help="DBSCAN min_samples (minimum events per cluster)"
    )
    parser.add_argument(
        "--sim-hours",
        type=float,
        default=1.0,
        help="Total simulation duration in hours (for energy scaling)"
    )
    parser.add_argument(
        "--avg-session-kwh",
        type=float,
        default=25.0,
        help="Assumed average energy per charging session (kWh)"
    )
    parser.add_argument(
        "--charger-kw",
        type=float,
        default=50.0,
        help="Power rating per charger (kW)"
    )
    parser.add_argument(
        "--utilization",
        type=float,
        default=0.75,
        help="Target utilization rate (0..1)"
    )
    parser.add_argument(
        "--buffer-radius",
        type=float,
        default=50.0,
        help="Buffer radius for area polygons (meters)"
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Verbose output"
    )
    
    args = parser.parse_args()
    
    # Read log
    if not os.path.exists(args.log):
        print(f"ERROR: Log file not found: {args.log}")
        return
    
    print(f"[*] Reading log: {args.log}")
    df = read_log(args.log)
    
    # Cluster
    print(f"[*] Clustering with eps={args.eps}, min_samples={args.min_samples}")
    clusters = cluster_charging_events(
        df, 
        eps=args.eps, 
        min_samples=args.min_samples,
        debug=args.debug
    )
    
    if not clusters:
        print("[ERROR] No clusters found. Maybe not enough charging events or wrong eps/min_samples.")
        return
    
    print(f"[OK] Found {len(clusters)} clusters\n")
    
    # Print summary
    for i, c in enumerate(clusters):
        est = estimate_chargers(
            c, 
            args.sim_hours, 
            args.avg_session_kwh, 
            args.charger_kw, 
            args.utilization,
            debug=args.debug
        )
        print(f"  Cluster {i}: ({c['x']:.1f}, {c['y']:.1f}) "
              f"events={c['count']} -> est_chargers={est}")
    
    print()
    
    # Write outputs
    csv_path = "C:\\Users\\erikw\\Desktop\\AIM\\bilfex-container\\data\\scenarios\\test13\\charging_suggestions.csv"
    geojson_path = "C:\\Users\\erikw\\Desktop\\AIM\\bilfex-container\\data\\scenarios\\test13\\charging_areas.geojson"
    xml_path = "C:\\Users\\erikw\\Desktop\\AIM\\bilfex-container\\data\\scenarios\\test13\\generated_charging.add.xml"
    
    write_csv(
        clusters, 
        csv_path, 
        args.sim_hours, 
        args.avg_session_kwh, 
        args.charger_kw, 
        args.utilization
    )
    
    write_geojson(clusters, geojson_path, buffer_radius=args.buffer_radius)
    
    write_sumo_xml(
        clusters,
        xml_path,
        netfile=args.net if os.path.exists(args.net) else None,
        sim_hours=args.sim_hours,
        avg_kwh=args.avg_session_kwh,
        charger_kw=args.charger_kw,
        util=args.utilization
    )
    
    print(f"\n[SUCCESS] Generated files:")
    print(f"  - {csv_path}")
    print(f"  - {geojson_path}")
    print(f"  - {xml_path}")


if __name__ == "__main__":
    main()