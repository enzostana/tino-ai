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

São **16 intenções** distintas reconhecidas a partir de texto livre.

## Como funciona a interpretação

O bot funciona em **dois modos**:

- **IA (padrão)** — usa o gateway OpenCode (`opencode.ai/zen/go/v1`) com o modelo `mimo-v2.5` (assinatura Go, custo fixo e super econômico) para interpretar mensagens em linguagem natural e extrair o JSON da intenção.
- **Regras locais (fallback)** — motor de regex em Python que reconhece as 16 intenções sem custo e sem internet. Ativa automaticamente se a IA falhar ou se nenhuma chave estiver configurada.

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
2. A **camada de interpretação** decide a intenção: pela **API do gateway OpenCode** (`mimo-v2.5`) com um system prompt que define as 16 intenções e força saída em JSON puro, ou, se indisponível, pelas **regras locais**.
3. O **roteador de intenção** despacha pro handler correspondente, que executa a lógica de negócio e as operações no banco.
4. O **banco** PostgreSQL é acessado via `psycopg2` (pool de conexões), com filtros por telefone para isolar os dados de cada usuário.
5. A resposta é enviada de volta pelo **Evolution API** via `POST /message/sendText/{instancia}`.

O telefone do remetente funciona como chave de particionamento: toda consulta filtra por `telefone`, então múltiplos usuários compartilham as mesmas tabelas sem enxergar os dados uns dos outros.

## Stack

| Camada | Tecnologia |
|--------|------------|
| API | FastAPI + Uvicorn |
| Interpretação | Gateway OpenCode (mimo-v2.5) + fallback por regras (regex) |
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
  -d '{"webhook":{"enabled":true,"url":"http://app:8000/webhook","events":["MESSAGES_UPSERT"],"byEvents":true}}'
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

## Variáveis de ambiente

| Variável | Obrigatória | Descrição |
|----------|-------------|-----------|
| `EVOLUTION_INSTANCE` | Sim | Nome da instância na Evolution API (ex: `tino`) |
| `EVOLUTION_API_KEY` | Sim | Token de autenticação da Evolution API |
| `POSTGRES_PASSWORD` | Sim | Senha do banco PostgreSQL |
| `OPENCODE_API_KEY` | Não | Chave do gateway OpenCode (Zen/Go). Sem ela, o bot usa apenas as regras locais |
| `OPENCODE_MODEL` | Não | Modelo no gateway (padrão: `mimo-v2.5`) |
| `OPENCODE_BASE_URL` | Não | Endpoint do gateway (padrão: `https://opencode.ai/zen/go/v1`) |

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