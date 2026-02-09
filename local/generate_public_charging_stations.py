"""
Generate public charging stations with power grid awareness.
This is an enhanced version that:
1. Supports restricting stations to specific vehicle types
2. Considers power grid capacity for optimal placement
3. Prioritizes locations with better grid connectivity
"""

import sumolib
import xml.etree.ElementTree as ET
import xml.dom.minidom
import io
import os


def generate_public_charging_stations(netfile, output_dir, min_length, vehicle_types=None, 
                                      power_grid_manager=None, max_stations=None):
    """
    Generate public charging stations that accept specified vehicle types.
    
    If power_grid_manager is provided, stations are placed considering grid capacity.

    Args:
        netfile (str): Path to the SUMO network file.
        output_dir (str): Directory to save the generated charging stations XML file.
        min_length (int): Minimum length of streets to consider for charging stations.
        vehicle_types (list or None): List of vehicle type IDs to allow. If None, all vehicles can use.
        power_grid_manager: PowerGridManager instance for grid-aware placement (optional)
        max_stations (int): Maximum number of stations to generate (optional)

    Returns:
        str: Path to the generated charging stations XML file.
    """
    net = sumolib.net.readNet(netfile)

    road_types = [
        "highway.primary", "highway.secondary", "highway.tertiary",
        "residential", "unclassified", "living_street", "service"
    ]

    # Collect candidate locations
    candidates = []
    
    # Convert vehicle_types list to space-separated string
    vehicle_types_str = " ".join(vehicle_types) if vehicle_types else None
    
    for edge in net.getEdges():
        if edge.getType() not in road_types:
            continue
        for lane in edge.getLanes():
            if lane.getLength() > min_length:
                lane_id = lane.getID()
                start_pos = lane.getLength() / 2
                cs_id = f"CS_{lane_id}"
                
                # Get lane coordinates for grid analysis
                lane_shape = lane.getShape()
                if len(lane_shape) > 0:
                    # Use midpoint of lane
                    mid_idx = len(lane_shape) // 2
                    x, y = lane_shape[mid_idx]
                    
                    candidate = {
                        'id': cs_id,
                        'lane_id': lane_id,
                        'start_pos': start_pos,
                        'x': x,
                        'y': y,
                        'priority': 1.0  # Default priority
                    }
                    
                    # If power grid manager available, check grid capacity
                    if power_grid_manager:
                        try:
                            # Convert SUMO coords to lon/lat using proper coordinate transformation
                            lon, lat = net.convertXY2LonLat(x, y)
                            
                            grid_capacity = power_grid_manager.get_grid_capacity_at_location(lon, lat, radius_m=1000)
                            
                            # Prioritize locations with better grid access
                            quality_score = {
                                'excellent': 1.0,
                                'good': 0.8,
                                'fair': 0.5,
                                'poor': 0.2,
                                'none': 0.1  # Changed from 0.0 - still include but with low priority
                            }
                            candidate['grid_capacity_kw'] = grid_capacity['available_power_kw']
                            candidate['grid_quality'] = grid_capacity['grid_quality']
                            candidate['priority'] = quality_score.get(grid_capacity['grid_quality'], 0.5)
                            
                            # Don't skip locations with no grid access - just deprioritize them
                            # This ensures we still generate stations even if grid is sparse
                        except Exception as e:
                            # Grid check failed - use default priority
                            print(f"[DEBUG] Grid check failed for {cs_id}: {e}")
                            pass
                    
                    candidates.append(candidate)
    
    # Sort candidates by priority (best grid access first)
    if power_grid_manager:
        candidates.sort(key=lambda c: c['priority'], reverse=True)
        print(f"[INFO] Prioritized {len(candidates)} locations by grid capacity")
    
    # Limit number of stations if requested
    if max_stations and len(candidates) > max_stations:
        candidates = candidates[:max_stations]
        print(f"[INFO] Limited to {max_stations} best locations")
    
    # Generate XML
    root = ET.Element("additional")
    count = 0
    
    for candidate in candidates:
        # Create charging station attributes
        cs_attrs = {
            "id": candidate['id'],
            "lane": candidate['lane_id'],
            "startPos": str(candidate['start_pos']),
            "endPos": str(candidate['start_pos'] + 5),  # 5m long
            "power": "200000",  # 200 kW public fast charger
            "chargeInTransit": "0",
            "chargeDelay": "200.0",
        }
        
        # Add vehicleTypes restriction if specified
        if vehicle_types_str:
            cs_attrs["vehicleTypes"] = vehicle_types_str
        
        ET.SubElement(root, "chargingStation", **cs_attrs)
        count += 1

    tree = ET.ElementTree(root)

    # Pretty-Print XML
    xml_bytes = io.BytesIO()
    tree.write(xml_bytes, encoding="utf-8", xml_declaration=True)
    xml_str = xml_bytes.getvalue().decode("utf-8")
    parsed = xml.dom.minidom.parseString(xml_str)
    pretty_xml = parsed.toprettyxml(indent="  ")

    # Save to output directory
    os.makedirs(output_dir, exist_ok=True)
    output_xml = os.path.join(output_dir, "public_chargingstations.xml")
    with open(output_xml, "w", encoding="utf-8") as f:
        f.write(pretty_xml)

    if power_grid_manager:
        print(f"✓ Generated {count} grid-aware public charging stations")
    elif vehicle_types_str:
        print(f"✓ Generated {count} public charging stations (restricted to {len(vehicle_types)} vehicle types)")
    else:
        print(f"✓ Generated {count} public charging stations (unrestricted)")
    print(f"  Saved to: {output_xml}")
    
    return output_xml


if __name__ == "__main__":
    # Example: Generate public charging stations that accept all EV types
    import sys
    
    if len(sys.argv) < 3:
        print("Usage: python generate_public_charging_stations.py <netfile> <output_dir> [min_length]")
        sys.exit(1)
    
    netfile = sys.argv[1]
    output_dir = sys.argv[2]
    min_length = int(sys.argv[3]) if len(sys.argv) > 3 else 50
    
    # Generate unrestricted public stations
    generate_public_charging_stations(netfile, output_dir, min_length)
