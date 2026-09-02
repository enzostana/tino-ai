from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import anthropic
import json
import os
import re
from datetime import datetime, timedelta
import httpx
import logging
from psycopg2 import pool

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
OPENCODE_API_KEY = os.getenv("OPENCODE_API_KEY", "")
OPENCODE_MODEL = os.getenv("OPENCODE_MODEL", "mimo-v2.5")
OPENCODE_BASE_URL = os.getenv("OPENCODE_BASE_URL", "https://opencode.ai/zen/go/v1")
EVOLUTION_URL = os.getenv("EVOLUTION_URL", "").rstrip("/")
EVOLUTION_INSTANCE = os.getenv("EVOLUTION_INSTANCE", "")
EVOLUTION_API_KEY = os.getenv("EVOLUTION_API_KEY", "")
DATABASE_URL = os.getenv("DATABASE_URL", "")

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

_db_pool = None

def get_pool():
    global _db_pool
    if _db_pool is None:
        _db_pool = pool.ThreadedConnectionPool(1, 10, dsn=DATABASE_URL)
    return _db_pool

def query(sql, params=None):
    """Executa uma query e retorna linhas como dicionários (ou [] para DML sem retorno)."""
    pool = get_pool()
    conn = pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            if cur.description:
                cols = [d[0] for d in cur.description]
                rows = cur.fetchall()
                conn.commit()
                return [dict(zip(cols, r)) for r in rows]
            conn.commit()
            return []
    finally:
        pool.putconn(conn)

def insert(sql, params):
    """Executa um INSERT e retorna o id gerado."""
    resultado = query(sql, params)
    return resultado[0]["id"] if resultado else "?"

# ============================================================
# WHATSAPP (EVOLUTION API)
# ============================================================
def enviar_whatsapp(telefone, texto):
    try:
        url = f"{EVOLUTION_URL}/message/sendText/{EVOLUTION_INSTANCE}"
        headers = {"apikey": EVOLUTION_API_KEY, "Content-Type": "application/json"}
        data = {"number": telefone, "text": texto}
        httpx.post(url, headers=headers, json=data, timeout=20)
    except Exception as e:
        logger.error(f"Falha ao enviar WhatsApp para {telefone}: {e}")

# ============================================================
# HELPERS
# ============================================================
def filtro_mes(hoje, offset=0):
    """Retorna o prefixo YYYY-MM para o mês atual ou anterior."""
    mes = hoje.month - offset
    ano = hoje.year
    while mes <= 0:
        mes += 12
        ano -= 1
    return f"{ano}-{mes:02d}"

def buscar_gastos_periodo(telefone, periodo="mes"):
    hoje = datetime.now()
    if periodo == "hoje":
        return query(
            "SELECT * FROM gastos WHERE telefone = %s AND data LIKE %s ORDER BY id DESC",
            (telefone, f"{hoje.strftime('%Y-%m-%d')}%")
        )
    elif periodo == "semana":
        inicio = (hoje - timedelta(days=7)).strftime("%Y-%m-%d")
        return query(
            "SELECT * FROM gastos WHERE telefone = %s AND data >= %s ORDER BY id DESC",
            (telefone, inicio)
        )
    return query(
        "SELECT * FROM gastos WHERE telefone = %s AND data LIKE %s ORDER BY id DESC",
        (telefone, f"{filtro_mes(hoje)}%")
    )

def buscar_gastos_mes_offset(telefone, offset=0):
    """Busca gastos de um mês específico. offset=0 = mês atual, offset=1 = mês passado."""
    prefixo = filtro_mes(datetime.now(), offset)
    return query(
        "SELECT * FROM gastos WHERE telefone = %s AND data LIKE %s ORDER BY id DESC",
        (telefone, f"{prefixo}%")
    )

# ============================================================
# GASTOS
# ============================================================
def salvar_gasto(descricao, valor, categoria, forma_pagamento, telefone):
    return insert(
        "INSERT INTO gastos (telefone, data, descricao, valor, categoria, forma_pagamento) "
        "VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
        (telefone, datetime.now().strftime("%Y-%m-%d %H:%M"), descricao, valor, categoria, forma_pagamento)
    )

def remover_ultimo_gasto(telefone):
    gastos = query("SELECT * FROM gastos WHERE telefone = %s ORDER BY id DESC LIMIT 1", (telefone,))
    if not gastos: return None
    gasto = gastos[0]
    query("DELETE FROM gastos WHERE id = %s", (gasto["id"],))
    return gasto

def remover_gasto_por_descricao(telefone, descricao):
    gastos = query("SELECT * FROM gastos WHERE telefone = %s ORDER BY id DESC LIMIT 50", (telefone,))
    filtrados = [g for g in gastos if descricao.lower() in g.get("descricao", "").lower()]
    if not filtrados: return None
    gasto = filtrados[0]
    query("DELETE FROM gastos WHERE id = %s", (gasto["id"],))
    return gasto

def remover_gasto_por_categoria(telefone, categoria, valor=None):
    gastos = query("SELECT * FROM gastos WHERE telefone = %s ORDER BY id DESC LIMIT 50", (telefone,))
    filtrados = [g for g in gastos if categoria.lower() in g.get("categoria", "").lower()]
    if not filtrados: return None
    if valor:
        por_valor = [g for g in filtrados if abs(g["valor"] - valor) < 0.01]
        if not por_valor: return None
        gasto = por_valor[0]
    else:
        gasto = filtrados[0]
    query("DELETE FROM gastos WHERE id = %s", (gasto["id"],))
    return gasto

