import csv
import random
import xml.etree.ElementTree as ET

# Parameter
def main():
    input_csv = "poi_edges.csv"
    output_xml = "osm.passenger.trips.xml"
    num_trips = 50           # Anzahl der Fahrzeuge/Trips
    begin = 0                # Simulationsstart (Sekunden)
    end = 3600               # Simulationsende (Sekunden)
    depart_interval = (0, end)  # Zeitfenster für Abfahrten

    # Einzigartige Edge-IDs aus CSV sammeln
    edges = set()
    with open(input_csv, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            edge_id = row['edge_id']
            if edge_id:
                edges.add(edge_id)
    edges = list(edges)

    if len(edges) < 2:
        raise ValueError("Es müssen mindestens zwei verschiedene Edges vorhanden sein!")

    # XML-Struktur aufbauen
    routes = ET.Element('routes')
    vtype = ET.SubElement(routes, 'vType', id="veh_passenger", vClass="passenger")

    for i in range(1, num_trips + 1):
        from_edge, to_edge = random.sample(edges, 2)
        depart = round(random.uniform(*depart_interval), 2)
        trip = ET.SubElement(
            routes, 'trip',
            id=f"poiTrip{i}",
            type="veh_passenger",
            depart=str(depart),
            departLane="best",
            from_=from_edge,
            to=to_edge
        )

    # Attribut 'from_' muss zu 'from' umbenannt werden (wegen Python-Schlüsselwort)
    for trip in routes.findall('trip'):
        trip.attrib['from'] = trip.attrib.pop('from_')

    # XML schön formatieren (einrücken)
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

    # XML speichern
    tree = ET.ElementTree(routes)
    tree.write(output_xml, encoding='utf-8', xml_declaration=True)

    print(f"Fertig! {num_trips} Trips wurden in '{output_xml}' gespeichert.")

if __name__ == "__main__":
    main() 