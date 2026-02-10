"""
Trip chain generator for realistic mobility patterns.
Based on ev_mobility_model approach (MIT License, Jonas Schlund 2022).
Simplified for SUMO traffic simulation integration.
"""

import random
from typing import List, Dict, Tuple
from mobility_variables import (
    Purpose, HomogeneousGroup, MobilityPattern, DayType, AgeGroup,
    Trip, TripChain, UserProfile, TripDistributions
)


class TripChainGenerator:
    """
    Generates realistic daily trip chains for EV users.
    
    This is a simplified statistical model based on mobility research.
    The original ev_mobility_model uses detailed CSV distributions from
    the Mobility in Germany 2017 dataset.
    """
    
    def __init__(self, seed: int = None):
        """Initialize generator with optional random seed."""
        self.seed = seed
        if seed is not None:
            random.seed(seed)
    
    def generate_user_profiles(
        self,
        num_users: int,
        working_person_ratio: float = 0.65,
        student_ratio: float = 0.15,
        car_dependent_ratio: float = 0.4,
        young_ratio: float = 0.35,
        middle_ratio: float = 0.40
    ) -> List[UserProfile]:
        """
        Generate a population of users with diverse demographics.
        
        Args:
            num_users: Total number of users to generate
            working_person_ratio: Fraction of working persons (0-1)
            student_ratio: Fraction of students (0-1)
            car_dependent_ratio: Fraction of car-dependent users (0-1)
            young_ratio: Fraction of young users (<40)
            middle_ratio: Fraction of middle-aged users (40-65)
            
        Returns:
            List of UserProfile objects
        """
        profiles = []
        
        for i in range(num_users):
            user_id = f"person{i+1}"
            
            # Sample homogeneous group
            r = random.random()
            if r < working_person_ratio:
                hgroup = HomogeneousGroup.WORKING_PERSON
            elif r < working_person_ratio + student_ratio:
                hgroup = HomogeneousGroup.STUDENT
            else:
                hgroup = HomogeneousGroup.NON_WORKING_PERSON
            
            # Sample mobility pattern
            r = random.random()
            if r < car_dependent_ratio:
                mpattern = MobilityPattern.CAR_DEPENDENT
            elif r < car_dependent_ratio + 0.4:
                mpattern = MobilityPattern.BALANCED
            else:
                mpattern = MobilityPattern.LIGHT_USER
            
            # Sample age group
            r = random.random()
            if r < young_ratio:
                age = AgeGroup.YOUNG
            elif r < young_ratio + middle_ratio:
                age = AgeGroup.MIDDLE
            else:
                age = AgeGroup.SENIOR
            
            # Working people have fixed work locations
            has_work = (hgroup == HomogeneousGroup.WORKING_PERSON)
            work_dist = None
            if has_work:
                # Sample work distance from realistic distribution
                work_dist = max(2.0, min(80.0, random.lognormvariate(2.5, 0.8)))
            
            profiles.append(UserProfile(
                user_id=user_id,
                homogeneous_group=hgroup,
                mobility_pattern=mpattern,
                age_group=age,
                has_fixed_work_location=has_work,
                work_distance_km=work_dist
            ))
        
        return profiles
    
    def generate_trip_chain(
        self,
        user_profile: UserProfile,
        day_type: DayType = DayType.WEEKDAY,
        available_locations: Dict[Purpose, List[str]] = None
    ) -> TripChain:
        """
        Generate a complete daily trip chain for a user.
        
        Args:
            user_profile: User demographic and behavioral profile
            day_type: Type of day (weekday, weekend, holiday)
            available_locations: Dict mapping purposes to edge IDs
            
        Returns:
            TripChain object with all trips
        """
        chain = TripChain()
        
        # Sample chain length
        chain_length = TripDistributions.sample_trip_chain_length(
            user_profile.homogeneous_group,
            day_type,
            user_profile.mobility_pattern
        )
        
        if chain_length == 0:
            # No trips today (stays home)
            return chain
        
        # Sample purpose sequence
        purposes = TripDistributions.sample_purpose_chain(
            chain_length,
            user_profile.homogeneous_group,
            day_type
        )
        
        if not purposes:
            return chain
        
        # Generate trips
        current_time = TripDistributions.sample_start_time(
            purposes[0],
            user_profile.homogeneous_group,
            day_type
        )
        
        for i, purpose in enumerate(purposes):
            is_last = (i == len(purposes) - 1)
            
            # Sample trip characteristics
            stay_time = None if is_last else TripDistributions.sample_stay_time(
                purpose, day_type
            )
            
            distance = TripDistributions.sample_distance(
                purpose,
                user_profile.mobility_pattern,
                user_profile.work_distance_km if purpose == Purpose.WORK else None
            )
            
            speed = TripDistributions.sample_speed(distance, purpose)
            duration = distance / speed  # hours
            
            # Assign location
            location = None
            if available_locations and purpose in available_locations:
                locs = available_locations[purpose]
                if locs:
                    location = random.choice(locs)
            
            # Create trip
            trip = Trip(
                purpose=purpose,
                departure_time=current_time,
                duration=duration,
                distance=distance,
                location=location
            )
            trip.stay_time = stay_time
            
            chain.add_trip(trip)
            
            # Update time for next trip
            if not is_last:
                current_time = trip.arrival_time + stay_time
        
        return chain
    
    def generate_all_chains(
        self,
        user_profiles: List[UserProfile],
        day_type: DayType = DayType.WEEKDAY,
        available_locations: Dict[Purpose, List[str]] = None
    ) -> Dict[str, TripChain]:
        """
        Generate trip chains for all users.
        
        Args:
            user_profiles: List of user profiles
            day_type: Type of day
            available_locations: Available locations by purpose
            
        Returns:
            Dictionary mapping user_id to TripChain
        """
        chains = {}
        
        for profile in user_profiles:
            chain = self.generate_trip_chain(
                profile,
                day_type,
                available_locations
            )
            chains[profile.user_id] = chain
        
        return chains
    
    def get_statistics(self, chains: Dict[str, TripChain]) -> dict:
        """
        Calculate statistics about generated trip chains.
        
        Args:
            chains: Dictionary of trip chains
            
        Returns:
            Dictionary with statistics
        """
        total_users = len(chains)
        mobile_users = sum(1 for c in chains.values() if c.get_trip_count() > 0)
        total_trips = sum(c.get_trip_count() for c in chains.values())
        total_distance = sum(c.get_total_distance() for c in chains.values())
        
        # Purpose breakdown
        purpose_counts = {}
        for chain in chains.values():
            for trip in chain.trips:
                purpose_name = trip.purpose.name
                purpose_counts[purpose_name] = purpose_counts.get(purpose_name, 0) + 1
        
        avg_trips_per_user = total_trips / total_users if total_users > 0 else 0
        avg_distance_per_user = total_distance / total_users if total_users > 0 else 0
        avg_distance_per_trip = total_distance / total_trips if total_trips > 0 else 0
        
        return {
            'total_users': total_users,
            'mobile_users': mobile_users,
            'stationary_users': total_users - mobile_users,
            'total_trips': total_trips,
            'total_distance_km': round(total_distance, 1),
            'avg_trips_per_user': round(avg_trips_per_user, 2),
            'avg_distance_per_user_km': round(avg_distance_per_user, 1),
            'avg_distance_per_trip_km': round(avg_distance_per_trip, 1),
            'purpose_distribution': purpose_counts
        }


