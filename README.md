# Tino.IA 🐙

**Assistente financeiro pessoal via WhatsApp.** Você manda "uber 27" e ele entende, categoriza e registra. Sem app, sem planilha, sem formulário — só a conversa.

```
Você:  almoço 32 no pix
Tino:  ✅ Gasto registrado! (#184)
       📌 Almoço
       💵 R$ 32.00
       🏷️ Alimentação
       💳 Pix

Você:  meta alimentação 300
Tino:  🎯 Meta criada!
       Alimentação: R$ 300.00/mês

Você:  ifood 45
Tino:  ✅ Gasto registrado! (#185)
       📌 Ifood
       💵 R$ 45.00
       🏷️ Alimentação
       💳 não informado

       ⚠️ Você usou 87% do limite de Alimentação (R$ 261.68/R$ 300.00)
```

## Funcionalidades

**Registro** — gastos e receitas em linguagem natural, com categorização automática e detecção da forma de pagamento.

**Relatórios** — por período (hoje, semana, mês), por forma de pagamento, saldo do período (receitas menos gastos) e comparativo entre o mês atual e o anterior, com variação por categoria.

**Metas** — limite mensal por categoria, com alerta automático ao atingir 80% e 100%. O aviso dispara no momento do registro do gasto, não só no relatório.

**Lembretes** — contas fixas com dia de vencimento, sinalizando o que vence hoje ou nos próximos três dias.

**Correções** — remover o último lançamento, remover por descrição ou por categoria, e consultar o histórico recente.

**Boas-vindas automáticas** — quando uma pessoa envia a primeira mensagem, o Tino se apresenta e mostra os comandos úteis com exemplos de uso. Cada número de WhatsApp é registrado como usuário, com contagem de mensagens e data de última atividade (base pronta para planos pagos no futuro).

São **16 intenções** distintas reconhecidas a partir de texto livre.

## Como funciona a interpretação

O Tino é um **agente conversacional**: a IA responde com independência, não com respostas prontas.

- **Agente com ferramentas** — o modelo (MiMo-V2.5 via gateway OpenCode Go) recebe a mensagem com o histórico da conversa e decide sozinho: conversar naturalmente (dicas, insights, papo) ou chamar ferramentas que consultam os **dados reais** do usuário (`relatorio`, `saldo`, `comparativo`, `registrar_gasto`, `definir_meta`, `ver_lembretes`...). Ele mesmo monta a resposta, incluindo observações personalizadas.
- **Memória** — as últimas 10 mensagens de cada usuário entram no contexto, então o agente mantém o assunto e retoma conversas.
- **Confirmação antes de remover** — antes de apagar qualquer gasto ou lembrete, o agente pergunta e aguarda o "sim".
- **Regras locais (fallback)** — motor de regex em Python que reconhece as 16 intenções sem custo. Ativa automaticamente se a IA falhar ou se nenhuma chave estiver configurada.

## Arquitetura

```
flowchart LR
    A["Usuário<br/>WhatsApp"] -->|mensagem| B["Evolution API<br/>(Docker)"]
    B -->|"POST /webhook (JSON)"| C["Tino.IA<br/>FastAPI (Docker)"]
    C -->|interpreta| D["Claude API<br/>(opcional)"]
    D -->|"JSON estruturado"| C
    C -->|"psycopg2"| E[("PostgreSQL<br/>(Docker)")]
    E -->|dados| C
    C -->|"POST /message/sendText"| B
    B -->|resposta| A
```

O fluxo de uma mensagem:

1. **Evolution API** recebe a mensagem no WhatsApp e faz um `POST` no endpoint `/webhook` com o payload JSON do evento `messages.upsert` (texto em `data.message.conversation` / `extendedTextMessage`, remetente em `data.key.remoteJid`).
2. O **agente** monta o contexto (system prompt + últimas 10 mensagens do usuário) e chama a IA. Se o modelo pedir uma ferramenta, ela é executada (consultando ou gravando no banco) e o resultado volta para a IA, que monta a resposta final.
3. O **banco** PostgreSQL é acessado via `psycopg2` (pool de conexões), com filtros por telefone para isolar os dados de cada usuário.
4. A resposta é enviada de volta pelo **Evolution API** via `POST /message/sendText/{instancia}`.

O telefone do remetente funciona como chave de particionamento: toda consulta filtra por `telefone`, então múltiplos usuários compartilham as mesmas tabelas sem enxergar os dados uns dos outros. A tabela `usuarios` registra cada número na primeira mensagem e mede a atividade (base para cobrança futura).

## Stack

| Camada | Tecnologia |
|--------|------------|
| API | FastAPI + Uvicorn |
| Agente | MiMo-V2.5 via gateway OpenCode Go (function calling) + fallback por regras |
| Banco de dados | PostgreSQL 16 (Docker) |
| Mensageria | Evolution API (WhatsApp) via Docker |
| Cliente HTTP | httpx |
| Orquestração | Docker Compose |

## Rodando localmente

**Pré-requisitos:** Docker e Docker Compose.

```bash
git clone https://github.com/enzostana/tino-ai.git
cd tino-ai

cp .env.example .env
# Preencha .env (por enquanto apenas EVOLUTION_INSTANCE e EVOLUTION_API_KEY
# são necessários; ANTHROPIC_API_KEY é opcional e POSTGRES_PASSWORD pode ser trocada)
```

Subindo a stack (banco + Evolution API + app):

```bash
docker compose up -d --build
```

Verifique a saúde:

```bash
curl http://localhost:8000/          # Tino.IA rodando! 🐙
curl http://localhost:8081/          # Evolution API v2
```

### Pareando o WhatsApp

