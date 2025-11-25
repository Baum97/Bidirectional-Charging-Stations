import xml.etree.ElementTree as ET
from tqdm import tqdm  # Import tqdm for progress tracking
import os  # Import os for directory operations

def extract_pois(osm_file, output_dir):
    """
    Extract POIs like offices and residential buildings from an OSM XML file.

    Args:
        osm_file (str): Path to the OSM XML file.
        output_dir (str): Directory where the output CSV files will be written.
    """
    try:
        # Ensure the output directory exists
        os.makedirs(output_dir, exist_ok=True)

        # Parse the OSM XML file
        tree = ET.parse(osm_file)
        root = tree.getroot()

        # Define the tags to look for and their categories
        poi_categories = {
            "offices": ["office"],
            "residential": ["residential"],
            "others": [
                "doctors", "clinic", "hospital", "pharmacy", "school", "university",
                "kindergarten", "supermarket", "mall", "convenience", "bakery",
                "butcher", "clothes", "furniture", "electronics", "restaurant",
                "cafe", "bar", "pub"
            ]
        }

        # Open separate output files for each category
        output_files = {}
        for category in poi_categories:
            category_file = os.path.join(output_dir, f"poi_{category}.csv")
            output_files[category] = open(category_file, "w", encoding="utf-8")
            output_files[category].write("id,name,type,lat,lon\n")

        # Collect all nodes and ways for processing
        elements = root.findall(".//node") + root.findall(".//way")

        try:
            # Iterate through all elements with a progress bar
            for element in tqdm(elements, desc="Processing elements", unit="element"):
                element_id = element.get("id")
                lat = element.get("lat")  # Only nodes have lat/lon
                lon = element.get("lon")

                # Check if the element has tags
                tags = element.findall("tag")
                for tag in tags:
                    k = tag.get("k")
                    v = tag.get("v")

                    # Determine the category of the POI
                    for category, values in poi_categories.items():
                        if v in values:
                            name = next((t.get("v") for t in tags if t.get("k") == "name"), "Unknown")

                            # For ways, calculate centroid if lat/lon is not available
                            if element.tag == "way" and (lat is None or lon is None):
                                nd_refs = [nd.get("ref") for nd in element.findall("nd")]
                                lat, lon = calculate_centroid(root, nd_refs)

                            output_files[category].write(f"{element_id},{name},{v},{lat},{lon}\n")
                            break
        finally:
            # Close all output files
            for f in output_files.values():
                f.close()

        print(f"POIs successfully extracted to {output_dir}")

    except ET.ParseError as e:
        print(f"Error parsing the OSM file: {e}")
    except Exception as e:
        print(f"An error occurred: {e}")
    
    return [os.path.join(output_dir, f"poi_{category}.csv") for category in poi_categories]

def calculate_centroid(root, nd_refs):
    """
    Calculate the centroid of a way based on its node references.

    Args:
        root (Element): The root of the OSM XML tree.
        nd_refs (list): List of node references.

    Returns:
        tuple: (latitude, longitude) of the centroid.
    """
    latitudes = []
    longitudes = []

    for node in root.findall(".//node"):
        if node.get("id") in nd_refs:
            latitudes.append(float(node.get("lat")))
            longitudes.append(float(node.get("lon")))

    if latitudes and longitudes:
        return sum(latitudes) / len(latitudes), sum(longitudes) / len(longitudes)

    return None, None

"""
if __name__ == "__main__":
    # Example usage
    osm_file = "../data/scenarios/test3/test_name_bbox.osm.xml"  # Path to the OSM file
    output_file = "poi_coordinates.csv"  # Path to the output CSV file

    extract_pois(osm_file, output_file)
"""