"""
Seed Sample Project
===================
Creates a representative 5-bus, 60 Hz power system in the SQLite database so
that all analysis pages can be exercised out-of-the-box.

Network topology
----------------
   BUS1 (Slack, 115 kV) ─── L1 ─── BUS2 (PV, 115 kV) ─── L2 ─── BUS3 (PQ, 115 kV)
                                          │                              │
                                        T1 (115/13.8 kV)             C1-bank
                                          │
                                       BUS4 (PQ, 13.8 kV) ─── T2 ─── BUS5 (PQ, 4.16 kV)

Equipment
---------
  • 5 buses
  • 2 overhead lines
  • 2 transformers  (115/13.8 kV  and  13.8/4.16 kV)
  • 1 generator     (at BUS2, PV 50 MW)
  • 3 loads         (BUS3 20 MW, BUS4 30 MW, BUS5 8 MW)
  • 1 shunt cap     (BUS4, +10 Mvar)
  • 2 protection devices (zone-1 relays on each transformer feeder)
  • 1 grounding grid (at BUS4 substation, IEEE 80-2013)

Run
---
    python sample_data/seed_project.py            # from project root
    python seed_project.py                        # from sample_data/
"""
import sys
from pathlib import Path

# Allow running from either project root or sample_data/
HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from datetime import datetime
from models.database import init_db, get_session
from models.schema import (
    Project, Bus, Line, Transformer, Generator,
    Load, Shunt, ProtectionDevice, GroundingGrid,
)

PROJECT_NAME = "Sample 5-Bus System (115/13.8/4.16 kV)"


