import traci
import csv
import xml.etree.ElementTree as ET
import pandas as pd
import time


sumo_cfg = "generated_files/osmNoTraci.sumocfg"
output_csv = "ev_soc_tracking.csv"

sumo_cmd = ["sumo", "-c", sumo_cfg, "--start"]
traci.start(sumo_cmd)

# Caching
charging_stations_cache = {}  # lane_id -> [(cs_id, start_pos, end_pos), ...]
last_soc = {}
charging_status = {}

# EV tracking
ev_vehicles = set()
step_counter = 0
EV_TYPES = ["veh_ev"]

# Performance settings
TRACKING_INTERVAL = 50
POSITION_TOLERANCE = 1.0
SOC_CHANGE_THRESHOLD = 0.1

# RampUp system
charging_start_time = {}      # veh_id -> time charging began
charging_ramp_power = {}      # veh_id -> last used charging power

MAX_CHARGING_POWER = 200000   # Watt (matching additional.xml)
RAMPUP_DURATION = 300         # seconds

def compute_rampup_power(veh_id, sim_time):
    """Compute the progressive power increase."""
    start_t = charging_start_time.get(veh_id)
    if start_t is None:
        return 0

    dt = sim_time - start_t
    ramp_factor = min(1.0, dt / RAMPUP_DURATION)

    return MAX_CHARGING_POWER * ramp_factor


def build_charging_stations_cache():
    """Build cache of charging stations."""
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
    """Fast lookup via lane cache."""
    try:
        current_lane = traci.vehicle.getLaneID(veh_id)

        if current_lane in charging_stations_cache:
            veh_pos = traci.vehicle.getLanePosition(veh_id)
            
            for cs_id, cs_start, cs_end in charging_stations_cache[current_lane]:
                if (cs_start - POSITION_TOLERANCE) <= veh_pos <= (cs_end + POSITION_TOLERANCE):
                    return cs_id
    except traci.TraCIException:
        pass
    
    return None


# Initialize cache
build_charging_stations_cache()

step_counter = 50
start = time.time()

while traci.simulation.getMinExpectedNumber() > 0:
    traci.simulationStep()
    sim_time = traci.simulation.getTime()

    if step_counter % 1000 == 0:
        print("sim_time:", sim_time)

    if step_counter % TRACKING_INTERVAL != 0:
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

            # Detect possible charging
            if speed < 0.2:
                station_id = find_charging_station_for_vehicle_fast(veh_id)
                
                if station_id:
                    if veh_id in last_soc:
                        soc_diff = soc_percent - last_soc[veh_id]
                        if soc_diff > SOC_CHANGE_THRESHOLD:
                            is_charging = True
                    else:
                        is_charging = True

            # Update charging state
            prev_status = charging_status.get(veh_id, (False, None))
            charging_status[veh_id] = (is_charging, station_id)

            # --- RAMP UP LOGIC ---
            if is_charging and station_id:

                # Start of charging event
                if veh_id not in charging_start_time:
                    charging_start_time[veh_id] = sim_time

                new_power = compute_rampup_power(veh_id, sim_time)
                charging_ramp_power[veh_id] = new_power

                try:
                    traci.chargingstation.setChargingPower(station_id, new_power)
                    print(f"{veh_id} at station {station_id}, RampPower={new_power}")
                except traci.TraCIException:
                    pass

            else:
                # Reset RampUp
                charging_start_time.pop(veh_id, None)
                charging_ramp_power.pop(veh_id, None)

            last_soc[veh_id] = soc_percent

        except (traci.TraCIException, ValueError, TypeError):
            ev_vehicles.discard(veh_id)
            continue


traci.close()
end = time.time()
print("Runtime der Simulation:", (end-start))
print("Simulation beendet.")
