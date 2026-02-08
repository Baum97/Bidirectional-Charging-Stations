"""
Generate private wallboxes for residential POIs in SUMO.

Each person with an EV gets:
1. A unique vehicle type (vehicleTypePersonX)
2. A private wallbox at their home location (wallboxPersonX)
3. The wallbox is inside a parkingArea that only the owner is routed to

Enforcement strategy:
- Each wallbox is a <chargingStation> nested INSIDE a <parkingArea>
- The parkingArea has roadsideCapacity="1" (single private spot)
- Only the wallbox owner's trip includes a <stop parkingArea="parkingArea_personX">
- Other vehicles have NO stop referencing that parkingArea, so they never park/charge there
- This achieves access control through routing, not through attribute-based restrictions
"""

import sumolib
import csv
import random
import xml.etree.ElementTree as ET
import os


def _select_wallbox_recipients(persons, wallbox_share=0.5):
    """
    Decide which EV owners get a private wallbox.
    Must be called BEFORE trip generation so trips can include parkingArea stops.

    Args:
        persons (list): List of person dicts (must have 'has_ev' set).
        wallbox_share (float): Fraction of EV owners that get wallboxes.

    Returns:
        set: IDs of persons who receive a wallbox.
    """
    ev_owners = [p for p in persons if p.get('has_ev', False)]
    random.seed(42)
    num_wallboxes = int(len(ev_owners) * wallbox_share)
    recipients = set(random.sample([p['id'] for p in ev_owners], num_wallboxes))
    for p in persons:
        p['has_wallbox'] = p['id'] in recipients
    return recipients


def generate_trips_with_private_wallboxes(netfile, input_csvs, output_dir, wallbox_recipients=None):
    """
    Generate trips with unique vehicle types per person for private wallbox access.
    Wallbox owners get an additional <stop parkingArea="parkingArea_personX"> when
    they return home, so they park at their private wallbox and charge.

    Args:
        netfile (str): Path to the SUMO network file.
        input_csvs (list): List of input CSV files containing POI edges.
        output_dir (str): Directory to save the generated trips XML file.
        wallbox_recipients (set): Set of person IDs that have wallboxes.
            If None, no parkingArea stops are added.

    Returns:
        tuple: (trips_file_path, persons_data_dict)
            - trips_file_path: Path to the generated trips XML file
            - persons_data_dict: Dictionary with person data for wallbox generation
    """
    if wallbox_recipients is None:
        wallbox_recipients = set()

    # Configuration
    num_persons = 250
    morning_depart_interval = (23400, 32400)  # 6:30 - 9:00
    work_duration = 8 * 3600  # 8 hrs in sec
    home_duration = 10 * 3600  # 10 hrs parked at home (overnight)
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
        
        # Check if this person has a wallbox at home
        has_wallbox = person_id in wallbox_recipients
        p['has_wallbox'] = has_wallbox
        
        vehicles.append({
            'id': person_id,
            'type': veh_type,
            'depart': depart_morning,
            'route': [p['home'], p['work'], p['home']],
            'stop_edge': p['work'],
            'stop_duration': work_duration,
            'has_wallbox': has_wallbox,
            'home_duration': home_duration
        })

    vehicles.sort(key=lambda v: v['depart'])

    # Generate vehicle elements
    wallbox_stop_count = 0
    for v in vehicles:
        if v['has_wallbox']:
            # Wallbox owners: depart at time 0 and start parked at their wallbox.
            # They charge overnight until their actual departure time, then drive to work.
            veh_elem = ET.SubElement(
                routes, 'vehicle',
                id=v['id'],
                type=v['type'],
                depart="0"  # Exist from simulation start
            )
            ET.SubElement(veh_elem, 'route', edges=" ".join(v['route']))
            # Stop 0: parked at home wallbox from sim start until departure time (overnight charging)
            ET.SubElement(
                veh_elem, 'stop',
                parkingArea=f"parkingArea_{v['id']}",
                until=str(v['depart']),  # Stay parked and charging until morning departure
                parking="true"
            )
            # Stop 1: at work
            ET.SubElement(
                veh_elem, 'stop',
                edge=v['stop_edge'],
                duration=str(v['stop_duration']),
                parking="true"
            )
            # Stop 2: return home to wallbox (evening/overnight charging)
            ET.SubElement(
                veh_elem, 'stop',
                parkingArea=f"parkingArea_{v['id']}",
                duration=str(v['home_duration']),
                parking="true"
            )
            wallbox_stop_count += 1
        else:
            # Non-wallbox vehicles: depart at their scheduled time
            veh_elem = ET.SubElement(
                routes, 'vehicle',
                id=v['id'],
                type=v['type'],
                depart=str(v['depart'])
            )
            ET.SubElement(veh_elem, 'route', edges=" ".join(v['route']))
            # Stop 1: at work
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
    print(f"  {wallbox_stop_count} vehicles have explicit parkingArea stops at home wallbox")
    print(f"  Saved to: {output_xml}")

    return output_xml, persons


