import traci
import time
import csv
import xml.etree.ElementTree as ET
import pandas as pd

from ElectricVehicles import ElectricVehicles
from evse_class import EVSE_class


# ----------------------------------------------------
# CONFIGURATION
# ----------------------------------------------------

SUMO_CONFIG = "generated_files/osmNoTraci.sumocfg"
TRACKING_INTERVAL = 1                     # 1 sec timestep
RAMPUP_DURATION = 20                      # seconds (ramp up over 20s)
MAX_CHARGING_POWER_KW = 200               # kW (server default)
POSITION_TOLERANCE = 1.0
SOC_CHANGE_THRESHOLD = 0.05               # detect charging
EV_TYPES = ["veh_ev"]

OUTPUT_MODEL_LOG = "model_log_data.csv"
OUTPUT_EVSE_LOG = "evse_log_data.csv"

# apply setChargingPower before advancing the simulation step
APPLY_POWER_BEFORE_STEP = True

# how often to flush evse_log to disk during run (0 = only at the end)
EVSE_LOG_FLUSH_INTERVAL = 1000

# ----------------------------------------------------
# INTERNAL STATE
# ----------------------------------------------------

ev_objects = {}                 # veh_id -> ElectricVehicles()
evse_objects = {}               # station_id -> EVSE_class()
charging_start_time = {}        # veh_id -> timestamp
charging_status = {}            # veh_id -> (is_charging, station)
last_soc = {}

charging_stations_cache = {}    # lane_id -> [(cs_id, start, end)]
ev_vehicles = set()
model_log = []
evse_log = []


# ----------------------------------------------------
# RAMP UP FUNCTION
# ----------------------------------------------------

def compute_rampup_power(sim_time, start_time, Prated_kW=MAX_CHARGING_POWER_KW):
    dt = sim_time - start_time
    ramp = min(1.0, dt / RAMPUP_DURATION)
    return Prated_kW * ramp

def simple_charge_curve(ev, dt=10):
    """
    ev: ElectricVehicles-Objekt
    dt: Zeitschritt in Sekunden
    """
    P_max = 50_000  # in W, z.B. 50 kW
    eta = 0.95
    # aktuelle Batteriegröße in Wh
    current_energy = ev.actualBatteryCapacity
    max_energy = ev.batterycapacity_kWh * 1000  # kWh -> Wh

    # Energie, die im Zeitschritt geladen wird
    energy_delta = P_max * dt * eta / 3600  # Wh
    # sicherstellen, dass SOC nicht über Ziel geht
    if current_energy + energy_delta > max_energy * ev.target_soc:
        energy_delta = max_energy * ev.target_soc - current_energy

    ev.actualBatteryCapacity += energy_delta
    return energy_delta



# ----------------------------------------------------
# CHARGING STATION CACHE
# ----------------------------------------------------

def build_charging_station_cache():
    global charging_stations_cache
    charging_stations_cache = {}

    try:
        for cs_id in traci.chargingstation.getIDList():
            lane = traci.chargingstation.getLaneID(cs_id)
            start = traci.chargingstation.getStartPos(cs_id)
            end   = traci.chargingstation.getEndPos(cs_id)

            if lane not in charging_stations_cache:
                charging_stations_cache[lane] = []

            charging_stations_cache[lane].append((cs_id, start, end))

    except traci.TraCIException:
        print("WARN: No charging stations found")


def find_station(veh_id):
    """Lane-based cache with prefix/fallback matching."""
    try:
        lane = traci.vehicle.getLaneID(veh_id)
        if not lane:
            return None

        pos = traci.vehicle.getLanePosition(veh_id)

        # direct match
        if lane in charging_stations_cache:
            for cs_id, start, end in charging_stations_cache[lane]:
                if (start - POSITION_TOLERANCE) <= pos <= (end + POSITION_TOLERANCE):
                    return cs_id

        # prefix match (e.g. cs lane 'edge_0' matches vehicle 'edge_0_0')
        for cs_lane, entries in charging_stations_cache.items():
            if lane.startswith(cs_lane) or cs_lane.startswith(lane):
                for cs_id, start, end in entries:
                    if (start - POSITION_TOLERANCE) <= pos <= (end + POSITION_TOLERANCE):
                        return cs_id

        # fallback: check all stations regardless of lane
        for entries in charging_stations_cache.values():
            for cs_id, start, end in entries:
                if (start - POSITION_TOLERANCE) <= pos <= (end + POSITION_TOLERANCE):
                    return cs_id

    except traci.TraCIException:
        return None

    return None


# ----------------------------------------------------
# MAIN LOOP
# ----------------------------------------------------

