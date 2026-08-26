# ADR-0063 — Exportação de relatórios em PDF (item 2 do Radar Competitivo)

- **Status:** Aceito
- **Data:** 2026-08-26

## Contexto

Segundo item da sequência priorizada do Radar Competitivo. O relatório
semanal do talhão (FASE 32, `WeeklyReportOut`) já existe e é mostrado no
dashboard com um botão "Imprimir" que usa `window.print()` + CSS
`@media print` — funcional, mas depende do usuário estar numa sessão de
browser aberta e ainda ter que escolher "Salvar como PDF" na própria caixa
de diálogo de impressão do sistema operacional. Não é algo que dá pra
anexar automaticamente a um e-mail, gerar em lote, ou baixar de um clique
só. Faltava um PDF de verdade, gerado no servidor.

## Decisão

### Um único lugar calcula os números

A lógica que monta o `WeeklyReportOut` (chuva acumulada, dias secos,
alertas e leituras de NDVI do período) estava inteira dentro do handler
HTTP em `app/locations/router.py`. Extraída para
`app/locations/service.py::build_weekly_report` — o endpoint JSON e o
endpoint PDF novo chamam exatamente a mesma função, então nunca podem
divergir nos números que mostram.

### reportlab, não HTML-para-PDF

Cogitado usar algo como WeasyPrint (renderiza HTML/CSS real) para
reaproveitar visualmente o `WeeklyReportModal.tsx` existente, mas isso
precisa de bibliotecas nativas (Pango/Cairo/GDK-Pixbuf) instaladas na
imagem Docker — o projeto já rastreia de perto o tamanho da imagem
(`runtime-base` vs `runtime-satellite`, ver ADR-0056 e o job de
comparação de tamanho no CI). `reportlab` é puro Python, zero dependência
de sistema, então o PDF é montado programaticamente em
`app/locations/pdf.py` (tabela de estatísticas + listas de alertas/NDVI)
— mais verboso que reaproveitar HTML, mas sem custo de imagem. Fica em
`app/locations/`, não em `app/reports/` (que já existe para outra coisa:
o modelo `UserReport` de relatórios crowdsourced, FASE 16, ainda sem
endpoint) — evita misturar dois conceitos sem relação só porque a
palavra "relatório" aparece nos dois.

### Endpoint próprio, não um parâmetro `?format=pdf`

`GET /locations/{id}/agro/weekly-report/pdf` — endpoint HTTP separado do
JSON, porque o tipo de resposta é fundamentalmente diferente
(`application/pdf` vs JSON) e FastAPI não faz negociação de conteúdo por
`response_model` de forma limpa quando os dois formatos têm serialização
totalmente distinta. Mesma autenticação e mesmo escopo (só talhão, só o
dono) que o endpoint JSON — implementado chamando `_get_owned_or_404` +
o mesmo `build_weekly_report` antes de passar o resultado pro renderer.

### Frontend: baixa direto, sem depender do diálogo de impressão

`api.weeklyReportPdf` busca o PDF como `Blob` (nova função `requestBlob`
em `api.ts`, com o mesmo contrato de retry em 401 que `request<T>` já
tinha, mas sem tentar fazer `.json()` do corpo binário). O botão "⬇️
Baixar PDF" no `WeeklyReportModal` cria um Object URL e aciona o download
via um `<a download>` temporário — o botão "🖨️ Imprimir" continua
existindo do lado, para quem só quer visualizar/imprimir sem baixar um
arquivo.

## Verificação

`tests/test_weekly_report_pdf.py` (Postgres/Redis reais): PDF começa com
o magic byte `%PDF`, `Content-Type`/`Content-Disposition` corretos, 404
para local que não é talhão, 404 para talhão de outro usuário, 401 sem
autenticação. Verificado também manualmente: baixado via `curl` (`file`
confirma "PDF document, version 1.4") e via browser real (upload do PDF
gerado confirma o conteúdo — tabela, alertas, NDVI, todos os números
batendo com a versão JSON/tela do mesmo talhão).

## Consequências

- Puramente aditivo — o endpoint JSON e o botão "Imprimir" existentes não
  mudam de comportamento.
- Uma nova dependência (`reportlab`) no backend, pura Python, sem impacto
  de tamanho de imagem Docker relevante.
- O PDF tem um layout mais simples que a tela (texto corrido, sem os
  ícones/cores do dashboard) — aceitável para o caso de uso (anexar a um
  relatório, mostrar a um agrônomo/banco), não uma cópia pixel-a-pixel da
  UI.
