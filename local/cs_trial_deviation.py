"""
Analyse von GeoJSON-Polygon-Dateien aus mehreren Simulationsläufen.

Berechnet Standardabweichung und Statistiken über:
- Anzahl der vorgeschlagenen Standorte
- Räumliche Stabilität (wie konsistent Cluster-Zentren sind)
- SOC-Metriken, Charger-Schätzungen, Quality-Scores
- Überlappungsanalyse (welche Bereiche tauchen in jedem Lauf auf)
"""

import json
import math
import os
import sys
from collections import defaultdict

import numpy as np


def load_geojson(filepath):
    """Load a GeoJSON file and return features list."""
    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)
    features = data.get("features", [])
    return features


def polygon_centroid(coordinates):
    """Calculate centroid of a polygon from its coordinate ring."""
    ring = coordinates[0] if coordinates else []
    if not ring:
        return None, None
    # Exclude closing point if it duplicates the first
    pts = ring[:-1] if len(ring) > 1 and ring[0] == ring[-1] else ring
    if not pts:
        return None, None
    cx = sum(p[0] for p in pts) / len(pts)
    cy = sum(p[1] for p in pts) / len(pts)
    return cx, cy


def haversine_m(lon1, lat1, lon2, lat2):
    """Haversine distance in meters between two lon/lat points."""
    R = 6_371_000  # Earth radius in meters
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def extract_feature_data(feature):
    """Extract centroid and properties from a GeoJSON feature."""
    props = feature.get("properties", {})
    geom = feature.get("geometry", {})
    coords = geom.get("coordinates", [])
    lon, lat = polygon_centroid(coords)
    return {
        "lon": lon,
        "lat": lat,
        "count_low_soc": props.get("count_low_soc", 0),
        "mean_soc": props.get("mean_soc", 0.0),
        "estimated_chargers": props.get("estimated_chargers", 0),
        "quality_score": props.get("quality_score", 0.0),
        "unique_vehicles": props.get("unique_vehicles", 0),
        "soc_urgency": props.get("soc_urgency", 0.0),
        "dwell_score": props.get("dwell_score", 0.0),
        "temporal_spread": props.get("temporal_spread", 0.0),
        "cluster_id": props.get("cluster_id", -1),
    }


def match_clusters_across_runs(all_runs_data, match_radius_m=300.0):
    """Match clusters across runs by spatial proximity.
    
    Two clusters from different runs are considered 'the same location'
    if their centroids are within match_radius_m of each other.
    
    Returns a list of matched groups, where each group contains
    (run_index, feature_data) tuples.
    """
    # Flatten all features with run index
    all_points = []
    for run_idx, run_data in enumerate(all_runs_data):
        for feat in run_data:
            if feat["lon"] is not None and feat["lat"] is not None:
                all_points.append((run_idx, feat))

    # Greedy matching: assign each point to a group
    groups = []
    assigned = set()

    for i, (run_i, feat_i) in enumerate(all_points):
        if i in assigned:
            continue
        group = [(run_i, feat_i)]
        assigned.add(i)

        for j, (run_j, feat_j) in enumerate(all_points):
            if j in assigned:
                continue
            # Don't match points from the same run
            if run_j == run_i:
                continue
            dist = haversine_m(feat_i["lon"], feat_i["lat"], feat_j["lon"], feat_j["lat"])
            if dist <= match_radius_m:
                group.append((run_j, feat_j))
                assigned.add(j)

        groups.append(group)

    return groups


