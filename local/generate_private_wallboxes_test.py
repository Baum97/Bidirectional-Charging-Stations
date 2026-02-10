"""
Generate private wallboxes for residential POIs - FAST TEST VERSION.

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


def generate_trips_with_private_wallboxes_test(netfile, input_csvs, output_dir, sim_params=None):
    """
    Generate trips with unique vehicle types per person for private wallbox access.
    FAST TEST VERSION: 100 cars, 10 hour simulation.

    Args:
        netfile (str): Path to the SUMO network file.
        input_csvs (list): List of input CSV files containing POI edges.
        output_dir (str): Directory to save the generated trips XML file.
        sim_params (dict, optional): Scenario parameters from the UI.

    Returns:
        tuple: (trips_file_path, persons_data_dict)
            - trips_file_path: Path to the generated trips XML file
            - persons_data_dict: Dictionary with person data for wallbox generation
    """
    if sim_params is None:
        sim_params = {}
    # Configuration - FAST TEST VERSION (overridable via sim_params)
    num_persons = int(sim_params.get('num_persons', 100))  # 100 cars instead of 250
    morning_depart_interval = (0, 1800)  # 0-30 minutes
    work_duration = 3 * 3600  # 3 hours instead of 8
    home_evening_duration_range = (2 * 3600, 4 * 3600)  # 2-4 hours instead of 6-14
    ev_share = float(sim_params.get('ev_share', 0.6))  # 60% EVs
    num_evs = int(num_persons * ev_share)
    battery_capacity = str(int(sim_params.get('battery_capacity', 80000)))
    battery_actual = str(int(sim_params.get('battery_actual', 40000)))
    stationfinder_radius = str(int(sim_params.get('stationfinder_radius', 3000)))

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

    # Dictionary to store person data for wallbox generation
    persons_data = {}

    # Create vehicles
    vehicles = []
    for p in persons:
        depart_morning = round(random.uniform(*morning_depart_interval), 2)
        home_evening_duration = round(random.uniform(*home_evening_duration_range), 2)
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
                mass="183000"
            )
            
            # Battery configuration
            ET.SubElement(vtype_ev, 'param', key="has.battery.device", value="true")
            ET.SubElement(vtype_ev, 'param', key="device.battery.capacity", value=battery_capacity)
            ET.SubElement(vtype_ev, 'param', key="device.battery.actualBatteryCapacity", value=battery_actual)
            # Rerouting configuration
            ET.SubElement(vtype_ev, 'param', key="has.rerouting.device", value="true")
            ET.SubElement(vtype_ev, 'param', key="device.rerouting.probability", value="1")
            # Station finder configuration
            ET.SubElement(vtype_ev, 'param', key="has.stationfinder.device", value="true")
            ET.SubElement(vtype_ev, 'param', key="device.stationfinder.rescueTime", value="1800")
            ET.SubElement(vtype_ev, 'param', key="device.stationfinder.reserveFactor", value="1.2")
            ET.SubElement(vtype_ev, 'param', key="device.stationfinder.radius", value=stationfinder_radius)
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
            
            # Store person data for wallbox generation
            persons_data[person_id] = {
                'home_edge': p['home'],
                'work_edge': p['work'],
                'vehicle_type': veh_type
            }
        else:
            veh_type = "veh_passenger"

        vehicles.append({
            'id': person_id,
            'type': veh_type,
            'depart': depart_morning,
            'route': [p['home'], p['work'], p['home']],
            'stops': [
                {'edge': p['work'], 'duration': work_duration},
                {'edge': p['home'], 'duration': home_evening_duration}
            ]
        })

    vehicles.sort(key=lambda v: v['depart'])

    # Add vehicle definitions to XML
    for v in vehicles:
        veh_elem = ET.SubElement(
            routes, 'vehicle',
            id=v['id'],
            type=v['type'],
            depart=str(v['depart'])
        )
        ET.SubElement(veh_elem, 'route', edges=" ".join(v['route']))
        
        # Add stops (work + home)
        for stop in v['stops']:
            ET.SubElement(
                veh_elem, 'stop',
                edge=stop['edge'],
                duration=str(stop['duration']),
                parking="true"
            )

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
    print(f"[TEST] Schnell-Testlauf mit Wallboxen erstellt: {num_persons} Fahrzeuge ({num_evs} EVs mit Wallboxen) in '{output_xml}'")

    return output_xml, persons_data


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 4:
        print("Usage: python generate_private_wallboxes_test.py <netfile> <input_csv> <output_dir> [input_csv2 ...]")
        sys.exit(1)

    netfile = sys.argv[1]
    input_csvs = sys.argv[2:-1]
    output_dir = sys.argv[-1]

    generate_trips_with_private_wallboxes_test(netfile, input_csvs, output_dir)
