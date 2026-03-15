"""SQLAlchemy ORM models for all power-system equipment."""
from datetime import datetime
from sqlalchemy import (
    Column, Integer, Float, String, Boolean, Text, DateTime,
    ForeignKey, JSON,
)
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------------------
# Project
# ---------------------------------------------------------------------------
class Project(Base):
    __tablename__ = "projects"

    id          = Column(Integer, primary_key=True, autoincrement=True)
    name        = Column(String(200), nullable=False)
    description = Column(Text, default="")
    client      = Column(String(200), default="")
    engineer    = Column(String(200), default="")
    date        = Column(String(50), default="")
    mva_base    = Column(Float, default=100.0)   # system MVA base
    frequency   = Column(Float, default=60.0)    # Hz
    created_at  = Column(DateTime, default=datetime.utcnow)

    buses        = relationship("Bus",             back_populates="project", cascade="all, delete-orphan")
    lines        = relationship("Line",            back_populates="project", cascade="all, delete-orphan")
    transformers = relationship("Transformer",     back_populates="project", cascade="all, delete-orphan")
    generators   = relationship("Generator",       back_populates="project", cascade="all, delete-orphan")
    loads        = relationship("Load",            back_populates="project", cascade="all, delete-orphan")
    shunts       = relationship("Shunt",           back_populates="project", cascade="all, delete-orphan")
    prot_devices = relationship("ProtectionDevice",back_populates="project", cascade="all, delete-orphan")
    grounding    = relationship("GroundingGrid",   back_populates="project", cascade="all, delete-orphan")
    results      = relationship("AnalysisResult",  back_populates="project", cascade="all, delete-orphan")


# ---------------------------------------------------------------------------
# Bus
# ---------------------------------------------------------------------------
class Bus(Base):
    __tablename__ = "buses"

    id          = Column(Integer, primary_key=True, autoincrement=True)
    project_id  = Column(Integer, ForeignKey("projects.id"), nullable=False, index=True)
    name        = Column(String(100), nullable=False)
    base_kv     = Column(Float, nullable=False)
    # 1=PQ load bus, 2=PV generator bus, 3=Slack/reference
    bus_type    = Column(Integer, default=1)
    zone        = Column(String(50), default="")
    # For PV buses: desired voltage magnitude
    vm_pu       = Column(Float, default=1.0)
    # Optional description / location
    notes       = Column(Text, default="")

    project = relationship("Project", back_populates="buses")


# ---------------------------------------------------------------------------
# Line (overhead / cable)
# ---------------------------------------------------------------------------
class Line(Base):
    __tablename__ = "lines"

    id              = Column(Integer, primary_key=True, autoincrement=True)
    project_id      = Column(Integer, ForeignKey("projects.id"), nullable=False, index=True)
    name            = Column(String(100), nullable=False)
    from_bus_id     = Column(Integer, ForeignKey("buses.id"), nullable=False)
    to_bus_id       = Column(Integer, ForeignKey("buses.id"), nullable=False)
    # Positive-sequence parameters (Ω/km)
    r_ohm_per_km    = Column(Float, nullable=False)
    x_ohm_per_km    = Column(Float, nullable=False)
    c_nf_per_km     = Column(Float, default=0.0)
    length_km       = Column(Float, nullable=False)
    max_i_ka        = Column(Float, default=1.0)   # thermal rating
    # Zero-sequence (for SC analysis)
    r0_ohm_per_km   = Column(Float, default=None)
    x0_ohm_per_km   = Column(Float, default=None)
    in_service      = Column(Boolean, default=True)
    notes           = Column(Text, default="")

    project  = relationship("Project", back_populates="lines")
    from_bus = relationship("Bus", foreign_keys=[from_bus_id])
    to_bus   = relationship("Bus", foreign_keys=[to_bus_id])


