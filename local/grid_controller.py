"""
Grid Controller - Intelligent power distribution for V2G charging network.

This controller replaces the simple EnergyPool with a realistic power grid
simulation that considers voltage constraints, line loading, and transformer limits.
"""

import pandapower as pp
import numpy as np
from collections import defaultdict


class GridController:
    """
    Manages power distribution across charging stations using realistic grid constraints.
    
    Features:
    - Runs power flow calculations to check grid limits
    - Allocates power based on voltage and loading constraints
    - Supports V2G (vehicle-to-grid) discharge at private wallboxes
    - Provides grid stability monitoring
    """
    
    def __init__(self, power_grid_manager, max_total_power_kw=None):
        """
        Initialize grid controller.
        
        Args:
            power_grid_manager: PowerGridManager instance with configured network
            max_total_power_kw: Optional power limit (if None, uses grid capacity)
        """
        self.grid_manager = power_grid_manager
        self.net = power_grid_manager.net
        self.station_to_bus = power_grid_manager.station_to_bus
        
        # Power limits
        self.max_total_power_kw = max_total_power_kw
        
        # Tracking
        self.station_requests = {}      # station_id -> requested_power_kw
        self.station_allocated = {}     # station_id -> allocated_power_kw
        self.station_actual = {}        # station_id -> actual_usage_kw
        self.v2g_stations = {}          # station_id -> discharge_kw (negative values)
        
        # Grid state
        self.last_power_flow_success = True
        self.voltage_violations = []
        self.loading_violations = []
        
        # Constraint limits
        self.voltage_min_pu = 0.95
        self.voltage_max_pu = 1.05
        self.line_loading_max = 100.0
        self.trafo_loading_max = 100.0
        self._previous_total_demand = 0  # Total demand from previous step (for fair scaling)
        
        print("[GridController] Initialized with pandapower network")
        print(f"  Buses: {len(self.net.bus)}, Lines: {len(self.net.line)}, Transformers: {len(self.net.trafo)}")
    
    def reset_requests(self):
        """Clear all power requests and actuals at the start of each time step.
        Preserves station_allocated from previous step for get_available_power_for_station()."""
        self._previous_total_demand = sum(self.station_requests.values())
        self.station_requests.clear()
        self.station_actual.clear()  # Clear stale entries from previous step
        # Note: station_allocated is NOT cleared — retains previous step's allocation
        # so get_available_power_for_station() can use it for fair power distribution
        self.voltage_violations.clear()
        self.loading_violations.clear()
    
    def register_station_request(self, station_id, requested_power_kw):
        """
        Register a charging station's power request.
        
        Args:
            station_id: Station identifier
            requested_power_kw: Power requested in kW (positive for charging)
        """
        self.station_requests[station_id] = max(0.0, requested_power_kw)
    
    def register_v2g_discharge(self, station_id, discharge_power_kw):
        """
        Register a V2G discharge request (vehicle feeding power back to grid).
        
        Args:
            station_id: Station identifier
            discharge_power_kw: Power to discharge in kW (will be converted to negative)
        """
        self.v2g_stations[station_id] = -abs(discharge_power_kw)  # Negative = generation
    
    def allocate_power(self):
        """
        Allocate power to all requesting stations based on grid constraints.
        
        This is the main power distribution algorithm:
        1. Update grid network with all requests
        2. Run power flow calculation
        3. Check constraints (voltage, line loading, transformer loading)
        4. If violations occur, reduce power proportionally
        5. Return allocated power for each station
        
        Returns:
            dict: station_id -> allocated_power_kw
        """
        if not self.station_requests and not self.v2g_stations:
            # No active requests, but still run power flow for baseline grid state
            self.net.load['p_mw'] = 0.0  # Zero all loads
            self._run_power_flow()  # Update grid state with zero load
            return {}
        
        # Update network loads with requests
        self._update_network_loads()
        
        # Run power flow
        success = self._run_power_flow()
        
        if not success:
            # Power flow failed - emergency reduction
            return self._emergency_power_allocation()
        
        # Check constraints
        constraints_ok = self._check_all_constraints()
        
        if constraints_ok:
            # All constraints satisfied - grant full requests
            self.station_allocated = self.station_requests.copy()
            return self.station_allocated
        else:
            # Constraints violated - iteratively reduce power
            return self._iterative_power_reduction()
    
    def get_available_power_for_station(self, station_id, requested_power_kw):
        """
        Get available power for a specific station (for compatibility with old EnergyPool API).
        
        Args:
            station_id: Station identifier
            requested_power_kw: Requested power in kW
        
        Returns:
            float: Allocated power in kW
        """
        # If this station was registered and allocated, return allocation
        if station_id in self.station_allocated:
            return self.station_allocated[station_id]
        
        # Otherwise, use simple proportional allocation with fair scaling
        current_total = sum(self.station_requests.values())
        total_requested = max(current_total, self._previous_total_demand)
        
        if total_requested == 0:
            return requested_power_kw
        
        if self.max_total_power_kw and total_requested > self.max_total_power_kw:
            scale = self.max_total_power_kw / total_requested
            return requested_power_kw * scale
        
        return requested_power_kw
    
    def update_station_power_usage(self, station_id, actual_power_kw):
        """
        Update actual power usage for a station (for monitoring).
        
        Args:
            station_id: Station identifier
            actual_power_kw: Actual power being used in kW
        """
        self.station_actual[station_id] = actual_power_kw
    
    def get_total_requested_power(self):
        """Get total power requested by all stations."""
        charging_demand = sum(self.station_requests.values())
        v2g_supply = sum(self.v2g_stations.values())  # Negative values
        return charging_demand + v2g_supply
    
    def get_total_power_usage(self):
        """Get total actual power usage."""
        return sum(self.station_actual.values())
    
    def get_grid_state(self):
        """
        Get current grid state for monitoring and visualization.
        
        Returns:
            dict: Comprehensive grid state information
        """
        state = {
            'power_flow_success': self.last_power_flow_success,
            'total_requested_kw': self.get_total_requested_power(),
            'total_usage_kw': self.get_total_power_usage(),
            'voltage_violations': len(self.voltage_violations),
            'loading_violations': len(self.loading_violations),
            'v2g_active_stations': len(self.v2g_stations),
            'v2g_total_discharge_kw': abs(sum(self.v2g_stations.values())),
        }
        
        # Add grid metrics if power flow succeeded
        if self.last_power_flow_success:
            state['grid_power_mw'] = float(self.net.res_ext_grid.p_mw.sum())
            state['min_voltage_pu'] = float(self.net.res_bus.vm_pu.min())
            state['max_voltage_pu'] = float(self.net.res_bus.vm_pu.max())
            
            if len(self.net.res_line) > 0:
                state['max_line_loading'] = float(self.net.res_line.loading_percent.max())
            else:
                state['max_line_loading'] = 0.0
            
            if len(self.net.res_trafo) > 0:
                state['max_trafo_loading'] = float(self.net.res_trafo.loading_percent.max())
            else:
                state['max_trafo_loading'] = 0.0
        
        return state
    
    def enable_v2g_for_station(self, station_id, discharge_kw):
        """
        Enable V2G discharge mode for a specific station.
        
        Args:
            station_id: Station identifier
            discharge_kw: Power to discharge in kW
        """
        if station_id not in self.station_to_bus:
            return
        
        bus_data = self.station_to_bus[station_id]
        load_idx = bus_data['load_idx']
        
        # Set load to zero (vehicle not consuming)
        self.net.load.at[load_idx, 'p_mw'] = 0.0
        
        # Create or update static generator (sgen) for V2G
        # Note: In pandapower, negative load = generation, but we use sgen for clarity
        bus_idx = bus_data['bus_idx']
        
        # Check if sgen already exists for this station
        existing_sgen = self.net.sgen[self.net.sgen['name'] == f"v2g_{station_id}"]
        
        if len(existing_sgen) > 0:
            # Update existing
            sgen_idx = existing_sgen.index[0]
            self.net.sgen.at[sgen_idx, 'p_mw'] = discharge_kw / 1000.0
        else:
            # Create new
            pp.create_sgen(
                self.net,
                bus=bus_idx,
                p_mw=discharge_kw / 1000.0,
                name=f"v2g_{station_id}"
            )
        
        self.v2g_stations[station_id] = -discharge_kw  # Track as negative
    
    def disable_v2g_for_station(self, station_id):
        """
        Disable V2G discharge mode for a specific station.
        
        Args:
            station_id: Station identifier
        """
        # Remove from v2g tracking
        self.v2g_stations.pop(station_id, None)
        
        # Remove sgen from network
        sgen_name = f"v2g_{station_id}"
        sgen_indices = self.net.sgen[self.net.sgen['name'] == sgen_name].index
        
        if len(sgen_indices) > 0:
            self.net.sgen.drop(sgen_indices, inplace=True)
    
    # ===== Internal Methods =====
    
    def _update_network_loads(self):
        """Update pandapower network loads with current requests."""
        # Reset all loads to zero
        self.net.load['p_mw'] = 0.0
        
        # Apply charging requests
        for station_id, power_kw in self.station_requests.items():
            if station_id in self.station_to_bus:
                load_idx = self.station_to_bus[station_id]['load_idx']
                self.net.load.at[load_idx, 'p_mw'] = power_kw / 1000.0  # Convert to MW
        
        # V2G is handled via sgen elements (already created in enable_v2g_for_station)
    
    def _run_power_flow(self):
        """
        Run AC power flow calculation.
        
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            pp.runpp(self.net, algorithm='nr', init='auto', max_iteration=20)
            self.last_power_flow_success = True
            return True
        except Exception as e:
            # Power flow failed - likely due to extreme conditions
            self.last_power_flow_success = False
            return False
    
    def _check_all_constraints(self):
        """
        Check all grid constraints (voltage, line loading, transformer loading).
        
        Returns:
            bool: True if all constraints satisfied, False otherwise
        """
        voltage_ok = self._check_voltage_constraints()
        line_ok = self._check_line_loading()
        trafo_ok = self._check_transformer_loading()
        
        return voltage_ok and line_ok and trafo_ok
    
    def _check_voltage_constraints(self):
        """Check bus voltage limits."""
        self.voltage_violations.clear()
        
        for bus_idx, row in self.net.res_bus.iterrows():
            vm_pu = row['vm_pu']
            
            if vm_pu < self.voltage_min_pu or vm_pu > self.voltage_max_pu:
                self.voltage_violations.append({
                    'bus': bus_idx,
                    'voltage_pu': vm_pu,
                    'limit': 'low' if vm_pu < self.voltage_min_pu else 'high'
                })
        
        return len(self.voltage_violations) == 0
    
    def _check_line_loading(self):
        """Check line loading limits."""
        self.loading_violations.clear()
        
        for line_idx, row in self.net.res_line.iterrows():
            loading = row['loading_percent']
            
            if loading > self.line_loading_max:
                self.loading_violations.append({
                    'line': line_idx,
                    'loading_percent': loading
                })
        
        return len(self.loading_violations) == 0
    
    def _check_transformer_loading(self):
        """Check transformer loading limits."""
        for trafo_idx, row in self.net.res_trafo.iterrows():
            loading = row['loading_percent']
            
            if loading > self.trafo_loading_max:
                self.loading_violations.append({
                    'transformer': trafo_idx,
                    'loading_percent': loading
                })
        
        return len(self.loading_violations) == 0
    
    def _iterative_power_reduction(self, max_iterations=5):
        """
        Iteratively reduce power until constraints are satisfied.
        
        Returns:
            dict: station_id -> allocated_power_kw
        """
        reduction_factor = 0.9  # Reduce by 10% each iteration
        allocated = self.station_requests.copy()
        
        for iteration in range(max_iterations):
            # Apply reduction
            for station_id in allocated:
                allocated[station_id] *= reduction_factor
            
            # Update network and check
            for station_id, power_kw in allocated.items():
                if station_id in self.station_to_bus:
                    load_idx = self.station_to_bus[station_id]['load_idx']
                    self.net.load.at[load_idx, 'p_mw'] = power_kw / 1000.0
            
            # Run power flow
            if not self._run_power_flow():
                continue  # Failed, reduce more
            
            # Check constraints
            if self._check_all_constraints():
                # Success!
                self.station_allocated = allocated
                return allocated
        
        # Max iterations reached - use emergency allocation
        return self._emergency_power_allocation()
    
    def _emergency_power_allocation(self):
        """
        Emergency power allocation when grid is severely constrained.
        Reduces all requests to 25% of original.
        
        Returns:
            dict: station_id -> allocated_power_kw
        """
        allocated = {
            station_id: power_kw * 0.25
            for station_id, power_kw in self.station_requests.items()
        }
        
        self.station_allocated = allocated
        return allocated
    
    def __str__(self):
        """String representation for debugging."""
        state = self.get_grid_state()
        return (f"GridController(buses={len(self.net.bus)}, "
                f"power={state['total_usage_kw']:.1f}kW, "
                f"v2g={state['v2g_active_stations']} stations)")

    def finalize_step(self):
        """
        Finalize power allocation for this step.
        Runs power flow and allocates power based on grid constraints.
        Results are used by get_available_power_for_station() in the next step.
        """
        self._previous_total_demand = sum(self.station_requests.values())
        if self.station_requests or self.v2g_stations:
            self.allocate_power()


if __name__ == "__main__":
    # Test grid controller
    from power_grid_manager import PowerGridManager
    
    # Create test grid (fallback 3-bus grid since no OSM file)
    manager = PowerGridManager()
    manager.build_grid()
    
    # Add test stations
    test_stations = [
        {'id': 'cs_001', 'lon': 13.0, 'lat': 48.0, 'power_kw': 200.0, 'type': 'public'},
        {'id': 'cs_002', 'lon': 13.01, 'lat': 48.01, 'power_kw': 200.0, 'type': 'public'},
    ]
    manager.assign_charging_stations_to_grid(test_stations)
    
    # Create controller
    controller = GridController(manager, max_total_power_kw=500)
    
    # Test power allocation
    controller.reset_requests()
    controller.register_station_request('cs_001', 150.0)
    controller.register_station_request('cs_002', 100.0)
    
    allocated = controller.allocate_power()
    print(f"Allocated power: {allocated}")
    
    state = controller.get_grid_state()
    print(f"Grid state: {state}")
