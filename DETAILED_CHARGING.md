# Detailed Charging Implementation

When the build option **“Build with TraCI (Detailed Charging, no V2G)”** is selected in the UI, charging behavior is simulated with a **higher level of physical and electrical detail**.

Instead of simplified charging curves, this mode uses **realistic battery and charging current models** to calculate charging behavior over time.

---

## Models Used

The detailed charging simulation is based on the following components:

### Battery Modeling
- **PyChargeModel**  
  Repository:  
  https://github.com/NatLabRockies/PyChargeModel

  This library is used to model realistic battery behavior, including state-of-charge–dependent charging characteristics.

### Realistic Charging Current Profiles
- **simulation-charging**  
  Repository:  
  https://gitlab.cc-asp.fraunhofer.de/truoel/simulation-charging

  This package provides **real-world–based current profiles** for charging sessions, enabling a much more accurate representation of charging power over time.

Detailed documentation for both models can be found directly in their respective repositories.

---

## Performance Considerations

⚠️ **Important:**  
Enabling *Detailed Charging* significantly increases computational complexity.

As a result:
- The simulation runtime is **noticeably longer**
- Overall performance is **lower** compared to standard or V2G-enabled builds
- This mode is recommended primarily for **high-fidelity analyses**, not for large-scale or fast exploratory runs

---

## Installation

Before *Detailed Charging* can be used, the Python package  
`simulation_charging_profile_current` must be installed.

There are two options:

1. Install the wheel file included in this repository, or  
2. Download the latest version from GitLab, replace the old wheel file, and install it  
   https://gitlab.cc-asp.fraunhofer.de/truoel/simulation-charging

### Installation Command

```bash
pip install simulation_charging_profile_current-0.1.0-py3-none-any.whl
```
After installation, the detailed charging models will be available for use in TraCI-based simulations without V2G.