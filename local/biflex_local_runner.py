#!/usr/bin/env python3
"""
Local SUMO builder helper.

Runs a tiny HTTP server on 127.0.0.1:8787 that accepts POST /build with JSON:
{
  "bbox": [minLon, minLat, maxLon, maxLat],
  "scenario": "scenario_name"
}

Requirements:
- Python 3
- SUMO installed locally and SUMO_HOME set (points to SUMO root)

This helper fetches OSM for the bbox, converts to a SUMO net, generates routes,
and writes a basic sim.sumocfg in data/scenarios/<scenario>.

It adds permissive CORS for http://localhost:8080 for development.
"""

import json
import os
import sys
import subprocess
import random
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse

from extract_pois import extract_pois
from getPOIEdgeIDs import assign_poi_to_edges
from mainGenerateTrips import generate_trips
from mainGenerateChargingStations import generate_charging_stations
from generate_private_wallboxes import generate_trips_with_private_wallboxes, generate_private_wallboxes

import xml.etree.ElementTree as ET

import xml.etree.ElementTree as ET
import re

from convert_logs_to_csv import process_sumo_logs as convert_logs_to_csv
from train_from_sumo_log_no_stations import process_sumo_log_no_stations as train_from_sumo_log_no_stations
from generate_traffic_heatmap import generate_traffic_heatmap



HOST = "127.0.0.1"
PORT = 8787


def _sumo_paths():
    sumo_home = os.environ.get("SUMO_HOME")
    if not sumo_home:
        raise RuntimeError("SUMO_HOME environment variable is not set.")
    tools = os.path.join(sumo_home, "tools")
    bin_dir = os.path.join(sumo_home, "bin")
    osm_get = os.path.join(tools, "osmGet.py")
    random_trips = os.path.join(tools, "randomTrips.py")
    netconvert = os.path.join(bin_dir, "netconvert")
    if os.name == "nt":
        netconvert += ".exe"
    return {
        "SUMO_HOME": sumo_home,
        "tools": tools,
        "bin": bin_dir,
        "osmGet": osm_get,
        "randomTrips": random_trips,
        "netconvert": netconvert,
    }


def _run(cmd, cwd=None):
    print("[RUN]", " ".join(cmd))
    result = subprocess.run(cmd, check=False, cwd=cwd, capture_output=True, text=True)
    if result.stdout:
        print(result.stdout)
    if result.stderr:
        print("[STDERR]", result.stderr)
    if result.returncode != 0:
        raise subprocess.CalledProcessError(result.returncode, cmd, result.stdout, result.stderr)


def download_osm_data(bbox, scenario, prefix="test_name"):
    """
    Downloads OSM data for the given bounding box and scenario.

    Args:
        bbox (list): Bounding box [minLon, minLat, maxLon, maxLat].
        scenario (str): Scenario name.
        prefix (str): Prefix for the OSM file.

    Returns:
        str: Path to the downloaded OSM file.
    """
    if not isinstance(bbox, list) or len(bbox) != 4:
        raise ValueError("bbox must be [minLon, minLat, maxLon, maxLat]")

    paths = _sumo_paths()
    base_dir = os.path.join("..", "data", "scenarios", scenario)
    os.makedirs(base_dir, exist_ok=True)
    print(f"[INFO] Created base directory: {base_dir}")

    minLon, minLat, maxLon, maxLat = bbox
    bbox_str = f"{minLon},{minLat},{maxLon},{maxLat}"

    # Fetch OSM extract
    print(f"[INFO] Fetching OSM data for bbox: {bbox_str}")
    _run([sys.executable, paths["osmGet"], "-b", bbox_str, "-p", prefix], cwd=base_dir)

    # Determine the produced OSM file
    print("[INFO] Determining the produced OSM file...")
    allowed_suffixes = (".osm.xml", ".osm", ".osm.gz", ".osm.bz2", ".pbf", ".osm.pbf")
    osm_file = None
    for fname in sorted(os.listdir(base_dir)):
        low = fname.lower()
        if (low.startswith("map") or low.startswith(f"{prefix}_bbox")) and any(
            low.endswith(s) for s in allowed_suffixes
        ):
            osm_file = fname
            break

    if not osm_file:
        listing = "\n".join(sorted(os.listdir(base_dir)))
        raise RuntimeError(
            "osmGet did not produce an OSM file matching 'map*' or "
            "'<prefix>_bbox*' with suffixes {}. Directory contents:\n{}".format(
                ", ".join(allowed_suffixes), listing
            )
        )

    osm_file_path = os.path.abspath(os.path.join(base_dir, osm_file))
    print(f"[INFO] Found OSM file: {osm_file_path}")
    return osm_file_path