def listar_ultimos_gastos(telefone, limite=5):
    return query(
        "SELECT * FROM gastos WHERE telefone = %s ORDER BY id DESC LIMIT %s",
        (telefone, limite)
    )

# ============================================================
# RECEITAS
# ============================================================
def salvar_receita(descricao, valor, categoria, telefone):
    return insert(
        "INSERT INTO receitas (telefone, data, descricao, valor, categoria) "
        "VALUES (%s, %s, %s, %s, %s) RETURNING id",
        (telefone, datetime.now().strftime("%Y-%m-%d %H:%M"), descricao, valor, categoria)
    )

def buscar_receitas_periodo(telefone, periodo="mes"):
    hoje = datetime.now()
    if periodo == "hoje":
        return query(
            "SELECT * FROM receitas WHERE telefone = %s AND data LIKE %s ORDER BY id DESC",
            (telefone, f"{hoje.strftime('%Y-%m-%d')}%")
        )
    elif periodo == "semana":
        inicio = (hoje - timedelta(days=7)).strftime("%Y-%m-%d")
        return query(
            "SELECT * FROM receitas WHERE telefone = %s AND data >= %s ORDER BY id DESC",
            (telefone, inicio)
        )
    return query(
        "SELECT * FROM receitas WHERE telefone = %s AND data LIKE %s ORDER BY id DESC",
        (telefone, f"{filtro_mes(hoje)}%")
    )

# ============================================================
# METAS
# ============================================================
def salvar_meta(telefone, categoria, limite):
    existentes = query("SELECT * FROM metas WHERE telefone = %s ORDER BY id DESC LIMIT 50", (telefone,))
    for m in existentes:
        if categoria.lower() in m.get("categoria", "").lower():
            query("UPDATE metas SET limite = %s WHERE id = %s", (limite, m["id"]))
            return "atualizada"
    query(
        "INSERT INTO metas (telefone, categoria, limite) VALUES (%s, %s, %s)",
        (telefone, categoria, limite)
    )
    return "criada"

def buscar_metas(telefone):
    return query("SELECT * FROM metas WHERE telefone = %s ORDER BY categoria ASC", (telefone,))

# ============================================================
# LEMBRETES
# ============================================================
def salvar_lembrete(telefone, descricao, valor, dia_vencimento):
    return insert(
        "INSERT INTO lembretes (telefone, descricao, valor, dia_vencimento) "
        "VALUES (%s, %s, %s, %s) RETURNING id",
        (telefone, descricao, valor, dia_vencimento)
    )

def buscar_lembretes(telefone):
    return query(
        "SELECT * FROM lembretes WHERE telefone = %s ORDER BY dia_vencimento ASC",
        (telefone,)
    )

def remover_lembrete(telefone, descricao):
    lembretes = query("SELECT * FROM lembretes WHERE telefone = %s ORDER BY id DESC LIMIT 50", (telefone,))
    filtrados = [l for l in lembretes if descricao.lower() in l.get("descricao", "").lower()]
    if not filtrados: return None
    lembrete = filtrados[0]
    query("DELETE FROM lembretes WHERE id = %s", (lembrete["id"],))
    return lembrete

# ============================================================
# IA
# ============================================================
SYSTEM_PROMPT = """Você é um assistente financeiro pessoal via WhatsApp chamado Tino.IA 🐙.
Responda APENAS com JSON válido, sem markdown, sem explicações.

1. REGISTRAR GASTO (ex: "uber 27", "mercado 150 débito", "almoço 35 pix"):
{"tipo": "gasto", "descricao": "descrição", "valor": 27.0, "categoria": "Transporte", "forma_pagamento": "não informado"}
Categorias: Alimentação, Transporte, Lazer, Saúde, Moradia, Educação, Vestuário, Outros

2. REGISTRAR RECEITA (ex: "recebi salário 3000", "freelance 500", "entrada 1200"):
{"tipo": "receita", "descricao": "salário", "valor": 3000.0, "categoria": "Salário"}
Categorias receita: Salário, Freelance, Investimento, Presente, Outros

3. RELATÓRIO GASTOS (ex: "resumo", "quanto gastei hoje", "resumo da semana"):
{"tipo": "relatorio", "periodo": "mes"}
Períodos: hoje, semana, mes

4. RELATÓRIO POR FORMA DE PAGAMENTO (ex: "quanto gastei no cartão", "total no pix"):
{"tipo": "relatorio_pagamento", "forma": "cartão", "periodo": "mes"}

5. SALDO DISPONÍVEL (ex: "saldo", "quanto tenho", "quanto sobrou"):
{"tipo": "saldo", "periodo": "mes"}

6. COMPARATIVO MESES (ex: "comparar meses", "esse mês vs mês passado", "comparativo"):
{"tipo": "comparativo"}

7. DEFINIR META (ex: "meta alimentação 500", "limite lazer 300", "definir meta transporte 200"):
{"tipo": "definir_meta", "categoria": "Alimentação", "limite": 500.0}

8. VER METAS (ex: "minhas metas", "ver limites", "metas"):
{"tipo": "ver_metas"}

9. ADICIONAR LEMBRETE (ex: "lembrete aluguel 1200 dia 5", "conta luz 80 vence dia 10"):
{"tipo": "adicionar_lembrete", "descricao": "aluguel", "valor": 1200.0, "dia_vencimento": 5}

10. VER LEMBRETES (ex: "meus lembretes", "contas fixas", "ver lembretes"):
{"tipo": "ver_lembretes"}

11. REMOVER LEMBRETE (ex: "remover lembrete aluguel", "apagar conta luz"):
{"tipo": "remover_lembrete", "descricao": "aluguel"}

12. REMOVER ÚLTIMO (ex: "remover último", "desfazer"):
{"tipo": "remover_ultimo"}

13. REMOVER ESPECÍFICO (ex: "remover uber", "apagar mercado"):
{"tipo": "remover_item", "descricao": "uber"}

14. REMOVER POR CATEGORIA (ex: "remover lazer", "extorno 100 transporte"):
{"tipo": "remover_categoria", "categoria": "Lazer", "valor": null}

15. HISTÓRICO (ex: "últimos gastos", "o que registrei"):
{"tipo": "historico"}

16. OUTROS (ex: "oi", "ajuda"):
{"tipo": "ajuda"}"""

