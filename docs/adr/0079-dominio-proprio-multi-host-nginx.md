# ADR-0079 — Domínio próprio (Enzova): 2 hosts, 1 container, 1 certificado

- **Status:** Aceito
- **Data:** 2026-09-01

## Contexto

A ADR-0037 registrou explicitamente "sem domínio próprio por enquanto" e a
ADR-0039 resolveu isso com [nip.io](https://nip.io) — um domínio
provisório que resolve pro próprio IP do EC2, suficiente pra emitir um
certificado Let's Encrypt real sem custo. O sistema rodava inteiro sob
`https://52-206-89-133.nip.io`.

A empresa (Enzova) comprou o domínio real `enzova.com.br` na Hostinger.
Pedido do dono do produto: mover o StormPulse pra um subdomínio próprio, e
criar uma página institucional/portfólio simples no domínio raiz —
"mostrar que somos uma empresa que trabalha com desenvolvimento de
sistemas para todos os tipos de público", com o StormPulse como único item
do portfólio por enquanto.

## Decisão

### Dois hosts, um único container `web`, sem novo serviço Docker

`stormpulse.enzova.com.br` (SPA + proxy `/api/`, o mesmo bloco que já
existia) e `enzova.com.br`/`www.enzova.com.br` (site institucional,
puramente estático, sem proxy nenhum) são servidos pelo mesmo container
nginx via dois `server{}` blocks diferenciados por `server_name`, em vez
de subir um segundo serviço/container só pra uma página sem lógica
nenhuma. O site institucional é buildado dentro da mesma imagem
`stormpulse-web` (`web/enzova-site/` → `/usr/share/nginx/enzova-site` no
`web/Dockerfile`), reaproveitando o pipeline de build/deploy que já
existe — nenhuma mudança de CI/CD foi necessária.

### Um certificado multi-SAN, não um por host

`certbot -d stormpulse.enzova.com.br -d enzova.com.br -d
www.enzova.com.br` — um único certificado cobrindo os 3 hostnames, em vez
de gerenciar certificados/renovações separadas. `infra/renew-tls.sh` não
precisou mudar (já era agnóstico a quantos SANs o certificado ativo tem).
`infra/setup-tls.sh` passou a aceitar múltiplos domínios (`<primário>
<email> [extras...]`) — o primeiro continua sendo obrigatório e é o nome
usado pelo certbot pro diretório do certificado; o comportamento antigo
(um domínio só, ex. nip.io) continua funcionando sem quebrar, com o bloco
institucional recebendo um `server_name` reservado (`enzova-site.invalid`,
TLD `.invalid` de RFC 2606) que nunca bate com tráfego real — nginx não
aceita `server_name` vazio.

### Verificação de sintaxe antes de ativar em produção

`infra/setup-tls.sh` agora roda `docker compose ... exec web nginx -t`
contra a config HTTPS nova antes de reiniciar o `web` — se falhar, reverte
pra config HTTP-only e aborta, em vez de arriscar um erro de sintaxe no
bloco institucional (novo, menos testado) derrubar
`stormpulse.enzova.com.br`, que vive no mesmo arquivo. Mesma filosofia de
segurança que `infra/deploy.sh` já aplica a outras etapas de deploy
(ADR-0040/0043/0044).

### CSP separada por host

O bloco institucional usa uma CSP mais restrita que a da SPA
(`default-src 'self'` sem hCaptcha/Google Sign-In/tiles de mapa — nada
disso existe na página institucional) — cada host tem exatamente a CSP
que o conteúdo dele precisa, não uma união das duas.

### Identidade visual reaproveitada, não recriada

`brand/enzova/` já tinha um kit de marca completo (paleta Navy/Electric/
Graphite/Cloud/Slate, tipografia Manrope+Inter, logos em SVG) de um
trabalho anterior — o site institucional usa esses assets diretamente
(`web/enzova-site/assets/`), sem redesenhar nada.

## Consequências

- **Ainda depende de 3 ações manuales do usuário, fora do meu alcance**:
  criar os registros DNS na Hostinger (`A` pros 3 hosts), rodar o
  `setup-tls.sh` atualizado via SSH depois que o DNS propagar, e ajustar
  `CORS_ALLOWED_ORIGINS` no `.env` do servidor. Até isso acontecer, o
  nip.io continua sendo o único jeito de acessar o sistema em produção —
  nada nesta mudança de código altera o nginx ativo sozinho.
- ADR-0037 e ADR-0039 ficam como registro histórico, não apagadas —
  documentam por que o nip.io foi a escolha certa *na época* (sem domínio
  ainda), mesmo agora superadas.
- O nip.io não precisa ser desligado — pode continuar servindo como
  fallback de acesso durante a transição; simplesmente para de ser
  referenciado pela config ativa assim que o `setup-tls.sh` novo rodar.
