import sys
import os
if 'SUMO_HOME' in os.environ:
    sys.path.append(os.path.join(os.environ['SUMO_HOME'], 'tools'))
import traci # if performance is an issue, change to libsumo (import libsumo as traci)
import time
from xml.etree import ElementTree as ET

# person-based simulation!

# connect to sumo
sumoCmd = ["sumo-gui", "-c", "welzheim.sumocfg", "--start"]
# rather start with sumo?

routes = 'welzheim_routes.rou.xml'
buffer = 30 # buffer in seconds after last excepted person arrival

def get_departure_bounds(route_file):
    tree = ET.parse(route_file)
    root = tree.getroot()

    times = []
    for person in root.findall("person"):
        for stop in person.findall("stop"):
            until = stop.attrib.get("until")
            if until:
                h, m, s = map(int, until.split(":"))
                seconds = h * 3600 + m * 60 + s
                times.append(seconds)

    return min(times), max(times)

traci.start(sumoCmd)

# set simulation times
start_time, end_time = get_departure_bounds(routes)

for _ in range(max(0, start_time - 5)):
    traci.simulationStep() # fast forward 5 seconds before real action happens

current_time = start_time - 5
new_vehicles = []
while current_time < (end_time + buffer):

    traci.simulationStep()

    # check for newly spawned vehicles (triggered by person/ride)
    for vehicleID in traci.simulation.getDepartedIDList():
        if vehicleID not in new_vehicles:
            try:
                # set color (currently not needed)
                traci.vehicle.setColor(vehicleID, (0, 0, 255, 255))

            except traci.TraCIException:
                print(f'Something went wrong!')
                pass
            new_vehicles.append(vehicleID)

    # test battery levels:
    test_vehicleID = "219_0"
    show_battery_219_0 = traci.vehicle.getParameter(test_vehicleID, "device.battery.actualBatteryCapacity")
    print(f'{test_vehicleID} speed: {traci.vehicle.getSpeed(test_vehicleID)}')
    print(f'{test_vehicleID} battery level: {show_battery_219_0} Wh')

    if current_time > end_time:
        if traci.simulation.getMinExpectedNumber() == 0:
            print("All vehicles are gone. Ending simulation now.")
            break

    time.sleep(0.0001)
    current_time +=1

traci.close()


