package org.matsim.project.v1;

import org.matsim.api.core.v01.Scenario;
import org.matsim.api.core.v01.network.Network;
import org.matsim.core.config.Config;
import org.matsim.core.config.ConfigUtils;
import org.matsim.core.utils.geometry.CoordinateTransformation;
import org.matsim.core.utils.geometry.transformations.TransformationFactory;
import org.matsim.core.utils.io.OsmNetworkReader;
import org.matsim.core.scenario.ScenarioUtils;

public class NetworkBuilderUtil {

    // Static method for building the network
    public static void buildNetwork(String osmPbfFile, String networkFile) {
        // Set up MATSim scenario and config
        Config config = ConfigUtils.createConfig();
        Scenario scenario = ScenarioUtils.createScenario(config);

        Network network = scenario.getNetwork();

        // Use proper coordinate transformation (adjust to your region if needed)
        CoordinateTransformation ct = TransformationFactory.getCoordinateTransformation(
                TransformationFactory.WGS84, "EPSG:25832");

        // Create and run the reader
        OsmNetworkReader osmNetworkReader = new OsmNetworkReader(network, ct);
        osmNetworkReader.parse(osmPbfFile);

        // Write the network to file
        new org.matsim.core.network.io.NetworkWriter(network).write(networkFile);

        System.out.println("Network created and written to: " + networkFile);
    }
}
