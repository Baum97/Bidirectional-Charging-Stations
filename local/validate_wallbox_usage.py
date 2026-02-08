#!/usr/bin/env python3
"""
Validate that private wallboxes are only used by their designated vehicle owners.

This script analyzes SUMO simulation output to verify the vehicleTypes restriction
on charging stations is working correctly.
"""

import xml.etree.ElementTree as ET
import sys
import os
from collections import defaultdict


def parse_wallbox_restrictions(wallbox_file):
    """
    Parse private_wallboxes.xml to get wallbox -> allowed_vehicle_type mapping.
    
    Returns:
        dict: {wallbox_id: allowed_vehicle_type}
    """
    wallbox_restrictions = {}
    
    try:
        tree = ET.parse(wallbox_file)
        root = tree.getroot()
        
        # Find chargingStations both at root level and nested inside parkingAreas
        for cs in root.findall('chargingStation'):
            cs_id = cs.get('id')
            vehicle_types = cs.get('vehicleTypes')
            if cs_id and cs_id.startswith('wallbox_'):
                wallbox_restrictions[cs_id] = vehicle_types
        
        for pa in root.findall('parkingArea'):
            pa_id = pa.get('id', '')
            for cs in pa.findall('chargingStation'):
                cs_id = cs.get('id')
                if cs_id and cs_id.startswith('wallbox_'):
                    # For nested stations, derive allowed type from parkingArea ID
                    # parkingArea_personX -> vehicleType_personX
                    person_id = pa_id.replace('parkingArea_', '')
                    allowed_type = f'vehicleType_{person_id}'
                    wallbox_restrictions[cs_id] = allowed_type
        
        print(f"✓ Found {len(wallbox_restrictions)} private wallboxes with restrictions")
        return wallbox_restrictions
    
    except Exception as e:
        print(f"[ERROR] Could not parse wallbox file: {e}")
        return {}


def parse_vehicle_types(trips_file):
    """
    Parse osm.passenger.trips.xml to get vehicle -> vehicle_type mapping.
    
    Returns:
        dict: {vehicle_id: vehicle_type}
    """
    vehicle_types = {}
    
    try:
        tree = ET.parse(trips_file)
        root = tree.getroot()
        
        for vehicle in root.findall('vehicle'):
            vehicle_id = vehicle.get('id')
            vehicle_type = vehicle.get('type')
            
            if vehicle_id and vehicle_type:
                vehicle_types[vehicle_id] = vehicle_type
        
        print(f"✓ Found {len(vehicle_types)} vehicles")
        ev_count = sum(1 for vt in vehicle_types.values() if vt.startswith('vehicleType_'))
        print(f"  - {ev_count} EVs with unique vehicle types")
        print(f"  - {len(vehicle_types) - ev_count} regular vehicles")
        return vehicle_types
    
    except Exception as e:
        print(f"[ERROR] Could not parse trips file: {e}")
        return {}


def parse_charging_events(chargingstations_output_file):
    """
    Parse chargingstations.xml output from SUMO simulation.
    
    Returns:
        list: [(vehicle_id, charging_station_id, begin_time, end_time, energy)]
    """
    charging_events = []
    
    try:
        tree = ET.parse(chargingstations_output_file)
        root = tree.getroot()
        
        for cs in root.findall('.//chargingStation'):
            cs_id = cs.get('id')
            
            for vehicle in cs.findall('vehicle'):
                vehicle_id = vehicle.get('id')
                begin = float(vehicle.get('begin', 0))
                end = float(vehicle.get('end', 0))
                charged_energy = float(vehicle.get('actualBatteryCapacity', 0))
                
                if vehicle_id and cs_id:
                    charging_events.append((vehicle_id, cs_id, begin, end, charged_energy))
        
        print(f"✓ Found {len(charging_events)} charging events in simulation")
        return charging_events
    
    except FileNotFoundError:
        print(f"[WARNING] Charging stations output file not found: {chargingstations_output_file}")
        print("  Make sure the simulation completed and generated chargingstations.xml")
        return []
    except Exception as e:
        print(f"[ERROR] Could not parse charging output: {e}")
        return []