def build_sumo_network(osm_file, scenario):
    """
    Builds the SUMO network from the OSM file for the given scenario.

    Args:
        osm_file (str): Path to the OSM file.
        scenario (str): Scenario name.

    Returns:
        str: Path to the generated SUMO network file.
    """
    paths = _sumo_paths()
    base_dir = os.path.abspath(os.path.join("..", "data", "scenarios", scenario))
    os.makedirs(base_dir, exist_ok=True)
    print(f"[INFO] Building network in directory: {base_dir}")

    osm_file = os.path.abspath(osm_file)
    net_file = os.path.abspath(os.path.join(base_dir, "osm.net.xml.gz"))
    print(f"[INFO] Running netconvert with OSM file: {osm_file}")
    print(f"[INFO] Command working directory: {base_dir}")
    _run(
        [
            paths["netconvert"],
            "--osm-files",
            osm_file,
            "-o",
            net_file,
            "--speed-in-kmh",
            "--proj.utm",
        ],
        cwd=base_dir,
    )
    print(f"[INFO] Network built successfully: {net_file}")
    return net_file


def copy_default_combined_additional(scenario):
    """
    Copies the default combined_additional.xml to the scenario directory.

    Args:
        scenario (str): Scenario name.
    """
    base_dir = os.path.abspath(os.path.join("..", "data", "scenarios", scenario))
    src_file = os.path.abspath(os.path.join("..", "data", "defaults", "default_combined_additional.xml"))
    dest_file = os.path.join(base_dir, "combined_additional.xml")
    print(f"[INFO] Copying default combined_additional.xml to {dest_file}")
    with open(src_file, "r", encoding="utf-8") as src, open(dest_file, "w", encoding="utf-8") as dst:
        dst.write(src.read())
    print("[INFO] Default combined_additional.xml copied successfully.")


def copy_vehicle_types_additional(scenario):
    """
    Copies the default vehicle_types.add.xml to the scenario directory.

    Args:
        scenario (str): Scenario name.
    """
    base_dir = os.path.abspath(os.path.join("..", "data", "scenarios", scenario))
    src_file = os.path.abspath(os.path.join("..", "data", "defaults", "default_vehicle_types.add.xml"))
    dest_file = os.path.join(base_dir, "vehicle_types.add.xml")
    print(f"[INFO] Copying default vehicle_types.add.xml to {dest_file}")
    with open(src_file, "r", encoding="utf-8") as src, open(dest_file, "w", encoding="utf-8") as dst:
        dst.write(src.read())
    print("[INFO] Default vehicle_types.add.xml copied successfully.")


