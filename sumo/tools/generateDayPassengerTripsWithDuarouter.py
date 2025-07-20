import sumolib
import csv
import random
import xml.etree.ElementTree as ET
import subprocess
import os

input_csv = "poi_edges.csv"
output_trips = "osm.passenger.trips.xml"
output_routes = "osm.passenger.routes.xml"
netfile = "generated_files/osm.net.xml.gz"
num_persons = 50
morning_depart_interval = (23400, 32400)  # 6:30 - 9:00

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
trips = ET.Element('trips')
ET.SubElement(trips, 'vType', id="veh_passenger", vClass="passenger")
for p in persons:
    depart_morning = round(random.uniform(*morning_depart_interval), 2)
    ET.SubElement(
        trips, 'trip',
        id=p['id'],
        type="veh_passenger",
        depart=str(depart_morning),
        from_=p['home'],
        to=p['work']
    )

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

indent(trips)
tree = ET.ElementTree(trips)
tree.write(output_trips, encoding='utf-8', xml_declaration=True)
print(f"Fertig! {num_persons} Trips wurden in '{output_trips}' gespeichert.")

# duarouter aufrufen
duarouter_cmd = [
    "duarouter",
    "-n", netfile,
    "-t", output_trips,
    "-o", output_routes,
    "--ignore-errors",  # Optional: damit das Skript nicht abbricht, wenn ein Trip nicht routbar ist
    "--route-files.sort"
]
print("Starte duarouter...")
try:
    subprocess.run(duarouter_cmd, check=True)
    print(f"Routen wurden erfolgreich in '{output_routes}' erzeugt.")
except FileNotFoundError:
    print("Fehler: duarouter wurde nicht gefunden. Stelle sicher, dass SUMO in deinem PATH ist.")
except subprocess.CalledProcessError as e:
    print("Fehler beim Ausführen von duarouter:", e)
