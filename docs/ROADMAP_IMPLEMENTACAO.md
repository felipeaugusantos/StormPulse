# Roadmap de implementação — Ciclo de Evolução Agroclimática

- **Criado em:** 2026-09-05, Fase 0 (diagnóstico), a partir do commit
  `8b60dee` — ver [BASELINE_TECNICA.md](BASELINE_TECNICA.md) para o
  levantamento completo que fundamenta este plano.
- **Numeração:** este documento usa "Fase 1, 2, 3…" **próprias**, distintas
  das FASES 1–34 (MVP, ver `ROADMAP.md`) e das fases do "ciclo de
  hardening técnico" (1–11, também em `ROADMAP.md`) já concluídas. Pra
  evitar ambiguidade, sempre que citado fora deste arquivo, um item daqui
  deve ser referido como "Ciclo Agroclimático — Fase N".

## Objetivo do ciclo

Evoluir o StormPulse de "monitoramento de tempestade + sinais agro
avulsos" para uma plataforma que responda, por talhão, de forma
verificável e auditável:

> **Qual risco climático ameaça meus talhões, quando poderá chegar, qual
> ação é recomendada e como registrar que essa ação foi executada?**

As quatro perguntas mapeiam diretamente pra quatro capacidades — as três
primeiras já existem parcial e fragmentadamente no sistema hoje; a quarta
**não existe ainda em nenhuma forma**:

| Pergunta | Estado hoje |
|---|---|
| Qual risco ameaça meus talhões? | Existe, mas **espalhado** em painéis separados por tipo de sinal (tempestade, geada, seca, ZARC, NDVI, desmatamento, umidade de solo) — sem uma visão consolidada por talhão |
| Quando poderá chegar? | Existe por sinal (ETA de célula, dias de geada prevista, janela ZARC) — sem um conceito unificado de "janela de risco" |
| Qual ação é recomendada? | **Não existe.** O sistema mostra números e classificações, nunca uma recomendação de ação |
| Como registrar que foi executada? | **Não existe.** Não há nenhum modelo de "ação tomada" — `UserReport` existe na arquitetura mas está documentado como "sem UI" |

## Princípios que valem para **todas** as fases abaixo (não repetidos em
cada uma)

- Nenhuma fase decide severidade meteorológica por IA generativa — motor
  determinístico decide, IA (quando usada) só resume/explica um resultado
  já calculado (regra inviolável do projeto, ADR-0005/0060).
- Nenhum dado estimado é apresentado como observação real — todo novo
  campo carrega `is_mock`/`experimental`/proveniência quando aplicável.
- Toda mudança de schema tem migração Alembic com upgrade **e** downgrade,
  compatível com dados existentes, com índices/constraints adequados e
  teste cobrindo o caminho novo.
- Toda funcionalidade nova considera, desde o desenho: isolamento
  multitenant + RLS (política criada na mesma migração que cria a
  tabela, nunca depois), LGPD (dado pessoal com o mesmo tratamento de
  criptografia/retenção já usado em `app/core/crypto.py`), autorização
  por função (RBAC existente), auditoria (mesmo padrão de
  `app/admin/` — `AuditLogEntry`), rate limit onde fizer sentido, web
  **e** mobile, acessibilidade, observabilidade (métrica OTel nova
  quando a feature tiver um ciclo/pipeline próprio).
- Se uma integração depender de contrato/licença/credencial indisponível
  (ex.: uma fonte agronômica paga), a fase entrega a interface de
  provider + um mock explícito + documentação do que falta configurar —
  nunca dado inventado.
- Cada fase termina com lint + typecheck + testes + build rodando limpos,
  e um relatório (arquivos alterados, decisões, migrações, testes,
  riscos, passos manuais) antes de pedir autorização pra próxima.

---

## Fase 1 — Segurança e Qualidade ✅ concluída (2026-09-05)

Escopo definido diretamente pelo dono do produto (substitui o rascunho
original desta seção, renumerado abaixo como **Fase 1-A**): dependências
vulneráveis, CORS/cookies/tokens/uploads/logs/rate limit, testes dos
fluxos críticos (cadastro, login, verificação de e-mail, recuperação de
senha, renovação de sessão, cadastro de fazenda, cadastro/desenho de
talhão, geração de relatório), E2E web (Playwright), teste de contrato
front↔API, gate de vulnerabilidade no CI. Decisões e achados detalhados
em [ADR-0081](adr/0081-fase1-seguranca-e-qualidade.md). Commits:
`7eb6836`, `6131914`, `9c6163a`, `6322105` (mais `12e06e1`, incidente de
deploy resolvido antes de iniciar a fase).

## Fase 1-A — Fechar dívida técnica P0 (fundação antes de crescer escopo)

