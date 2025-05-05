netconvert --matsim myMATsimNetwork.xml -o mySUMOnetwork.net.xml

python .\tools\import\matsim\matsim_importPlans.py --plan-file .\from-matsim\plans.xml -o routes.rou.xml

sumo-gui -c ....sumocfg
