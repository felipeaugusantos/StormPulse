// Hardening ADR-0036 — shown on every screen with weather-derived content
// (Dashboard, VisitorView), not just documented in the README. StormPulse
// aggregates and simplifies signals; it is not validated as a
// safety-critical alerting system and must never be presented as a
// substitute for official channels.
export function SafetyDisclaimer() {
  return (
    <p className="safety-disclaimer">
      ⚠️ StormPulse não substitui alertas oficiais (INMET, Defesa Civil,
      CEMADEN). Em qualquer situação de risco real, siga os canais oficiais.
    </p>
  )
}
