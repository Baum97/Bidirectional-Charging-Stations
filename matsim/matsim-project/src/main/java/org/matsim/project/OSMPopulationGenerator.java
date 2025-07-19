package org.matsim.project;

import org.matsim.api.core.v01.*;
import org.matsim.api.core.v01.network.Link;
import org.matsim.api.core.v01.population.*;
import org.matsim.core.config.Config;
import org.matsim.core.config.ConfigUtils;
import org.matsim.api.core.v01.population.PopulationWriter;
import org.matsim.core.scenario.ScenarioUtils;
import org.matsim.core.network.io.MatsimNetworkReader;
import org.matsim.api.core.v01.network.Network;


import java.io.File;
import java.util.*;

public class OSMPopulationGenerator {
    public static void main(String[] args) {
        // Paths
        String networkFile = "input-erik/network.xml.gz";
        String outputPopulation = "input-erik/population.xml.gz";

        // Ensure output directory exists
        File outputDirectory = new File("output-erik");
        if (!outputDirectory.exists()) {
            outputDirectory.mkdirs();
        }

        // Load the network into the scenario
        Config config = ConfigUtils.createConfig();
        Scenario scenario = ScenarioUtils.loadScenario(config);
        new MatsimNetworkReader(scenario.getNetwork()).readFile(networkFile);

        // Prepare to generate population
        Network network = scenario.getNetwork();
        Population population = scenario.getPopulation();
        PopulationFactory factory = population.getFactory();
        List<Link> links = new ArrayList<>(network.getLinks().values());

        Random rand = new Random();

        for (int i = 0; i < 1000; i++) {
            Person person = factory.createPerson(Id.createPersonId(i));
            Plan plan = factory.createPlan();

            // Select random links for home and work
            Link homeLink = links.get(rand.nextInt(links.size()));
            Link workLink = links.get(rand.nextInt(links.size()));

            // Create home activity
            Activity home = factory.createActivityFromLinkId("home", homeLink.getId());
            home.setCoord(homeLink.getCoord());
            home.setEndTime(6 * 3600 + rand.nextInt(7200)); // Leave between 6am and 8am
            plan.addActivity(home);

            // Add travel leg
            Leg leg = factory.createLeg("car");
            plan.addLeg(leg);

            // Create work activity
            Activity work = factory.createActivityFromLinkId("work", workLink.getId());
            work.setCoord(workLink.getCoord());
            plan.addActivity(work);

            person.addPlan(plan);
            population.addPerson(person);
        }

        // Write population to file
        new PopulationWriter(population).write(outputPopulation);
        System.out.println("1000-agent population written to " + outputPopulation);
    }
}