def generate_private_wallboxes(netfile, persons_data, output_dir):
    """
    Generate private wallboxes at EV owners' home locations.
    Each wallbox is a chargingStation nested inside a parkingArea.
    
    Access control is enforced through routing:
    - Only the owner's trip has a <stop parkingArea="parkingArea_personX">
    - The parkingArea has roadsideCapacity="1" (single private spot)
    - No other vehicle has a stop referencing this parkingArea
    - Therefore only the owner ever parks and charges there

    Args:
        netfile (str): Path to the SUMO network file.
        persons_data (list): List of person dicts (must have 'has_wallbox' already set).
        output_dir (str): Directory to save the wallboxes XML file.

    Returns:
        tuple: (wallbox_file_path, wallbox_homes_geojson_path)
    """
    net = sumolib.net.readNet(netfile)
    
    root = ET.Element("additional")
    wallbox_count = 0
    
    # Track homes with wallboxes for GeoJSON visualization
    wallbox_homes = []
    
    # Count for logging
    ev_count = sum(1 for p in persons_data if p.get('has_ev', False))
    wb_count = sum(1 for p in persons_data if p.get('has_wallbox', False))
    print(f"[INFO] Creating wallboxes for {wb_count} out of {ev_count} EV owners")
    
    for person in persons_data:
        # Only create wallboxes for persons marked as wallbox recipients
        if not person.get('has_wallbox', False):
            continue
        
        person_id = person['id']
        home_edge_id = person['home']
        vehicle_type = person.get('vehicle_type', '')
        
        if not vehicle_type:
            print(f"[WARNING] {person_id} has wallbox but no vehicle_type, skipping")
            continue
        
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
        
        # Create parking area ID and charging station ID
        parking_area_id = f"parkingArea_{person_id}"
        wallbox_id = f"wallbox_{person_id}"
        
        s_start = str(round(startPos, 2))
        s_end = str(round(endPos, 2))
        
        # Private parkingArea: restricted to this person's vehicle type via vehicleTypes.
        # Only vehicleType_personX can park here.
        # roadsideCapacity="1": single private spot.
        # The owner's trip also has <stop parkingArea="..."> to route them here.
        ET.SubElement(
            root, "parkingArea",
            id=parking_area_id,
            lane=lane_id,
            startPos=s_start,
            endPos=s_end,
            roadsideCapacity="1",
            onRoad="false",
            vehicleTypes=vehicle_type  # Only this vehicle type can access
        )
        
        # Charging station at the same location (top-level, not nested).
        # Also restricted to this person's vehicle type.
        # Public charging stations do NOT have vehicleTypes, so all EVs can use those.
        ET.SubElement(
            root, "chargingStation",
            id=wallbox_id,
            lane=lane_id,
            startPos=s_start,
            endPos=s_end,
            power="11000",
            efficiency="0.95",
            chargeInTransit="0",
            chargeDelay="0",
            vehicleTypes=vehicle_type  # Only this vehicle type can charge here
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


def generate_complete_scenario_with_wallboxes(netfile, input_csvs, output_dir, wallbox_share=0.5):
    """
    Complete pipeline: Generate trips with unique vehicle types AND private wallboxes.
    
    The wallbox recipient selection happens FIRST, so that:
    1. Trip generation can add <stop parkingArea="..."> for wallbox owners
    2. Wallbox generation creates matching parkingArea + chargingStation elements
    
    This ensures access control through routing: only the owner is routed to
    their private parkingArea, so no other vehicle parks or charges there.
    
    Args:
        netfile (str): Path to the SUMO network file.
        input_csvs (list): List of POI edge CSV files.
        output_dir (str): Output directory for generated files.
        wallbox_share (float): Fraction of EV owners that get wallboxes (default 0.5).
        
    Returns:
        dict: Paths to generated files
    """
    # --- Step 0: Build person list and select EV owners + wallbox recipients ---
    # We need to pre-compute who gets a wallbox BEFORE generating trips,
    # because trips need to include parkingArea stops for wallbox owners.
    
    num_persons = 250
    ev_share = 0.6
    num_evs = int(num_persons * ev_share)
    
    # Build temporary person list to select EVs and wallbox recipients
    temp_persons = [{'id': f'person{i}'} for i in range(1, num_persons + 1)]
    random.seed(42)
    all_ids = [p['id'] for p in temp_persons]
    ev_ids = set(random.sample(all_ids, num_evs))
    for p in temp_persons:
        p['has_ev'] = p['id'] in ev_ids
    
    # Select wallbox recipients (uses random.seed(42) internally)
    wallbox_recipients = _select_wallbox_recipients(temp_persons, wallbox_share)
    
    print(f"\n=== Pre-selected {len(wallbox_recipients)} wallbox recipients ===")
    
    # --- Step 1: Generate trips WITH parkingArea stops for wallbox owners ---
    print("\n=== Generating Trips with Unique Vehicle Types ===")
    trips_file, persons_data = generate_trips_with_private_wallboxes(
        netfile, input_csvs, output_dir, wallbox_recipients=wallbox_recipients
    )
    
    # --- Step 2: Generate wallbox XML (parkingArea containing chargingStation) ---
    print("\n=== Generating Private Wallboxes ===")
    wallbox_file = generate_private_wallboxes(netfile, persons_data, output_dir)
    
    # --- Summary ---
    print("\n=== Summary ===")
    ev_count = sum(1 for p in persons_data if p.get('has_ev', False))
    wb_count = sum(1 for p in persons_data if p.get('has_wallbox', False))
    print(f"Total persons: {len(persons_data)}")
    print(f"EV owners: {ev_count}")
    print(f"Private wallboxes: {wb_count} ({wallbox_share*100:.0f}% of EV owners)")
    print(f"\nAccess control mechanism:")
    print(f"  - Each wallbox is inside a parkingArea (roadsideCapacity=1)")
    print(f"  - Only the owner's trip has <stop parkingArea=\"parkingArea_personX\">")
    print(f"  - No other vehicle is routed to that parkingArea")
    print(f"  - Therefore only the owner can park and charge there")
    
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
