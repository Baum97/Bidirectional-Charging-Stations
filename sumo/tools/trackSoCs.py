import traci
import csv

sumo_cfg = "generated_files/osm.sumocfg"
output_csv = "ev_soc_tracking.csv"

sumo_cmd = ["sumo-gui", "-c", sumo_cfg, "--start"]
traci.start(sumo_cmd)

last_soc = {}

with open(output_csv, "w", newline="") as csvfile:
    writer = csv.writer(csvfile)
    writer.writerow(["time", "vehicle_id", "soc_percent"])

    while traci.simulation.getMinExpectedNumber() > 0:
        traci.simulationStep()
        time = traci.simulation.getTime()
        for veh_id in traci.vehicle.getIDList():
            try:
                soc = traci.vehicle.getParameter(veh_id, "device.battery.actualBatteryCapacity")
                max_soc = traci.vehicle.getParameter(veh_id, "device.battery.maximumBatteryCapacity")
                if soc and max_soc:
                    soc_percent = 100 * float(soc) / float(max_soc)
                    # Prüfen, ob sich der SoC geändert hat
                    if veh_id not in last_soc or abs(last_soc[veh_id] - soc_percent) > 1e-6:
                        print(f"[t={time:.1f}s] {veh_id}: SoC = {soc_percent:.2f}%")
                        last_soc[veh_id] = soc_percent
                    writer.writerow([time, veh_id, soc_percent])
            except traci.TraCIException:
                continue

traci.close()
print(f"Tracking abgeschlossen. Ergebnisse in {output_csv}")