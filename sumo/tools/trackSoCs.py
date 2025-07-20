import traci
import csv

sumo_cfg = "generated_files/osm.sumocfg"
output_csv = "ev_soc_tracking.csv"

sumo_cmd = ["sumo-gui", "-c", sumo_cfg, "--start"]
traci.start(sumo_cmd)

last_soc = {}
charging_status = {}  # vehicle_id -> (is_charging, station_id)
EV_TYPES = ["veh_ev"]

with open(output_csv, "w", newline="") as csvfile:
    writer = csv.writer(csvfile)
    writer.writerow(["time", "vehicle_id", "soc_percent", "is_charging", "station_id"])

    step_counter = 0
    
    while traci.simulation.getMinExpectedNumber() > 0:
        traci.simulationStep()
        time = traci.simulation.getTime()
        step_counter += 1
        
        # Alle EV-Fahrzeuge durchgehen
        for veh_id in traci.vehicle.getIDList():
            try:
                vtype = traci.vehicle.getTypeID(veh_id)
                if vtype not in EV_TYPES:
                    continue

                # Battery Status abrufen
                soc = traci.vehicle.getParameter(veh_id, "device.battery.actualBatteryCapacity")
                max_soc = traci.vehicle.getParameter(veh_id, "device.battery.maximumBatteryCapacity")
                
                if not (soc and max_soc):
                    continue
                    
                soc_percent = 100 * float(soc) / float(max_soc)
                
                # CHARGING STATUS ERKENNEN - Mehrere Methoden:
                is_charging = False
                station_id = None
                
                # Methode 1: Direkte Abfrage ob Fahrzeug lädt
                try:
                    charging_power = float(traci.vehicle.getParameter(veh_id, "device.battery.chargingStationPower"))
                    if charging_power > 0:
                        is_charging = True
                        print(f"*** LADEN *** [t={time:.1f}s] {veh_id} lädt mit {charging_power}W")
                except:
                    charging_power = 0
                
                # Methode 2: Position an Charging Station prüfen
                if not is_charging:
                    try:
                        current_lane = traci.vehicle.getLaneID(veh_id)
                        veh_pos = traci.vehicle.getLanePosition(veh_id)
                        speed = traci.vehicle.getSpeed(veh_id)
                        
                        # Prüfe alle Charging Stations
                        for cs_id in traci.chargingstation.getIDList():
                            try:
                                cs_lane = traci.chargingstation.getLaneID(cs_id)
                                if cs_lane == current_lane:
                                    cs_start = traci.chargingstation.getStartPos(cs_id)
                                    cs_end = traci.chargingstation.getEndPos(cs_id)
                                    
                                    # Fahrzeug steht in der Station?
                                    if cs_start <= veh_pos <= cs_end and speed < 0.5:
                                        is_charging = True
                                        station_id = cs_id
                                        print(f"*** POSITION LADEN *** [t={time:.1f}s] {veh_id} steht an Station {cs_id}")
                                        break
                            except:
                                continue
                    except:
                        pass
                
                # Methode 3: SoC steigt = lädt
                if not is_charging and veh_id in last_soc:
                    soc_diff = soc_percent - last_soc[veh_id]
                    if soc_diff > 0.1:  # SoC steigt um mehr als 0.1%
                        is_charging = True
                        print(f"*** SOC STEIGT *** [t={time:.1f}s] {veh_id} lädt (SoC +{soc_diff:.2f}%)")
                
                # Methode 4: Vehicle Stops prüfen
                if not is_charging:
                    try:
                        stops = traci.vehicle.getStops(veh_id)
                        for stop in stops:
                            if hasattr(stop, 'chargingStation') and stop.chargingStation:
                                # Fahrzeug hat Charging Stop
                                if traci.vehicle.getSpeed(veh_id) < 0.1:
                                    is_charging = True
                                    station_id = stop.chargingStation
                                    print(f"*** STOP LADEN *** [t={time:.1f}s] {veh_id} lädt an Stop {station_id}")
                                break
                    except:
                        pass
                
                # Status-Änderung ausgeben
                prev_status = charging_status.get(veh_id, (False, None))
                if is_charging != prev_status[0]:
                    if is_charging:
                        print(f"LADEN BEGONNEN: {veh_id} (SoC: {soc_percent:.1f}%) an Station {station_id}")
                    else:
                        print(f"LADEN BEENDET: {veh_id} (SoC: {soc_percent:.1f}%)")
                
                charging_status[veh_id] = (is_charging, station_id)
                
                # CSV schreiben
                writer.writerow([time, veh_id, soc_percent, is_charging, station_id or ""])
                
                # Fahrzeugfarbe setzen
                if is_charging:
                    color = (0, 255, 255, 255)  # Cyan = lädt
                elif soc_percent == 0:
                    color = (0, 0, 0, 255)      # Schwarz = leer
                elif soc_percent <= 10:
                    color = (255, 0, 0, 255)    # Rot = sehr niedrig
                elif soc_percent <= 30:
                    color = (255, 165, 0, 255)  # Orange = niedrig
                else:
                    color = (0, 255, 0, 255)    # Grün = ok
                
                traci.vehicle.setColor(veh_id, color)
                
                # SoC für nächste Iteration speichern
                last_soc[veh_id] = soc_percent
                
                # Periodische Ausgabe für alle EVs
                if step_counter % 100 == 0:
                    status_text = "LÄDT" if is_charging else "fährt"
                    print(f"[t={time:.1f}s] {veh_id}: {soc_percent:.1f}% - {status_text}")
                    
            except traci.TraCIException as e:
                # print(f"TraCI Fehler für {veh_id}: {e}")
                continue
            except Exception as e:
                # print(f"Allgemeiner Fehler für {veh_id}: {e}")
                continue

        # Alle 500 Steps: Zusammenfassung
        if step_counter % 500 == 0:
            charging_count = sum(1 for status in charging_status.values() if status[0])
            total_evs = len([v for v in traci.vehicle.getIDList() if traci.vehicle.getTypeID(v) in EV_TYPES])