"""
Power Grid Manager – Builds a synthetic distribution grid from OSM road data.

Creates a pandapower model with realistic hierarchy:
  ┌──────────────┐
  │  HV 110 kV   │  (External grid / slack bus)
  └──────┬───────┘
         │  HV/MV Transformer(s)
  ┌──────┴───────┐
  │  MV  20 kV   │  (Distribution substations at major intersections)
  └──────┬───────┘
         │  MV/LV Transformer(s)
  ┌──────┴───────┐
  │  LV  0.4 kV  │  (Street-level distribution at residential intersections)
  └──────────────┘
         │  Loads (charging stations, wallboxes)

Algorithm:
1. Parse OSM road network (residential, tertiary, etc.)
2. Identify road intersections (nodes referenced by ≥ 2 ways)
3. Spatial-grid sampling (~300 m cells) → select representative bus locations
4. Classify as MV (tertiary+) or LV (residential) based on road type
5. Build pandapower buses, same-voltage lines along road paths, transformers
6. Add HV slack bus + HV/MV transformers
7. Validate full connectivity via NetworkX
"""

import pandapower as pp
import numpy as np
import json
import pickle
import os
import xml.etree.ElementTree as ET
from math import radians, cos, sin, asin, sqrt
from collections import defaultdict, deque


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

def haversine(lon1, lat1, lon2, lat2):
    """Great-circle distance in **metres** between two points (decimal degrees)."""
    lon1, lat1, lon2, lat2 = map(radians, [lon1, lat1, lon2, lat2])
    dlon = lon2 - lon1
    dlat = lat2 - lat1
    a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    return 6_371_000 * 2 * asin(sqrt(a))


# ---------------------------------------------------------------------------
# Standard pandapower types
# ---------------------------------------------------------------------------

def _line_type(voltage_kv):
    if voltage_kv >= 100:
        return "149-AL1/24-ST1A 110.0"
    elif voltage_kv >= 10:
        return "NA2XS2Y 1x185 RM/25 12/20 kV"
    else:
        return "NAYY 4x150 SE"


def _trafo_type(hv_kv, lv_kv):
    if hv_kv >= 100 and lv_kv >= 10:
        return "25 MVA 110/20 kV"
    elif hv_kv >= 10:
        return "0.4 MVA 20/0.4 kV"
    else:
        return "0.25 MVA 10/0.4 kV"


# ═══════════════════════════════════════════════════════════════════════════
# Main class
# ═══════════════════════════════════════════════════════════════════════════

