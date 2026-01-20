import traci
import time
import csv
import xml.etree.ElementTree as ET
import pandas as pd

from ElectricVehicles import ElectricVehicles
from evse_class import EVSE_class, EnergyPool


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

# Global energy pool configuration
MAX_TOTAL_GRID_POWER_KW = 500             # Total available power from grid/source

OUTPUT_CHARGING_LOG = "generated_files/logs/model_log_data.csv"
OUTPUT_EVSE_LOG = "generated_files/logs/evse_log_data.csv"

# apply setChargingPower before advancing the simulation step
APPLY_POWER_BEFORE_STEP = True

# how often to flush evse_log to disk during run (0 = only at the end)
EVSE_LOG_FLUSH_INTERVAL = 1000

# Energy tracking: detect when a charging session ends and log cumulative energy
TRACK_CHARGING_SESSIONS = True

# ----------------------------------------------------
# INTERNAL STATE
# ----------------------------------------------------

# Global energy pool instance
energy_pool = EnergyPool(max_total_power_kw=MAX_TOTAL_GRID_POWER_KW)

ev_objects = {}                 # veh_id -> ElectricVehicles()
evse_objects = {}               # station_id -> EVSE_class()
charging_start_time = {}        # veh_id -> timestamp when charging started
charging_status = {}            # veh_id -> (is_charging, station)
last_soc = {}
charging_session_energy = {}    # veh_id -> accumulated energy in kWh during current session

charging_stations_cache = {}    # lane_id -> [(cs_id, start, end)]
ev_vehicles = set()
car_log = []
evse_log = []
charging_sessions_log = []      # log for complete charging sessions


# ----------------------------------------------------
# RAMP UP FUNCTION
# ----------------------------------------------------

def compute_rampup_power(sim_time, start_time, Prated_kW=MAX_CHARGING_POWER_KW):
    dt = sim_time - start_time
    ramp = min(1.0, dt / RAMPUP_DURATION)
    return Prated_kW * ramp


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


