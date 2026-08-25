interface Props {
  onEnter: () => void
  onVisitor: () => void
}

/** Institutional page shown before login (FASE 30) — explains what
 * StormPulse actually does, grounded in what's real and shipped (README's
 * own description), not aspirational copy. Purely presentational: no data
 * fetching, no auth state. */
export function LandingPage({ onEnter, onVisitor }: Props) {
  return (
    <div className="landing">
      <header className="landing-hero">
        <div className="brand">
          <span aria-hidden>⚡</span>
          <span>
            Storm<strong>Pulse</strong>
          </span>
        </div>
        <span className="landing-eyebrow">Monitoramento em tempo real · grátis pra começar</span>
        <h1>Monitoramento meteorológico que avisa antes de virar problema</h1>
        <p className="landing-lede">
          Transformamos dados de radar, satélite e estações em alertas simples e diretos
          por local — sua casa, seu trabalho, sua fazenda — em vez de mais um app de
          previsão genérica pra você interpretar sozinho.
        </p>
        <div className="landing-cta">
          <button className="btn" type="button" onClick={onEnter}>
            Criar conta grátis
          </button>
          <button className="btn ghost" type="button" onClick={onVisitor}>
            Ver sem login
          </button>
        </div>
      </header>

      <section className="landing-modules">
        <div className="landing-module-card landing-module-card--storm">
          <span className="landing-module-icon" aria-hidden>
            ⛈️
          </span>
          <h2>Tempestade</h2>
          <p>
            Chuva forte, granizo, raios, vento e acompanhamento de células de tempestade —
            alertas acionáveis por local monitorado, não só um número de previsão.
          </p>
          <ul>
            <li>Alertas por chuva forte, granizo, raios e vento</li>
            <li>Rastreamento de células de tempestade em tempo real</li>
            <li>Observação por satélite e detecção de raios</li>
            <li>Três fontes meteorológicas em cadeia de redundância</li>
          </ul>
        </div>

        <div className="landing-module-card landing-module-card--agro">
          <span className="landing-module-icon" aria-hidden>
            🌾
          </span>
          <h2>Agro</h2>
          <p>
            Sinais agronômicos por talhão — do risco de geada ao vigor da vegetação vistos
            do espaço.
          </p>
          <ul>
            <li>Risco de geada e sequência de dias sem chuva</li>
            <li>Balanço hídrico, VPD e risco de doença fúngica</li>
            <li>Janela de pulverização e trafegabilidade do solo</li>
            <li>NDVI por talhão via satélite (Sentinel-2)</li>
          </ul>
        </div>
      </section>

      <section className="landing-note">
        <span className="landing-note-icon" aria-hidden>
          ✓
        </span>
        <p>
          A classificação meteorológica é determinística — baseada em modelos e regras
          específicas, nunca inventada por IA generativa.
        </p>
      </section>

      <footer className="landing-footer">
        <button className="link-btn" type="button" onClick={onEnter}>
          Já tem conta? Entrar
        </button>
        <div className="enzova-credit">
          <img src="/enzova-icon.svg" alt="" width={18} height={18} aria-hidden />
          <span>
            by <strong>Enzova</strong>
          </span>
        </div>
      </footer>
    </div>
  )
}