def analyze_geojson_deviation(*geojson_files, match_radius_m=300.0):
    """Analyse mehrerer GeoJSON-Polygon-Dateien und berechne Standardabweichungen.
    
    Args:
        *geojson_files: 2 oder mehr Pfade zu GeoJSON-Dateien
        match_radius_m: Radius in Metern, innerhalb dessen Cluster als
                        gleicher Standort betrachtet werden (default: 300m)
    
    Returns:
        dict mit Analyse-Ergebnissen (enthält auch _internal_data für Plotting)
    """
    if len(geojson_files) < 2:
        raise ValueError("Mindestens 2 GeoJSON-Dateien erforderlich")

    n_runs = len(geojson_files)
    all_runs_data = []
    run_summaries = []

    # --- Per-run Daten laden ---
    for idx, filepath in enumerate(geojson_files):
        if not os.path.exists(filepath):
            raise FileNotFoundError(f"Datei nicht gefunden: {filepath}")
        features = load_geojson(filepath)
        run_data = [extract_feature_data(f) for f in features]
        all_runs_data.append(run_data)
        run_summaries.append({
            "file": os.path.basename(filepath),
            "n_polygons": len(run_data),
            "total_low_soc": sum(d["count_low_soc"] for d in run_data),
            "total_chargers": sum(d["estimated_chargers"] for d in run_data),
            "mean_quality": float(np.mean([d["quality_score"] for d in run_data])) if run_data else 0.0,
        })

    # --- Globale Statistiken über Anzahl Polygone ---
    polygon_counts = [s["n_polygons"] for s in run_summaries]
    charger_totals = [s["total_chargers"] for s in run_summaries]
    quality_means = [s["mean_quality"] for s in run_summaries]

    global_stats = {
        "n_runs": n_runs,
        "polygon_count": {
            "mean": float(np.mean(polygon_counts)),
            "std": float(np.std(polygon_counts, ddof=1)) if n_runs > 1 else 0.0,
            "min": int(np.min(polygon_counts)),
            "max": int(np.max(polygon_counts)),
            "values": polygon_counts,
        },
        "total_chargers": {
            "mean": float(np.mean(charger_totals)),
            "std": float(np.std(charger_totals, ddof=1)) if n_runs > 1 else 0.0,
            "min": int(np.min(charger_totals)),
            "max": int(np.max(charger_totals)),
            "values": charger_totals,
        },
        "mean_quality_score": {
            "mean": float(np.mean(quality_means)),
            "std": float(np.std(quality_means, ddof=1)) if n_runs > 1 else 0.0,
            "values": [round(q, 4) for q in quality_means],
        },
    }

    # --- Cluster-Matching über Runs ---
    groups = match_clusters_across_runs(all_runs_data, match_radius_m=match_radius_m)

    # Analyse pro matched Location
    location_analyses = []
    stable_count = 0  # Locations die in ALLEN runs vorkommen
    partial_count = 0  # Locations die nur in manchen runs vorkommen

    for group in groups:
        runs_present = set(run_idx for run_idx, _ in group)
        n_present = len(runs_present)
        appearance_rate = n_present / n_runs

        lons = [f["lon"] for _, f in group]
        lats = [f["lat"] for _, f in group]
        counts = [f["count_low_soc"] for _, f in group]
        socs = [f["mean_soc"] for _, f in group]
        chargers = [f["estimated_chargers"] for _, f in group]
        qualities = [f["quality_score"] for _, f in group]
        vehicles = [f["unique_vehicles"] for _, f in group]

        # Räumliche Streuung: Standardabweichung der Zentren in Metern
        if len(lons) >= 2:
            center_lon = float(np.mean(lons))
            center_lat = float(np.mean(lats))
            distances = [haversine_m(center_lon, center_lat, lo, la) for lo, la in zip(lons, lats)]
            spatial_std_m = float(np.std(distances, ddof=1)) if len(distances) > 1 else 0.0
        else:
            center_lon = lons[0]
            center_lat = lats[0]
            spatial_std_m = 0.0

        loc = {
            "center_lon": round(center_lon, 6),
            "center_lat": round(center_lat, 6),
            "appearance_rate": round(appearance_rate, 2),
            "runs_present": sorted(runs_present),
            "spatial_std_m": round(spatial_std_m, 2),
            "count_low_soc": {
                "mean": round(float(np.mean(counts)), 1),
                "std": round(float(np.std(counts, ddof=1)), 1) if len(counts) > 1 else 0.0,
            },
            "mean_soc": {
                "mean": round(float(np.mean(socs)), 2),
                "std": round(float(np.std(socs, ddof=1)), 2) if len(socs) > 1 else 0.0,
            },
            "estimated_chargers": {
                "mean": round(float(np.mean(chargers)), 1),
                "std": round(float(np.std(chargers, ddof=1)), 1) if len(chargers) > 1 else 0.0,
            },
            "quality_score": {
                "mean": round(float(np.mean(qualities)), 3),
                "std": round(float(np.std(qualities, ddof=1)), 3) if len(qualities) > 1 else 0.0,
            },
            "unique_vehicles": {
                "mean": round(float(np.mean(vehicles)), 1),
                "std": round(float(np.std(vehicles, ddof=1)), 1) if len(vehicles) > 1 else 0.0,
            },
        }
        location_analyses.append(loc)

        if n_present == n_runs:
            stable_count += 1
        else:
            partial_count += 1

    # Sortiere: stabilste Locations zuerst, dann nach Quality
    location_analyses.sort(key=lambda x: (-x["appearance_rate"], -x["quality_score"]["mean"]))

    result = {
        "global_stats": global_stats,
        "run_summaries": run_summaries,
        "location_analysis": {
            "match_radius_m": match_radius_m,
            "total_unique_locations": len(groups),
            "stable_locations": stable_count,
            "partial_locations": partial_count,
            "stability_rate": round(stable_count / len(groups), 3) if groups else 0.0,
            "locations": location_analyses,
        },
        # Internal data for plotting (not serialized to JSON by default)
        "_all_runs_data": all_runs_data,
        "_geojson_files": list(geojson_files),
    }
    return result


