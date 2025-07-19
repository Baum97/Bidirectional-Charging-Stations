package org.matsim.project.v1;

import org.matsim.project.utils.Net;
import org.xml.sax.Attributes;
import org.xml.sax.SAXException;
import org.xml.sax.helpers.DefaultHandler;

import javax.xml.parsers.SAXParser;
import javax.xml.parsers.SAXParserFactory;
import javax.xml.stream.XMLOutputFactory;
import javax.xml.stream.XMLStreamWriter;
import java.io.FileInputStream;
import java.io.FileWriter;
import java.text.SimpleDateFormat;
import java.util.*;

public class MatsimPlans2SumoTrips {

    static class TripData {
        String personId;
        double fromX, fromY, toX, toY;
        String departTime;
    }

    public static void main(String[] args) throws Exception {
        String plansPath = "plans.xml";
        String netPath = "map.net.xml";
        String tripsPath = "matsim_trips.xml";

        Net net = new Net(netPath);

        // Liste zum Speichern der extrahierten Trips
        List<TripData> trips = new ArrayList<>();

        // XML-Parser für MATSim plans.xml
        SAXParserFactory factory = SAXParserFactory.newInstance();
        SAXParser saxParser = factory.newSAXParser();

        saxParser.parse(new FileInputStream(plansPath), new DefaultHandler() {
            TripData currentTrip = null;
            boolean inSelectedPlan = false;
            int activityCount = 0;

            public void startElement(String uri, String localName, String qName, Attributes attributes) throws SAXException {
                switch (qName) {
                    case "person":
                        currentTrip = new TripData();
                        currentTrip.personId = attributes.getValue("id");
                        break;
                    case "plan":
                        inSelectedPlan = "yes".equals(attributes.getValue("selected"));
                        activityCount = 0;
                        break;
                    case "activity":
                        if (inSelectedPlan) {
                            double x = Double.parseDouble(attributes.getValue("x"));
                            double y = Double.parseDouble(attributes.getValue("y"));
                            if (activityCount == 0) {
                                currentTrip.fromX = x;
                                currentTrip.fromY = y;
                                currentTrip.departTime = attributes.getValue("end_time");
                            } else if (activityCount == 1) {
                                currentTrip.toX = x;
                                currentTrip.toY = y;
                            }
                            activityCount++;
                        }
                        break;
                    case "leg":
                        // Nur car-Modus berücksichtigen
                        if (inSelectedPlan && !"car".equals(attributes.getValue("mode"))) {
                            inSelectedPlan = false; // ignoriere diesen Plan
                        }
                        break;
                }
            }

            public void endElement(String uri, String localName, String qName) throws SAXException {
                if ("plan".equals(qName) && inSelectedPlan && activityCount >= 2) {
                    trips.add(currentTrip);
                }
            }
        });

        System.out.println("Gefundene Trips: " + trips.size());

        // XML-Schreiber für SUMO trips.xml
        XMLOutputFactory xof = XMLOutputFactory.newInstance();
        XMLStreamWriter xtw = xof.createXMLStreamWriter(new FileWriter(tripsPath));

        xtw.writeStartDocument("UTF-8", "1.0");
        xtw.writeStartElement("trips");

        for (TripData trip : trips) {
            String fromEdge = net.getNearestEdge(trip.fromX, trip.fromY);
            String toEdge = net.getNearestEdge(trip.toX, trip.toY);
            if (fromEdge == null || toEdge == null) continue;

            int depart = parseTimeToSeconds(trip.departTime);

            xtw.writeEmptyElement("trip");
            xtw.writeAttribute("id", trip.personId);
            xtw.writeAttribute("type", "car");
            xtw.writeAttribute("depart", String.valueOf(depart));
            xtw.writeAttribute("from", fromEdge);
            xtw.writeAttribute("to", toEdge);
        }

        xtw.writeEndElement(); // </trips>
        xtw.writeEndDocument();
        xtw.close();

        System.out.println("✅ `trips.xml` erfolgreich geschrieben: " + tripsPath);
    }

    // Hilfsmethode zur Zeitumrechnung von HH:mm:ss zu Sekunden
    static int parseTimeToSeconds(String time) {
        if (time == null) return 0;
        try {
            if (time.contains(":")) {
                SimpleDateFormat sdf = new SimpleDateFormat("HH:mm:ss");
                Date date = sdf.parse(time);
                Calendar cal = Calendar.getInstance();
                cal.setTime(date);
                return cal.get(Calendar.HOUR_OF_DAY) * 3600 + cal.get(Calendar.MINUTE) * 60 + cal.get(Calendar.SECOND);
            } else {
                return (int) Double.parseDouble(time);
            }
        } catch (Exception e) {
            return 0;
        }
    }
}
