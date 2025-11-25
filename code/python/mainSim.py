import traci
import csv
import xml.etree.ElementTree as ET
import pandas as pd


sumo_cfg = "generated_files/osm.sumocfg"
output_csv = "ev_soc_tracking.csv"

sumo_cmd = ["sumo-gui", "-c", sumo_cfg, "--start"]
traci.start(sumo_cmd)

# Caching
charging_stations_cache = {}  # lane_id -> [(cs_id, start_pos, end_pos), ...]
last_soc = {}
charging_status = {}
unique_charging_process = []
charging_count = 0
charge_entries = {}
charge_results = {}
model_log_data = []
log_data = []
ev_vehicles = set()
step_counter = 0
EV_TYPES = ["veh_ev"]

# performance settings
TRACKING_INTERVAL = 5  # track every x steps
POSITION_TOLERANCE = 1.0  
SOC_CHANGE_THRESHOLD = 0.1 

def build_charging_stations_cache():
    """Einmaliger Aufbau des Ladestations-Cache für bessere Performance."""
    global charging_stations_cache
    charging_stations_cache = {}
    
    try:
        for cs_id in traci.chargingstation.getIDList():
            try:
                cs_lane = traci.chargingstation.getLaneID(cs_id)
                cs_start = traci.chargingstation.getStartPos(cs_id)
                cs_end = traci.chargingstation.getEndPos(cs_id)
                
                if cs_lane not in charging_stations_cache:
                    charging_stations_cache[cs_lane] = []
                charging_stations_cache[cs_lane].append((cs_id, cs_start, cs_end))
            except traci.TraCIException:
                continue
    except traci.TraCIException:
        print("Warnung: Keine Ladestationen gefunden")

        
    
def find_charging_station_for_vehicle_fast(veh_id):
    """Schnelle Suche nach Ladestation mit Cache."""
    try:
        current_lane = traci.vehicle.getLaneID(veh_id)
        
        # check only stations in own lane
        if current_lane in charging_stations_cache:
            veh_pos = traci.vehicle.getLanePosition(veh_id)
            
            for cs_id, cs_start, cs_end in charging_stations_cache[current_lane]:
                if (cs_start - POSITION_TOLERANCE) <= veh_pos <= (cs_end + POSITION_TOLERANCE):
                    return cs_id
    except traci.TraCIException:
        pass
    
    return None

def add_charging_process(veh_id, is_charging):
    if is_charging == False and veh_id in unique_charging_process:
        print(f"removed car {veh_id} from uniquecharge")
        unique_charging_process.pop(veh_id)
    if veh_id in unique_charging_process:
        pass    
    if station_id not in charge_entries:
        charge_entries[station_id] = 0
    charge_count = charge_entries[station_id]
    charge_entries[station_id] = charge_count+1
    unique_charging_process.append(veh_id)



# build cache
build_charging_stations_cache()
    
while traci.simulation.getMinExpectedNumber() > 0:
    traci.simulationStep()
    time = traci.simulation.getTime()
    step_counter += 1
    
    if step_counter % TRACKING_INTERVAL != 0:
        continue
    
    if step_counter % 50 == 0:
        current_vehicles = set(traci.vehicle.getIDList())

        ev_vehicles = ev_vehicles.intersection(current_vehicles)
        
        for veh_id in current_vehicles - ev_vehicles:
            try:
                vtype = traci.vehicle.getTypeID(veh_id)
                if vtype in EV_TYPES:
                    ev_vehicles.add(veh_id)
            except traci.TraCIException:
                continue
    
    for veh_id in list(ev_vehicles):  
        try:
            try:
                soc = traci.vehicle.getParameter(veh_id, "device.battery.actualBatteryCapacity")
                max_soc = traci.vehicle.getParameter(veh_id, "device.battery.maximumBatteryCapacity")

            except traci.TraCIException:
                ev_vehicles.discard(veh_id)  
                continue
                
            if not soc or not max_soc:
                continue
                
            soc_percent = 100 * float(soc) / float(max_soc)
            
            is_charging = False
            station_id = None
            
            speed = traci.vehicle.getSpeed(veh_id)
            if speed < 0.2:  
                station_id = find_charging_station_for_vehicle_fast(veh_id)
                
                if station_id:
                    if veh_id in last_soc:
                        soc_diff = soc_percent - last_soc[veh_id]
                        if soc_diff > SOC_CHANGE_THRESHOLD:  
                            is_charging = True
                            add_charging_process(veh_id, is_charging)
                    else:
                        is_charging = True  
                        add_charging_process(veh_id, is_charging)
            
            prev_status = charging_status.get(veh_id, (False, None))             
            charging_status[veh_id] = (is_charging, station_id)
            
            coord = str(traci.vehicle.getPosition(veh_id)).strip("()")
            x_pos,y_pos = coord.split(",")
            y_pos.lstrip()
            model_log_data.append({
                    "time": time,
                    "veh_id": veh_id,
                    "position_x" : x_pos,
                    "position_y": y_pos,
                    "edge_id": traci.vehicle.getRoadID(veh_id),
                    "lane_offset": traci.vehicle.getLanePosition(veh_id),
                    "soc": soc_percent,
                    "is_charging": is_charging
            })

            if (is_charging != prev_status[0]) or (step_counter % 100 == 0):
                writer.writerow([time, veh_id, soc_percent, is_charging, station_id or ""])
            
            if is_charging:
                color = (0, 255, 255, 255)  # cyan = loading
            elif soc_percent <= 10:
                color = (255, 0, 0, 255)    # red = low
            elif soc_percent <= 30:
                color = (255, 165, 0, 255)  
            elif soc_percent <= 50:
                color = (100, 255, 100, 255)
            else:
                color = (0, 255, 0, 255)    
                
            try:
                traci.vehicle.setColor(veh_id, color)
            except traci.TraCIException:
                pass  
            
            last_soc[veh_id] = soc_percent
                
        except (traci.TraCIException, ValueError, TypeError):
            ev_vehicles.discard(veh_id) 
            continue

    log_data.append
    with open("logCharges.csv", mode="w", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(["CS_id", "charges"])
        for station_id, charge_count in charge_entries.items():
            writer.writerow([station_id, charge_count])

tree = ET.parse("generated_files/osm.chargingstations.xml")
root = tree.getroot()

df = pd.DataFrame(model_log_data)
df.to_csv("model_log_data.csv", index=False)

with open("logCharges.csv", mode="r", newline="") as file:
    reader = csv.DictReader(file) 
    for row in reader:
        charge_results["CS_id"] = row["charges"]

total_amount_charges = 0
for count in charge_results["CS_id"]:
    total_amount_charges += int(count)

for cs in root.findall("chargingStation"):
    if cs.get("id") not in charge_entries.keys():
        root.remove(cs)
    elif charge_entries[cs.get("id")] < (total_amount_charges/20):
        root.remove(cs)

tree.write("generated_files/osm.chargingstations.xml", encoding="utf-8", xml_declaration=True)


traci.close()
print("Simulation beendet.")