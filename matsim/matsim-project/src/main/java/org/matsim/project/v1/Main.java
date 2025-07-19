package org.matsim.project.v1;

import java.io.PrintWriter;
import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.util.*;

import org.matsim.api.core.v01.*;
import org.matsim.api.core.v01.network.*;
import org.matsim.api.core.v01.population.*;
import org.matsim.core.config.*;
import org.matsim.core.scenario.ScenarioUtils;
import org.matsim.core.utils.geometry.CoordinateTransformation;
import org.matsim.core.utils.geometry.transformations.TransformationFactory;
import org.matsim.vehicles.*;

public class Main {

    static int POPULATION_SIZE = 200;
    static String bidiData = "C:\\Users\\erikw\\Documents\\Uni\\Bidirectional-Charging-Stations\\sumoconfigs\\reutlingen";
    static String outputPopulationFile = bidiData + "\\population-test.rou.xml";
    static String outputRouFile = bidiData + "\\reutlingenSumoRoutes.rou.xml";

    public static void main(String[] args) {

        // 1. Netzwerk laden
        String osmPbfFile = bidiData + "\\reutlingen.osm";
        String networkFile = bidiData + "\\reutlingen-network.xml";

        if (!new java.io.File(networkFile).exists()) {
            NetworkBuilderUtil.buildNetwork(osmPbfFile, networkFile);
        }

        Config config = ConfigUtils.createConfig();
        config.network().setInputFile(networkFile);
        Scenario scenario = ScenarioUtils.loadScenario(config);
        Network network = scenario.getNetwork();

        // 2. POIs einlesen
        String ResidentialCsv = bidiData + "\\csv\\commerical_zentroid.poi.csv";
        String CommercialCsv = bidiData + "\\csv\\residential_zentroid.poi.csv";

        List<POICentroid> residential_coordinates = CSVReaderUtil.readCoordinates(ResidentialCsv);
        List<POICentroid> commercial_coordinates = CSVReaderUtil.readCoordinates(CommercialCsv);

        CoordinateTransformation ct = TransformationFactory.getCoordinateTransformation(
                TransformationFactory.WGS84, "EPSG:25832");

        for (POICentroid c : residential_coordinates) {
            c.setTranformedCoord(ct.transform(new Coord(c.getX_coord(), c.getY_coord())));
        }
        for (POICentroid c : commercial_coordinates) {
            c.setTranformedCoord(ct.transform(new Coord(c.getX_coord(), c.getY_coord())));
        }

        NearestLinkUtil nearestLinkFinder = new NearestLinkUtil(network);

        List<Link> homeLocations = new ArrayList<>();
        for (POICentroid c : residential_coordinates) {
            Link l = nearestLinkFinder.findNearestLink(c.getTranformedCoord());
            c.setNearestLinkId(l.getId().toString());
            homeLocations.add(l);
        }

        List<Link> workLocations = new ArrayList<>();
        for (POICentroid c : commercial_coordinates) {
            Link l = nearestLinkFinder.findNearestLink(c.getTranformedCoord());
            c.setNearestLinkId(l.getId().toString());
            workLocations.add(l);
        }

        // 3. Population erzeugen
        Population population = scenario.getPopulation();
        PopulationFactory factory = population.getFactory();
        Random rand = new Random();

        for (int i = 0; i < POPULATION_SIZE; i++) {
            Link home = homeLocations.get(rand.nextInt(homeLocations.size()));
            Link work = workLocations.get(rand.nextInt(workLocations.size()));

            for (int day = 0; day < 7; day++) {
                String personId = i + "_d" + day;
                Person person = factory.createPerson(Id.createPersonId(personId));
                Plan plan = factory.createPlan();

                int baseDeparture = 6 * 3600 + rand.nextInt(7200); // 6-8 Uhr
                int departureTime = baseDeparture + (day * 86400);

                Activity homeActivity = factory.createActivityFromLinkId("home", home.getId());
                homeActivity.setEndTime(departureTime);
                plan.addActivity(homeActivity);

                plan.addLeg(factory.createLeg("car"));

                Activity workActivity = factory.createActivityFromLinkId("work", work.getId());
                workActivity.setStartTime(departureTime + 1800);
                workActivity.setEndTime(departureTime + 10 * 3600);
                plan.addActivity(workActivity);

                plan.addLeg(factory.createLeg("car"));

                Activity homeAgain = factory.createActivityFromLinkId("home", home.getId());
                plan.addActivity(homeAgain);

                person.addPlan(plan);
                population.addPerson(person);
            }
        }

        new PopulationWriter(population).write(outputPopulationFile);
        System.out.println("Population written to: " + outputPopulationFile);

        // 4. Fahrzeuge erstellen
        Vehicles vehicles = VehicleUtils.createVehiclesContainer();
        VehicleType vehicleType = vehicles.getFactory().createVehicleType(Id.create("carType", VehicleType.class));
        vehicleType.setMaximumVelocity(50.0 / 3.6);
        vehicleType.setPcuEquivalents(1.0);
        vehicles.addVehicleType(vehicleType);

        for (Person person : population.getPersons().values()) {
            Vehicle vehicle = vehicles.getFactory().createVehicle(Id.createVehicleId(person.getId()), vehicleType);
            vehicles.addVehicle(vehicle);
        }

        String vehicleOutput = bidiData + "\\vehicles.xml";
        new VehicleWriterV1(vehicles).writeFile(vehicleOutput);
        System.out.println("Vehicles written to: " + vehicleOutput);

        // 5. SUMO .rou.xml mit parkenden Fahrzeugen erzeugen
        try (PrintWriter writer = new PrintWriter(outputRouFile)) {
            writer.println("<?xml version=\"1.0\" encoding=\"UTF-8\"?>");
            writer.printf("<!-- generated on %s -->%n",
                    LocalDateTime.now().format(DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss")));
            writer.println("<routes xmlns:xsi=\"http://www.w3.org/2001/XMLSchema-instance\"");
            writer.println("        xsi:noNamespaceSchemaLocation=\"http://sumo.dlr.de/xsd/routes_file.xsd\">");
            writer.println("    <vType id=\"car\" vClass=\"passenger\"/>");

            for (Person person : population.getPersons().values()) {
                String vehId = "veh_" + person.getId();
                Plan plan = person.getSelectedPlan();
                List<PlanElement> elements = plan.getPlanElements();

                String fromEdge = null, toEdge = null;
                int departureTime = 0;
                int parkDuration = 10 * 3600;
                int homeDuration = 14 * 3600;

                for (int i = 0; i < elements.size() - 2; i++) {
                    if (elements.get(i) instanceof Activity &&
                            elements.get(i + 1) instanceof Leg &&
                            elements.get(i + 2) instanceof Activity) {

                        Activity act1 = (Activity) elements.get(i);
                        Activity act2 = (Activity) elements.get(i + 2);

                        fromEdge = act1.getLinkId().toString();
                        toEdge = act2.getLinkId().toString();
                        if (act1.getEndTime().isDefined()) {
                            departureTime = (int) act1.getEndTime().seconds();
                        } else {
                            departureTime = 6 * 3600 + rand.nextInt(7200); // fallback, wenn kein Endzeitpunkt vorhanden
                        }

                        break;
                    }
                }

                if (fromEdge != null && toEdge != null) {
                    writer.printf("    <vehicle id=\"%s\" type=\"car\" depart=\"%d\">%n", vehId, departureTime);
                    writer.printf("        <route edges=\"%s %s %s\"/>%n", fromEdge, toEdge, fromEdge);
                    writer.printf("        <stop edge=\"%s\" duration=\"%d\" parking=\"true\"/>%n", toEdge, parkDuration);
                    writer.printf("        <stop edge=\"%s\" duration=\"%d\" parking=\"true\"/>%n", fromEdge, homeDuration);
                    writer.println("    </vehicle>");
                }
            }

            writer.println("</routes>");
            System.out.println("SUMO .rou.xml with parked vehicles written to: " + outputRouFile);
        } catch (Exception e) {
            e.printStackTrace();
        }

        // 6. OSM → SUMO Netzwerk konvertieren
        String outputNet = bidiData + "\\reutlingen-network.xml";
        OSM2Network.convertOSM2Network(osmPbfFile, outputNet);
    }
}
