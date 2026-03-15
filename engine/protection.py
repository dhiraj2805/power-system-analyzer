"""
Protective Device Coordination Engine
Supports ANSI/IEEE (IEEE C37.112) and IEC 60255 overcurrent relay curves.
Checks coordination time interval (CTI) margins and recommends settings.
"""
import traceback
import math
import numpy as np

from models.database import get_session
from models.schema import ProtectionDevice, Bus


# ---------------------------------------------------------------------------
# Curve constants
# ---------------------------------------------------------------------------

# ANSI/IEEE C37.112-1996  t = TDS * (A / (M^p - 1) + B)
# IEC 60255-151           t = TMS * (A / (M^p - 1))
CURVE_CONSTANTS = {
    "SI":     {"A": 0.0514,  "B": 0.1140, "p": 0.02,  "label": "Standard Inverse (ANSI)",        "std": "ANSI"},
    "VI":     {"A": 19.61,   "B": 0.491,  "p": 2.0,   "label": "Very Inverse (ANSI)",             "std": "ANSI"},
    "EI":     {"A": 28.2,    "B": 0.1217, "p": 2.0,   "label": "Extremely Inverse (ANSI)",        "std": "ANSI"},
    "LTI":    {"A": 120.0,   "B": 0.0,    "p": 1.0,   "label": "Long Time Inverse (ANSI)",        "std": "ANSI"},
    "IEC_SI": {"A": 0.14,    "B": 0.0,    "p": 0.02,  "label": "Standard Inverse (IEC 60255)",    "std": "IEC"},
    "IEC_VI": {"A": 13.5,    "B": 0.0,    "p": 1.0,   "label": "Very Inverse (IEC 60255)",        "std": "IEC"},
    "IEC_EI": {"A": 80.0,    "B": 0.0,    "p": 2.0,   "label": "Extremely Inverse (IEC 60255)",   "std": "IEC"},
}

# Minimum recommended coordination time interval (s)
DEFAULT_CTI = 0.30   # 300 ms (typical for electromechanical relays / breakers)
MIN_CTI_DIGITAL = 0.20   # 200 ms (numerical relays)


# ---------------------------------------------------------------------------
# Core curve calculation
# ---------------------------------------------------------------------------

def relay_time(I_fault_a: float, pickup_a: float, tds: float, curve: str = "VI") -> float:
    """
    Calculate relay operating time for an overcurrent relay.

    Parameters
    ----------
    I_fault_a : fault current (A, primary)
    pickup_a  : relay pickup current (A, primary)
    tds       : time-dial setting (ANSI TDS or IEC TMS)
    curve     : curve identifier key

    Returns operating time in seconds, or inf if below pickup.
    """
    if I_fault_a <= pickup_a or pickup_a <= 0:
        return math.inf

    M = I_fault_a / pickup_a
    if M <= 1.0:
        return math.inf

    C = CURVE_CONSTANTS.get(curve, CURVE_CONSTANTS["VI"])
    denom = M ** C["p"] - 1
    if denom <= 0:
        return math.inf

    t = tds * (C["A"] / denom + C["B"])
    return max(t, 0.0)


def relay_time_curve(I_range, pickup_a: float, tds: float, curve: str = "VI") -> list[float]:
    """Return list of operating times for an array of fault currents."""
    return [relay_time(I, pickup_a, tds, curve) for I in I_range]


# ---------------------------------------------------------------------------
# TCC data for plotting
# ---------------------------------------------------------------------------

def build_tcc_data(device: dict, I_min: float, I_max: float, n_points: int = 200) -> dict:
    """
    Build time-current characteristic data for plotting (log-log scale).

    device: dict with keys pickup_current_a, tds, curve_type, name, inst_pickup_a, inst_delay_s
    """
    I_range = np.logspace(np.log10(max(I_min, device["pickup_current_a"] * 1.01)),
                          np.log10(I_max), n_points).tolist()
    times = relay_time_curve(I_range, device["pickup_current_a"], device["tds"], device["curve_type"])

    # Clip infinite values
    result_I = []
    result_t = []
    for I, t in zip(I_range, times):
        if math.isfinite(t) and t > 0 and t < 100:
            result_I.append(round(I, 2))
            result_t.append(round(t, 4))

    # Add instantaneous element
    inst_I = []
    inst_t = []
    if device.get("inst_pickup_a") and device["inst_pickup_a"] > 0:
        inst_I = [device["inst_pickup_a"], I_max]
        inst_t = [device.get("inst_delay_s", 0.05)] * 2

    return dict(
        name=device["name"],
        curve_I=result_I,
        curve_t=result_t,
        pickup_a=device["pickup_current_a"],
        tds=device["tds"],
        curve_type=device["curve_type"],
        inst_I=inst_I,
        inst_t=inst_t,
    )


