
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

    static Integer POPULATION_SIZE = 50;
    static String bidiData = "C:\\Users\\erikw\\Documents\\Uni\\Bidirectional-Charging-Stations\\sumoconfigs\\reutlingen";
    static String outputPopulationAchim = bidiData + "\\reutlingen-population.xml";

    public static void main(String[] args) {

        // Before: // osmosis --read-pbf file="stuttgart-regbez.osm.pbf" --write-xml
        // file="stuttgart-regbez.osm"

        // Build Network
        String osmPbfFile = bidiData + "\\reutlingen.osm";
        String networkFile = bidiData + "\\reutlingen-network.net.xml";

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

        String ResidentialCsvFilePath = bidiData + "\\csv\\commerical_zentroid.poi.csv";
        String CommercialCsvFilePath = bidiData + "\\csv\\residential_zentroid.poi.csv";

        // Read x & y coordinates from csv file
        List<POICentroid> residential_coordinates = CSVReaderUtil.readCoordinates(ResidentialCsvFilePath);
        List<POICentroid> commercial_coordinates = CSVReaderUtil.readCoordinates(CommercialCsvFilePath);

        /*
         * // Print coordinates for testing
         * System.out.println("Residential coordinates: ");
         * for (POICentroid coordinate : commercial_coordinates) {
         * System.out.println(coordinate);
         * }
         */

        // Convert to MATSim Coordinates
        // x => longitude, y => latitude
        CoordinateTransformation ct = TransformationFactory.getCoordinateTransformation(
                TransformationFactory.WGS84, "EPSG:25832");

        for (POICentroid coordinate : residential_coordinates) {
            double lon = coordinate.getX_coord();
            double lat = coordinate.getY_coord();
            Coord coords_transformed = ct.transform(new Coord(lon, lat));
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
            Coord coords_transformed = ct.transform(new Coord(lon, lat));
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
         * for (Link link : homeLocations) {
         * System.out.println(link);
         * }
         */

        // Prepare to generate population
        Population population = scenario.getPopulation();
        PopulationFactory factory = population.getFactory();
        Random rand = new Random();


        int DAYS = 7;
        double DAY_SEC = 24 * 3600;

        // Generate Population
        for (int i = 0; i < POPULATION_SIZE; i++) {
            Person person = factory.createPerson(Id.createPersonId(i));
            Plan plan = factory.createPlan();

            // wähle einmalig ein Home und Work
            Link homeLink = homeLocations.get(rand.nextInt(homeLocations.size()));
            Link workLink = workLocations.get(rand.nextInt(workLocations.size()));

            for (int day = 0; day < DAYS; day++) {
                double dayOffset = day * DAY_SEC;

                // --- Abfahrt von Zuhause ---
                Activity homeAct = factory.createActivityFromLinkId("home", homeLink.getId());
                // Ende zwischen 6 uhr + Zufall 0 bis 2 h
                double depart = dayOffset + 6*3600 + rand.nextInt(2*3600);
                homeAct.setEndTime(depart);
                plan.addActivity(homeAct);

                // Fahrt
                Leg legToWork = factory.createLeg("car");
                plan.addLeg(legToWork);

                // Arbeit (ohne Endzeit, unbegrenzt bis zur Rückfahrt)
                Activity workAct = factory.createActivityFromLinkId("work", workLink.getId());
                plan.addActivity(workAct);

                // Rückfahrt
                Leg legHome = factory.createLeg("car");
                plan.addLeg(legHome);

                // Wieder Zuhause bis Mitternacht dieses Tages
                Activity homeAgain = factory.createActivityFromLinkId("home", homeLink.getId());
                homeAgain.setEndTime(dayOffset + DAY_SEC);
                plan.addActivity(homeAgain);
            }

            person.addPlan(plan);
            population.addPerson(person);
        }

        // new PopulationWriter(population).write(outputPopulationAchim);
        System.out.println("Population has been written to " + outputPopulationAchim);

        for (Person p : population.getPersons().values()) {
            for (PlanElement pe : p.getSelectedPlan().getPlanElements()) {
                if (pe instanceof Activity) {
                    Id<Link> linkId = ((Activity) pe).getLinkId();
                    if (!network.getLinks().containsKey(linkId)) {
                        System.err.println("Ungültige Link-ID in Aktivität: " + linkId);
                    }
                }
            }
        }

        // Convert OSM2Network suitable for SUMO
        String output_file = bidiData + "\\reutlingen-matsim-network.xml";
        OSM2Network.convertOSM2Network(osmPbfFile, output_file);

    }
}