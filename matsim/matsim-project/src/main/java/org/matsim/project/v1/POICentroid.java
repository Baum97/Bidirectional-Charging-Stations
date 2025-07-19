package org.matsim.project.v1;

import java.io.BufferedReader;
import java.io.FileReader;
import java.io.IOException;
import java.util.ArrayList;
import java.util.List;
import org.matsim.api.core.v01.Coord;

class POICentroid {
    double x_coord;
    double y_coord;
    private Coord transformedCoord;
    private Coord nearestPoint;
    private String nearestLinkId;

    public POICentroid(String x_coord, String y_coord) {
        this.x_coord = Double.parseDouble(x_coord);
        this.y_coord = Double.parseDouble(y_coord);
    }

    public double getX_coord() {
        return x_coord;
    }

    public double getY_coord() {
        return y_coord;
    }

    public Coord getTranformedCoord() {
        return transformedCoord;
    }

    public void setTranformedCoord(Coord transformedCoord) {
        this.transformedCoord = transformedCoord;
    }

    public String getNearestLinkId() {
        return nearestLinkId;
    }

    public void setNearestLinkId(String nearestLinkId) {
        this.nearestLinkId = nearestLinkId;
    }

    public Coord getNearestPoint() {
        return nearestPoint;
    }

    public void setNearestPoint(Coord nearestPoint) {
        this.nearestPoint = nearestPoint;
    }

    @Override
    public String toString() {
        return "X: " + x_coord + ", Y: " + y_coord;
    }
}
