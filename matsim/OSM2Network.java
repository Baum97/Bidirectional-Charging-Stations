package org.matsim.project.v1;

import org.matsim.api.core.v01.Scenario;
import org.matsim.api.core.v01.network.Network;
import org.matsim.core.config.Config;
import org.matsim.core.config.ConfigUtils;
import org.matsim.core.network.algorithms.NetworkCleaner;
import org.matsim.core.network.io.NetworkWriter;
import org.matsim.core.scenario.ScenarioUtils;
import org.matsim.core.utils.geometry.CoordinateTransformation;
import org.matsim.core.utils.geometry.transformations.TransformationFactory;
import org.matsim.core.utils.io.OsmNetworkReader;

public class OSM2Network {

    public static void convertOSM2Network(String inputFile, String outputFile) {

        // Create MATSim scenario and config
        Config config = ConfigUtils.createConfig();
        Scenario scenario = ScenarioUtils.createScenario(config);

        CoordinateTransformation ct = TransformationFactory.getCoordinateTransformation(
                TransformationFactory.WGS84, "EPSG:25832");

        // Read OSM file into MATSim Network
        Network network = scenario.getNetwork();
        OsmNetworkReader reader = new OsmNetworkReader(network, ct);

        reader.parse(inputFile);

        /*
         * Clean the Network. Cleaning means removing disconnected components, so that
         * afterwards there is a route from every link
         * to every other link. This may not be the case in the initial network
         * converted from OpenStreetMap.
         */
        new NetworkCleaner().run(network);

        // Write output MATSim network file
        new NetworkWriter(network).write(outputFile);

        System.out.println("Network conversion complete: " + outputFile);

    }

}