def create_sumo_config(net_file, trips_file, additional_files, base_dir):
    print("[INFO] Writing detailed SUMO configuration file...")
    cfg = (
        "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n"
        "<sumoConfiguration xmlns:xsi=\"http://www.w3.org/2001/XMLSchema-instance\" xsi:noNamespaceSchemaLocation=\"http://sumo.dlr.de/xsd/sumoConfiguration.xsd\">\n"
        "    <input>\n"
        f"        <net-file value=\"{net_file}\"/>\n"
        f"        <route-files value=\"{trips_file}\"/>\n"
        f"        <additional-files value=\"{additional_files}\"/>\n"
        "    </input>\n"
        "    <output>\n"
        "        <fcd-output value=\"fcd_output.xml.gz\"/>\n"
        "        <battery-output value=\"battery_output.xml.gz\"/>\n"
        "        <chargingstations-output value=\"chargingstations.xml\"/>\n"
        "        <vehroute-output value=\"veh_routes.xml.gz\"/>\n"
        "        <vehroute-output.write-unfinished value=\"true\"/>\n"  
        "        <vehroute-output.sorted value=\"true\"/>\n"
        "    </output>\n"
        "    <time>\n"
        "        <begin value=\"0\"/>\n"
        "        <step-length value=\"10\"/>\n"
        "    </time>\n"
        "    <processing>\n"
        "        <ignore-route-errors value=\"true\"/>\n"
        "        <tls.actuated.jam-threshold value=\"30\"/>\n"
        "        <lateral-resolution value=\"1.6\"/>\n"
        "        <collision.action value=\"none\"/>\n"
        "        <max-depart-delay value=\"900\"/>\n"
        "        <!-- Device settings: using probability since each vType has its own device config -->\n"
        "        <device.battery.probability value=\"1\"/>\n"
        "        <device.rerouting.probability value=\"1.0\"/>\n"
        "        <device.stationfinder.probability value=\"1\"/>\n"
        "        <device.stationfinder.rescueTime value=\"0\"/>\n"
        "        <device.stationfinder.reserveFactor value=\"1.3\"/>\n"
        "        <device.stationfinder.emptyThreshold value=\"0.05\"/>\n"
        "        <device.stationfinder.radius value=\"3000\"/>\n"
        "    </processing>\n"
        "    <routing>\n"
        "        <device.rerouting.adaptation-steps value=\"36\"/>\n"
        "        <device.rerouting.adaptation-interval value=\"30\"/>\n"
        "        <device.rerouting.pre-period value=\"120\"/>\n"
        "        <device.rerouting.with-taz value=\"false\"/>\n"
        "    </routing>\n"
        "    <report>\n"
        "        <verbose value=\"false\"/>\n"
        "        <duration-log.statistics value=\"false\"/>\n"
        "        <no-step-log value=\"true\"/>\n"
        "        <no-warnings value=\"true\"/>\n"
        "    </report>\n"
        "</sumoConfiguration>\n"
    )
    with open(os.path.join(base_dir, "sim.sumocfg"), "w", encoding="utf-8") as f:
        f.write(cfg)
    print("[INFO] Detailed SUMO configuration file written.")


def _parse_voltage_to_kv(voltage_str):
    """
    Parse an OSM voltage string into a single float in kV (max of all values),
    or None if it can't be parsed.
    Examples:
      "110000"     -> 110.0
      "110 kV"     -> 110.0
      "110000;20000" -> 110.0
      "0.4"        -> 0.4
    """
    if not voltage_str:
        return None
    s = str(voltage_str)
    # Extract all numbers (ints or floats)
    nums = re.findall(r"\d+(?:\.\d+)?", s.replace(",", "."))
    if not nums:
        return None
    values = [float(n) for n in nums]
    if not values:
        return None
    v = max(values)
    # Heuristic: if it's > 1000, assume it's in volts and convert to kV
    if v > 1000:
        return v / 1000.0
    return v


def extract_power_grid(osm_file):
    """
    Parse the OSM file and extract power-related features as GeoJSON.

    - Nodes: substations, transformers, poles, towers, plants, busbars, switches, etc.
    - Lines: power=line, power=minor_line, power=cable
    - Areas: power=substation, power=plant (as polygons where possible)
    """
    tree = ET.parse(osm_file)
    root = tree.getroot()

    # Collect all nodes
    nodes = {}
    for n in root.findall("node"):
        nid = n.get("id")
        lat = float(n.get("lat"))
        lon = float(n.get("lon"))
        nodes[nid] = (lon, lat)  # GeoJSON expects [lon, lat]

    features = []

    # --- 1) Power nodes ---
    power_node_types = {
        "substation",
        "generator",
        "transformer",
        "pole",
        "tower",
        "plant",
        "busbar",
        "switch",
        "compensator",
        "converter",
    }

    for n in root.findall("node"):
        tags = {t.get("k"): t.get("v") for t in n.findall("tag")}
        power_tag = tags.get("power")
        if power_tag and power_tag in power_node_types:
            nid = n.get("id")
            lon, lat = nodes[nid]
            voltage = tags.get("voltage")
            voltage_kv = _parse_voltage_to_kv(voltage)
            feature = {
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [lon, lat],
                },
                "properties": {
                    "osm_id": nid,
                    "kind": "power_node",
                    "power": power_tag,
                    "name": tags.get("name"),
                    "voltage": voltage,
                    "voltage_kv": voltage_kv,
                    "operator": tags.get("operator"),
                },
            }
            features.append(feature)

    # --- 2) Power lines ---
    line_types = {"line", "minor_line", "cable"}

    for w in root.findall("way"):
        tags = {t.get("k"): t.get("v") for t in w.findall("tag")}
        power_tag = tags.get("power")
        if power_tag and power_tag in line_types:
            coords = []
            for nd in w.findall("nd"):
                ref = nd.get("ref")
                if ref in nodes:
                    coords.append(list(nodes[ref]))
            if len(coords) >= 2:
                voltage = tags.get("voltage")
                voltage_kv = _parse_voltage_to_kv(voltage)
                feature = {
                    "type": "Feature",
                    "geometry": {
                        "type": "LineString",
                        "coordinates": coords,
                    },
                    "properties": {
                        "osm_id": w.get("id"),
                        "kind": "power_line",
                        "power": power_tag,
                        "name": tags.get("name"),
                        "voltage": voltage,
                        "voltage_kv": voltage_kv,
                        "circuits": tags.get("circuits"),
                        "operator": tags.get("operator"),
                    },
                }
                features.append(feature)

    # --- 3) Power areas (substations / plants as polygons) ---
    area_types = {"substation", "plant"}

    for w in root.findall("way"):
        tags = {t.get("k"): t.get("v") for t in w.findall("tag")}
        power_tag = tags.get("power")
        if power_tag and power_tag in area_types:
            nd_refs = [nd.get("ref") for nd in w.findall("nd")]
            if len(nd_refs) < 3:
                continue
            # check if closed polygon
            if nd_refs[0] != nd_refs[-1]:
                continue
            ring = []
            missing = False
            for ref in nd_refs:
                if ref not in nodes:
                    missing = True
                    break
                ring.append(list(nodes[ref]))
            if missing or len(ring) < 4:
                continue

            voltage = tags.get("voltage")
            voltage_kv = _parse_voltage_to_kv(voltage)
            feature = {
                "type": "Feature",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [ring],
                },
                "properties": {
                    "osm_id": w.get("id"),
                    "kind": "power_area",
                    "power": power_tag,
                    "name": tags.get("name"),
                    "voltage": voltage,
                    "voltage_kv": voltage_kv,
                    "operator": tags.get("operator"),
                },
            }
            features.append(feature)

    return {
        "type": "FeatureCollection",
        "features": features,
    }


