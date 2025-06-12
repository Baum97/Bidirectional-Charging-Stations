package org.matsim.project;

import org.matsim.contrib.otfvis.OTFVis;
import org.matsim.vis.otfvis.OTFClientLive;

public class ViewResults {
    public static void main(String[] args) {
        OTFVis.playMVI("output/ITERS/it.10/10.otfvis.mvi");
    }
}