# ADR-0090 — Fase 6: Caderno de Campo (offline-first)

- **Status:** Aceito
- **Data:** 2026-09-07

## Contexto

O roadmap original desta fase ("Fase 6 — Registro de execução da ação")
era um recorte pequeno: só ligar uma `RecommendedAction` (Fase 5,
ADR-0089) a um status de execução. O usuário substituiu esse escopo pelo
de uma especificação mais ampla, tratada como a Fase 6 efetiva: um
caderno de campo completo — ocorrências, inspeções, fotos, tarefas,
responsáveis, prazos, linha do tempo do talhão — com funcionamento
offline obrigatório no mobile (fila local de sincronização, resolução
seguro de conflitos, fotos privadas). O rascunho original foi preservado
no roadmap como "Fase 6-A", não descartado.

Nada disso existia: não havia nenhum armazenamento de objetos no projeto
(nenhum bucket S3/MinIO, nenhuma tabela de blob), `UserReport` era um
modelo morto sem nenhum endpoint, e o mobile não tinha nenhuma
infraestrutura de persistência local nem de fila de sincronização.

## Decisões

**MinIO local, novo serviço Docker, via `boto3` (já dependência do
projeto para SES).** Escolhido entre MinIO/S3 real/blob em Postgres —
S3 real exigiria uma conta AWS e credenciais de produção fora do escopo
desta fase; blob em Postgres não escala para fotos e mistura dado
binário grande na mesma base transacional. MinIO fala o protocolo S3,
então nenhuma SDK nova é necessária — `boto3.client("s3", endpoint_url=...)`
apontado para o MinIO. Fotos nunca são públicas: todo acesso passa por
`generate_presigned_url` de curta duração (`FIELDNOTES_STORAGE_PRESIGNED_URL_EXPIRY_SECONDS`,
padrão 600s) — nunca uma URL direta/pública do objeto.

**Identidade offline-first via UUID gerado no cliente.** Toda
`FieldOccurrence`/`Inspection`/`Task` aceita um `id` fornecido pelo
chamador na criação (o mixin `UUIDPrimaryKeyMixin` só gera automaticamente
quando não fornecido). O app mobile gera o UUID no aparelho, ainda
offline, e o mesmo `id` sobrevive à fila local até a sincronização —
tornando um replay/retry de uma criação enfileirada naturalmente
idempotente, sem precisar de uma tabela de idempotência separada.

**Toda criação é idempotente por construção.** Cada endpoint de criação
verifica `existing = await session.get(Model, data.id)` antes de
inserir; se já existe, retorna o registro existente em vez de tentar
inserir de novo. Isso é o que garante o critério de aceite "sincronização
acontece ao recuperar a conexão" sem duplicar registros quando a fila
local reenvia uma operação que já havia sido aplicada (rede caiu depois
do servidor confirmar, mas antes do mobile marcar como sincronizada).

**Concorrência otimista via `version`/`base_version`/409 — nunca
sobrescrita silenciosa.** Toda linha mutável do caderno de campo tem um
`version: int` (começa em 1, incrementado a cada update). Todo schema de
update exige `base_version` (a versão que o cliente viu por último); o
router compara e responde `409 Conflict` em caso de divergência, nunca
aplica a mudança por cima. Atende diretamente o critério de aceite
"conflitos não sobrescrevem informações silenciosamente" — a resolução
do conflito (reaplicar sobre o estado atual, descartar, mesclar
manualmente) fica a critério de quem chama, o backend só garante que o
conflito nunca passa despercebido.

**Sem endpoint de "sync em lote" — reutiliza os endpoints REST comuns,
replayed em ordem pela fila mobile.** Considerada e descartada uma rota
tipo `POST /field-notebook/sync` que aceitasse um lote de operações
pendentes de uma vez. Optado por manter os mesmos endpoints REST
simples (`POST /locations/{id}/field-occurrences`, etc.) e deixar o
mobile reproduzir a fila local operação por operação, em ordem — mais
simples, sem uma superfície de API paralela para manter, e cada operação
já é idempotente e verificável isoladamente (sem uma transação "tudo ou
nada" implícita de um lote).

**Mobile: offline completo. Web: sempre online, sem fila.** A
especificação pede "funcionamento offline no mobile" — não menciona o
web. O web usa os mesmos endpoints diretamente, sem `expo-sqlite`/fila
local; decisão consciente de não replicar a complexidade offline onde
não foi pedida (o navegador desktop tem conectividade mais confiável que
um dispositivo de campo).

**Compressão de fotos: só no mobile (`expo-image-manipulator`,
resize 1600px + compressão 0.6 JPEG antes do upload).** O web não
comprime antes de enviar. Decisão implícita, não uma regra formal —
justificada por upload no mobile tipicamente ser em rede móvel/3G-4G no
campo, enquanto o desktop web tem banda mais folgada; registrada aqui
para que uma eventual reclamação de tamanho de upload no web tenha
contexto (a resposta seria adicionar compressão client-side ao web
também, não uma limitação de arquitetura).

**Sincronização automática só na transição desconectado→conectado.**
`startAutoSync` (via `@react-native-community/netinfo`) dispara o flush
da fila apenas quando o estado runtime muda de "sem rede" para "com
rede" — não no evento inicial que o NetInfo sempre dispara ao assinar,
o que causaria uma tentativa de flush vazia (fila ainda vazia) em todo
cold start.

**CI roda MinIO via `docker run` direto, não via `services:` do GitHub
Actions.** O mecanismo `services:` do Actions não permite sobrescrever o
comando de entrada do container — a imagem `minio/minio` sem `server
/data` só imprime o help e sai. Contornado com um passo explícito
`docker run -d ... minio/minio:... server /data` mais um loop de
healthcheck via curl antes dos testes.

## Consequências

- 4 tabelas novas (`field_occurrences`, `inspections`, `photos`, `tasks`),
  todas tenant-scoped com RLS desde a migração.
- Nova dependência de runtime: `python-multipart` (primeiro endpoint do
  projeto a aceitar `UploadFile`/multipart).
- Novo serviço Docker (`minio`) em dev e produção — em produção,
  `FIELDNOTES_STORAGE_ACCESS_KEY`/`FIELDNOTES_STORAGE_SECRET_KEY` devem
  ser trocados dos valores padrão de desenvolvimento (a validação de
  `Settings` já recusa o segredo padrão em `environment=production`,
  mesmo padrão das demais chaves — JWT, senha do Postgres, chaves de
  criptografia de campo).
- Primeira infraestrutura de persistência local do mobile (`expo-sqlite`)
  — precedente para qualquer futura funcionalidade offline-first no app.
- Dois padrões já vistos nas Fases 3/3-A/5 reapareceram aqui e foram
  corrigidos da mesma forma: o reset do GUC de tenant do RLS após
  `commit()` (precisa reaplicar `set_tenant_context` antes de qualquer
  `refresh()` seguinte) e o fato de o SQLAlchemy persistir o **nome** do
  membro do enum Python (`"OPEN"`), não o `.value` (`"open"`) — o tipo
  enum do Postgres precisa ser criado com os nomes em maiúsculas.
