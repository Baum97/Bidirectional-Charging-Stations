"""
Generate private wallboxes for residential POIs in SUMO.

Each person with an EV gets:
1. A unique vehicle type (vehicleTypePersonX)
2. A private wallbox at their home location (wallboxPersonX)
3. The wallbox is restricted to only accept that person's vehicle type
"""

import sumolib
import csv
import random
import xml.etree.ElementTree as ET
import os


def generate_trips_with_private_wallboxes(netfile, input_csvs, output_dir):
    """
    Generate trips with unique vehicle types per person for private wallbox access.

    Args:
        netfile (str): Path to the SUMO network file.
        input_csvs (list): List of input CSV files containing POI edges.
        output_dir (str): Directory to save the generated trips XML file.

    Returns:
        tuple: (trips_file_path, persons_data_dict)
            - trips_file_path: Path to the generated trips XML file
            - persons_data_dict: Dictionary with person data for wallbox generation
    """
    # Configuration
    num_persons = 250
    morning_depart_interval = (23400, 32400)  # 6:30 - 9:00
    work_duration = 8 * 3600  # 8 hrs in sec
    ev_share = 0.6  # part of electrical cars
    num_evs = int(num_persons * ev_share)

    # Load network and define edges
    def edge_allows_passenger(edge):
        for lane in edge.getLanes():
            allowed = getattr(lane, '_allowed', [])
            if 'passenger' in allowed or 'private' in allowed:
                return True
        return False

    net = sumolib.net.readNet(netfile)
    car_edges = set(e.getID() for e in net.getEdges() if edge_allows_passenger(e))

    # Filter POI-Edges
    edges = set()
    for input_csv in input_csvs:
        with open(input_csv, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                edge_id = row['edge_id']
                if edge_id and edge_id in car_edges:
                    edges.add(edge_id)
    edges = list(edges)

    if len(edges) < 2:
        raise ValueError("Need at least two different drivable edges!")

    # Every person gets fixed home/work edge
    persons = []
    for i in range(1, num_persons + 1):
        home, work = random.sample(edges, 2)
        persons.append({'id': f'person{i}', 'home': home, 'work': work})

    # Randomly select which persons have EVs
    random.seed(42)
    all_ids = [p['id'] for p in persons]
    ev_ids = set(random.sample(all_ids, num_evs))

    # Create XML structure
    routes = ET.Element('routes')
    
    # Standard passenger vehicle type (non-EV)
    ET.SubElement(routes, 'vType', id="veh_passenger", vClass="passenger", color="0,0,255")

    # Create vehicles
    vehicles = []
    for p in persons:
        depart_morning = round(random.uniform(*morning_depart_interval), 2)
        person_id = p['id']
        
        if person_id in ev_ids:
            # Create UNIQUE vehicle type for this person
            veh_type = f"vehicleType_{person_id}"
            
            # Define unique vehicle type with battery configuration
            vtype_ev = ET.SubElement(
                routes, 'vType',
                id=veh_type,
                minGap="2.50",
                maxSpeed="29.06",
                color="white",
                accel="1.0",
                decel="1.0",
                sigma="0.0",
                emissionClass="Energy",
                mass="183000",
                vClass="passenger"
            )
            # Battery configuration
            ET.SubElement(vtype_ev, 'param', key="has.battery.device", value="true")
            ET.SubElement(vtype_ev, 'param', key="device.battery.capacity", value="80000")
            ET.SubElement(vtype_ev, 'param', key="device.battery.actualBatteryCapacity", value="40000")
            # Rerouting configuration
            ET.SubElement(vtype_ev, 'param', key="has.rerouting.device", value="true")
            ET.SubElement(vtype_ev, 'param', key="device.rerouting.probability", value="1")
            # Station finder configuration
            ET.SubElement(vtype_ev, 'param', key="has.stationfinder.device", value="true")
            ET.SubElement(vtype_ev, 'param', key="device.stationfinder.rescueTime", value="1800")
            ET.SubElement(vtype_ev, 'param', key="device.stationfinder.reserveFactor", value="1.2")
            ET.SubElement(vtype_ev, 'param', key="device.stationfinder.radius", value="3000")
            # Energy parameters
            ET.SubElement(vtype_ev, 'param', key="maximumPower", value="150000")
            ET.SubElement(vtype_ev, 'param', key="recuperationEfficiency", value="0.00")
            ET.SubElement(vtype_ev, 'param', key="stoppingThreshold", value="0.1")
            # Physics parameters
            ET.SubElement(vtype_ev, 'param', key="airDragCoefficient", value="0.35")
            ET.SubElement(vtype_ev, 'param', key="constantPowerIntake", value="500")
            ET.SubElement(vtype_ev, 'param', key="frontSurfaceArea", value="2.6")
            ET.SubElement(vtype_ev, 'param', key="rotatingMass", value="40")
            ET.SubElement(vtype_ev, 'param', key="propulsionEfficiency", value="0.95")
            ET.SubElement(vtype_ev, 'param', key="radialDragCoefficient", value="0.1")
            ET.SubElement(vtype_ev, 'param', key="rollDragCoefficient", value="0.01")
            
            p['vehicle_type'] = veh_type
            p['has_ev'] = True
        else:
            veh_type = "veh_passenger"
            p['has_ev'] = False
        
        vehicles.append({
            'id': person_id,
            'type': veh_type,
            'depart': depart_morning,
            'route': [p['home'], p['work'], p['home']],
            'stop_edge': p['work'],
            'stop_duration': work_duration
        })

    vehicles.sort(key=lambda v: v['depart'])

    # Generate vehicle elements
    for v in vehicles:
        veh_elem = ET.SubElement(
            routes, 'vehicle',
            id=v['id'],
            type=v['type'],
            depart=str(v['depart'])
        )
        ET.SubElement(veh_elem, 'route', edges=" ".join(v['route']))
        ET.SubElement(
            veh_elem, 'stop',
            edge=v['stop_edge'],
            duration=str(v['stop_duration']),
            parking="true"
        )

    # Pretty print XML
    def indent(elem, level=0):
        i = "\n" + level * "  "
        if len(elem):
            if not elem.text or not elem.text.strip():
                elem.text = i + "  "
            for child in elem:
                indent(child, level + 1)
            if not elem.tail or not elem.tail.strip():
                elem.tail = i
        else:
            if level and (not elem.tail or not elem.tail.strip()):
                elem.tail = i

    indent(routes)

    # Save to output directory
    os.makedirs(output_dir, exist_ok=True)
    output_xml = os.path.join(output_dir, "osm.passenger.trips.xml")
    tree = ET.ElementTree(routes)
    tree.write(output_xml, encoding='utf-8', xml_declaration=True)
    
    print(f"✓ Generated {num_persons} vehicles ({num_evs} EVs with unique vehicle types)")
    print(f"  Saved to: {output_xml}")

    return output_xml, persons


def generate_private_wallboxes(netfile, persons_data, output_dir, wallbox_share=0.5):
    """
    Generate private wallboxes at selected EV owner's home locations.
    Each wallbox is restricted to only accept its owner's vehicle type.

    Args:
        netfile (str): Path to the SUMO network file.
        persons_data (list): List of person dictionaries with home edges and vehicle types.
        output_dir (str): Directory to save the wallboxes XML file.
        wallbox_share (float): Fraction of EV owners that get private wallboxes (default 0.5 = 50%).

    Returns:
        tuple: (wallbox_file_path, wallbox_homes_geojson_path)
    """
    net = sumolib.net.readNet(netfile)
    
    root = ET.Element("additional")
    wallbox_count = 0
    
    # Collect all EV owners
    ev_owners = [p for p in persons_data if p.get('has_ev', False)]
    
    # Select random subset of EV owners to receive wallboxes
    import random
    random.seed(42)  # Use same seed for reproducibility
    num_wallboxes = int(len(ev_owners) * wallbox_share)
    wallbox_recipients = set(random.sample([p['id'] for p in ev_owners], num_wallboxes))
    
    print(f"[INFO] Creating wallboxes for {num_wallboxes} out of {len(ev_owners)} EV owners ({wallbox_share*100:.0f}%)")
    
    # Track homes with wallboxes for GeoJSON visualization
    wallbox_homes = []
    
    for person in persons_data:
        # Only create wallboxes for selected EV owners
        if not person.get('has_ev', False):
            continue
        
        # Check if this person is selected for a wallbox
        if person['id'] not in wallbox_recipients:
            person['has_wallbox'] = False
            continue
        
        person['has_wallbox'] = True
        
        person_id = person['id']
        home_edge_id = person['home']
        vehicle_type = person['vehicle_type']
        
        # Get the edge object
        try:
            edge = net.getEdge(home_edge_id)
        except:
            print(f"Warning: Edge {home_edge_id} not found for {person_id}")
            continue
        
        # Use the first lane of the home edge
        lanes = edge.getLanes()
        if not lanes:
            continue
        
        lane = lanes[0]
        lane_id = lane.getID()
        lane_length = lane.getLength()
        
        # Constants for wallbox placement
        WALLBOX_LENGTH = 5.0  # 5m charging area
        MIN_LANE_LENGTH = 6.0  # Skip very short lanes
        
        # Skip lanes that are too short to fit a wallbox
        if lane_length < MIN_LANE_LENGTH:
            print(f"[WARNING] Lane {lane_id} too short ({lane_length:.1f}m) for wallbox for {person_id}, skipping")
            continue
        
        # Calculate position: prefer end of lane, but ensure it fits within bounds
        if lane_length >= WALLBOX_LENGTH + 10:
            # Long enough: place near the end (10m from end)
            startPos = lane_length - 10 - WALLBOX_LENGTH
        else:
            # Short lane: place as far back as possible while fitting
            startPos = max(0.5, lane_length - WALLBOX_LENGTH - 0.5)  # 0.5m buffer
        
        endPos = min(startPos + WALLBOX_LENGTH, lane_length - 0.1)  # Stay 0.1m within bounds
        
        # Final validation
        if startPos < 0 or endPos > lane_length or startPos >= endPos:
            print(f"[WARNING] Invalid position for wallbox at {lane_id} for {person_id} (lane: {lane_length:.1f}m, start: {startPos:.1f}m, end: {endPos:.1f}m), skipping")
            continue
        
        # Create charging station ID
        wallbox_id = f"wallbox_{person_id}"
        
        # Create charging station restricted to this person's vehicle type
        ET.SubElement(
            root, "chargingStation",
            id=wallbox_id,
            lane=lane_id,
            startPos=str(round(startPos, 2)),
            endPos=str(round(endPos, 2)),
            power="11000",  # 11 kW (typical home wallbox power)
            efficiency="0.95",
            chargeInTransit="0",
            chargeDelay="0",  # Start charging immediately
            vehicleTypes=vehicle_type  # KEY: Restrict to only this vehicle type!
        )
        wallbox_count += 1
        
        # Store home location for visualization (get coordinates from lane)
        try:
            shape = lane.getShape()
            if shape:
                # Get the end point of the lane (near home) - these are in network coordinates (x, y)
                x, y = shape[-1]
                
                # Convert network coordinates to geographic coordinates (lon, lat)
                # SUMO network coordinates are typically in projected coordinates (meters)
                # We need to convert them to WGS84 lon/lat for Leaflet
                lon, lat = net.convertXY2LonLat(x, y)
                
                wallbox_homes.append({
                    "person_id": person_id,
                    "lat": lat,
                    "lon": lon,
                    "vehicle_type": vehicle_type,
                    "home_edge": home_edge_id
                })
        except Exception as e:
            print(f"[WARNING] Could not get coordinates for {person_id}: {e}")
    
    # Pretty print XML
    def indent(elem, level=0):
        i = "\n" + level * "  "
        if len(elem):
            if not elem.text or not elem.text.strip():
                elem.text = i + "  "
            for child in elem:
                indent(child, level + 1)
            if not elem.tail or not elem.tail.strip():
                elem.tail = i
        else:
            if level and (not elem.tail or not elem.tail.strip()):
                elem.tail = i
    
    indent(root)
    
    # Save wallboxes XML to output directory
    output_xml = os.path.join(output_dir, "private_wallboxes.xml")
    tree = ET.ElementTree(root)
    tree.write(output_xml, encoding='utf-8', xml_declaration=True)
    
    print(f"✓ Generated {wallbox_count} private wallboxes")
    print(f"  Saved to: {output_xml}")
    
    # Generate GeoJSON for wallbox home locations
    import json
    wallbox_homes_geojson = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [home["lon"], home["lat"]]
                },
                "properties": {
                    "person_id": home["person_id"],
                    "vehicle_type": home["vehicle_type"],
                    "home_edge": home["home_edge"],
                    "has_wallbox": True
                }
            }
            for home in wallbox_homes
        ]
    }
    
    wallbox_homes_file = os.path.join(output_dir, "wallbox_homes.geojson")
    with open(wallbox_homes_file, 'w', encoding='utf-8') as f:
        json.dump(wallbox_homes_geojson, f, indent=2)
    
    print(f"✓ Generated GeoJSON for {len(wallbox_homes)} homes with wallboxes")
    print(f"  Saved to: {wallbox_homes_file}")
    
    return output_xml, wallbox_homes_file