def interpretar_com_claude(mensagem):
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=400,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": mensagem}]
    )
    texto = response.content[0].text.strip()
    if texto.startswith("```"):
        texto = texto.split("```")[1]
        if texto.startswith("json"):
            texto = texto[4:]
    return json.loads(texto.strip())

# ============================================================
# IA — REGRAS (sem chave de API)
# ============================================================
NOMES_CATEGORIAS = [
    "alimentação", "alimentacao", "transporte", "lazer", "saúde", "saude",
    "moradia", "educação", "educacao", "vestuário", "vestuario", "outros"
]

PALAVRAS_CATEGORIA = {
    "Alimentação": ["alimentação", "alimentacao", "almoço", "almoco", "jantar", "mercado",
                    "ifood", "i food", "lanche", "café", "cafe", "restaurante", "açaí",
                    "acai", "padaria", "supermercado", "comida", "pizza", "hamburguer",
                    "hambúrguer", "feira", "sushi", "dogao", "dogão", "pão", "pao",
                    "x-burger", "esfiha", "marmita"],
    "Transporte": ["transporte", "uber", "99", "taxi", "táxi", "gasolina", "combustivel",
                   "combustível", "ônibus", "onibus", "metrô", "metro", "pedágio",
                   "pedagio", "estacionamento", "bilhete", "passagem", "carro",
                   "app de carro", "voo", "passe"],
    "Lazer": ["lazer", "cinema", "jogo", "stream", "netflix", "spotify", "show", "bar",
              "festa", "viagem", "passeio", "steam", "game", "balada", "cerveja",
              "happy hour"],
    "Saúde": ["saúde", "saude", "farmacia", "farmácia", "remédio", "remedio", "médico",
              "medico", "dentista", "academia", "psicólogo", "psicologo", "consulta",
              "exame", "vacina", "fisioterapia"],
    "Moradia": ["moradia", "aluguel", "condominio", "condomínio", "luz", "energia", "água",
                "agua", "internet", "gás", "gas", "iptu", "conta de luz", "conta de água",
                "limpeza"],
    "Educação": ["educação", "educacao", "curso", "faculdade", "mensalidade", "livro",
                 "escola", "universidade", "material escolar", "matrícula", "matricula",
                 "aula"],
    "Vestuário": ["vestuário", "vestuario", "roupa", "camisa", "sapato", "tênis", "tenis",
                  "calça", "calca", "vestido", "casaco", "blusa", "short"],
}

FORMAS_PAGAMENTO = ["pix", "débito", "debito", "crédito", "credito", "cartão", "cartao",
                    "dinheiro", "boleto", "transferência", "transferencia"]

PALAVRAS_RECEITA = ["recebi", "recebido", "salário", "salario", "freelance", "freela",
                    "investimento", "dividendo", "presente", "entrada", "renda", "comissão",
                    "comissao", "bônus", "bonus", "ganhei", "pix recebido", "vendi", "venda"]

CATEGORIA_RECEITA = {
    "Salário": ["salário", "salario", "salario", "renda"],
    "Freelance": ["freelance", "freela", "comissão", "comissao", "vendi", "venda"],
    "Investimento": ["investimento", "dividendo", "rendimento"],
    "Presente": ["presente", "ganhei", "bônus", "bonus"],
}

VALOR_RE = re.compile(r"(?:R\$|r\$)?\s*(\d{1,3}(?:\.\d{3})+(?:,\d{1,2})?|\d+(?:[.,]\d{1,2})?)")

DIA_RE = re.compile(r"(?:dia|vence(?: dia)?|todo dia|todo mês|todo mes)\s*(\d{1,2})")

def extrair_valor(texto):
    m = VALOR_RE.search(texto)
    if not m:
        return None
    return float(m.group(1).replace(".", "").replace(",", "."))

