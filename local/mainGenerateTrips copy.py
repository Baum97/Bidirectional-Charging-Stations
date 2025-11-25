import sumolib
import csv
import random
import xml.etree.ElementTree as ET
import sys

input_csv = "poi_offices_edges.csv"
output_xml = "osm.passenger.trips.xml"
netfile = "../data/scenarios/test3/osm.net.xml.gz"
num_persons = 250
morning_depart_interval = (23400, 32400)  # 6:30 - 9:00
work_duration = 8 * 3600  # 8 hrs in sec
ev_share = 0.6  # part of electrical cars
num_evs = int(num_persons * ev_share)

# Override with command line arguments if provided
if len(sys.argv) > 1:
    input_csv = sys.argv[1]
if len(sys.argv) > 2:
    output_xml = sys.argv[2]
if len(sys.argv) > 3:
    netfile = sys.argv[3]
if len(sys.argv) > 4:
    num_persons = int(sys.argv[4])
if len(sys.argv) > 5:
    ev_share = float(sys.argv[5])

# load networks and define edges
def edge_allows_passenger(edge):
    for lane in edge.getLanes():
        allowed = getattr(lane, '_allowed', [])
        if 'passenger' in allowed or 'private' in allowed:
            return True
    return False

net = sumolib.net.readNet(netfile)
car_edges = set(e.getID() for e in net.getEdges() if edge_allows_passenger(e))

# filter POI-Edges
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

# every person gets fixed home/work node
persons = []
for i in range(1, num_persons + 1):
    home, work = random.sample(edges, 2)
    persons.append({'id': f'person{i}', 'home': home, 'work': work})

# random id of vehicle
random.seed(42)  
all_ids = [p['id'] for p in persons]
ev_ids = set(random.sample(all_ids, num_evs))

# produce random route
vehicles = []
for p in persons:
    depart_morning = round(random.uniform(*morning_depart_interval), 2)
    veh_type = "veh_ev" if p['id'] in ev_ids else "veh_passenger"
    vehicles.append({
        'id': p['id'],
        'type': veh_type,
        'depart': depart_morning,
        'route': [p['home'], p['work'], p['home']],
        'stop_edge': p['work'],
        'stop_duration': work_duration
    })

vehicles.sort(key=lambda v: v['depart'])

routes = ET.Element('routes')
ET.SubElement(routes, 'vType', id="veh_passenger", vClass="passenger", color="0,0,255")

vtype_ev = ET.SubElement(
    routes, 'vType',
    id="veh_ev",
    minGap="2.50",
    maxSpeed="29.06",
    color="white",
    accel="1.0",
    decel="1.0",
    sigma="0.0",
    emissionClass="Energy",
    mass="183000"
)
# BATTERY CONFIGURATION
ET.SubElement(vtype_ev, 'param', key="has.battery.device", value="true")
ET.SubElement(vtype_ev, 'param', key="device.battery.capacity", value="80000")
ET.SubElement(vtype_ev, 'param', key="device.battery.actualBatteryCapacity", value="40000")
# REROUTING CONFIGURATION
ET.SubElement(vtype_ev, 'param', key="has.rerouting.device", value="true")
ET.SubElement(vtype_ev, 'param', key="device.rerouting.probability", value="1")
# STATION FINDER CONFIGURATION
ET.SubElement(vtype_ev, 'param', key="has.stationfinder.device", value="true")
ET.SubElement(vtype_ev, 'param', key="device.stationfinder.rescueTime", value="1800")
ET.SubElement(vtype_ev, 'param', key="device.stationfinder.reserveFactor", value="1.2")
ET.SubElement(vtype_ev, 'param', key="device.stationfinder.radius", value="3000")
# ENERGY PARAMETERS
ET.SubElement(vtype_ev, 'param', key="maximumPower", value="150000")
ET.SubElement(vtype_ev, 'param', key="recuperationEfficiency", value="0.00")
ET.SubElement(vtype_ev, 'param', key="stoppingThreshold", value="0.1")
# Physik-Params
ET.SubElement(vtype_ev, 'param', key="airDragCoefficient", value="0.35")
ET.SubElement(vtype_ev, 'param', key="constantPowerIntake", value="500")
ET.SubElement(vtype_ev, 'param', key="frontSurfaceArea", value="2.6")
ET.SubElement(vtype_ev, 'param', key="rotatingMass", value="40")
ET.SubElement(vtype_ev, 'param', key="propulsionEfficiency", value="0.95")
ET.SubElement(vtype_ev, 'param', key="radialDragCoefficient", value="0.1")
ET.SubElement(vtype_ev, 'param', key="rollDragCoefficient", value="0.01")

for v in vehicles:
    veh_elem = ET.SubElement(
        routes, 'vehicle',
        id=v['id'],
        type=v['type'],
        depart=str(v['depart'])
    )
    ET.SubElement(veh_elem, 'route', edges=" ".join(v['route']))
    ET.SubElement(
        veh_elem, 'stop',
        edge=v['stop_edge'],
        duration=str(v['stop_duration']),
        parking="true"
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

indent(routes)
tree = ET.ElementTree(routes)
tree.write(output_xml, encoding='utf-8', xml_declaration=True)
print(f"Fertig! {num_persons} Fahrzeuge mit Tagesrhythmus und Arbeitsstopp wurden in '{output_xml}' gespeichert.")
