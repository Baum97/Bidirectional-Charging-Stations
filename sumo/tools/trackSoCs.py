import traci
import csv

sumo_cfg = "generated_files/osm.sumocfg"
output_csv = "ev_soc_tracking.csv"

sumo_cmd = ["sumo-gui", "-c", sumo_cfg, "--start"]
traci.start(sumo_cmd)

# Cache für Performance-Optimierung
charging_stations_cache = {}  # lane_id -> [(cs_id, start_pos, end_pos), ...]
last_soc = {}
charging_status = {}
charging_count = 0
charge_entries = {}
EV_TYPES = ["veh_ev"]

# PERFORMANCE-EINSTELLUNGEN
TRACKING_INTERVAL = 10  # Nur jede 10 Schritte tracken (anstatt jeden Schritt)
POSITION_TOLERANCE = 1.0  # Großzügigere Position-Toleranz
SOC_CHANGE_THRESHOLD = 0.05  # Größerer Schwellenwert für SoC-Änderung

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
        
        # Prüfe nur Stationen auf der aktuellen Spur (aus Cache)
        if current_lane in charging_stations_cache:
            veh_pos = traci.vehicle.getLanePosition(veh_id)
            
            for cs_id, cs_start, cs_end in charging_stations_cache[current_lane]:
                if (cs_start - POSITION_TOLERANCE) <= veh_pos <= (cs_end + POSITION_TOLERANCE):
                    return cs_id
    except traci.TraCIException:
        pass
    
    return None

# Cache aufbauen
build_charging_stations_cache()

with open(output_csv, "w", newline="") as csvfile:
    writer = csv.writer(csvfile)
    writer.writerow(["time", "vehicle_id", "soc_percent", "is_charging", "station_id"])
    step_counter = 0
    ev_vehicles = set()  # Cache für EV-Fahrzeuge
    
    while traci.simulation.getMinExpectedNumber() > 0:
        traci.simulationStep()
        time = traci.simulation.getTime()
        step_counter += 1
        
        # NUR JEDE X SCHRITTE TRACKEN (große Performance-Verbesserung!)
        if step_counter % TRACKING_INTERVAL != 0:
            continue
        
        # EV-Fahrzeuge-Cache aktualisieren (nur alle 50 Schritte)
        if step_counter % 50 == 0:
            current_vehicles = set(traci.vehicle.getIDList())
            # Entferne nicht mehr existierende Fahrzeuge
            ev_vehicles = ev_vehicles.intersection(current_vehicles)
            
            # Füge neue EVs hinzu
            for veh_id in current_vehicles - ev_vehicles:
                try:
                    vtype = traci.vehicle.getTypeID(veh_id)
                    if vtype in EV_TYPES:
                        ev_vehicles.add(veh_id)
                except traci.TraCIException:
                    continue
        
        # Nur bekannte EV-Fahrzeuge verarbeiten
        for veh_id in list(ev_vehicles):  # Liste erstellen für sichere Iteration
            try:
                # Schnelle Überprüfung ob Fahrzeug noch existiert
                try:
                    soc = traci.vehicle.getParameter(veh_id, "device.battery.actualBatteryCapacity")
                    max_soc = traci.vehicle.getParameter(veh_id, "device.battery.maximumBatteryCapacity")
                except traci.TraCIException:
                    ev_vehicles.discard(veh_id)  # Fahrzeug entfernen
                    continue
                    
                if not soc or not max_soc:
                    continue
                    
                soc_percent = 100 * float(soc) / float(max_soc)
                
                # Lade-Erkennung (vereinfacht für Performance)
                is_charging = False
                station_id = None
                
                # Methode 1: Position und Geschwindigkeit (mit Cache)
                speed = traci.vehicle.getSpeed(veh_id)
                if speed < 0.2:  # Steht relativ still
                    station_id = find_charging_station_for_vehicle_fast(veh_id)
                    
                    if station_id:
                        # Prüfe SoC-Änderung nur wenn an Station
                        if veh_id in last_soc:
                            soc_diff = soc_percent - last_soc[veh_id]
                            if soc_diff > SOC_CHANGE_THRESHOLD:  # SoC steigt deutlich
                                is_charging = True
                        else:
                            is_charging = True  # Erste Messung, nehme an dass geladen wird
                
                # Status-Änderung ausgeben (nur bei Änderung)
                prev_status = charging_status.get(veh_id, (False, None))             
                charging_status[veh_id] = (is_charging, station_id)
                
                # CSV schreiben (nur bei Änderungen oder alle 100 Schritte)
                if (is_charging != prev_status[0]) or (step_counter % 100 == 0):
                    writer.writerow([time, veh_id, soc_percent, is_charging, station_id or ""])
                
                # Fahrzeugfarbe setzen (nur bei Status-Änderung)
                if is_charging != prev_status[0]:
                    if is_charging:
                        color = (0, 255, 255, 255)  # Cyan = lädt
                    elif soc_percent <= 10:
                        color = (255, 0, 0, 255)    # Rot = niedrig
                    elif soc_percent <= 30:
                        color = (255, 165, 0, 255)  # Orange = mittel
                    else:
                        color = (0, 255, 0, 255)    # Grün = ok
                    
                    try:
                        traci.vehicle.setColor(veh_id, color)
                    except traci.TraCIException:
                        pass  # Fahrzeug möglicherweise nicht mehr da
                
                last_soc[veh_id] = soc_percent
                    
            except (traci.TraCIException, ValueError, TypeError):
                ev_vehicles.discard(veh_id)  # Fahrzeug entfernen bei Fehlern
                continue

        # Reduzierte Status-Ausgabe (nur alle 1000 Schritte)
        if step_counter % 1000 == 0:
            charging_count = sum(1 for status in charging_status.values() if status[0])
            print(f"[t={time:.0f}s] {charging_count}/{len(ev_vehicles)} EVs laden gerade")

    # Ladezählung speichern
    with open("logCharges.csv", mode="w", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(["CS_id", "charges"])
        for station_id, charge_count in charge_entries.items():
            writer.writerow([station_id, charge_count])

traci.close()
print("Simulation beendet.")