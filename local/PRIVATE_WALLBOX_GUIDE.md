# Private Wallbox Implementation in SUMO

This guide shows how to create **private charging stations (wallboxes)** where each vehicle can only charge at its own dedicated wallbox.

## Key Concept

The solution uses SUMO's `vehicleTypes` attribute in charging station definitions:

```xml
<chargingStation id="wallbox_person123" 
                 lane="edge_456_0" 
                 startPos="50" 
                 endPos="55"
                 power="11000"
                 vehicleTypes="vehicleType_person123"/>
```

The `vehicleTypes` attribute restricts which vehicles can charge at this station!

## Implementation Steps

### Step 1: Create Unique Vehicle Types

Instead of using a shared `veh_ev` type for all EVs, create a unique type per person:

```xml
<routes>
  <!-- Person 1's unique vehicle type -->
  <vType id="vehicleType_person1" vClass="passenger" color="white" ...>
    <param key="has.battery.device" value="true"/>
    <param key="device.battery.capacity" value="80000"/>
    <!-- ... other battery params ... -->
  </vType>
  
  <!-- Person 2's unique vehicle type -->
  <vType id="vehicleType_person2" vClass="passenger" color="white" ...>
    <param key="has.battery.device" value="true"/>
    <param key="device.battery.capacity" value="80000"/>
    <!-- ... other battery params ... -->
  </vType>
  
  <!-- Vehicle definitions using unique types -->
  <vehicle id="person1" type="vehicleType_person1" depart="25000">
    <route edges="home_edge work_edge home_edge"/>
  </vehicle>
  
  <vehicle id="person2" type="vehicleType_person2" depart="25500">
    <route edges="home_edge work_edge home_edge"/>
  </vehicle>
</routes>
```

### Step 2: Create Private Wallboxes

Each EV owner gets a wallbox at their residential POI, restricted to their vehicle type:

```xml
<additional>
  <!-- Person 1's private wallbox - ONLY accepts vehicleType_person1 -->
  <chargingStation id="wallbox_person1" 
                   lane="residential_edge_789_0" 
                   startPos="45.5" 
                   endPos="50.5"
                   power="11000"
                   efficiency="0.95"
                   chargeInTransit="0"
                   chargeDelay="0"
                   vehicleTypes="vehicleType_person1"/>
  
  <!-- Person 2's private wallbox - ONLY accepts vehicleType_person2 -->
  <chargingStation id="wallbox_person2" 
                   lane="residential_edge_456_0" 
                   startPos="60.0" 
                   endPos="65.0"
                   power="11000"
                   efficiency="0.95"
                   chargeInTransit="0"
                   chargeDelay="0"
                   vehicleTypes="vehicleType_person2"/>
  
  <!-- You can also have public charging stations that accept ALL EV types -->
  <chargingStation id="public_cs_001" 
                   lane="highway_edge_123_0" 
                   startPos="100" 
                   endPos="110"
                   power="50000"
                   efficiency="0.90"
                   chargeInTransit="0"
                   chargeDelay="200"
                   vehicleTypes="vehicleType_person1 vehicleType_person2"/>
                   <!-- Space-separated list for multiple types -->
</additional>
```

### Step 3: Update Your SUMO Configuration

Add both files to your `sim.sumocfg`:

```xml
<configuration>
  <input>
    <net-file value="osm.net.xml.gz"/>
    <route-files value="osm.passenger.trips.xml"/>
    <additional-files value="private_wallboxes.xml,osm.chargingstations.xml"/>
  </input>
  <time>
    <begin value="0"/>
    <end value="86400"/>
  </time>
</configuration>
```

## Using the Implementation

### Quick Start

```bash
cd local
python generate_private_wallboxes.py
```

This will:
1. ✓ Generate trips with unique vehicle types for each EV owner
2. ✓ Create private wallboxes at each residential location
3. ✓ Restrict each wallbox to only accept its owner's vehicle

### Integration with Existing Code

To integrate into your existing pipeline, modify `biflex_local_runner.py`:

```python
# After generating trips
from generate_private_wallboxes import generate_private_wallboxes, generate_trips_with_private_wallboxes

# Replace the standard trip generation
trips_file, persons_data = generate_trips_with_private_wallboxes(
    net_file, 
    edge_files, 
    scen_dir
)

# Generate private wallboxes
wallbox_file = generate_private_wallboxes(
    net_file,
    persons_data,
    scen_dir
)

# Update combined_additional.xml to include wallboxes
```

## Advanced: Multiple Charging Station Types

You can combine private and public charging:

```xml
<additional>
  <!-- PRIVATE: Home wallbox - only person123's vehicle -->
  <chargingStation id="wallbox_person123" 
                   vehicleTypes="vehicleType_person123"
                   power="11000"/>
  
  <!-- SEMI-PRIVATE: Office parking - only employees -->
  <chargingStation id="office_charger_1" 
                   vehicleTypes="vehicleType_person123 vehicleType_person456"
                   power="22000"/>
  
  <!-- PUBLIC: Highway fast charger - all EVs -->
  <chargingStation id="fastcharger_highway" 
                   vehicleTypes="vehicleType_person1 vehicleType_person2 ... vehicleType_person250"
                   power="150000"/>
  
  <!-- UNRESTRICTED: If no vehicleTypes attribute, all vehicles can use it -->
  <chargingStation id="unrestricted_charger"
                   power="50000"/>
</additional>
```

## Key Parameters Explained

- **`vehicleTypes`**: Space-separated list of allowed vehicle type IDs. **This is the key feature!**
- **`power`**: Charging power in Watts
  - 11000 W = 11 kW (typical home wallbox)
  - 22000 W = 22 kW (faster home/office wallbox)
  - 50000 W = 50 kW (public DC fast charger)
  - 150000 W = 150 kW (highway supercharger)
- **`chargeInTransit`**: "0" = vehicle must stop, "1" = can charge while moving
- **`chargeDelay`**: Delay before charging starts (seconds)
- **`efficiency`**: Charging efficiency (0.0-1.0)

## Verification

To verify it's working, check your SUMO simulation output:

1. **Check vehicle types** in the simulation:
   ```bash
   grep "vehicleType_person" osm.passenger.trips.xml | head
   ```

2. **Check wallbox restrictions**:
   ```bash
   grep "vehicleTypes=" private_wallboxes.xml | head
   ```

3. **Watch simulation**: Only the vehicle with `vehicleType_person123` will be able to charge at `wallbox_person123`

## Benefits of This Approach

✅ **Realistic V2G scenarios** - Each home has its own wallbox  
✅ **Privacy modeling** - Vehicles only charge at their own home  
✅ **Flexible control** - Easy to add shared charging (family, workplace)  
✅ **Scalable** - Works with hundreds or thousands of vehicles  
✅ **SUMO native** - Uses built-in vehicleTypes restriction feature

## Troubleshooting

**Q: My vehicle isn't charging at any station**  
A: Make sure the vehicle's type matches at least one charging station's `vehicleTypes` list

**Q: How do I allow a vehicle to use multiple stations?**  
A: Use the same vehicle type in multiple charging station definitions

**Q: Can I have public stations too?**  
A: Yes! List all vehicle types in the public station's `vehicleTypes` attribute, or omit it entirely

**Q: How do I add family sharing (2 cars, 1 wallbox)?**  
A: Give both vehicles the same vehicle type, or list both types in the wallbox:
```xml
vehicleTypes="vehicleType_person123 vehicleType_person124"
```
