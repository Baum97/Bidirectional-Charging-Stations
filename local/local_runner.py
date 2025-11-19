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
    if os.name == 'nt':
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


def build_scenario(bbox, scenario, prefix="test_name"):
    try:
        if not isinstance(bbox, list) or len(bbox) != 4:
            raise ValueError("bbox must be [minLon, minLat, maxLon, maxLat]")
        paths = _sumo_paths()

        base_dir = os.path.join("data", "scenarios", scenario)
        os.makedirs(base_dir, exist_ok=True)
        print(f"[INFO] Created base directory: {base_dir}")

        minLon, minLat, maxLon, maxLat = bbox
        bbox_str = f"{minLon},{minLat},{maxLon},{maxLat}"

        # Fetch OSM extract
        print(f"[INFO] Fetching OSM data for bbox: {bbox_str}")
        _run([sys.executable, paths["osmGet"], "-b", bbox_str, "-p", prefix], cwd=base_dir)

        # Determine the produced OSM file (osmGet may create compressed files)
        print("[INFO] Determining the produced OSM file...")
        allowed_suffixes = (".osm.xml", ".osm", ".osm.gz", ".osm.bz2", ".pbf", ".osm.pbf")
        osm_file = None
        for fname in sorted(os.listdir(base_dir)):
            low = fname.lower()
            if (low.startswith("map") or low.startswith(f"{prefix}_bbox")) and any(low.endswith(s) for s in allowed_suffixes):
                osm_file = fname
                break
        if not osm_file:
            listing = "\n".join(sorted(os.listdir(base_dir)))
            raise RuntimeError(
                "osmGet did not produce an OSM file matching 'map*' or '<prefix>_bbox*' with suffixes {}. Directory contents:\n{}".format(
                    ", ".join(allowed_suffixes), listing
                )
            )
        print(f"[INFO] Found OSM file: {osm_file}")

        # Build network
        print("[INFO] Building network...")
        net_file = "osm.net.xml.gz"
        _run([paths["netconvert"], "--osm-files", osm_file, "-o", net_file, "--speed-in-kmh", "--proj.utm"], cwd=base_dir)

        # Generate trips and routes
        print("[INFO] Generating trips and routes...")
        trips_file = "osm.passenger.trips.xml"
        _run([sys.executable, paths["randomTrips"], "-n", net_file, "-o", trips_file, "-r", "routes.rou.xml", "--seed", "42", "--end", "3600", "--period", "1.0"], cwd=base_dir)

        # Write detailed sumocfg
        print("[INFO] Writing detailed SUMO configuration file...")
        cfg = (
            "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n"
            "<sumoConfiguration xmlns:xsi=\"http://www.w3.org/2001/XMLSchema-instance\" xsi:noNamespaceSchemaLocation=\"http://sumo.dlr.de/xsd/sumoConfiguration.xsd\">\n"
            "    <input>\n"
            f"        <net-file value=\"{net_file}\"/>\n"
            f"        <route-files value=\"{trips_file}\"/>\n"
            # "        <additional-files value=\"combined_additional.xml\"/>\n"
            "    </input>\n"
            "    <time>\n"
            "        <begin value=\"10000\"/>\n"
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

        print("[INFO] Scenario build completed successfully.")
        return base_dir

    except Exception as e:
        print(f"[ERROR] An error occurred: {e}")
        raise


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
        if parsed.path != "/build":
            self.send_response(404)
            self._set_cors()
            self.end_headers()
            return
        try:
            length = int(self.headers.get('Content-Length', '0'))
            raw = self.rfile.read(length) if length else b"{}"
            data = json.loads(raw.decode('utf-8') or '{}')
            bbox = data.get('bbox')
            scenario = data.get('scenario') or 'scenario'
            scen_dir = build_scenario(bbox, scenario)
            resp = {"ok": True, "message": "scenario built", "scenarioDir": scen_dir}
            payload = json.dumps(resp).encode('utf-8')
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self._set_cors()
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
        except Exception as e:
            msg = {"ok": False, "error": str(e)}
            payload = json.dumps(msg).encode('utf-8')
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