**Por quê:** expandir o modelo de dados e adicionar um módulo novo
(ação/execução, Fase 6) sobre uma base onde RLS não é testada e backup
não sai da instância é multiplicar o raio de um incidente futuro, não só
adicionar risco novo. Ainda não iniciada — aguardando autorização.

- Corrigir `app/core/rls.py::_TENANT_SCOPED_TABLES` (incluir
  `ndvi_images`, `deforestation_checks`, conferir se há outras) e mudar
  o CI pra rodar os testes de integração com um role **sem** `BYPASSRLS`
  e diferente do role de migração — hoje ambos são o mesmo (`stormpulse`),
  então RLS nunca bloqueia nada em teste.
- Documentar e configurar `BACKUP_S3_BUCKET` (o script já suporta) — ou
  decidir explicitamente não fazer isso agora e registrar o risco aceito
  em ADR.
- Monitoramento externo mínimo: um `on: schedule` no GitHub Actions
  batendo em `/health` dos 3 hostnames, alertando por e-mail (SES já
  configurado) se cair.
- CI: publicar a mesma imagem que foi escaneada/smoke-testada (hoje builda
  duas vezes, em dois jobs separados, com cache diferente).
- Sincronizar `README.md`/`ARCHITECTURE.md`/`ROADMAP.md` com a realidade
  (RLS implementada, produção real existe, endpoints atuais, entidades
  novas no modelo de dados) — sem isso, quem ler a documentação antes de
  mexer no código parte de premissas falsas.

## Fase 2 — Comparação e Validação de Previsões ✅ concluída (2026-09-05)

Escopo definido diretamente pelo dono do produto (substitui o rascunho
original desta seção, renumerado abaixo como **Fase 2-A**): comparar
ECMWF/GFS/ICON (via Open-Meteo, sem credencial nova) contra observação
real, calculando MAE de temperatura, viés/erro de precipitação, erro de
vento, taxa de acerto de chuva e Brier Score, por modelo/localidade/
horizonte, sem recomendar um modelo sem amostra mínima. INMET/CPTEC não
entram na comparação numérica (não dão número de previsão, só texto).
Decisões e achados detalhados em
[ADR-0082](adr/0082-comparacao-validacao-previsoes.md).

## Fase 2-A — Fechar P1 (confiabilidade)

- Dedup de descargas no pipeline de raios (chave estável por
  posição+janela de tempo, não re-inserir o mesmo raio a cada ciclo).
- Testes de componente web (`@testing-library/react` + `@testing-library/jest-dom`)
  cobrindo pelo menos `useAgroEntries` (o hook que já teve um bug real de
  staleness corrigido nesta sessão) e os painéis agro. ✅ Parcialmente feito
  na Fase 1 (primeiro teste de componente do projeto, `WeeklyReportModal`;
  `useAgroEntries` continua sem teste dedicado).
- ✅ Geração de tipos TypeScript a partir do OpenAPI do backend — feito na
  Fase 1 (`openapi-typescript`, checado no CI).
- `workflow_dispatch` de rollback (SHA anterior já fica disponível via
  `PREV_*_IMAGE` no `deploy.sh`) em vez de procedimento manual por SSH.
- Ação do dono do produto, não bloqueante pro código: token INMET
  (e-mail já enviado) e chave REDEMET.

## Fase 3 — Visão consolidada de risco por talhão

Hoje cada sinal (tempestade, geada, seca, ZARC, NDVI, desmatamento,
umidade de solo) tem seu próprio painel/endpoint, sem lugar único que
responda "qual risco ameaça ESTE talhão agora". Esta fase:

- Novo endpoint `GET /locations/{id}/risk-digest` (ou nome equivalente)
  que agrega os sinais já calculados (nenhum recálculo — só leitura dos
  resultados já materializados de cada pipeline) num único payload
  tipado, com proveniência de cada sinal preservada (`is_mock`/
  `experimental`/fonte/`observed_at` de cada um, nunca colapsados numa
  média sem sentido).
- Web e mobile ganham uma tela/card "Risco consolidado" por talhão,
  reaproveitando os componentes de exibição já existentes por sinal
  (não recriar).
- Sem migração de schema necessária nesta fase — é uma camada de leitura
  sobre dados já persistidos.

## Fase 4 — Janela de risco unificada ("quando pode chegar")

- Consolidar os diferentes conceitos de "quando" que já existem (ETA de
  célula em minutos, dias de geada prevista, janela ZARC em dias) num
  formato de exibição comum ("daqui a X horas", "nos próximos N dias"),
  sem fingir uma precisão que a fonte não tem — cada sinal mantém sua
  própria unidade de tempo internamente, só a apresentação é unificada.
