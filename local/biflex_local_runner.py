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
import shutil
import time
import xml.etree.ElementTree as ET
import re
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError
import gzip
import io

from extract_pois import extract_pois
from getPOIEdgeIDs import assign_poi_to_edges
from mainGenerateTrips import generate_trips
from mainGenerateChargingStations import generate_charging_stations
from generate_private_wallboxes import generate_private_wallboxes
from power_grid_manager import PowerGridManager
from generate_public_charging_stations import generate_public_charging_stations

# Fast test versions for quick iteration (100 cars, 10h simulation)
from mainGenerateTrips_test import generate_trips_test
from generate_private_wallboxes_test import generate_trips_with_private_wallboxes_test

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


def _run(cmd, cwd=None, timeout=300):
    print("[RUN]", " ".join(cmd))
    result = subprocess.run(cmd, check=False, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    if result.stdout:
        print(result.stdout)
    if result.stderr:
        print("[STDERR]", result.stderr)
    if result.returncode != 0:
        raise subprocess.CalledProcessError(result.returncode, cmd, result.stdout, result.stderr)
    return result


def _download_osm_direct(bbox, output_path, timeout=120):
    """
    Fallback: download OSM data directly via HTTP when osmGet.py fails.
    Tries multiple Overpass API servers, then falls back to the OSM map API.
    """
    minLon, minLat, maxLon, maxLat = bbox

    # Overpass QL query for the bounding box
    overpass_query = (
        f'[out:xml][timeout:180];'
        f'(node({minLat},{minLon},{maxLat},{maxLon});'
        f'<;);'
        f'out meta;'
    )

    overpass_servers = [
        "https://overpass-api.de/api/interpreter",
        "https://overpass.kumi.systems/api/interpreter",
        "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
    ]

    # Try each Overpass server
    for server_url in overpass_servers:
        try:
            print(f"[INFO] Direct download: trying {server_url}")
            data = overpass_query.encode("utf-8")
            req = Request(server_url, data=data, headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept-Encoding": "gzip",
            })
            response = urlopen(req, timeout=timeout)
            content = response.read()

            # Decompress if gzipped
            if response.headers.get("Content-Encoding") == "gzip":
                content = gzip.decompress(content)

            # Sanity check: must contain OSM XML
            text = content.decode("utf-8", errors="replace")
            if "<osm" not in text[:500]:
                print(f"[WARNING] Response from {server_url} is not valid OSM XML (first 200 chars): {text[:200]}")
                continue

            with open(output_path, "wb") as f:
                f.write(content)
            print(f"[INFO] Direct download succeeded from {server_url} -> {output_path} ({len(content)} bytes)")
            return output_path

        except (HTTPError, URLError, TimeoutError, OSError) as e:
            print(f"[WARNING] Direct download from {server_url} failed: {e}")
            continue

    # Last resort: OSM export API (limited to small areas)
    try:
        export_url = f"https://api.openstreetmap.org/api/0.6/map?bbox={minLon},{minLat},{maxLon},{maxLat}"
        print(f"[INFO] Direct download: trying OSM export API: {export_url}")
        req = Request(export_url, headers={"Accept-Encoding": "gzip"})
        response = urlopen(req, timeout=timeout)
        content = response.read()
        if response.headers.get("Content-Encoding") == "gzip":
            content = gzip.decompress(content)

        text = content.decode("utf-8", errors="replace")
        if "<osm" not in text[:500]:
            print(f"[WARNING] OSM export API response is not valid OSM XML")
        else:
            with open(output_path, "wb") as f:
                f.write(content)
            print(f"[INFO] OSM export API download succeeded -> {output_path} ({len(content)} bytes)")
            return output_path
    except (HTTPError, URLError, TimeoutError, OSError) as e:
        print(f"[WARNING] OSM export API failed: {e}")

    return None


