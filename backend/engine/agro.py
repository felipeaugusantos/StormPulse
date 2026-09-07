"""Agro signal math shared server-side (Fase 3 — Alertas Personalizados).

VPD and disease-risk were, until now, only ever computed client-side
(``web/src/agro.ts``/``mobile/src/agro.ts``) from data the frontend already
had in hand — fine for a dashboard card, but a custom alert rule needs to
evaluate these unattended, in a backend pipeline, with nobody's browser
open. Ported here verbatim (same formula/thresholds) so both the frontend
display and the backend rule engine agree on what "high VPD" means.
"""

from __future__ import annotations

import math
from typing import Literal

DiseaseRisk = Literal["low", "high", "unknown"]
VpdLevel = Literal["low", "ideal", "high", "unknown"]


def vapor_pressure_deficit_kpa(temperature_mean_c: float, humidity_mean_percent: float) -> float:
    """Vapor Pressure Deficit (kPa) — Tetens/FAO-56 saturation vapor
    pressure formula. Low VPD (<0.4 kPa) means reduced transpiration/
    nutrient uptake; high (>1.6 kPa) means plant stress from excessive
    water loss."""
    svp = 0.6108 * math.exp((17.27 * temperature_mean_c) / (temperature_mean_c + 237.3))
    return svp * (1 - humidity_mean_percent / 100)


def classify_vpd(vpd_kpa: float) -> VpdLevel:
    if vpd_kpa < 0.4:
        return "low"
    if vpd_kpa <= 1.6:
        return "ideal"
    return "high"


def classify_disease_risk(
    humidity_mean_percent: float | None,
    temperature_mean_c: float | None,
    *,
    humidity_threshold_percent: float,
    min_temp_c: float,
    max_temp_c: float,
) -> DiseaseRisk:
    """Simplified daily proxy for fungal disease pressure: high humidity in
    a mild temperature band favors fungal growth. A real model needs
    consecutive-hours-above-threshold tracking, which the daily-granularity
    forecast doesn't have — this is an approximation, not a diagnosis."""
    if humidity_mean_percent is None or temperature_mean_c is None:
        return "unknown"
    humid = humidity_mean_percent >= humidity_threshold_percent
    mild_temp = min_temp_c <= temperature_mean_c <= max_temp_c
    return "high" if humid and mild_temp else "low"