- Avaliar, com o dono do produto, se faz sentido um "próximo evento"
  cross-sinal (ex.: "o risco mais iminente neste talhão hoje é X, chega
  em Y") — decisão de produto, não só engenharia; registrar em ADR antes
  de implementar.

## Fase 5 — Motor de recomendação de ação (determinístico)

**Não existe hoje.** Núcleo novo, e o mais sensível desta fase — precisa
de validação de domínio agronômico, não só código.

- Catálogo de regras determinísticas risco→ação recomendada (ex.: "chuva
  forte prevista em ≤2h + colheita pendente → recomendar antecipar/adiar
  colheita"; "geada forte prevista + cultura sensível → recomendar
  irrigação por aspersão ou cobertura"), documentado e versionado como
  as regras do `StormRiskEngine`/`AlertEngine` já são — nunca uma LLM
  decidindo a ação, só (opcionalmente) redigindo o texto de uma
  recomendação já decidida pela regra.
- Escopo inicial deliberadamente pequeno (2–3 pares risco→ação bem
  validados) em vez de um catálogo grande e não revisado — mesma
  filosofia YAGNI já usada no resto do projeto.
- Novo modelo `RecommendedAction` (tenant-scoped, RLS desde a migração
  que cria a tabela), ligado ao `Alert`/sinal que a originou.
- Exposto em `GET /locations/{id}/recommended-actions` (ou embutido no
  `risk-digest` da Fase 3) — web e mobile.

## Fase 6 — Registro de execução da ação (auditoria)

**O núcleo que fecha a pergunta do produto.** Não existe nenhuma forma
disso hoje — `UserReport` é o mais próximo, mas está descrito como
"arquitetura preparada, ainda sem UI".

- Novo modelo (`ActionExecution` ou reaproveitando/evoluindo
  `UserReport` — decidir na fase, comparando os dois caminhos) com:
  status (recomendada/executada/ignorada/expirada), quem marcou, quando,
  observação livre opcional, ligação com a `RecommendedAction`/`Alert`
  de origem. Tenant-scoped, RLS, auditoria (mesmo padrão de
  `AuditLogEntry`).
- UI web **e** mobile pra marcar uma ação como feita — acessível (rótulos
  claros, não só ícone/cor), simples (não um formulário longo).
- Isso também alimenta, no futuro, o backtesting já existente
  (ADR-0058) — não só "o alerta acertou", mas "a ação recomendada
  ajudou" — fica registrado aqui como direção futura, não escopo desta
  fase.

## Fase 7 — Colaboração multi-tenant supervisionada (consultores,
   cooperativas, grupos)

Hoje um tenant é, na prática, uma conta pessoal ou uma fazenda — não há
um papel que veja talhões de **vários tenants diferentes** (um consultor
atendendo produtores distintos, uma cooperativa acompanhando associados).
O painel de operador de plataforma (`app/admin/`) já faz algo parecido,
mas é para operação da própria plataforma, não para um usuário de
negócio real ver dados de terceiros com consentimento.

Esta é a fase de **maior risco arquitetural e de LGPD** do ciclo —
precisa de decisão explícita (ADR) sobre modelo de consentimento antes de
qualquer código: quem concede acesso, a que granularidade (talhão? fazenda
inteira?), por quanto tempo, como é revogado, e como isso interage com
RLS (hoje a política é "tenant = tenant", um modelo de acesso
compartilhado é uma mudança de premissa, não um ajuste incremental).
**Não iniciar sem alinhamento explícito do dono do produto sobre este
modelo.**

---

## Ordem recomendada e dependências

```
Fase 1 ✅ ──► Fase 1-A (P0) ──► Fase 2-A (P1) ──► Fase 3 (visão consolidada)
                                        │
                                        ▼
                              Fase 4 (janela unificada)
                                        │
                                        ▼
                    Fase 5 (recomendação) ──► Fase 6 (registro de execução)
                                        │
                                        ▼
                         Fase 7 (colaboração multi-tenant, isolada,
                                 pode rodar em paralelo a qualquer
                                 momento depois da Fase 1)

Fase 2 (Comparação e Validação de Previsões) ✅ já concluída — independente
desta cadeia (não bloqueia nem é bloqueada por Fase 2-A/3-7).
```

Fases 1-A e 2-A não são estritamente bloqueantes uma da outra internamente,
mas ambas devem vir antes da Fase 3 em diante — não faz sentido construir
uma visão consolidada de risco sobre uma base cujo isolamento multitenant
não é testado.

## Como este documento deve ser usado

Cada fase só começa mediante autorização explícita, uma de cada vez —
nunca várias juntas. Ao final de cada fase, o relatório de entrega
(arquivos, decisões, migrações, testes, riscos, passos manuais) atualiza
este documento marcando a fase como concluída, com o commit/PR
correspondente, antes de pedir autorização para a próxima.