def generate_complete_scenario_with_wallboxes(netfile, input_csvs, output_dir):
    """
    Complete pipeline: Generate trips with unique vehicle types AND private wallboxes.
    
    Args:
        netfile (str): Path to the SUMO network file.
        input_csvs (list): List of POI edge CSV files.
        output_dir (str): Output directory for generated files.
        
    Returns:
        dict: Paths to generated files
    """
    print("\n=== Generating Trips with Unique Vehicle Types ===")
    trips_file, persons_data = generate_trips_with_private_wallboxes(netfile, input_csvs, output_dir)
    
    print("\n=== Generating Private Wallboxes ===")
    wallbox_file = generate_private_wallboxes(netfile, persons_data, output_dir)
    
    print("\n=== Summary ===")
    ev_count = sum(1 for p in persons_data if p.get('has_ev', False))
    print(f"Total persons: {len(persons_data)}")
    print(f"EV owners: {ev_count}")
    print(f"Private wallboxes: {ev_count}")
    print(f"\nEach EV owner has:")
    print(f"  - Unique vehicle type: vehicleType_personX")
    print(f"  - Private wallbox: wallbox_personX")
    print(f"  - Wallbox accepts ONLY their vehicle type")
    
    return {
        'trips_file': trips_file,
        'wallbox_file': wallbox_file,
        'persons_data': persons_data
    }


# Example usage
if __name__ == "__main__":
    # Example paths - adjust to your scenario
    netfile = "../data/scenarios/scenario_20260206_234300/osm.net.xml.gz"
    input_csvs = [
        "../data/scenarios/scenario_20260206_234300/poi_residential_edges.csv",
        "../data/scenarios/scenario_20260206_234300/poi_offices_edges.csv",
    ]
    output_dir = "../data/scenarios/scenario_20260206_234300"
    
    result = generate_complete_scenario_with_wallboxes(netfile, input_csvs, output_dir)
    
    print("\n✓ Done! To use in SUMO, add both files to your sumocfg:")
    print(f"  <route-files value=\"{os.path.basename(result['trips_file'])}\"/>")
    print(f"  <additional-files value=\"{os.path.basename(result['wallbox_file'])}\"/>")
