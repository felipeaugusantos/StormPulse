"""Aggregate import of all ORM models.

Importing this module registers every model on ``Base.metadata`` — used by
Alembic (autogenerate / bootstrap) and anywhere the full schema is needed.
"""

from __future__ import annotations

from app.alerts.models import Alert
from app.locations.models import AlertPreference, Location
from app.notifications.models import Notification
from app.reports.models import UserReport
from app.storms.models import StormCell, StormObservation, StormRisk, StormTrack
from app.tenants.models import Tenant
from app.users.models import User
from app.weather.models import RadarFrame, WeatherSource

__all__ = [
    "Alert",
    "AlertPreference",
    "Location",
    "Notification",
    "RadarFrame",
    "StormCell",
    "StormObservation",
    "StormRisk",
    "StormTrack",
    "Tenant",
    "User",
    "UserReport",
    "WeatherSource",
]