def limpar_descricao(texto):
    desc = texto.lower()
    for w in ["gastei", "paguei", "comprei", "foi", "no", "na", "nos", "nas", "de", "do",
              "da", "em", "com", "um", "uma", "hoje", "ontem", "agora", "registrar",
              "registra", "recebi", "recebido", "ganhei", "entrada de"]:
        desc = re.sub(rf"\b{w}\b", " ", desc)
    for f in FORMAS_PAGAMENTO:
        desc = desc.replace(f, " ")
    desc = re.sub(r"\b\d+[.,]?\d*\b", " ", desc)
    desc = re.sub(r"\s+", " ", desc).strip()
    return desc.capitalize() or "Gasto"

def detectar_categoria(texto):
    for cat, palavras in PALAVRAS_CATEGORIA.items():
        for p in palavras:
            if re.search(rf"\b{re.escape(p)}\b", texto.lower()):
                return cat
    return None

def detectar_forma(texto):
    for f in FORMAS_PAGAMENTO:
        if re.search(rf"\b{re.escape(f)}\b", texto.lower()):
            return f
    return "não informado"

def detectar_categoria_receita(texto):
    for cat, palavras in CATEGORIA_RECEITA.items():
        for p in palavras:
            if re.search(rf"\b{re.escape(p)}\b", texto.lower()):
                return cat
    return "Outros"

def nome_categoria_no_texto(texto):
    for nome in NOMES_CATEGORIAS:
        if re.search(rf"\b{re.escape(nome)}\b", texto.lower()):
            return nome
    return None

def interpretar_com_regras(mensagem):
    m = mensagem.lower().strip()

    if m in ("oi", "ola", "olá", "ajuda", "help", "hello", "começar", "comecar", "inicio", "início"):
        return {"tipo": "ajuda"}

    if any(p in m for p in ["quanto gastei no", "total no", "gastei no cartão", "gastei no cartao",
                            "no cartão", "no cartao", "total no pix", "quanto no pix",
                            "gastos no cartão", "gastos no cartao", "no débito", "no debito",
                            "no crédito", "no credito"]):
        forma = detectar_forma(m)
        if forma == "não informado":
            forma = "cartão" if ("cart" in m) else "pix" if "pix" in m else "cartão"
        periodo = "hoje" if "hoje" in m else "semana" if ("semana" in m or "7 dias" in m) else "mes"
        return {"tipo": "relatorio_pagamento", "forma": forma, "periodo": periodo}

    if any(p in m for p in ["resumo", "quanto gastei", "gastei quanto", "relatório", "relatorio",
                            "meus gastos", "gastos do mês", "gastos do mes"]):
        periodo = "hoje" if "hoje" in m else "semana" if ("semana" in m or "7 dias" in m) else "mes"
        return {"tipo": "relatorio", "periodo": periodo}

    if "saldo" in m or "quanto tenho" in m or "quanto sobrou" in m or "quanto sobra" in m:
        periodo = "hoje" if "hoje" in m else "semana" if ("semana" in m or "7 dias" in m) else "mes"
        return {"tipo": "saldo", "periodo": periodo}

    if "compar" in m or "mês passado" in m or "mes passado" in m or "vs mês" in m:
        return {"tipo": "comparativo"}

    if "histórico" in m or "historico" in m or "últimos gastos" in m or "ultimos gastos" in m \
            or "o que registrei" in m or "ultimas compras" in m or "últimas compras" in m:
        return {"tipo": "historico"}

    if "remover último" in m or "remover ultimo" in m or "desfazer" in m or "apagar último" in m \
            or "apagar ultimo" in m or "desfaz" in m:
        return {"tipo": "remover_ultimo"}

    if m.startswith("remover ") or m.startswith("apagar ") or m.startswith("excluir ") \
            or m.startswith("deletar ") or m.startswith("extorn") or m.startswith("estorno"):
        resto = m.split(" ", 1)[1].strip() if " " in m else ""
        if "lembrete" in resto or "conta" in resto:
            desc = resto.replace("lembrete", "").replace("conta", "").strip()
            return {"tipo": "remover_lembrete", "descricao": desc}
        nome_cat = nome_categoria_no_texto(resto)
        if nome_cat:
            valor = extrair_valor(resto)
            return {"tipo": "remover_categoria", "categoria": nome_cat.capitalize(), "valor": valor}
        if "meta" in resto:
            return {"tipo": "remover_lembrete", "descricao": resto.replace("meta", "").strip()}
        return {"tipo": "remover_item", "descricao": resto}

    if any(p in m for p in ["minhas metas", "ver metas", "ver limites", "meus limites"]):
        return {"tipo": "ver_metas"}

    if "meta" in m or "limite" in m or "limitar" in m:
        valor = extrair_valor(m)
        if valor:
            cat = detectar_categoria(m) or "Outros"
            return {"tipo": "definir_meta", "categoria": cat, "limite": valor}
        return {"tipo": "ver_metas"}

    if any(p in m for p in ["meus lembretes", "ver lembretes", "contas fixas", "minhas contas",
                            "meus compromissos"]):
        return {"tipo": "ver_lembretes"}

    dia_match = DIA_RE.search(m)
    if dia_match and ("lembrete" in m or "vence" in m or "todo dia" in m or "conta" in m
                      or "compromisso" in m):
        dia = int(dia_match.group(1))
        valor = extrair_valor(m) or 0.0
        desc = m.replace("lembrete", "").replace("conta", "").replace("compromisso", "")
        desc = re.sub(r"(?:vence(?: dia)?|todo dia|todo mês|todo mes|dia)\s*\d{1,2}.*$", "", desc)
        desc = re.sub(r"\d+[.,]?\d*", "", desc).strip()
        for w in ["de", "do", "da", "no", "na", "em", "todo"]:
            desc = re.sub(rf"\b{w}\b", " ", desc)
        desc = re.sub(r"\s+", " ", desc).strip().capitalize()
        return {"tipo": "adicionar_lembrete", "descricao": desc or "Conta", "valor": valor,
                "dia_vencimento": dia}

    if any(p in m for p in PALAVRAS_RECEITA):
        valor = extrair_valor(m)
        if valor:
            cat = detectar_categoria_receita(m)
            desc = limpar_descricao(m)
            return {"tipo": "receita", "descricao": desc, "valor": valor, "categoria": cat}

    valor = extrair_valor(m)
    if valor:
        desc = limpar_descricao(m)
        cat = detectar_categoria(m) or "Outros"
        forma = detectar_forma(m)
        return {"tipo": "gasto", "descricao": desc, "valor": valor, "categoria": cat,
                "forma_pagamento": forma}

    return {"tipo": "ajuda"}

