# Private Wallbox Integration - Implementation Summary

## ✅ Changes Made to biflex_local_runner.py

The local runner has been updated to automatically generate **private wallboxes** with vehicle-specific access control.

### Modified Pipeline Steps

#### Step 5: Trip Generation (Modified)
- **Before**: Used `generate_trips()` - all EVs had shared `veh_ev` type
- **After**: Uses `generate_trips_with_private_wallboxes()` 
  - Creates **unique vehicle type** for each EV owner (`vehicleType_person1`, `vehicleType_person2`, etc.)
  - Returns both trips file AND persons data needed for wallbox generation
  - Each vehicle type has full battery configuration and device settings

#### Step 6: Private Wallbox Generation (NEW)
- **New function**: `generate_private_wallboxes()`
- Creates one wallbox per EV owner at their residential location
- Each wallbox restricted to accept **only its owner's vehicle type**
- Wallbox specs:
  - Power: 11 kW (typical home wallbox)
  - Efficiency: 95%
  - Location: At home edge of each EV owner
  - ID format: `wallbox_person1`, `wallbox_person2`, etc.

#### Step 7: Public Charging Stations (Unchanged)
- Still generates public charging stations using `generate_charging_stations()`
- These remain **unrestricted** - all vehicles can use them
- Power: 200 kW (fast chargers)

#### Step 8: Configuration Update (Modified)
- SUMO config now includes **three** additional files:
  1. `combined_additional.xml` (default infrastructure)
  2. `private_wallboxes.xml` (NEW - private wallboxes)
  3. `osm.chargingstations.xml` (public stations)

#### Configuration Changes
- Removed `device.*.explicit` settings (were hardcoded to `veh_ev`)
- Now relies on per-vType device configuration (cleaner approach)
- Battery, rerouting, and stationfinder devices configured in each vehicle type

## 📂 New Files Created

### 1. generate_private_wallboxes.py
Complete implementation with three main functions:
- `generate_trips_with_private_wallboxes()` - Creates unique vehicle types
- `generate_private_wallboxes()` - Generates restricted wallboxes
- `generate_complete_scenario_with_wallboxes()` - Full pipeline

### 2. PRIVATE_WALLBOX_GUIDE.md
Comprehensive documentation explaining:
- The `vehicleTypes` attribute concept
- How to implement private wallboxes
- Examples for different scenarios
- Troubleshooting tips

### 3. generate_public_charging_stations.py
Enhanced version supporting vehicle type restrictions on public stations (optional)

## 🔄 How It Works Now

### Scenario Generation Flow
```
1. Download OSM data
2. Build SUMO network
3. Extract POIs (offices, residential)
4. Assign POIs to edges
5. Generate trips with UNIQUE vehicle types per person ⭐
6. Generate PRIVATE wallboxes (restricted access) ⭐
7. Generate PUBLIC charging stations (unrestricted)
8. Combine all additional files
9. Create SUMO config with all charging infrastructure
10. Run simulation
11. Process results
```

### Vehicle Type Structure
```xml
<!-- Person 1's unique type -->
<vType id="vehicleType_person1" ...>
  <param key="has.battery.device" value="true"/>
  <param key="has.stationfinder.device" value="true"/>
  <!-- ... all EV params ... -->
</vType>

<!-- Person 1's vehicle -->
<vehicle id="person1" type="vehicleType_person1" .../>
```

### Wallbox Structure
```xml
<!-- Person 1's private wallbox -->
<chargingStation id="wallbox_person1" 
                 lane="residential_edge_0" 
                 startPos="50" 
                 endPos="55"
                 power="11000"
                 vehicleTypes="vehicleType_person1"/>
                 ⬆️ Only person1's vehicle can charge here!
```

## 🎯 Result

Each EV owner now has:
- ✅ Unique vehicle type (`vehicleType_personX`)
- ✅ Private wallbox at home (`wallbox_personX`)
- ✅ Exclusive access to their own wallbox
- ✅ Ability to use public charging stations
- ✅ Realistic V2G/bidirectional charging scenario

## 🚀 Usage

Just run the scenario generation as before:

```bash
# In the UI, select area and click "Download OSM Data"
# Or via API:
curl -X POST http://localhost:8787/build \
  -H "Content-Type: application/json" \
  -d '{"bbox": [13.4, 52.49, 13.43, 52.51], "scenario": "test_wallboxes"}'
```

The pipeline automatically:
1. Creates unique vehicle types for each EV
2. Generates private wallboxes with access restrictions
3. Includes them in the simulation config

## 📊 API Response

The response now includes wallbox information:
```json
{
  "ok": true,
  "message": "Pipeline completed successfully with private wallboxes",
  "privateWallboxes": {
    "file": "private_wallboxes.xml",
    "count": 150,
    "description": "Private wallboxes restricted to vehicle owner"
  },
  "publicChargingStations": {
    "file": "osm.chargingstations.xml",
    "description": "Public charging stations (unrestricted)"
  }
}
```

## 🔍 Verification

To verify the implementation:

### Check unique vehicle types:
```bash
grep "vType id=\"vehicleType_" osm.passenger.trips.xml | head -5
```

Expected output:
```xml
<vType id="vehicleType_person1" ...>
<vType id="vehicleType_person2" ...>
<vType id="vehicleType_person3" ...>
```

### Check wallbox restrictions:
```bash
grep "vehicleTypes=" private_wallboxes.xml | head -5
```

Expected output:
```xml
<chargingStation id="wallbox_person1" ... vehicleTypes="vehicleType_person1"/>
<chargingStation id="wallbox_person2" ... vehicleTypes="vehicleType_person2"/>
<chargingStation id="wallbox_person3" ... vehicleTypes="vehicleType_person3"/>
```

### Check SUMO config:
```bash
grep "additional-files" sim.sumocfg
```

Expected output:
```xml
<additional-files value="combined_additional.xml,private_wallboxes.xml,osm.chargingstations.xml"/>
```

## 💡 Benefits

1. **Realistic V2G modeling** - Each home has its own charging infrastructure
2. **Privacy & ownership** - Vehicles only charge at their designated locations
3. **Flexible scenarios** - Easy to add shared access (family, workplace)
4. **Scalable** - Works with hundreds/thousands of vehicles
5. **SUMO native** - Uses built-in `vehicleTypes` restriction feature

## 🔧 Customization Options

### Share wallbox between family members:
Modify wallbox to accept multiple types:
```xml
vehicleTypes="vehicleType_person1 vehicleType_person2"
```

### Add workplace charging:
Create semi-private stations for office employees in the wallbox generation function.

### Adjust wallbox power:
Modify `power="11000"` in `generate_private_wallboxes()` (11kW typical, can go up to 22kW)

### Change public station power:
Modify `power="200000"` in `mainGenerateChargingStations.py` for different fast-charging speeds

## 📝 Notes

- The implementation preserves backward compatibility
- Non-EV vehicles still use the standard `veh_passenger` type
- Public charging stations remain unrestricted by default
- Device configurations are now managed per-vType (cleaner than global explicit settings)
- EV share configurable in `generate_private_wallboxes.py` (default 60%)

## 🎓 Next Steps

1. **Test the implementation**: Run a scenario and check the generated files
2. **Visualize results**: Use SUMO-GUI to see vehicles charging at their private wallboxes
3. **Analyze V2G potential**: Process battery logs to understand charging patterns
4. **Customize**: Adjust parameters for your specific use case

For more details, see [PRIVATE_WALLBOX_GUIDE.md](PRIVATE_WALLBOX_GUIDE.md)
