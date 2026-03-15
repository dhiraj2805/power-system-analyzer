"""
Transient Stability Engine
Classical machine model (constant internal voltage, swing equation).
Numerical integration via SciPy RK45 (variable step).

  dδ/dt  = ω_s · ω  (ω is per-unit deviation from synchronous speed)
  dω/dt  = (π·f₀ / H) · (Pm − Pe − D·ω)

  Pe = (E'·V / X'_total) · sin(δ − θ_V)   [simplified]

Standards reference: IEEE Std 1110-2019 (Guide for Synchronous Generator Modelling)
"""
import traceback
import numpy as np

try:
    from scipy.integrate import solve_ivp
    SCIPY_OK = True
except ImportError:
    SCIPY_OK = False

try:
    import pandapower as pp
    PANDAPOWER_OK = True
except ImportError:
    PANDAPOWER_OK = False

from engine.load_flow import build_pandapower_net
from models.database import get_session
from models.schema import Bus, Generator


def run_transient_stability(
    project_id: int,
    fault_bus_id: int,
    fault_start: float = 0.1,
    fault_clear: float = 0.2,
    sim_time: float = 3.0,
    dt: float = 0.01,
    delta_limit_deg: float = 180.0,
) -> dict:
    """
    Run a transient stability simulation.

    Parameters
    ----------
    project_id    : DB project id
    fault_bus_id  : DB bus id where the fault is applied
    fault_start   : fault inception time (s)
    fault_clear   : fault clearing time (s)
    sim_time      : total simulation duration (s)
    dt            : output time-step (s)
    delta_limit_deg : rotor angle beyond which machine is considered unstable
    """
    if not SCIPY_OK:
        return {"error": "scipy is not installed. Run: pip install scipy"}
    if not PANDAPOWER_OK:
        return {"error": "pandapower is not installed. Run: pip install pandapower"}

    session = get_session()
    try:
        # Step 1: Run pre-fault load flow to get initial conditions
        net, bus_map = build_pandapower_net(project_id, session)
        if len(net.bus) == 0:
            return {"error": "No buses found. Enter network data first."}

        pp.runpp(net, algorithm="nr", max_iteration=50, tolerance_mva=1e-8)

        generators = session.query(Generator).filter_by(project_id=project_id).all()
        if not generators:
            return {"error": "No generators defined in this project."}

        fault_pp_bus = bus_map.get(fault_bus_id)
        if fault_pp_bus is None:
            return {"error": f"Fault bus id={fault_bus_id} not found in network."}

        # Build generator initial conditions
        gen_data = _initialize_generators(net, bus_map, generators, session)
        if not gen_data:
            return {"error": "No generators could be initialized from load-flow results."}

        omega_s = 2.0 * np.pi * (session.query(Bus).filter_by(id=fault_bus_id).first() and 60)
        # Get system frequency from project
        from models.schema import Project
        proj = session.query(Project).filter_by(id=project_id).first()
        f0 = proj.frequency if proj else 60.0
        omega_s = 2.0 * np.pi * f0

        # Step 2: Build Y-bus admittance matrices for 3 network states
        # pre-fault, during-fault, post-fault (reduced to generator internal nodes)
        Ybus_pre   = _build_reduced_ybus(net, gen_data, fault_pp_bus=None, faulted=False)
        Ybus_fault = _build_reduced_ybus(net, gen_data, fault_pp_bus=fault_pp_bus, faulted=True)
        Ybus_post  = Ybus_pre  # assume fault is cleared by line tripping (same as pre for simplicity)

        # Step 3: Integrate swing equations
        n = len(gen_data)
        x0 = np.array([g["delta0"] for g in gen_data] + [g["omega0"] for g in gen_data])

        t_eval = np.arange(0, sim_time + dt, dt)

        def swing(t, x):
            deltas = x[:n]
            omegas = x[n:]
            dx = np.zeros(2 * n)

            if t < fault_start:
                Y = Ybus_pre
            elif t < fault_clear:
                Y = Ybus_fault
            else:
                Y = Ybus_post

            # Electrical power for each generator
            for i in range(n):
                Pe_i = 0.0
                Ei = gen_data[i]["Eq_prime"]
                delta_i = deltas[i]
                for j in range(n):
                    Ej = gen_data[j]["Eq_prime"]
                    delta_j = deltas[j]
                    Gij = Y[i, j].real
                    Bij = Y[i, j].imag
                    Pe_i += Ei * Ej * (
                        Gij * np.cos(delta_i - delta_j) + Bij * np.sin(delta_i - delta_j)
                    )

                H = gen_data[i]["H"]
                D = gen_data[i]["D"]
                Pm = gen_data[i]["Pm"]
                dx[i]     = omega_s * omegas[i]
                dx[n + i] = (np.pi * f0 / H) * (Pm - Pe_i - D * omegas[i])

            return dx

        sol = solve_ivp(
            swing,
            (0, sim_time),
            x0,
            t_eval=t_eval,
            method="RK45",
            rtol=1e-6,
            atol=1e-8,
            max_step=dt,
        )

        # Step 4: Extract and assess results
        time_list = sol.t.tolist()
        gen_results = []
        system_stable = True

        for i, g in enumerate(gen_data):
            delta_rad = sol.y[i]
            delta_deg = np.degrees(delta_rad).tolist()
            omega     = sol.y[n + i].tolist()
            max_delta = float(np.max(np.abs(delta_deg)))
            unstable  = max_delta > delta_limit_deg
            if unstable:
                system_stable = False
            gen_results.append(dict(
                name=g["name"],
                delta_deg=delta_deg,
                omega_pu=omega,
                max_delta_deg=round(max_delta, 2),
                initial_delta_deg=round(float(np.degrees(g["delta0"])), 2),
                stable=not unstable,
            ))

        # Estimate critical clearing time via bisection
        cct = _estimate_cct(
            project_id, fault_bus_id, fault_start, fault_clear, sim_time, dt,
            omega_s, f0, n, gen_data, x0, delta_limit_deg, Ybus_pre, Ybus_fault, Ybus_post,
        )

        return dict(
            converged=True,
            time=time_list,
            generators=gen_results,
            stable=system_stable,
            fault_bus_id=fault_bus_id,
            fault_start_s=fault_start,
            fault_clear_s=fault_clear,
            cct_s=cct,
            summary=_build_ts_summary(gen_results, system_stable, fault_start, fault_clear, cct),
        )

    except Exception as exc:
        return {"error": str(exc), "traceback": traceback.format_exc()}
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Initialise generator internal voltages from load-flow
# ---------------------------------------------------------------------------

