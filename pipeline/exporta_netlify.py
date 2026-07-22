#!/usr/bin/env python3
"""
Exporta a plataforma como site 100% estático para publicação no Netlify.

Gera em plataforma/deploy/:
  - frontend (com window.API_STATIC = 1 injetado)
  - api/ufs.json                       {"T":[...], "PUB":[...], "PRIV":[...]}
  - api/municipios/{UF}.json           idem
  - api/escolas/{co_municipio}.json    lista (filtro de rede é client-side)
  - api/entidade/ESC/{chave}.json      {resumo, itens, hist_resumo, hist_scope}
  - api/entidade/{BR|UF|MUN}/{chave}.json  {"T":{resumo,itens,hist_resumo}, ...}
  - api/refs/{BR|UF}.json              {"T":{item:p}, …} p/ colunas UF·Brasil
  - api/historico/{BR|UF|MUN|ESC}/{chave}.json (lazy — itens por ano)
  - api/habilidades/index.json         heatmap cross-year (4×30×5)
  - api/habilidades/{area}/{h}.json    120 arquivos — card de cobertura

Itens compactos: [item, n, p, p_esp, habilidade, param_b, tp_lingua].

Uso:  python3 pipeline/exporta_netlify.py
"""
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_LATEST = os.path.join(BASE, "data", "enem2025.sqlite")
DB_HIST = os.path.join(BASE, "data", "enem_hist.sqlite")
WEB = os.path.join(BASE, "web")
OUT = os.path.join(BASE, "deploy")

DEPENDENCIA = {1: "Federal", 2: "Estadual", 3: "Municipal", 4: "Privada"}
REDES = ("T", "PUB", "PRIV")
ANOS = (2021, 2022, 2023, 2024, 2025)
ANOS_COM_ESCOLA = (2024, 2025)

HABILIDADES_JS = os.path.join(WEB, "habilidades.js")

t0 = time.time()


def log(msg):
    print(f"[{time.time() - t0:6.1f}s] {msg}", flush=True)


def jdump(caminho, obj):
    os.makedirs(os.path.dirname(caminho), exist_ok=True)
    with open(caminho, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))


def rnd(v, d=3):
    return None if v is None else round(float(v), d)


# ---------------------------------------------------------------- conexões
con = sqlite3.connect(DB_LATEST)
con.row_factory = sqlite3.Row

hist_con = None
if os.path.exists(DB_HIST):
    hist_con = sqlite3.connect(DB_HIST)
    hist_con.row_factory = sqlite3.Row
    log("enem_hist.sqlite disponível — emitindo série histórica")
else:
    log("enem_hist.sqlite AUSENTE — só o painel single-year será emitido")

# ---------------------------------------------------------------- frontend
log("Copiando frontend…")
if os.path.exists(OUT):
    shutil.rmtree(OUT)
shutil.copytree(WEB, OUT)
for arq in os.listdir(OUT):
    if not arq.endswith(".html"):
        continue
    p = os.path.join(OUT, arq)
    html = open(p, encoding="utf-8").read()
    if "window.API_STATIC" in html:
        continue      # já injetado (idempotente)
    if '<link rel="stylesheet" href="styles.css">' not in html:
        continue      # sem stylesheet → provavelmente não é página principal
    html = html.replace('<link rel="stylesheet" href="styles.css">',
                        '<link rel="stylesheet" href="styles.css">\n'
                        "<script>window.API_STATIC = 1;</script>")
    open(p, "w", encoding="utf-8").write(html)
with open(os.path.join(OUT, "netlify.toml"), "w") as f:
    f.write('[build]\n  publish = "."\n')

# ---------------------------------------------------------------- lookups (2025)
log("Carregando lookups do ano corrente (2025)…")
resumos = {(r["nivel"], str(r["chave"]), r["rede"]): dict(r)
           for r in con.execute("SELECT * FROM agg_resumo")}
escolas = {str(r["chave"]): dict(r) for r in con.execute("SELECT * FROM escolas")}
meta = {r["CO_ITEM"]: dict(r) for r in con.execute("SELECT * FROM itens_meta")}

