def seconds_to_time(seconds):
    """Konvertiert Sekunden zu HH:MM:SS Format"""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"

def create_areas_mapping(network_file="esslingen.net.xml"):
    """
    Erstellt eine Zuordnung von Bereichen zu echten Edges im Netzwerk
    """
    print("Analysiere Netzwerk für Bereichszuordnung...")
    
    try:
        tree = ET.parse(network_file)
        root = tree.getroot()
        
        # Alle Edges sammeln
        edges = []
        for edge in root.findall('.//edge'):
            edge_id = edge.get('id')
            if edge_id and not edge_id.startswith(':'):  # Keine internen Edges
                edges.append(edge_id)
        
        if len(edges) < 3:
            print("Warnung: Weniger als 3 Edges gefunden. Verwende Standard-Bereiche.")
            return {
                'home_area': edges[0] if edges else 'edge_1',
                'work_area': edges[1] if len(edges) > 1 else 'edge_2', 
                'leisure_area': edges[2] if len(edges) > 2 else 'edge_3'
            }
        
        # Zufällige Auswahl für verschiedene Bereiche
        random.shuffle(edges)
        num_edges = len(edges)
        
        areas = {
            'home_area': edges[:num_edges//3],      # Erstes Drittel für Wohnen
            'work_area': edges[num_edges//3:2*num_edges//3],  # Zweites Drittel für Arbeit
            'leisure_area': edges[2*num_edges//3:]   # Letztes Drittel für Freizeit
        }
        
        print(f"Bereiche erstellt: {len(areas['home_area'])} Wohn-, {len(areas['work_area'])} Arbeits-, {len(areas['leisure_area'])} Freizeitbereiche")
        return areas
        
    except Exception as e:
        print(f"Fehler beim Lesen des Netzwerks: {e}")
        print("Verwende Standard-Bereiche...")
        return {
            'home_area': ['edge_1', 'edge_2'],
            'work_area': ['edge_3', 'edge_4'],
            'leisure_area': ['edge_5', 'edge_6']
        }

def create_sumo_routes_with_real_edges(num_persons=40, network_file="esslingen.net.xml", output_file="7day_esslingen.rou.xml"):
    """
    Erstellt SUMO-Routes mit echten Edges aus dem Netzwerk
    """
    print(f"Erstelle SUMO Routes mit echten Netzwerk-Edges für {num_persons} Personen...")
    
    # Bereiche aus Netzwerk laden
    areas = create_areas_mapping(network_file)
    
    # Root element für SUMO routes
    root = ET.Element("routes")
    
    # Vehicle Type definieren
    vtype = ET.SubElement(root, "vType", id="car", accel="2.6", decel="4.5", 
                         sigma="0.5", length="5", minGap="2.5", maxSpeed="50")
    
    # Für jede Person
    for person_id in range(1, num_persons + 1):
        # Zufällige Bereiche für diese Person zuweisen
        home_edges = areas['home_area'] 
        work_edges = areas['work_area']
        leisure_edges = areas['leisure_area']
        
        # Wochenpläne für jede Person
        for day in range(7):
            day_name = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"][day]
            
            if day < 5:  # Werktag
                create_weekday_routes_real(root, person_id, day, day_name, home_edges, work_edges)
            else:  # Wochenende  
                create_weekend_routes_real(root, person_id, day, day_name, home_edges, leisure_edges)
    
    # XML schreiben
    tree = ET.ElementTree(root)
    ET.indent(tree, space="  ")
    
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n')
        tree.write(f, encoding='unicode', xml_declaration=False)
    
    print(f"SUMO Routes mit echten Edges erstellt: {output_file}")
    return output_file

def create_weekday_routes_real(root, person_id, day, day_name, home_edges, work_edges):
    """Erstellt Werktag-Routen mit echten Edges"""
    
    # Zufällige Zeiten
    work_start_hour = random.randint(7, 9)
    work_end_hour = random.randint(16, 18)
    
    # Basis-Zeit für den Tag (in Sekunden seit Simulationsstart)
    day_offset = day * 24 * 3600
    
    # Zufällige Edge-Auswahl
    home_edge = random.choice(home_edges)
    work_edge = random.choice(work_edges)
    
    # Route zur Arbeit (Morgens)
    depart_time = day_offset + work_start_hour * 3600 + random.randint(0, 1800)  # +/- 30min
    route_to_work = ET.SubElement(root, "trip", 
                                 id=f"person{person_id}_{day_name}_to_work",
                                 type="car",
                                 depart=str(depart_time),
                                 **{"from": home_edge, "to": work_edge})
    
    # Route nach Hause (Abends)
    return_time = day_offset + work_end_hour * 3600 + random.randint(0, 1800)  # +/- 30min
    route_home = ET.SubElement(root, "trip",
                              id=f"person{person_id}_{day_name}_home",
                              type="car", 
                              depart=str(return_time),
                              **{"from": work_edge, "to": home_edge})

def create_weekend_routes_real(root, person_id, day, day_name, home_edges, leisure_edges):
    """Erstellt Wochenend-Routen mit echten Edges"""
    
    # Späteren Start am Wochenende
    leisure_start_hour = random.randint(10, 12)
    leisure_end_hour = random.randint(15, 17)
    
    # Basis-Zeit für den Tag
    day_offset = day * 24 * 3600
    
    # Zufällige Edge-Auswahl
    home_edge = random.choice(home_edges)
    leisure_edge = random.choice(leisure_edges)
    
    # Route zu Freizeitaktivität
    depart_time = day_offset + leisure_start_hour * 3600 + random.randint(0, 1800)
    route_to_leisure = ET.SubElement(root, "trip",
                                   id=f"person{person_id}_{day_name}_to_leisure", 
                                   type="car",
                                   depart=str(depart_time),
                                   **{"from": home_edge, "to": leisure_edge})
    
    # Route nach Hause
    return_time = day_offset + leisure_end_hour * 3600 + random.randint(0, 1800)
    route_home = ET.SubElement(root, "trip",
                              id=f"person{person_id}_{day_name}_home",
                              type="car",
                              depart=str(return_time), 
                              **{"from": leisure_edge, "to": home_edge})#!/usr/bin/env python3
"""
Script to generate weekly MATSim plans.xml with different patterns for weekdays/weekends
Korrigiert für bessere SUMO-Kompatibilität + direkter SUMO Routes Export
"""

import xml.etree.ElementTree as ET
import random
import subprocess
import os

def create_weekly_plan_xml(num_persons=100, output_file="7day_plan.xml"):
    """
    Erstellt eine wöchentliche MATSim plan.xml mit unterschiedlichen Mustern
    """
    
    # Zeitkonstanten (in Sekunden)
    DAY_SECONDS = 24 * 3600  # 86400
    WEEK_SECONDS = 7 * DAY_SECONDS  # 604800
    
    # Wochentage definieren
    WEEKDAYS = {
        0: "Monday", 1: "Tuesday", 2: "Wednesday", 3: "Thursday", 4: "Friday",
        5: "Saturday", 6: "Sunday"
    }
    
    root = ET.Element("population")
    
    for person_id in range(1, num_persons + 1):
        person = ET.SubElement(root, "person", id=f"person{person_id}")
        
        # Person Attribute
        attributes = ET.SubElement(person, "attributes")
        attr = ET.SubElement(attributes, "attribute", 
                           name="subpopulation", 
                           **{"class": "java.lang.String"})
        attr.text = "person"
        
        # Plan für die gesamte Woche
        plan = ET.SubElement(person, "plan", selected="yes")
        
        # Realistischere Koordinaten für Esslingen (ungefähr)
        # Esslingen liegt bei etwa: 48.7° N, 9.3° E
        # In UTM-Koordinaten (Zone 32N): ca. 520000, 5395000
        home_x = random.uniform(515000, 525000)
        home_y = random.uniform(5390000, 5400000)
        
        work_x = random.uniform(515000, 525000)
        work_y = random.uniform(5390000, 5400000)
        
        leisure_x = random.uniform(515000, 525000)
        leisure_y = random.uniform(5390000, 5400000)
        
        # Vereinfachte Link-IDs (sollten im Netzwerk existieren)
        home_link = f"home_{person_id}"
        work_link = f"work_{person_id}"
        leisure_link = f"leisure_{person_id}"
        
        # Für jeden Tag der Woche
        for day in range(7):
            day_start_time = day * DAY_SECONDS
            
            if day < 5:  # Montag bis Freitag (Werktage)
                create_weekday_activities(plan, day_start_time, home_x, home_y, home_link,
                                        work_x, work_y, work_link, day == 6)  # letzter Tag?
            else:  # Samstag und Sonntag (Wochenende)
                create_weekend_activities(plan, day_start_time, home_x, home_y, home_link,
                                        leisure_x, leisure_y, leisure_link, day == 6)  # letzter Tag?
    
    # XML schreiben mit korrekter Formatierung
    tree = ET.ElementTree(root)
    ET.indent(tree, space="  ")
    
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n')
        f.write('<!DOCTYPE population SYSTEM "http://www.matsim.org/files/dtd/population_v6.dtd">\n\n')
        tree.write(f, encoding='unicode', xml_declaration=False)
    
    print(f"Wöchentliche Plan.xml mit {num_persons} Personen erstellt: {output_file}")

def create_weekday_activities(plan, day_start, home_x, home_y, home_link, 
                            work_x, work_y, work_link, is_last_day):
    """Erstellt Werktag-Aktivitäten"""
    
    # Zufällige Zeiten für diesen Tag
    work_start = random.randint(7, 9)  # 7-9 Uhr
    work_end = random.randint(16, 18)  # 16-18 Uhr
    
    # Home Activity (Morgens)
    start_time = day_start + work_start * 3600
    home_morning = ET.SubElement(plan, "activity",
                               type="home",
                               link_id=str(home_link),
                               x=str(home_x),
                               y=str(home_y),
                               end_time=seconds_to_time(start_time))
    
    # Leg zur Arbeit
    leg_to_work = ET.SubElement(plan, "leg", mode="car")
    
    # Work Activity
    end_time = day_start + work_end * 3600
    work_activity = ET.SubElement(plan, "activity",
                                type="work",
                                link_id=str(work_link),
                                x=str(work_x),
                                y=str(work_y),
                                end_time=seconds_to_time(end_time))
    
    # Leg nach Hause
    leg_home = ET.SubElement(plan, "leg", mode="car")
    
    # Home Activity (Abends) - nur end_time wenn nicht letzter Tag
    home_attrs = {
        "type": "home",
        "link_id": str(home_link),
        "x": str(home_x),
        "y": str(home_y)
    }
    if not is_last_day:
        # Nächster Tag beginnt um Mitternacht
        home_attrs["end_time"] = seconds_to_time(day_start + 24 * 3600)
    
    home_evening = ET.SubElement(plan, "activity", **home_attrs)

def create_weekend_activities(plan, day_start, home_x, home_y, home_link,
                            leisure_x, leisure_y, leisure_link, is_last_day):
    """Erstellt Wochenend-Aktivitäten"""
    
    # Längeres Ausschlafen am Wochenende
    leisure_start = random.randint(10, 12)  # 10-12 Uhr
    leisure_end = random.randint(15, 17)    # 15-17 Uhr
    
    # Home Activity (Morgens, länger)
    start_time = day_start + leisure_start * 3600
    home_morning = ET.SubElement(plan, "activity",
                               type="home",
                               link_id=str(home_link),
                               x=str(home_x),
                               y=str(home_y),
                               end_time=seconds_to_time(start_time))
    
    # Leg zu Freizeitaktivität
    leg_to_leisure = ET.SubElement(plan, "leg", mode="car")
    
    # Leisure Activity (Shopping, Sport, etc.)
    activity_type = random.choice(["shopping", "leisure", "sport", "visit"])
    end_time = day_start + leisure_end * 3600
    leisure_activity = ET.SubElement(plan, "activity",
                                   type=activity_type,
                                   link_id=str(leisure_link),
                                   x=str(leisure_x),
                                   y=str(leisure_y),
                                   end_time=seconds_to_time(end_time))
    
    # Leg nach Hause
    leg_home = ET.SubElement(plan, "leg", mode="car")
    
    # Home Activity (Abends)
    home_attrs = {
        "type": "home",
        "link_id": str(home_link),
        "x": str(home_x),
        "y": str(home_y)
    }
    if not is_last_day:
        home_attrs["end_time"] = seconds_to_time(day_start + 24 * 3600)
    
    home_evening = ET.SubElement(plan, "activity", **home_attrs)

def create_sumo_routes_directly(num_persons=40, network_file="esslingen.net.xml", output_file="7day_esslingen.rou.xml"):
    """
    Erstellt direkt SUMO-Routes ohne MATSim-Zwischenschritt
    """
    print(f"Erstelle SUMO Routes direkt für {num_persons} Personen...")
    
    # Root element für SUMO routes
    root = ET.Element("routes", xmlns="http://sumo.dlr.de/xsd/routes_file.xsd")
    
    # Vehicle Type definieren
    vtype = ET.SubElement(root, "vType", id="car", accel="2.6", decel="4.5", 
                         sigma="0.5", length="5", minGap="2.5", maxSpeed="70")
    
    # Für jede Person
    for person_id in range(1, num_persons + 1):
        # Wochenpläne für jede Person
        for day in range(7):
            day_name = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"][day]
            
            if day < 5:  # Werktag
                create_weekday_routes(root, person_id, day, day_name)
            else:  # Wochenende  
                create_weekend_routes(root, person_id, day, day_name)
    
    # XML schreiben
    tree = ET.ElementTree(root)
    ET.indent(tree, space="  ")
    
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n\n')
        tree.write(f, encoding='unicode', xml_declaration=False)
    
    print(f"SUMO Routes erstellt: {output_file}")
    return output_file

def create_weekday_routes(root, person_id, day, day_name):
    """Erstellt Werktag-Routen direkt für SUMO"""
    
    # Zufällige Zeiten
    work_start_hour = random.randint(7, 9)
    work_end_hour = random.randint(16, 18)
    
    # Basis-Zeit für den Tag (in Sekunden seit Simulationsstart)
    day_offset = day * 24 * 3600
    
    # Route zur Arbeit (Morgens)
    depart_time = day_offset + work_start_hour * 3600 + random.randint(0, 1800)  # +/- 30min
    route_to_work = ET.SubElement(root, "trip", 
                                 id=f"person{person_id}_{day_name}_to_work",
                                 type="car",
                                 depart=str(depart_time),
                                 **{"from": f"home_area", "to": f"work_area"})
    
    # Route nach Hause (Abends)
    return_time = day_offset + work_end_hour * 3600 + random.randint(0, 1800)  # +/- 30min
    route_home = ET.SubElement(root, "trip",
                              id=f"person{person_id}_{day_name}_home",
                              type="car", 
                              depart=str(return_time),
                              **{"from": f"work_area", "to": f"home_area"})

def create_weekend_routes(root, person_id, day, day_name):
    """Erstellt Wochenend-Routen direkt für SUMO"""
    
    # Späteren Start am Wochenende
    leisure_start_hour = random.randint(10, 12)
    leisure_end_hour = random.randint(15, 17)
    
    # Basis-Zeit für den Tag
    day_offset = day * 24 * 3600
    
    # Route zu Freizeitaktivität
    depart_time = day_offset + leisure_start_hour * 3600 + random.randint(0, 1800)
    route_to_leisure = ET.SubElement(root, "trip",
                                   id=f"person{person_id}_{day_name}_to_leisure", 
                                   type="car",
                                   depart=str(depart_time),
                                   **{"from": f"home_area", "to": f"leisure_area"})
    
    # Route nach Hause
    return_time = day_offset + leisure_end_hour * 3600 + random.randint(0, 1800)
    route_home = ET.SubElement(root, "trip",
                              id=f"person{person_id}_{day_name}_home",
                              type="car",
                              depart=str(return_time), 
                              **{"from": f"leisure_area", "to": f"home_area"})

if __name__ == "__main__":
    print("=== 7-Tage SUMO Routes Generator ===\n")
    
    # Option 1: Direkte SUMO Routes mit echten Netzwerk-Edges (EMPFOHLEN)
    print("Erstelle SUMO Routes direkt mit echten Netzwerk-Edges...")
    network_file = "esslingen.net.xml"  # Passen Sie den Namen an
    
    if os.path.exists(network_file):
        create_sumo_routes_with_real_edges(num_persons=40, 
                                         network_file=network_file, 
                                         output_file="7day_esslingen.rou.xml")
        print(f"\n✅ Fertig! Die Datei '7day_esslingen.rou.xml' wurde erstellt.")
        print("Sie können diese direkt in SUMO verwenden.")
    else:
        print(f"❌ Netzwerkdatei '{network_file}' nicht gefunden!")
        print("Bitte passen Sie den Dateinamen in der Zeile 'network_file = ...' an.")
    
    # Option 2: Fallback - MATSim Plans (falls Sie das MATSim-Tool trotzdem verwenden möchten)
    print(f"\n--- Alternative: MATSim Plans ---")
    create_weekly_plan_xml(num_persons=40, output_file="7day_plan.xml")
    print("Falls Sie trotzdem MATSim verwenden möchten:")
    print('py "C:\\Program Files (x86)\\Eclipse\\Sumo\\tools\\import\\matsim\\matsim_importPlans.py" --plan-file 7day_plan.xml --net-file esslingen.net.xml -o 7day_esslingen_matsim.rou.xml')