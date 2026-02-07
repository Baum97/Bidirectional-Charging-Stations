"""
Generate public charging stations that accept all EV vehicle types.
This is an enhanced version of mainGenerateChargingStations.py that:
1. Supports restricting stations to specific vehicle types
2. Can generate both unrestricted and type-restricted stations
"""

import sumolib
import xml.etree.ElementTree as ET
import xml.dom.minidom
import io
import os


def generate_public_charging_stations(netfile, output_dir, min_length, vehicle_types=None):
    """
    Generate public charging stations that accept specified vehicle types.

    Args:
        netfile (str): Path to the SUMO network file.
        output_dir (str): Directory to save the generated charging stations XML file.
        min_length (int): Minimum length of streets to consider for charging stations.
        vehicle_types (list or None): List of vehicle type IDs to allow. If None, all vehicles can use.

    Returns:
        str: Path to the generated charging stations XML file.
    """
    net = sumolib.net.readNet(netfile)

    road_types = [
        "highway.primary", "highway.secondary", "highway.tertiary",
        "residential", "unclassified", "living_street", "service"
    ]

    root = ET.Element("additional")
    count = 0
    
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
                
                # Create charging station attributes
                cs_attrs = {
                    "id": cs_id,
                    "lane": lane_id,
                    "startPos": str(start_pos),
                    "endPos": str(start_pos + 5),  # 5m long
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

    if vehicle_types_str:
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
