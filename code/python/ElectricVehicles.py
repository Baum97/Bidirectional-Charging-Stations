class ElectricVehicles:
    """
    Lightweight EV model used by performativeMainSim.py.

    Notes / assumptions:
    - The code tries to be tolerant to units coming from SUMO. The class stores
      battery capacity in kWh (`batterycapacity_kWh`) and `actualBatteryCapacity`
      in Wh to match usages in the repo.
    - `chargevehicle(..., kw=...)` expects `kw` in kW and `dt` in seconds.
    """

    def __init__(self, vehicle_type="bev", arrival_time=0.0, initial_soc=0.5, batterycapacity_kwh=50.0):
        self.vehicle_type = vehicle_type
        self.arrival_time = arrival_time

        # batterycapacity_kwh is expected in kWh (common convention in the repo)
        self.batterycapacity_kWh = float(batterycapacity_kwh)

        # actualBatteryCapacity stored in Wh for compatibility with other helpers
        self.actualBatteryCapacity = float(initial_soc) * self.batterycapacity_kWh * 1000.0

        # state vars used by performativeMainSim
        self.soc = float(initial_soc)
        self.packvoltage = 400.0      # nominal pack voltage (V)
        self.packpower = 0.0          # instantaneous pack power (W)
        self.readytocharge = True
        self.target_soc = 0.95
        
        # Home charging station support (V2G)
        self.home_station_id = None   # ID of home charging station (if any)
        self.start_position = None    # (x, y) tuple for home location
        self.is_at_home = False       # whether currently at home location

    def update_soc_from_sumo(self, actual, maximum):
        """
        Update SOC from SUMO parameters. `actual` and `maximum` are taken
        as the same units and a ratio is computed. The method also updates
        internal battery capacity if `maximum` looks like Wh/kWh.
        """
        try:
            actual_f = float(actual)
            maximum_f = float(maximum)
            # compute soc as ratio
            if maximum_f > 0:
                self.soc = actual_f / maximum_f
            else:
                self.soc = 0.0

            # store actualBatteryCapacity in Wh; if maximum looks like kWh (small),
            # assume maximum_f is kWh and convert to Wh; heuristic:
            if maximum_f < 1000:
                # treat maximum_f as kWh
                cap_kwh = maximum_f
                self.batterycapacity_kWh = cap_kwh
                self.actualBatteryCapacity = self.soc * cap_kwh * 1000.0
            else:
                # treat maximum_f as Wh
                cap_wh = maximum_f
                self.batterycapacity_kWh = cap_wh / 1000.0
                self.actualBatteryCapacity = actual_f
        except Exception:
            pass

    def chargevehicle(self, simulationtime, dt=1.0, kw=0.0):
        """
        Apply charging energy for `dt` seconds at `kw` kW (delivered to vehicle).
        Updates `actualBatteryCapacity`, `packpower` and `soc`.
        """
        try:
            power_w = float(kw) * 1000.0
            # energy added in Wh
            energy_added_wh = power_w * float(dt) / 3600.0

            # apply energy (do not exceed target soc)
            cap_wh = max(0.0, self.batterycapacity_kWh * 1000.0)
            new_energy = self.actualBatteryCapacity + energy_added_wh
            max_allowed = self.target_soc * cap_wh
            if new_energy > max_allowed:
                energy_added_wh = max(0.0, max_allowed - self.actualBatteryCapacity)
                new_energy = self.actualBatteryCapacity + energy_added_wh

            self.actualBatteryCapacity = new_energy
            self.packpower = power_w
            if cap_wh > 0:
                self.soc = min(self.actualBatteryCapacity / cap_wh, 1.0)
            else:
                self.soc = 0.0

            return energy_added_wh
        except Exception:
            return 0.0

    def dischargevehicle(self, simulationtime, dt=1.0, kw=0.0):
        """
        Apply discharging energy for `dt` seconds at `kw` kW (delivered FROM vehicle to grid).
        Updates `actualBatteryCapacity`, `packpower` and `soc`.
        Respects minimum SOC of 20% (vehicle stays operational).
        """
        try:
            power_w = float(kw) * 1000.0
            # energy removed in Wh
            energy_removed_wh = power_w * float(dt) / 3600.0

            # do not discharge below 20% SOC
            cap_wh = max(0.0, self.batterycapacity_kWh * 1000.0)
            min_allowed = 0.2 * cap_wh
            new_energy = self.actualBatteryCapacity - energy_removed_wh
            if new_energy < min_allowed:
                energy_removed_wh = max(0.0, self.actualBatteryCapacity - min_allowed)
                new_energy = self.actualBatteryCapacity - energy_removed_wh

            self.actualBatteryCapacity = new_energy
            self.packpower = -power_w  # negative for discharge
            if cap_wh > 0:
                self.soc = max(self.actualBatteryCapacity / cap_wh, 0.0)
            else:
                self.soc = 0.0

            return energy_removed_wh
        except Exception:
            return 0.0

    def __repr__(self):
        return f"<ElectricVehicles soc={self.soc:.3f} cap_kWh={self.batterycapacity_kWh}>"