# Helper functions for integration with SUMO

def purpose_to_poi_type(purpose: Purpose) -> str:
    """Map trip purpose to POI type for location assignment."""
    mapping = {
        Purpose.WORK: 'offices',
        Purpose.BUSINESS: 'offices',
        Purpose.EDUCATION: 'others',  # schools, universities
        Purpose.SHOPPING: 'others',  # shops, malls
        Purpose.PRIVATE_ERRANDS: 'others',
        Purpose.LEISURE: 'others',  # entertainment, restaurants
        Purpose.HOME: 'residential',
        Purpose.UNKNOWN: 'others'
    }
    return mapping.get(purpose, 'others')


def convert_trip_chain_to_sumo_route(
    trip_chain: TripChain,
    home_edge: str,
    poi_edges: Dict[str, List[str]],
    ev_params: dict = None
) -> dict:
    """
    Convert a trip chain to SUMO route format.
    
    Args:
        trip_chain: Generated trip chain
        home_edge: Home location edge ID
        poi_edges: Available POI edges by category
        ev_params: EV-specific parameters (battery, etc.)
        
    Returns:
        Dictionary with SUMO route information
    """
    if ev_params is None:
        ev_params = {}
    
    route = []
    stops = []
    current_edge = home_edge
    
    # Start from home
    route.append(home_edge)
    
    for trip in trip_chain.trips:
        # Determine destination edge
        if trip.purpose == Purpose.HOME:
            dest_edge = home_edge
        elif trip.location:
            dest_edge = trip.location
        else:
            # Assign location based on purpose
            poi_type = purpose_to_poi_type(trip.purpose)
            available = poi_edges.get(poi_type, [])
            if available:
                dest_edge = random.choice(available)
            else:
                # Fallback to random POI
                all_pois = [e for edges in poi_edges.values() for e in edges]
                dest_edge = random.choice(all_pois) if all_pois else home_edge
        
        # Add to route if different from current
        if dest_edge != current_edge:
            route.append(dest_edge)
            current_edge = dest_edge
        
        # Add stop if there's a stay time
        if trip.stay_time is not None:
            duration_seconds = int(trip.stay_time * 3600)
            stops.append({
                'edge': dest_edge,
                'duration': duration_seconds,
                'purpose': trip.purpose.name
            })
    
    # Ensure route ends at home if not already
    if route[-1] != home_edge:
        route.append(home_edge)
    
    # Calculate departure time in seconds
    first_trip = trip_chain.trips[0] if trip_chain.trips else None
    depart_seconds = int(first_trip.departure_time * 3600) if first_trip else 0
    
    return {
        'route': route,
        'stops': stops,
        'depart': depart_seconds,
        'depart_time': f"{int(first_trip.departure_time):02d}:{int((first_trip.departure_time % 1) * 60):02d}" if first_trip else "00:00"
    }
