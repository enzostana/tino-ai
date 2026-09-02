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