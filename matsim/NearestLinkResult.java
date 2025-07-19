package org.matsim.project.v1;

import org.matsim.api.core.v01.Coord;
import org.matsim.api.core.v01.network.Link;

public class NearestLinkResult {
    private final Link link;
    private final Coord nearestPoint;

    public NearestLinkResult(Link link, Coord nearestPoint) {
        this.link = link;
        this.nearestPoint = nearestPoint;
    }

    public Link getLink() {
        return link;
    }

    public Coord getNearestPoint() {
        return nearestPoint;
    }
}
