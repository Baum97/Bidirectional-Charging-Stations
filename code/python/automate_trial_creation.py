import xml.etree.ElementTree as ET
import pandas as pd
import sys
import subprocess
import os


#! custom input ####################################################!


java_files = ["Main.java", "MatsimPlans2SumoTrips.java", "NearestLinkResult.java", "NearestLinkUtil.java", 
                "NetworkBuilderUtil.java", "OSM2Network.java", "POICentroid.java"]

    # input_args= 1: city_name, 2: csv file(s)
java_args = ["reutlingen.osm", "POIdata.csv"]

    # matsim= MATsim.net.xml, netxml= output file name (recommended: [city_name].net.xml)
netc_matsim = "MATreutlingenNet.xml"
netc_netxml = "Reutlingen.net.xml"

#! custom input ####################################################!




# custom functions ################################################

def compile_java_file(input_files):
    compile_process = subprocess.run(
        ["javac"] + input_files,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )

    if (compile_process.returncode != 0):
        print("Compile Process failed:")
        print(compile_process.stderr)
        exit(1)
    else:
        print("Compilation successful")


    # input_args= 1: file.osm, 2: csv file(s)
def execute_java_file(input_args):
    subprocess.run(["java", "Main"] + input_args)

    # input_args= 1: MATsim.net.xml 2: output file name (recommended: [city_name].net.xml)
def execute_netconvert(input_args):
    command = ["netconvert", input_args]
    subprocess.run(command)


    # input_args=
def execute_matsim_importPlans(matsim_pop, route_xml):
    command = ["python", ".\tools\import\matsim\matsim_importPlans.py", 
               "--plan-file", matsim_pop, "-o", route_xml]

# custom functions ################################################





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


    # java files dir- D:\Master\Forschungsprojekt\GitDir\Bidirectional-Charging-Stations\matsim\matsim-project\src\main\java\org\matsim\project\v1
    # compile all necessary java files to then call main.java to create MATsim files
    #compile_java_file(java_files)
    #execute_java_file(java_args)
    #execute_netconvert(netc_matsim, netc_netxml)

if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Nutzung: python extract_buildings.py <eingabe.osm> <ausgabe.csv>")
        sys.exit(1)

    input_file = sys.argv[1]
    output_file = sys.argv[2]
    main(input_file, output_file)
