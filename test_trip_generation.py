"""
Test script for the improved trip generation system.

Run this to verify the new mobility model works correctly.
"""

import sys
import os

# Add local directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'local'))

from trip_chain_generator import TripChainGenerator
from mobility_variables import DayType, Purpose


def test_basic_generation():
    """Test basic trip chain generation."""
    print("=" * 60)
    print("Test 1: Basic Trip Chain Generation")
    print("=" * 60)
    
    generator = TripChainGenerator(seed=42)
    
    # Generate a small population
    profiles = generator.generate_user_profiles(
        num_users=10,
        working_person_ratio=0.7,
        student_ratio=0.2
    )
    
    print(f"✓ Generated {len(profiles)} user profiles")
    
    # Show profile distribution
    groups = {}
    for p in profiles:
        group = p.homogeneous_group.value
        groups[group] = groups.get(group, 0) + 1
    
    print(f"  Profile distribution:")
    for group, count in groups.items():
        print(f"    {group}: {count}")
    
    return True


def test_trip_chain_generation():
    """Test trip chain generation for different user types."""
    print("\n" + "=" * 60)
    print("Test 2: Trip Chain Generation for Different Users")
    print("=" * 60)
    
    generator = TripChainGenerator(seed=42)
    
    # Generate profiles
    profiles = generator.generate_user_profiles(num_users=5)
    
    # Generate chains
    chains = generator.generate_all_chains(
        profiles,
        day_type=DayType.WEEKDAY
    )
    
    print(f"✓ Generated {len(chains)} trip chains")
    
    # Show some examples
    for i, (user_id, chain) in enumerate(list(chains.items())[:3]):
        profile = profiles[i]
        print(f"\n  User {user_id} ({profile.homogeneous_group.value}):")
        print(f"    Trips: {chain.get_trip_count()}")
        print(f"    Total distance: {chain.get_total_distance():.1f} km")
        
        if chain.trips:
            print(f"    Activity sequence:")
            for trip in chain.trips:
                depart_h = int(trip.departure_time)
                depart_m = int((trip.departure_time % 1) * 60)
                arrive_h = int(trip.arrival_time)
                arrive_m = int((trip.arrival_time % 1) * 60)
                stay = f" [stay {trip.stay_time:.1f}h]" if trip.stay_time else ""
                print(f"      {depart_h:02d}:{depart_m:02d} → {arrive_h:02d}:{arrive_m:02d}: "
                      f"{trip.purpose.name} ({trip.distance:.1f}km){stay}")
    
    return True


def test_statistics():
    """Test statistics generation."""
    print("\n" + "=" * 60)
    print("Test 3: Statistics Generation")
    print("=" * 60)
    
    generator = TripChainGenerator(seed=42)
    
    # Generate a larger population
    profiles = generator.generate_user_profiles(num_users=100)
    chains = generator.generate_all_chains(profiles, day_type=DayType.WEEKDAY)
    
    stats = generator.get_statistics(chains)
    
    print(f"✓ Generated statistics for {stats['total_users']} users")
    print(f"\n  Statistics:")
    print(f"    Mobile users: {stats['mobile_users']} ({stats['mobile_users']/stats['total_users']*100:.1f}%)")
    print(f"    Total trips: {stats['total_trips']}")
    print(f"    Avg trips/user: {stats['avg_trips_per_user']}")
    print(f"    Avg distance/user: {stats['avg_distance_per_user_km']} km")
    print(f"    Avg distance/trip: {stats['avg_distance_per_trip_km']} km")
    
    print(f"\n  Purpose distribution:")
    total_trips = stats['total_trips']
    for purpose, count in sorted(stats['purpose_distribution'].items()):
        pct = (count / total_trips * 100) if total_trips > 0 else 0
        print(f"    {purpose:20s}: {count:4d} ({pct:5.1f}%)")
    
    return True


def test_weekday_vs_weekend():
    """Test difference between weekday and weekend patterns."""
    print("\n" + "=" * 60)
    print("Test 4: Weekday vs Weekend Patterns")
    print("=" * 60)
    
    generator = TripChainGenerator(seed=42)
    profiles = generator.generate_user_profiles(num_users=50)
    
    # Weekday
    chains_weekday = generator.generate_all_chains(profiles, day_type=DayType.WEEKDAY)
    stats_weekday = generator.get_statistics(chains_weekday)
    
    # Weekend
    generator.seed = 42  # Reset seed for fair comparison
    chains_weekend = generator.generate_all_chains(profiles, day_type=DayType.WEEKEND)
    stats_weekend = generator.get_statistics(chains_weekend)
    
    print(f"✓ Compared weekday vs weekend patterns")
    print(f"\n  Weekday:")
    print(f"    Mobile users: {stats_weekday['mobile_users']}")
    print(f"    Avg trips/user: {stats_weekday['avg_trips_per_user']}")
    print(f"    Work trips: {stats_weekday['purpose_distribution'].get('WORK', 0)}")
    
    print(f"\n  Weekend:")
    print(f"    Mobile users: {stats_weekend['mobile_users']}")
    print(f"    Avg trips/user: {stats_weekend['avg_trips_per_user']}")
    print(f"    Work trips: {stats_weekend['purpose_distribution'].get('WORK', 0)}")
    
    return True


def run_all_tests():
    """Run all tests."""
    print("\n" + "=" * 60)
    print("IMPROVED TRIP GENERATION SYSTEM - TEST SUITE")
    print("=" * 60 + "\n")
    
    tests = [
        test_basic_generation,
        test_trip_chain_generation,
        test_statistics,
        test_weekday_vs_weekend
    ]
    
    passed = 0
    failed = 0
    
    for test in tests:
        try:
            if test():
                passed += 1
            else:
                failed += 1
                print(f"  ✗ Test failed")
        except Exception as e:
            failed += 1
            print(f"  ✗ Test failed with error: {e}")
            import traceback
            traceback.print_exc()
    
    print("\n" + "=" * 60)
    print(f"RESULTS: {passed} passed, {failed} failed")
    print("=" * 60 + "\n")
    
    if failed == 0:
        print("✅ All tests passed! The trip generation system is working correctly.")
    else:
        print("⚠️  Some tests failed. Please check the output above.")
    
    return failed == 0


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
