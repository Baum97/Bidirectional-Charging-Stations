"""
Mobility model variables and data structures.
Simplified version based on ev_mobility_model (MIT License, Jonas Schlund 2022).
"""

from enum import Enum
from typing import List, Union, Optional
import random


class Purpose(int, Enum):
    """Trip purposes for activity chain modeling."""
    WORK = 1
    BUSINESS = 2
    EDUCATION = 3
    SHOPPING = 4
    PRIVATE_ERRANDS = 5
    LEISURE = 6
    HOME = 7
    UNKNOWN = 0


class HomogeneousGroup(str, Enum):
    """Behavioral user groups."""
    WORKING_PERSON = "working"
    NON_WORKING_PERSON = "non_working"
    STUDENT = "student"
    UNKNOWN = "unknown"


class MobilityPattern(str, Enum):
    """Mobility patterns based on typical behavior."""
    CAR_DEPENDENT = "car_dependent"  # Heavy car users
    BALANCED = "balanced"  # Mix of transport modes
    LIGHT_USER = "light_user"  # Occasional car use
    UNKNOWN = "unknown"


class DayType(str, Enum):
    """Day types affecting mobility behavior."""
    WEEKDAY = "weekday"
    WEEKEND = "weekend"
    HOLIDAY = "holiday"
    UNKNOWN = "unknown"


class AgeGroup(str, Enum):
    """Age groups with different mobility patterns."""
    YOUNG = "young"  # < 40
    MIDDLE = "middle"  # 40-65
    SENIOR = "senior"  # > 65
    UNKNOWN = "unknown"


class Trip:
    """Represents a single trip in a trip chain."""
    
    def __init__(
        self,
        purpose: Purpose,
        departure_time: float,  # hours from midnight
        duration: float,  # hours
        distance: float,  # km
        location: str = None  # edge ID
    ):
        self.purpose = purpose
        self.departure_time = departure_time
        self.duration = duration
        self.distance = distance
        self.arrival_time = departure_time + duration
        self.location = location
        self.stay_time: Optional[float] = None  # Set for all but last trip


class TripChain:
    """Complete daily activity chain for one person."""
    
    def __init__(self):
        self.trips: List[Trip] = []
        self.home_location: str = None
        
    def add_trip(self, trip: Trip):
        """Add a trip to the chain."""
        self.trips.append(trip)
        
    def get_total_distance(self) -> float:
        """Get total distance traveled."""
        return sum(t.distance for t in self.trips)
    
    def get_trip_count(self) -> int:
        """Get number of trips."""
        return len(self.trips)


class UserProfile:
    """User demographic and behavioral profile."""
    
    def __init__(
        self,
        user_id: str,
        homogeneous_group: HomogeneousGroup = HomogeneousGroup.UNKNOWN,
        mobility_pattern: MobilityPattern = MobilityPattern.UNKNOWN,
        age_group: AgeGroup = AgeGroup.UNKNOWN,
        has_fixed_work_location: bool = False,
        work_distance_km: float = None
    ):
        self.user_id = user_id
        self.homogeneous_group = homogeneous_group
        self.mobility_pattern = mobility_pattern
        self.age_group = age_group
        self.has_fixed_work_location = has_fixed_work_location
        self.work_distance_km = work_distance_km


# Statistical distributions for trip generation
# These are simplified; the original model uses detailed CSV data