def generate_synthetic_distribution(osm_file):
    """
    Generate a synthetic, dense distribution grid based on OSM roads.

    - Uses residential / living_street / service / unclassified / tertiary roads.
    - Skips any way that is already tagged with power=*.
    - Creates LineString features with a low voltage_kv (0.4–10 kV).
    """
    tree = ET.parse(osm_file)
    root = tree.getroot()

    # Collect nodes
    nodes = {}
    for n in root.findall("node"):
        nid = n.get("id")
        lat = float(n.get("lat"))
        lon = float(n.get("lon"))
        nodes[nid] = (lon, lat)

    # Identify ways that are already power lines so we don't clone them
    power_way_ids = set()
    for w in root.findall("way"):
        for t in w.findall("tag"):
            if t.get("k") == "power":
                power_way_ids.add(w.get("id"))
                break

    # Road types to use as synthetic distribution feeders
    highway_types = {
        "residential",
        "living_street",
        "service",
        "unclassified",
        "tertiary",
        "tertiary_link",
    }

    features = []

    for w in root.findall("way"):
        wid = w.get("id")
        if wid in power_way_ids:
            continue

        tags = {t.get("k"): t.get("v") for t in w.findall("tag")}
        hwy = tags.get("highway")
        if hwy not in highway_types:
            continue

        coords = []
        for nd in w.findall("nd"):
            ref = nd.get("ref")
            if ref in nodes:
                coords.append(list(nodes[ref]))
        if len(coords) < 2:
            continue

        # Heuristic voltage: MV for bigger roads, LV for small ones
        if hwy in {"tertiary", "tertiary_link"}:
            voltage_kv = 10.0   # MV feeder
        else:
            voltage_kv = 0.4    # LV distribution

        feature = {
            "type": "Feature",
            "geometry": {
                "type": "LineString",
                "coordinates": coords,
            },
            "properties": {
                "osm_id": wid,
                "kind": "synthetic_line",
                "synthetic": True,
                "power": "distribution",
                "highway_source": hwy,
                "name": tags.get("name"),
                "voltage": f"{voltage_kv} kV",
                "voltage_kv": voltage_kv,
            },
        }
        features.append(feature)

    return {
        "type": "FeatureCollection",
        "features": features,
    }


