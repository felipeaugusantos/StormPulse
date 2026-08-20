"""Central domain enumerations.

Kept in one place so values are consistent across models, schemas and the
storm engine. String-valued enums serialize cleanly over JSON and map to
native Postgres enums via SQLAlchemy.
"""

from __future__ import annotations

from enum import StrEnum


class UserRole(StrEnum):
    """RBAC roles. ADMIN/USER now; the rest are reserved for later phases."""

    ADMIN = "admin"
    USER = "user"
    # Reserved (FASE 18): METEOROLOGIST, COMPANY_ADMIN, OPERATOR
    METEOROLOGIST = "meteorologist"
    COMPANY_ADMIN = "company_admin"
    OPERATOR = "operator"


class AlertType(StrEnum):
    """Types of alert a user can enable per monitored location."""

    RAIN_INTENSE = "rain_intense"
    SEVERE_STORM = "severe_storm"
    STRONG_WIND = "strong_wind"
    HAIL = "hail"
    LIGHTNING = "lightning"
    SEVERE_CELL = "severe_cell"


class RiskLevel(StrEnum):
    """Actionable alert levels. Thresholds are configurable (see thresholds.py)."""

    GREEN = "green"
    YELLOW = "yellow"
    ORANGE = "orange"
    RED = "red"


class StormSeverity(StrEnum):
    """Coarse severity classification of a detected cell (deterministic)."""

    WEAK = "weak"
    MODERATE = "moderate"
    STRONG = "strong"
    SEVERE = "severe"


class TrackTrend(StrEnum):
    """How a storm cell is evolving over time."""

    INTENSIFYING = "intensifying"
    STEADY = "steady"
    WEAKENING = "weakening"


class WeatherSourceKind(StrEnum):
    """Provenance of weather data. MOCK must always be explicit."""

    MOCK = "mock"
    RADAR = "radar"
    SATELLITE = "satellite"
    STATION = "station"
    OFFICIAL_WARNING = "official_warning"
    FORECAST_MODEL = "forecast_model"


class AlertEventType(StrEnum):
    """Event-driven alert lifecycle (see architecture — alerts are event-based)."""

    STORM_DETECTED = "storm_detected"
    STORM_APPROACHING = "storm_approaching"
    STORM_INTENSIFIED = "storm_intensified"
    STORM_ENTERED_MONITORING_AREA = "storm_entered_monitoring_area"
    STORM_RISK_CHANGED = "storm_risk_changed"
    STORM_PASSED = "storm_passed"
    # Satellite-derived convective watches (FASE 16) — a distinct, earlier
    # and less certain signal than a confirmed storm cell; never conflated
    # with the STORM_* events above.
    SATELLITE_WATCH_DETECTED = "satellite_watch_detected"
    SATELLITE_WATCH_DISSIPATED = "satellite_watch_dissipated"
    # Agronomic advisories (FASE 19) — derived from forecast/historical
    # readings already collected, evaluated per monitored Location on its
    # own schedule (see workers/agro_pipeline.py), not from the storm engine.
    FROST_WARNING = "frost_warning"
    DRY_SPELL_WARNING = "dry_spell_warning"


class NotificationChannel(StrEnum):
    PUSH = "push"  # Firebase Cloud Messaging (FASE 9)
    EMAIL = "email"


class NotificationStatus(StrEnum):
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"
    SUPPRESSED = "suppressed"  # withheld by anti-spam rules


class ReportType(StrEnum):
    """Crowdsourced report categories (architecture prepared — FASE 16)."""

    HAIL = "hail"
    STRONG_WIND = "strong_wind"
    FLOODING = "flooding"
    RAIN_INTENSE = "rain_intense"
    FALLEN_TREE = "fallen_tree"
    LIGHTNING = "lightning"


class ReportStatus(StrEnum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"