def main():
    print("Starting SUMO with config:", SUMO_CONFIG)

    traci.start(["sumo", "-c", SUMO_CONFIG, "--start"])
    build_charging_station_cache()

    start_time = time.time()

    step = 0

    while traci.simulation.getMinExpectedNumber() > 0:
        # DO NOT call traci.simulationStep() here — we'll do it at the end

        sim_time = traci.simulation.getTime()

        # detect EVs
        if step % 10 == 0:
            current_vehicles = set(traci.vehicle.getIDList())
            ev_vehicles.update({
                vid for vid in current_vehicles
                if traci.vehicle.getTypeID(vid) in EV_TYPES
            })

        # count time
        if step % 1000 == 0:
            elapsed = time.time() - start_time
            print(f"Sim time: {sim_time:.1f}s, Elapsed real time: {elapsed:.1f}s")

        # MAIN LOOP FOR EV VEHICLES
        for vid in list(ev_vehicles):
            # ensure these are defined for logging and safe calls
            ramp_kw = 0.0
            allowed_kw = 0.0

            try:
                # get SOC from SUMO
                soc = traci.vehicle.getParameter(vid, "device.battery.actualBatteryCapacity")
                max_soc = traci.vehicle.getParameter(vid, "device.battery.maximumBatteryCapacity")

                if not soc or not max_soc:
                    continue

                soc_val = float(soc) / float(max_soc)

                # Create EV object on first appearance
                if vid not in ev_objects:
                    ev_objects[vid] = ElectricVehicles(
                        vehicle_type="bev",
                        arrival_time=sim_time,
                        initial_soc=soc_val,
                        batterycapacity_kwh=max_soc
                    )
                    print(f"[INIT] New EV: {vid}")

                ev = ev_objects[vid]

                ev.update_soc_from_sumo(float(soc), float(max_soc))

                # detect charging
                speed = traci.vehicle.getSpeed(vid)
                station_id = None
                is_charging = False

                if speed < 0.2:
                    station_id = find_station(vid)
                    if station_id:
                        is_charging = True
                        # removed premature ev.chargevehicle(...) call here;
                        # allowed_kw will be computed once EVSE and server interaction happen below.

                # update charging status
                prev_status = charging_status.get(vid, (False, None))
                charging_status[vid] = (is_charging, station_id)

                # EVSE management
                if is_charging and station_id:

                    # construct EVSE object if not exists
                    if station_id not in evse_objects:
                        evse_objects[station_id] = EVSE_class(
                            efficiency=0.95,
                            Prated_kW=MAX_CHARGING_POWER_KW,
                            evse_id=station_id
                        )

                    evse = evse_objects[station_id]

                    # RAMP UP handling
                    if vid not in charging_start_time:
                        charging_start_time[vid] = sim_time

                    ramp_kw = compute_rampup_power(sim_time, charging_start_time[vid], evse.Prated_kW)

                    # inform EVSE from server (server_setpoint will be ramped)
                    evse.receive_from_server(ramp_kw)

                    # inform EVSE from EV
                    evse.receive_from_ev(
                        Vbatt=ev.packvoltage,
                        Pbatt_kW=ev.packpower / 1000,
                        soc=ev.soc,
                        plugged=True,
                        ready=ev.readytocharge
                    )

                    # EVSE gives allowed power (kW)
                    allowed_kw = evse.send_to_ev()

                    # charge EV in Python model with allowed power
                    ev.chargevehicle(simulationtime=sim_time, dt=1, kw=allowed_kw)

                    # set SUMO charging power (W)
                    w = allowed_kw * 1000
                    traci.chargingstation.setChargingPower(station_id, w)

                    # Debug print when value changes notably
                    prev = evse_log[-1]["allowed_kw"] if evse_log else None
                    if prev is None or abs(allowed_kw - prev) > 0.1:
                        print(f"[EVSE] time={sim_time} veh={vid} station={station_id} ramp_kw={ramp_kw:.2f} allowed_kw={allowed_kw:.2f}")

                    # periodically flush evse_log to disk
                    if EVSE_LOG_FLUSH_INTERVAL and (step % EVSE_LOG_FLUSH_INTERVAL == 0):
                        pd.DataFrame(evse_log).to_csv(OUTPUT_EVSE_LOG, index=False)
                        
                    # log EVSE
                    evse_log.append({
                        "time": sim_time,
                        "veh_id": vid,
                        "station": station_id,
                        "ramp_kw": ramp_kw,
                        "allowed_kw": allowed_kw,
                        "soc": ev.soc
                    })
                else:
                    charging_start_time.pop(vid, None)

                # LOG MODEL DATA
                x, y = traci.vehicle.getPosition(vid)
                model_log.append({
                    "time": sim_time,
                    "veh_id": vid,
                    "x": x,
                    "y": y,
                    "soc": ev.soc,
                    "charging": is_charging,
                    "station": station_id,
                    "energy_delta": ramp_kw
                })

                last_soc[vid] = soc_val

            except traci.TraCIException:
                ev_vehicles.discard(vid)
        
        # NOW advance the simulation ONCE at the end
        traci.simulationStep()
        sim_time = traci.simulation.getTime()  # update sim_time after step
        step += 1
    # ----------------------------------------------------
    # FINISH
    # ----------------------------------------------------

    traci.close()

    runtime = time.time() - start_time
    print("Simulation finished. Runtime:", runtime)

    pd.DataFrame(model_log).to_csv(OUTPUT_MODEL_LOG, index=False)
    pd.DataFrame(evse_log).to_csv(OUTPUT_EVSE_LOG, index=False)

    print("Model log written:", OUTPUT_MODEL_LOG)
    print("EVSE log written:", OUTPUT_EVSE_LOG)


if __name__ == "__main__":
    main()