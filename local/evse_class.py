

class EVSE_class():
    def __init__(self, efficiency, Prated_kW, evse_id, energy_pool=None, is_private=False, allowed_vehicle_id=None):
        self.efficiency = efficiency
        self.Prated_kW  = Prated_kW
        self.evse_id   = evse_id
        # Reference to global energy pool or grid controller
        # Both implement the same interface: get_available_power_for_station()
        self.energy_pool = energy_pool  # Can be EnergyPool or GridController
        
        # Private home charging station support
        self.is_private = is_private                    # True if this is a private home station
        self.allowed_vehicle_id = allowed_vehicle_id    # only this vehicle can use it
        self.supports_v2g = is_private                  # V2G only for private home stations

        self.ev_voltage = 0.0
        self.ev_power   = 0.0
        self.ev_soc     = 0.0
        self.ev_plugged = False
        self.state      = 'A'

        self.server_setpoint = 0.0
        self.is_discharging = False    # V2G mode flag
        self.charging_process = None

    def getPrated_kw(self):
        return self.Prated_kW

    def getEfficiency(self):
        return self.efficiency

    def receive_from_ev(self, Vbatt, Pbatt_kW, soc, plugged, ready):
        ### receive Vbatt, Pbatt, SOC, plugged via TCP or something if there needs a connection
        self.ev_voltage = Vbatt
        self.ev_power   = Pbatt_kW
        self.ev_soc     = soc
        self.ev_plugged = plugged
        self.ev_ready   = ready

        if self.ev_plugged and self.ev_power < 0.1:
            self.state = 'B'
        if self.ev_plugged and self.ev_power >= 0.1:
            self.state = 'C'
        if not self.ev_plugged:
            self.state = 'A'


    def send_to_ev(self):
        if self.ev_ready:
            if not self.is_discharging:
                # Charging mode: get power from grid
                available_power = self.server_setpoint
                if self.energy_pool:
                    available_power = self.energy_pool.get_available_power_for_station(self.evse_id, self.server_setpoint)
                    if available_power < self.server_setpoint:
                        available_power *= self.efficiency  # apply efficiency to scaled power
                Pmax = min(available_power* self.efficiency, self.curr_power)
            else:
                # V2G mode: request discharge power
                Pmax = -min(self.server_setpoint, self.curr_power)  # negative = discharge
        else:
            Pmax = 0.0

        ### send Pmax via TCP or something if there needs a connection
        return Pmax

    def set_ChargingProcess(self, charging_process):
        self.charging_process = charging_process

    def reset_ChargingProcess(self):
        self.charging_process = None


    def receive_from_server(self, setpoint_kW):
        self.server_setpoint = setpoint_kW


    def set_discharge_mode(self, enabled):
        """
        Enable or disable V2G (discharge) mode for this station.
        """
        if self.supports_v2g:
            self.is_discharging = enabled


    def send_to_server(self):
        Vbatt    = self.ev_voltage
        Pbatt_kW = self.ev_power
        soc      = self.ev_soc
        
        return [Vbatt, Pbatt_kW, soc]

    def compute_power(self, curr_time):
        power = self.charging_process.get_power_at_time(curr_time)
        self.curr_power = power
        return power


class EnergyPool:
    """
    Global energy pool that manages total available power for all charging stations.
    Limits the total power draw when too many vehicles are charging.
    """
    def __init__(self, max_total_power_kw):
        """
        Args:
            max_total_power_kw: Maximum total power available from the grid/source (in kW)
        """
        self.max_total_power_kw = max_total_power_kw
        self.station_requests = {}  # station_id -> requested_power_kw
        self.station_setpoints = {}  # station_id -> currently allocated power_kw
        self._previous_total_demand = 0  # Total demand from previous step (for fair scaling)
    
    def register_station_request(self, station_id, requested_power_kw):
        """
        Register a station's power request. Called before calculating distribution.
        """
        self.station_requests[station_id] = max(0.0, requested_power_kw)
    
    def get_available_power_for_station(self, station_id, requested_power_kw):
        """
        Calculate available power for a station based on total demand.
        Uses fair distribution: if total demand exceeds max, scale proportionally.
        
        Args:
            station_id: ID of the charging station
            requested_power_kw: Power requested by this station (kW)
        
        Returns:
            Available power for this station (kW)
        """
        requested_power_kw = max(0.0, requested_power_kw)
        
        # Calculate total requested power from all active stations
        # Use max of current and previous step's demand for fair scaling
        # (prevents race condition where early stations get more power)
        current_total = sum(self.station_requests.values())
        total_requested = max(current_total, self._previous_total_demand)
        
        # If no demand or within limits, grant full request
        if total_requested <= self.max_total_power_kw:
            return requested_power_kw
        
        # Power is limited: scale proportionally
        scale_factor = self.max_total_power_kw / total_requested
        available = requested_power_kw * scale_factor
        
        return available

    #def get_current_current(self, simulation_time, ):

    def reset_requests(self):
        """
        Clear all station requests and actuals at the start of each time step.
        Preserves previous step's total demand for fair scaling.
        """
        self._previous_total_demand = sum(self.station_requests.values())
        self.station_requests.clear()
        self.station_setpoints.clear()  # Clear stale entries from previous step
    
    def get_total_power_usage(self):
        """
        Returns the total power currently being used (sum of all station setpoints).
        """
        return sum(self.station_setpoints.values())
    
    def get_total_requested_power(self):
        """
        Returns the total power currently being requested.
        """
        return sum(self.station_requests.values())
    
    def update_station_power_usage(self, station_id, actual_power_kw):
        """
        Update actual power usage for a station (for monitoring).
        """
        self.station_setpoints[station_id] = max(0.0, actual_power_kw)

    def finalize_step(self):
        """
        Finalize power allocation for this step.
        Called after all stations have registered their requests.
        Saves total demand for next step's fair scaling.
        """
        self._previous_total_demand = sum(self.station_requests.values())