def interpretar_com_llm(mensagem):
    """Interpreta via gateway OpenCode (compatível com OpenAI)."""
    r = httpx.post(
        f"{OPENCODE_BASE_URL}/chat/completions",
        headers={"Authorization": f"Bearer {OPENCODE_API_KEY}",
                 "Content-Type": "application/json"},
        json={
            "model": OPENCODE_MODEL,
            "max_tokens": 400,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": mensagem}
            ]
        },
        timeout=30
    )
    r.raise_for_status()
    texto = r.json()["choices"][0]["message"]["content"].strip()
    if texto.startswith("```"):
        texto = texto.split("```")[1]
        if texto.startswith("json"):
            texto = texto[4:]
    return json.loads(texto.strip())

def interpretar_mensagem(mensagem):
    """Usa o gateway OpenCode (ou Claude) se configurado; senão, usa regras locais."""
    if OPENCODE_API_KEY:
        try:
            return interpretar_com_llm(mensagem)
        except Exception as e:
            logger.warning(f"OpenCode falhou, usando regras: {e}")
    elif ANTHROPIC_API_KEY:
        try:
            return interpretar_com_claude(mensagem)
        except Exception as e:
            logger.warning(f"Claude falhou, usando regras: {e}")
    return interpretar_com_regras(mensagem)

# ============================================================
# RELATÓRIOS
# ============================================================
def gerar_relatorio(telefone, periodo):
    gastos = buscar_gastos_periodo(telefone, periodo)
    if not gastos:
        nomes = {"hoje": "hoje", "semana": "nos últimos 7 dias", "mes": "este mês"}
        return f"📭 Nenhum gasto registrado {nomes.get(periodo, 'neste período')}."
    total = sum(g["valor"] for g in gastos)
    por_cat = {}
    for g in gastos:
        por_cat[g["categoria"]] = por_cat.get(g["categoria"], 0) + g["valor"]
    nomes_p = {"hoje": "Hoje", "semana": "Últimos 7 dias", "mes": "Este mês"}
    linhas = [f"📊 *Relatório — {nomes_p.get(periodo, 'Período')}*\n"]
    for cat, val in sorted(por_cat.items(), key=lambda x: -x[1]):
        linhas.append(f"  {cat}: R$ {val:.2f}")
    linhas.append(f"\n💰 *Total: R$ {total:.2f}*")

    metas = buscar_metas(telefone)
    alertas = []
    for meta in metas:
        cat = meta["categoria"]
        limite = meta["limite"]
        gasto_cat = por_cat.get(cat, 0)
        pct = (gasto_cat / limite) * 100 if limite > 0 else 0
        if pct >= 100:
            alertas.append(f"🚨 *{cat}*: limite de R$ {limite:.2f} ultrapassado!")
        elif pct >= 80:
            alertas.append(f"⚠️ *{cat}*: {pct:.0f}% do limite (R$ {gasto_cat:.2f}/R$ {limite:.2f})")
    if alertas:
        linhas.append("\n" + "\n".join(alertas))
    return "\n".join(linhas)

def gerar_relatorio_pagamento(telefone, forma, periodo):
    todos = buscar_gastos_periodo(telefone, periodo)
    gastos = [g for g in todos if forma.lower() in g.get("forma_pagamento", "").lower()]
    nomes = {"hoje": "hoje", "semana": "nos últimos 7 dias", "mes": "este mês"}
    if not gastos:
        return f"📭 Nenhum gasto no {forma} {nomes.get(periodo, 'neste período')}."
    total = sum(g["valor"] for g in gastos)
    por_cat = {}
    for g in gastos:
        por_cat[g["categoria"]] = por_cat.get(g["categoria"], 0) + g["valor"]
    nomes2 = {"hoje": "Hoje", "semana": "Últimos 7 dias", "mes": "Este mês"}
    linhas = [f"💳 *{forma.capitalize()} — {nomes2.get(periodo, 'Período')}*\n"]
    for cat, val in sorted(por_cat.items(), key=lambda x: -x[1]):
        linhas.append(f"  {cat}: R$ {val:.2f}")
    linhas.append(f"\n💰 *Total no {forma}: R$ {total:.2f}*")
    return "\n".join(linhas)

