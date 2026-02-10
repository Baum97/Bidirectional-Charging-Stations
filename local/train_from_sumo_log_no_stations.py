def process_sumo_log_no_stations(default_log, out_csv, out_geojson, out_xml, net_file=None, out_heatmap_json=None, power_grid_manager=None, fast_mode=True, existing_stations_file=None):
    import os
    import math
    import json
    from collections import defaultdict
    import xml.etree.ElementTree as ET

    import numpy as np
    import pandas as pd
    from sklearn.cluster import DBSCAN

    try:
        import sumolib
        HAS_SUMOLIB = True
    except Exception:
        sumolib = None
        HAS_SUMOLIB = False

    # Fast mode: Optimized parameters for speed (default)
    # Slow mode: Original parameters for granular clustering
    if fast_mode:
        SOC_THRESHOLD = 30.0      # percent
        EPS_METERS = 35.0         # INCREASED from 25 - merges nearby clusters faster
        MIN_SAMPLES = 10          # INCREASED from 5 - requires denser concentrations, fewer noise points
        MAX_CLUSTER_SIZE = 300    # INCREASED from 200 - larger chunks, fewer splits
        GRID_PRESCALE = 500.0     # NEW: Pre-cluster with spatial grid before DBSCAN (500m cells)
        SAMPLE_RATE = 0.5         # NEW: Use 50% of low-SOC points, randomly sampled
    else:
        SOC_THRESHOLD = 30.0
        EPS_METERS = 25.0
        MIN_SAMPLES = 5
        MAX_CLUSTER_SIZE = 200
        GRID_PRESCALE = None      # Disable pre-clustering
        SAMPLE_RATE = 1.0         # Use all points
    
    SPEED_THRESHOLD = 2.0     # m/s - only consider stopped/slow vehicles
    BUFFER_MARGIN = 20.0      # meters added to cluster spread
    POLY_POINTS = 32

    # heuristics for charger estimation
    AVG_SESSION_KWH = 20.0
    CHARGER_KW = 50.0
    UTILIZATION = 0.75

    def read_log(path):
        if not os.path.exists(path):
            raise FileNotFoundError(path)
        df = pd.read_csv(path)
        # normalize column names for coordinates and soc
        if "position_x" in df.columns and "position_y" in df.columns:
            df = df.rename(columns={"position_x": "x", "position_y": "y"})
        # enforce types
        df["x"] = pd.to_numeric(df["x"], errors="coerce")
        df["y"] = pd.to_numeric(df["y"], errors="coerce")
        if "soc_percent" in df.columns:
            df["soc_percent"] = pd.to_numeric(df["soc_percent"], errors="coerce")
        elif "soc" in df.columns:
            df["soc_percent"] = pd.to_numeric(df["soc"], errors="coerce")
        else:
            # if only absolute soc present, try to infer if it's 0..1 or already percent
            df["soc_percent"] = pd.to_numeric(df.get("soc", 0), errors="coerce") * 100.0
        # time numeric
        if "time" in df.columns:
            df["time"] = pd.to_numeric(df["time"], errors="coerce")
        return df

    def cluster_low_soc_points(coords, eps=EPS_METERS, min_samples=MIN_SAMPLES):
        if len(coords) == 0:
            return np.array([]), np.array([])
        db = DBSCAN(eps=eps, min_samples=min_samples, metric="euclidean")
        labels = db.fit_predict(coords)
        return labels

    def polygon_around_points(cx, cy, radius, n_points=POLY_POINTS):
        pts = []
        for i in range(n_points):
            angle = 2 * math.pi * i / n_points
            px = cx + radius * math.cos(angle)
            py = cy + radius * math.sin(angle)
            pts.append([px, py])
        pts.append(pts[0])
        return pts

    def estimate_chargers(count_events, sim_hours, avg_session_kwh=AVG_SESSION_KWH, charger_kw=CHARGER_KW, utilization=UTILIZATION):
        events_per_hour = count_events / sim_hours if sim_hours > 0 else count_events
        energy_kwh_per_hour = events_per_hour * avg_session_kwh
        capacity_kwh_per_hour_per_charger = charger_kw * utilization
        if capacity_kwh_per_hour_per_charger <= 0:
            return 1
        n = math.ceil(energy_kwh_per_hour / capacity_kwh_per_hour_per_charger)
        return max(1, n)

    def find_nearest_lane_id(net, x, y):
        if not HAS_SUMOLIB or net is None:
            return None
        try:
            lane = net.getNearestLane((x, y))
            return lane.getID() if lane else None
        except Exception:
            return None

    def load_existing_charging_stations(stations_file, net):
        """Load existing charging stations from XML file and get their SUMO coordinates.
        
        Uses sumolib to resolve lane positions to x,y coordinates.
        Falls back to edge midpoint if interpolation fails.
        """
        existing_stations = []
        if not stations_file or not os.path.exists(stations_file):
            return existing_stations
        
        if not net or not HAS_SUMOLIB:
            print("WARNING: Network file required to resolve charging station coordinates")
            return existing_stations
        
        try:
            tree = ET.parse(stations_file)
            root = tree.getroot()
            
            for cs_elem in root.findall('.//chargingStation'):
                cs_id = cs_elem.get('id')
                lane_id = cs_elem.get('lane')
                start_pos_str = cs_elem.get('startPos')
                end_pos_str = cs_elem.get('endPos')
                
                if not lane_id:
                    continue
                
                try:
                    start_pos = float(start_pos_str) if start_pos_str else 0.0
                except (ValueError, TypeError):
                    start_pos = 0.0
                
                try:
                    end_pos = float(end_pos_str) if end_pos_str else start_pos + 5.0
                except (ValueError, TypeError):
                    end_pos = start_pos + 5.0
                
                # Use midpoint of the charging station
                mid_pos = (start_pos + end_pos) / 2.0
                
                # Try to get the lane directly
                lane = None
                try:
                    lane = net.getLane(lane_id)
                except Exception:
                    pass
                
                if lane is None:
                    # Try the edge ID (lane_id without the trailing _N)
                    edge_id = lane_id.rsplit('_', 1)[0] if '_' in lane_id else lane_id
                    try:
                        edge = net.getEdge(edge_id)
                        if edge and edge.getLanes():
                            lane = edge.getLanes()[0]
                    except Exception:
                        pass
                
                if lane is None:
                    print(f"  Warning: Lane/Edge not found for station {cs_id} (lane={lane_id})")
                    continue
                
                # Get position using lane shape interpolation
                shape = lane.getShape()
                if not shape or len(shape) < 2:
                    # Fallback: use edge shape
                    try:
                        edge = lane.getEdge()
                        shape = edge.getShape() if edge else None
                    except Exception:
                        shape = None
                
                if not shape or len(shape) < 1:
                    print(f"  Warning: No shape for station {cs_id}")
                    continue
                
                # Interpolate position along shape at mid_pos
                x, y = shape[0]
                cumulative_dist = 0.0
                found = False
                
                for idx in range(len(shape) - 1):
                    p1 = shape[idx]
                    p2 = shape[idx + 1]
                    seg_len = math.sqrt((p2[0] - p1[0])**2 + (p2[1] - p1[1])**2)
                    
                    if cumulative_dist + seg_len >= mid_pos and seg_len > 0:
                        t = (mid_pos - cumulative_dist) / seg_len
                        t = max(0.0, min(1.0, t))
                        x = p1[0] + t * (p2[0] - p1[0])
                        y = p1[1] + t * (p2[1] - p1[1])
                        found = True
                        break
                    cumulative_dist += seg_len
                
                if not found:
                    # mid_pos beyond shape length - use last point
                    x, y = shape[-1]
                
                existing_stations.append({
                    'id': cs_id,
                    'x': x,
                    'y': y,
                    'lane_id': lane_id,
                    'mid_pos': mid_pos
                })
            
            print(f"Loaded {len(existing_stations)} existing charging stations from {stations_file}")
        except Exception as e:
            print(f"Warning: Could not load existing charging stations: {e}")
            import traceback
            traceback.print_exc()
        
        return existing_stations

    def is_near_existing_station(center_x, center_y, existing_stations, radius_m=500.0, cluster_radius=0.0):
        """Check if a cluster polygon could overlap with any existing charging station area.
        
        The effective exclusion distance is radius_m + cluster_radius, so that
        no part of the polygon can fall within radius_m of a station.
        """
        if not existing_stations:
            return False, None, None
        
        effective_radius = radius_m + cluster_radius
        min_distance = float('inf')
        nearest_station = None
        
        for station in existing_stations:
            dist = math.sqrt((center_x - station['x'])**2 + (center_y - station['y'])**2)
            if dist < min_distance:
                min_distance = dist
                nearest_station = station['id']
            
            if dist <= effective_radius:
                return True, dist, nearest_station
        
        return False, min_distance, nearest_station

    def compute_cluster_quality_score(cluster_points, sim_hours):
        """Multi-criteria scoring for cluster quality.
        
        Combines multiple factors beyond just low SOC count:
        - unique_vehicles: Number of distinct vehicles affected (diversity of demand)
        - soc_urgency: How critically low the SOC levels are (lower = more urgent)
        - dwell_time: How long vehicles stay in the area with low SOC (longer = better location)
        - temporal_spread: Demand across different time periods (wider = more consistent need)
        - recurring_demand: Vehicles that return to the same area multiple times
        
        Returns a normalized score 0..1 (higher = better candidate for charging station).
        """
        points = cluster_points
        
        # 1. Unique vehicles (0..1) - more unique vehicles = stronger signal
        if "veh_id" in points.columns:
            unique_vehs = points["veh_id"].nunique()
            total_points = len(points)
            # Ratio of unique vehicles to total observations
            # High ratio = many different vehicles, not just one stuck car
            veh_diversity = min(1.0, unique_vehs / max(1, total_points) * 10.0)
        else:
            unique_vehs = 0
            veh_diversity = 0.5  # neutral if unknown
        
        # 2. SOC urgency (0..1) - lower average SOC = more urgent need
        mean_soc = float(points["soc_percent"].mean())
        # SOC 0% -> urgency 1.0, SOC 30% -> urgency 0.0
        soc_urgency = max(0.0, min(1.0, (SOC_THRESHOLD - mean_soc) / SOC_THRESHOLD))
        
        # 3. Dwell time (0..1) - how long vehicles stay at low SOC in this area
        if "time" in points.columns and "veh_id" in points.columns:
            # For each vehicle, compute time span in this cluster
            veh_times = points.groupby("veh_id")["time"].agg(["min", "max"])
            veh_dwell = (veh_times["max"] - veh_times["min"]).mean()
            # Normalize: 300s (5min) dwell = 0.5, 1800s (30min) = 1.0
            dwell_score = min(1.0, veh_dwell / 1800.0) if not np.isnan(veh_dwell) else 0.3
        else:
            dwell_score = 0.3  # neutral
        
        # 4. Temporal spread (0..1) - demand across different hours
        if "time" in points.columns:
            hours = (points["time"] / 3600.0).astype(int)
            unique_hours = hours.nunique()
            sim_hours_int = max(1, int(sim_hours))
            # More hours with demand = more consistent need
            temporal_spread = min(1.0, unique_hours / max(1, sim_hours_int))
        else:
            temporal_spread = 0.3
        
        # 5. Recurring demand (0..1) - vehicles returning to same area
        if "veh_id" in points.columns:
            veh_counts = points["veh_id"].value_counts()
            avg_visits = float(veh_counts.mean())
            # Average 3+ observations per vehicle = strong recurring signal
            recurring = min(1.0, avg_visits / 5.0)
        else:
            recurring = 0.3
        
        # Weighted combination
        score = (
            0.25 * veh_diversity +     # 25% - many different vehicles need charging
            0.25 * soc_urgency +        # 25% - critically low SOC levels
            0.10 * dwell_score +        # 10% - vehicles stay long (good for charging)
            0.15 * temporal_spread +    # 15% - consistent demand across time
            0.25 * recurring            # 25% - vehicles return repeatedly
        )
        
        return score, {
            "unique_vehicles": int(unique_vehs) if "veh_id" in points.columns else 0,
            "veh_diversity": round(veh_diversity, 3),
            "soc_urgency": round(soc_urgency, 3),
            "dwell_score": round(dwell_score, 3),
            "temporal_spread": round(temporal_spread, 3),
            "recurring": round(recurring, 3),
            "total_score": round(score, 3)
        }

    # Minimum quality score threshold - clusters below this are not worth a station
    MIN_QUALITY_SCORE = 0.15

    df = read_log(default_log)
    total_rows = len(df)
    print(f"Read {total_rows} rows from {default_log}")

    # detect if any charging stations were logged
    has_station_col = "charging_station" in df.columns
    stations_present = False
    if has_station_col:
        stations_present = df["charging_station"].notnull().astype(bool).any()
    if stations_present:
        print("NOTE: Some charging_station entries exist in the log. This script focuses on low-SOC hotspots when no stations are present.")
        # We proceed but warn the user.

    # select low-SOC rows
    low_df = df[df["soc_percent"] <= SOC_THRESHOLD].copy()
    if len(low_df) == 0:
        print(f"No rows with soc_percent <= {SOC_THRESHOLD} found. Nothing to do.")
        return
    print(f"Low-SOC rows (<= {SOC_THRESHOLD}%): {len(low_df)}")
    
    # Filter by speed if available (only consider stopped/slow vehicles)
    if "speed" in low_df.columns:
        low_df["speed"] = pd.to_numeric(low_df["speed"], errors="coerce")
        before_filter = len(low_df)
        low_df = low_df[low_df["speed"] <= SPEED_THRESHOLD].copy()
        print(f"Filtered by speed (<= {SPEED_THRESHOLD} m/s): {len(low_df)} rows (removed {before_filter - len(low_df)} fast-moving vehicles)")
        if len(low_df) == 0:
            print("No slow/stopped vehicles with low SOC. Nothing to do.")
            return

    # OPTIMIZATION: Sample data for faster clustering if in fast_mode
    if fast_mode and SAMPLE_RATE < 1.0:
        sample_size = max(1000, int(len(low_df) * SAMPLE_RATE))  # At least 1000 samples
        low_df = low_df.sample(n=sample_size, random_state=42).reset_index(drop=True)
        print(f"Sampled {len(low_df)} points ({SAMPLE_RATE*100:.0f}%) for clustering")

    coords = low_df[["x","y"]].to_numpy()
    
    # OPTIMIZATION: Pre-cluster with spatial grid before DBSCAN (divide-and-conquer)
    if fast_mode and GRID_PRESCALE is not None:
        print(f"Pre-clustering with {GRID_PRESCALE}m spatial grid...")
        x_min, x_max, y_min, y_max = coords[:, 0].min(), coords[:, 0].max(), coords[:, 1].min(), coords[:, 1].max()
        
        # Create grid cells
        x_cells = int(np.ceil((x_max - x_min) / GRID_PRESCALE))
        y_cells = int(np.ceil((y_max - y_min) / GRID_PRESCALE))
        
        # Assign each point to a grid cell
        low_df["grid_x"] = ((coords[:, 0] - x_min) / GRID_PRESCALE).astype(int).clip(0, x_cells - 1)
        low_df["grid_y"] = ((coords[:, 1] - y_min) / GRID_PRESCALE).astype(int).clip(0, y_cells - 1)
        
        # Cluster within each grid cell
        all_labels = np.full(len(coords), -1, dtype=int)
        label_counter = 0
        
        for (gx, gy), grid_group in low_df.groupby(["grid_x", "grid_y"]):
            if len(grid_group) < MIN_SAMPLES:
                continue
            
            grid_coords = grid_group[["x", "y"]].to_numpy()
            grid_labels = cluster_low_soc_points(grid_coords, eps=EPS_METERS, min_samples=MIN_SAMPLES)
            
            # Map grid labels to global labels
            for local_label in set(grid_labels):
                if local_label == -1:
                    continue
                all_labels[grid_group.index[grid_labels == local_label]] = label_counter
                label_counter += 1
        
        labels = all_labels
        print(f"Grid pre-clustering complete: {label_counter} clusters found")
    else:
        # Original DBSCAN clustering on all points
        labels = cluster_low_soc_points(coords, eps=EPS_METERS, min_samples=MIN_SAMPLES)
    
    low_df["cluster"] = labels
    
    # Clean up temporary grid columns if they exist
    if "grid_x" in low_df.columns:
        low_df = low_df.drop(columns=["grid_x", "grid_y"])
    def split_large_cluster_grid(subset_df, max_size=MAX_CLUSTER_SIZE):
        """Split oversized cluster into spatial grid cells"""
        if len(subset_df) <= max_size:
            return [subset_df]
        
        print(f"  Grid-splitting mega-cluster with {len(subset_df)} points into ~{max_size}-point chunks...")
        
        # Calculate grid dimensions
        x_min, x_max = subset_df["x"].min(), subset_df["x"].max()
        y_min, y_max = subset_df["y"].min(), subset_df["y"].max()
        
        # Estimate grid cells needed
        num_cells = math.ceil(len(subset_df) / max_size)
        grid_side = math.ceil(math.sqrt(num_cells))
        
        cell_width = (x_max - x_min) / grid_side if grid_side > 0 else 1.0
        cell_height = (y_max - y_min) / grid_side if grid_side > 0 else 1.0
        
        # Avoid division by zero
        if cell_width == 0:
            cell_width = 1.0
        if cell_height == 0:
            cell_height = 1.0
        
        # Assign each point to a grid cell
        subset_df = subset_df.copy()
        subset_df["grid_x"] = ((subset_df["x"] - x_min) / cell_width).astype(int)
        subset_df["grid_y"] = ((subset_df["y"] - y_min) / cell_height).astype(int)
        
        # Group by grid cell
        result = []
        for (gx, gy), group in subset_df.groupby(["grid_x", "grid_y"]):
            if len(group) >= MIN_SAMPLES:  # Only keep cells with enough points
                group_clean = group.drop(columns=["grid_x", "grid_y"])
                result.append(group_clean)
        
        return result if result else [subset_df.drop(columns=["grid_x", "grid_y"], errors='ignore')]

    clusters = {}
    cluster_counter = 0
    for lbl in sorted(set(labels)):
        if lbl == -1:
            continue
        subset = low_df[low_df["cluster"] == lbl]
        
        # Split if cluster is too large
        if len(subset) > MAX_CLUSTER_SIZE:
            print(f"Cluster {lbl} has {len(subset)} points (>{MAX_CLUSTER_SIZE}), splitting...")
            sub_clusters = split_large_cluster_grid(subset, MAX_CLUSTER_SIZE)
            print(f"  Split into {len(sub_clusters)} sub-clusters")
            
            for sub_subset in sub_clusters:
                if len(sub_subset) < MIN_SAMPLES:
                    continue  # Skip tiny fragments
                    
                cx = float(sub_subset["x"].mean())
                cy = float(sub_subset["y"].mean())
                count = len(sub_subset)
                mean_soc = float(sub_subset["soc_percent"].mean())
                dists = np.sqrt((sub_subset["x"] - cx)**2 + (sub_subset["y"] - cy)**2)
                max_dist = float(dists.max()) if len(dists) > 0 else 0.0
                radius = max(25.0, max_dist + BUFFER_MARGIN)
                # Select available columns for points
                point_cols = [col for col in ["x","y","time","veh_id","soc_percent"] if col in sub_subset.columns]
                clusters[cluster_counter] = {
                    "cluster": cluster_counter,
                    "center_x": cx,
                    "center_y": cy,
                    "count": int(count),
                    "mean_soc": mean_soc,
                    "radius": radius,
                    "points": sub_subset[point_cols]
                }
                cluster_counter += 1
        else:
            cx = float(subset["x"].mean())
            cy = float(subset["y"].mean())
            count = len(subset)
            mean_soc = float(subset["soc_percent"].mean())
            dists = np.sqrt((subset["x"] - cx)**2 + (subset["y"] - cy)**2)
            max_dist = float(dists.max()) if len(dists) > 0 else 0.0
            radius = max(25.0, max_dist + BUFFER_MARGIN)
            point_cols = [col for col in ["x","y","time","veh_id","soc_percent"] if col in subset.columns]
            clusters[cluster_counter] = {
                "cluster": cluster_counter,
                "center_x": cx,
                "center_y": cy,
                "count": int(count),
                "mean_soc": mean_soc,
                "radius": radius,
                "points": subset[point_cols]
            }
            cluster_counter += 1

    if not clusters:
        print("No clusters found (all points considered noise). Consider reducing eps or min_samples.")
        return

    # estimate simulation hours from time column if provided
    if "time" in df.columns:
        tmin = df["time"].min()
        tmax = df["time"].max()
        sim_hours = max( (tmax - tmin) / 3600.0, 1.0/3600.0 )
        print(f"Estimated sim duration: {sim_hours:.3f} hours (time range {tmin} .. {tmax})")
    else:
        sim_hours = 1.0
        print("No time column found; assuming sim_hours=1.0")

    # build CSV rows and GeoJSON features
    csv_rows = []
    features = []
    # try load network for coordinate conversion
    net = None
    if HAS_SUMOLIB and net_file:
        try:
            net = sumolib.net.readNet(net_file)
            print(f"Loaded SUMO network: {net_file}")
        except Exception as e:
            print(f"Could not load network: {e}")
            net = None

    # Load existing charging stations if provided
    existing_stations = []
    STATION_BUFFER = 100.0
    if existing_stations_file:
        existing_stations = load_existing_charging_stations(existing_stations_file, net)
        if existing_stations:
            print(f"Loaded {len(existing_stations)} existing stations - excluding new polygons within {STATION_BUFFER}m radius:")
            for s in existing_stations:
                print(f"  Station {s['id']}: SUMO coords ({s['x']:.1f}, {s['y']:.1f}) on lane {s['lane_id']}")
        else:
            print(f"WARNING: No station coordinates could be resolved from {existing_stations_file} (network required)")
    
    EXISTING_STATION_BUFFER = STATION_BUFFER  # meters - no polygon within this radius of existing stations

    # Compute quality scores for all clusters
    print(f"\nScoring {len(clusters)} clusters with multi-criteria analysis...")
    skipped_quality = 0
    skipped_station_proximity = 0

    for i, c in enumerate(sorted(clusters.values(), key=lambda x: x["count"], reverse=True)):
        # Multi-criteria quality scoring
        quality_score, score_details = compute_cluster_quality_score(c["points"], sim_hours)
        c["quality_score"] = quality_score
        c["score_details"] = score_details
        
        if quality_score < MIN_QUALITY_SCORE:
            skipped_quality += 1
            print(f"[SKIP] Cluster {c['cluster']} - quality score {quality_score:.3f} < {MIN_QUALITY_SCORE} "
                  f"(vehicles={score_details['unique_vehicles']}, urgency={score_details['soc_urgency']:.2f}, "
                  f"dwell={score_details['dwell_score']:.2f})")
            continue

        est_chargers = estimate_chargers(c["count"], sim_hours, avg_session_kwh=AVG_SESSION_KWH,
                                         charger_kw=CHARGER_KW, utilization=UTILIZATION)
        
        # Check grid capacity at this location if power grid manager available
        grid_quality = 'unknown'
        grid_capacity_kw = 0.0
        grid_distance_m = 0.0
        
        if power_grid_manager:
            try:
                # Convert SUMO coords to lon/lat for grid query
                if net:
                    lon, lat = net.convertXY2LonLat(c["center_x"], c["center_y"])
                else:
                    lon, lat = c["center_x"], c["center_y"]  # Fallback
                
                grid_info = power_grid_manager.get_grid_capacity_at_location(lon, lat, radius_m=500)
                grid_quality = grid_info['grid_quality']
                grid_capacity_kw = grid_info['available_power_kw']
                grid_distance_m = grid_info['distance_m']
                
                # Skip locations with no grid access
                if grid_quality == 'none':
                    print(f"[SKIP] Cluster {c['cluster']} - no grid access within 500m")
                    continue
                
                # Adjust charger estimate based on grid capacity
                max_chargers_by_grid = int(grid_capacity_kw / CHARGER_KW)
                if max_chargers_by_grid < est_chargers:
                    print(f"[INFO] Cluster {c['cluster']} - grid limits chargers to {max_chargers_by_grid} (was {est_chargers})")
                    est_chargers = max_chargers_by_grid
                    if est_chargers == 0:
                        continue  # Skip if grid can't support any chargers
            except Exception as e:
                print(f"[WARNING] Grid check failed for cluster {c['cluster']}: {e}")
        
        # Check if cluster is too close to existing charging stations
        if existing_stations:
            is_near, distance, nearest_id = is_near_existing_station(
                c["center_x"], c["center_y"], existing_stations,
                radius_m=EXISTING_STATION_BUFFER,
                cluster_radius=c["radius"]
            )
            if is_near:
                skipped_station_proximity += 1
                print(f"[SKIP] Cluster {c['cluster']} at ({c['center_x']:.1f}, {c['center_y']:.1f}) r={c['radius']:.0f}m - "
                      f"too close to station '{nearest_id}' (distance: {distance:.1f}m, "
                      f"effective limit: {EXISTING_STATION_BUFFER + c['radius']:.0f}m)")
                continue
        
        csv_rows.append({
            "cluster_id": c["cluster"],
            "center_x": c["center_x"],
            "center_y": c["center_y"],
            "count_low_soc": c["count"],
            "mean_soc": c["mean_soc"],
            "radius_m": c["radius"],
            "estimated_chargers": est_chargers,
            "quality_score": c["quality_score"],
            "unique_vehicles": c["score_details"]["unique_vehicles"],
            "soc_urgency": c["score_details"]["soc_urgency"],
            "dwell_score": c["score_details"]["dwell_score"],
            "temporal_spread": c["score_details"]["temporal_spread"],
            "grid_quality": grid_quality,
            "grid_capacity_kw": grid_capacity_kw,
            "grid_distance_m": grid_distance_m
        })
        poly = polygon_around_points(c["center_x"], c["center_y"], c["radius"], n_points=POLY_POINTS)
        
        # Convert SUMO coordinates to lat/lon for GeoJSON
        if net:
            poly_latlon = []
            for px, py in poly:
                try:
                    lon, lat = net.convertXY2LonLat(px, py)
                    poly_latlon.append([lon, lat])
                except Exception as e:
                    print(f"Warning: Could not convert coordinates ({px}, {py}): {e}")
                    poly_latlon.append([px, py])  # fallback to SUMO coords
            poly = poly_latlon
        
        prop = {
            "cluster_id": c["cluster"],
            "count_low_soc": c["count"],
            "mean_soc": c["mean_soc"],
            "estimated_chargers": est_chargers,
            "quality_score": round(c["quality_score"], 3),
            "unique_vehicles": c["score_details"]["unique_vehicles"],
            "soc_urgency": c["score_details"]["soc_urgency"],
            "dwell_score": c["score_details"]["dwell_score"],
            "temporal_spread": c["score_details"]["temporal_spread"],
            "grid_quality": grid_quality,
            "grid_capacity_kw": grid_capacity_kw,
            "grid_distance_m": grid_distance_m
        }
        features.append({
            "type": "Feature",
            "properties": prop,
            "geometry": {
                "type": "Polygon",
                "coordinates": [poly]
            }
        })

    # save CSV
    out_df = pd.DataFrame(csv_rows)
    os.makedirs(os.path.dirname(out_csv), exist_ok=True)
    out_df.to_csv(out_csv, index=False)
    print("Wrote CSV:", out_csv)

    # save geojson
    geo = {"type": "FeatureCollection", "features": features}
    os.makedirs(os.path.dirname(out_geojson), exist_ok=True)
    with open(out_geojson, "w", encoding="utf-8") as f:
        json.dump(geo, f, indent=2)
    print("Wrote GeoJSON:", out_geojson)

    # write SUMO additional XML: if lane mapping possible, attach lane else write commented coords
    with open(out_xml, "w", encoding="utf-8") as f:
        f.write("<additional>\n")
        for r in csv_rows:
            cx = r["center_x"]
            cy = r["center_y"]
            radius = next(c["radius"] for c in clusters.values() if c["center_x"] == cx and c["center_y"] == cy)
            # find lane id if possible
            lane_id = None
            if net:
                lane_id = find_nearest_lane_id(net, cx, cy)
            start_pos = 0.0
            end_pos = 2.0
            power_w = int(CHARGER_KW * 1000)
            if lane_id:
                f.write(f'  <chargingStation id="ns_cs_{r["cluster_id"]}" lane="{lane_id}" startPos="{start_pos:.2f}" endPos="{end_pos:.2f}" power="{power_w}" efficiency="0.95"/>\n')
            else:
                f.write(f'  <!-- ns_cs_{r["cluster_id"]} at ({cx:.1f},{cy:.1f}) r={radius:.1f} est_chargers={r["estimated_chargers"]} -->\n')
        f.write("</additional>\n")
    print("Wrote XML (or commented suggestions):", out_xml)

    # Export heatmap data (individual low-SOC points for gradient visualization)
    # Filter out points near existing stations to avoid misleading heatmap blobs
    if out_heatmap_json:
        heatmap_points = []
        filtered_near_station = 0
        for _, row in low_df.iterrows():
            x, y = row["x"], row["y"]
            soc = row["soc_percent"]
            
            # Skip heatmap points near existing charging stations
            if existing_stations:
                near_station = False
                for station in existing_stations:
                    dist = math.sqrt((x - station['x'])**2 + (y - station['y'])**2)
                    if dist <= EXISTING_STATION_BUFFER:
                        near_station = True
                        filtered_near_station += 1
                        break
                if near_station:
                    continue
            
            # Convert to lat/lon if network available
            if net:
                try:
                    lon, lat = net.convertXY2LonLat(x, y)
                    # Intensity based on how low the SOC is (lower SOC = higher intensity)
                    intensity = max(0.1, (SOC_THRESHOLD - soc) / SOC_THRESHOLD)
                    heatmap_points.append([lat, lon, intensity])
                except Exception:
                    pass
            else:
                # Fallback to SUMO coords (won't work well on real map)
                intensity = max(0.1, (SOC_THRESHOLD - soc) / SOC_THRESHOLD)
                heatmap_points.append([y, x, intensity])
        
        if filtered_near_station > 0:
            print(f"Heatmap: filtered {filtered_near_station} points near existing stations")
        
        os.makedirs(os.path.dirname(out_heatmap_json), exist_ok=True)
        with open(out_heatmap_json, "w", encoding="utf-8") as f:
            json.dump(heatmap_points, f, indent=2)
        print(f"Wrote heatmap data ({len(heatmap_points)} points):", out_heatmap_json)

    print(f"\n{'='*60}")
    print(f"RESULTS SUMMARY")
    print(f"{'='*60}")
    print(f"Total clusters found:           {len(clusters)}")
    print(f"Skipped (low quality score):     {skipped_quality}")
    print(f"Skipped (near existing station): {skipped_station_proximity}")
    print(f"Final suggested locations:       {len(csv_rows)}")
    if existing_stations:
        print(f"Existing stations considered:    {len(existing_stations)}")
        print(f"Exclusion radius:               {EXISTING_STATION_BUFFER}m")
    print(f"{'='*60}")
    print("Tip: visualize the geojson in QGIS / any GeoJSON viewer.")