class PowerGridManager:
    """
    Builds and manages a synthetic distribution grid from OSM road data.

    Public API
    ----------
    build_grid()                         → bool
    assign_charging_stations_to_grid()   → dict
    get_grid_capacity_at_location()      → dict
    to_geojson()                         → dict (FeatureCollection)
    save(filepath) / load(filepath)
    """

    # --- Tuning knobs (class-level) ---
    GRID_CELL_M = 300            # Spatial sampling cell size (metres)
    MAX_LINE_SEARCH_M = 900      # BFS distance limit for line creation
    MAX_LINE_LENGTH_KM = 1.0     # Reject lines longer than this

    MV_HIGHWAYS = frozenset({
        "tertiary", "tertiary_link",
        "secondary", "secondary_link",
        "primary", "primary_link",
        "trunk", "trunk_link",
    })
    LV_HIGHWAYS = frozenset({
        "residential", "living_street",
        "service", "unclassified",
    })

    # -----------------------------------------------------------------
    # Init
    # -----------------------------------------------------------------

    def __init__(self, osm_file=None, scenario_name="default"):
        self.osm_file = osm_file
        self.scenario_name = scenario_name
        self.net = pp.create_empty_network(name=f"Grid_{scenario_name}")

        # Public mappings (used by GridController / export)
        self.bus_to_coords = {}        # bus_idx → (lon, lat)
        self.station_to_bus = {}       # station_id → {bus_idx, load_idx, coords, …}
        self.line_paths = {}           # line_idx → [[lon, lat], …]  (for GeoJSON)
        self.bus_paths = {}            # bus_idx → [[lon, lat], …] (busbar line along road)
        self.station_connection_paths = {}  # station_id → [[lon, lat], …]

        # Internal book-keeping
        self._osm_nodes = {}           # osm_node_id → (lon, lat)
        self._road_segments = []       # [(node_a, node_b, highway_type)]
        self._node_to_ways = defaultdict(set)
        self._adj = defaultdict(set)   # node_id → {neighbour_id, …}
        self._intersection_nodes = set()
        self._selected_nodes = {}      # osm_node_id → {lon, lat, voltage_kv, bus_idx}
        self._bus_to_node = {}         # bus_idx → osm_node_id (reverse mapping)

        # Statistics
        self.stats = {
            "total_osm_road_nodes": 0,
            "total_intersections": 0,
            "hv_buses": 0,
            "mv_buses": 0,
            "lv_buses": 0,
            "lines": 0,
            "transformers": 0,
            "slack_bus": None,
            "loads": 0,
            "area_km2": 0.0,
        }

    # ═════════════════════════════════════════════════════════════════
    # PUBLIC API
    # ═════════════════════════════════════════════════════════════════

    def build_grid(self):
        """Build complete synthetic distribution grid.  Returns *True* on success."""
        if not self.osm_file or not os.path.exists(self.osm_file):
            print("[WARNING] No OSM file – creating minimal fallback grid")
            return self._create_fallback_grid()

        print(f"[INFO] Building synthetic distribution grid from {os.path.basename(self.osm_file)}")

        self._parse_osm()
        self._find_intersections()
        self._sample_bus_locations()
        self._create_buses()
        self._create_lines()
        self._create_transformers()
        self._add_hv_connection()
        self._validate_network()

        self._print_stats()
        return True

    # Alias kept for backward-compat (old code called build_grid_from_osm)
    build_grid_from_osm = build_grid

    def assign_charging_stations_to_grid(self, charging_stations, private_wallboxes=None):
        """Connect charging stations (and wallboxes) as controllable loads."""
        if charging_stations:
            print(f"[INFO] Connecting {len(charging_stations)} charging stations to grid")
        for s in charging_stations:
            self._attach_station(s)

        if private_wallboxes:
            print(f"[INFO] Connecting {len(private_wallboxes)} private wallboxes to grid")
            for wb in private_wallboxes:
                wb.setdefault("power_kw", 11.0)
                wb.setdefault("type", "wallbox")
                self._attach_station(wb)

        print(f"[INFO] Total loads in grid: {self.stats['loads']}")
        return self.station_to_bus

    def get_grid_capacity_at_location(self, lon, lat, radius_m=1000):
        """Estimate grid capacity at a geographic location."""
        bus = self._find_nearest_bus(lon, lat, max_m=radius_m)
        if bus is None:
            return {
                "available_power_kw": 0.0,
                "bus_idx": None,
                "voltage_kv": 0.0,
                "distance_m": float("inf"),
                "grid_quality": "none",
            }

        bcoords = self.bus_to_coords[bus]
        dist = haversine(lon, lat, bcoords[0], bcoords[1])
        vkv = float(self.net.bus.at[bus, "vn_kv"])
        existing_mw = float(self.net.load[self.net.load.bus == bus]["p_mw"].sum())

        cap_map = {0.4: 500.0, 20.0: 5000.0, 110.0: 50000.0}
        max_cap = cap_map.get(vkv, 5000.0)
        avail = max(0.0, max_cap - existing_mw * 1000)

        if dist < 100:
            quality = "excellent"
        elif dist < 300:
            quality = "good"
        elif dist < 600:
            quality = "fair"
        else:
            quality = "poor"

        return {
            "available_power_kw": avail,
            "bus_idx": bus,
            "voltage_kv": vkv,
            "distance_m": dist,
            "grid_quality": quality,
        }

    # -----------------------------------------------------------------
    # GeoJSON export (for UI visualisation)
    # -----------------------------------------------------------------

    def to_geojson(self):
        features = []

        # --- Buses (Points - network nodes) ---
        for bidx, coords in self.bus_to_coords.items():
            vkv = float(self.net.bus.at[bidx, "vn_kv"])
            if vkv >= 100:
                btype, color = "HV", "#e74c3c"
            elif vkv >= 10:
                btype, color = "MV", "#f39c12"
            else:
                btype, color = "LV", "#3498db"

            features.append({
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": list(coords)},
                "properties": {
                    "type": "bus",
                    "bus_type": btype,
                    "bus_idx": int(bidx),
                    "voltage_kv": vkv,
                    "name": str(self.net.bus.at[bidx, "name"]),
                    "color": color,
                },
            })

        # --- Lines (road-following polylines) ---
        for lidx, ldata in self.net.line.iterrows():
            fb, tb = int(ldata["from_bus"]), int(ldata["to_bus"])
            if fb not in self.bus_to_coords or tb not in self.bus_to_coords:
                continue
            path = self.line_paths.get(int(lidx))
            if not path:
                path = [list(self.bus_to_coords[fb]), list(self.bus_to_coords[tb])]
            features.append({
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": path},
                "properties": {
                    "type": "line",
                    "line_idx": int(lidx),
                    "from_bus": fb,
                    "to_bus": tb,
                    "length_km": round(float(ldata["length_km"]), 3),
                    "color": "#95a5a6",
                },
            })

        # --- Transformers (point at LV bus location) ---
        for tidx, tdata in self.net.trafo.iterrows():
            hb, lb = int(tdata["hv_bus"]), int(tdata["lv_bus"])
            if hb not in self.bus_to_coords or lb not in self.bus_to_coords:
                continue
            # Place transformer symbol at the LV bus (that's where the device sits)
            lv_coords = self.bus_to_coords[lb]
            hv_vkv = float(self.net.bus.at[hb, "vn_kv"])
            lv_vkv = float(self.net.bus.at[lb, "vn_kv"])
            if hv_vkv >= 100:
                ttype = "HV/MV"
            else:
                ttype = "MV/LV"
            features.append({
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": list(lv_coords),
                },
                "properties": {
                    "type": "transformer",
                    "trafo_type": ttype,
                    "trafo_idx": int(tidx),
                    "hv_bus": hb,
                    "lv_bus": lb,
                    "name": str(tdata.get("name", "")),
                    "color": "#9b59b6",
                },
            })

        # --- Station / wallbox connections (road-following paths) ---
        for sid, sdata in self.station_to_bus.items():
            bidx = sdata["bus_idx"]
            sc = sdata["coords"]
            if bidx not in self.bus_to_coords:
                continue
            bc = self.bus_to_coords[bidx]
            dist = haversine(sc[0], sc[1], bc[0], bc[1])
            if dist > 1500:
                continue  # skip unreasonably long connections

            # Use precomputed road-following path if available
            conn_path = self.station_connection_paths.get(str(sid))
            if not conn_path:
                conn_path = self.station_connection_paths.get(sid)
            if not conn_path:
                conn_path = [list(sc), list(bc)]  # fallback: straight line

            features.append({
                "type": "Feature",
                "geometry": {
                    "type": "LineString",
                    "coordinates": conn_path,
                },
                "properties": {
                    "type": "station_connection",
                    "station_id": str(sid),
                    "bus_idx": int(bidx),
                    "station_type": sdata.get("type", "unknown"),
                    "power_kw": float(sdata.get("power_kw", 0)),
                    "distance_m": round(dist, 1),
                    "color": "#2ecc71" if sdata.get("type") == "wallbox" else "#27ae60",
                },
            })

        # Metadata
        props = {
            "total_buses": len(self.net.bus),
            "hv_buses": self.stats["hv_buses"],
            "mv_buses": self.stats["mv_buses"],
            "lv_buses": self.stats["lv_buses"],
            "total_lines": len(self.net.line),
            "total_transformers": len(self.net.trafo),
            "total_loads": len(self.net.load),
            "total_stations_connected": len(self.station_to_bus),
            "area_km2": round(self.stats.get("area_km2", 0), 2),
        }

        return {"type": "FeatureCollection", "features": features, "properties": props}

    # -----------------------------------------------------------------
    # Persistence
    # -----------------------------------------------------------------

    def save(self, filepath):
        os.makedirs(os.path.dirname(filepath) or ".", exist_ok=True)
        data = {
            "net": self.net,
            "station_to_bus": self.station_to_bus,
            "bus_to_coords": self.bus_to_coords,
            "stats": self.stats,
            "line_paths": self.line_paths,
            "bus_paths": self.bus_paths,
            "station_connection_paths": self.station_connection_paths,
        }
        with open(filepath, "wb") as f:
            pickle.dump(data, f)
        print(f"[INFO] Power grid saved to {filepath}")

    @staticmethod
    def load(filepath):
        with open(filepath, "rb") as f:
            data = pickle.load(f)
        mgr = PowerGridManager()
        mgr.net = data["net"]
        mgr.station_to_bus = data["station_to_bus"]
        mgr.bus_to_coords = data["bus_to_coords"]
        mgr.stats = data["stats"]
        mgr.line_paths = data.get("line_paths", {})
        mgr.bus_paths = data.get("bus_paths", {})
        mgr.station_connection_paths = data.get("station_connection_paths", {})
        print(f"[INFO] Power grid loaded from {filepath}")
        return mgr

    # ═════════════════════════════════════════════════════════════════
    # INTERNAL – OSM parsing
    # ═════════════════════════════════════════════════════════════════

    def _parse_osm(self):
        """Extract road network from the OSM XML."""
        tree = ET.parse(self.osm_file)
        root = tree.getroot()

        # --- Collect all nodes ---
        for n in root.findall("node"):
            nid = n.get("id")
            lat = float(n.get("lat"))
            lon = float(n.get("lon"))
            self._osm_nodes[nid] = (lon, lat)

        # --- Parse road ways ---
        target_hwy = self.MV_HIGHWAYS | self.LV_HIGHWAYS

        for w in root.findall("way"):
            tags = {t.get("k"): t.get("v") for t in w.findall("tag")}
            hwy = tags.get("highway")
            if hwy not in target_hwy:
                continue
            if tags.get("power"):          # skip power infrastructure ways
                continue

            wid = w.get("id")
            nd_refs = [nd.get("ref") for nd in w.findall("nd")]

            # Track node → way for intersection detection
            for ref in nd_refs:
                self._node_to_ways[ref].add(wid)

            # Build adjacency + segment list
            for i in range(len(nd_refs) - 1):
                na, nb = nd_refs[i], nd_refs[i + 1]
                if na in self._osm_nodes and nb in self._osm_nodes:
                    self._road_segments.append((na, nb, hwy))
                    self._adj[na].add(nb)
                    self._adj[nb].add(na)

        self.stats["total_osm_road_nodes"] = len(
            {n for seg in self._road_segments for n in (seg[0], seg[1])}
        )
        print(f"[INFO] Parsed {len(self._osm_nodes)} OSM nodes, "
              f"{len(self._road_segments)} road segments, "
              f"{self.stats['total_osm_road_nodes']} road nodes")

    # ═════════════════════════════════════════════════════════════════
    # INTERNAL – intersection detection
    # ═════════════════════════════════════════════════════════════════

    def _find_intersections(self):
        """Nodes referenced by ≥ 2 road ways  +  dead-ends (degree 1)."""
        # True intersections
        for nid, ways in self._node_to_ways.items():
            if len(ways) >= 2 and nid in self._osm_nodes:
                self._intersection_nodes.add(nid)

        # Dead-ends (for coverage at cul-de-sacs)
        degree = defaultdict(int)
        for na, nb, _ in self._road_segments:
            degree[na] += 1
            degree[nb] += 1
        for nid, deg in degree.items():
            if deg == 1 and nid in self._osm_nodes:
                self._intersection_nodes.add(nid)

        self.stats["total_intersections"] = len(self._intersection_nodes)
        print(f"[INFO] Found {len(self._intersection_nodes)} road intersections / endpoints")

    # ═════════════════════════════════════════════════════════════════
    # INTERNAL – spatial sampling
    # ═════════════════════════════════════════════════════════════════

    def _sample_bus_locations(self):
        """Pick one representative intersection per spatial-grid cell."""
        if not self._intersection_nodes:
            print("[WARNING] No intersections found – grid will be empty")
            return

        lons = [self._osm_nodes[n][0] for n in self._intersection_nodes]
        lats = [self._osm_nodes[n][1] for n in self._intersection_nodes]
        min_lon, max_lon = min(lons), max(lons)
        min_lat, max_lat = min(lats), max(lats)

        width_m = haversine(min_lon, min_lat, max_lon, min_lat)
        height_m = haversine(min_lon, min_lat, min_lon, max_lat)
        self.stats["area_km2"] = (width_m * height_m) / 1e6

        # Convert cell size → degrees
        mid_lat = (min_lat + max_lat) / 2
        deg_per_m_lon = 1.0 / (111_320 * cos(radians(mid_lat)))
        deg_per_m_lat = 1.0 / 110_540
        cell_lon = self.GRID_CELL_M * deg_per_m_lon
        cell_lat = self.GRID_CELL_M * deg_per_m_lat

        # Bucket intersections into grid cells
        cells = defaultdict(list)
        for nid in self._intersection_nodes:
            lon, lat = self._osm_nodes[nid]
            ci = int((lon - min_lon) / cell_lon) if cell_lon > 0 else 0
            cj = int((lat - min_lat) / cell_lat) if cell_lat > 0 else 0
            cells[(ci, cj)].append(nid)

        # Pick the most-connected node per cell
        for (ci, cj), nodes in cells.items():
            best = max(nodes, key=lambda n: len(self._node_to_ways.get(n, set())))
            lon, lat = self._osm_nodes[best]

            # Classify voltage by road type of adjacent segments
            is_mv = False
            for nbr in self._adj.get(best, set()):
                for na, nb, hwy in self._road_segments:
                    if (na == best and nb == nbr) or (nb == best and na == nbr):
                        if hwy in self.MV_HIGHWAYS:
                            is_mv = True
                            break
                if is_mv:
                    break

            self._selected_nodes[best] = {
                "lon": lon,
                "lat": lat,
                "voltage_kv": 20.0 if is_mv else 0.4,
                "bus_idx": None,
            }

        # Ensure at least some MV buses exist (promote highest-connectivity if needed)
        mv_count = sum(1 for d in self._selected_nodes.values() if d["voltage_kv"] >= 10)
        if mv_count == 0 and len(self._selected_nodes) > 0:
            ranked = sorted(
                self._selected_nodes.keys(),
                key=lambda n: len(self._node_to_ways.get(n, set())),
                reverse=True,
            )
            n_promote = max(1, len(ranked) // 10)
            for nid in ranked[:n_promote]:
                self._selected_nodes[nid]["voltage_kv"] = 20.0
            mv_count = n_promote
            print(f"[INFO] Promoted {n_promote} LV nodes → MV (no tertiary roads found)")

        lv_count = len(self._selected_nodes) - mv_count
        print(
            f"[INFO] Sampled {len(self._selected_nodes)} bus locations "
            f"({mv_count} MV, {lv_count} LV) from {len(cells)} grid cells "
            f"at {self.GRID_CELL_M}m resolution"
        )

    # ═════════════════════════════════════════════════════════════════
    # INTERNAL – pandapower bus creation
    # ═════════════════════════════════════════════════════════════════

    def _create_buses(self):
        for nid, info in self._selected_nodes.items():
            vkv = info["voltage_kv"]
            prefix = "MV" if vkv >= 10 else "LV"
            bidx = pp.create_bus(
                self.net,
                vn_kv=vkv,
                name=f"{prefix}_bus_{nid}",
                geodata=(info["lon"], info["lat"]),
            )
            info["bus_idx"] = bidx
            self.bus_to_coords[bidx] = (info["lon"], info["lat"])
            self._bus_to_node[bidx] = nid

            if vkv >= 10:
                self.stats["mv_buses"] += 1
            else:
                self.stats["lv_buses"] += 1

    # ═════════════════════════════════════════════════════════════════
    # INTERNAL – line creation (BFS along roads)
    # ═════════════════════════════════════════════════════════════════

    def _create_lines(self):
        """
        Create pandapower lines between adjacent *same-voltage* buses.

        Uses BFS from every bus node along the road adjacency graph; stops at
        other bus nodes.  Only connects buses of the same voltage level so that
        voltage-level bridging is handled exclusively by transformers.
        """
        bus_nodes = set(self._selected_nodes.keys())
        node_voltage = {n: d["voltage_kv"] for n, d in self._selected_nodes.items()}
        node_bus = {n: d["bus_idx"] for n, d in self._selected_nodes.items()}

        created_pairs = set()          # frozenset(nid_a, nid_b)
        max_m = self.MAX_LINE_SEARCH_M

        for start_nid in bus_nodes:
            start_v = node_voltage[start_nid]
            start_bus = node_bus[start_nid]

            visited = {start_nid}
            queue = deque()
            queue.append((start_nid, [start_nid], 0.0))

            while queue:
                cur, path, dist = queue.popleft()

                for nbr in self._adj.get(cur, set()):
                    if nbr in visited:
                        continue
                    if nbr not in self._osm_nodes or cur not in self._osm_nodes:
                        continue

                    seg_d = haversine(
                        self._osm_nodes[cur][0], self._osm_nodes[cur][1],
                        self._osm_nodes[nbr][0], self._osm_nodes[nbr][1],
                    )
                    new_dist = dist + seg_d
                    if new_dist > max_m:
                        continue

                    new_path = path + [nbr]
                    visited.add(nbr)

                    if nbr in bus_nodes:
                        # Reached another bus – create line if same voltage
                        nbr_v = node_voltage[nbr]
                        if abs(nbr_v - start_v) < 1.0:
                            pair = frozenset((start_nid, nbr))
                            if pair not in created_pairs:
                                created_pairs.add(pair)
                                length_km = max(0.01, new_dist / 1000)
                                if length_km <= self.MAX_LINE_LENGTH_KM:
                                    self._make_line(
                                        node_bus[start_nid],
                                        node_bus[nbr],
                                        length_km,
                                        max(start_v, nbr_v),
                                        new_path,
                                        f"line_{start_nid}_{nbr}",
                                    )
                        # Never explore past a bus node (any voltage)
                        continue

                    # Regular road node – keep exploring
                    queue.append((nbr, new_path, new_dist))

        print(f"[INFO] Created {self.stats['lines']} distribution lines")

    def _make_line(self, from_bus, to_bus, length_km, voltage_kv, path_nodes, name):
        """Helper: create a pandapower line + store its road-following path."""
        try:
            lidx = pp.create_line(
                self.net,
                from_bus=from_bus,
                to_bus=to_bus,
                length_km=length_km,
                std_type=_line_type(voltage_kv),
                name=name,
            )
            self.stats["lines"] += 1
            coords = [
                list(self._osm_nodes[n])
                for n in path_nodes
                if n in self._osm_nodes
            ]
            self.line_paths[int(lidx)] = coords
        except Exception:
            pass  # pandapower may reject duplicate or degenerate lines

    # ═════════════════════════════════════════════════════════════════
    # INTERNAL – transformer creation
    # ═════════════════════════════════════════════════════════════════

    def _create_transformers(self):
        """Connect each LV bus to the nearest MV bus via a 20/0.4 kV transformer."""
        mv_buses = [
            b for b in self.bus_to_coords
            if 10 <= self.net.bus.at[b, "vn_kv"] < 100
        ]
        lv_buses = [
            b for b in self.bus_to_coords
            if self.net.bus.at[b, "vn_kv"] < 10
        ]

        if not mv_buses:
            print("[WARNING] No MV buses – transformers will be created in HV step")
            return

        connected = 0
        for lv in lv_buses:
            lv_c = self.bus_to_coords[lv]
            best_mv, best_d = None, float("inf")
            for mv in mv_buses:
                mv_c = self.bus_to_coords[mv]
                d = haversine(lv_c[0], lv_c[1], mv_c[0], mv_c[1])
                if d < best_d:
                    best_d = d
                    best_mv = mv

            if best_mv is not None and best_d < 2000:
                try:
                    pp.create_transformer(
                        self.net,
                        hv_bus=best_mv,
                        lv_bus=lv,
                        std_type="0.4 MVA 20/0.4 kV",
                        name=f"trafo_MV{best_mv}_LV{lv}",
                    )
                    self.stats["transformers"] += 1
                    connected += 1
                except Exception:
                    pass

        print(
            f"[INFO] Created {self.stats['transformers']} MV/LV transformers "
            f"({connected}/{len(lv_buses)} LV buses connected)"
        )

    # ═════════════════════════════════════════════════════════════════
    # INTERNAL – HV slack bus
    # ═════════════════════════════════════════════════════════════════

    def _add_hv_connection(self):
        """Add a 110 kV slack bus and connect it to the MV ring."""
        if not self.bus_to_coords:
            return

        avg_lon = float(np.mean([c[0] for c in self.bus_to_coords.values()]))
        avg_lat = float(np.mean([c[1] for c in self.bus_to_coords.values()]))

        hv_bus = pp.create_bus(
            self.net, vn_kv=110.0, name="HV_slack",
            geodata=(avg_lon, avg_lat),
        )
        self.bus_to_coords[hv_bus] = (avg_lon, avg_lat)
        self.stats["hv_buses"] = 1

        pp.create_ext_grid(self.net, bus=hv_bus, vm_pu=1.0, name="external_grid")
        self.stats["slack_bus"] = int(hv_bus)

        # Connect HV to the most-central MV buses
        mv_buses = [
            b for b in self.bus_to_coords
            if 10 <= self.net.bus.at[b, "vn_kv"] < 100
        ]

        if mv_buses:
            mv_buses.sort(key=lambda b: haversine(
                self.bus_to_coords[b][0], self.bus_to_coords[b][1],
                avg_lon, avg_lat,
            ))
            for mv in mv_buses[:min(3, len(mv_buses))]:
                try:
                    pp.create_transformer(
                        self.net,
                        hv_bus=hv_bus,
                        lv_bus=mv,
                        std_type="25 MVA 110/20 kV",
                        name=f"HV_MV_trafo_{mv}",
                    )
                    self.stats["transformers"] += 1
                except Exception:
                    pass
        else:
            # No MV buses at all – create one + bridge to first few LV buses
            mv_bus = pp.create_bus(
                self.net, vn_kv=20.0, name="MV_central",
                geodata=(avg_lon, avg_lat),
            )
            self.bus_to_coords[mv_bus] = (avg_lon, avg_lat)
            self.stats["mv_buses"] += 1

            pp.create_transformer(
                self.net, hv_bus=hv_bus, lv_bus=mv_bus,
                std_type="25 MVA 110/20 kV", name="HV_MV_trafo_central",
            )
            self.stats["transformers"] += 1

            lv_buses = [
                b for b in self.bus_to_coords
                if self.net.bus.at[b, "vn_kv"] < 10
            ]
            for lv in lv_buses[:10]:
                try:
                    pp.create_transformer(
                        self.net, hv_bus=mv_bus, lv_bus=lv,
                        std_type="0.4 MVA 20/0.4 kV",
                        name=f"emergency_trafo_MV_LV{lv}",
                    )
                    self.stats["transformers"] += 1
                except Exception:
                    pass

        print(f"[INFO] HV slack bus at ({avg_lon:.5f}, {avg_lat:.5f})")

    # ═════════════════════════════════════════════════════════════════
    # INTERNAL – connectivity validation
    # ═════════════════════════════════════════════════════════════════

    def _validate_network(self):
        """Ensure full connectivity – merge isolated components."""
        import networkx as nx

        def _build_graph():
            G = nx.Graph()
            for _, row in self.net.line.iterrows():
                G.add_edge(int(row.from_bus), int(row.to_bus))
            for _, row in self.net.trafo.iterrows():
                G.add_edge(int(row.hv_bus), int(row.lv_bus))
            return G

        # Step 1: connect truly isolated buses (no line/trafo at all)
        G = _build_graph()
        graph_buses = set(G.nodes())
        isolated = set(self.net.bus.index) - graph_buses
        slack = self.stats["slack_bus"]

        for iso in isolated:
            if iso == slack:
                continue
            nearest = self._find_nearest_bus(
                self.bus_to_coords[iso][0],
                self.bus_to_coords[iso][1],
                max_m=5000,
                exclude={iso},
            )
            if nearest is None:
                continue
            self._connect_two_buses(iso, nearest)

        # Step 2: merge disconnected components into the main (slack) component
        G = _build_graph()
        if len(G) == 0:
            return

        components = list(nx.connected_components(G))
        if len(components) <= 1:
            print(f"[INFO] Network fully connected: {len(self.net.bus)} buses")
            return

        main = next((c for c in components if slack in c), components[0])

        for comp in components:
            if comp is main:
                continue
            # Pick the component bus closest to any main bus
            best_pair, best_d = (None, None), float("inf")
            for cb in comp:
                if cb not in self.bus_to_coords:
                    continue
                for mb in main:
                    if mb not in self.bus_to_coords:
                        continue
                    d = haversine(
                        *self.bus_to_coords[cb], *self.bus_to_coords[mb]
                    )
                    if d < best_d:
                        best_d = d
                        best_pair = (cb, mb)

            if best_pair[0] is not None:
                self._connect_two_buses(best_pair[0], best_pair[1])
                main = main | comp  # merge for subsequent iterations

        G = _build_graph()
        final = list(nx.connected_components(G))
        print(
            f"[INFO] Network validation: {len(final)} component(s), "
            f"{len(self.net.bus)} buses, {len(self.net.line)} lines, "
            f"{len(self.net.trafo)} transformers"
        )

    def _connect_two_buses(self, bus_a, bus_b):
        """Create a line or transformer to connect two buses."""
        va = float(self.net.bus.at[bus_a, "vn_kv"])
        vb = float(self.net.bus.at[bus_b, "vn_kv"])
        ca = self.bus_to_coords.get(bus_a)
        cb = self.bus_to_coords.get(bus_b)
        if ca is None or cb is None:
            return
        dist_km = max(0.01, haversine(ca[0], ca[1], cb[0], cb[1]) / 1000)

        if abs(va - vb) < 1.0:
            # Same voltage → line
            try:
                road_path = self._find_road_path_between_buses(bus_a, bus_b)
                lidx = pp.create_line(
                    self.net, from_bus=bus_a, to_bus=bus_b,
                    length_km=dist_km,
                    std_type=_line_type(max(va, vb)),
                    name=f"fix_{bus_a}_{bus_b}",
                )
                if road_path:
                    self.line_paths[int(lidx)] = road_path
            except Exception:
                pass
        else:
            # Different voltage → transformer
            hv, lv = (bus_a, bus_b) if va > vb else (bus_b, bus_a)
            try:
                pp.create_transformer(
                    self.net, hv_bus=hv, lv_bus=lv,
                    std_type=_trafo_type(
                        float(self.net.bus.at[hv, "vn_kv"]),
                        float(self.net.bus.at[lv, "vn_kv"]),
                    ),
                    name=f"fix_trafo_{hv}_{lv}",
                )
            except Exception:
                pass

    # ═════════════════════════════════════════════════════════════════
    # INTERNAL – road-following path helpers
    # ═════════════════════════════════════════════════════════════════

    def _find_nearest_osm_road_node(self, lon, lat, max_m=500):
        """Find the nearest OSM node that is part of the road network."""
        best, best_d = None, float("inf")
        for nid in self._adj:               # only nodes with road adjacency
            if nid not in self._osm_nodes:
                continue
            nlon, nlat = self._osm_nodes[nid]
            d = haversine(lon, lat, nlon, nlat)
            if d < best_d and d <= max_m:
                best_d = d
                best = nid
        return best

    def _find_road_path_between_buses(self, bus_a, bus_b):
        """BFS along the road network from bus_a's OSM node to bus_b's."""
        node_a = self._bus_to_node.get(bus_a)
        node_b = self._bus_to_node.get(bus_b)
        if not node_a or not node_b or not self._adj:
            return None
        return self._bfs_road_path(node_a, node_b, max_m=5000)

    def _find_road_path_to_bus(self, lon, lat, bus_idx):
        """Find a road-following path from (lon, lat) to the given bus's node."""
        bus_node = self._bus_to_node.get(bus_idx)
        if bus_node is None or not self._adj:
            return None
        start_node = self._find_nearest_osm_road_node(lon, lat, max_m=500)
        if start_node is None:
            return None
        osm_path = self._bfs_road_path(start_node, bus_node, max_m=3000)
        if osm_path is None:
            return None
        # Prepend the actual station location
        return [[lon, lat]] + osm_path

    def _bfs_road_path(self, start_node, target_node, max_m=3000):
        """BFS along road adjacency from start_node to target_node.
        Returns list of [lon, lat] coordinates or None."""
        if start_node == target_node:
            c = self._osm_nodes.get(start_node)
            return [list(c)] if c else None

        visited = {start_node}
        queue = deque([(start_node, [start_node], 0.0)])

        while queue:
            cur, path, dist = queue.popleft()

            for nbr in self._adj.get(cur, set()):
                if nbr in visited:
                    continue
                if nbr not in self._osm_nodes or cur not in self._osm_nodes:
                    continue
                seg_d = haversine(
                    self._osm_nodes[cur][0], self._osm_nodes[cur][1],
                    self._osm_nodes[nbr][0], self._osm_nodes[nbr][1],
                )
                new_dist = dist + seg_d
                if new_dist > max_m:
                    continue
                visited.add(nbr)
                new_path = path + [nbr]

                if nbr == target_node:
                    return [
                        list(self._osm_nodes[n])
                        for n in new_path
                        if n in self._osm_nodes
                    ]
                queue.append((nbr, new_path, new_dist))

        return None  # no path found

    # ═════════════════════════════════════════════════════════════════
    # INTERNAL – station attachment
    # ═════════════════════════════════════════════════════════════════

    def _attach_station(self, station):
        """Create a controllable load for one charging station / wallbox."""
        sid = station["id"]
        lon, lat = float(station["lon"]), float(station["lat"])
        pkw = station.get("power_kw", 200.0)

        # Prefer LV bus
        bus = self._find_nearest_bus(lon, lat, voltage_target=0.4, max_m=2000)
        if bus is None:
            bus = self._find_nearest_bus(lon, lat, max_m=5000)
        if bus is None and self.bus_to_coords:
            bus = min(
                self.bus_to_coords,
                key=lambda b: haversine(
                    lon, lat, self.bus_to_coords[b][0], self.bus_to_coords[b][1]
                ),
            )
        if bus is None:
            return

        load_idx = pp.create_load(
            self.net,
            bus=bus,
            p_mw=0.0,
            q_mvar=0.0,
            name=f"station_{sid}",
            controllable=True,
        )

        # Try to find a road-following path from station to its bus
        road_path = self._find_road_path_to_bus(lon, lat, bus)
        if road_path:
            self.station_connection_paths[sid] = road_path

        self.station_to_bus[sid] = {
            "bus_idx": bus,
            "load_idx": load_idx,
            "coords": (lon, lat),
            "power_kw": pkw,
            "type": station.get("type", "public"),
        }
        self.stats["loads"] += 1

    def _find_nearest_bus(self, lon, lat, voltage_target=None, max_m=2000, exclude=None):
        """Find nearest bus (optionally at a target voltage)."""
        best, best_d = None, float("inf")
        for bidx, coords in self.bus_to_coords.items():
            if exclude and bidx in exclude:
                continue
            if voltage_target is not None:
                v = float(self.net.bus.at[bidx, "vn_kv"])
                if abs(v - voltage_target) > 10:
                    continue
            d = haversine(lon, lat, coords[0], coords[1])
            if d < best_d and d <= max_m:
                best_d = d
                best = bidx
        return best

    # ═════════════════════════════════════════════════════════════════
    # Fallback
    # ═════════════════════════════════════════════════════════════════

    def _create_fallback_grid(self):
        """Minimal 3-bus grid when no OSM data is available."""
        hv = pp.create_bus(self.net, vn_kv=110.0, name="HV_bus", geodata=(13.4, 52.52))
        mv = pp.create_bus(self.net, vn_kv=20.0, name="MV_bus", geodata=(13.4, 52.52))
        lv = pp.create_bus(self.net, vn_kv=0.4, name="LV_bus", geodata=(13.4, 52.52))
        self.bus_to_coords = {
            hv: (13.4, 52.52), mv: (13.4, 52.52), lv: (13.4, 52.52)
        }
        pp.create_ext_grid(self.net, bus=hv, vm_pu=1.0)
        pp.create_transformer(self.net, hv_bus=hv, lv_bus=mv, std_type="25 MVA 110/20 kV")
        pp.create_transformer(self.net, hv_bus=mv, lv_bus=lv, std_type="0.4 MVA 20/0.4 kV")
        self.stats.update({
            "hv_buses": 1, "mv_buses": 1, "lv_buses": 1,
            "transformers": 2, "slack_bus": int(hv),
        })
        self._print_stats()
        return True

    # ═════════════════════════════════════════════════════════════════
    # Stats reporting
    # ═════════════════════════════════════════════════════════════════

    def _print_stats(self):
        print("\n" + "=" * 60)
        print("POWER GRID CONSTRUCTION SUMMARY")
        print("=" * 60)
        print(f"  Area:               {self.stats.get('area_km2', 0):.2f} km²")
        print(f"  HV buses (110 kV):  {self.stats['hv_buses']}")
        print(f"  MV buses (20 kV):   {self.stats['mv_buses']}")
        print(f"  LV buses (0.4 kV):  {self.stats['lv_buses']}")
        print(f"  Total buses:        {len(self.net.bus)}")
        print(f"  Lines:              {len(self.net.line)}")
        print(f"  Transformers:       {len(self.net.trafo)}")
        print(f"  Slack bus:          {self.stats['slack_bus']}")
        print("=" * 60 + "\n")


# ───────────────────────────────────────────────────────────────────
# Quick self-test
# ───────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    osm = sys.argv[1] if len(sys.argv) > 1 else None
    mgr = PowerGridManager(osm_file=osm)
    ok = mgr.build_grid()
    if ok:
        # Quick power-flow test
        try:
            pp.runpp(mgr.net)
            print(f"[OK] Power flow converged – "
                  f"grid draws {mgr.net.res_ext_grid.p_mw.sum():.3f} MW")
        except Exception as e:
            print(f"[FAIL] Power flow: {e}")
