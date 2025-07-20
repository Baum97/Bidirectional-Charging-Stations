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

    static Integer POPULATION_SIZE = 1;
    static Integer SIMULATION_DAYS = 7;
    static String bidiData = "C:\\Users\\erikw\\Documents\\Uni\\Bidirectional-Charging-Stations\\sumoconfigs\\reutlingen";
    static String outputPopulationAchim = bidiData + "\\reutlingen-population-7days.xml";

    public static void main(String[] args) {

        // Before: // osmosis --read-pbf file="stuttgart-regbez.osm.pbf" --write-xml file="stuttgart-regbez.osm"

        // Build Network
        String osmPbfFile = bidiData + "\\reutlingen.osm";
        String networkFile = bidiData + "\\reutlingen.net.xml";

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

        // Convert to MATSim Coordinates
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

        // Prepare to generate population
        Population population = scenario.getPopulation();
        PopulationFactory factory = population.getFactory();
        Random rand = new Random();

        // Generate Population with 7-day plans
        for (int i = 0; i < POPULATION_SIZE; i++){

            // Create person and plan
            Person person = factory.createPerson(Id.createPersonId(i));
            Plan plan = factory.createPlan();

            // Select fixed home and work locations for this person
            Link home = homeLocations.get(rand.nextInt(residential_coordinates.size()));
            Link work = workLocations.get(rand.nextInt(commercial_coordinates.size()));

            System.out.println("Person " + i + " assigned to home: " + home.getId() + " and work: " + work.getId());

            // Generate activities for 7 days
            for (int day = 0; day < SIMULATION_DAYS; day++) {
                double dayOffset = day * 24 * 3600; // Seconds offset for each day

                // Morning home activity (sleep/night activity from previous day continues)
                if (day == 0) {
                    // First day: start with home activity
                    Activity morningHome = factory.createActivityFromLinkId("home", home.getId());
                    double departureTime = dayOffset + 6 * 3600 + rand.nextInt(7200); // 6am to 8am
                    morningHome.setEndTime(departureTime);
                    plan.addActivity(morningHome);
                }

                // Travel to work
                if (day > 0 || plan.getPlanElements().size() > 0) {
                    Leg legToWork = factory.createLeg("car");
                    plan.addLeg(legToWork);
                }

                // Work activity
                Activity workActivity = factory.createActivityFromLinkId("work", work.getId());
                double workStartTime = dayOffset + 6 * 3600 + rand.nextInt(7200); // Start work between 6-8am
                double workEndTime = dayOffset + 16 * 3600 + rand.nextInt(7200); // End work between 4-6pm

                if (day > 0) {
                    // For days after the first, the work activity starts when they arrive
                    workActivity.setEndTime(workEndTime);
                } else {
                    workActivity.setEndTime(workEndTime);
                }
                plan.addActivity(workActivity);

                // Travel back home
                Leg legToHome = factory.createLeg("car");
                plan.addLeg(legToHome);

                // Evening home activity
                Activity eveningHome = factory.createActivityFromLinkId("home", home.getId());

                if (day < SIMULATION_DAYS - 1) {
                    // Not the last day - set end time to next morning
                    double nextDayDeparture = (day + 1) * 24 * 3600 + 6 * 3600 + rand.nextInt(7200);
                    eveningHome.setEndTime(nextDayDeparture);
                } else {
                    // Last day - no end time (activity continues)
                    // eveningHome.setEndTime() is not called for the last activity
                }

                plan.addActivity(eveningHome);
            }

            person.addPlan(plan);
            population.addPerson(person);
        }

        // Alternative method: Create a more structured 7-day plan
        //createStructured7DayPlan(population, factory, homeLocations, workLocations, residential_coordinates, commercial_coordinates, rand);

        new PopulationWriter(population).write(outputPopulationAchim);
        System.out.println("7-day population has been written to " + outputPopulationAchim);

        // Convert OSM2Network suitable for SUMO
        String output_file = bidiData + "\\reutlingen-matsim-network.xml";
        OSM2Network.convertOSM2Network(osmPbfFile, output_file);
    }

    /**
     * Alternative method to create a more structured 7-day plan
     */
    private static void createStructured7DayPlan(Population population, PopulationFactory factory,
                                                 List<Link> homeLocations, List<Link> workLocations,
                                                 List<POICentroid> residential_coordinates, List<POICentroid> commercial_coordinates, Random rand) {

        for (int i = POPULATION_SIZE; i < POPULATION_SIZE * 2; i++) { // Create additional agents
            Person person = factory.createPerson(Id.createPersonId("structured_" + i));
            Plan plan = factory.createPlan();

            // Fixed locations for this person
            Link home = homeLocations.get(rand.nextInt(residential_coordinates.size()));
            Link work = workLocations.get(rand.nextInt(commercial_coordinates.size()));

            // Generate typical weekly schedule
            for (int day = 0; day < 7; day++) {
                double dayStart = day * 24 * 3600;
                boolean isWeekend = (day == 5 || day == 6); // Saturday and Sunday

                if (day == 0) {
                    // Start of simulation - person is at home
                    Activity startHome = factory.createActivityFromLinkId("home", home.getId());
                    startHome.setEndTime(getWorkDepartureTime(dayStart, isWeekend, rand));
                    plan.addActivity(startHome);
                }

                if (!isWeekend) {
                    // Weekday: go to work

                    // Travel to work
                    Leg toWork = factory.createLeg("car");
                    plan.addLeg(toWork);

                    // Work activity
                    Activity workAct = factory.createActivityFromLinkId("work", work.getId());
                    workAct.setEndTime(getWorkEndTime(dayStart, rand));
                    plan.addActivity(workAct);

                    // Travel home
                    Leg toHome = factory.createLeg("car");
                    plan.addLeg(toHome);

                } else {
                    // Weekend: stay home or add leisure activities
                    if (rand.nextBoolean()) {
                        // Sometimes go out on weekends
                        Leg outLeg = factory.createLeg("car");
                        plan.addLeg(outLeg);

                        // Leisure activity (use a work location as leisure destination)
                        Activity leisure = factory.createActivityFromLinkId("leisure",
                                workLocations.get(rand.nextInt(workLocations.size())).getId());
                        leisure.setEndTime(dayStart + 12 * 3600 + rand.nextInt(8 * 3600)); // 12pm to 8pm
                        plan.addActivity(leisure);

                        // Return home
                        Leg returnHome = factory.createLeg("car");
                        plan.addLeg(returnHome);
                    }
                }

                // Evening/night at home
                Activity homeEvening = factory.createActivityFromLinkId("home", home.getId());

                if (day < 6) {
                    // Not the last day
                    homeEvening.setEndTime(getWorkDepartureTime((day + 1) * 24 * 3600,
                            ((day + 1) == 5 || (day + 1) == 6), rand));
                }
                // Last day: no end time set

                plan.addActivity(homeEvening);
            }

            person.addPlan(plan);
            population.addPerson(person);
        }
    }

    private static double getWorkDepartureTime(double dayStart, boolean isWeekend, Random rand) {
        if (isWeekend) {
            return dayStart + 8 * 3600 + rand.nextInt(4 * 3600); // 8am to 12pm on weekends
        } else {
            return dayStart + 6 * 3600 + rand.nextInt(3 * 3600); // 6am to 9am on weekdays
        }
    }

    private static double getWorkEndTime(double dayStart, Random rand) {
        return dayStart + 16 * 3600 + rand.nextInt(4 * 3600); // 4pm to 8pm
    }
}