def read_poi_files(poi_files):
    """
    Read POI CSV files and convert them to GeoJSON format.

    Args:
        poi_files (list): List of CSV file paths.

    Returns:
        dict: Dictionary mapping category names to GeoJSON FeatureCollections.
    """
    import csv
    
    poi_geojson = {}
    
    # poi_files is a list of file paths like ["path/poi_offices.csv", "path/poi_residential.csv", ...]
    for filepath in poi_files:
        if not os.path.exists(filepath):
            print(f"[WARNING] POI file not found: {filepath}")
            continue
        
        # Extract category from filename (e.g., "poi_offices.csv" -> "offices")
        filename = os.path.basename(filepath)
        if filename.startswith("poi_") and filename.endswith(".csv"):
            category = filename[4:-4]  # Remove "poi_" prefix and ".csv" suffix
        else:
            print(f"[WARNING] Unexpected POI filename format: {filename}")
            continue
        
        features = []
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    # Skip rows without valid coordinates
                    if not row.get('lat') or not row.get('lon'):
                        continue
                    
                    try:
                        lat = float(row['lat'])
                        lon = float(row['lon'])
                        
                        feature = {
                            "type": "Feature",
                            "geometry": {
                                "type": "Point",
                                "coordinates": [lon, lat]
                            },
                            "properties": {
                                "id": row.get('id', ''),
                                "name": row.get('name', 'Unknown'),
                                "type": row.get('type', ''),
                                "category": category
                            }
                        }
                        features.append(feature)
                    except (ValueError, KeyError) as e:
                        print(f"[WARNING] Skipping invalid POI row: {e}")
                        continue
            
            poi_geojson[category] = {
                "type": "FeatureCollection",
                "features": features
            }
            print(f"[INFO] Loaded {len(features)} POIs for category '{category}'")
        
        except Exception as e:
            print(f"[ERROR] Failed to read POI file {filepath}: {e}")
            continue
    
    return poi_geojson


def extract_real_charging_stations(osm_file):
    """
    Extract real charging stations from an OSM file.

    Args:
        osm_file (str): Path to the OSM file.

    Returns:
        dict: GeoJSON FeatureCollection of charging stations.
    """
    tree = ET.parse(osm_file)
    root = tree.getroot()

    # Collect all nodes
    nodes = {}
    for n in root.findall("node"):
        nid = n.get("id")
        lat = float(n.get("lat"))
        lon = float(n.get("lon"))
        nodes[nid] = (lon, lat)  # GeoJSON expects [lon, lat]

    print(f"[DEBUG] Total nodes found: {len(nodes)}")

    features = []

    # --- Charging stations ---
    for n in root.findall("node"):
        tags = {t.get("k"): t.get("v") for t in n.findall("tag")}
        amenity = tags.get("amenity")
        if amenity == "charging_station":
            nid = n.get("id")
            lon, lat = nodes[nid]
            print(f"[DEBUG] Found charging station - Node ID: {nid}, Tags: {tags}")
            feature = {
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [lon, lat],
                },
                "properties": {
                    "osm_id": nid,
                    "name": tags.get("name"),
                    "operator": tags.get("operator"),
                    "capacity": tags.get("capacity"),
                },
            }
            features.append(feature)

    return {
        "type": "FeatureCollection",
        "features": features,
    }



