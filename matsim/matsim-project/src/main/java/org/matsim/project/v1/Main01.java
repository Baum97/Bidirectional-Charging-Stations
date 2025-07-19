package org.matsim.project.v1;

import org.matsim.api.core.v01.Coord;
import org.matsim.api.core.v01.Id;
import org.matsim.api.core.v01.Scenario;
import org.matsim.api.core.v01.network.Link;
import org.matsim.api.core.v01.network.Network;
import org.matsim.api.core.v01.population.*;
import org.matsim.core.config.Config;
import org.matsim.core.config.ConfigUtils;
import org.matsim.core.scenario.ScenarioUtils;
import org.matsim.core.utils.geometry.CoordinateTransformation;
import org.matsim.core.utils.geometry.transformations.TransformationFactory;
import org.w3c.dom.Document;
import org.w3c.dom.Element;
import org.w3c.dom.NodeList;

import javax.xml.parsers.DocumentBuilder;
import javax.xml.parsers.DocumentBuilderFactory;
import java.util.*;

public class Main01 {

    static Integer POPULATION_SIZE = 200;
    static String bidiData = "C:\\Users\\erikw\\Documents\\Uni\\Bidirectional-Charging-Stations\\sumoconfigs\\reutlingen";
    static String outputPopulationAchim = bidiData + "\\reutlingen-population.rou.xml";

    public static void main(String[] args) {

        String osmPbfFile = bidiData + "\\reutlingen.osm";
        String matsimNetworkFile = bidiData + "\\reutlingen-matsim-network.xml";
        String sumoNetworkFile = bidiData + "\\reutlingenSumoNetwork.net.xml";

        // Build MATSim network from OSM
        java.io.File netFile = new java.io.File(matsimNetworkFile);
        if (!netFile.exists()) {
            System.out.println("Building MATSim network from OSM...");
            NetworkBuilderUtil.buildNetwork(osmPbfFile, matsimNetworkFile);
        }

        // Load MATSim network and use its link IDs (these will be compatible)
        Config config = ConfigUtils.createConfig();
        config.network().setInputFile(matsimNetworkFile);
        Scenario scenario = ScenarioUtils.loadScenario(config);
        Network network = scenario.getNetwork();

        // Get all valid link IDs from the MATSim network
        Set<String> validLinkIds = new HashSet<>();
        Map<String, Link> networkLinks = new HashMap<>();

        for (Link link : network.getLinks().values()) {
            String linkId = link.getId().toString();
            validLinkIds.add(linkId);
            networkLinks.put(linkId, link);
        }

        System.out.println("Found " + validLinkIds.size() + " valid MATSim links");

        // Create a simple scenario for population generation
        Population population = scenario.getPopulation();
        PopulationFactory factory = population.getFactory();

        String ResidentialCsvFilePath = bidiData + "\\csv\\residential_zentroid.poi.csv"; // Fixed the path
        String CommercialCsvFilePath = bidiData + "\\csv\\commerical_zentroid.poi.csv";

        // Read coordinates from CSV
        List<POICentroid> residential_coordinates = CSVReaderUtil.readCoordinates(ResidentialCsvFilePath);
        List<POICentroid> commercial_coordinates = CSVReaderUtil.readCoordinates(CommercialCsvFilePath);

        // Convert to projected coordinates
        CoordinateTransformation ct = TransformationFactory.getCoordinateTransformation(
                TransformationFactory.WGS84, "EPSG:25832");

        // Process residential coordinates and find nearest MATSim links
        NearestLinkUtil nearestLinkFinder = new NearestLinkUtil(network);
        List<String> homeLinkIds = new ArrayList<>();

        for (POICentroid coordinate : residential_coordinates) {
            double lon = coordinate.getX_coord();
            double lat = coordinate.getY_coord();
            Coord coords_transformed = ct.transform(new Coord(lon, lat));

            Link nearestLink = nearestLinkFinder.findNearestLink(coords_transformed);
            if (nearestLink != null && validLinkIds.contains(nearestLink.getId().toString())) {
                homeLinkIds.add(nearestLink.getId().toString());
                System.out.println("Found home link: " + nearestLink.getId().toString());
            }
        }

        // Process commercial coordinates
        List<String> workLinkIds = new ArrayList<>();
        for (POICentroid coordinate : commercial_coordinates) {
            double lon = coordinate.getX_coord();
            double lat = coordinate.getY_coord();
            Coord coords_transformed = ct.transform(new Coord(lon, lat));

            Link nearestLink = nearestLinkFinder.findNearestLink(coords_transformed);
            if (nearestLink != null && validLinkIds.contains(nearestLink.getId().toString())) {
                workLinkIds.add(nearestLink.getId().toString());
                System.out.println("Found work link: " + nearestLink.getId().toString());
            }
        }

        if (homeLinkIds.isEmpty() || workLinkIds.isEmpty()) {
            System.err.println("Error: No valid home or work links found!");
            System.err.println("Home links found: " + homeLinkIds.size());
            System.err.println("Work links found: " + workLinkIds.size());
            return;
        }

        // Generate population with valid MATSim link IDs
        Random rand = new Random();

        for (int i = 0; i < POPULATION_SIZE; i++) {
            Person person = factory.createPerson(Id.createPersonId(i));
            Plan plan = factory.createPlan();

            // Home activity - use MATSim link ID directly
            String homeLinkId = homeLinkIds.get(rand.nextInt(homeLinkIds.size()));
            Activity homeActivity = factory.createActivityFromLinkId("home", Id.createLinkId(homeLinkId));
            homeActivity.setEndTime(6 * 3600 + rand.nextInt(7200));
            plan.addActivity(homeActivity);

            // Travel leg
            Leg leg = factory.createLeg("car");
            plan.addLeg(leg);

            // Work activity - use MATSim link ID directly
            String workLinkId = workLinkIds.get(rand.nextInt(workLinkIds.size()));
            Activity workActivity = factory.createActivityFromLinkId("work", Id.createLinkId(workLinkId));
            plan.addActivity(workActivity);

            person.addPlan(plan);
            population.addPerson(person);
        }

        new PopulationWriter(population).write(outputPopulationAchim);
        System.out.println("Population written with " + population.getPersons().size() + " persons");
        System.out.println("Using " + homeLinkIds.size() + " home locations and " + workLinkIds.size() + " work locations");

        // Now convert the MATSim network to SUMO format for simulation
        convertMatsimNetworkToSumo(matsimNetworkFile, sumoNetworkFile);
    }

    // Convert MATSim network to SUMO format
    private static void convertMatsimNetworkToSumo(String matsimNetworkFile, String sumoNetworkFile) {
        try {
            // Load MATSim network
            Config config = ConfigUtils.createConfig();
            config.network().setInputFile(matsimNetworkFile);
            Scenario scenario = ScenarioUtils.loadScenario(config);
            Network network = scenario.getNetwork();

            // Write as SUMO network using MATSim's built-in converter
            // Note: You might need to use a different converter here
            // This is a placeholder - you may need to implement this conversion
            System.out.println("Converting MATSim network to SUMO format...");

            // Alternative: Use your existing OSM2Network but save to different file
            // OSM2Network.convertOSM2Network(osmFile, sumoNetworkFile);

        } catch (Exception e) {
            System.err.println("Error converting network: " + e.getMessage());
        }
    }
}