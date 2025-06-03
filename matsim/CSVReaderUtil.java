package org.matsim.project.v1;

import java.io.BufferedReader;
import java.io.FileReader;
import java.io.IOException;
import java.util.ArrayList;
import java.util.List;

public class CSVReaderUtil {

    public static List<POICentroid> readCoordinates(String csvFilePath) {
        List<POICentroid> coordinates = new ArrayList<>();
        String line;
        String csvSplitBy = ",";

        try (BufferedReader br = new BufferedReader(new FileReader(csvFilePath))) {
            // Skip header line
            br.readLine();

            while ((line = br.readLine()) != null) {
                String[] parts = line.split(csvSplitBy);
                if (parts.length >= 2) {
                    String x = parts[0].trim();
                    String y = parts[1].trim();
                    coordinates.add(new POICentroid(x, y));
                }
            }
        } catch (IOException e) {
            e.printStackTrace();
        }

        return coordinates;
    }
}
