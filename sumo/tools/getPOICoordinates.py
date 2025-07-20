import gzip
import xml.etree.ElementTree as ET
import csv

# Pfad zur Datei
filename = "generated_files/osm.poly.xml.gz"
output_csv = "poi_coordinates.csv"

# Datei entpacken und parsen
with gzip.open(filename, 'rt', encoding='utf-8') as f:
    tree = ET.parse(f)
    root = tree.getroot()

# CSV-Datei schreiben
with open(output_csv, 'w', newline='', encoding='utf-8') as csvfile:
    writer = csv.writer(csvfile)
    writer.writerow(['poi_id', 'x', 'y'])  # Header
    for poly in root.findall('poly'):
        if poly.get('type') == 'building.residential':
            poi_id = poly.get('id')
            shape = poly.get('shape')
            coords = [tuple(map(float, pair.split(','))) for pair in shape.strip().split()]
            for x, y in coords:
                writer.writerow([poi_id, x, y])