"""
Improved trip generation using realistic mobility patterns.

This module integrates the TripChainGenerator with SUMO trip generation,
based on the ev_mobility_model approach (MIT License, Jonas Schlund 2022).
"""

import sumolib
import csv
import random
import xml.etree.ElementTree as ET
import sys
import os

# Import the new mobility model
from trip_chain_generator import (
    TripChainGenerator,
    purpose_to_poi_type,
    convert_trip_chain_to_sumo_route
)
from mobility_variables import (
    Purpose, HomogeneousGroup, MobilityPattern, DayType, AgeGroup
)


def generate_trips(netfile, input_csvs, output_dir, sim_params=None):
    """
    Generate trips based on realistic mobility patterns and save them to an XML file.

    Args:
        netfile (str): Path to the SUMO network file.
        input_csvs (list): List of input CSV files containing POI edges.
        output_dir (str): Directory to save the generated trips XML file.
        sim_params (dict, optional): Scenario parameters from the UI.

    Returns:
        str: Path to the generated trips XML file.
    """
    if sim_params is None:
        sim_params = {}
    
    # Configuration (overridable via sim_params)
    num_persons = int(sim_params.get('num_persons', 250))
    ev_share = float(sim_params.get('ev_share', 0.6))
    num_evs = int(num_persons * ev_share)
    
    # Battery parameters
    battery_capacity = str(int(sim_params.get('battery_capacity', 80000)))
    battery_actual = str(int(sim_params.get('battery_actual', 40000)))
    stationfinder_radius = str(int(sim_params.get('stationfinder_radius', 3000)))
    
    # New mobility model parameters
    working_person_ratio = float(sim_params.get('working_person_ratio', 0.65))
    student_ratio = float(sim_params.get('student_ratio', 0.15))
    car_dependent_ratio = float(sim_params.get('car_dependent_ratio', 0.4))
    use_weekday_pattern = sim_params.get('use_weekday_pattern', True)
    random_seed = sim_params.get('random_seed', 42)
    
    print(f"🚗 Generating trips for {num_persons} persons ({num_evs} EVs)...")
    print(f"📊 Demographics: {working_person_ratio*100:.0f}% working, {student_ratio*100:.0f}% students")
    
    # Load network and define edges
    def edge_allows_passenger(edge):
        for lane in edge.getLanes():
            allowed = getattr(lane, '_allowed', [])
            if 'passenger' in allowed or 'private' in allowed:
                return True
        return False

    net = sumolib.net.readNet(netfile)
    car_edges = set(e.getID() for e in net.getEdges() if edge_allows_passenger(e))

    # Load POI edges by category
    poi_edges = {
        'residential': [],
        'offices': [],
        'others': []
    }
    
    for input_csv in input_csvs:
        # Determine category from filename
        if 'residential' in input_csv.lower():
            category = 'residential'
        elif 'offices' in input_csv.lower():
            category = 'offices'
        else:
            category = 'others'
        
        with open(input_csv, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                edge_id = row['edge_id']
                if edge_id and edge_id in car_edges:
                    poi_edges[category].append(edge_id)
    
    # Ensure we have enough edges
    all_edges = [e for edges in poi_edges.values() for e in edges]
    if len(all_edges) < 10:
        raise ValueError("Not enough POI edges! Need at least 10 different edges.")
    
    print(f"📍 Loaded POIs: {len(poi_edges['residential'])} residential, "
          f"{len(poi_edges['offices'])} offices, {len(poi_edges['others'])} others")
    
    # Initialize trip chain generator
    generator = TripChainGenerator(seed=random_seed)
    
    # Generate user profiles
    user_profiles = generator.generate_user_profiles(
        num_users=num_persons,
        working_person_ratio=working_person_ratio,
        student_ratio=student_ratio,
        car_dependent_ratio=car_dependent_ratio,
        young_ratio=0.35,
        middle_ratio=0.40
    )
    
    print(f"👥 Generated {len(user_profiles)} user profiles")
    
    # Assign home locations
    residential_edges = poi_edges['residential'] if poi_edges['residential'] else all_edges
    for profile in user_profiles:
        profile.home_edge = random.choice(residential_edges)
    
    # Generate trip chains
    day_type = DayType.WEEKDAY if use_weekday_pattern else DayType.WEEKEND
    trip_chains = generator.generate_all_chains(
        user_profiles,
        day_type=day_type,
        available_locations=None  # Will be assigned during conversion
    )
    
    # Print statistics
    stats = generator.get_statistics(trip_chains)
    print(f"\n📈 Trip Generation Statistics:")
    print(f"   Mobile users: {stats['mobile_users']} ({stats['mobile_users']/stats['total_users']*100:.1f}%)")
    print(f"   Total trips: {stats['total_trips']}")
    print(f"   Avg trips/user: {stats['avg_trips_per_user']}")
    print(f"   Avg distance/trip: {stats['avg_distance_per_trip_km']} km")
    print(f"   Purpose distribution:")
    for purpose, count in sorted(stats['purpose_distribution'].items()):
        pct = count / stats['total_trips'] * 100
        print(f"      {purpose}: {count} ({pct:.1f}%)")
    
    # Determine which users get EVs
    random.seed(random_seed)
    all_ids = [p.user_id for p in user_profiles]
    ev_ids = set(random.sample(all_ids, num_evs))
    
    # Create vehicle data for SUMO
    vehicles = []
    
    for profile in user_profiles:
        chain = trip_chains[profile.user_id]
        
        if chain.get_trip_count() == 0:
            # User stays home all day - skip or create minimal route
            continue
        
        # Convert trip chain to SUMO route
        sumo_route = convert_trip_chain_to_sumo_route(
            chain,
            profile.home_edge,
            poi_edges
        )
        
        # Determine vehicle type
        veh_type = "veh_ev" if profile.user_id in ev_ids else "veh_passenger"
        
        vehicles.append({
            'id': profile.user_id,
            'type': veh_type,
            'depart': sumo_route['depart'],
            'route': sumo_route['route'],
            'stops': sumo_route['stops']
        })
    
    # Sort by departure time
    vehicles.sort(key=lambda v: v['depart'])
    
    print(f"\n🚙 Created {len(vehicles)} vehicle routes ({sum(1 for v in vehicles if v['type'] == 'veh_ev')} EVs)")
    
    # Create XML structure
    routes = ET.Element('routes')
    
    # Add vehicle type definitions
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

    # Add vehicle routes
    for v in vehicles:
        veh_elem = ET.SubElement(
            routes, 'vehicle',
            id=v['id'],
            type=v['type'],
            depart=str(v['depart'])
        )
        
        # Add route
        ET.SubElement(veh_elem, 'route', edges=" ".join(v['route']))
        
        # Add stops
        for stop in v['stops']:
            ET.SubElement(
                veh_elem, 'stop',
                edge=stop['edge'],
                duration=str(stop['duration']),
                parking="true"
            )

    # Format XML with indentation
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
    
    print(f"\n✅ Generated trips saved to: {output_xml}")
    print(f"   Total vehicles: {len(vehicles)}")
    print(f"   Total stops: {sum(len(v['stops']) for v in vehicles)}")

    return output_xml


def generate_trips_simple(netfile, input_csvs, output_dir, sim_params=None):
    """
    Fallback to simple trip generation if the new model fails.
    This is the old implementation kept for compatibility.
    """
    # Import the old function
    import mainGenerateTrips_old
    return mainGenerateTrips_old.generate_trips(netfile, input_csvs, output_dir, sim_params)