# Distribuição de nota por (nivel, chave, rede, campo) — só existe pra BR e UF
# porque foi o escopo escolhido no build_db (municípios ficaram fora).
hist_nota = {}   # (nivel, chave, rede) -> {campo: {bucket: n}}
try:
    for r in con.execute("SELECT nivel, chave, rede, campo, bucket, n FROM agg_hist_nota"):
        key = (r["nivel"], str(r["chave"]), r["rede"])
        hist_nota.setdefault(key, {}).setdefault(r["campo"], {})[r["bucket"]] = r["n"]
    log(f"  hist_nota: {len(hist_nota):,} entidades")
except sqlite3.OperationalError:
    log("  (agg_hist_nota ausente — pule o histograma no export)")


def uf_de(nivel, chave):
    if nivel == "ESC":
        return escolas[chave]["uf"]
    if nivel == "MUN":
        r = resumos.get(("MUN", chave, "T"))
        return r["uf"] if r else None
    if nivel == "UF":
        return chave
    return None


def monta_resumo(nivel, chave, rede):
    alvo = resumos.get((nivel, chave, "T" if nivel == "ESC" else rede))
    if not alvo:
        return None
    alvo = dict(alvo)
    ctx = []
    if nivel == "ESC":
        e = dict(escolas[chave])
        if e["nome"]:
            alvo["nome"] = e["nome"]
        e["dependencia_nome"] = DEPENDENCIA.get(e["dependencia"], "")
        alvo["escola"] = e
        m = resumos.get(("MUN", str(e["co_municipio"]), rede))
        u = resumos.get(("UF", e["uf"], rede))
        ctx = [dict(x) for x in (m, u) if x]
    elif nivel == "MUN":
        u = resumos.get(("UF", alvo.get("uf") or "", rede))
        if u:
            ctx = [dict(u)]
    if nivel != "BR":
        br = resumos.get(("BR", "BR", rede))
        if br:
            ctx.append(dict(br))
    return {"alvo": alvo, "contexto": ctx}


# ---------------------------------------------------------------- histórico
#
# hist_por_entidade[(nivel, chave, rede)] = [{ano, n_participantes, ...}, ...]
# ordenado por ano crescente. Só carregado se enem_hist.sqlite existe.
hist_por_entidade = {}
FIELDS_HIST = ("n_participantes", "media_geral",
               "media_cn", "media_ch", "media_lc", "media_mt", "media_red",
               "media_comp1", "media_comp2", "media_comp3",
               "media_comp4", "media_comp5")

if hist_con is not None:
    log("Carregando série histórica em memória…")
    for r in hist_con.execute("""
        SELECT ano, nivel, chave, rede, n_participantes, media_geral,
               media_cn, media_ch, media_lc, media_mt, media_red,
               media_comp1, media_comp2, media_comp3, media_comp4, media_comp5
        FROM hist_resumo ORDER BY nivel, chave, rede, ano
    """):
        key = (r["nivel"], str(r["chave"]), r["rede"])
        item = {"ano": r["ano"]}
        for f in FIELDS_HIST:
            item[f] = r[f]
        if r["ano"] == 2021:
            item["flag_pandemia"] = True
        hist_por_entidade.setdefault(key, []).append(item)
    log(f"  {len(hist_por_entidade):,} timelines (nivel×chave×rede)")


def hist_para(nivel, chave, rede):
    return hist_por_entidade.get((nivel, str(chave), rede), [])


# ---------------------------------------------------------------- refs
log("Gerando referências UF/BR por rede (ano corrente)…")
refs = {}          # chave_ref -> {rede -> {item: p}}
for r in con.execute("""SELECT nivel, chave, rede, CO_ITEM, n, acertos
                        FROM agg_item WHERE nivel IN ('BR','UF')"""):
    refs.setdefault(str(r["chave"]), {}).setdefault(r["rede"], {})[
        r["CO_ITEM"]] = rnd(int(r["acertos"]) / r["n"])
for chave_ref, por_rede in refs.items():
    jdump(os.path.join(OUT, "api", "refs", f"{chave_ref}.json"), por_rede)

