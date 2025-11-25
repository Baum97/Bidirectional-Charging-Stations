import sumolib
import csv
import os

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
def assign_poi_to_edges(netfile, input_csv_files):
    """
    Assign POIs to the closest edges in the SUMO network.

    Args:
        netfile (str): Path to the SUMO network file.
        input_csv_files (list): List of input CSV files containing POIs.

    Returns:
        list: List of output CSV file paths with assigned edge IDs.
    """
    if not input_csv_files:
        raise ValueError("Input CSV files list is empty or None.")

    output_csv_files = [f.replace('.csv', '_edges.csv') for f in input_csv_files]

    # Load the SUMO network
    net = sumolib.net.readNet(netfile)

    def get_closest_edge(net, x, y, radius=100):
        edges = net.getNeighboringEdges(x, y, radius)
        if not edges:
            return None
        edge, dist = min(edges, key=lambda e: e[1])
        return edge

    # Assign edges for each input CSV file
    for input_csv, output_csv in zip(input_csv_files, output_csv_files):
        if not os.path.exists(input_csv):
            print(f"[ERROR] Input CSV file does not exist: {input_csv}")
            continue

        print(f"[INFO] Processing input CSV file: {input_csv}")
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

                    # Convert WGS84 to SUMO projection
                    x, y = net.convertLonLat2XY(lon, lat)
                    print(f"[DEBUG] Processing POI {poi_id} at lon: {lon}, lat: {lat}, x: {x}, y: {y}")

                    edge = get_closest_edge(net, x, y)
                    if edge is None:
                        print(f"[WARNING] No edge found for POI {poi_id} at ({lon}, {lat}). Skipping.")
                        writer.writerow([poi_id, lon, lat, x, y, ""])
                        continue

                    edge_id = edge.getID()
                    print(f"[DEBUG] Closest edge for POI {poi_id}: {edge_id}")
                    writer.writerow([poi_id, lon, lat, x, y, edge_id])

                except Exception as e:
                    print(f"[ERROR] Skipping row due to error: {e}. Row content: {row}")

    print("Fertig! Edge-IDs wurden erfolgreich zugeordnet.")
    return output_csv_files

    # return [os.path.join(output_dir, f"poi_{category}.csv") for category in poi_categories]

# Call the function
print(assign_poi_to_edges(netfile, input_csv_files))
