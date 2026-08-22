# Política de segurança

StormPulse é um projeto pessoal em desenvolvimento ativo — o processo abaixo
é deliberadamente simples, não um SLA corporativo.

## Como reportar uma vulnerabilidade

**Canal preferido — Private vulnerability reporting do GitHub** (aba
"Security" → "Report a vulnerability" do repositório): cria uma conversa
privada entre você e os mantenedores, sem expor detalhes de exploração
publicamente em nenhum momento. Isso não está habilitado no repositório
ainda — TODO(owner): habilitar em Settings → Security → "Private
vulnerability reporting" (é uma configuração do próprio repositório, não
requer nenhuma mudança de código; ver
[documentação do GitHub](https://docs.github.com/code-security/security-advisories/guidance-on-reporting-and-writing/privately-reporting-a-security-vulnerability)).

Até lá, ou para o que não se enquadrar no fluxo acima: abra uma
[issue no GitHub](https://github.com/felipeaugusantos/StormPulse/issues)
marcada como segurança, **sem incluir detalhes de exploração publicamente**
se a vulnerabilidade for séria — nesse caso, descreva o impacto em termos
gerais e aguarde contato antes de detalhar os passos de reprodução.

## O que esperar

- Confirmação de recebimento: melhor esforço, sem prazo garantido (projeto
  pessoal, não uma equipe de plantão).
- Correções de vulnerabilidades reais têm prioridade sobre novas
  funcionalidades.
- Dependências são monitoradas automaticamente via
  [Dependabot](.github/dependabot.yml) e `pip-audit` no CI
  (`.github/workflows/ci.yml`).

## Escopo

Cobre o backend (`backend/`), dashboard web (`web/`) e app mobile
(`mobile/`) deste repositório. Não cobre infraestrutura de terceiros usada
em produção (se houver), nem dados meteorológicos de fontes externas
(INMET) — ver [ADR-0006](docs/adr/0006-integracao-real-inmet.md).

## Versões suportadas

Sem versionamento formal ainda (projeto pré-1.0) — apenas a branch principal
recebe correções.
