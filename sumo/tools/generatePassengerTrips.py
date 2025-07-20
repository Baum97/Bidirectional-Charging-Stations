import sumolib
import csv
import random
import xml.etree.ElementTree as ET

input_csv = "poi_edges.csv"
output_xml = "osm.passenger.trips.xml"
netfile = "generated_files/osm.net.xml.gz"
num_persons = 50
morning_depart_interval = (23400, 32400)  # 6:30 - 9:00
work_duration = 8 * 3600  # 8 Stunden in Sekunden

# Netz laden und befahrbare Edges bestimmen
def edge_allows_passenger(edge):
    for lane in edge.getLanes():
        allowed = getattr(lane, '_allowed', [])
        if 'passenger' in allowed or 'private' in allowed:
            return True
    return False

net = sumolib.net.readNet(netfile)
car_edges = set(e.getID() for e in net.getEdges() if edge_allows_passenger(e))

# POI-Edges filtern
edges = set()
with open(input_csv, 'r', encoding='utf-8') as f:
    reader = csv.DictReader(f)
    for row in reader:
        edge_id = row['edge_id']
        if edge_id and edge_id in car_edges:
            edges.add(edge_id)
edges = list(edges)

if len(edges) < 2:
    raise ValueError("Es müssen mindestens zwei verschiedene befahrbare Edges vorhanden sein!")

# Für jede Person einen festen home- und work-Edge ziehen (verschieden!)
persons = []
for i in range(1, num_persons + 1):
    home, work = random.sample(edges, 2)
    persons.append({'id': f'person{i}', 'home': home, 'work': work})

# Fahrzeuge mit Route und Stop generieren
vehicles = []
for p in persons:
    depart_morning = round(random.uniform(*morning_depart_interval), 2)
    vehicles.append({
        'id': p['id'],
        'type': "veh_passenger",
        'depart': depart_morning,
        'route': [p['home'], p['work'], p['home']],
        'stop_edge': p['work'],
        'stop_duration': work_duration
    })

# XML schreiben (mit Einrückung)
routes = ET.Element('routes')
ET.SubElement(routes, 'vType', id="veh_passenger", vClass="passenger")
for v in vehicles:
    veh_elem = ET.SubElement(
        routes, 'vehicle',
        id=v['id'],
        type=v['type'],
        depart=str(v['depart'])
    )
    ET.SubElement(veh_elem, 'route', edges=" ".join(v['route']))
    ET.SubElement(veh_elem, 'stop', edge=v['stop_edge'], duration=str(v['stop_duration']))

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
tree = ET.ElementTree(routes)
tree.write(output_xml, encoding='utf-8', xml_declaration=True)
print(f"Fertig! {num_persons} Fahrzeuge mit Tagesrhythmus und Arbeitsstopp wurden in '{output_xml}' gespeichert.")