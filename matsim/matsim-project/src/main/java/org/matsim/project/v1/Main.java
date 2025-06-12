package org.matsim.project.v1;

import java.util.ArrayList;
import java.util.List;
import java.util.Random;

import cadyts.calibrators.filebased.Agent;
import com.jogamp.nativewindow.javafx.JFXAccessor;
import org.matsim.api.core.v01.Coord;
import org.matsim.api.core.v01.Id;
import org.matsim.api.core.v01.network.Link;
import org.matsim.api.core.v01.population.*;
import org.matsim.core.utils.geometry.CoordinateTransformation;
import org.matsim.core.utils.geometry.transformations.TransformationFactory;
import org.matsim.api.core.v01.Scenario;
import org.matsim.api.core.v01.network.Network;
import org.matsim.core.config.Config;
import org.matsim.core.config.ConfigUtils;
import org.matsim.core.scenario.ScenarioUtils;


public class Main {

    static Integer POPULATION_SIZE = 10;
    static String outputPopulation = "C:\\Users\\erikw\\Desktop\\AIM\\biflex\\matsim-example-project\\src\\main\\java\\org\\matsim\\project\\v1\\esslingen-population.xml.gz";


    public static void main(String[] args) {

        // Before: // osmosis --read-pbf file="stuttgart-regbez.osm.pbf" --write-xml file="stuttgart-regbez.osm"

        // Build Network
        String osmPbfFile = "C:\\Users\\erikw\\Desktop\\AIM\\biflex\\esslingen.osm";
        String networkFile = "C:\\Users\\erikw\\Desktop\\AIM\\biflex\\esslingen-network.xml";

        // Check if network file already exists or built it
        java.io.File netFile = new java.io.File(networkFile);
        if (!netFile.exists()) {
            System.out.println("Network file not found. Building network from OSM...");
            NetworkBuilderUtil.buildNetwork(osmPbfFile, networkFile);
        } else {
            System.out.println("Network file found. Skipping build.");
        }

        // Network
        Config config = ConfigUtils.createConfig();
        config.network().setInputFile(networkFile);
        Scenario scenario = ScenarioUtils.loadScenario(config);
        Network network = scenario.getNetwork();


        String ResidentialCsvFilePath = "C:\\Users\\erikw\\Desktop\\AIM\\biflex\\matsim-example-project\\src\\main\\java\\org\\matsim\\project\\v1\\esslingen_poi_residential.csv";
        String CommercialCsvFilePath = "C:\\Users\\erikw\\Desktop\\AIM\\biflex\\matsim-example-project\\src\\main\\java\\org\\matsim\\project\\v1\\esslingen_poi_commercial.csv";


        // Read x & y coordinates from csv file
        List<POICentroid> residential_coordinates = CSVReaderUtil.readCoordinates(ResidentialCsvFilePath);
        List<POICentroid> commercial_coordinates = CSVReaderUtil.readCoordinates(CommercialCsvFilePath);

        /*
        // Print coordinates for testing
        System.out.println("Residential coordinates: ");
        for (POICentroid coordinate : commercial_coordinates) {
            System.out.println(coordinate);
        }
        */

        // Convert to MATSim Coordinates
        // x => longitude, y => latitude
        CoordinateTransformation ct = TransformationFactory.getCoordinateTransformation(
                TransformationFactory.WGS84, "EPSG:25832");

        for (POICentroid coordinate : residential_coordinates) {
            double lon = coordinate.getX_coord();
            double lat = coordinate.getY_coord();
            Coord coords_transformed = ct.transform(new Coord(lon,lat));
            coordinate.setTranformedCoord(coords_transformed);
            System.out.println(coords_transformed);
        }

        NearestLinkUtil nearestLinkFinder = new NearestLinkUtil(network);

        // Create a list to store all nearest points as home locations
        List<Link> homeLocations = new ArrayList<>();

        // Loop through all transformed Centroids & find nearest Point on nearest Link
        // NOTE: Nearest Points aren't useful for us
        for (POICentroid coordinate : residential_coordinates) {
            Coord transformed = coordinate.getTranformedCoord();
            Link nearestLink = nearestLinkFinder.findNearestLink(transformed);
            Coord nearestPoint = nearestLinkFinder.findNearestPointOnLink(nearestLink, transformed);

            coordinate.setNearestPoint(nearestPoint);
            coordinate.setNearestLinkId(nearestLink.getId().toString());

            homeLocations.add(nearestLink);

            System.out.println("Centroid: " + coordinate);
            System.out.println("Nearest Link ID: " + coordinate.getNearestLinkId());
            System.out.println("Nearest Point: (" + nearestPoint.getX() + ", " + nearestPoint.getY() + ")");
        }

        for (POICentroid coordinate : commercial_coordinates) {
            double lon = coordinate.getX_coord();
            double lat = coordinate.getY_coord();
            Coord coords_transformed = ct.transform(new Coord(lon,lat));
            coordinate.setTranformedCoord(coords_transformed);
            System.out.println(coords_transformed);
        }

        List<Link> workLocations = new ArrayList<>();

        for (POICentroid coordinate : commercial_coordinates) {
            Coord transformed = coordinate.getTranformedCoord();
            Link nearestLink = nearestLinkFinder.findNearestLink(transformed);
            Coord nearestPoint = nearestLinkFinder.findNearestPointOnLink(nearestLink, transformed);

            coordinate.setNearestPoint(nearestPoint);
            coordinate.setNearestLinkId(nearestLink.getId().toString());

            workLocations.add(nearestLink);

            System.out.println("Commercial Centroid: " + coordinate);
            System.out.println("Nearest Link ID: " + coordinate.getNearestLinkId());
            System.out.println("Nearest Point: (" + nearestPoint.getX() + ", " + nearestPoint.getY() + ")");
        }

        /*
        for (Link link : homeLocations) {
            System.out.println(link);
        }
        */

        // Prepare to generate population
        Population population = scenario.getPopulation();
        PopulationFactory factory = population.getFactory();
        Random rand = new Random();

        // Generate Population
        for (int i = 0; i < POPULATION_SIZE; i++){

            // Create person and plan
            Person person = factory.createPerson(Id.createPersonId(i));
            Plan plan = factory.createPlan();

            // Home activity
            Link home = homeLocations.get(rand.nextInt(residential_coordinates.size())); // select random homeLocation
            // System.out.println(home);

            // Create home activity
            Activity homeActivity = factory.createActivityFromLinkId("home", home.getId());
            homeActivity.setEndTime(6 * 3600 + rand.nextInt(7200)); // 6am to 8am departure
            plan.addActivity(homeActivity);

            // Create travel leg
            Leg leg = factory.createLeg("car");
            plan.addLeg(leg);

            // NOTE: (TODO) Can add offices!!!

            // Work activity
            Link work = workLocations.get(rand.nextInt(commercial_coordinates.size()));
            // System.out.println(home);
            Activity workActivity = factory.createActivityFromLinkId("work", work.getId());
            plan.addActivity(workActivity);

            person.addPlan(plan);
            population.addPerson(person);
        }

        new PopulationWriter(population).write(outputPopulation);
        System.out.println("Population has been written to " + outputPopulation);

        // Convert OSM2Network suitable for SUMO
        String output_file = "C:\\Users\\erikw\\Desktop\\AIM\\biflex\\matsim-example-project\\src\\main\\java\\org\\matsim\\project\\v1\\esslingen-network.xml";

        OSM2Network.convertOSM2Network(osmPbfFile, output_file);


    }
}
