import xml.etree.ElementTree as ET
import pandas as pd
import sys

def main(input_file, output_file):
    residential_buildings = {
        "apartments", "house", "residential", "detached",
        "semidetached_house", "terrace", "dormitory"
    }

    commercial_buildings = {
        "commercial",        
        "retail",           
        "supermarket",      
        "shop",              
        "kiosk",             
        "mall",             
        "office",           
        "industrial",       
        "warehouse",        
        "restaurant",       
        "cafe",             
        "fast_food",        
        "hotel",            
        "bank",             
        "pub",              
        "bar",              
        "bakery",           
        "clinic",           
        "hospital",         
        "pharmacy",         
        "car_repair",       
        "car_wash",         
        "fuel",             
        "yes"               
    }


    # Amenity and Leisure buildings aren't always declared through building tag alone, so checking 
    # amenity = "university"
    # instead of 
    # building = "university"
    # becomes necessary.
    amenity_buildings = {
        "school",         
        "university",     
        "kindergarten",   
        "hospital",       
        "clinic",         
        "doctors",        
        "fire_station",   
        "police",         
        "townhall",       
        "library",        
        "public",         
        "toilets",        
        "community_centre", 
        "place_of_worship", 
        "church",         
        "chapel",         
        "temple",         
        "mosque",        
        "synagogue",      
    }

    leisure_buildings = {
        "stadium",       
        "sports_centre", 
        "pavilion",      
        "clubhouse",     
        "cabin",         
        "baths",         
        "gym",           
        "recreation_centre", 
        "theatre",       
        "cinema",        
        "museum",       
        "arts_centre",  
    }  


    # Parse OSM-Datei
    tree = ET.parse(input_file)
    root = tree.getroot()

    # Alle Nodes indexieren
    node_dict = {}
    for node in root.findall("node"):
        node_id = node.get("id")
        lat = node.get("lat")
        lon = node.get("lon")
        node_dict[node_id] = (lat, lon)

    results = []

    # <node> mit building=* Tag
    for node in root.findall("node"):
        for tag in node.findall("tag"):
            if tag.get("k") == "building" and tag.get("v") in residential_buildings:
                results.append({
                    "element_type": "node",
                    "id": node.get("id"),
                    "lat": node.get("lat"),
                    "lon": node.get("lon"),
                    "building": tag.get("v")
                })
                break

    # <way> mit erstem <nd> zur Geolokation
    for way in root.findall("way"):
        tags = {tag.get("k"): tag.get("v") for tag in way.findall("tag")}
        if "building" in tags and tags["building"] in residential_buildings:
            first_nd = way.find("nd")
            lat, lon = (None, None)
            if first_nd is not None:
                ref = first_nd.get("ref")
                lat, lon = node_dict.get(ref, (None, None))
            results.append({
                "element_type": "way",
                "id": way.get("id"),
                "lat": lat,
                "lon": lon,
                "building": tags["building"],
                "type": "residential"
            })

    for way in root.findall("way"):
        tags = {tag.get("k"): tag.get("v") for tag in way.findall("tag")}
        is_commercial = 0

        for tag in tags:     
            match tag:
                case "amenity": is_commercial = is_commercial + 1
                case "name": is_commercial = is_commercial + 2
                case "retail" : is_commercial = is_commercial + 1
                case "brand" : is_commercial = is_commercial + 3
                case "opening_hours" : is_commercial = is_commercial + 3
                case "contact:phone" : is_commercial = is_commercial + 3
            if is_commercial >= 4:
                results.append({
                    "element_type": "way",
                    "id": way.get("id"),
                    "lat": lat,
                    "lon": lon,
                    "building": tags.get("building", "unknown"),
                    "type": "commercial"                
                })




    # In CSV speichern
    df = pd.DataFrame(results)
    df.to_csv(output_file, index=False, encoding="utf-8")
    print(f"{len(df)} Wohngebäude gespeichert in '{output_file}'")

if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Nutzung: python extract_buildings.py <eingabe.osm> <ausgabe.csv>")
        sys.exit(1)

    input_file = sys.argv[1]
    output_file = sys.argv[2]
    main(input_file, output_file)
