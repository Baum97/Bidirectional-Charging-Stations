import sumolib
import csv

# Pfade zu den Dateien
netfile = "../data/scenarios/test3/osm.net.xml.gz"
input_csv_files = ["poi_offices.csv", "poi_residential.csv", "poi_others.csv"]
output_csv_files = ["poi_offices_edges.csv", "poi_residential_edges.csv", "poi_others_edges.csv"]

# SUMO-Netz laden
net = sumolib.net.readNet(netfile)

def get_closest_edge(net, x, y, radius=100):
    edges = net.getNeighboringEdges(x, y, radius)
    if not edges:
        return None
    edge, dist = min(edges, key=lambda e: e[1])
    return edge

# Für jede Eingabedatei die Edge-IDs berechnen
for input_csv, output_csv in zip(input_csv_files, output_csv_files):
    with open(input_csv, 'r', encoding='utf-8') as infile, \
         open(output_csv, 'w', newline='', encoding='utf-8') as outfile:
        reader = csv.DictReader(infile)
        writer = csv.writer(outfile)
        writer.writerow(['poi_id', 'lon', 'lat', 'x', 'y', 'edge_id'])

        for row in reader:
            try:
                poi_id = row['id']
                lon = float(row['lon'])
                lat = float(row['lat'])

                # ⭐ CONVERT WGS84 → SUMO PROJECTION ⭐
                x, y = net.convertLonLat2XY(lon, lat)

                edge = get_closest_edge(net, x, y)
                edge_id = edge.getID() if edge else ""

                writer.writerow([poi_id, lon, lat, x, y, edge_id])

            except Exception as e:
                print(f"Skipping row due to error: {e}. Row content: {row}")

print("Fertig! Edge-IDs wurden erfolgreich zugeordnet.")