def _initialize_generators(net, bus_map, generators, session):
    gen_data = []
    gen_list_pp = list(net.gen.itertuples())

    for i, gen in enumerate(generators):
        pp_bus = bus_map.get(gen.bus_id)
        if pp_bus is None:
            continue

        # Get terminal voltage from load flow
        Vm = float(net.res_bus.at[pp_bus, "vm_pu"])
        Va = float(np.radians(net.res_bus.at[pp_bus, "va_degree"]))
        Vt = complex(Vm * np.cos(Va), Vm * np.sin(Va))

        # Get generator output from load-flow
        # Find matching generator in pp net by bus
        P = gen.p_mw / (gen.sn_mva or 100.0)
        Q = 0.0
        for gpp in gen_list_pp:
            if gpp.bus == pp_bus:
                try:
                    Q = float(net.res_gen.at[gpp.Index, "q_mvar"]) / (gen.sn_mva or 100.0)
                except Exception:
                    pass
                break

        Ra = gen.ra_pu or 0.003
        Xd_prime = gen.xd_prime_pu or 0.3

        # Terminal current (generator convention: positive into network)
        S = complex(P, Q)
        Ia = (S / Vt).conjugate()

        # Internal voltage (E')
        Eq_prime_c = Vt + complex(Ra, Xd_prime) * Ia
        delta0 = np.angle(Eq_prime_c)
        Eq_prime = abs(Eq_prime_c)

        # Initial mechanical power = initial electrical power (steady state)
        Pe_0 = P
        Pm   = Pe_0

        gen_data.append(dict(
            name=gen.name,
            bus_id=gen.bus_id,
            pp_bus=pp_bus,
            delta0=delta0,
            omega0=0.0,
            H=gen.H_s or 5.0,
            D=gen.D or 2.0,
            Pm=Pm,
            Eq_prime=Eq_prime,
            Xd_prime=Xd_prime,
            Ra=Ra,
            sn_mva=gen.sn_mva or 100.0,
        ))

    return gen_data


# ---------------------------------------------------------------------------
# Reduced Y-bus (generator internal nodes)
# ---------------------------------------------------------------------------

