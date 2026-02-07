import sumolib
import xml.etree.ElementTree as ET
import xml.dom.minidom
import io
import os

def generate_charging_stations(netfile, output_dir, min_length):
    """
    Generate charging stations based on the network file and save them to an XML file.

    Args:
        netfile (str): Path to the SUMO network file.
        output_dir (str): Directory to save the generated charging stations XML file.
        min_length (int): Minimum length of streets to consider for charging stations.

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
    skipped = 0
    
    for edge in net.getEdges():
        if edge.getType() not in road_types:
            continue
        for lane in edge.getLanes():
            if lane.getLength() > min_length:
                lane_id = lane.getID()
                lane_length = lane.getLength()
                
                # Place charging station in the middle of the lane
                start_pos = lane_length / 2
                end_pos = start_pos + 5  # 5m long
                
                # Validate that the charging station fits within the lane
                if end_pos > lane_length:
                    # Adjust if it doesn't fit
                    end_pos = lane_length - 0.1  # 0.1m buffer
                    start_pos = max(0, end_pos - 5)
                    
                    # Skip if still invalid
                    if start_pos >= end_pos or start_pos < 0:
                        skipped += 1
                        continue
                
                cs_id = f"CS_{lane_id}"
                ET.SubElement(
                    root, "chargingStation",
                    id=cs_id,
                    lane=lane_id,
                    startPos=str(round(start_pos, 2)),
                    endPos=str(round(end_pos, 2)),
                    power="200000",
                    chargeInTransit="0",
                    chargeDelay="200.0",
                )
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
    output_xml = os.path.join(output_dir, "osm.chargingstations.xml")
    with open(output_xml, "w", encoding="utf-8") as f:
        f.write(pretty_xml)

    print(f"{count} Charging Stations wurden in '{output_xml}' erzeugt.")
    if skipped > 0:
        print(f"[WARNING] {skipped} charging stations skipped due to invalid positions")
    return output_xml