def log_charging_session_end(veh_id, station_id, end_time, energy_kwh, soc_start, soc_end):
    """
    Log a complete charging session when it ends.
    """
    if not TRACK_CHARGING_SESSIONS:
        return
    
    charging_sessions_log.append({
        "veh_id": veh_id,
        "station_id": station_id,
        "end_time": end_time,
        "energy_kwh": energy_kwh,
        "soc_start": soc_start,
        "soc_end": soc_end,
        "duration_sec": 0  # can be calculated from model_log if needed
    })


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

        # Reset energy pool requests at the start of each step
        energy_pool.reset_requests()

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
            total_demand = energy_pool.get_total_requested_power()
            total_usage = energy_pool.get_total_power_usage()
            print(f"Sim time: {sim_time:.1f}s, Elapsed real time: {elapsed:.1f}s")
            print(f"  Energy Pool: Requested={total_demand:.1f}kW, Usage={total_usage:.1f}kW, Limit={MAX_TOTAL_GRID_POWER_KW}kW")

        # MAIN LOOP FOR EV VEHICLES
        for vid in list(ev_vehicles):
            # ensure these are defined for logging and safe calls
            ramp_kw = 0.0
            allowed_kw = 0.0
            energy_kwh_this_step = 0.0
            kWh_delivered = 0.0

            try:
                # get SOC from SUMO
                soc = traci.vehicle.getParameter(vid, "device.battery.actualBatteryCapacity")
                max_soc = traci.vehicle.getParameter(vid, "device.battery.maximumBatteryCapacity")

                if not soc or not max_soc:
                    ev_vehicles.discard(vid)
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

                # update charging status
                prev_status = charging_status.get(vid, (False, None))
                was_charging = prev_status[0]
                prev_station = prev_status[1]

                charging_status[vid] = (is_charging, station_id)

                # EVSE management
                if is_charging and station_id:

                    # construct EVSE object if not exists
                    if station_id not in evse_objects:
                        evse_objects[station_id] = EVSE_class(
                            efficiency=0.95,
                            Prated_kW=MAX_CHARGING_POWER_KW,
                            evse_id=station_id,
                            energy_pool=energy_pool  # Pass global energy pool
                        )

                    evse = evse_objects[station_id]

                    # RAMP UP handling
                    if vid not in charging_start_time:
                        charging_start_time[vid] = sim_time
                        charging_session_energy[vid] = 0.0
                    ramp_kw = compute_rampup_power(sim_time, charging_start_time[vid], evse.Prated_kW)

                    # Register this station's request with the energy pool
                    energy_pool.register_station_request(station_id, ramp_kw)

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

                    # Update energy pool with actual usage
                    energy_pool.update_station_power_usage(station_id, allowed_kw)

                    # charge EV in Python model with allowed power
                    ev.chargevehicle(simulationtime=sim_time, dt=1, kw=allowed_kw)

                    # set SUMO charging power (W)
                    w = allowed_kw * 1000
                    traci.chargingstation.setChargingPower(station_id, w)

                    # Accumulate energy during this session (kWh per second)
                    energy_kwh_this_step = allowed_kw / 3600.0
                    charging_session_energy[vid] = charging_session_energy.get(vid, 0.0) + energy_kwh_this_step

                    # Debug print when value changes notably
                    prev = evse_log[-1]["allowed_kw"] if evse_log else None
                    if prev is None or abs(allowed_kw - prev) > 0.1:
                        total_requested = energy_pool.get_total_requested_power()
                        if total_requested > MAX_TOTAL_GRID_POWER_KW:
                            print(f"[EVSE] time={sim_time} veh={vid} station={station_id} ramp_kw={ramp_kw:.2f} allowed_kw={allowed_kw:.2f} (limited by pool: {total_requested:.1f}kW > {MAX_TOTAL_GRID_POWER_KW}kW)")
                        else:
                            print(f"[EVSE] time={sim_time} veh={vid} station={station_id} ramp_kw={ramp_kw:.2f} allowed_kw={allowed_kw:.2f}")

                    # periodically flush evse_log to disk
                    if EVSE_LOG_FLUSH_INTERVAL and (step % EVSE_LOG_FLUSH_INTERVAL == 0):
                        pd.DataFrame(car_log).to_csv(OUTPUT_CHARGING_LOG, index=False)
                        print(f"EVSE log flushed ${len(car_log)} entries to disk.")
                        car_log.clear()

                else:
                    # Charging session ended
                    if was_charging and vid in charging_start_time:
                        soc_start = last_soc.get(vid, 0.0)
                        soc_end = soc_val
                        total_energy = charging_session_energy.get(vid, 0.0)
                        kWh_delivered = total_energy

                        log_charging_session_end(vid, prev_station, sim_time, total_energy, soc_start, soc_end)
                        
                        if total_energy > 0.01:
                            print(f"[SESSION] veh={vid} station={prev_station} energy={total_energy:.3f} kWh soc:{soc_start:.2f}->{soc_end:.2f}")
                    
                    charging_start_time.pop(vid, None)
                    charging_session_energy.pop(vid, None)


                x, y = traci.vehicle.getPosition(vid)
                car_log.append({
                    "time": sim_time,
                    "veh_id": vid,
                    "speed": speed,
                    "x": x,
                    "y": y,
                    "station": station_id,
                    "allowed_kw": allowed_kw,
                    "ramp_kw": ramp_kw,
                    "energy": kWh_delivered,
                    "soc": ev.soc,
                    "edge_id": traci.vehicle.getRoadID(vid),
                    "is_charging": is_charging
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

    pd.DataFrame(car_log).to_csv(OUTPUT_CHARGING_LOG, index=False)
    
    if charging_sessions_log:
        pd.DataFrame(charging_sessions_log).to_csv("generated_files/logs/charging_sessions.csv", index=False)
        print("Charging sessions log written: generated_files/logs/charging_sessions.csv")

    print("Model log written:", OUTPUT_CHARGING_LOG)


if __name__ == "__main__":
    main()