def download_osm_data(bbox, scenario, prefix="test_name", max_retries=3):
    """
    Downloads OSM data for the given bounding box and scenario.
    Retries on failure to handle transient network issues.
    Falls back to direct HTTP download if osmGet.py fails.

    Args:
        bbox (list): Bounding box [minLon, minLat, maxLon, maxLat].
        scenario (str): Scenario name.
        prefix (str): Prefix for the OSM file.
        max_retries (int): Number of retry attempts.

    Returns:
        str: Path to the downloaded OSM file.
    """
    if not isinstance(bbox, list) or len(bbox) != 4:
        raise ValueError("bbox must be [minLon, minLat, maxLon, maxLat]")

    paths = _sumo_paths()
    base_dir = os.path.abspath(os.path.join("..", "data", "scenarios", scenario))
    os.makedirs(base_dir, exist_ok=True)
    print(f"[INFO] Created base directory: {base_dir}")

    minLon, minLat, maxLon, maxLat = bbox
    bbox_str = f"{minLon},{minLat},{maxLon},{maxLat}"

    # Retry loop for transient network failures
    for attempt in range(max_retries):
        try:
            # Fetch OSM extract
            print(f"[INFO] Fetching OSM data for bbox: {bbox_str} (attempt {attempt + 1}/{max_retries})")
            print(f"[INFO] Using osmGet from: {paths['osmGet']}")
            print(f"[INFO] Output directory: {base_dir}")
            
            # Check files before running osmGet
            files_before = set(os.listdir(base_dir))
            print(f"[DEBUG] Files before osmGet: {files_before}")
            
            # Run osmGet with explicit output directory
            # osmGet.py uses -d for output directory
            cmd = [sys.executable, paths["osmGet"], "-b", bbox_str, "-p", prefix, "-d", base_dir]
            print(f"[DEBUG] Running command with output directory: {base_dir}")
            
            try:
                result = _run(cmd, cwd=base_dir, timeout=120)
            except subprocess.CalledProcessError as e:
                # If that fails, try running from SUMO tools directory
                print(f"[INFO] Trying alternate approach from SUMO tools directory...")
                sumo_tools_dir = os.path.dirname(paths["osmGet"])
                cmd = [sys.executable, paths["osmGet"], "-b", bbox_str, "-p", prefix, "-d", base_dir]
                result = _run(cmd, cwd=sumo_tools_dir, timeout=120)
            
            # Detect HTTP errors in osmGet output (it exits 0 even on 504, 429, etc.)
            combined_output = (result.stdout or "") + (result.stderr or "")
            http_error_patterns = ["Gateway Timeout", "503 Service", "429 Too Many", "500 Internal", "502 Bad Gateway"]
            for pat in http_error_patterns:
                if pat.lower() in combined_output.lower():
                    print(f"[WARNING] osmGet output contains HTTP error: '{pat}'")
                    raise subprocess.CalledProcessError(1, cmd, result.stdout, f"HTTP error detected in output: {pat}")
            
            # Check files after running osmGet
            files_after = set(os.listdir(base_dir))
            new_files = files_after - files_before
            print(f"[DEBUG] Files after osmGet: {files_after}")
            print(f"[DEBUG] New files created: {new_files}")
            
            if not new_files:
                # Check if osmGet created files in the SUMO tools directory instead
                sumo_tools_dir = os.path.dirname(paths["osmGet"])
                print(f"[DEBUG] Checking SUMO tools directory for files: {sumo_tools_dir}")
                try:
                    tools_files_before = set(os.listdir(sumo_tools_dir))
                    tools_files_after = set(os.listdir(sumo_tools_dir))
                    tools_new_files = tools_files_after - tools_files_before
                    if tools_new_files:
                        print(f"[DEBUG] Found files in SUMO tools directory: {tools_new_files}")
                        # Try to move them to base_dir
                        for f in tools_new_files:
                            src = os.path.join(sumo_tools_dir, f)
                            dst = os.path.join(base_dir, f)
                            try:
                                shutil.move(src, dst)
                                new_files.add(f)
                                print(f"[INFO] Moved {f} from SUMO tools to scenario directory")
                            except Exception as e:
                                print(f"[WARNING] Could not move {f}: {e}")
                except Exception as e:
                    print(f"[DEBUG] Could not check SUMO tools directory: {e}")
                
            if not new_files:
                error_msg = f"osmGet executed (returncode={result.returncode}) but did not create any files in {base_dir}"
                if attempt < max_retries - 1:
                    print(f"[WARNING] {error_msg}")
                    print(f"[INFO] Retrying in 5 seconds...")
                    time.sleep(5)
                    continue
                else:
                    # All osmGet retries exhausted — try direct HTTP download
                    print(f"[INFO] All osmGet attempts produced no files. Trying direct HTTP download...")
                    fallback_file = os.path.join(base_dir, f"{prefix}_bbox.osm.xml")
                    result_path = _download_osm_direct(bbox, fallback_file)
                    if result_path and os.path.isfile(result_path):
                        return result_path
                    raise RuntimeError(error_msg)
            
            # Determine the produced OSM file
            print("[INFO] Determining the produced OSM file...")
            allowed_suffixes = (".osm.xml", ".osm", ".osm.gz", ".osm.bz2", ".pbf", ".osm.pbf")
            osm_file = None
            
            dir_contents = sorted(files_after)
            print(f"[DEBUG] Directory contents: {dir_contents}")
            
            # First, try to find by prefix pattern
            for fname in dir_contents:
                low = fname.lower()
                print(f"[DEBUG] Checking file: {fname} (starts with 'map'={low.startswith('map')}, starts with '{prefix}_bbox'={low.startswith(f'{prefix}_bbox')})")
                if (low.startswith("map") or low.startswith(f"{prefix}_bbox")) and any(
                    low.endswith(s) for s in allowed_suffixes
                ):
                    osm_file = fname
                    break
            
            # If not found by prefix, look for ANY OSM file in new files
            if not osm_file and new_files:
                print(f"[DEBUG] Prefix pattern not found, checking new files for OSM extensions: {new_files}")
                for fname in new_files:
                    low = fname.lower()
                    if any(low.endswith(s) for s in allowed_suffixes):
                        osm_file = fname
                        print(f"[INFO] Found OSM file by extension: {fname}")
                        break

            if osm_file:
                osm_file_path = os.path.join(base_dir, osm_file)
                print(f"[INFO] Found OSM file: {osm_file_path}")
                return osm_file_path
            else:
                error_msg = (
                    f"osmGet created files but none matched expected pattern 'map*' or '{prefix}_bbox*' "
                    f"with suffixes {', '.join(allowed_suffixes)}. Created files: {new_files}"
                )
                if attempt < max_retries - 1:
                    print(f"[WARNING] {error_msg}")
                    # Clean up created files for next attempt
                    for f in new_files:
                        try:
                            os.remove(os.path.join(base_dir, f))
                        except:
                            pass
                    print(f"[INFO] Retrying in 5 seconds...")
                    time.sleep(5)
                    continue
                else:
                    raise RuntimeError(error_msg)
                    
        except subprocess.TimeoutExpired:
            if attempt < max_retries - 1:
                print(f"[WARNING] osmGet.py timed out. Retrying in 5 seconds...")
                time.sleep(5)
            else:
                raise RuntimeError(f"osmGet.py timed out after {max_retries} attempts. The OSM API may be unavailable or slow.")
        except subprocess.CalledProcessError as e:
            if attempt < max_retries - 1:
                print(f"[WARNING] osmGet returned non-zero exit code {e.returncode}")
                print(f"[WARNING] stdout: {e.stdout}")
                print(f"[WARNING] stderr: {e.stderr}")
                print(f"[INFO] Retrying in 5 seconds...")
                time.sleep(5)
            else:
                print(f"[ERROR] osmGet failed after {max_retries} attempts")
                print(f"[ERROR] Last error: {e}")
                raise RuntimeError(f"osmGet.py failed: {e.stderr or e.stdout or 'Unknown error'}")
        except Exception as e:
            if attempt < max_retries - 1:
                print(f"[WARNING] Error during OSM download: {e}. Retrying in 5 seconds...")
                time.sleep(5)
            else:
                # All osmGet retries exhausted — try direct HTTP download as fallback
                print(f"[INFO] All osmGet attempts failed. Trying direct HTTP download as fallback...")
                fallback_file = os.path.join(base_dir, f"{prefix}_bbox.osm.xml")
                result_path = _download_osm_direct(bbox, fallback_file)
                if result_path and os.path.isfile(result_path):
                    return result_path
                raise


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