# ---------------------------------------------------------------------------
# Transformer (2-winding)
# ---------------------------------------------------------------------------
class Transformer(Base):
    __tablename__ = "transformers"

    id            = Column(Integer, primary_key=True, autoincrement=True)
    project_id    = Column(Integer, ForeignKey("projects.id"), nullable=False, index=True)
    name          = Column(String(100), nullable=False)
    hv_bus_id     = Column(Integer, ForeignKey("buses.id"), nullable=False)
    lv_bus_id     = Column(Integer, ForeignKey("buses.id"), nullable=False)
    sn_mva        = Column(Float, nullable=False)
    vn_hv_kv      = Column(Float, nullable=False)
    vn_lv_kv      = Column(Float, nullable=False)
    vk_percent    = Column(Float, nullable=False)   # short-circuit voltage %
    vkr_percent   = Column(Float, default=0.0)      # resistive component %
    pfe_kw        = Column(Float, default=0.0)      # iron loss
    i0_percent    = Column(Float, default=0.0)      # no-load current %
    vector_group  = Column(String(20), default="Dyn11")
    tap_pos       = Column(Integer, default=0)
    tap_neutral   = Column(Integer, default=0)
    tap_min       = Column(Integer, default=-2)
    tap_max       = Column(Integer, default=2)
    tap_step_pct  = Column(Float, default=2.5)
    in_service    = Column(Boolean, default=True)
    notes         = Column(Text, default="")

    project = relationship("Project", back_populates="transformers")
    hv_bus  = relationship("Bus", foreign_keys=[hv_bus_id])
    lv_bus  = relationship("Bus", foreign_keys=[lv_bus_id])


# ---------------------------------------------------------------------------
# Generator
# ---------------------------------------------------------------------------
class Generator(Base):
    __tablename__ = "generators"

    id              = Column(Integer, primary_key=True, autoincrement=True)
    project_id      = Column(Integer, ForeignKey("projects.id"), nullable=False, index=True)
    name            = Column(String(100), nullable=False)
    bus_id          = Column(Integer, ForeignKey("buses.id"), nullable=False)
    # Steady-state dispatch
    p_mw            = Column(Float, nullable=False)
    vm_pu           = Column(Float, default=1.0)   # voltage set-point
    max_q_mvar      = Column(Float, default=999.0)
    min_q_mvar      = Column(Float, default=-999.0)
    sn_mva          = Column(Float, default=100.0)
    # Machine impedances (p.u. on machine base)
    xd_pu           = Column(Float, default=1.8)    # d-axis synchronous
    xd_prime_pu     = Column(Float, default=0.3)    # d-axis transient
    xd_dbl_prime_pu = Column(Float, default=0.2)    # d-axis subtransient
    xq_pu           = Column(Float, default=1.7)    # q-axis synchronous
    xq_prime_pu     = Column(Float, default=0.55)
    x2_pu           = Column(Float, default=0.2)    # negative-sequence
    x0_pu           = Column(Float, default=0.05)   # zero-sequence
    ra_pu           = Column(Float, default=0.003)  # armature resistance
    # Dynamic parameters
    H_s             = Column(Float, default=5.0)    # inertia constant (s)
    D               = Column(Float, default=2.0)    # damping coefficient
    in_service      = Column(Boolean, default=True)
    notes           = Column(Text, default="")

    project = relationship("Project", back_populates="generators")
    bus     = relationship("Bus", foreign_keys=[bus_id])


# ---------------------------------------------------------------------------
# Load
# ---------------------------------------------------------------------------
class Load(Base):
    __tablename__ = "loads"

    id         = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False, index=True)
    name       = Column(String(100), nullable=False)
    bus_id     = Column(Integer, ForeignKey("buses.id"), nullable=False)
    p_mw       = Column(Float, nullable=False)
    q_mvar     = Column(Float, default=0.0)
    in_service = Column(Boolean, default=True)
    notes      = Column(Text, default="")

    project = relationship("Project", back_populates="loads")
    bus     = relationship("Bus", foreign_keys=[bus_id])


# ---------------------------------------------------------------------------
# Shunt (capacitor bank / reactor)
# ---------------------------------------------------------------------------
class Shunt(Base):
    __tablename__ = "shunts"

    id         = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False, index=True)
    name       = Column(String(100), nullable=False)
    bus_id     = Column(Integer, ForeignKey("buses.id"), nullable=False)
    # positive = capacitive (Mvar injected), negative = inductive (Mvar absorbed)
    q_mvar     = Column(Float, nullable=False)
    in_service = Column(Boolean, default=True)
    notes      = Column(Text, default="")

    project = relationship("Project", back_populates="shunts")
    bus     = relationship("Bus", foreign_keys=[bus_id])


