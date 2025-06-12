package org.matsim.project;

import org.matsim.api.core.v01.Scenario;
import org.matsim.api.core.v01.network.Network;
import org.matsim.core.config.Config;
import org.matsim.core.config.ConfigUtils;
import org.matsim.core.network.algorithms.NetworkCleaner;
import org.matsim.core.network.io.NetworkWriter;
import org.matsim.core.scenario.ScenarioUtils;
import org.matsim.core.utils.io.OsmNetworkReader;
import org.matsim.core.utils.geometry.CoordinateTransformation;
import org.matsim.core.utils.geometry.transformations.TransformationFactory;
import java.io.File;

public class OSM2Network {
    public static void main(String[] args) {
        // String osmFile = "D:\\matsim-example-project\\Kernen.osm"; // Accepts .osm or
        // .osm.pbf
        String osmFile = "D:\\matsim-example-project\\welzheim.osm";

        File outputDirectory = new File("input-erik");
        if (!outputDirectory.exists()) {
            outputDirectory.mkdirs();
        }
        String outputNetwork = "input-erik/network.xml.gz";

        // Create MATSim scenario and config
        Config config = ConfigUtils.createConfig();
        Scenario scenario = ScenarioUtils.createScenario(config);

        // Use proper coordinate transformation (adjust to your region if needed)
        CoordinateTransformation ct = TransformationFactory.getCoordinateTransformation(
                TransformationFactory.WGS84, TransformationFactory.WGS84_Albers);

        // Read OSM file into MATSim Network
        Network network = scenario.getNetwork();
        OsmNetworkReader reader = new OsmNetworkReader(network, ct);

        reader.parse(osmFile);

        /*
         * Clean the Network. Cleaning means removing disconnected components, so that
         * afterwards there is a route from every link
         * to every other link. This may not be the case in the initial network
         * converted from OpenStreetMap.
         */
        new NetworkCleaner().run(network);

        // Write output MATSim network file
        new NetworkWriter(network).write(outputNetwork);

        System.out.println("Network conversion complete: " + outputNetwork);
    }
}