def create_sumo_config(net_file, trips_file, additional_files, base_dir, stationfinder_radius=3000, duration=0):
    print("[INFO] Writing detailed SUMO configuration file...")
    end_tag = f"        <end value=\"{duration}\"/>\n" if duration and duration > 0 else ""
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
        + end_tag +
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
        f"        <device.stationfinder.radius value=\"{stationfinder_radius}\"/>\n"
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
                sim_params = data.get("params") or {}

                # Step 1: Download OSM data -> returns full path to the file
                # COMMENTED OUT: Reusing OSM data from scenario_20260208_215130 instead of downloading
                osm_file = download_osm_data(bbox, scenario)
                scen_dir = os.path.dirname(osm_file)

                # Save simulation parameters for downstream scripts
                sim_params_file = os.path.join(scen_dir, "sim_params.json")
                with open(sim_params_file, 'w', encoding='utf-8') as f:
                    json.dump(sim_params, f, indent=2)
                print(f"[INFO] Simulation parameters saved -> {sim_params_file}")
                
                # Extract real already existing charging stations
                real_charging_stations = extract_real_charging_stations(osm_file)
                print(f"[INFO] Extracted real charging stations: {len(real_charging_stations['features'])} found")

                # Step 2: Build SUMO network
                net_file = build_sumo_network(osm_file, scenario)

                # Step 3: Extract POIs
                # COMMENTED OUT: Reusing POI data from scenario_20260208_215130 instead of processing
                print(f"[INFO] Extracting POIs -> {scen_dir}")
                poi_files = extract_pois(osm_file, scen_dir)
                
               
                # Read POI files and convert to GeoJSON
                poi_geojson = read_poi_files(poi_files)

                # Step 4: Assign POIs to edges
                print(f"[INFO] Assigning POIs to edges -> {poi_files}")
                edge_files = assign_poi_to_edges(net_file, poi_files)
                print(f"[INFO] POI edge assignments completed: {len(edge_files)} files generated")

                # Step 5: Generate trips
                print(f"[INFO] Generating vehicle trips")
                # edge_files is already a list from assign_poi_to_edges
                edge_files_list = edge_files if isinstance(edge_files, list) else list(edge_files.values())
                _duration = int(sim_params.get('duration', 0))
                if 0 < _duration < 36000:
                    trips_file = generate_trips_test(net_file, edge_files_list, scen_dir, sim_params=sim_params)
                    print(f"[INFO] FAST trips generated (duration {_duration}s < 10h threshold) -> {trips_file}")
                else:
                    trips_file = generate_trips(net_file, edge_files_list, scen_dir, sim_params=sim_params)
                    print(f"[INFO] Full trips generated -> {trips_file}")

                # Step 5.5: Build synthetic power grid from OSM road network
                print(f"[INFO] Building synthetic power grid from OSM road network")
                grid_manager = PowerGridManager(osm_file=osm_file, scenario_name=scenario)
                grid_build_success = grid_manager.build_grid()
                
                if grid_build_success:
                    # Connect real charging stations to grid
                    real_stations_for_grid = []
                    net = __import__('sumolib').net.readNet(net_file)
                    
                    for feature in real_charging_stations['features']:
                        props = feature['properties']
                        coords = feature['geometry']['coordinates']
                        real_stations_for_grid.append({
                            'id': f"real_cs_{props.get('osm_id', len(real_stations_for_grid))}",
                            'lon': coords[0],
                            'lat': coords[1],
                            'power_kw': 50.0,
                            'type': 'real'
                        })
                    
                    if real_stations_for_grid:
                        grid_manager.assign_charging_stations_to_grid(real_stations_for_grid)
                    
                    grid_file = os.path.join(scen_dir, "power_grid.pkl")
                    grid_manager.save(grid_file)
                else:
                    print(f"[WARNING] Grid construction failed - using fallback")
                    grid_manager = None

                # Step 6: Generate public charging stations (grid-aware if grid available)
                print(f"[INFO] Generating public charging stations")
                charging_stations_file = generate_public_charging_stations(
                    net_file, 
                    scen_dir, 
                    min_length=50,
                    power_grid_manager=grid_manager,
                    max_stations=100  # Limit to 100 best locations
                )
                print(f"[INFO] Public charging stations generated -> {charging_stations_file}")
                
                # Connect generated public stations to grid
                if grid_manager and grid_build_success and net:
                    print(f"[INFO] Connecting generated public charging stations to grid")
                    # Parse charging stations XML to get locations
                    cs_tree = ET.parse(charging_stations_file)
                    cs_root = cs_tree.getroot()
                    public_stations_for_grid = []
                    
                    for cs_elem in cs_root.findall('.//chargingStation'):
                        cs_id = cs_elem.get('id')
                        lane_id = cs_elem.get('lane')
                        
                        # Get lane coordinates from SUMO network
                        try:
                            edge_id = lane_id.rsplit('_', 1)[0]
                            edge = net.getEdge(edge_id)
                            lane = edge.getLane(0)
                            lane_shape = lane.getShape()
                            if lane_shape:
                                mid_idx = len(lane_shape) // 2
                                x, y = lane_shape[mid_idx]
                                
                                # Convert SUMO coords to lon/lat for grid manager
                                lon, lat = net.convertXY2LonLat(x, y)
                                
                                public_stations_for_grid.append({
                                    'id': cs_id,
                                    'lon': lon,
                                    'lat': lat,
                                    'power_kw': 200.0,
                                    'type': 'public'
                                })
                        except Exception as e:
                            print(f"[WARNING] Could not get coords for {cs_id}: {e}")
                    
                    if public_stations_for_grid:
                        grid_manager.assign_charging_stations_to_grid(public_stations_for_grid)
                        grid_manager.save(grid_file)  # Re-save with all stations
                        print(f"[INFO] Connected {len(public_stations_for_grid)} public stations to grid")

                # Step 7: Combine additional files
                copy_default_combined_additional(scenario)
                copy_vehicle_types_additional(scenario)
                
                # Update combined_additional.xml to use public_chargingstations.xml instead of osm.chargingstations.xml
                combined_add_path = os.path.join(scen_dir, "combined_additional.xml")
                if os.path.exists(combined_add_path):
                    tree = ET.parse(combined_add_path)
                    root = tree.getroot()
                    
                    # Remove private_wallboxes.xml include (not used in normal pipeline)
                    for include in root.findall('include'):
                        if include.get('href') == 'private_wallboxes.xml':
                            root.remove(include)
                            print(f"[INFO] Removed private_wallboxes.xml from combined_additional.xml")
                    
                    # Replace osm.chargingstations.xml with public_chargingstations.xml
                    for include in root.findall('include'):
                        if include.get('href') == 'osm.chargingstations.xml':
                            include.set('href', 'public_chargingstations.xml')
                            print(f"[INFO] Updated combined_additional.xml to use public_chargingstations.xml")
                    
                    tree.write(combined_add_path, encoding='utf-8', xml_declaration=True)

                # Step 8: Create sim.sumocfg
                create_sumo_config(net_file, trips_file, "combined_additional.xml", scen_dir,
                                   stationfinder_radius=sim_params.get('stationfinder_radius', 3000),
                                   duration=sim_params.get('duration', 0))

                # Step 9: Run simulation to generate logs
                print("[INFO] Running SUMO simulation...")
                sumo_command = ["sumo", "-c", "sim.sumocfg"]
                try:
                    subprocess.run(sumo_command, check=True, cwd=scen_dir)
                    print("[INFO] SUMO simulation completed successfully.")
                except subprocess.CalledProcessError as e:
                    raise RuntimeError(f"SUMO simulation failed: {e}")

                # Step 10: convert logs to CSV
                convert_logs_to_csv(
                    os.path.join(scen_dir, "fcd_output.xml.gz"),
                    os.path.join(scen_dir, "battery_output.xml.gz"),
                    os.path.join(scen_dir, "combined_additional.xml"),
                    os.path.join(scen_dir, "sumo_merged_output.csv")
                )

                print("[INFO] Logs converted to CSV successfully.")

                # Step 11: generate traffic heatmap from logs
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

                # Step 12: generate stations from log (grid-aware if grid available)
                heatmap_json_file = os.path.join(scen_dir, "no_station_heatmap.json")
                train_from_sumo_log_no_stations(
                    os.path.join(scen_dir, "sumo_merged_output.csv"),
                    os.path.join(scen_dir, "no_station_charging_suggestions.csv"),
                    os.path.join(scen_dir, "no_station_areas.geojson"),
                    os.path.join(scen_dir, "suggested_charging_stations.add.xml"),
                    net_file,  # Pass network file for coordinate conversion
                    heatmap_json_file,  # Output heatmap data for gradient visualization
                    power_grid_manager=grid_manager if grid_build_success else None,  # Grid-aware placement
                    fast_mode=True  # OPTIMIZED: spatial grid pre-clustering, sampling, larger EPS/MIN_SAMPLES
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

                # Export power grid network as GeoJSON for visualization
                power_grid_network = None
                if grid_build_success and grid_manager:
                    try:
                        power_grid_network = grid_manager.to_geojson()
                        print(f"[INFO] Exported power grid network: {power_grid_network['properties']['total_buses']} buses, "
                              f"{power_grid_network['properties']['total_lines']} lines, "
                              f"{power_grid_network['properties']['total_transformers']} transformers")
                    except Exception as e:
                        print(f"[WARNING] Could not export grid network: {e}")

                # Respond with success
                resp = {
                    "ok": True,
                    "message": "Pipeline completed successfully",
                    "scenarioDir": scen_dir,
                    "networkFile": net_file,
                    "poiFiles": poi_files,
                    "poiGeoJSON": poi_geojson,
                    "powerGridNetwork": power_grid_network,
                    "powerGridStats": power_grid_network.get('properties') if power_grid_network else None,
                    "realChargingStations": real_charging_stations,
                    "heatmapGeoJSON": heatmap_geojson,
                    "heatmapData": heatmap_data,
                    "trafficHeatmap": traffic_heatmap_data,
                    "chargingStations": {
                        "file": os.path.basename(charging_stations_file),
                        "description": "Public charging stations"
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
        
        elif parsed.path == "/buildWithTraci":
            try:
                length = int(self.headers.get("Content-Length", "0"))
                raw = self.rfile.read(length) if length else b"{}"
                data = json.loads(raw.decode("utf-8") or "{}")
                bbox = data.get("bbox")
                scenario = data.get("scenario") or "scenario"
                sim_params = data.get("params") or {}

                # Step 1: Download OSM data -> returns full path to the file
                osm_file = download_osm_data(bbox, scenario)
                scen_dir = os.path.dirname(osm_file)

                # Save simulation parameters for downstream scripts (performativeMainSim2 reads these)
                sim_params_file = os.path.join(scen_dir, "sim_params.json")
                with open(sim_params_file, 'w', encoding='utf-8') as f:
                    json.dump(sim_params, f, indent=2)
                print(f"[INFO] Simulation parameters saved -> {sim_params_file}")

                # Extract real already existing charging stations
                real_charging_stations = extract_real_charging_stations(osm_file)
                print(f"[INFO] Extracted real charging stations: {len(real_charging_stations['features'])} found")

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
                print(f"[INFO] POI edge assignments completed: {len(edge_files)} files generated")

                # Step 5: Generate trips
                print(f"[INFO] Generating vehicle trips")
                # edge_files is already a list from assign_poi_to_edges
                edge_files_list = edge_files if isinstance(edge_files, list) else list(edge_files.values())
                
                _duration = int(sim_params.get('duration', 0))
                if 0 < _duration < 36000:
                    trips_file = generate_trips_test(net_file, edge_files_list, scen_dir, sim_params=sim_params)
                    print(f"[INFO] FAST trips generated (duration {_duration}s < 10h threshold) -> {trips_file}")
                else:
                    trips_file = generate_trips(net_file, edge_files_list, scen_dir, sim_params=sim_params)
                    print(f"[INFO] Full trips generated -> {trips_file}")

                # Step 5.5: Build synthetic power grid from OSM road network
                print(f"[INFO] Building synthetic power grid from OSM road network")
                grid_manager = PowerGridManager(osm_file=osm_file, scenario_name=scenario)
                grid_build_success = grid_manager.build_grid()
                
                try:
                    import sumolib
                    net = sumolib.net.readNet(net_file)
                except ImportError:
                    print("[WARNING] sumolib not available - some grid features may not work")
                    net = None
                
                if grid_build_success:
                    # Connect real charging stations to grid
                    real_stations_for_grid = []
                    
                    for feature in real_charging_stations['features']:
                        props = feature['properties']
                        coords = feature['geometry']['coordinates']
                        real_stations_for_grid.append({
                            'id': f"real_cs_{props.get('osm_id', len(real_stations_for_grid))}",
                            'lon': coords[0],
                            'lat': coords[1],
                            'power_kw': 50.0,
                            'type': 'real'
                        })
                    
                    if real_stations_for_grid:
                        grid_manager.assign_charging_stations_to_grid(real_stations_for_grid)
                    
                    grid_file = os.path.join(scen_dir, "power_grid.pkl")
                    grid_manager.save(grid_file)
                else:
                    print(f"[WARNING] Grid construction failed - using fallback")
                    grid_manager = None

                # Step 6: Generate public charging stations (grid-aware if grid available)
                print(f"[INFO] Generating public charging stations")
                charging_stations_file = generate_public_charging_stations(
                    net_file, 
                    scen_dir, 
                    min_length=50,
                    power_grid_manager=grid_manager if grid_build_success else None,
                    max_stations=100  # Limit to 100 best locations
                )
                print(f"[INFO] Public charging stations generated -> {charging_stations_file}")
                
                # Connect generated public stations to grid
                if grid_manager and grid_build_success and net:
                    print(f"[INFO] Connecting generated public charging stations to grid")
                    # Parse charging stations XML to get locations
                    cs_tree = ET.parse(charging_stations_file)
                    cs_root = cs_tree.getroot()
                    public_stations_for_grid = []
                    
                    for cs_elem in cs_root.findall('.//chargingStation'):
                        cs_id = cs_elem.get('id')
                        lane_id = cs_elem.get('lane')
                        
                        # Get lane coordinates from SUMO network
                        try:
                            edge_id = lane_id.rsplit('_', 1)[0]
                            edge = net.getEdge(edge_id)
                            lane = edge.getLane(0)
                            lane_shape = lane.getShape()
                            if lane_shape:
                                mid_idx = len(lane_shape) // 2
                                x, y = lane_shape[mid_idx]
                                
                                # Convert SUMO coords to lon/lat
                                lon, lat = net.convertXY2LonLat(x, y)
                                
                                public_stations_for_grid.append({
                                    'id': cs_id,
                                    'lon': lon,
                                    'lat': lat,
                                    'power_kw': 200.0,
                                    'type': 'public'
                                })
                        except Exception as e:
                            pass
                    
                    if public_stations_for_grid:
                        grid_manager.assign_charging_stations_to_grid(public_stations_for_grid)
                        grid_manager.save(grid_file)  # Re-save with all stations
                        print(f"[INFO] Connected {len(public_stations_for_grid)} public stations to grid")

                # Step 7: Copy default additional files (BEFORE wallbox generation so we can modify combined_additional.xml)
                copy_default_combined_additional(scenario)
                copy_vehicle_types_additional(scenario)

                # Step 8: Generate private wallboxes (50% of EV owners)
                print(f"[INFO] Generating private wallboxes at 50% of EV owner homes")
                
                # Read the trips file to get persons data
                trips_tree = ET.parse(trips_file)
                trips_root = trips_tree.getroot()
                
                # Extract persons data from trips XML
                persons_data = []
                for vehicle in trips_root.findall('vehicle'):
                    veh_id = vehicle.get('id')
                    veh_type = vehicle.get('type')
                    
                    # Get home edge from the route (first edge in the route)
                    route_elem = vehicle.find('route')
                    if route_elem is not None:
                        edges = route_elem.get('edges', '').split()
                        if edges:
                            home_edge = edges[0]  # First edge is home
                            
                            # Determine if this is an EV based on vehicle type
                            # mainGenerateTrips.py creates "veh_ev" for EVs
                            # Wallbox owners will later get unique types "veh_ev_personXXX"
                            is_ev = veh_type.startswith("veh_ev")
                            
                            person_data = {
                                'id': veh_id,
                                'home': home_edge,
                                'vehicle_type': veh_type,
                                'has_ev': is_ev
                            }
                            persons_data.append(person_data)
                
                # Generate wallboxes at 5% of EV owner homes
                try:
                    wallbox_file, wallbox_homes_geojson_path, vehicle_types_file = generate_private_wallboxes(
                        net_file, 
                        persons_data, 
                        scen_dir,
                        trips_file=trips_file,  # Pass trips file for updating vehicle types
                        wallbox_share=0.50  # 50% of EV owners get wallboxes
                    )
                    print(f"[INFO] Private wallboxes generated -> {wallbox_file}")
                    
                    # Read wallbox homes GeoJSON for UI visualization
                    wallbox_homes_geojson = None
                    if os.path.exists(wallbox_homes_geojson_path):
                        with open(wallbox_homes_geojson_path, 'r', encoding='utf-8') as f:
                            wallbox_homes_geojson = json.load(f)
                        print(f"[INFO] Loaded wallbox homes GeoJSON: {len(wallbox_homes_geojson.get('features', []))} homes")
                    
                    # If unique vehicle types were generated, use them instead of default
                    if vehicle_types_file and os.path.exists(vehicle_types_file):
                        print(f"[INFO] Using wallbox-specific vehicle types: {os.path.basename(vehicle_types_file)}")
                        # Update combined_additional.xml to reference the new vehicle types file
                        # IMPORTANT: Remove private_wallboxes.xml so stationfinder doesn't route vehicles there
                        # TraCI will manage wallboxes as virtual stations based on vehicle proximity
                        combined_add_path = os.path.join(scen_dir, "combined_additional.xml")
                        if os.path.exists(combined_add_path):
                            tree = ET.parse(combined_add_path)
                            root = tree.getroot()
                            
                            # Remove private_wallboxes.xml from SUMO's additional files
                            # This prevents stationfinder from routing vehicles to wallboxes
                            for include in root.findall('include'):
                                if include.get('href') == 'private_wallboxes.xml':
                                    root.remove(include)
                                    print(f"[INFO] Removed private_wallboxes.xml from SUMO - TraCI manages wallboxes")
                            
                            # Replace osm.chargingstations.xml with public_chargingstations.xml
                            for include in root.findall('include'):
                                if include.get('href') == 'osm.chargingstations.xml':
                                    include.set('href', 'public_chargingstations.xml')
                                    print(f"[INFO] Updated combined_additional.xml to use public_chargingstations.xml")
                            
                            # Replace vehicle_types.add.xml include with wallbox_vehicle_types.add.xml
                            for include in root.findall('include'):
                                if include.get('href') == 'vehicle_types.add.xml':
                                    include.set('href', os.path.basename(vehicle_types_file))
                            tree.write(combined_add_path, encoding='utf-8', xml_declaration=True)
                            print(f"[INFO] Updated combined_additional.xml to use wallbox vehicle types")
                    
                    # Connect private wallboxes to grid
                    if grid_manager and grid_build_success and net and wallbox_file and os.path.exists(wallbox_file):
                        print(f"[INFO] Connecting private wallboxes to grid")
                        # Parse wallboxes XML to get locations
                        wb_tree = ET.parse(wallbox_file)
                        wb_root = wb_tree.getroot()
                        wallboxes_for_grid = []
                        
                        for wb_elem in wb_root.findall('.//chargingStation'):
                            wb_id = wb_elem.get('id')
                            lane_id = wb_elem.get('lane')
                            
                            # Get lane coordinates from SUMO network
                            try:
                                edge_id = lane_id.rsplit('_', 1)[0]
                                edge = net.getEdge(edge_id)
                                lane = edge.getLane(0)
                                lane_shape = lane.getShape()
                                if lane_shape:
                                    mid_idx = len(lane_shape) // 2
                                    x, y = lane_shape[mid_idx]
                                    
                                    # Convert SUMO coords to lon/lat for grid manager
                                    lon, lat = net.convertXY2LonLat(x, y)
                                    
                                    wallboxes_for_grid.append({
                                        'id': wb_id,
                                        'lon': lon,
                                        'lat': lat,
                                        'power_kw': 11.0,
                                        'type': 'wallbox'
                                    })
                            except Exception as wb_err:
                                print(f"[WARNING] Could not get coords for {wb_id}: {wb_err}")
                        
                        if wallboxes_for_grid:
                            grid_manager.assign_charging_stations_to_grid([], private_wallboxes=wallboxes_for_grid)
                            grid_manager.save(grid_file)  # Re-save with wallboxes
                            print(f"[INFO] Connected {len(wallboxes_for_grid)} private wallboxes to grid")
                    
                except Exception as e:
                    print(f"[WARNING] Could not generate private wallboxes: {e}")
                    import traceback
                    traceback.print_exc()
                    wallbox_homes_geojson = None

                # Step 9: Create sim.sumocfg
                create_sumo_config(net_file, trips_file, "combined_additional.xml", scen_dir,
                                   stationfinder_radius=sim_params.get('stationfinder_radius', 3000),
                                   duration=sim_params.get('duration', 0))

                # Step 9b: Calculate dynamic grid power based on map area
                try:
                    import math
                    if bbox and len(bbox) == 4:
                        minLon, minLat, maxLon, maxLat = bbox
                        avg_lat_rad = math.radians((minLat + maxLat) / 2.0)
                        width_km = (maxLon - minLon) * math.cos(avg_lat_rad) * 111.32
                        height_km = (maxLat - minLat) * 111.32
                        area_km2 = width_km * height_km
                    else:
                        # Fallback: estimate from network file bounds
                        area_km2 = 1.0  # Default 1 km²

                    # Power density: ~1500 kW/km² for typical urban residential area
                    # This accounts for transformer capacity, line limits, and typical load mix
                    POWER_DENSITY_KW_PER_KM2 = 1500
                    dynamic_grid_power_kw = max(200, min(50000, area_km2 * POWER_DENSITY_KW_PER_KM2))

                    grid_config = {
                        "max_grid_power_kw": round(dynamic_grid_power_kw, 0),
                        "area_km2": round(area_km2, 4),
                        "power_density_kw_per_km2": POWER_DENSITY_KW_PER_KM2,
                        "bbox": bbox
                    }
                    grid_config_file = os.path.join(scen_dir, "grid_config.json")
                    with open(grid_config_file, 'w', encoding='utf-8') as f:
                        json.dump(grid_config, f, indent=2)
                    print(f"[INFO] Dynamic grid power: {dynamic_grid_power_kw:.0f} kW for {area_km2:.3f} km² area -> {grid_config_file}")
                except Exception as e:
                    print(f"[WARNING] Could not calculate dynamic grid power: {e}")

                # Step 10: Run TraCI simulation with V2G and home charging
                # NOTE: This replaces the standard headless SUMO simulation
                print("[INFO] Running TraCI simulation with V2G support...")
                traci_script = os.path.join(os.path.dirname(__file__), "performativeMainSim2.py")
                traci_command = [sys.executable, traci_script, scen_dir]
                try:
                    result = subprocess.run(traci_command, check=True, capture_output=True, text=True)
                    print(result.stdout)
                    if result.stderr:
                        print(f"[STDERR] {result.stderr}")
                    print("[INFO] TraCI simulation completed successfully")
                except subprocess.CalledProcessError as e:
                    print(f"[ERROR] TraCI simulation failed: {e.stderr}")
                    raise Exception(f"TraCI simulation failed: {e.stderr}")

                # Step 11: Convert SUMO logs to CSV for analysis
                print("[INFO] Converting SUMO logs to CSV...")
                convert_logs_to_csv(
                    os.path.join(scen_dir, "fcd_output.xml.gz"),
                    os.path.join(scen_dir, "battery_output.xml.gz"),
                    os.path.join(scen_dir, "combined_additional.xml"),
                    os.path.join(scen_dir, "sumo_merged_output.csv")
                )
                print("[INFO] Logs converted to CSV successfully.")

                # Step 12: Generate traffic heatmap from logs
                traffic_heatmap_file = os.path.join(scen_dir, "traffic_heatmap.json")
                try:
                    generate_traffic_heatmap(
                        os.path.join(scen_dir, "sumo_merged_output.csv"),
                        net_file,
                        traffic_heatmap_file,
                        sample_rate=0.25  # 25% sampling to reduce data size
                    )
                    print("[INFO] Traffic heatmap generated successfully.")
                except Exception as e:
                    print(f"[WARNING] Traffic heatmap generation failed: {e}")

                # Step 13: Generate charging demand heatmap from low-SOC analysis (grid-aware)
                heatmap_json_file = os.path.join(scen_dir, "no_station_heatmap.json")
                try:
                    train_from_sumo_log_no_stations(
                        os.path.join(scen_dir, "sumo_merged_output.csv"),
                        os.path.join(scen_dir, "no_station_charging_suggestions.csv"),
                        os.path.join(scen_dir, "no_station_areas.geojson"),
                        os.path.join(scen_dir, "suggested_charging_stations.add.xml"),
                        net_file,
                        heatmap_json_file,
                        power_grid_manager=grid_manager if grid_build_success else None,  # Grid-aware placement
                        fast_mode=True  # OPTIMIZED: spatial grid pre-clustering, sampling, larger EPS/MIN_SAMPLES
                    )
                    print("[INFO] Charging demand heatmap generated successfully.")
                except Exception as e:
                    print(f"[WARNING] Charging demand analysis failed: {e}")

                # Read heatmap data files
                heatmap_geojson_file = os.path.join(scen_dir, "no_station_areas.geojson")
                
                heatmap_geojson = None
                if os.path.exists(heatmap_geojson_file):
                    with open(heatmap_geojson_file, "r", encoding="utf-8") as f:
                        heatmap_geojson = json.load(f)

                heatmap_data = None
                if os.path.exists(heatmap_json_file):
                    with open(heatmap_json_file, "r", encoding="utf-8") as f:
                        heatmap_data = json.load(f)

                traffic_heatmap_data = None
                if os.path.exists(traffic_heatmap_file):
                    with open(traffic_heatmap_file, "r", encoding="utf-8") as f:
                        traffic_heatmap_data = json.load(f)

                # Export power grid network as GeoJSON for visualization
                power_grid_network = None
                if grid_build_success and grid_manager:
                    try:
                        power_grid_network = grid_manager.to_geojson()
                        print(f"[INFO] Exported power grid network: {power_grid_network['properties']['total_buses']} buses, "
                              f"{power_grid_network['properties']['total_lines']} lines, "
                              f"{power_grid_network['properties']['total_transformers']} transformers")
                    except Exception as e:
                        print(f"[WARNING] Could not export grid network: {e}")

                # Read TraCI simulation outputs
                traci_logs_dir = os.path.join(scen_dir, "traci_logs")
                traci_model_log = os.path.join(traci_logs_dir, "model_log_data.csv")
                traci_charging_sessions = os.path.join(traci_logs_dir, "charging_sessions.csv")
                
                traci_summary = {
                    "logs_available": os.path.exists(traci_model_log),
                    "model_log": os.path.basename(traci_model_log) if os.path.exists(traci_model_log) else None,
                    "charging_sessions": os.path.basename(traci_charging_sessions) if os.path.exists(traci_charging_sessions) else None,
                    "logs_dir": "traci_logs"
                }

                # Read V2G summary statistics
                v2g_summary_file = os.path.join(traci_logs_dir, "v2g_summary.json")
                v2g_stats = None
                if os.path.exists(v2g_summary_file):
                    with open(v2g_summary_file, 'r', encoding='utf-8') as f:
                        v2g_stats = json.load(f)
                    print(f"[INFO] V2G summary loaded: {v2g_stats.get('v2g', {}).get('active_vehicles', 0)} V2G vehicles, "
                          f"{v2g_stats.get('v2g', {}).get('total_discharged_kwh', 0):.2f} kWh discharged")

                # Read charts data for UI visualization
                charts_file = os.path.join(traci_logs_dir, "charts_data.json")
                charts_data = None
                if os.path.exists(charts_file):
                    with open(charts_file, 'r', encoding='utf-8') as f:
                        charts_data = json.load(f)
                    print(f"[INFO] Charts data loaded: {len(charts_data)} chart datasets")

                # Respond with success
                resp = {
                    "ok": True,
                    "message": "Pipeline completed successfully with TraCI simulation (V2G + Home Charging + Private Wallboxes)",
                    "scenarioDir": scen_dir,
                    "networkFile": net_file,
                    "poiFiles": poi_files,
                    "poiGeoJSON": poi_geojson,
                    "powerGridNetwork": power_grid_network,
                    "powerGridStats": power_grid_network.get('properties') if power_grid_network else None,
                    "realChargingStations": real_charging_stations,
                    "heatmapGeoJSON": heatmap_geojson,
                    "heatmapData": heatmap_data,
                    "trafficHeatmap": traffic_heatmap_data,
                    "wallboxHomes": wallbox_homes_geojson,
                    "chargingStations": {
                        "file": os.path.basename(charging_stations_file),
                        "description": "Public charging stations"
                    },
                    "traciSimulation": traci_summary,
                    "v2gStats": v2g_stats,
                    "chartsData": charts_data,
                    "note": "TraCI simulation with V2G + dynamic home charging + private wallboxes (50% of EV owners) - heatmaps show effects of smart charging control"
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
                import traceback
                traceback.print_exc()
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