def gerar_saldo(telefone, periodo):
    gastos = buscar_gastos_periodo(telefone, periodo)
    receitas = buscar_receitas_periodo(telefone, periodo)
    total_gastos = sum(g["valor"] for g in gastos)
    total_receitas = sum(r["valor"] for r in receitas)
    saldo = total_receitas - total_gastos
    nomes = {"hoje": "Hoje", "semana": "Últimos 7 dias", "mes": "Este mês"}
    emoji = "✅" if saldo >= 0 else "🔴"
    linhas = [
        f"💼 *Saldo — {nomes.get(periodo, 'Período')}*\n",
        f"  📈 Receitas: R$ {total_receitas:.2f}",
        f"  📉 Gastos: R$ {total_gastos:.2f}",
        f"\n{emoji} *Saldo: R$ {saldo:.2f}*"
    ]
    if not receitas:
        linhas.append("\n💡 Dica: registre suas receitas com 'recebi salário 3000'")
    return "\n".join(linhas)

def gerar_comparativo(telefone):
    hoje = datetime.now()
    gastos_atual = buscar_gastos_mes_offset(telefone, 0)
    gastos_passado = buscar_gastos_mes_offset(telefone, 1)

    total_atual = sum(g["valor"] for g in gastos_atual)
    total_passado = sum(g["valor"] for g in gastos_passado)

    mes_atual = hoje.strftime("%B/%Y")
    mes_passado = (hoje.replace(day=1) - timedelta(days=1)).strftime("%B/%Y")

    cats_atual = {}
    for g in gastos_atual:
        cats_atual[g["categoria"]] = cats_atual.get(g["categoria"], 0) + g["valor"]
    cats_passado = {}
    for g in gastos_passado:
        cats_passado[g["categoria"]] = cats_passado.get(g["categoria"], 0) + g["valor"]

    todas_cats = set(list(cats_atual.keys()) + list(cats_passado.keys()))

    diff = total_atual - total_passado
    emoji = "📈" if diff > 0 else "📉"

    linhas = [f"📅 *Comparativo de Meses*\n"]
    linhas.append(f"  {mes_passado}: R$ {total_passado:.2f}")
    linhas.append(f"  {mes_atual}: R$ {total_atual:.2f}")
    linhas.append(f"\n{emoji} Diferença: R$ {abs(diff):.2f} {'a mais' if diff > 0 else 'a menos'} que o mês passado\n")

    if todas_cats:
        linhas.append("*Por categoria:*")
        for cat in sorted(todas_cats):
            v_atual = cats_atual.get(cat, 0)
            v_passado = cats_passado.get(cat, 0)
            d = v_atual - v_passado
            sinal = "▲" if d > 0 else "▼" if d < 0 else "="
            linhas.append(f"  {cat}: R$ {v_atual:.2f} {sinal}")
    return "\n".join(linhas)

def gerar_ver_metas(telefone):
    metas = buscar_metas(telefone)
    if not metas:
        return "📭 Nenhuma meta definida.\n\n💡 Defina uma com: 'meta alimentação 500'"
    gastos = buscar_gastos_mes_offset(telefone, 0)
    por_cat = {}
    for g in gastos:
        por_cat[g["categoria"]] = por_cat.get(g["categoria"], 0) + g["valor"]

    linhas = ["🎯 *Suas metas este mês:*\n"]
    for meta in metas:
        cat = meta["categoria"]
        limite = meta["limite"]
        gasto = por_cat.get(cat, 0)
        pct = (gasto / limite) * 100 if limite > 0 else 0
        barra = "█" * int(pct / 10) + "░" * (10 - int(pct / 10))
        emoji = "🚨" if pct >= 100 else "⚠️" if pct >= 80 else "✅"
        linhas.append(f"{emoji} *{cat}*")
        linhas.append(f"  [{barra}] {pct:.0f}%")
        linhas.append(f"  R$ {gasto:.2f} / R$ {limite:.2f}\n")
    return "\n".join(linhas)

def gerar_ver_lembretes(telefone):
    lembretes = buscar_lembretes(telefone)
    if not lembretes:
        return "📭 Nenhum lembrete cadastrado.\n\n💡 Adicione com: 'lembrete aluguel 1200 dia 5'"
    hoje = datetime.now().day
    linhas = ["🔔 *Contas fixas:*\n"]
    for l in lembretes:
        dia = l["dia_vencimento"]
        valor = l["valor"]
        desc = l["descricao"].capitalize()
        dias_restantes = dia - hoje
        if dias_restantes < 0:
            dias_restantes += 30
        if dias_restantes == 0:
            emoji = "🚨"
            aviso = "vence HOJE!"
        elif dias_restantes <= 3:
            emoji = "⚠️"
            aviso = f"vence em {dias_restantes} dia(s)"
        else:
            emoji = "📅"
            aviso = f"dia {dia}"
        linhas.append(f"{emoji} *{desc}* — R$ {valor:.2f} ({aviso})")
    return "\n".join(linhas)

