# Structure

The root dir shall not contain files necessary for development or documentation, so that orderly work habits can be guaranteed.

- documents: papers, presentations, images 
- files: files that offer information
- code: code and logs
- .github

are the only directories in root, along with .gitignore and README.md

# How to Run

- Download and install SUMO and Python from the official sites
- Install the necessary python libraries with "pip install <lib>"

# Necessary files

 The .sumocfg file contains all the necessary information, to determine, what files will be neede to execute the simulation.

 ## SUMO-GUI

 To execute the simulation WITH a Graphical User Interface, the 'sumo_cmd' variable has to contain "sumo-gui" as its first parameter. If the simulation is to be executed without graphical interface, only use "sumo" as the first parameter.


