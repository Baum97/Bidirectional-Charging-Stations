#!/usr/bin/env python3
"""
Script to generate weekly MATSim plans.xml with different patterns for weekdays/weekends
"""

import xml.etree.ElementTree as ET
import random

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
        plan = ET.SubElement(person, "plan")
        
        # Zufällige Person-spezifische Daten
        home_x = random.uniform(0, 1000)
        home_y = random.uniform(0, 1000)
        home_link = random.randint(1, 50)
        
        work_x = random.uniform(0, 1000)
        work_y = random.uniform(0, 1000)
        work_link = random.randint(51, 100)
        
        leisure_x = random.uniform(0, 1000)
        leisure_y = random.uniform(0, 1000)
        leisure_link = random.randint(101, 150)
        
        # Für jeden Tag der Woche
        for day in range(7):
            day_start_time = day * DAY_SECONDS
            
            if day < 5:  # Montag bis Freitag (Werktage)
                create_weekday_activities(plan, day_start_time, home_x, home_y, home_link,
                                        work_x, work_y, work_link, day == 6)  # letzter Tag?
            else:  # Samstag und Sonntag (Wochenende)
                create_weekend_activities(plan, day_start_time, home_x, home_y, home_link,
                                        leisure_x, leisure_y, leisure_link, day == 6)  # letzter Tag?
    
    # XML schreiben
    tree = ET.ElementTree(root)
    ET.indent(tree, space="    ")
    
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n')
        f.write('<!DOCTYPE population SYSTEM "http://www.matsim.org/files/dtd/population_v6.dtd">\n')
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
    leg_to_work = ET.SubElement(plan, "leg",
                              mode="car",
                              dep_time=seconds_to_time(start_time))
    add_routing_mode(leg_to_work, "car")
    
    # Work Activity
    end_time = day_start + work_end * 3600
    work_activity = ET.SubElement(plan, "activity",
                                type="work",
                                link_id=str(work_link),
                                x=str(work_x),
                                y=str(work_y),
                                end_time=seconds_to_time(end_time))
    
    # Leg nach Hause
    leg_home = ET.SubElement(plan, "leg",
                           mode="car",
                           dep_time=seconds_to_time(end_time))
    add_routing_mode(leg_home, "car")
    
    # Home Activity (Abends) - nur end_time wenn nicht letzter Tag
    home_attrs = {
        "type": "home",
        "link_id": str(home_link),
        "x": str(home_x),
        "y": str(home_y)
    }
    if not is_last_day:
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
    leg_to_leisure = ET.SubElement(plan, "leg",
                                 mode="car",
                                 dep_time=seconds_to_time(start_time))
    add_routing_mode(leg_to_leisure, "car")
    
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
    leg_home = ET.SubElement(plan, "leg",
                           mode="car",
                           dep_time=seconds_to_time(end_time))
    add_routing_mode(leg_home, "car")
    
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

def add_routing_mode(leg_element, mode):
    """Fügt routing mode zu leg hinzu"""
    attributes = ET.SubElement(leg_element, "attributes")
    attr = ET.SubElement(attributes, "attribute",
                       name="routingMode",
                       **{"class": "java.lang.String"})
    attr.text = mode

def seconds_to_time(seconds):
    """Konvertiert Sekunden zu HH:MM:SS Format"""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"

if __name__ == "__main__":
    # Wöchentliche Plan erstellen
    create_weekly_plan_xml(num_persons=50, output_file="7day_plan.xml")
    print("Führen Sie dann aus:")
    print('py "C:\\Program Files (x86)\\Eclipse\\Sumo\\tools\\import\\matsim\\matsim_importPlans.py" --plan-file 7day_esslingen.xml -o 7day_esslingen.rou.xml')