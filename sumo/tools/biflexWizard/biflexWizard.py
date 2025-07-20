#!/usr/bin/env python

'''
The goal of this script is to implement SAGA into the osmWebWizard by official SUMO.
'''

from webWizard.SimpleWebSocketServer import SimpleWebSocketServer, WebSocket
import json
import threading
import webbrowser
import os
import datetime
import osmGet
import sys

# Add saga folder to the python path (have to find better solution later in developement)
sys.path.append(os.path.abspath("D:/SUMOActivityGen"))
import scenarioFromOSM

print("Welcome to BIFLEX!")

class Builder(object):

    prefix = "biflex_osm"

    def __init__(self, data, local):
        self.files = {}
        self.files_relative = {}
        self.data = data

        # Save everything inside ./output/
        output_base = "output"
        os.makedirs(output_base, exist_ok=True)

        folder_name = data.get("outputDir", datetime.datetime.now().strftime("%Y-%m-%d-%H-%M-%S"))
        self.tmp = os.path.abspath(os.path.join(output_base, folder_name))
        os.makedirs(self.tmp, exist_ok=data.get("outputDirExistOk", False))

        self.origDir = os.getcwd()
        print(f'Saving files in {self.tmp}')

    def filename(self, key, suffix):
        path = os.path.join(self.tmp, self.prefix + suffix)
        self.files[key] = path

    def getOSM(self):
        self.filename("biflex_osm", "_bbox.osm.xml")

        # self.report("Downloading map data")
        print("Downloading map data")

        # create string for osmGet
        osmArgs = ["-b=" + ",".join(map(str, self.data["coords"])), "-p", self.prefix, "-d", self.tmp]
        print("osmArgs:", osmArgs)

        if self.data.get("poly"):
            osmArgs.append("--shapes")
        if 'osmMirror' in self.data:
            osmArgs += ["-u", self.data["osmMirror"]]
        if 'roadTypes' in self.data:
            osmArgs += ["-r", json.dumps(self.data["roadTypes"])]

        osmGet.get(osmArgs)

        if os.path.exists(self.tmp):
            print("Successfully downloaded OSM-map")
        elif not os.path.exists(self.tmp):
            print("Download failed")

        self.startSAGA()

    def startSAGA(self):
        print("Starting SAGA. Hopefully this goes well!")

        scenarioFromOSM.main([
            '--osm', self.files["biflex_osm"], # .osm-file itself
            '--out', self.tmp, # folder
        ])



class OSMImporterWebSocket(WebSocket):

    local = False
    outputDir = None

    def report(self, message):
        print(message)
        self.sendMessage(u"report " + message)
        self.steps -= 1

    def handleMessage(self):
        data = json.loads(self.data)
        thread = threading.Thread(target=self.build, args=(data,))
        thread.start()

    def build(self, data):
        # debugging
        print("JSON Payload received by Builder:\n", json.dumps(data, indent=4))

        builder = Builder(data, self.local)
        # builder.report = self.report
        builder.getOSM()


def main():
    webbrowser.open("file://" + os.path.join(os.path.dirname(os.path.abspath(__file__)), "app", "index.html"))
    print("Starting WebSocket server at ws://localhost:8010")
    server = SimpleWebSocketServer('localhost', 8010, OSMImporterWebSocket)
    server.serveforever()


if __name__ == "__main__":
    main()