# ---------------------------------------------------------------- listas
log("Gerando ufs/municípios/escolas…")
CAMPOS_LISTA = ("chave", "nome", "n_participantes", "media_geral", "media_red",
                "media_lc", "media_ch", "media_cn", "media_mt")


def lista(nivel, filtro=None):
    out = {rv: [] for rv in REDES}
    for (nv, ch, rv), r in resumos.items():
        if nv == nivel and (filtro is None or filtro(r)):
            out[rv].append({k: r[k] for k in CAMPOS_LISTA})
    for rv in REDES:
        out[rv].sort(key=lambda x: x["nome"] or "")
    return out


jdump(os.path.join(OUT, "api", "ufs.json"), lista("UF"))
ufs_todas = {r["uf"] for (nv, _, _), r in resumos.items() if nv == "MUN"}
for uf in ufs_todas:
    jdump(os.path.join(OUT, "api", "municipios", f"{uf}.json"),
          lista("MUN", lambda r, u=uf: r["uf"] == u))

esc_por_mun = {}
for ch, e in escolas.items():
    r = resumos.get(("ESC", ch, "T"))
    if not r:
        continue
    dep = DEPENDENCIA.get(e["dependencia"], "")
    rotulo = (e["nome"] or f"Escola INEP {ch}") + (f" · {dep}" if dep else "")
    esc_por_mun.setdefault(str(e["co_municipio"]), []).append({
        "chave": ch, "nome": e["nome"], "dependencia": e["dependencia"],
        "n_participantes": e["n_participantes"],
        "media_geral": r["media_geral"], "rotulo": rotulo,
    })
for mun, lst in esc_por_mun.items():
    lst.sort(key=lambda x: -x["n_participantes"])
    jdump(os.path.join(OUT, "api", "escolas", f"{mun}.json"), lst)

# ---------------------------------------------------------------- top escolas
# Ranking das melhores escolas por (nivel, chave, rede), ordenado por média
# geral e cortado nas 30 primeiras com n_participantes >= 30 (evita ruído).
log("Gerando top escolas por BR/UF/MUN…")
TOP_N = 30
MIN_N = 30

def linha_esc(ch):
    e = escolas[ch]
    r = resumos.get(("ESC", ch, "T"))
    if not r or (r.get("n_participantes") or 0) < MIN_N:
        return None
    return {
        "chave": ch, "nome": e["nome"] or f"Escola INEP {ch}",
        "uf": e["uf"],
        "co_municipio": str(e["co_municipio"]),
        "municipio": e["municipio"],   # nome — só rótulo
        "dependencia": e["dependencia"],
        "dependencia_nome": DEPENDENCIA.get(e["dependencia"], ""),
        "n_participantes": r["n_participantes"],
        "media_geral": r["media_geral"], "media_red": r["media_red"],
        "media_lc": r["media_lc"], "media_ch": r["media_ch"],
        "media_cn": r["media_cn"], "media_mt": r["media_mt"],
    }

por_uf = {}
por_mun = {}
todas = []
for ch, e in escolas.items():
    linha = linha_esc(ch)
    if not linha:
        continue
    todas.append(linha)
    por_uf.setdefault(linha["uf"], []).append(linha)
    por_mun.setdefault(str(e["co_municipio"]), []).append(linha)

def top_por_rede(linhas):
    out = {}
    for rv in REDES:
        filtradas = linhas
        if rv == "PUB":
            filtradas = [x for x in linhas if x["dependencia"] != 4]
        elif rv == "PRIV":
            filtradas = [x for x in linhas if x["dependencia"] == 4]
        filtradas = sorted(filtradas, key=lambda x: -(x["media_geral"] or 0))
        out[rv] = filtradas[:TOP_N]
    return out

jdump(os.path.join(OUT, "api", "top_escolas", "BR.json"), top_por_rede(todas))
for uf, ls in por_uf.items():
    jdump(os.path.join(OUT, "api", "top_escolas", "UF", f"{uf}.json"),
          top_por_rede(ls))
for cod, ls in por_mun.items():
    jdump(os.path.join(OUT, "api", "top_escolas", "MUN", f"{cod}.json"),
          top_por_rede(ls))
