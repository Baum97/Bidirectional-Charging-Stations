class EVSE_class():
    def __init__(self, efficiency, Prated_kW, evse_id, energy_pool=None, is_private=False, allowed_vehicle_id=None):
        self.efficiency = efficiency
        self.Prated_kW  = Prated_kW
        self.evse_id   = evse_id
        self.energy_pool = energy_pool  # reference to global energy pool
        
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
                
                Pmax = min(available_power, self.Prated_kW) * self.efficiency
            else:
                # V2G mode: request discharge power
                Pmax = -min(self.server_setpoint, self.Prated_kW) * self.efficiency  # negative = discharge
        else:
            Pmax = 0.0

        ### send Pmax via TCP or something if there needs a connection
        return Pmax


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
        total_requested = sum(self.station_requests.values())
        
        # If no demand or within limits, grant full request
        if total_requested <= self.max_total_power_kw:
            return requested_power_kw
        
        # Power is limited: scale proportionally
        scale_factor = self.max_total_power_kw / total_requested
        available = requested_power_kw * scale_factor
        
        return available
    
    def reset_requests(self):
        """
        Clear all station requests at the start of each time step.
        """
        self.station_requests.clear()
    
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
