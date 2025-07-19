netconvert --matsim myMATsimNetwork.xml -o mySUMOnetwork.net.xml

python .\tools\import\matsim\matsim_importPlans.py --plan-file .\from-matsim\plans.xml -o routes.rou.xml

sumo-gui -c ....sumocfg

Notes von Erik:

wget https://download.geofabrik.de/europe/germany/baden-wuerttemberg/stuttgart-regbez-latest.osm.pbf -O stuttgart-regbez.osm.pbf

osmium extract -b 8.65,48.70,9.05,48.85 stuttgart-regbez.osm.pbf -o esslingen.osm.pbf


sudo apt install osmium-tool

osmium tags-filter stuttgart-regbez.osm.pbf w/landuse=residential -o residential.osm.pbf
[======================================================================] 100%

osmium tags-filter stuttgart-regbez.osm.pbf w/landuse=commercial -o commercial.osm.pbf
[======================================================================] 100%

osmium tags-filter stuttgart-regbez.osm.pbf n/amenity=office -o office.osm.pbf
[======================================================================] 100%

osmium export residential.osm.pbf -o residential.geojson
osmium export commercial.osm.pbf -o commercial.geojson


Open QGIS
Layer -> Vector Layer -> ADD

Vector -> Geometry -> Zentroids -> Residential layer Polygons

Save layers as csv (see chatty) (timezone, name, path, ...)

Then see code:
- POICentroid
- CSVReaderUtil
- Main.java



osmosis --read-pbf file="stuttgart-regbez.osm.pbf" --write-xml file="stuttgart-regbez.osm"
May 31, 2025 7:17:37 PM org.openstreetmap.osmosis.core.Osmosis run
INFO: Osmosis Version 0.48.3
May 31, 2025 7:17:38 PM org.openstreetmap.osmosis.core.Osmosis run
INFO: Preparing pipeline.
May 31, 2025 7:17:38 PM org.openstreetmap.osmosis.core.Osmosis run
INFO: Launching pipeline execution.
May 31, 2025 7:17:38 PM org.openstreetmap.osmosis.core.Osmosis run
INFO: Pipeline executing, waiting for completion.
May 31, 2025 7:19:52 PM org.openstreetmap.osmosis.core.Osmosis run
INFO: Pipeline complete.
May 31, 2025 7:19:52 PM org.openstreetmap.osmosis.core.Osmosis run
INFO: Total execution time: 134350 milliseconds.
