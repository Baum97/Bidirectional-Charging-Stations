def generate_traffic_heatmap(csv_file, net_file, out_heatmap_json, sample_rate=0.1):
    """
    Generate traffic heatmap data from SUMO log CSV.
    
    Args:
        csv_file: Path to the merged SUMO output CSV (with x, y coordinates)
        net_file: Path to the SUMO network file for coordinate conversion
        out_heatmap_json: Output JSON file path for heatmap data
        sample_rate: Fraction of points to sample (0.1 = 10% to reduce data size)
    
    Output format: [[lat, lon, intensity], ...]
    """
    import os
    import json
    import pandas as pd
    import numpy as np
    
    try:
        import sumolib
        HAS_SUMOLIB = True
    except Exception:
        sumolib = None
        HAS_SUMOLIB = False
    
    if not os.path.exists(csv_file):
        raise FileNotFoundError(f"CSV file not found: {csv_file}")
    
    print(f"Reading traffic data from {csv_file}...")
    df = pd.read_csv(csv_file)
    
    # Check for required columns
    if "x" not in df.columns or "y" not in df.columns:
        raise ValueError("CSV must contain 'x' and 'y' coordinate columns")
    
    total_rows = len(df)
    print(f"Total vehicle position records: {total_rows}")
    
    # Sample data to reduce size (optional)
    if sample_rate < 1.0:
        df = df.sample(frac=sample_rate, random_state=42)
        print(f"Sampled {len(df)} points ({sample_rate*100:.0f}%)")
    
    # Load SUMO network for coordinate conversion
    net = None
    if HAS_SUMOLIB and net_file and os.path.exists(net_file):
        try:
            net = sumolib.net.readNet(net_file)
            print(f"Loaded SUMO network: {net_file}")
        except Exception as e:
            print(f"Could not load network: {e}")
    
    if not net:
        print("WARNING: No network loaded. Traffic heatmap will use SUMO coordinates (may not display correctly)")
    
    # Build heatmap points
    heatmap_points = []
    conversion_errors = 0
    
    for idx, row in df.iterrows():
        x, y = row["x"], row["y"]
        
        if pd.isna(x) or pd.isna(y):
            continue
        
        # Convert to lat/lon if network available
        if net:
            try:
                lon, lat = net.convertXY2LonLat(x, y)
                # Uniform intensity for traffic (can be adjusted based on speed or other factors)
                intensity = 0.5
                
                # Optional: vary intensity by speed (slower = more congestion = higher intensity)
                if "speed" in row and not pd.isna(row["speed"]):
                    speed = float(row["speed"])
                    # Normalize: 0 km/h = intensity 1.0, 50+ km/h = intensity 0.3
                    intensity = max(0.3, min(1.0, 1.0 - (speed / 50.0) * 0.7))
                
                heatmap_points.append([lat, lon, intensity])
            except Exception as e:
                conversion_errors += 1
                if conversion_errors <= 5:  # Only print first few errors
                    print(f"Warning: Could not convert coordinates ({x}, {y}): {e}")
        else:
            # Fallback to SUMO coords (won't work well on real map)
            intensity = 0.5
            heatmap_points.append([y, x, intensity])
    
    if conversion_errors > 5:
        print(f"... and {conversion_errors - 5} more conversion errors")
    
    # Save to JSON
    os.makedirs(os.path.dirname(out_heatmap_json), exist_ok=True)
    with open(out_heatmap_json, "w", encoding="utf-8") as f:
        json.dump(heatmap_points, f, indent=2)
    
    print(f"Wrote traffic heatmap data ({len(heatmap_points)} points): {out_heatmap_json}")
    return heatmap_points
