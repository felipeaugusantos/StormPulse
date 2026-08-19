import type { StormAssessment } from '../lib/storm'

interface Props {
  assessment: StormAssessment
}

const ICON: Record<StormAssessment['level'], string> = {
  calm: '🟢',
  watch: '🟡',
  warning: '🟠',
  severe: '🔴',
}

export function StormAlert({ assessment }: Props) {
  const { level, score, title, summary, alerts } = assessment
  return (
    <section className={`storm-alert storm-${level}`} aria-live="polite">
      <div className="storm-head">
        <span className="storm-icon" aria-hidden>{ICON[level]}</span>
        <div>
          <h2 className="storm-title">{title}</h2>
          <p className="storm-summary">{summary}</p>
        </div>
        <div className="storm-score" title="Índice StormPulse (0-100)">
          <span className="storm-score-num">{score}</span>
          <span className="storm-score-label">pulso</span>
        </div>
      </div>

      <div className="storm-meter" role="img" aria-label={`Índice de risco ${score} de 100`}>
        <div className="storm-meter-fill" style={{ width: `${score}%` }} />
      </div>

      <ul className="storm-list">
        {alerts.map((a, i) => (
          <li key={i}>{a}</li>
        ))}
      </ul>
    </section>
  )
}