def _build_reduced_ybus(net, gen_data, fault_pp_bus, faulted: bool):
    """
    Build the reduced admittance matrix between generator internal nodes.
    Uses a simplified approach: connect each generator through Xd' to its terminal bus,
    then Kron-reduce to eliminate load buses.
    """
    n = len(gen_data)
    Y = np.zeros((n, n), dtype=complex)

    if n == 0:
        return Y

    for i in range(n):
        for j in range(n):
            if i == j:
                # Self admittance: 1/jXd' + sum of network admittances
                Y[i, i] = complex(gen_data[i]["Ra"], gen_data[i]["Xd_prime"])
                Y[i, i] = 1.0 / complex(gen_data[i]["Ra"], gen_data[i]["Xd_prime"])
                # Add load conductance at generator bus
                Y[i, i] += 1.0 / complex(0.001, 0.1)   # simplified load representation
                if faulted and gen_data[i]["pp_bus"] == fault_pp_bus:
                    # Fault at this bus: add large shunt (short circuit)
                    Y[i, i] += complex(0, -1e6)
            else:
                # Transfer admittance (simplified: small coupling through network)
                # Full reduction would require building full Y-bus and Kron-reducing
                # For classical model with no network reduction, use simplified approach
                X_transfer = (gen_data[i]["Xd_prime"] + gen_data[j]["Xd_prime"]) * 2.0
                if faulted:
                    X_transfer *= 3.0  # fault increases impedance between machines
                Y[i, j] = -1.0 / complex(0, X_transfer)

    return Y


# ---------------------------------------------------------------------------
# CCT estimation via bisection
# ---------------------------------------------------------------------------

def _estimate_cct(project_id, fault_bus_id, fault_start, fault_clear_initial,
                  sim_time, dt, omega_s, f0, n, gen_data, x0,
                  delta_limit_deg, Ybus_pre, Ybus_fault, Ybus_post):
    """Estimate critical clearing time using bisection method."""
    lo, hi = fault_start, min(fault_start + 1.0, sim_time * 0.8)
    tol = 0.005  # 5 ms precision

    def is_stable(tc):
        def swing(t, x):
            deltas = x[:n]
            omegas = x[n:]
            dx = np.zeros(2 * n)
            Y = Ybus_pre if t < fault_start else (Ybus_fault if t < tc else Ybus_post)
            for i in range(n):
                Pe_i = sum(
                    gen_data[i]["Eq_prime"] * gen_data[j]["Eq_prime"] * (
                        Y[i, j].real * np.cos(deltas[i] - deltas[j]) +
                        Y[i, j].imag * np.sin(deltas[i] - deltas[j])
                    )
                    for j in range(n)
                )
                dx[i]     = omega_s * omegas[i]
                dx[n + i] = (np.pi * f0 / gen_data[i]["H"]) * (
                    gen_data[i]["Pm"] - Pe_i - gen_data[i]["D"] * omegas[i]
                )
            return dx

        try:
            sol = solve_ivp(swing, (0, sim_time), x0, method="RK45",
                            rtol=1e-4, atol=1e-6, max_step=dt * 2)
            for i in range(n):
                if np.any(np.abs(np.degrees(sol.y[i])) > delta_limit_deg):
                    return False
            return True
        except Exception:
            return False

    if not is_stable(hi):
        hi = fault_start + 0.05  # system unstable even at very short clearing
    if is_stable(hi):
        return round(hi, 3)  # stable for entire range

    for _ in range(20):
        mid = (lo + hi) / 2
        if is_stable(mid):
            lo = mid
        else:
            hi = mid
        if hi - lo < tol:
            break

    return round(lo, 3)


def _build_ts_summary(gen_results, stable, fault_start, fault_clear, cct) -> list[str]:
    findings = []
    if stable:
        findings.append(f"System remains STABLE after fault at t={fault_start}s cleared at t={fault_clear}s.")
    else:
        unstable = [g["name"] for g in gen_results if not g["stable"]]
        findings.append(
            f"System is UNSTABLE. Generator(s) out of step: {', '.join(unstable)}"
        )
    findings.append(
        f"Estimated Critical Clearing Time (CCT): {cct:.3f} s  "
        f"(actual clearing time: {fault_clear:.3f} s)"
    )
    margin = cct - fault_clear
    if margin >= 0:
        findings.append(f"Stability margin: {margin:.3f} s  ({'ADEQUATE' if margin > 0.1 else 'MARGINAL'})")
    else:
        findings.append(
            f"CRITICAL: Fault clearing time exceeds CCT by {abs(margin)*1000:.0f} ms – "
            "reduce protection clearing times."
        )
    for g in gen_results:
        findings.append(
            f"  {g['name']}: max δ = {g['max_delta_deg']:.1f}°  "
            f"(initial: {g['initial_delta_deg']:.1f}°)  "
            f"→ {'STABLE' if g['stable'] else 'UNSTABLE'}"
        )
    return findings
