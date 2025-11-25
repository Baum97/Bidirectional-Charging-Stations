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
    for edge in net.getEdges():
        if edge.getType() not in road_types:
            continue
        for lane in edge.getLanes():
            if lane.getLength() > min_length:
                lane_id = lane.getID()
                start_pos = lane.getLength() / 2
                cs_id = f"CS_{lane_id}"
                ET.SubElement(
                    root, "chargingStation",
                    id=cs_id,
                    lane=lane_id,
                    startPos=str(start_pos),
                    endPos=str(start_pos + 5),  # 5m long
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
    return output_xml