log(f"  top escolas: 1 BR + {len(por_uf)} UFs + {len(por_mun)} municípios")

# Ranking completo (todas escolas com n>=30), sem filtro de rede — o cliente
# filtra por `dependencia`. Um arquivo por escopo. Usado na página dedicada.
def ordenadas(linhas):
    return sorted(linhas, key=lambda x: -(x["media_geral"] or 0))

jdump(os.path.join(OUT, "api", "top_escolas_full", "BR.json"), ordenadas(todas))
for uf, ls in por_uf.items():
    jdump(os.path.join(OUT, "api", "top_escolas_full", "UF", f"{uf}.json"),
          ordenadas(ls))
log(f"  top escolas full: {len(todas):,} escolas totais em BR + {len(por_uf)} UFs")

# ---------------------------------------------------------------- entidades
log("Gerando entidades (resumo + itens + hist_resumo)…")
n_ent = 0


def linhas_area_from_agg(linhas):
    """agrupa (CO_ITEM,n,acertos,esperado) em 7-tuplas por área."""
    por_area = {}
    for co, n, a, e in linhas:
        m = meta.get(co)
        if m:
            por_area.setdefault(m["area"], []).append((co, n, a, e, m))
    itens = {}
    for area, lst in por_area.items():
        n_max = max(x[1] for x in lst)
        lst = [x for x in lst if x[1] >= 0.25 * n_max]
        rows = [[co, n, rnd(a / n), rnd(e / n) if e is not None else None,
                 m["habilidade_inep"], rnd(m["param_b"], 2), m["tp_lingua"]]
                for co, n, a, e, m in lst]
        rows.sort(key=lambda x: x[2])
        itens[area] = rows
    return itens


def flush(nivel, chave, por_rede):
    global n_ent
    if nivel == "ESC":
        alvo = monta_resumo(nivel, chave, "T")
        doc = {
            "resumo": {
                "alvo": alvo["alvo"],
                "contexto_por_rede": {
                    rv: monta_resumo(nivel, chave, rv)["contexto"]
                    for rv in REDES},
            },
            "itens": linhas_area_from_agg(por_rede.get("T", [])),
        }
        h = hist_para("ESC", chave, "T")
        if h:
            doc["hist_resumo"] = h
        # Escolas só existem nos microdados a partir de 2024. Se o histórico
        # cobre menos que a janela completa, sinalizamos ao cliente pra ele
        # explicar isso na UI (sem furos silenciosos).
        anos_presentes = [x["ano"] for x in h]
        if anos_presentes and min(anos_presentes) > min(ANOS):
            doc["hist_scope"] = {
                "primeiro_ano_com_escola": min(anos_presentes),
                "nota": ("Antes de 2024 o INEP não expunha o código INEP "
                         "nos microdados; portanto o histórico da escola "
                         "começa em 2024."),
            }
    else:
        doc = {}
        for rv in REDES:
            if rv not in por_rede:
                continue
            resumo = monta_resumo(nivel, chave, rv)
            if resumo:
                bloco = {"resumo": resumo,
                         "itens": linhas_area_from_agg(por_rede[rv])}
                h = hist_para(nivel, chave, rv)
                if h:
                    bloco["hist_resumo"] = h
                # distribuição de nota (só BR e UF)
                hn = hist_nota.get((nivel, str(chave), rv))
                if hn:
                    bloco["hist_nota"] = hn
                doc[rv] = bloco
    jdump(os.path.join(OUT, "api", "entidade", nivel, f"{chave}.json"), doc)
    n_ent += 1
    if n_ent % 5000 == 0:
        log(f"  {n_ent:,} entidades…")


cur = con.execute("""SELECT nivel, chave, rede, CO_ITEM, n, acertos, esperado
                     FROM agg_item ORDER BY nivel, chave""")
atual, buf = None, {}
for r in cur:
    k = (r["nivel"], str(r["chave"]))
    if k != atual:
        if atual:
            flush(atual[0], atual[1], buf)
        atual, buf = k, {}
    buf.setdefault(r["rede"], []).append(
        (r["CO_ITEM"], r["n"], int(r["acertos"]), r["esperado"]))
