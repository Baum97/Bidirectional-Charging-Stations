import sumolib
import csv

# Pfade zu den Dateien
netfile = "generated_files/osm.net.xml.gz"
input_csv = "poi_coordinates.csv"
output_csv = "poi_edges.csv"

# SUMO-Netz laden
net = sumolib.net.readNet(netfile)

def get_closest_edge(net, x, y, radius=100):
    # Liefert die Edge mit der geringsten Distanz im Umkreis
    edges = net.getNeighboringEdges(x, y, radius)
    if not edges:
        return None
    # edges ist eine Liste von (edge, dist)-Tupeln
    edge, dist = min(edges, key=lambda e: e[1])
    return edge

# CSV einlesen und neue CSV schreiben
with open(input_csv, 'r', encoding='utf-8') as infile, \
     open(output_csv, 'w', newline='', encoding='utf-8') as outfile:
    reader = csv.DictReader(infile)
    writer = csv.writer(outfile)
    writer.writerow(['poi_id', 'x', 'y', 'edge_id'])  # Header

    for row in reader:
        poi_id = row['poi_id']
        x = float(row['x'])
        y = float(row['y'])
        edge = get_closest_edge(net, x, y)
        edge_id = edge.getID() if edge else ""
        writer.writerow([poi_id, x, y, edge_id])

print("Fertig! Die Datei 'poi_edges.csv' enthält jetzt die Edge-IDs zu den POIs.")