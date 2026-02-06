# Home Charging Station Implementation

## Overview
5% of all electric vehicles are now assigned permanent home charging stations at their starting positions. These vehicles can charge/discharge (V2G) at home when they return.

## Key Changes Made

### 1. **Enhanced Data Structures** ([performativeMainSim2.py](performativeMainSim2.py#L50-L60))
- `vehicle_home_positions`: Maps vehicle IDs to their home coordinates (x, y)
- `home_station_positions`: Maps station IDs to their home coordinates
- `home_charging_cache`: Stores station positions with tolerance distance for quick lookup

### 2. **Improved `assign_home_charging_stations()` Function** ([performativeMainSim2.py](performativeMainSim2.py#L147-L200))
- Records each selected vehicle's starting position as their home
- Creates EVSE (charging station) objects for each home
- Pre-initializes EV objects with proper battery capacity
- Logs the home positions for debugging

### 3. **New Home Charging Logic** ([performativeMainSim2.py](performativeMainSim2.py#L415-L505))
This replaces the previous V2G logic and handles:

#### **Charging at Home:**
- Detects when vehicle is within 15m of home position AND stationary (speed < 0.2)
- Applies power ramp-up for smooth charging start
- Charges vehicle up to 95% SOC
- Tracks energy delivered during home charging sessions

#### **V2G (Vehicle-to-Grid) at Home:**
- Activates when:
  - Vehicle SOC ≥ 50%
  - Grid usage ≥ 90% capacity
- Vehicle discharges up to 50 kW to support the grid
- Reduces home station's power demand from grid

#### **Leaving Home:**
- When vehicle moves more than 15m away from home, charging session ends
- Session energy is logged

## Configuration

### Home Charging Parameters
```python
HOME_CHARGING_PERCENTAGE = 0.05           # 5% of EVs have home charging
HOME_STATION_TOLERANCE = 15.0             # meters (distance to trigger charging)
V2G_SOC_THRESHOLD = 0.50                  # Discharge if SOC > 50%
V2G_DISCHARGE_POWER_KW = 50               # Max discharge power per vehicle
GRID_CAPACITY_WARNING_THRESHOLD = 0.90    # Trigger V2G if grid at 90%
```

## How It Works

1. **Simulation Start (Step 100):**
   - Randomly selects 5% of EV vehicles
   - Records their current position as "home"
   - Creates EVSE objects for their private home stations

2. **During Simulation:**
   - Every step, checks if vehicle is at home (distance ≤ 15m, speed < 0.2)
   - If at home and SOC < 95%: charges vehicle
   - If at home and SOC ≥ 50% AND grid stressed (90%+ usage): V2G mode

3. **Energy Management:**
   - Home charging requests are registered with energy pool
   - V2G discharge reduces grid demand
   - All energy transfers tracked per session

## Output & Logging

The following logs are generated:
- `[HOME_CHARGING]`: Initial assignment of 5% of vehicles
- `[HOME_CHARGE_START]`: Vehicle arrives home
- `[HOME_CHARGE]`: Active charging at home (logged every 100 steps)
- `[V2G]`: V2G discharge active (logged every 100 steps)
- `[HOME_SESSION_END]`: Vehicle leaves home with session summary

## Files Modified

1. **performativeMainSim2.py**
   - Enhanced global state variables
   - Improved `assign_home_charging_stations()` function
   - New comprehensive home charging logic with V2G support

2. **combined_additional.xml**
   - Added reference to new `home_charging_stations.xml`

3. **home_charging_stations.xml** (NEW)
   - Placeholder XML for home charging configuration

## Benefits

✅ 5% of vehicles can charge at designated home locations
✅ V2G support allows home vehicles to stabilize grid during peak demand
✅ Proper energy tracking for all home charging sessions
✅ Smooth power ramp-up prevents grid instability
✅ Realistic modeling of home charging behavior
