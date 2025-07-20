import traci
import csv

sumo_cfg = "generated_files/osm.sumocfg"
output_csv = "ev_soc_tracking.csv"

sumo_cmd = ["sumo-gui", "-c", sumo_cfg, "--start"]
traci.start(sumo_cmd)

last_soc = {}

# Definiere die EV-Typen, wie sie in deiner Simulation verwendet werden
EV_TYPES = ["veh_ev"]  # Passe diese Liste ggf. an

with open(output_csv, "w", newline="") as csvfile:
    writer = csv.writer(csvfile)
    writer.writerow(["time", "vehicle_id", "soc_percent"])

    while traci.simulation.getMinExpectedNumber() > 0:
        traci.simulationStep()
        time = traci.simulation.getTime()
        for veh_id in traci.vehicle.getIDList():
            try:
                vtype = traci.vehicle.getTypeID(veh_id)
                if vtype not in EV_TYPES:
                    continue  # Überspringe Nicht-EVs

                soc = traci.vehicle.getParameter(veh_id, "device.battery.actualBatteryCapacity")
                max_soc = traci.vehicle.getParameter(veh_id, "device.battery.maximumBatteryCapacity")
                if soc and max_soc:
                    soc_percent = 100 * float(soc) / float(max_soc)

                    # Farbe je nach SoC setzen
                    if soc_percent == 0:
                        color = (0, 0, 0, 255)  # schwarz
                    elif soc_percent <= 10:
                        color = (255, 0, 0, 255)  # rot
                    elif soc_percent <= 30:
                        color = (255, 165, 0, 255)  # orange
                    elif soc_percent > 50:
                        color = (0, 255, 0, 255)  # grün
                    else:
                        color = (255, 255, 0, 255)  # gelb (optional)

                    traci.vehicle.setColor(veh_id, color)
                    # Prüfen, ob sich der SoC geändert hat
                    if veh_id not in last_soc or abs(last_soc[veh_id] - soc_percent) > 1e-6:
                        print(f"[t={time:.1f}s] {veh_id}: SoC = {soc_percent:.2f}%")
                        last_soc[veh_id] = soc_percent
                    writer.writerow([time, veh_id, soc_percent])
            except traci.TraCIException:
                continue

traci.close()
print(f"Tracking abgeschlossen. Ergebnisse in {output_csv}")