# ---------------------------------------------------------------------------
# Coordination check
# ---------------------------------------------------------------------------

def check_coordination(project_id: int, cti: float = DEFAULT_CTI,
                       fault_current_range: list[float] = None) -> dict:
    """
    Check coordination between all overcurrent protection devices in a project.

    Devices are sorted by coord_order (1 = most downstream).
    For each adjacent pair, the upstream device must operate at least CTI
    seconds AFTER the downstream device for every fault current.
    """
    session = get_session()
    try:
        devices = (
            session.query(ProtectionDevice)
            .filter_by(project_id=project_id, in_service=True)
            .order_by(ProtectionDevice.coord_order)
            .all()
        )

        if len(devices) < 2:
            return {
                "error": "At least 2 protection devices required for coordination check.",
                "devices": _devices_to_list(devices),
            }

        # Build fault current test range if not provided
        if fault_current_range is None:
            max_pickup = max(d.pickup_current_a for d in devices)
            fault_current_range = list(np.logspace(
                np.log10(max_pickup * 2),
                np.log10(max_pickup * 20),
                20,
            ))

        pairs_results = []
        all_coordinated = True

        for i in range(len(devices) - 1):
            ds = devices[i]    # downstream (lower coord_order)
            us = devices[i + 1]  # upstream (higher coord_order)

            margins = []
            for I in fault_current_range:
                t_ds = relay_time(I, ds.pickup_current_a, ds.tds, ds.curve_type)
                t_us = relay_time(I, us.pickup_current_a, us.tds, us.curve_type)

                if math.isinf(t_ds) and math.isinf(t_us):
                    continue  # neither relay sees this fault
                if math.isinf(t_ds):
                    continue  # downstream doesn't see fault – skip
                if math.isinf(t_us):
                    continue  # upstream doesn't see fault (should not happen for upstream)

                margin = t_us - t_ds
                margins.append(dict(
                    fault_a=round(I, 1),
                    t_downstream_s=round(t_ds, 3),
                    t_upstream_s=round(t_us, 3),
                    margin_s=round(margin, 3),
                    ok=margin >= cti,
                ))

            pair_ok = all(m["ok"] for m in margins) if margins else True
            if not pair_ok:
                all_coordinated = False

            min_margin = min((m["margin_s"] for m in margins), default=None)
            pairs_results.append(dict(
                downstream=ds.name,
                upstream=us.name,
                margins=margins,
                coordinated=pair_ok,
                min_margin_s=round(min_margin, 3) if min_margin is not None else None,
                required_cti_s=cti,
            ))

        # Build TCC plot data
        I_min = min(d.pickup_current_a for d in devices) * 0.8
        I_max = max(d.pickup_current_a for d in devices) * 30
        tcc_curves = [
            build_tcc_data(dict(
                name=d.name,
                pickup_current_a=d.pickup_current_a,
                tds=d.tds,
                curve_type=d.curve_type,
                inst_pickup_a=d.inst_pickup_a,
                inst_delay_s=d.inst_delay_s,
            ), I_min, I_max)
            for d in devices
        ]

        return dict(
            all_coordinated=all_coordinated,
            cti_used_s=cti,
            pairs=pairs_results,
            tcc_curves=tcc_curves,
            devices=_devices_to_list(devices),
            summary=_build_prot_summary(pairs_results, all_coordinated, cti),
        )

    except Exception as exc:
        return {"error": str(exc), "traceback": traceback.format_exc()}
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Setting recommendation
# ---------------------------------------------------------------------------

