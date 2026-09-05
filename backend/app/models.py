"""Aggregate import of all ORM models.

Importing this module registers every model on ``Base.metadata`` — used by
Alembic (autogenerate / bootstrap) and anywhere the full schema is needed.
"""

from __future__ import annotations

from app.alerts.models import Alert
from app.alerts.verification_models import AlertVerification
from app.apikeys.models import ApiKey
from app.deforestation.models import DeforestationCheck
from app.forecast_comparison.models import ForecastSnapshot
from app.lightning.models import LightningStrike
from app.locations.models import AlertPreference, Location
from app.ndvi.models import NdviImage, NdviReading
from app.notifications.models import Notification, PushSubscription
from app.reports.models import UserReport
from app.satellite.models import ConvectiveWatch, SatelliteImage
from app.storms.models import StormCell, StormObservation, StormRisk, StormTrack
from app.tenants.models import Tenant
from app.users.models import User
from app.weather.models import RadarFrame, WeatherSource
from app.zarc.models import ZarcRiskWindow

__all__ = [
    "Alert",
    "AlertPreference",
    "AlertVerification",
    "ApiKey",
    "ConvectiveWatch",
    "DeforestationCheck",
    "ForecastSnapshot",
    "LightningStrike",
    "Location",
    "NdviImage",
    "NdviReading",
    "Notification",
    "PushSubscription",
    "RadarFrame",
    "SatelliteImage",
    "StormCell",
    "StormObservation",
    "StormRisk",
    "StormTrack",
    "Tenant",
    "User",
    "UserReport",
    "WeatherSource",
    "ZarcRiskWindow",
]
