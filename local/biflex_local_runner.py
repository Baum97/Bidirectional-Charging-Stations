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
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse

from extract_pois import extract_pois
from getPOIEdgeIDs import assign_poi_to_edges
from mainGenerateTrips import generate_trips
from mainGenerateChargingStations import generate_charging_stations

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
    subprocess.run(cmd, check=True, cwd=cwd)


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
        "    <time>\n"
        "        <begin value=\"0\"/>\n"
        "        <step-length value=\"1\"/>\n"
        "    </time>\n"
        "    <processing>\n"
        "        <ignore-route-errors value=\"true\"/>\n"
        "        <tls.actuated.jam-threshold value=\"30\"/>\n"
        "        <lateral-resolution value=\"1.6\"/>\n"
        "        <collision.action value=\"none\"/>\n"
        "        <max-depart-delay value=\"900\"/>\n"
        "        <device.battery.probability value=\"1\"/>\n"
        "        <device.battery.explicit value=\"veh_ev\"/>\n"
        "        <device.rerouting.probability value=\"1.0\"/>\n"
        "        <device.rerouting.explicit value=\"veh_ev\"/>\n"
        "        <device.stationfinder.probability value=\"1\"/>\n"
        "        <device.stationfinder.explicit value=\"veh_ev\"/>\n"
        "        <device.stationfinder.rescueTime value=\"3600\"/>\n"
        "        <device.stationfinder.reserveFactor value=\"1.1\"/>\n"
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

                # Step 2: Build SUMO network
                net_file = build_sumo_network(osm_file, scenario)

                # Step 3: Extract POIs
                print(f"[INFO] Extracting POIs -> {scen_dir}")
                poi_files = extract_pois(osm_file, scen_dir)

                # Step 4: Assign POIs to edges
                print(f"[INFO] Assigning POIs to edges -> {poi_files}")
                edge_files = assign_poi_to_edges(net_file, poi_files)

                # Step 5: Generate trips
                print(f"[INFO] Generating trips -> {edge_files}")
                trips_file = generate_trips(net_file, edge_files, scen_dir)
                print(f"[INFO] Trips generated -> {trips_file}")

                # Step 6: Generate charging stations
                print(f"[INFO] Generating charging stations")
                charging_stations_file = generate_charging_stations(net_file, scen_dir, min_length=50)
                print(f"[INFO] Charging stations generated -> {charging_stations_file}")

                # Step 7: Combine additional files
                copy_default_combined_additional(scenario)
                copy_vehicle_types_additional(scenario)

                # Step 8: Create sim.sumocfg
                create_sumo_config(net_file, trips_file, "combined_additional.xml", scen_dir)

                # Respond with success
                resp = {
                    "ok": True,
                    "message": "Pipeline completed successfully",
                    "scenarioDir": scen_dir,
                    "networkFile": net_file,
                    "poiFiles": poi_files,
                }
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
