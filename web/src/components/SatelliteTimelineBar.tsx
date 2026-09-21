import { formatTimeBR } from '../format'
import type { SatelliteTimeline } from '../useSatelliteTimeline'

interface Props {
  timeline: SatelliteTimeline
  /** Real (non-estimated) frame count — drives the "1 quadro · histórico em
   * formação" vs. "N quadros · 1h até a última aquisição" copy. */
  frameCount: number
}

/** Play/pause + scrubber for the satellite IR timeline (Fase 8, ADR-0091) —
 * shared by `Dashboard` (authenticated) and `VisitorView` (public), each
 * feeding it their own `useSatelliteTimeline(...)` instance. */
export function SatelliteTimelineBar({ timeline, frameCount }: Props) {
  const { steps, index, playing, activeStep, currentIndex, toggle, selectIndex, goLive } =
    timeline

  return (
    <div className="map-timeline" aria-label="Linha do tempo meteorológica">
      <button
        type="button"
        className="timeline-play"
        onClick={toggle}
        disabled={steps.length === 0}
        aria-label={
          playing
            ? 'Pausar animação'
            : steps.length === 1
              ? 'Exibir único quadro de satélite disponível'
              : 'Reproduzir última e próxima hora'
        }
        title={
          steps.length === 1
            ? 'Histórico em formação — o próximo ciclo adicionará outro quadro'
            : undefined
        }
      >
        {playing ? '⏸' : '▶'}
      </button>
      <div className="timeline-content">
        <div className="timeline-heading">
          <strong>
            {activeStep?.estimated
              ? `Estimativa +${activeStep.offsetMinutes} min`
              : activeStep
                ? `Observado ${formatTimeBR(activeStep.image.captured_at)}`
                : 'Agora'}
          </strong>
          <span>
            {activeStep?.estimated
              ? 'trajetória linear das células; imagem é a última observação'
              : frameCount === 1
                ? '1 quadro real · histórico em formação'
                : `${frameCount} quadros reais · 1h até a última aquisição`}
          </span>
        </div>
        {steps.length > 0 ? (
          <input
            type="range"
            min={0}
            max={Math.max(0, steps.length - 1)}
            value={index ?? currentIndex}
            onChange={(event) => selectIndex(Number(event.target.value))}
            aria-label="Posição na linha do tempo"
          />
        ) : (
          <span className="timeline-empty">Aguardando quadros de satélite válidos.</span>
        )}
      </div>
      {index != null && (
        <button type="button" className="timeline-live" onClick={goLive}>
          Ao vivo
        </button>
      )}
    </div>
  )
}
