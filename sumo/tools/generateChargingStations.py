import sumolib
import xml.etree.ElementTree as ET
import xml.dom.minidom
import io

netfile = "generated_files/osm.net.xml.gz"
output_xml = "generated_files/osm.chargingstations.xml"
min_length = 50  # Meter

net = sumolib.net.readNet(netfile)

# Definiere die Typen, die als Straßen gelten (ggf. anpassen)
road_types = [
    "highway.primary", "highway.secondary", "highway.tertiary",
    "residential", "unclassified", "living_street", "service"
]

# Optional: Zum Herausfinden der Typen im Netz, diese Zeile aktivieren
# for edge in net.getEdges():
#     print(edge.getID(), edge.getType())

root = ET.Element("additional")
count = 0
for edge in net.getEdges():
    if edge.getType() not in road_types:
        continue
    for lane in edge.getLanes():
        if lane.getLength() > min_length:
            lane_id = lane.getID()
            # Charging Station mittig auf der Lane platzieren
            start_pos = lane.getLength() / 2
            cs_id = f"CS_{lane_id}"
            ET.SubElement(
                root, "chargingStation",
                id=cs_id,
                lane=lane_id,
                startPos=str(start_pos),
                endPos=str(start_pos + 5),  # 1m lang, kann angepasst werden
                power="22000"  # Beispielwert, anpassen nach Bedarf
            )
            count += 1

tree = ET.ElementTree(root)
# Schreibe zunächst in einen String, um Pretty-Print zu ermöglichen
xml_bytes = io.BytesIO()
tree.write(xml_bytes, encoding="utf-8", xml_declaration=True)
xml_str = xml_bytes.getvalue().decode("utf-8")

# Pretty-Print mit minidom
parsed = xml.dom.minidom.parseString(xml_str)
pretty_xml = parsed.toprettyxml(indent="  ")

with open(output_xml, "w", encoding="utf-8") as f:
    f.write(pretty_xml)

print(f"{count} Charging Stations wurden in '{output_xml}' erzeugt.")