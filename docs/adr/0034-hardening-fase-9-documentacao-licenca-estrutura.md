# ADR-0034 — Hardening (Fase 9): documentação, licença, estrutura frontend

- **Status:** Aceito
- **Data:** 2026-08-22

## Contexto

Os quatro documentos principais da raiz do repositório (`README.md`,
`ARCHITECTURE.md`, `ROADMAP.md`, `SECURITY.md`) descreviam o projeto como
estando nas **FASE 0/1** (arquitetura/fundação) — na prática, o MVP
ponta-a-ponta está completo desde a FASE 20, mais 7 fases de funcionalidade
adicional (21–27) e 8 fases de um ciclo de hardening técnico em andamento.
Especificamente:

- `README.md` dizia "Este repositório está nas FASE 0/1" e listava só
  saúde/config/Docker como "o que já funciona".
- `ARCHITECTURE.md` marcava com 🔭 (intenção futura) seções inteiras que
  já estavam implementadas há dezenas de fases (auth, locations, storms,
  workers, dashboard web, app mobile).
- `ROADMAP.md` parava na FASE 20 — as fases 21–27 (sinais adicionais,
  push real, talhão, paridade mobile, polígono de talhão) e o ciclo de
  hardening (fases 1–8, ADR-0026 a 0033) não apareciam em lugar nenhum.
- **Confusão real de estrutura**: o repositório tem dois apps React
  distintos — o app na raiz (`src/`, publicado no GitHub Pages) é uma demo
  standalone que consulta o Open-Meteo direto do navegador, sem backend;
  `web/` é o dashboard admin de verdade, que fala com a API FastAPI. Nenhum
  documento explicava essa distinção — alguém lendo só o README concluiria
  que o GitHub Pages publica o produto StormPulse completo, o que é falso.
- `SECURITY.md` só oferecia issues públicas do GitHub como canal de
  reporte, sem mencionar o Private Vulnerability Reporting nativo do
  GitHub (mais apropriado para reportes sensíveis).

## Decisão

- **`README.md`**: seção "Estado atual" reescrita para refletir o estado
  real (MVP completo + ciclo de hardening em andamento), com link pro
  ROADMAP para o histórico fase a fase. Nova seção "Estrutura — dois
  produtos frontend distintos, não confunda" explicando explicitamente o
  app raiz (demo Open-Meteo, GitHub Pages) vs. `web/` (dashboard real).
  Nova seção "⚠️ Limitações" consolidando num único lugar o que antes
  estava espalhado: não substitui alertas oficiais, células aproximadas
  via Marshall–Palmer (não radar real), avisos casados por UF (não
  polígono), satélite como sinal precoce (não confirmação), dados
  `is_mock`/`experimental` explícitos.
- **`ARCHITECTURE.md`**: cabeçalho de status atualizado; diagrama e seção
  de estrutura de diretórios sem os marcadores 🔭 em partes já
  implementadas há muito tempo (auth, locations, storms, alerts,
  notifications, engine, workers, web, mobile); modelo de dados atualizado
  com as entidades reais adicionadas desde a FASE 2 original
  (`PushSubscription`, `ConvectiveWatch`, `SatelliteImage`,
  `LightningStrike`); seção de segurança/observabilidade descreve o que
  está implementado hoje (incluindo os resultados do hardening: rate limit
  atrás de proxy, config por instância, cookie opt-in); modelo de execução
  deixa explícito que produção real (proxy reverso, TLS, domínio) ainda
  **não foi decidida** — é o bloqueio real por trás da Fase 4 parcial do
  hardening (ADR-0029).
- **`ROADMAP.md`**: duas seções novas. "Funcionalidades adicionais (fases
  21–27)" — lista consolidada (sem tabela fase-a-fase individual, porque
  nem toda ADR declara seu próprio número de fase de forma consistente)
  linkando cada ADR correspondente. "Ciclo de hardening técnico (em
  andamento)" — tabela com as 11 fases planejadas, status real de cada uma
  (9 concluídas, Fase 4 marcada explicitamente como parcial/bloqueada,
  10/11 planejadas), e nota de que a
  preparação de infraestrutura de produção ainda não começou.
- **`SECURITY.md`**: adiciona o Private Vulnerability Reporting do GitHub
  como canal preferido, com um `TODO(owner)` explícito — **não foi
  habilitado por esta ADR**, é uma configuração do repositório
  (`Settings → Security`) que só o dono pode ativar; confirmado via `gh
  api repos/.../private-vulnerability-reporting` que está desabilitado
  hoje. O fluxo de issue pública continua documentado como alternativa.
- **Licença**: mantida "A definir" no README, sem nenhuma proposta ou
  escolha implícita — decisão que só o dono do produto pode tomar, per
  instrução explícita do ciclo de hardening.

## Fora de escopo desta fase

- Habilitar o Private Vulnerability Reporting de fato (ação do dono no
  GitHub, não código).
- Escolher uma licença.
- Métricas operacionais, code-splitting do bundle e testes mínimos de
  frontend — Fase 10 do ciclo de hardening.
- Infraestrutura de validação meteorológica formal — Fase 11.

## Consequências

- Alguém lendo o README pela primeira vez agora entende corretamente: (1)
  o estado real do projeto, (2) que o GitHub Pages publica uma demo, não o
  produto, (3) as limitações reais dos dados meteorológicos antes de
  confiar neles.
- Nenhuma mudança de código, modelo ou regra meteorológica — só
  documentação.
