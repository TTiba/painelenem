#!/usr/bin/env python3
"""Gera deploy_d1/ — PRÉVIA do painel nacional com o p_esp recalculado em D=1.

O rebuild definitivo (build_all_years.py + exporta_netlify.py, com o D=1 já
corrigido no build_db.py) recalcula o p_esp aluno a aluno a partir dos
microdados. Esta prévia NÃO substitui isso: ela reprocessa os JSONs já
publicados, recalculando o p_esp dos itens de TODOS os anos (2021-2025) a partir dos
parâmetros oficiais (a, b, c) e da distribuição de notas (hist_nota, 25 pts)
que cada entidade já carrega. Método validado no painel PR contra os θ exatos
de uma escola reconstruída dos microdados: 0,02 pp de erro agregado.

Escopo: BR + as 27 UFs (entidade + bloco 2025 do historico). Municípios e
escolas não têm hist_nota no deploy nacional — mantêm o valor antigo (a
variante PR cobre municípios e escolas do PR via hist_nota_pr.json).
Itens de língua estrangeira ficam null (a UI mostra "–"): não há distribuição
de θ por língua. Os parâmetros vêm de pipeline/params_itens.json, consolidado
dos ITENS_PROVA_{ano}.csv (todos os anos) — arquivos de ~300 KB, não os
microdados de resultados.

Atenção sobre a série histórica: a distribuição de θ usada é a do ANO CORRENTE
(hist_nota do deploy é de 2025). Para 2021-2024 isso é uma aproximação — o
esperado daqueles anos sai calculado sobre o perfil de alunos de 2025. Serve
pra ver a ordem de grandeza e a direção da correção, não como número final;
o definitivo sai do rebuild, que usa o θ real de cada ano.

Uso:  python3 pipeline/gera_preview_d1.py
      cd deploy_d1 && python3 -m http.server 9100
"""
import glob
import json
import math
import os
import shutil
import sys
import time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEPLOY = os.path.join(BASE, "deploy")
OUT = os.path.join(BASE, "deploy_d1")
PARAMS_PATH = os.path.join(BASE, "pipeline", "params_itens.json")
ANOS = ("2021", "2022", "2023", "2024", "2025")

BANNER = (
    '<div style="position:sticky;top:0;z-index:9999;background:#5b21b6;color:#fff;'
    'padding:8px 16px;font:600 13px system-ui;text-align:center">'
    "\U0001f9ea PRÉVIA · p_esp recalculado com D=1 na 3PL · BR e UFs, 2021-2025 · "
    "municípios/escolas mantêm o valor antigo · θ dos anos antigos aproximado · "
    "a versão definitiva sai do rebuild completo</div>"
)


def p3pl(a, b, c, th):
    return c + (1 - c) / (1 + math.exp(-a * (th - b)))


def grade(hist_campo):
    """{bucket: n} → [(theta, peso)] ignorando a cauda no bucket 0."""
    pares = [(int(k), n) for k, n in hist_campo.items() if int(k) >= 200]
    tot = sum(n for _, n in pares)
    if not tot:
        return None
    return [((k + 12.5 - 500) / 100, n / tot) for k, n in pares]


def corrigir(rows, grades_por_area, params, stats):
    for area, lst in rows.items():
        g = grades_por_area.get(area)
        if not g:
            continue
        for arr in lst:
            prm = params.get(str(arr[0]))
            if arr[3] is None or prm is None:
                continue
            lingua = arr[6] if len(arr) > 6 else None
            if lingua is not None:          # LEM: sem distribuição por língua
                arr[3] = None
                stats[1] += 1
                continue
            a, b, c = prm
            arr[3] = round(sum(w * p3pl(a, b, c, t) for t, w in g), 3)
            stats[0] += 1


def patch(caminho, params, stats):
    doc = json.load(open(caminho, encoding="utf-8"))
    for rede in ("T", "PUB", "PRIV"):
        bloco = doc.get(rede)
        if not isinstance(bloco, dict):
            continue
        hn = bloco.get("hist_nota")
        if not hn:
            continue
        grades = {a: grade(hn.get(a.lower(), {})) for a in ("CN", "CH", "LC", "MT")}
        if "itens" in bloco:
            corrigir(bloco["itens"], grades, params, stats)
        for ano in ANOS:
            lst = bloco.get("por_ano", {}).get(ano)
            if lst:
                corrigir(lst, grades, params, stats)
    os.remove(caminho)                       # quebra o hardlink
    json.dump(doc, open(caminho, "w", encoding="utf-8"),
              ensure_ascii=False, separators=(",", ":"))


def main():
    if not os.path.exists(PARAMS_PATH):
        sys.exit(f"faltam os parâmetros dos itens: {PARAMS_PATH}")
    params = json.load(open(PARAMS_PATH))
    t0 = time.time()
    print(f"Clonando {DEPLOY} → {OUT} (hardlinks)…")
    if os.path.exists(OUT):
        shutil.rmtree(OUT)
    shutil.copytree(DEPLOY, OUT, copy_function=os.link)

    stats = [0, 0]
    alvos = ([os.path.join(OUT, "api", "entidade", "BR", "BR.json")]
             + sorted(glob.glob(os.path.join(OUT, "api", "entidade", "UF", "*.json"))))
    print(f"Recalculando p_esp (D=1) de {len(alvos)} entidades…")
    for c in alvos:
        patch(c, params, stats)
    # historico: BR + UFs, todos os anos (as distribuições vêm da entidade)
    hist_alvos = ([os.path.join(OUT, "api", "historico", "BR", "BR.json")]
                  + sorted(glob.glob(os.path.join(OUT, "api", "historico", "UF", "*.json"))))
    for h in hist_alvos:
        if not os.path.exists(h):
            continue
        ent = h.replace(os.path.join("api", "historico"), os.path.join("api", "entidade"))
        if not os.path.exists(ent):
            continue
        doc_e = json.load(open(ent, encoding="utf-8"))
        doc_h = json.load(open(h, encoding="utf-8"))
        for rede in ("T", "PUB", "PRIV"):
            hn = doc_e.get(rede, {}).get("hist_nota")
            if not hn:
                continue
            grades = {a: grade(hn.get(a.lower(), {})) for a in ("CN", "CH", "LC", "MT")}
            for ano in ANOS:
                lst = doc_h.get(rede, {}).get("por_ano", {}).get(ano)
                if lst:
                    corrigir(lst, grades, params, stats)
        os.remove(h)
        json.dump(doc_h, open(h, "w", encoding="utf-8"),
                  ensure_ascii=False, separators=(",", ":"))
    print(f"  {stats[0]} itens recalculados · {stats[1]} anulados (língua estrangeira)")

    print("Injetando banner…")
    for f in os.listdir(OUT):
        if not f.endswith(".html"):
            continue
        c = os.path.join(OUT, f)
        html = open(c, encoding="utf-8").read()
        if "PRÉVIA" in html:
            continue
        html = html.replace("<body>", "<body>\n" + BANNER, 1)
        html = html.replace("<title>", "<title>[PRÉVIA D=1] ", 1)
        os.remove(c)
        open(c, "w", encoding="utf-8").write(html)
    print(f"✓ pronto em {time.time()-t0:.0f}s — cd deploy_d1 && python3 -m http.server 9100")


if __name__ == "__main__":
    main()
