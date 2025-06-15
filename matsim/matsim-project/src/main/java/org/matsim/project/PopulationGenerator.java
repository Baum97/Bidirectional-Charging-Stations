package org.matsim.project;

import org.matsim.api.core.v01.*;
import org.matsim.api.core.v01.population.*;
import org.matsim.api.core.v01.population.PopulationWriter;
import org.matsim.core.scenario.ScenarioUtils;
import org.matsim.core.config.ConfigUtils;

import java.io.File;
import java.util.Random;

public class PopulationGenerator {
    public static void main(String[] args) {

        File outputDirectory = new File("C:\\Projekte\\Bidi-Data");
        if (!outputDirectory.exists()) {
            outputDirectory.mkdirs();
        }

        Scenario scenario = ScenarioUtils.createScenario(ConfigUtils.createConfig());
        Population population = scenario.getPopulation();
        PopulationFactory factory = population.getFactory();

        Random rand = new Random();

        for (int i = 0; i < 1000; i++) {
            Person person = factory.createPerson(Id.createPersonId(i));
            Plan plan = factory.createPlan();

            // Random home location
            Coord homeCoord = new Coord(rand.nextDouble() * 10000, rand.nextDouble() * 10000);
            Activity home = factory.createActivityFromCoord("home", homeCoord);
            home.setEndTime(6 * 3600 + rand.nextInt(7200)); // Leave between 6am and 8am
            plan.addActivity(home);

            // Travel by car
            Leg leg = factory.createLeg("car");
            plan.addLeg(leg);

            // Random work location
            Coord workCoord = new Coord(rand.nextDouble() * 10000, rand.nextDouble() * 10000);
            Activity work = factory.createActivityFromCoord("work", workCoord);
            plan.addActivity(work);

            person.addPlan(plan);
            population.addPerson(person);
        }

        String fileDir = outputDirectory + "\\esslingen-plans.xml";
        new PopulationWriter(population).write(fileDir);
        System.out.println("1000-agent population written to " + fileDir);


    }
}
