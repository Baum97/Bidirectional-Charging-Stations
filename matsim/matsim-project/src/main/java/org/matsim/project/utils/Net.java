package org.matsim.project.utils;

import java.io.*;
import java.util.*;
import javax.xml.parsers.*;
import org.w3c.dom.*;

public class Net {
    private final Map<String, double[]> edgeCoords = new HashMap<>();

    public Net(String netFile) throws Exception {
        DocumentBuilderFactory dbf = DocumentBuilderFactory.newInstance();
        Document doc = dbf.newDocumentBuilder().parse(new File(netFile));
        NodeList edges = doc.getElementsByTagName("edge");

        for (int i = 0; i < edges.getLength(); i++) {
            Element e = (Element) edges.item(i);
            if (e.hasAttribute("id") && !e.getAttribute("id").startsWith(":")) {
                NodeList lanes = e.getElementsByTagName("lane");
                if (lanes.getLength() > 0) {
                    Element lane = (Element) lanes.item(0);
                    String shape = lane.getAttribute("shape");
                    String[] coords = shape.split(" ")[0].split(",");
                    double x = Double.parseDouble(coords[0]);
                    double y = Double.parseDouble(coords[1]);
                    edgeCoords.put(e.getAttribute("id"), new double[]{x, y});
                }
            }
        }
    }

    public String getNearestEdge(double x, double y) {
        String bestEdge = null;
        double minDist = Double.MAX_VALUE;
        for (Map.Entry<String, double[]> entry : edgeCoords.entrySet()) {
            double[] coord = entry.getValue();
            double dist = Math.pow(coord[0] - x, 2) + Math.pow(coord[1] - y, 2);
            if (dist < minDist) {
                minDist = dist;
                bestEdge = entry.getKey();
            }
        }
        return bestEdge;
    }
}