if atual:
    flush(atual[0], atual[1], buf)

log(f"  total: {n_ent:,} entidades")

# ---------------------------------------------------------------- historico/
#
# Endpoint lazy: itens por ano (7-tuplas). Só BR/UF/MUN — não ESC (que só
# teria 2024/2025, e a UI de escola não muda de ano na tabela de itens).
#
# Refs BR/UF são emitidos em api/refs_hist/{ano}/{BR|UF/uf}.json para não
# replicar os mesmos ~180 números em cada arquivo de município.
if hist_con is not None:
    log("Gerando api/refs_hist/… (referências históricas por ano/rede)")
    refs_ano_dump = {}  # (ano, nivel, chave) -> {rede -> {CO_ITEM: p_acerto}}
    for r in hist_con.execute("""
        SELECT ano, nivel, chave, rede, CO_ITEM, p_acerto FROM hist_item
        WHERE nivel IN ('BR','UF')
    """):
        refs_ano_dump.setdefault(
            (r["ano"], r["nivel"], str(r["chave"])), {}
        ).setdefault(r["rede"], {})[r["CO_ITEM"]] = rnd(r["p_acerto"])
    for (ano, nivel, chave), por_rede in refs_ano_dump.items():
        sub = "BR.json" if nivel == "BR" else f"UF/{chave}.json"
        jdump(os.path.join(OUT, "api", "refs_hist", str(ano), sub), por_rede)
    # index leve, útil pro cliente saber quais anos existem
    jdump(os.path.join(OUT, "api", "refs_hist", "index.json"),
          {"anos": list(ANOS)})

    log("Gerando api/historico/… (itens por ano)")
    meta_all = {r["CO_ITEM"]: dict(r) for r in hist_con.execute(
        "SELECT CO_ITEM, area, habilidade_inep, param_a, param_b, param_c, tp_lingua FROM itens_meta_all")}

    def linhas_area_hist(itens):
        por_area = {}
        for co, n, p, pe in itens:
            m = meta_all.get(co)
            if not m:
                continue
            por_area.setdefault(m["area"], []).append((co, n, p, pe, m))
        out = {}
        for area, lst in por_area.items():
            n_max = max(x[1] for x in lst)
            lst = [x for x in lst if x[1] >= 0.25 * n_max]
            rows = [[co, n, rnd(p), rnd(pe),
                     m["habilidade_inep"], rnd(m["param_b"], 2), m["tp_lingua"]]
                    for co, n, p, pe, m in lst]
            rows.sort(key=lambda x: x[2] if x[2] is not None else -1)
            out[area] = rows
        return out

    hcur = hist_con.execute("""
        SELECT ano, nivel, chave, rede, CO_ITEM, n, p_acerto, p_esp
        FROM hist_item
        WHERE nivel IN ('BR','UF','MUN')
        ORDER BY nivel, chave, rede, ano
    """)
    n_hist = 0
    atual = None
    buf = {}

    def flush_hist(nivel, chave):
        global n_hist
        if not buf:
            return
        tem_multiano = any(len(a.keys()) >= 2 for a in buf.values())
        if not tem_multiano:
            return
        doc = {"uf": uf_de(nivel, chave)}
        for rv, ano_map in buf.items():
            por_ano = {}
            for ano, itens in ano_map.items():
                por_ano[str(ano)] = linhas_area_hist(itens)
            doc[rv] = {"por_ano": por_ano}
        jdump(os.path.join(OUT, "api", "historico", nivel, f"{chave}.json"), doc)
        n_hist += 1
        if n_hist % 2000 == 0:
            log(f"  historico: {n_hist:,} entidades…")

    for r in hcur:
        k = (r["nivel"], str(r["chave"]))
        if k != atual:
            if atual is not None:
                flush_hist(*atual)
            atual, buf = k, {}
        buf.setdefault(r["rede"], {}).setdefault(r["ano"], []).append(
            (r["CO_ITEM"], r["n"], r["p_acerto"], r["p_esp"]))
    if atual is not None:
        flush_hist(*atual)
    log(f"  historico: {n_hist:,} arquivos emitidos")

