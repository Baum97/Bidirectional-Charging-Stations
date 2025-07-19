package org.matsim.project;

import org.geotools.data.*;
import org.geotools.data.simple.*;
import org.geotools.feature.simple.SimpleFeatureBuilder;
import org.geotools.feature.simple.SimpleFeatureTypeBuilder;
import org.geotools.referencing.CRS;
import org.locationtech.jts.geom.*;
import org.matsim.api.core.v01.Scenario;
import org.matsim.api.core.v01.network.Link;
import org.matsim.api.core.v01.network.Network;
import org.matsim.core.network.io.MatsimNetworkReader;
import org.matsim.core.scenario.ScenarioUtils;
import org.opengis.feature.simple.SimpleFeature;
import org.opengis.feature.simple.SimpleFeatureType;
import org.opengis.referencing.crs.CoordinateReferenceSystem;
import org.geotools.data.shapefile.ShapefileDataStoreFactory;
import org.geotools.data.shapefile.ShapefileDataStore;

import java.io.File;
import java.io.Serializable;
import java.net.URL;
import java.util.*;

public class MatsimNetwork2Shapefile {

    public static void main(String[] args) throws Exception {
        // === Input and output paths ===
        String networkFile = "input-erik/network.xml";  // path to MATSim network
        String outputFile = "input-erik/matsim_network.shp"; // output .shp file

        // === Load MATSim network ===
        Scenario scenario = ScenarioUtils.createScenario(org.matsim.core.config.ConfigUtils.createConfig());
        new MatsimNetworkReader(scenario.getNetwork()).readFile(networkFile);
        Network network = scenario.getNetwork();

        // === Define CRS (default: WGS84) ===
        CoordinateReferenceSystem crs = CRS.decode("EPSG:25832", true);;;  // Change if needed

        // === Create schema ===
        SimpleFeatureTypeBuilder builder = new SimpleFeatureTypeBuilder();
        builder.setName("link");
        builder.setCRS(crs);
        builder.add("geometry", LineString.class);
        builder.add("id", String.class);
        builder.add("length", Double.class);
        builder.add("capacity", Double.class);
        builder.add("freespeed", Double.class);
        SimpleFeatureType TYPE = builder.buildFeatureType();

        // === Set up shapefile store ===
        File newFile = new File(outputFile);
        newFile.getParentFile().mkdirs(); // ensure parent folders exist

        Map<String, Serializable> params = new HashMap<>();
        params.put("url", newFile.toURI().toURL());
        params.put("create spatial index", Boolean.TRUE);

        ShapefileDataStoreFactory dataStoreFactory = new ShapefileDataStoreFactory();
        ShapefileDataStore dataStore = (ShapefileDataStore) dataStoreFactory.createNewDataStore(params);
        dataStore.setCharset(java.nio.charset.StandardCharsets.UTF_8);
        dataStore.createSchema(TYPE); // ⬅️ This must happen before writing!
        String typeName = dataStore.getTypeNames()[0];
        dataStore.forceSchemaCRS(TYPE.getCoordinateReferenceSystem());

        // === Write features ===
        Transaction transaction = new DefaultTransaction("create");
        GeometryFactory geometryFactory = new GeometryFactory();


        try (FeatureWriter<SimpleFeatureType, SimpleFeature> writer =
                     dataStore.getFeatureWriterAppend(typeName, transaction)) {
        /*
        try (FeatureWriter<SimpleFeatureType, SimpleFeature> writer =
                     dataStore.getFeatureWriterAppend(TYPE.getTypeName(), transaction)) {
        */
            SimpleFeatureBuilder featureBuilder = new SimpleFeatureBuilder(TYPE);

            for (Link link : network.getLinks().values()) {
                double x1 = link.getFromNode().getCoord().getX();
                double y1 = link.getFromNode().getCoord().getY();
                double x2 = link.getToNode().getCoord().getX();
                double y2 = link.getToNode().getCoord().getY();

                Coordinate[] coords = new Coordinate[]{
                        new Coordinate(x1, y1),
                        new Coordinate(x2, y2)
                };

                LineString geometry = geometryFactory.createLineString(coords);

                featureBuilder.add(geometry);
                featureBuilder.add(link.getId().toString());
                featureBuilder.add(link.getLength());
                featureBuilder.add(link.getCapacity());
                featureBuilder.add(link.getFreespeed());

                SimpleFeature newFeature = featureBuilder.buildFeature(null);
                SimpleFeature feature = writer.next();
                feature.setAttributes(newFeature.getAttributes());
            }

            transaction.commit();
            System.out.println("✅ Shapefile written to: " + outputFile);

        } catch (Exception e) {
            transaction.rollback();
            e.printStackTrace();
        } finally {
            transaction.close();
        }
    }
}