def seed():
    init_db()
    session = get_session()
    try:
        # ── Delete any previous sample project ──────────────────────────────
        existing = session.query(Project).filter_by(name=PROJECT_NAME).first()
        if existing:
            print(f"  → Deleting existing project id={existing.id}")
            session.delete(existing)
            session.commit()

        # ── Project ─────────────────────────────────────────────────────────
        project = Project(
            name=PROJECT_NAME,
            description=(
                "Demonstration project: 5-bus, 60 Hz network with "
                "HV/MV/LV voltage levels.  Used for automated validation."
            ),
            client="ABC Utility Corp.",
            engineer="J. Doe, P.E.",
            date=datetime.today().strftime("%Y-%m-%d"),
            mva_base=100.0,
            frequency=60.0,
        )
        session.add(project)
        session.flush()  # get project.id
        pid = project.id
        print(f"  → Created project id={pid}: {PROJECT_NAME}")

        # ── Buses ────────────────────────────────────────────────────────────
        bus1 = Bus(project_id=pid, name="BUS1-SLACK", base_kv=115.0,
                   bus_type=3, vm_pu=1.02, zone="HV")
        bus2 = Bus(project_id=pid, name="BUS2-GEN",   base_kv=115.0,
                   bus_type=2, vm_pu=1.02, zone="HV")
        bus3 = Bus(project_id=pid, name="BUS3-HV",    base_kv=115.0,
                   bus_type=1, vm_pu=1.00, zone="HV")
        bus4 = Bus(project_id=pid, name="BUS4-MV",    base_kv=13.8,
                   bus_type=1, vm_pu=1.00, zone="MV")
        bus5 = Bus(project_id=pid, name="BUS5-LV",    base_kv=4.16,
                   bus_type=1, vm_pu=1.00, zone="LV")
        session.add_all([bus1, bus2, bus3, bus4, bus5])
        session.flush()
        buses = [bus1, bus2, bus3, bus4, bus5]
        print(f"  → Added {len(buses)} buses")

        # ── Lines ────────────────────────────────────────────────────────────
        # ACSR "Dove" 795 kcmil: r=0.0539 Ω/km, x=0.3543 Ω/km, rated 1.0 kA
        line1 = Line(
            project_id=pid, name="L1-BUS1-BUS2",
            from_bus_id=bus1.id, to_bus_id=bus2.id,
            r_ohm_per_km=0.054, x_ohm_per_km=0.355,
            c_nf_per_km=11.0,   length_km=25.0,
            max_i_ka=1.0,
            r0_ohm_per_km=0.162, x0_ohm_per_km=1.065,
        )
        line2 = Line(
            project_id=pid, name="L2-BUS2-BUS3",
            from_bus_id=bus2.id, to_bus_id=bus3.id,
            r_ohm_per_km=0.054, x_ohm_per_km=0.355,
            c_nf_per_km=11.0,   length_km=30.0,
            max_i_ka=1.0,
            r0_ohm_per_km=0.162, x0_ohm_per_km=1.065,
        )
        session.add_all([line1, line2])
        print("  → Added 2 lines")

        # ── Transformers ─────────────────────────────────────────────────────
        trafo1 = Transformer(
            project_id=pid, name="T1-115/13.8kV-50MVA",
            hv_bus_id=bus2.id, lv_bus_id=bus4.id,
            sn_mva=50.0, vn_hv_kv=115.0, vn_lv_kv=13.8,
            vk_percent=11.0, vkr_percent=0.5,
            pfe_kw=70.0, i0_percent=0.07,
            vector_group="Dyn11",
            tap_pos=0, tap_neutral=0, tap_min=-2, tap_max=2, tap_step_pct=2.5,
        )
        trafo2 = Transformer(
            project_id=pid, name="T2-13.8/4.16kV-10MVA",
            hv_bus_id=bus4.id, lv_bus_id=bus5.id,
            sn_mva=10.0, vn_hv_kv=13.8, vn_lv_kv=4.16,
            vk_percent=6.5, vkr_percent=0.8,
            pfe_kw=20.0, i0_percent=0.1,
            vector_group="Dyn11",
            tap_pos=0, tap_neutral=0, tap_min=-2, tap_max=2, tap_step_pct=2.5,
        )
        session.add_all([trafo1, trafo2])
        print("  → Added 2 transformers")

        # ── Generator ────────────────────────────────────────────────────────
        gen1 = Generator(
            project_id=pid, name="G1-BUS2",
            bus_id=bus2.id,
            p_mw=50.0, vm_pu=1.02,
            sn_mva=62.5,
            max_q_mvar=30.0, min_q_mvar=-20.0,
            # IEEE machine parameters
            xd_pu=1.80, xd_prime_pu=0.28, xd_dbl_prime_pu=0.20,
            xq_pu=1.70, xq_prime_pu=0.55,
            x2_pu=0.20, x0_pu=0.06,
            ra_pu=0.003,
            H_s=5.5, D=2.0,
        )
        session.add(gen1)
        print("  → Added 1 generator")

        # ── Loads ─────────────────────────────────────────────────────────────
        load1 = Load(project_id=pid, name="LOAD-BUS3",  bus_id=bus3.id,
                     p_mw=20.0, q_mvar=8.0)
        load2 = Load(project_id=pid, name="LOAD-BUS4",  bus_id=bus4.id,
                     p_mw=30.0, q_mvar=12.0)
        load3 = Load(project_id=pid, name="LOAD-BUS5",  bus_id=bus5.id,
                     p_mw=8.0,  q_mvar=3.5)
        session.add_all([load1, load2, load3])
        print("  → Added 3 loads")

        # ── Shunt (cap bank) ─────────────────────────────────────────────────
        cap1 = Shunt(project_id=pid, name="CAPBANK-BUS4",
                     bus_id=bus4.id, q_mvar=10.0)   # +10 Mvar capacitive
        session.add(cap1)
        print("  → Added 1 shunt (cap bank)")

        # ── Protection Devices ───────────────────────────────────────────────
        # Relay-1: downstream (feeder from BUS4)
        relay1 = ProtectionDevice(
            project_id=pid, name="R1-T1-LV-Feeder",
            bus_id=bus4.id,
            device_type="overcurrent",
            pickup_current_a=150.0,   # primary amps
            tds=0.30,
            curve_type="EI",          # Extremely Inverse (IEC)
            ct_ratio="400/5",
            ct_ratio_num=80.0,
            inst_pickup_a=3500.0,
            inst_delay_s=0.05,
            coord_order=1,
        )
        # Relay-2: upstream (HV side of T1)
        relay2 = ProtectionDevice(
            project_id=pid, name="R2-T1-HV-Backup",
            bus_id=bus2.id,
            device_type="overcurrent",
            pickup_current_a=60.0,    # referred to 115 kV side
            tds=0.60,
            curve_type="EI",
            ct_ratio="100/5",
            ct_ratio_num=20.0,
            inst_pickup_a=800.0,
            inst_delay_s=0.05,
            coord_order=2,
        )
        session.add_all([relay1, relay2])
        print("  → Added 2 protection devices")

        # ── Grounding Grid ───────────────────────────────────────────────────
        grid1 = GroundingGrid(
            project_id=pid, name="GRID-BUS4-Substation",
            bus_id=bus4.id,
            # 40 m × 40 m grid with 5 m spacing, 0.5 m deep
            grid_length_m=40.0, grid_width_m=40.0,
            conductor_spacing_m=5.0, burial_depth_m=0.5,
            conductor_diameter_m=0.0112,   # ~4/0 AWG copper
            # Ground rods
            num_ground_rods=8, rod_length_m=3.0, rod_diameter_m=0.016,
            # Soil: moderately resistive, crushed-rock surface layer
            soil_resistivity_ohm_m=120.0,
            surface_resistivity_ohm_m=2500.0,
            surface_layer_depth_m=0.1,
            # Fault
            fault_current_ka=8.0,
            fault_duration_s=0.5,
            decrement_factor=1.0,
        )
        session.add(grid1)
        print("  → Added 1 grounding grid")

        session.commit()
        print(f"\n✅ Seed complete. Project id={pid} ready for validation.\n")
        return pid

    except Exception as exc:
        session.rollback()
        print(f"\n❌ Seed failed: {exc}")
        import traceback; traceback.print_exc()
        return None
    finally:
        session.close()


if __name__ == "__main__":
    print("=" * 60)
    print("Power System Analyzer – Sample Project Seeder")
    print("=" * 60)
    pid = seed()
    sys.exit(0 if pid else 1)
