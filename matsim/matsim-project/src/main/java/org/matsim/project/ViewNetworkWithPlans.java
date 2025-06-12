package org.matsim.project;

import org.matsim.api.core.v01.Scenario;
import org.matsim.core.config.Config;
import org.matsim.core.config.ConfigUtils;
import org.matsim.core.scenario.ScenarioUtils;
import org.matsim.contrib.otfvis.OTFVis;

public class ViewNetworkWithPlans {
    public static void main(String[] args) {
        // Load config and scenario (even if it's minimal, needed for loading the network)
        Config config = ConfigUtils.createConfig();
        config.network().setInputFile("input-erik/network.xml");  // network file
        config.plans().setInputFile("input-erik/population.xml"); // plans file

        Scenario scenario = ScenarioUtils.loadScenario(config);

        // Launch OTFVis GUI viewer
        OTFVis.playScenario(scenario);
    }
}
