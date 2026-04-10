import simulation_charging_profile_current as sc

def compute_current(one_phase=False, P=11):
    V = 250
    c = (P*1000)/V
    curr = [0 for i in range(3)]
    if one_phase:
        curr[0]=c
        curr[1]=0
        curr[2]=0
    else:
        curr[0] = (1/3)*c
        curr[1] = (1/3)*c
        curr[2] = (1/3)*c
    return curr

def compute_power(curr, one_phase=False, crate = 1):
    V = 250
    P = (curr[0]+curr[1]+curr[2])*(V/1000)*crate
    return P

def compute_energy_int(ramp_up, crate = 1, efficiency=1):
    energy = 0.0
    for e1, e2 in zip(ramp_up[:-1], ramp_up[1:]):
        p1 = compute_power(e1, crate = crate)*efficiency
        p2 = compute_power(e2, crate = crate)*efficiency
        # trapezoid rule
        avg_power = (p1 + p2) / 2
        energy += avg_power / 3600  # W → Wh (bei 1 Sekunde)
    return energy


def compute_energy(duration, power):
    energy = (duration*power)/3600
    return energy



class CHProcess:
    def __init__(self, start_time, one_phase = False, Pmax = 11, efficiency = 1.0, with_departure=False,
                 departure_time=None, with_rd=False, ev_soc = 100, crate=1, packcap=100):
        self.start_time = start_time

        self.one_phase = one_phase
        self.Pmax = Pmax
        self.efficiency = efficiency
        self.with_departure = with_departure
        self.departure_time = departure_time
        self.with_rd = with_rd
        self.crate = crate
        self.packcap = packcap
        self.ev_soc = ev_soc
        self.st = None
        self.ru = None
        self.ramp_up_started = False
        self.stagnant_started = False
        self.compute_ramp_up(self)
        self.compute_stagnant(self)

    def compute_ramp_up(self):
        sim_ru = sc.Simulation_RU()
        curr = compute_current(self.one_phase, P=self.Pmax)
        clusters_ru = sim_ru.compute_phase_clusters(self.one_phase)

        self.ru = sim_ru.generate_simulated_ramp_up(
            final_values=curr,
            n_samples=1,
            tol=1e-1,
            preferred_clusters=clusters_ru
        ).reshape(-1, 3)

    def compute_stagnant(self):
        #todo: evtl crate,... als parameter,nicht attribut
        energy_ru = compute_energy_int(self.ru, crate=self.crate, efficiency=self.efficiency)
        energy_to_charge = self.packcap * (1 - self.ev_soc)
        # -----------------------------------
        # Generate Stagnant Phase
        # -----------------------------------
        sim_sp2 = sc.Simulation_SP2()

        if self.with_departure:
            duration = self.departure_time - self.start_time - len(self.ru)
        else:
            duration = ((energy_to_charge - energy_ru) /
                        (self.Pmax * self.crate * self.efficiency)) * 3600 * 1.2 + self.setup_time

        stag = sim_sp2.generate_continuous_sample(
            duration_seconds=duration,
            start_currents=self.ru[-1],
            block_duration_seconds=None
        )
        self.st = sim_sp2.convert_sim_output_to_1s(stag, duration_seconds=duration)

    def get_power_at_time(self, t):

        # 1) Setup time
        if t < self.start_time:
            return 0

        # Time in local phase scale
        dt_local = t - self.start_time

        # 2) Ramp-Up
        if dt_local < len(self.ru):
            if not self.ramp_up_started:
                print("ramp_up begins")
                self.ramp_up_started = True
            return compute_power(self.ru[int(dt_local)], crate=self.crate)


        # 4) Stagnant
        st_idx = int(dt_local - len(self.ru))
        if st_idx < len(self.st):
            if not self.stagnant_started:
                print(f"stagnant phase begins at t={t}s")
                self.stagnant_started = True
            return compute_power(self.st[st_idx], crate=self.crate)

        # After stagnant: hold last value
        return compute_power(self.st[-1], crate=self.crate)