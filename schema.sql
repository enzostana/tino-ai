create table if not exists gastos (
  id              bigserial primary key,
  telefone        text      not null,
  data            text      not null,
  descricao       text      not null,
  valor           numeric   not null,
  categoria       text      not null,
  forma_pagamento text      default 'não informado'
);

create table if not exists receitas (
  id        bigserial primary key,
  telefone  text      not null,
  data      text      not null,
  descricao text      not null,
  valor     numeric   not null,
  categoria text      not null
);

create table if not exists metas (
  id        bigserial primary key,
  telefone  text      not null,
  categoria text      not null,
  limite    numeric   not null
);

create table if not exists lembretes (
  id              bigserial primary key,
  telefone        text      not null,
  descricao       text      not null,
  valor           numeric   not null,
  dia_vencimento  int       not null
);

create table if not exists usuarios (
  telefone        text primary key,
  nome            text,
  criado_em       timestamptz default now(),
  ultima_mensagem timestamptz,
  total_mensagens integer     default 0
);

create index if not exists idx_gastos_telefone on gastos (telefone);
create index if not exists idx_receitas_telefone on receitas (telefone);
create index if not exists idx_metas_telefone on metas (telefone);
create index if not exists idx_lembretes_telefone on lembretes (telefone);

create table if not exists conversas (
  id        bigserial primary key,
  telefone  text           not null,
  papel     text           not null,
  conteudo  text           not null,
  criado_em timestamptz default now()
);

create index if not exists idx_conversas_telefone on conversas (telefone, id desc);

create table if not exists mensagens_processadas (
  id        text primary key,
  telefone  text           not null default '',
  criado_em timestamptz default now()
);

create index if not exists idx_mensagens_criado on mensagens_processadas (criado_em);