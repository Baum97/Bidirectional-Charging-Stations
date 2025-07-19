package org.matsim.example;

import org.matsim.api.core.v01.Scenario;
import org.matsim.contrib.otfvis.OTFVisLiveModule;
import org.matsim.core.config.Config;
import org.matsim.core.config.ConfigUtils;
import org.matsim.core.controler.Controler;
import org.matsim.core.scenario.ScenarioUtils;
import org.matsim.examples.ExamplesUtils;

public class RunEquilWithVis {
    public static void main(String[] args) {
        String configPath = ExamplesUtils.getTestScenarioURL("equil").toString() + "config.xml";
        Config config = ConfigUtils.loadConfig(configPath);
        Scenario scenario = ScenarioUtils.loadScenario(config);
        Controler controler = new Controler(scenario);

        // Add live visualization
        controler.addOverridingModule(new OTFVisLiveModule());

        controler.run();
    }
}