class Handler(BaseHTTPRequestHandler):
    def _set_cors(self):
        self.send_header("Access-Control-Allow-Origin", "http://localhost:8080")
        self.send_header("Vary", "Origin")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def do_OPTIONS(self):
        self.send_response(204)
        self._set_cors()
        self.end_headers()

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path == "/build":
            try:
                length = int(self.headers.get("Content-Length", "0"))
                raw = self.rfile.read(length) if length else b"{}"
                data = json.loads(raw.decode("utf-8") or "{}")
                bbox = data.get("bbox")
                scenario = data.get("scenario") or "scenario"

                # Step 1: Download OSM data -> returns full path to the file
                osm_file = download_osm_data(bbox, scenario)
                scen_dir = os.path.dirname(osm_file)

                # Extract real already existing charging stations
                real_charging_stations = extract_real_charging_stations(osm_file)
                print(f"[INFO] Extracted real charging stations: {len(real_charging_stations['features'])} found")

                # Real high-/medium-voltage grid from OSM
                real_grid = extract_power_grid(osm_file)

                # Synthetic dense LV/MV distribution along roads
                synthetic_grid = generate_synthetic_distribution(osm_file)

                # Combine both into one FeatureCollection
                power_grid = {
                    "type": "FeatureCollection",
                    "features": real_grid["features"] + synthetic_grid["features"],
                }

                # print(json.dumps(power_grid, indent=2))

                # Step 2: Build SUMO network
                net_file = build_sumo_network(osm_file, scenario)

                # Step 3: Extract POIs
                print(f"[INFO] Extracting POIs -> {scen_dir}")
                poi_files = extract_pois(osm_file, scen_dir)
                
                # Read POI files and convert to GeoJSON
                poi_geojson = read_poi_files(poi_files)

                # Step 4: Assign POIs to edges
                print(f"[INFO] Assigning POIs to edges -> {poi_files}")
                edge_files = assign_poi_to_edges(net_file, poi_files)

                # Step 5: Pre-select wallbox recipients BEFORE trip generation
                # This is needed so trips can include parkingArea stops for wallbox owners
                print(f"[INFO] Pre-selecting wallbox recipients (50% of EV owners)")
                from generate_private_wallboxes import _select_wallbox_recipients
                
                # Build temporary person list to determine EV owners and wallbox recipients
                num_persons = 250
                ev_share = 0.6
                num_evs = int(num_persons * ev_share)
                temp_persons = [{'id': f'person{i}'} for i in range(1, num_persons + 1)]
                random.seed(42)
                all_ids = [p['id'] for p in temp_persons]
                ev_ids = set(random.sample(all_ids, num_evs))
                for p in temp_persons:
                    p['has_ev'] = p['id'] in ev_ids
                wallbox_recipients = _select_wallbox_recipients(temp_persons, wallbox_share=0.5)
                print(f"[INFO] Pre-selected {len(wallbox_recipients)} wallbox recipients")

                # Step 6: Generate trips with private wallboxes (unique vehicle types per person)
                # Wallbox owners get explicit <stop parkingArea="..."> for their home wallbox
                print(f"[INFO] Generating trips with unique vehicle types -> {edge_files}")
                trips_file, persons_data = generate_trips_with_private_wallboxes(
                    net_file, edge_files, scen_dir, wallbox_recipients=wallbox_recipients
                )
                print(f"[INFO] Trips generated -> {trips_file}")

                # Step 7: Generate private wallboxes (parkingArea + nested chargingStation)
                # Access control is enforced through routing: only owners are routed to their parkingArea
                print(f"[INFO] Generating private wallboxes")
                wallbox_file, wallbox_homes_file = generate_private_wallboxes(net_file, persons_data, scen_dir)
                ev_count = sum(1 for p in persons_data if p.get('has_ev', False))
                wallbox_count = sum(1 for p in persons_data if p.get('has_wallbox', False))
                print(f"[INFO] Private wallboxes generated -> {wallbox_file}")
                print(f"[INFO] Created {wallbox_count} wallboxes for {wallbox_count}/{ev_count} EV owners (50%)")

                # Step 8: Generate public charging stations (unrestricted - all EVs can use)
                print(f"[INFO] Generating public charging stations")
                charging_stations_file = generate_charging_stations(net_file, scen_dir, min_length=50)
                print(f"[INFO] Public charging stations generated -> {charging_stations_file}")
                print(f"[INFO] Public stations are unrestricted - all vehicles can use them")

                # Step 8: Combine additional files
                copy_default_combined_additional(scenario)
                copy_vehicle_types_additional(scenario)

                # Step 9: Create sim.sumocfg (combined_additional.xml includes wallboxes and charging stations)
                # The combined_additional.xml file includes via <include> directives:
                # - private_wallboxes.xml
                # - osm.chargingstations.xml  
                # - vehicle_types.add.xml
                create_sumo_config(net_file, trips_file, "combined_additional.xml", scen_dir)

                # Step 10: Run simulation to generate logs
                print("[INFO] Running SUMO simulation...")
                sumo_command = ["sumo", "-c", "sim.sumocfg"]
                try:
                    subprocess.run(sumo_command, check=True, cwd=scen_dir)
                    print("[INFO] SUMO simulation completed successfully.")
                except subprocess.CalledProcessError as e:
                    raise RuntimeError(f"SUMO simulation failed: {e}")

                # Step 11: convert logs to CSV (optional)
                convert_logs_to_csv(
                    os.path.join(scen_dir, "fcd_output.xml.gz"),
                    os.path.join(scen_dir, "battery_output.xml.gz"),
                    os.path.join(scen_dir, "combined_additional.xml"),
                    os.path.join(scen_dir, "sumo_merged_output.csv")
                )

                print("[INFO] Logs converted to CSV successfully.")

                # Step 12: generate traffic heatmap from logs
                traffic_heatmap_file = os.path.join(scen_dir, "traffic_heatmap.json")
                try:
                    generate_traffic_heatmap(
                        os.path.join(scen_dir, "sumo_merged_output.csv"),
                        net_file,
                        traffic_heatmap_file,
                        sample_rate=0.05  # 5% sampling to reduce data size
                    )
                except Exception as e:
                    print(f"[WARNING] Could not generate traffic heatmap: {e}")

                # Step 13: generate stations from log
                heatmap_json_file = os.path.join(scen_dir, "no_station_heatmap.json")
                train_from_sumo_log_no_stations(
                    os.path.join(scen_dir, "sumo_merged_output.csv"),
                    os.path.join(scen_dir, "no_station_charging_suggestions.csv"),
                    os.path.join(scen_dir, "no_station_areas.geojson"),
                    os.path.join(scen_dir, "suggested_charging_stations.add.xml"),
                    net_file,  # Pass network file for coordinate conversion
                    heatmap_json_file  # Output heatmap data for gradient visualization
                )

                heatmap_geojson_file = os.path.join(scen_dir, "no_station_areas.geojson")
                
                # Read the actual GeoJSON content (cluster polygons)
                heatmap_geojson = None
                if os.path.exists(heatmap_geojson_file):
                    with open(heatmap_geojson_file, 'r', encoding='utf-8') as f:
                        heatmap_geojson = json.load(f)
                    print(f"[INFO] Loaded heatmap GeoJSON with {len(heatmap_geojson.get('features', []))} features")

                # Read the heatmap point data (for gradient visualization)
                heatmap_data = None
                if os.path.exists(heatmap_json_file):
                    with open(heatmap_json_file, 'r', encoding='utf-8') as f:
                        heatmap_data = json.load(f)
                    print(f"[INFO] Loaded heatmap data with {len(heatmap_data)} points")

                # Read the traffic heatmap data
                traffic_heatmap_data = None
                if os.path.exists(traffic_heatmap_file):
                    with open(traffic_heatmap_file, 'r', encoding='utf-8') as f:
                        traffic_heatmap_data = json.load(f)
                    print(f"[INFO] Loaded traffic heatmap data with {len(traffic_heatmap_data)} points")

                # Read the wallbox homes GeoJSON
                wallbox_homes_geojson = None
                if os.path.exists(wallbox_homes_file):
                    with open(wallbox_homes_file, 'r', encoding='utf-8') as f:
                        wallbox_homes_geojson = json.load(f)
                    print(f"[INFO] Loaded wallbox homes GeoJSON with {len(wallbox_homes_geojson.get('features', []))} homes")

                # Respond with success
                resp = {
                    "ok": True,
                    "message": "Pipeline completed successfully with private wallboxes",
                    "scenarioDir": scen_dir,
                    "networkFile": net_file,
                    "poiFiles": poi_files,
                    "poiGeoJSON": poi_geojson,  # Added POI GeoJSON data
                    "powerGrid": power_grid,
                    "realChargingStations": real_charging_stations,  # Added charging stations
                    "heatmapGeoJSON": heatmap_geojson,  # Added heatmap geojson, Polygons
                    "heatmapData": heatmap_data,  # Added gradient heatmap data
                    "trafficHeatmap": traffic_heatmap_data,  # Added traffic heatmap
                    "wallboxHomesGeoJSON": wallbox_homes_geojson,  # NEW: Homes with private wallboxes
                    "privateWallboxes": {
                        "file": os.path.basename(wallbox_file),
                        "count": wallbox_count,
                        "total_evs": ev_count,
                        "coverage": f"{wallbox_count}/{ev_count} (50%)",
                        "description": "Private wallboxes restricted to vehicle owner"
                    },
                    "publicChargingStations": {
                        "file": os.path.basename(charging_stations_file),
                        "description": "Public charging stations (unrestricted)"
                    }
                }
                json.dumps(resp, indent=2)
                payload = json.dumps(resp).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self._set_cors()
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
            except Exception as e:
                print(f"[ERROR] {e}")
                msg = {"ok": False, "error": str(e)}
                payload = json.dumps(msg).encode("utf-8")
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self._set_cors()
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)


def main():
    print(f"Starting local SUMO builder on http://{HOST}:{PORT}")
    httpd = HTTPServer((HOST, PORT), Handler)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down…")
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()
