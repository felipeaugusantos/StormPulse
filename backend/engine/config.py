"""Engine tunables — centralized, documented, no magic numbers in algorithms.

Kept as frozen dataclasses so the engine stays self-contained (a worker may
build these from application settings later). Every threshold that shapes a
classification lives here.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DetectionConfig:
    """Thresholds for turning raw cells into detected storm cells.

    ⚠️ EXPERIMENTAL: coarse severity from reflectivity/area only. This is a
    development placeholder — it does NOT identify supercells and must not be
    presented as a validated meteorological classification (see ADR-0005).
    """

    # Minimum reflectivity (dBZ) for a raw cell to count as a storm cell.
    min_reflectivity_dbz: float = 35.0
    # Reflectivity (dBZ) lower bounds for each severity bucket.
    moderate_dbz: float = 40.0
    strong_dbz: float = 50.0
    severe_dbz: float = 55.0
    # Half-size (km) of the square footprint drawn around a cell centroid.
    footprint_half_km: float = 5.0


@dataclass(frozen=True)
class TrackingConfig:
    """Parameters for associating cells across consecutive frames."""

    # Max centroid displacement (km) between frames to be the same cell.
    max_association_km: float = 40.0


@dataclass(frozen=True)
class TrajectoryConfig:
    """Parameters for trajectory/trend estimation."""

    # Reflectivity change (dBZ) above which a track is intensifying/weakening.
    trend_delta_dbz: float = 3.0
    # Minimum speed (km/h) for an ETA to be meaningful.
    min_speed_kmh: float = 1.0


@dataclass(frozen=True)
class RiskConfig:
    """Parameters for the rule-based risk engine (FASE 8).

    ⚠️ EXPERIMENTAL: documented heuristics over possibly-simulated data. Not a
    validated meteorological model (ADR-0005). All shaping constants live here.
    """

    # Base intensity contributed by each severity bucket (0..1).
    intensity_weak: float = 0.20
    intensity_moderate: float = 0.50
    intensity_strong: float = 0.75
    intensity_severe: float = 1.00
    # Distance (km) at/above which proximity contributes nothing.
    reference_range_km: float = 120.0
    # ETA (min) horizon within which imminence ramps up.
    eta_horizon_min: float = 60.0
    # Wind reference (km/h) that saturates the wind hazard.
    wind_speed_ref_kmh: float = 80.0
    # Peak reflectivity (dBZ) at/above which hail becomes likely.
    hail_reflectivity_dbz: float = 55.0
    # Aggregate score weights (should sum to 1.0).
    weight_hazard: float = 0.60
    weight_proximity: float = 0.20
    weight_imminence: float = 0.20


DEFAULT_DETECTION = DetectionConfig()
DEFAULT_TRACKING = TrackingConfig()
DEFAULT_TRAJECTORY = TrajectoryConfig()
DEFAULT_RISK = RiskConfig()
