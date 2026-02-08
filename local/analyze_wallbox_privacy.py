#!/usr/bin/env python3
"""
Analyze wallbox charging sessions to verify privacy (only owners should charge at their wallbox)
"""
import csv
import sys
import os

def analyze_wallbox_sessions(charging_sessions_csv):
    """
    Analyze charging sessions at private wallboxes to check if privacy is enforced.
    
    Args:
        charging_sessions_csv: Path to charging_sessions.csv
    
    Returns:
        dict with analysis results
    """
    with open(charging_sessions_csv, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        
        wallbox_sessions = []
        public_sessions = []
        
        for row in reader:
            veh_id = row['veh_id']
            station_id = row['station_id']
            
            if station_id.startswith('wallbox_'):
                wallbox_sessions.append({
                    'vehicle': veh_id,
                    'station': station_id,
                    'owner': station_id.replace('wallbox_', ''),  # Extract owner from wallbox_personXX
                    'energy': float(row['energy_kwh']),
                    'time': float(row['end_time'])
                })
            else:
                public_sessions.append({
                    'vehicle': veh_id,
                    'station': station_id,
                    'energy': float(row['energy_kwh'])
                })
    
    # Analyze wallbox privacy
    owner_sessions = []  # Vehicle charging at their own wallbox
    trespasser_sessions = []  # Vehicle charging at someone else's wallbox
    
    for session in wallbox_sessions:
        if session['vehicle'] == session['owner']:
            owner_sessions.append(session)
        else:
            trespasser_sessions.append(session)
    
    return {
        'wallbox_sessions': wallbox_sessions,
        'public_sessions': public_sessions,
        'owner_sessions': owner_sessions,
        'trespasser_sessions': trespasser_sessions
    }

def print_analysis(results):
    """Print human-readable analysis"""
    total_wallbox = len(results['wallbox_sessions'])
    total_public = len(results['public_sessions'])
    owners = len(results['owner_sessions'])
    trespassers = len(results['trespasser_sessions'])
    
    print(f"\n{'='*70}")
    print(f"WALLBOX PRIVACY ANALYSIS")
    print(f"{'='*70}\n")
    
    print(f"Total charging sessions: {total_wallbox + total_public}")
    print(f"  - Public stations: {total_public}")
    print(f"  - Private wallboxes: {total_wallbox}")
    print()
    
    print(f"Private wallbox usage breakdown:")
    print(f"  ✅ Owner charging at their own wallbox: {owners} ({owners/total_wallbox*100:.1f}%)")
    print(f"  ❌ Trespasser charging at someone else's wallbox: {trespassers} ({trespassers/total_wallbox*100:.1f}%)")
    print()
    
    if trespassers > 0:
        print(f"⚠️  PRIVACY VIOLATION DETECTED!")
        print(f"   Wallboxes should be restricted to owners only.\n")
        
        # Show first 10 violations
        print(f"Sample trespasser sessions (showing first 10):")
        for i, session in enumerate(results['trespasser_sessions'][:10]):
            print(f"  {i+1}. {session['vehicle']} charged at wallbox_{session['owner']} (time: {session['time']:.0f}s, energy: {session['energy']:.3f} kWh)")
        
        if len(results['trespasser_sessions']) > 10:
            print(f"  ... and {len(results['trespasser_sessions']) - 10} more violations")
    else:
        print(f"✅ Privacy is perfectly enforced! No trespassers detected.")
    
    print()
    
    # Show owner usage
    if owners > 0:
        print(f"Owner wallbox usage (showing first 10):")
        for i, session in enumerate(results['owner_sessions'][:10]):
            print(f"  {i+1}. {session['vehicle']} charged at their wallbox_{session['owner']} (time: {session['time']:.0f}s, energy: {session['energy']:.3f} kWh)")
        
        if len(results['owner_sessions']) > 10:
            print(f"  ... and {len(results['owner_sessions']) - 10} more owner sessions")
    
    print(f"\n{'='*70}\n")

if __name__ == "__main__":
    if len(sys.argv) > 1:
        csv_path = sys.argv[1]
    else:
        # Default to most recent scenario
        csv_path = "../data/scenarios/scenario_20260208_220613/traci_logs/charging_sessions.csv"
    
    if not os.path.exists(csv_path):
        print(f"Error: File not found: {csv_path}")
        sys.exit(1)
    
    print(f"Analyzing: {csv_path}")
    results = analyze_wallbox_sessions(csv_path)
    print_analysis(results)