def print_deviation_report(result):
    """Formatierte Ausgabe der Analyse-Ergebnisse."""
    gs = result["global_stats"]
    la = result["location_analysis"]

    print("=" * 70)
    print("  GEOJSON POLYGON ABWEICHUNGSANALYSE")
    print("=" * 70)
    print(f"  Anzahl Simulationsläufe: {gs['n_runs']}")
    print()

    # Per-run Übersicht
    print("  Per-Run Übersicht:")
    print(f"  {'Run':<6} {'Datei':<40} {'Polygone':>8} {'Charger':>8} {'Ø Quality':>10}")
    print("  " + "-" * 72)
    for i, rs in enumerate(result["run_summaries"]):
        print(f"  {i:<6} {rs['file']:<40} {rs['n_polygons']:>8} {rs['total_chargers']:>8} {rs['mean_quality']:>10.3f}")
    print()

    # Globale Statistiken
    print("  Globale Statistiken (über alle Runs):")
    print(f"  {'Metrik':<25} {'Mittelwert':>12} {'Std.Abw.':>12} {'Min':>8} {'Max':>8}")
    print("  " + "-" * 65)
    pc = gs["polygon_count"]
    print(f"  {'Anzahl Polygone':<25} {pc['mean']:>12.1f} {pc['std']:>12.1f} {pc['min']:>8} {pc['max']:>8}")
    tc = gs["total_chargers"]
    print(f"  {'Gesamt Chargers':<25} {tc['mean']:>12.1f} {tc['std']:>12.1f} {tc['min']:>8} {tc['max']:>8}")
    qs = gs["mean_quality_score"]
    print(f"  {'Ø Quality Score':<25} {qs['mean']:>12.3f} {qs['std']:>12.3f} {'':>8} {'':>8}")
    print()

    # Location Analyse
    print(f"  Standort-Analyse (Match-Radius: {la['match_radius_m']}m):")
    print(f"  Einzigartige Standorte gesamt:   {la['total_unique_locations']}")
    print(f"  Stabile Standorte (alle Runs):   {la['stable_locations']}")
    print(f"  Partielle Standorte:             {la['partial_locations']}")
    print(f"  Stabilitätsrate:                 {la['stability_rate']:.1%}")
    print()

    if la["locations"]:
        print(f"  {'#':<4} {'Lon':>10} {'Lat':>10} {'Rate':>6} {'Spatial σ':>10} "
              f"{'Ø SOC':>7} {'σ SOC':>7} {'Ø Charger':>10} {'σ Charger':>10} {'Ø Quality':>10}")
        print("  " + "-" * 94)
        for i, loc in enumerate(la["locations"]):
            print(f"  {i+1:<4} {loc['center_lon']:>10.5f} {loc['center_lat']:>10.5f} "
                  f"{loc['appearance_rate']:>5.0%} {loc['spatial_std_m']:>9.1f}m "
                  f"{loc['mean_soc']['mean']:>7.1f} {loc['mean_soc']['std']:>7.1f} "
                  f"{loc['estimated_chargers']['mean']:>10.1f} {loc['estimated_chargers']['std']:>10.1f} "
                  f"{loc['quality_score']['mean']:>10.3f}")
    print()
    print("=" * 70)