def gerar_historico(telefone):
    gastos = listar_ultimos_gastos(telefone)
    if not gastos:
        return "📭 Nenhum gasto registrado ainda."
    linhas = ["🧾 *Últimos gastos:*\n"]
    for g in gastos:
        forma = g.get("forma_pagamento", "não informado")
        linhas.append(f"• {g['descricao'].capitalize()} — R$ {g['valor']:.2f} ({g['categoria']} · {forma})")
    return "\n".join(linhas)

# ============================================================
# USUÁRIOS
# ============================================================
def registrar_usuario(telefone, nome):
    """Registra o usuário se for a primeira mensagem. Retorna True se for novo."""
    existente = query("SELECT telefone FROM usuarios WHERE telefone = %s", (telefone,))
    if not existente:
        query("INSERT INTO usuarios (telefone, nome) VALUES (%s, %s)", (telefone, nome or ""))
        return True
    return False

def atualizar_atividade(telefone, nome):
    query(
        "UPDATE usuarios SET nome = %s, ultima_mensagem = now(), "
        "total_mensagens = total_mensagens + 1 WHERE telefone = %s",
        (nome or "", telefone)
    )

# ============================================================
# AJUDA
# ============================================================
MENSAGEM_AJUDA = """🐙 *Tino.IA — Seu assistente financeiro!*

*📝 Gastos:*
• "mercado 150" / "uber 27 pix"

*📈 Receitas:*
• "recebi salário 3000"
• "freelance 500"

*📊 Relatórios:*
• "resumo" / "resumo da semana"
• "quanto gastei no cartão"
• "saldo" / "quanto sobrou"
• "comparar meses"

*🎯 Metas:*
• "meta alimentação 500"
• "metas" / "ver limites"

*🔔 Lembretes:*
• "lembrete aluguel 1200 dia 5"
• "lembretes" / "contas fixas"

*🗑️ Remover:*
• "remover último"
• "remover uber" / "remover lazer"

*💡 Escreva naturalmente, eu entendo! 😊*"""

MENSAGEM_BEM_VINDO = """👋 *Oi! Eu sou o Tino.IA 🐙*, seu assistente financeiro no WhatsApp!

Basta escrever como se falasse com um amigo. Veja exemplos:

*📝 Gastos:*
• "uber 27" / "almoço 32 no pix"
• "mercado 150 débito"

*📈 Receitas:*
• "recebi salário 3000"
• "freelance 500"

*📊 Relatórios:*
• "resumo" / "resumo da semana"
• "saldo" / "quanto sobrou"
• "comparar meses"

*🎯 Metas:*
• "meta alimentação 300"
• "metas"

*🔔 Lembretes:*
• "lembrete aluguel 1200 dia 5"
• "lembretes"

*🗑️ Correções:*
• "remover último" / "remover uber"

Mande *"ajuda"* a qualquer momento para ver os comandos. Vamos lá! 😊"""