1. Acesse o gerenciador da Evolution API em `http://localhost:8081/manager`.
2. Crie uma instância chamada **tino** (integração `WHATSAPP-BAILEYS`).
3. Escaneie o QR Code com o WhatsApp do seu celular (*WhatsApp > Aparelhos conectados*).
4. Configure o webhook da instância para o evento `MESSAGES_UPSERT` apontando para `http://app:8000/webhook` (o app e a Evolution API se comunicam pela rede interna do Docker).

Alternativa via API:

```bash
# Criar instância
curl -X POST http://localhost:8081/instance/create \
  -H "apikey: SEU_TOKEN" -H "Content-Type: application/json" \
  -d '{"instanceName":"tino","integration":"WHATSAPP-BAILEYS","qrcode":true}'

# Configurar webhook
curl -X POST http://localhost:8081/webhook/set/tino \
  -H "apikey: SEU_TOKEN" -H "Content-Type: application/json" \
  -d '{"webhook":{"enabled":true,"url":"http://app:8000/webhook","events":["MESSAGES_UPSERT"],"byEvents":false,"headers":{"x-tino-token":"SEU_WEBHOOK_TOKEN"}}}'
```

Pronto: mande "ajuda" para o seu próprio número e comece a registrar gastos.

### Testando sem WhatsApp

O endpoint `/webhook` aceita o mesmo payload que a Evolution API envia:

```bash
curl -X POST http://localhost:8000/webhook -H "Content-Type: application/json" -d '{
  "event": "messages.upsert",
  "instance": "tino",
  "data": {
    "key": {"remoteJid": "5511999999999@s.whatsapp.net", "fromMe": false},
    "message": {"conversation": "uber 27"}
  }
}'
```

> Se `WEBHOOK_TOKEN` estiver configurado, inclua o header `x-tino-token`.

## Variáveis de ambiente

| Variável | Obrigatória | Descrição |
|----------|-------------|-----------|
| `EVOLUTION_INSTANCE` | Sim | Nome da instância na Evolution API (ex: `tino`) |
| `EVOLUTION_API_KEY` | Sim | Token de autenticação da Evolution API |
| `POSTGRES_PASSWORD` | Sim | Senha do banco PostgreSQL |
| `OPENCODE_API_KEY` | Não | Chave do gateway OpenCode (Zen/Go). Sem ela, o bot usa apenas as regras locais |
| `OPENCODE_MODEL` | Não | Modelo no gateway (padrão: `mimo-v2.5-free`) |
| `OPENCODE_BASE_URL` | Não | Endpoint do gateway (padrão: `https://opencode.ai/zen/v1`) |
| `WEBHOOK_TOKEN` | Não | Segredo validado no header `x-tino-token` do webhook (recomendado em produção) |
| `NUM_WORKERS` | Não | Threads de processamento em background (padrão: 4) |

## Robustez

- **Processamento em background** — o webhook valida, registra e enfileira a mensagem (resposta em milissegundos); 4 workers processam em paralelo. Um LLM lento não segura os demais usuários.
- **Sequencial por usuário** — mensagens do mesmo número processam em ordem (lock por telefone); usuários diferentes rodam em paralelo.
- **Dedup por ID** — reenvios da Evolution API são descartados (tabela `mensagens_processadas`, limpeza de 7 dias).
- **Fuso Brasil** — todos os registros e relatórios usam `America/Sao_Paulo` ("hoje"/"semana" corretos para usuários BR).
- **Token no webhook** — sem o header `x-tino-token` correto, a requisição é rejeitada (403).
- **Healthcheck** — `/health` testa o banco e o Docker reinicia o app se ele ficar doente.
- **Pool resiliente** — conexões do Postgres são recriadas automaticamente se o banco reiniciar.
- **Retry no envio** — falha de `sendText` tenta 1 vez a mais antes de desistir.
- **Backup diário** — `backup.sh` roda às 03:00 (cron), `pg_dump | gzip` em `/opt/backups/tino/` com retenção de 14 dias.

## Modelo de dados

```sql
create table gastos (
  id              bigserial primary key,
  telefone        text      not null,
  data            text      not null,
  descricao       text      not null,
  valor           numeric   not null,
  categoria       text      not null,
  forma_pagamento text      default 'não informado'
);

create table receitas (
  id        bigserial primary key,
  telefone  text      not null,
  data      text      not null,
  descricao text      not null,
  valor     numeric   not null,
  categoria text      not null
);

create table metas (
  id        bigserial primary key,
  telefone  text      not null,
  categoria text      not null,
  limite    numeric   not null
);

create table lembretes (
  id              bigserial primary key,
  telefone        text      not null,
  descricao       text      not null,
  valor           numeric   not null,
  dia_vencimento  int       not null
);

create table usuarios (
  telefone        text primary key,
  nome            text,
  criado_em       timestamptz default now(),
  ultima_mensagem timestamptz,
  total_mensagens integer     default 0
);

create table conversas (
  id        bigserial primary key,
  telefone  text           not null,
  papel     text           not null,
  conteudo  text           not null,
  criado_em timestamptz default now()
);
```

## Deploy

A stack é 100% Docker e roda em qualquer VPS. Para expor o webhook publicamente, aponte um túnel (ex: `cloudflared` ou ngrok) para a porta `8000` do host e use essa URL no webhook da Evolution API.

## Roadmap

- Migrar `data` para `timestamptz` em vez de texto
- Testes automatizados para a camada de interpretação e handlers
- Exportação do histórico em CSV
- Gráficos mensais enviados como imagem
- Suporte a áudio e foto de comprovante
- Dashboard web

## Agradecimentos

Projeto derivado de [paylo-ai](https://github.com/joaomauricioporto/paylo-ai), de João Maurício Medeiros Porto. O Tino.IA substitui o Twilio/Supabase por Evolution API + PostgreSQL local e adiciona o modo de interpretação por regras.