def plot_cluster_deviation_map(result, all_runs_data, geojson_files, out_html="cluster_deviation_map.html", match_radius_m=300.0):
    """Erzeugt eine interaktive Karte mit gematchten Clustern und Abweichungs-Ellipsen.
    
    - Jeder gematchte Standort wird als Kreis mit Standardabweichungs-Radius gezeigt
    - Individuelle Cluster-Zentren pro Run werden als farbige Punkte dargestellt
    - Verbindungslinien zeigen die Zuordnung
    - Tooltips zeigen Statistiken
    """
    import folium
    from folium import plugins

    la = result["location_analysis"]
    locations = la["locations"]
    
    if not locations:
        print("Keine Standorte zum Plotten vorhanden.")
        return

    # Karten-Zentrum berechnen
    all_lats = [loc["center_lat"] for loc in locations]
    all_lons = [loc["center_lon"] for loc in locations]
    center_lat = sum(all_lats) / len(all_lats)
    center_lon = sum(all_lons) / len(all_lons)

    m = folium.Map(location=[center_lat, center_lon], zoom_start=14, tiles="OpenStreetMap")

    # Farbpalette für Runs
    run_colors = ["#e41a1c", "#377eb8", "#4daf4a", "#984ea3", "#ff7f00", 
                  "#a65628", "#f781bf", "#999999", "#66c2a5", "#fc8d62"]
    n_runs = result["global_stats"]["n_runs"]

    # Legende als Feature Group pro Run
    run_groups = {}
    for i in range(n_runs):
        name = os.path.basename(geojson_files[i]) if i < len(geojson_files) else f"Run {i}"
        color = run_colors[i % len(run_colors)]
        run_groups[i] = folium.FeatureGroup(name=f"<span style='color:{color}'>● Run {i}: {name}</span>")

    # Matched-Locations Layer
    matched_layer = folium.FeatureGroup(name="⊕ Gematchte Zentren (Ø)")
    deviation_layer = folium.FeatureGroup(name="◎ Standardabweichung (σ)")
    stable_layer = folium.FeatureGroup(name="✓ Stabile Standorte (alle Runs)")

    # Re-match clusters um die Rohdaten zu haben
    groups = match_clusters_across_runs(all_runs_data, match_radius_m=match_radius_m)

    for grp_idx, (group, loc_stats) in enumerate(zip(groups, locations)):
        center_lon_g = loc_stats["center_lon"]
        center_lat_g = loc_stats["center_lat"]
        spatial_std = loc_stats["spatial_std_m"]
        appearance = loc_stats["appearance_rate"]
        n_present = len(loc_stats["runs_present"])

        is_stable = (n_present == n_runs)
        
        # Tooltip mit Statistiken
        tooltip_text = (
            f"<b>Standort #{grp_idx + 1}</b><br>"
            f"Vorkommen: {n_present}/{n_runs} Runs ({appearance:.0%})<br>"
            f"Räumliche σ: {spatial_std:.1f}m<br>"
            f"Ø SOC: {loc_stats['mean_soc']['mean']:.1f}% (σ {loc_stats['mean_soc']['std']:.1f})<br>"
            f"Ø Chargers: {loc_stats['estimated_chargers']['mean']:.1f} (σ {loc_stats['estimated_chargers']['std']:.1f})<br>"
            f"Ø Quality: {loc_stats['quality_score']['mean']:.3f} (σ {loc_stats['quality_score']['std']:.3f})<br>"
            f"Ø Vehicles: {loc_stats['unique_vehicles']['mean']:.0f}"
        )

        # Gematchtes Zentrum (schwarzer Punkt)
        folium.CircleMarker(
            location=[center_lat_g, center_lon_g],
            radius=8,
            color="black",
            fill=True,
            fill_color="black" if is_stable else "white",
            fill_opacity=0.8,
            weight=2,
            popup=folium.Popup(tooltip_text, max_width=300),
            tooltip=f"Standort #{grp_idx + 1} ({appearance:.0%})",
        ).add_to(matched_layer)

        # Standardabweichungs-Kreis
        if spatial_std > 0:
            folium.Circle(
                location=[center_lat_g, center_lon_g],
                radius=spatial_std,
                color="#333333",
                weight=2,
                dash_array="5,5",
                fill=True,
                fill_color="#ffcc00" if is_stable else "#ff6666",
                fill_opacity=0.15,
                popup=f"σ = {spatial_std:.1f}m",
            ).add_to(deviation_layer)

        # Stabilitäts-Indikator (großer Kreis)
        if is_stable:
            folium.Circle(
                location=[center_lat_g, center_lon_g],
                radius=30,
                color="#00aa00",
                weight=3,
                fill=True,
                fill_color="#00aa00",
                fill_opacity=0.15,
            ).add_to(stable_layer)

        # Individuelle Cluster-Punkte pro Run + Verbindungslinien
        for run_idx, feat_data in group:
            color = run_colors[run_idx % len(run_colors)]
            pt_lat = feat_data["lat"]
            pt_lon = feat_data["lon"]

            # Punkt pro Run
            folium.CircleMarker(
                location=[pt_lat, pt_lon],
                radius=6,
                color=color,
                fill=True,
                fill_color=color,
                fill_opacity=0.7,
                weight=1,
                tooltip=(
                    f"Run {run_idx} | SOC: {feat_data['mean_soc']:.1f}% | "
                    f"Chargers: {feat_data['estimated_chargers']} | "
                    f"Quality: {feat_data['quality_score']:.3f} | "
                    f"Vehicles: {feat_data['unique_vehicles']}"
                ),
            ).add_to(run_groups[run_idx])

            # Verbindungslinie zum Zentrum
            folium.PolyLine(
                locations=[[pt_lat, pt_lon], [center_lat_g, center_lon_g]],
                color=color,
                weight=1.5,
                opacity=0.5,
                dash_array="3,6",
            ).add_to(run_groups[run_idx])

    # Alle Layer zur Karte hinzufügen
    deviation_layer.add_to(m)
    stable_layer.add_to(m)
    matched_layer.add_to(m)
    for rg in run_groups.values():
        rg.add_to(m)

    folium.LayerControl(collapsed=False).add_to(m)

    # Info-Box oben rechts
    gs = result["global_stats"]
    info_html = f"""
    <div style="position:fixed; top:10px; right:10px; z-index:9999;
                background:white; padding:12px 16px; border-radius:8px;
                border:2px solid #333; font-family:monospace; font-size:12px;
                box-shadow: 2px 2px 6px rgba(0,0,0,0.3); max-width:320px;">
        <b>Cluster-Abweichungsanalyse</b><br>
        <hr style="margin:4px 0;">
        Runs: {gs['n_runs']} | Match-Radius: {la['match_radius_m']:.0f}m<br>
        Polygone: Ø {gs['polygon_count']['mean']:.1f} (σ {gs['polygon_count']['std']:.1f})<br>
        Chargers: Ø {gs['total_chargers']['mean']:.0f} (σ {gs['total_chargers']['std']:.1f})<br>
        <hr style="margin:4px 0;">
        Standorte: {la['total_unique_locations']} total<br>
        ✓ Stabil (alle Runs): {la['stable_locations']}<br>
        ◐ Partiell: {la['partial_locations']}<br>
        Stabilitätsrate: <b>{la['stability_rate']:.0%}</b>
    </div>
    """
    m.get_root().html.add_child(folium.Element(info_html))

    m.save(out_html)
    print(f"Karte gespeichert: {out_html}")
    return out_html


