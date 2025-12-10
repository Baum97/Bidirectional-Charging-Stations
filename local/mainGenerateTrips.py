import sumolib
import csv
import random
import xml.etree.ElementTree as ET
import sys
import os

"""
1. Define User Groups and Trip Purposes
Add enums or dictionaries to represent user groups (e.g., working persons, students) and trip purposes (e.g., work, shopping, leisure).

2. Generate Trip Chains
Replace the simple home-work-home logic with a method to generate trip chains. Each chain can include multiple stops with varying purposes, durations, and distances.

3. Incorporate Stochastic Sampling
Use cumulative distributions to sample trip parameters like departure times, distances, and stay durations. This ensures variability and realism.

4. Enhance EV Modeling
Add logic for EV-specific constraints, such as charging stops and battery levels.

"""
from enum import Enum

def generate_trips(netfile, input_csvs, output_dir):
    """
    Generate trips based on POI edges and save them to an XML file.

    Args:
        netfile (str): Path to the SUMO network file.
        input_csvs (list): List of input CSV files containing POI edges.
        output_dir (str): Directory to save the generated trips XML file.

    Returns:
        str: Path to the generated trips XML file.
    """
    # Configuration
    num_persons = 250
    morning_depart_interval = (23400, 32400)  # 6:30 - 9:00
    work_duration = 8 * 3600  # 8 hrs in sec
    ev_share = 0.6  # part of electrical cars
    num_evs = int(num_persons * ev_share)

    # Define trip purposes
    class Purpose(Enum):
        WORK = "work"
        SHOPPING = "shopping"
        LEISURE = "leisure"
        HOME = "home"

    # Define user groups
    class UserGroup(Enum):
        WORKING_PERSON = "working_person"
        STUDENT = "student"
        NON_WORKING_PERSON = "non_working_person"

    # Define regional types
    class RegionType(Enum):
        URBAN = "urban"
        RURAL = "rural"

    # Define time categories
    class TimeOfDay(Enum):
        MORNING = "morning"
        MIDDAY = "midday"
        EVENING = "evening"

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
        raise ValueError("Es müssen mindestens zwei verschiedene befahrbare Edges vorhanden sein!")

    # Every person gets fixed home/work node
    persons = []
    for i in range(1, num_persons + 1):
        home, work = random.sample(edges, 2)
        persons.append({'id': f'person{i}', 'home': home, 'work': work})

    # Random ID of vehicle
    random.seed(42)
    all_ids = [p['id'] for p in persons]
    ev_ids = set(random.sample(all_ids, num_evs))

    # Function to generate trip chains
    def generate_trip_chain(user_group, region_type):
        trip_chain = []

        # Define probabilities for trip purposes based on user group
        if user_group == UserGroup.WORKING_PERSON:
            purposes = [Purpose.HOME, Purpose.WORK, Purpose.SHOPPING, Purpose.HOME]
        elif user_group == UserGroup.STUDENT:
            purposes = [Purpose.HOME, Purpose.WORK, Purpose.LEISURE, Purpose.HOME]
        else:
            purposes = [Purpose.HOME, Purpose.SHOPPING, Purpose.LEISURE, Purpose.HOME]

        # Generate trips with stochastic departure times
        for i, purpose in enumerate(purposes):
            if i == 0:
                depart_time = random.uniform(6 * 3600, 9 * 3600)  # Morning departure
            else:
                depart_time += random.uniform(1 * 3600, 3 * 3600)  # Add random interval

            trip_chain.append({
                'purpose': purpose.value,
                'depart_time': round(depart_time, 2),
                'region': region_type.value
            })

        return trip_chain

    # Define user groups and regions
    user_groups = [UserGroup.WORKING_PERSON, UserGroup.STUDENT, UserGroup.NON_WORKING_PERSON]
    region_types = [RegionType.URBAN, RegionType.RURAL]

    # Generate trips for each user
    all_trips = []
    for i in range(1, num_persons + 1):
        user_group = random.choice(user_groups)
        region_type = random.choice(region_types)
        trip_chain = generate_trip_chain(user_group, region_type)
        all_trips.append(trip_chain)

    # Use the generated trip chains to create vehicles
    vehicles = []
    for i, trip_chain in enumerate(all_trips):
        veh_type = "veh_ev" if i < num_evs else "veh_passenger"
        vehicles.append({
            'id': f'person{i + 1}',
            'type': veh_type,
            'trips': trip_chain
        })

    # Create XML structure
    routes = ET.Element('routes')
    ET.SubElement(routes, 'vType', id="veh_passenger", vClass="passenger", color="0,0,255")

    vtype_ev = ET.SubElement(
        routes, 'vType',
        id="veh_ev",
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
    print(f"Fertig! {num_persons} Fahrzeuge mit Tagesrhythmus und Arbeitsstopp wurden in '{output_xml}' gespeichert.")

    return output_xml
