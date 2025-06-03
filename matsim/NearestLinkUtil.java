package org.matsim.project.v1;

/*
1. This is a simplistic nearest-link search based on point-to-link coordinate comparison.
It doesn’t consider the actual geometry of the link (like the middle of a line segment), only the link’s coordinate.

2. MATSim’s Link.getCoord() often returns the link’s midpoint, but this can vary depending on the network construction.

3. For large networks, this is a linear search, which can be slow — you might use spatial indexing (like QuadTrees) for better performance.

=> Instead of using the end node => use vector projection for real nearest point on link!

 */

import org.matsim.api.core.v01.Coord;
import org.matsim.api.core.v01.network.Link;
import org.matsim.api.core.v01.network.Network;
import org.matsim.core.utils.collections.QuadTree;

public class NearestLinkUtil {
    private final QuadTree<Link> quadTree;

    public NearestLinkUtil(Network network) {
        this.quadTree = buildQuadTree(network);
    }

    private QuadTree<Link> buildQuadTree(Network network) {
        double minX = Double.POSITIVE_INFINITY;
        double minY = Double.POSITIVE_INFINITY;
        double maxX = Double.NEGATIVE_INFINITY;
        double maxY = Double.NEGATIVE_INFINITY;

        for (Link link : network.getLinks().values()) {
            Coord from = link.getFromNode().getCoord();
            Coord to = link.getToNode().getCoord();
            minX = Math.min(minX, Math.min(from.getX(), to.getX()));
            minY = Math.min(minY, Math.min(from.getY(), to.getY()));
            maxX = Math.max(maxX, Math.max(from.getX(), to.getX()));
            maxY = Math.max(maxY, Math.max(from.getY(), to.getY()));
        }

        QuadTree<Link> qt = new QuadTree<>(minX, minY, maxX, maxY);
        for (Link link : network.getLinks().values()) {
            // For better spatial indexing, add both nodes or the mid-point
            Coord from = link.getFromNode().getCoord();
            Coord to = link.getToNode().getCoord();
            qt.put(from.getX(), from.getY(), link);
            qt.put(to.getX(), to.getY(), link);
        }

        return qt;
    }

    public Link findNearestLink(Coord coord) {
        return quadTree.getClosest(coord.getX(), coord.getY());
    }

    public Coord findNearestPointOnLink(Link link, Coord point) {
        Coord from = link.getFromNode().getCoord();
        Coord to = link.getToNode().getCoord();

        double x0 = point.getX();
        double y0 = point.getY();
        double x1 = from.getX();
        double y1 = from.getY();
        double x2 = to.getX();
        double y2 = to.getY();

        double dx = x2 - x1;
        double dy = y2 - y1;
        double lenSquared = dx * dx + dy * dy;

        if (lenSquared == 0) {
            // Link is a point
            return new Coord(x1, y1);
        }

        double t = ((x0 - x1) * dx + (y0 - y1) * dy) / lenSquared;
        t = Math.max(0, Math.min(1, t)); // Clamp t to [0,1]

        double xNearest = x1 + t * dx;
        double yNearest = y1 + t * dy;

        return new Coord(xNearest, yNearest);
    }
}