# --- CLI-Nutzung ---
if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Verwendung: python cs_trial_deviation.py <file1.geojson> <file2.geojson> [file3.geojson ...]")
        print()
        print("Optionen:")
        print("  --radius=N    Match-Radius in Metern (default: 300)")
        print("  --json        Ausgabe als JSON statt formatiertem Text")
        print("  --plot        Interaktive Karte erzeugen (cluster_deviation_map.html)")
        print("  --out=FILE    Ausgabedatei für Karte (default: cluster_deviation_map.html)")
        sys.exit(1)

    files = []
    match_radius = 300.0
    output_json = False
    do_plot = False
    plot_out = "cluster_deviation_map3.html"

    for arg in sys.argv[1:]:
        if arg.startswith("--radius="):
            match_radius = float(arg.split("=", 1)[1])
        elif arg == "--json":
            output_json = True
        elif arg == "--plot":
            do_plot = True
        elif arg.startswith("--out="):
            plot_out = arg.split("=", 1)[1]
        else:
            files.append(arg)

    if len(files) < 2:
        print("Fehler: Mindestens 2 GeoJSON-Dateien erforderlich")
        sys.exit(1)

    result = analyze_geojson_deviation(*files, match_radius_m=match_radius)

    if output_json:
        # Remove internal data before JSON serialization
        result_clean = {k: v for k, v in result.items() if not k.startswith("_")}
        print(json.dumps(result_clean, indent=2, ensure_ascii=False))
    else:
        print_deviation_report(result)

    if do_plot:
        plot_cluster_deviation_map(
            result,
            result["_all_runs_data"],
            result["_geojson_files"],
            out_html=plot_out,
            match_radius_m=match_radius,
        )
