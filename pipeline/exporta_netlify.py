#!/usr/bin/env python3
"""
Exporta a plataforma como site 100% estático para publicação no Netlify.

Gera em plataforma/deploy/:
  - frontend (com window.API_STATIC = 1 injetado)
  - api/ufs.json                       {"T":[...], "PUB":[...], "PRIV":[...]}
  - api/municipios/{UF}.json           idem
  - api/escolas/{co_municipio}.json    lista (filtro de rede é client-side)
  - api/entidade/ESC/{chave}.json      {resumo:{alvo, contexto_por_rede}, itens}
  - api/entidade/{BR|UF|MUN}/{chave}.json  {"T":{resumo,itens}, "PUB":…, "PRIV":…}
  - api/refs/{BR|UF}.json              {"T":{item:p}, …} p/ colunas UF·Brasil

Itens como arrays compactos: [item, n, p, p_esp, habilidade, param_b, tp_lingua]
(referências UF/BR são juntadas no cliente a partir de api/refs/).

Uso:  python3 pipeline/exporta_netlify.py
"""
import json
import os
import shutil
import sqlite3
import time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(BASE, "data", "enem2025.sqlite")
WEB = os.path.join(BASE, "web")
OUT = os.path.join(BASE, "deploy")

DEPENDENCIA = {1: "Federal", 2: "Estadual", 3: "Municipal", 4: "Privada"}
REDES = ("T", "PUB", "PRIV")
t0 = time.time()


def log(msg):
    print(f"[{time.time() - t0:6.1f}s] {msg}", flush=True)


def jdump(caminho, obj):
    os.makedirs(os.path.dirname(caminho), exist_ok=True)
    with open(caminho, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))


def rnd(v, d=3):
    return None if v is None else round(float(v), d)


con = sqlite3.connect(DB)
con.row_factory = sqlite3.Row

# ---------------------------------------------------------------- frontend
log("Copiando frontend…")
if os.path.exists(OUT):
    shutil.rmtree(OUT)
shutil.copytree(WEB, OUT)
for pagina in ("index.html", "mapa.html"):
    p = os.path.join(OUT, pagina)
    html = open(p, encoding="utf-8").read()
    html = html.replace('<link rel="stylesheet" href="styles.css">',
                        '<link rel="stylesheet" href="styles.css">\n'
                        "<script>window.API_STATIC = 1;</script>")
    open(p, "w", encoding="utf-8").write(html)
with open(os.path.join(OUT, "netlify.toml"), "w") as f:
    f.write('[build]\n  publish = "."\n')

# ---------------------------------------------------------------- lookups
log("Carregando lookups…")
resumos = {(r["nivel"], str(r["chave"]), r["rede"]): dict(r)
           for r in con.execute("SELECT * FROM agg_resumo")}
escolas = {str(r["chave"]): dict(r) for r in con.execute("SELECT * FROM escolas")}
meta = {r["CO_ITEM"]: dict(r) for r in con.execute("SELECT * FROM itens_meta")}


def uf_de(nivel, chave):
    if nivel == "ESC":
        return escolas[chave]["uf"]
    if nivel == "MUN":
        return resumos[("MUN", chave, "T")]["uf"]
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


# ---------------------------------------------------------------- refs
log("Gerando referências UF/BR por rede…")
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

# ---------------------------------------------------------------- entidades
log("Gerando entidades (resumo + itens)… é a etapa longa")
n_ent = 0


def linhas_area(linhas):
    """agrupa (CO_ITEM,n,acertos,esperado) por área com filtro de caderno"""
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
        doc = {
            "resumo": {
                "alvo": monta_resumo(nivel, chave, "T")["alvo"],
                "contexto_por_rede": {
                    rv: monta_resumo(nivel, chave, rv)["contexto"]
                    for rv in REDES},
            },
            "itens": linhas_area(por_rede.get("T", [])),
        }
    else:
        doc = {}
        for rv in REDES:
            if rv not in por_rede:
                continue
            resumo = monta_resumo(nivel, chave, rv)
            if resumo:
                doc[rv] = {"resumo": resumo,
                           "itens": linhas_area(por_rede[rv])}
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

con.close()

# ---------------------------------------------------------------- resumo
total, n_arq = 0, 0
for raiz, _, arquivos in os.walk(OUT):
    for a in arquivos:
        total += os.path.getsize(os.path.join(raiz, a))
        n_arq += 1
log(f"OK — {n_ent:,} entidades, {n_arq:,} arquivos, {total / 1e6:,.0f} MB em {OUT}")
