# ADR-0085 — Linha do tempo meteorológica no mapa

- **Status:** Aceito
- **Data:** 2026-09-05
- **Contexto:** o operador precisa reproduzir a última hora observada e visualizar a possível evolução na próxima hora.

## Decisão

O pipeline mantém um buffer móvel de duas horas dos PNGs infravermelhos reais. A API pública lista os quadros válidos da janela solicitada e entrega cada PNG por identificador imutável. O mapa reproduz os quadros da última hora em ordem cronológica.

Depois do último quadro observado, a interface oferece passos de dez minutos até `+60 min` somente quando alguma célula possui velocidade e direção medidas. Nesses passos, a posição é uma interpolação linear até a projeção de uma hora já calculada pelo backend; o raster permanece sendo a última imagem observada e a tela o identifica como estimativa.

## Consequências

- Não existe imagem de satélite futura fabricada.
- Sem histórico válido, a reprodução passada fica indisponível.
- Sem trajetória medida, não são criados passos futuros.
- O armazenamento permanece limitado: quadros com mais de duas horas são removidos e uma aquisição repetida é atualizada, não duplicada.
- Imediatamente após o primeiro deploy haverá poucos quadros; a janela completa se forma conforme os ciclos reais do pipeline forem executados.
