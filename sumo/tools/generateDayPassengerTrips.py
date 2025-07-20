import sumolib
import csv
import random
import xml.etree.ElementTree as ET

input_csv = "poi_edges.csv"
output_xml = "generated_files/osm.passenger.trips.xml"
netfile = "generated_files/osm.net.xml.gz"
num_persons = 1
# Zeitintervalle in Sekunden ab Mitternacht
morning_depart_interval = (23400, 32400)  # 6:30 - 9:00
evening_depart_interval = (57600, 68400)  # 16:00 - 19:00

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

# Trips generieren
trips = []
for p in persons:
    # Morgens: home -> work
    depart_morning = round(random.uniform(*morning_depart_interval), 2)
    trips.append({
        'id': f"{p['id']}_morning",
        'type': "veh_passenger",
        'depart': depart_morning,
        'departLane': "best",
        'from': p['home'],
        'to': p['work']
    })
    # Abends: work -> home
    depart_evening = round(random.uniform(*evening_depart_interval), 2)
    trips.append({
        'id': f"{p['id']}_evening",
        'type': "veh_passenger",
        'depart': depart_evening,
        'departLane': "best",
        'from': p['work'],
        'to': p['home']
    })

# Trips nach Abfahrtszeit sortieren
trips.sort(key=lambda t: t['depart'])

# XML schreiben (mit Einrückung)
routes = ET.Element('routes')
ET.SubElement(routes, 'vType', id="veh_passenger", vClass="passenger")
for t in trips:
    ET.SubElement(
        routes, 'trip',
        id=t['id'],
        type=t['type'],
        depart=str(t['depart']),
        departLane=t['departLane'],
        from_=t['from'],
        to=t['to']
    )
for trip in routes.findall('trip'):
    trip.attrib['from'] = trip.attrib.pop('from_')

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
print(f"Fertig! {num_persons} Personen mit Tagesrhythmus-Trips wurden in '{output_xml}' gespeichert.")