def validate_wallbox_usage(scenario_dir):
    """
    Validate that wallboxes are only used by their designated owners.
    
    Args:
        scenario_dir (str): Path to the scenario directory.
        
    Returns:
        dict: Validation results
    """
    print("\n" + "="*70)
    print("VALIDATING PRIVATE WALLBOX USAGE")
    print("="*70 + "\n")
    
    # File paths
    wallbox_file = os.path.join(scenario_dir, "private_wallboxes.xml")
    trips_file = os.path.join(scenario_dir, "osm.passenger.trips.xml")
    charging_output = os.path.join(scenario_dir, "chargingstations.xml")
    
    # Check if files exist
    if not os.path.exists(wallbox_file):
        print(f"[ERROR] Wallbox file not found: {wallbox_file}")
        return None
    
    if not os.path.exists(trips_file):
        print(f"[ERROR] Trips file not found: {trips_file}")
        return None
    
    if not os.path.exists(charging_output):
        print(f"[ERROR] Charging output file not found: {charging_output}")
        print("  You need to run the SUMO simulation first!")
        return None
    
    # Parse input files
    print("Step 1: Parsing wallbox restrictions...")
    wallbox_restrictions = parse_wallbox_restrictions(wallbox_file)
    
    print("\nStep 2: Parsing vehicle types...")
    vehicle_types = parse_vehicle_types(trips_file)
    
    print("\nStep 3: Parsing charging events from simulation output...")
    charging_events = parse_charging_events(charging_output)
    
    if not charging_events:
        print("\n[WARNING] No charging events found. Vehicles may not have needed to charge.")
        print("  Try running a longer simulation or with lower initial battery levels.")
        return {
            'total_events': 0,
            'violations': [],
            'valid_events': 0
        }
    
    # Validate each charging event
    print("\nStep 4: Validating charging events...")
    print("-" * 70)
    
    violations = []
    valid_events = 0
    wallbox_usage = defaultdict(list)
    
    for vehicle_id, cs_id, begin, end, energy in charging_events:
        # Only check private wallboxes
        if not cs_id.startswith('wallbox_'):
            continue
        
        wallbox_usage[cs_id].append(vehicle_id)
        
        # Get vehicle's type
        vehicle_type = vehicle_types.get(vehicle_id, 'UNKNOWN')
        
        # Get allowed type for this wallbox
        allowed_type = wallbox_restrictions.get(cs_id, 'UNKNOWN')
        
        # Check if vehicle type matches allowed type
        if vehicle_type != allowed_type:
            violations.append({
                'vehicle_id': vehicle_id,
                'vehicle_type': vehicle_type,
                'wallbox_id': cs_id,
                'allowed_type': allowed_type,
                'time': begin,
                'duration': end - begin,
                'energy': energy
            })
            print(f"⚠️  VIOLATION: {vehicle_id} (type: {vehicle_type}) used {cs_id}")
            print(f"   Expected type: {allowed_type}")
            print(f"   Time: {begin:.1f}s - {end:.1f}s")
        else:
            valid_events += 1
    
    # Summary
    print("\n" + "="*70)
    print("VALIDATION RESULTS")
    print("="*70)
    
    total_wallbox_events = sum(len(vehicles) for cs_id, vehicles in wallbox_usage.items() if cs_id.startswith('wallbox_'))
    
    print(f"\nTotal wallboxes: {len(wallbox_restrictions)}")
    print(f"Wallboxes used at least once: {len(wallbox_usage)}")
    print(f"Total charging events at wallboxes: {total_wallbox_events}")
    print(f"Valid events (correct owner): {valid_events}")
    print(f"Violations (wrong vehicle): {len(violations)}")
    
    if len(violations) == 0:
        print("\n✅ SUCCESS! All wallboxes were only used by their designated owners!")
        print("   The vehicleTypes restriction is working correctly.")
    else:
        print(f"\n❌ FAILURE! Found {len(violations)} violations where vehicles used wallboxes they shouldn't access.")
        print("   This indicates the vehicleTypes restriction may not be working properly.")
        print("\nViolation details:")
        for v in violations[:10]:  # Show first 10 violations
            print(f"  - {v['vehicle_id']} used {v['wallbox_id']} at {v['time']:.1f}s")
    
    # Additional statistics
    print("\n" + "-"*70)
    print("WALLBOX USAGE STATISTICS")
    print("-" * 70)
    
    used_wallboxes = [(cs_id, len(vehicles)) for cs_id, vehicles in wallbox_usage.items() if cs_id.startswith('wallbox_')]
    used_wallboxes.sort(key=lambda x: x[1], reverse=True)
    
    if used_wallboxes:
        print(f"\nTop 10 most used wallboxes:")
        for cs_id, count in used_wallboxes[:10]:
            owner = cs_id.replace('wallbox_', '')
            print(f"  {cs_id:30s} - {count:3d} charging session(s) (owner: {owner})")
        
        unused_count = len(wallbox_restrictions) - len(used_wallboxes)
        if unused_count > 0:
            print(f"\n{unused_count} wallboxes were not used during the simulation")
    
    return {
        'total_wallboxes': len(wallbox_restrictions),
        'total_events': total_wallbox_events,
        'valid_events': valid_events,
        'violations': violations,
        'wallbox_usage': dict(wallbox_usage)
    }


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python validate_wallbox_usage.py <scenario_directory>")
        print("\nExample:")
        print("  python validate_wallbox_usage.py ../data/scenarios/scenario_20260207_002502")
        sys.exit(1)
    
    scenario_dir = sys.argv[1]
    
    if not os.path.isdir(scenario_dir):
        print(f"[ERROR] Directory not found: {scenario_dir}")
        sys.exit(1)
    
    results = validate_wallbox_usage(scenario_dir)
    
    if results is None:
        sys.exit(1)
    
    # Exit with error code if violations found
    if results['violations']:
        sys.exit(1)
    else:
        sys.exit(0)