def recommend_settings(
    load_current_a: float,
    fault_max_a: float,
    fault_min_a: float,
    prev_device: dict = None,
    curve: str = "VI",
    cti: float = DEFAULT_CTI,
) -> dict:
    """
    Recommend overcurrent relay settings for a new/modified protection zone.

    Parameters
    ----------
    load_current_a : maximum load current (A, primary)
    fault_max_a    : maximum fault current at protected zone (A, primary)
    fault_min_a    : minimum fault current that must be detected (A, primary)
    prev_device    : dict with pickup_current_a, tds, curve_type of downstream device
    curve          : desired TCC curve
    cti            : required coordination time interval (s)
    """
    # Pickup: 125–150% of load, but must detect minimum fault (< 50% of min fault)
    pickup = max(load_current_a * 1.5, 1.0)
    detection_limit = fault_min_a / 2.0
    if pickup > detection_limit:
        pickup = fault_min_a / 3.0

    # TDS / TMS recommendation
    if prev_device:
        # Need to be slower than downstream device by at least CTI at all fault levels
        test_currents = np.logspace(
            np.log10(max(pickup * 1.1, prev_device["pickup_current_a"] * 1.1)),
            np.log10(fault_max_a),
            30,
        )
        min_tds = 0.05
        for I in test_currents:
            t_prev = relay_time(I, prev_device["pickup_current_a"], prev_device["tds"],
                                prev_device["curve_type"])
            if math.isinf(t_prev):
                continue
            target = t_prev + cti
            # Solve for tds: target = tds * f(M)
            M = I / pickup
            C = CURVE_CONSTANTS.get(curve, CURVE_CONSTANTS["VI"])
            denom = M ** C["p"] - 1
            if denom <= 0:
                continue
            f_M = C["A"] / denom + C["B"]
            if f_M > 0:
                needed = target / f_M
                min_tds = max(min_tds, needed)
        tds = round(min_tds + 0.02, 2)
        reason = (
            f"Pickup = {pickup:.0f} A (1.5× load). TDS derived from CTI ≥ {cti}s "
            f"over downstream device '{prev_device.get('name','?')}'."
        )
    else:
        tds = 0.50  # primary/main relay default
        reason = (
            f"Pickup = {pickup:.0f} A (1.5× load). TDS = 0.50 (typical primary relay)."
        )

    # Instantaneous element: 125–150% of max fault on the next section
    # or 80% of minimum fault at next bus (whichever is lower)
    inst_pickup = fault_max_a * 1.25  # conservative: not too sensitive

    return dict(
        pickup_a=round(pickup, 1),
        tds=round(tds, 2),
        curve=curve,
        curve_label=CURVE_CONSTANTS[curve]["label"],
        inst_pickup_a=round(inst_pickup, 1),
        inst_delay_s=0.05,
        reason=reason,
        # Verification
        operates_at_min_fault=(relay_time(fault_min_a, pickup, tds, curve) < 3.0),
        time_at_max_fault_s=round(relay_time(fault_max_a, pickup, tds, curve), 3),
        time_at_min_fault_s=round(relay_time(fault_min_a, pickup, tds, curve), 3),
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _devices_to_list(devices) -> list[dict]:
    return [dict(
        id=d.id,
        name=d.name,
        device_type=d.device_type,
        pickup_current_a=d.pickup_current_a,
        tds=d.tds,
        curve_type=d.curve_type,
        ct_ratio=d.ct_ratio,
        coord_order=d.coord_order,
        inst_pickup_a=d.inst_pickup_a,
        inst_delay_s=d.inst_delay_s,
    ) for d in devices]


def _build_prot_summary(pairs: list, all_coordinated: bool, cti: float) -> list[str]:
    findings = []
    if all_coordinated:
        findings.append(f"All adjacent device pairs are coordinated with CTI ≥ {cti*1000:.0f} ms.")
    else:
        bad = [p for p in pairs if not p["coordinated"]]
        findings.append(
            f"COORDINATION PROBLEM: {len(bad)} pair(s) fail CTI ≥ {cti*1000:.0f} ms requirement:"
        )
        for p in bad:
            findings.append(
                f"  • {p['downstream']} → {p['upstream']}: "
                f"minimum margin = {p['min_margin_s']*1000:.0f} ms (required {cti*1000:.0f} ms)"
            )
        findings.append(
            "Recommendation: Increase upstream TDS or reduce downstream TDS "
            "to achieve the required CTI margin."
        )
    findings.append(
        "Per IEEE C37.112, CTI ≥ 300 ms is recommended for electromechanical relays; "
        "≥ 200 ms for numerical relays."
    )
    return findings


def available_curves() -> list[dict]:
    """Return list of available curve types with labels for UI dropdowns."""
    return [
        {"key": k, "label": v["label"], "std": v["std"]}
        for k, v in CURVE_CONSTANTS.items()
    ]