class TripDistributions:
    """Statistical distributions for trip generation."""
    
    @staticmethod
    def sample_trip_chain_length(
        homogeneous_group: HomogeneousGroup,
        day_type: DayType,
        mobility_pattern: MobilityPattern
    ) -> int:
        """Sample the number of trips in a chain."""
        
        # Base probabilities for chain length [0, 1, 2, 3, 4, 5+]
        if day_type == DayType.WEEKEND:
            # Weekends: fewer, simpler trips
            probs = [0.15, 0.20, 0.25, 0.20, 0.15, 0.05]
        else:  # Weekday
            if homogeneous_group == HomogeneousGroup.WORKING_PERSON:
                # Working people: regular commute + errands
                probs = [0.05, 0.10, 0.25, 0.30, 0.20, 0.10]
            elif homogeneous_group == HomogeneousGroup.STUDENT:
                # Students: similar to working
                probs = [0.05, 0.15, 0.25, 0.25, 0.20, 0.10]
            else:  # Non-working
                # More flexible patterns
                probs = [0.10, 0.15, 0.25, 0.25, 0.15, 0.10]
        
        # Adjust by mobility pattern
        if mobility_pattern == MobilityPattern.CAR_DEPENDENT:
            # More trips for car-dependent users
            probs = [p * 0.8 if i < 2 else p * 1.2 for i, p in enumerate(probs)]
        elif mobility_pattern == MobilityPattern.LIGHT_USER:
            # Fewer trips for light users
            probs = [p * 1.2 if i < 2 else p * 0.8 for i, p in enumerate(probs)]
        
        # Normalize
        total = sum(probs)
        probs = [p / total for p in probs]
        
        # Sample
        r = random.random()
        cumsum = 0
        for i, p in enumerate(probs):
            cumsum += p
            if r <= cumsum:
                return min(i * 2, 6)  # 0, 2, 4, 6, 8, 10 trips
        return 4  # Default
    
    @staticmethod
    def sample_purpose_chain(
        chain_length: int,
        homogeneous_group: HomogeneousGroup,
        day_type: DayType
    ) -> List[Purpose]:
        """Sample a sequence of trip purposes."""
        
        if chain_length == 0:
            return []
        
        purposes = []
        
        # First trip from home
        if day_type == DayType.WEEKEND:
            # Weekend: more leisure and shopping
            first_purpose_weights = {
                Purpose.SHOPPING: 0.3,
                Purpose.LEISURE: 0.4,
                Purpose.PRIVATE_ERRANDS: 0.2,
                Purpose.WORK: 0.05,
                Purpose.EDUCATION: 0.05
            }
        else:  # Weekday
            if homogeneous_group == HomogeneousGroup.WORKING_PERSON:
                first_purpose_weights = {
                    Purpose.WORK: 0.7,
                    Purpose.BUSINESS: 0.1,
                    Purpose.SHOPPING: 0.1,
                    Purpose.PRIVATE_ERRANDS: 0.05,
                    Purpose.LEISURE: 0.05
                }
            elif homogeneous_group == HomogeneousGroup.STUDENT:
                first_purpose_weights = {
                    Purpose.EDUCATION: 0.7,
                    Purpose.WORK: 0.1,
                    Purpose.LEISURE: 0.1,
                    Purpose.SHOPPING: 0.05,
                    Purpose.PRIVATE_ERRANDS: 0.05
                }
            else:  # Non-working
                first_purpose_weights = {
                    Purpose.SHOPPING: 0.4,
                    Purpose.LEISURE: 0.3,
                    Purpose.PRIVATE_ERRANDS: 0.2,
                    Purpose.WORK: 0.05,
                    Purpose.EDUCATION: 0.05
                }
        
        # Sample first purpose
        purposes.append(TripDistributions._weighted_choice(first_purpose_weights))
        
        # Generate intermediate purposes
        for i in range(1, chain_length):
            previous = purposes[-1]
            
            # Most chains return home eventually
            is_last = (i == chain_length - 1)
            if is_last:
                purposes.append(Purpose.HOME)
            else:
                # Next purpose depends on previous
                if previous == Purpose.WORK:
                    next_weights = {
                        Purpose.HOME: 0.4,
                        Purpose.SHOPPING: 0.2,
                        Purpose.LEISURE: 0.2,
                        Purpose.PRIVATE_ERRANDS: 0.15,
                        Purpose.BUSINESS: 0.05
                    }
                elif previous in [Purpose.SHOPPING, Purpose.PRIVATE_ERRANDS]:
                    next_weights = {
                        Purpose.HOME: 0.5,
                        Purpose.SHOPPING: 0.15,
                        Purpose.LEISURE: 0.15,
                        Purpose.PRIVATE_ERRANDS: 0.15,
                        Purpose.WORK: 0.05
                    }
                elif previous == Purpose.LEISURE:
                    next_weights = {
                        Purpose.HOME: 0.6,
                        Purpose.SHOPPING: 0.15,
                        Purpose.LEISURE: 0.1,
                        Purpose.PRIVATE_ERRANDS: 0.1,
                        Purpose.WORK: 0.05
                    }
                else:  # EDUCATION, BUSINESS, etc.
                    next_weights = {
                        Purpose.HOME: 0.5,
                        Purpose.SHOPPING: 0.15,
                        Purpose.LEISURE: 0.15,
                        Purpose.PRIVATE_ERRANDS: 0.15,
                        Purpose.WORK: 0.05
                    }
                
                purposes.append(TripDistributions._weighted_choice(next_weights))
        
        return purposes
    
    @staticmethod
    def _weighted_choice(weights: dict) -> Purpose:
        """Choose a purpose based on weights."""
        r = random.random()
        cumsum = 0
        for purpose, weight in weights.items():
            cumsum += weight
            if r <= cumsum:
                return purpose
        return list(weights.keys())[-1]
    
    @staticmethod
    def sample_start_time(
        purpose: Purpose,
        homogeneous_group: HomogeneousGroup,
        day_type: DayType
    ) -> float:
        """Sample departure time in hours from midnight."""
        
        if day_type == DayType.WEEKEND:
            # Weekend: later starts
            if purpose == Purpose.WORK:
                return random.normalvariate(10.0, 2.0)  # 10:00 ± 2h
            elif purpose in [Purpose.SHOPPING, Purpose.LEISURE]:
                return random.normalvariate(11.0, 2.5)  # 11:00 ± 2.5h
            else:
                return random.normalvariate(10.5, 2.0)
        else:  # Weekday
            if purpose == Purpose.WORK:
                # Work: morning peak
                return max(5.0, min(11.0, random.normalvariate(7.5, 1.0)))  # 7:30 ± 1h
            elif purpose == Purpose.EDUCATION:
                # Education: early morning
                return max(6.0, min(9.0, random.normalvariate(7.5, 0.5)))
            elif purpose == Purpose.SHOPPING:
                # Shopping: spread throughout day
                return random.normalvariate(14.0, 3.0)  # 14:00 ± 3h
            elif purpose == Purpose.LEISURE:
                # Leisure: afternoon/evening
                return random.normalvariate(17.0, 2.5)  # 17:00 ± 2.5h
            else:
                # Other errands: business hours
                return random.normalvariate(12.0, 3.0)
    
    @staticmethod
    def sample_stay_time(
        purpose: Purpose,
        day_type: DayType
    ) -> float:
        """Sample stay time at location in hours."""
        
        if purpose == Purpose.WORK:
            # Work: 6-10 hours, typically 8
            return max(4.0, min(12.0, random.normalvariate(8.0, 1.5)))
        elif purpose == Purpose.EDUCATION:
            # Education: 4-8 hours
            return max(3.0, min(10.0, random.normalvariate(6.0, 1.5)))
        elif purpose == Purpose.SHOPPING:
            # Shopping: quick stops
            return max(0.25, random.normalvariate(1.5, 0.75))
        elif purpose == Purpose.LEISURE:
            # Leisure: variable
            if day_type == DayType.WEEKEND:
                return max(1.0, random.normalvariate(4.0, 2.0))
            else:
                return max(0.5, random.normalvariate(2.0, 1.0))
        elif purpose == Purpose.PRIVATE_ERRANDS:
            # Errands: short
            return max(0.25, random.normalvariate(1.0, 0.5))
        elif purpose == Purpose.HOME:
            # Time at home (before next trip or end of day)
            # This is calculated separately
            return 10.0  # Placeholder
        else:
            return max(0.5, random.normalvariate(2.0, 1.0))
    
    @staticmethod
    def sample_distance(
        purpose: Purpose,
        mobility_pattern: MobilityPattern,
        fixed_work_distance: float = None
    ) -> float:
        """Sample trip distance in km."""
        
        if purpose == Purpose.WORK and fixed_work_distance is not None:
            return fixed_work_distance
        
        # Base distance distributions by purpose
        # Using lognormal distribution: mu and sigma for ln(X)
        if purpose == Purpose.WORK:
            # Work: typically longer commutes
            if mobility_pattern == MobilityPattern.CAR_DEPENDENT:
                # mu=3.0, sigma=0.8 gives median ~20km, mean ~25km
                mu, sigma = 3.0, 0.8
            else:
                # mu=2.5, sigma=0.7 gives median ~12km, mean ~15km
                mu, sigma = 2.5, 0.7
            return max(1.0, random.lognormvariate(mu, sigma))
            
        elif purpose == Purpose.EDUCATION:
            # Education: medium distances
            # mu=2.0, sigma=0.6 gives median ~7km, mean ~9km
            return max(1.0, random.lognormvariate(2.0, 0.6))
            
        elif purpose == Purpose.SHOPPING:
            # Shopping: local, shorter trips
            # mu=1.5, sigma=0.7 gives median ~4.5km, mean ~6km
            return max(0.5, random.lognormvariate(1.5, 0.7))
            
        elif purpose == Purpose.LEISURE:
            # Leisure: variable, can be long
            # mu=2.7, sigma=0.9 gives median ~15km, mean ~22km
            return max(1.0, random.lognormvariate(2.7, 0.9))
            
        elif purpose == Purpose.PRIVATE_ERRANDS:
            # Errands: local
            # mu=1.3, sigma=0.6 gives median ~3.7km, mean ~5km
            return max(0.5, random.lognormvariate(1.3, 0.6))
            
        else:
            # Default: medium
            # mu=2.3, sigma=0.8 gives median ~10km, mean ~13km
            return max(1.0, random.lognormvariate(2.3, 0.8))
    
    @staticmethod
    def sample_speed(distance: float, purpose: Purpose) -> float:
        """Sample average speed in km/h."""
        
        # Urban speeds are lower for short distances
        if distance < 5.0:
            return max(15.0, random.normalvariate(25.0, 8.0))
        elif distance < 20.0:
            return max(20.0, random.normalvariate(40.0, 10.0))
        else:
            # Longer distances allow highway speeds
            return max(30.0, random.normalvariate(60.0, 15.0))