# ============================================================
# PROCESSAMENTO
# ============================================================
def processar_mensagem(mensagem, telefone):
    """Interpreta a mensagem com IA e executa a intenção. Retorna o texto de resposta."""
    resultado = interpretar_mensagem(mensagem)
    logger.info(f"Interpretado: {resultado}")
    tipo = resultado["tipo"]

    if tipo == "gasto":
        gasto_id = salvar_gasto(
            resultado["descricao"], resultado["valor"],
            resultado["categoria"], resultado.get("forma_pagamento", "não informado"), telefone
        )
        metas = buscar_metas(telefone)
        gastos_mes = buscar_gastos_mes_offset(telefone, 0)
        por_cat = {}
        for g in gastos_mes:
            por_cat[g["categoria"]] = por_cat.get(g["categoria"], 0) + g["valor"]
        alerta = ""
        for meta in metas:
            if meta["categoria"].lower() == resultado["categoria"].lower():
                gasto_cat = por_cat.get(resultado["categoria"], 0)
                pct = (gasto_cat / meta["limite"]) * 100
                if pct >= 100:
                    alerta = f"\n\n🚨 *Atenção!* Você ultrapassou o limite de R$ {meta['limite']:.2f} em {resultado['categoria']}!"
                elif pct >= 80:
                    alerta = f"\n\n⚠️ Você usou {pct:.0f}% do limite de {resultado['categoria']} (R$ {gasto_cat:.2f}/R$ {meta['limite']:.2f})"
        return (
            f"✅ *Gasto registrado!* (#{gasto_id})\n\n"
            f"📌 {resultado['descricao'].capitalize()}\n"
            f"💵 R$ {resultado['valor']:.2f}\n"
            f"🏷️ {resultado['categoria']}\n"
            f"💳 {resultado.get('forma_pagamento', 'não informado').capitalize()}"
            + alerta
        )

    if tipo == "receita":
        rec_id = salvar_receita(resultado["descricao"], resultado["valor"], resultado.get("categoria", "Outros"), telefone)
        return (
            f"✅ *Receita registrada!* (#{rec_id})\n\n"
            f"📌 {resultado['descricao'].capitalize()}\n"
            f"💵 R$ {resultado['valor']:.2f}\n"
            f"🏷️ {resultado.get('categoria', 'Outros')}"
        )

    if tipo == "relatorio":
        return gerar_relatorio(telefone, resultado.get("periodo", "mes"))

    if tipo == "relatorio_pagamento":
        return gerar_relatorio_pagamento(telefone, resultado.get("forma", "cartão"), resultado.get("periodo", "mes"))

    if tipo == "saldo":
        return gerar_saldo(telefone, resultado.get("periodo", "mes"))

    if tipo == "comparativo":
        return gerar_comparativo(telefone)

    if tipo == "definir_meta":
        status = salvar_meta(telefone, resultado["categoria"], resultado["limite"])
        return f"🎯 *Meta {status}!*\n\n{resultado['categoria']}: R$ {resultado['limite']:.2f}/mês"

    if tipo == "ver_metas":
        return gerar_ver_metas(telefone)

    if tipo == "adicionar_lembrete":
        lembrete_id = salvar_lembrete(telefone, resultado["descricao"], resultado["valor"], resultado["dia_vencimento"])
        return f"🔔 *Lembrete adicionado!* (#{lembrete_id})\n\n📌 {resultado['descricao'].capitalize()}\n💵 R$ {resultado['valor']:.2f}\n📅 Todo dia {resultado['dia_vencimento']}"

    if tipo == "ver_lembretes":
        return gerar_ver_lembretes(telefone)

    if tipo == "remover_lembrete":
        lembrete = remover_lembrete(telefone, resultado.get("descricao", ""))
        return f"🗑️ *Lembrete removido!*\n\n📌 {lembrete['descricao'].capitalize()}" if lembrete else "❌ Lembrete não encontrado."

    if tipo == "remover_ultimo":
        gasto = remover_ultimo_gasto(telefone)
        return f"🗑️ *Gasto removido!*\n\n📌 {gasto['descricao'].capitalize()} — R$ {gasto['valor']:.2f}" if gasto else "📭 Nenhum gasto para remover."

    if tipo == "remover_item":
        gasto = remover_gasto_por_descricao(telefone, resultado.get("descricao", ""))
        return f"🗑️ *Gasto removido!*\n\n📌 {gasto['descricao'].capitalize()} — R$ {gasto['valor']:.2f}" if gasto else "❌ Gasto não encontrado."

    if tipo == "remover_categoria":
        gasto = remover_gasto_por_categoria(telefone, resultado.get("categoria", ""), resultado.get("valor"))
        return f"🗑️ *Gasto removido!*\n\n📌 {gasto['descricao'].capitalize()} — R$ {gasto['valor']:.2f} ({gasto['categoria']})" if gasto else f"❌ Nenhum gasto em {resultado.get('categoria', '')}."

    if tipo == "historico":
        return gerar_historico(telefone)

    return MENSAGEM_AJUDA

def extrair_texto(message):
    """Extrai o texto de uma mensagem da Evolution API (ou None se não for texto)."""
    if not message:
        return None
    if "conversation" in message:
        return message["conversation"]
    if "extendedTextMessage" in message:
        return message["extendedTextMessage"].get("text")
    return None

# ============================================================
# WEBHOOK
# ============================================================
_owner_jid = None

def obter_owner_jid():
    """Retorna o JID do dono da instância (usado para aceitar auto-mensagens)."""
    global _owner_jid
    if _owner_jid:
        return _owner_jid
    try:
        r = httpx.get(f"{EVOLUTION_URL}/instance/fetchInstances",
                      headers={"apikey": EVOLUTION_API_KEY}, timeout=10)
        for inst in r.json():
            if inst.get("instanceName") == EVOLUTION_INSTANCE:
                _owner_jid = inst.get("ownerJid")
                break
    except Exception as e:
        logger.warning(f"Não foi possível obter ownerJid: {e}")
    return _owner_jid

@app.post("/webhook")
async def webhook(request: Request):
    try:
        payload = await request.json()
    except Exception:
        return JSONResponse({"status": "payload inválido"}, status_code=400)

    if payload.get("event") != "messages.upsert":
        return {"status": "ignored"}

    data = payload.get("data", {})
    key = data.get("key", {})
    telefone = key.get("remoteJid", "").split("@")[0]
    if not telefone:
        return {"status": "ignored"}

    # Ignora mensagens enviadas pela própria instância, exceto auto-mensagens
    # (chat "mensagens com você mesmo"), que são como o dono testa o bot.
    if key.get("fromMe"):
        owner = obter_owner_jid() or ""
        if telefone != owner.split("@")[0]:
            return {"status": "ignored"}

    mensagem = extrair_texto(data.get("message", {}))
    if not mensagem:
        return {"status": "ignored"}
    mensagem = mensagem.strip()

    nome = data.get("pushName", "")
    eh_novo = registrar_usuario(telefone, nome)
    atualizar_atividade(telefone, nome)

    logger.info(f"Mensagem de {telefone} ({nome}): {mensagem}")

    if eh_novo:
        resposta = MENSAGEM_BEM_VINDO
    else:
        try:
            resposta = processar_mensagem(mensagem, telefone)
        except Exception as e:
            logger.error(f"Erro: {e}")
            resposta = "⚠️ Não entendi sua mensagem.\n\nMande 'ajuda' para ver os comandos disponíveis."

    enviar_whatsapp(telefone, resposta)
    return {"status": "ok"}

@app.get("/")
def health():
    return {"status": "Tino.IA rodando! 🐙", "instancia": EVOLUTION_INSTANCE}