# ---------------------------------------------------------------- habilidades
if hist_con is not None:
    log("Gerando api/habilidades/index.json + per-skill…")

    descs = {"LC": {}, "CH": {}, "CN": {}, "MT": {}}
    # habilidades.js → carrega descrições para embutir na resposta
    if os.path.exists(HABILIDADES_JS):
        import re
        raw = open(HABILIDADES_JS, encoding="utf-8").read()
        try:
            data = raw.split("=", 1)[1].strip().rstrip(";")
            # o arquivo usa aspas duplas em keys — é JSON válido a menos
            # do trailing 'window.HABILIDADES ='; se falhar, seguimos sem desc.
            descs_load = json.loads(data)
            if isinstance(descs_load, dict):
                for area, hs in descs_load.items():
                    if area in descs:
                        for h, desc in hs.items():
                            descs[area][int(h)] = desc
        except Exception as e:
            log(f"  (aviso) não consegui parsear habilidades.js: {e}")

    # index cross-year — recalculado direto do hist_item pra aplicar o filtro
    # de caderno majoritário (`n >= 0.25 * n_max` por ano/área). Caso contrário,
    # itens de reaplicação e provas adaptadas dobrariam a contagem.
    idx = {"anos": list(ANOS), "areas": {"LC": {}, "CH": {}, "CN": {}, "MT": {}},
           "totais_por_ano": {}}
    for ano in ANOS:
        idx["totais_por_ano"][str(ano)] = {"LC": 0, "CH": 0, "CN": 0, "MT": 0}

    itens_br = list(hist_con.execute("""
        SELECT hi.ano, im.area, im.habilidade_inep AS h, hi.CO_ITEM,
               hi.n, hi.p_acerto
        FROM hist_item hi
        JOIN itens_meta_all im ON im.CO_ITEM = hi.CO_ITEM
        WHERE hi.nivel='BR' AND hi.rede='T'
    """))
    n_max_por = {}   # (ano, area) -> max(n)
    for r in itens_br:
        k = (r["ano"], r["area"])
        if r["n"] > n_max_por.get(k, 0):
            n_max_por[k] = r["n"]
    # bucket por (ano, area, h) com filtro aplicado
    buckets = {}
    for r in itens_br:
        n_max = n_max_por[(r["ano"], r["area"])]
        if r["n"] < 0.25 * n_max:
            continue
        key = (r["ano"], r["area"], int(r["h"]))
        buckets.setdefault(key, []).append((r["n"], r["p_acerto"]))
    for (ano, area, h), lst in buckets.items():
        cell = idx["areas"][area].setdefault(str(h), {
            "cob": [0] * len(ANOS),
            "p":   [None] * len(ANOS),
            "desc": descs.get(area, {}).get(h, ""),
        })
        i = ANOS.index(ano)
        cell["cob"][i] = len(lst)
        total_n = sum(x[0] for x in lst)
        total_acc = sum(x[0] * x[1] for x in lst if x[1] is not None)
        cell["p"][i] = rnd(total_acc / total_n) if total_n else None
        idx["totais_por_ano"][str(ano)][area] += len(lst)
    jdump(os.path.join(OUT, "api", "habilidades", "index.json"), idx)

    # per-skill drill-down (120 arquivos)
    # 1) coletar itens_meta_all
    itens_by_hab = {}   # (area, h) -> list of dict(CO_ITEM, param_b, anos)
    for r in hist_con.execute("""
        SELECT CO_ITEM, area, habilidade_inep AS h, param_b, tp_lingua, anos
        FROM itens_meta_all
    """):
        if r["area"] and r["h"] is not None:
            itens_by_hab.setdefault((r["area"], int(r["h"])), []).append({
                "CO_ITEM": r["CO_ITEM"],
                "param_b": rnd(r["param_b"], 2),
                "tp_lingua": r["tp_lingua"],
                "anos": [int(x) for x in (r["anos"] or "").split(",") if x],
            })

    # 2) desempenho por (area, h, ano) — reusa itens_br + n_max_por já
    #    computados (com o filtro de caderno majoritário aplicado).
    per_year_items = {}  # (area, h, ano) -> list of {CO_ITEM, param_b, p_br, n_br}
    for r in itens_br:
        n_max = n_max_por[(r["ano"], r["area"])]
        if r["n"] < 0.25 * n_max:
            continue
        per_year_items.setdefault(
            (r["area"], int(r["h"]), r["ano"]), []
        ).append({
            "CO_ITEM": r["CO_ITEM"],
            "param_b": None,
            "p_br": rnd(r["p_acerto"]),
            "n_br": int(r["n"]),
        })

    # popular param_b via meta_all
    param_b_by_item = {}
    for lst in itens_by_hab.values():
        for it in lst:
            param_b_by_item[it["CO_ITEM"]] = it["param_b"]
    for lst in per_year_items.values():
        for it in lst:
            it["param_b"] = param_b_by_item.get(it["CO_ITEM"])

    # 3) para cada (area, h) escrever um JSON
    n_hab = 0
    for area in ("LC", "CH", "CN", "MT"):
        for h in range(1, 31):
            key = (area, h)
            desc = descs.get(area, {}).get(h, "")
            por_ano = {}
            for ano in ANOS:
                itens_ano = per_year_items.get((area, h, ano), [])
                itens_ano_ord = sorted(
                    itens_ano, key=lambda x: (x["p_br"] if x["p_br"] is not None else 2))
                if itens_ano_ord:
                    total_n = sum(it["n_br"] for it in itens_ano_ord)
                    total_acertos = sum(
                        int(it["p_br"] * it["n_br"]) for it in itens_ano_ord
                        if it["p_br"] is not None)
                    media_p = rnd(total_acertos / total_n) if total_n else None
                    por_ano[str(ano)] = {
                        "n_itens": len(itens_ano_ord),
                        "n_participantes_br": total_n,
                        "media_p_acerto_br": media_p,
                        "itens": [
                            {"CO_ITEM": it["CO_ITEM"],
                             "param_b": it["param_b"],
                             "p_br": it["p_br"]}
                            for it in itens_ano_ord
                        ],
                    }
                else:
                    por_ano[str(ano)] = {
                        "n_itens": 0, "n_participantes_br": 0,
                        "media_p_acerto_br": None, "itens": []}
            # itens recorrentes: apareceram em mais de um ano
            recorrentes = []
            for it in itens_by_hab.get(key, []):
                if len(it["anos"]) >= 2:
                    recorrentes.append({
                        "CO_ITEM": it["CO_ITEM"],
                        "anos": it["anos"],
                        "param_b": it["param_b"],
                    })
            doc = {"area": area, "h": h, "desc": desc,
                   "por_ano": por_ano,
                   "itens_recorrentes": recorrentes}
            jdump(os.path.join(OUT, "api", "habilidades", area, f"{h}.json"), doc)
            n_hab += 1
    log(f"  habilidades: index + {n_hab} per-skill")

# ---------------------------------------------------------------- resumo
con.close()
if hist_con is not None:
    hist_con.close()

# Rebuild das imagens das questões (as pastas questoes/ e api/questoes/ foram
# apagadas pelo shutil.rmtree do começo — precisamos regerá-las). Se o script
# ou dependências (pdftoppm, cwebp) estiverem ausentes, seguimos sem quebrar.
try:
    script = os.path.join(BASE, "pipeline", "build_questoes_img.py")
    if os.path.exists(script):
        log("Regerando imagens das questões (build_questoes_img.py)…")
        r = subprocess.run([sys.executable, script, "--ano", "2025"],
                           capture_output=True, text=True, cwd=BASE)
        if r.returncode == 0:
            log("  imagens ok")
        else:
            log(f"  (aviso) falha ao gerar imagens: {r.stderr.strip()[:200]}")
except Exception as e:
    log(f"  (aviso) skip questoes img: {e}")

total, n_arq = 0, 0
for raiz, _, arquivos in os.walk(OUT):
    for a in arquivos:
        total += os.path.getsize(os.path.join(raiz, a))
        n_arq += 1
log(f"OK — {n_ent:,} entidades, {n_arq:,} arquivos, {total / 1e6:,.0f} MB em {OUT}")