# ---------------------------------------------------------------------------
# Protection Device
# ---------------------------------------------------------------------------
class ProtectionDevice(Base):
    __tablename__ = "protection_devices"

    id              = Column(Integer, primary_key=True, autoincrement=True)
    project_id      = Column(Integer, ForeignKey("projects.id"), nullable=False, index=True)
    name            = Column(String(100), nullable=False)
    bus_id          = Column(Integer, ForeignKey("buses.id"), nullable=True)
    # Type: overcurrent | differential | distance | fuse | recloser
    device_type     = Column(String(50), default="overcurrent")
    # Phase overcurrent settings
    pickup_current_a   = Column(Float, default=100.0)   # primary amps
    tds                = Column(Float, default=0.5)      # time-dial setting
    curve_type         = Column(String(20), default="VI") # SI/VI/EI/LTI/IEC_SI/IEC_VI/IEC_EI
    ct_ratio           = Column(String(20), default="200/5")
    ct_ratio_num       = Column(Float, default=40.0)     # numeric ratio
    # Instantaneous element
    inst_pickup_a      = Column(Float, default=None)
    inst_delay_s       = Column(Float, default=0.05)
    # Ground overcurrent
    gnd_pickup_a       = Column(Float, default=None)
    gnd_tds            = Column(Float, default=0.3)
    gnd_curve          = Column(String(20), default="EI")
    # Distance zones (Ω primary)
    zone1_reach_ohm    = Column(Float, default=None)
    zone2_reach_ohm    = Column(Float, default=None)
    zone3_reach_ohm    = Column(Float, default=None)
    zone2_timer_s      = Column(Float, default=0.3)
    zone3_timer_s      = Column(Float, default=0.6)
    # Ordering for coordination (1 = most downstream)
    coord_order        = Column(Integer, default=1)
    in_service         = Column(Boolean, default=True)
    notes              = Column(Text, default="")

    project = relationship("Project", back_populates="prot_devices")
    bus     = relationship("Bus", foreign_keys=[bus_id])


# ---------------------------------------------------------------------------
# Grounding Grid
# ---------------------------------------------------------------------------
class GroundingGrid(Base):
    __tablename__ = "grounding_grids"

    id                          = Column(Integer, primary_key=True, autoincrement=True)
    project_id                  = Column(Integer, ForeignKey("projects.id"), nullable=False, index=True)
    name                        = Column(String(100), nullable=False)
    bus_id                      = Column(Integer, ForeignKey("buses.id"), nullable=True)
    # Grid geometry
    grid_length_m               = Column(Float, default=50.0)
    grid_width_m                = Column(Float, default=50.0)
    conductor_spacing_m         = Column(Float, default=5.0)
    burial_depth_m              = Column(Float, default=0.5)
    conductor_diameter_m        = Column(Float, default=0.01)  # ~3/0 AWG copper
    # Ground rods
    num_ground_rods             = Column(Integer, default=0)
    rod_length_m                = Column(Float, default=3.0)
    rod_diameter_m              = Column(Float, default=0.016)
    # Soil
    soil_resistivity_ohm_m      = Column(Float, default=100.0)
    surface_resistivity_ohm_m   = Column(Float, default=2000.0)  # crushed rock
    surface_layer_depth_m       = Column(Float, default=0.1)
    # Fault
    fault_current_ka            = Column(Float, default=10.0)   # 3I0 in kA
    fault_duration_s            = Column(Float, default=0.5)    # clearing time
    decrement_factor            = Column(Float, default=1.0)    # Df per IEEE 80
    notes                       = Column(Text, default="")

    project = relationship("Project", back_populates="grounding")
    bus     = relationship("Bus", foreign_keys=[bus_id])


# ---------------------------------------------------------------------------
# Analysis Result  (stores JSON blob for each completed study)
# ---------------------------------------------------------------------------
class AnalysisResult(Base):
    __tablename__ = "analysis_results"

    id            = Column(Integer, primary_key=True, autoincrement=True)
    project_id    = Column(Integer, ForeignKey("projects.id"), nullable=False, index=True)
    analysis_type = Column(String(50), nullable=False)  # load_flow | short_circuit | transient | protection | grounding
    status        = Column(String(20), default="completed")  # completed | error
    result_json   = Column(JSON, nullable=True)
    error_msg     = Column(Text, default="")
    created_at    = Column(DateTime, default=datetime.utcnow)

    project = relationship("Project", back_populates="results")
