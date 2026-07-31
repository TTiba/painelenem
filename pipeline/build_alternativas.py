#!/usr/bin/env python3
"""Calcula, por item, o percentual que marcou cada alternativa (A–E e branco).

POR QUE UM SCRIPT SEPARADO, e não uma coluna no build_db.py: o build_db
recalcula o p_esp, e o painel do Paraná está publicado com D=1,7 por decisão
(as análises do ano já foram fechadas em cima daqueles números). Este script
NÃO toca em nenhum agregado, em nenhum JSON de entidade e em nenhum SQLite —
ele só acrescenta campos ao api/questoes/{ano}.json. O p_esp publicado fica
byte a byte como está.

O TX_RESPOSTAS não é persistido no SQLite (só os agregados são), então é
preciso uma passada nos microdados. É uma passada leve: poucas colunas, um
GROUP BY, sem os rollups do build completo.

Escreve em cada item de api/questoes/{ano}.json:
    "gab": "C"                      letra do gabarito
    "alt": [nA, nB, nC, nD, nE, nBranco]   contagens absolutas
    "alt_n": 71234                  total de respondentes considerados
A UI calcula o percentual e destaca a correta. Contagens em vez de percentuais
pra que quem lê possa recompor qualquer razão sem perder precisão.

População: a mesma que o painel usa pro acerto observado (mesmos filtros de
presença, conclusão e língua do build_db), pra que os percentuais fechem com
o "% de acerto" já exibido. --uf restringe a um estado.

Uso:
    python3 pipeline/build_alternativas.py --deploy deploy
    python3 pipeline/build_alternativas.py --deploy pr2_deploy --uf PR
    python3 pipeline/build_alternativas.py --deploy pr2_deploy --uf PR --anos 2025
"""
import argparse
import json
import os
import sys
import time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AREAS = [("LC", 0), ("CH", 45), ("CN", 90), ("MT", 135)]
LETRAS = ("A", "B", "C", "D", "E")


def log(m):
    print(m, flush=True)


def dados_de(ano):
    d = os.path.join(os.path.dirname(BASE), f"microdados_enem_{ano}", "DADOS")
    return d if os.path.isdir(d) else None


def um_ano(con, ano, dados, uf):
    itens_csv = os.path.join(dados, f"ITENS_PROVA_{ano}.csv")
    novo = os.path.join(dados, f"RESULTADOS_{ano}.csv")
    antigo = os.path.join(dados, f"MICRODADOS_ENEM_{ano}.csv")
    resultados = novo if os.path.exists(novo) else antigo
    if not os.path.exists(itens_csv) or not os.path.exists(resultados):
        log(f"! {ano}: CSV ausente em {dados}, pulando")
        return None
    tem_co_escola = ano >= 2024

    con.execute("DROP TABLE IF EXISTS itens; DROP TABLE IF EXISTS res")
    con.execute(f"""
        CREATE TABLE itens AS
        SELECT * FROM read_csv('{itens_csv}', delim=';', header=true,
                               encoding='latin-1', sample_size=-1)
        WHERE IN_ITEM_ABAN = 0
    """)
    con.execute("""
        ALTER TABLE itens ADD COLUMN pos INTEGER;
        UPDATE itens SET pos = CO_POSICAO - CASE SG_AREA
            WHEN 'LC' THEN 0 WHEN 'CH' THEN 45 WHEN 'CN' THEN 90 ELSE 135 END;
    """)

    # mesmos filtros de população do build_db.py, pra fechar com o "p" exibido
    if tem_co_escola:
        filtro = "CO_ESCOLA IS NOT NULL"
    else:
        filtro = ("TP_ST_CONCLUSAO = 2 AND IN_TREINEIRO = 0 "
                  "AND CO_MUNICIPIO_ESC IS NOT NULL "
                  "AND TP_PRESENCA_LC = 1 AND TP_PRESENCA_MT = 1")
    if uf:
        filtro += f" AND SG_UF_ESC = '{uf}'"

    log(f"  lendo {os.path.basename(resultados)}…")
    con.execute(f"""
        CREATE TABLE res AS
        SELECT SG_UF_ESC, TP_LINGUA,
               TP_PRESENCA_CN, TP_PRESENCA_CH, TP_PRESENCA_LC, TP_PRESENCA_MT,
               CO_PROVA_CN, CO_PROVA_CH, CO_PROVA_LC, CO_PROVA_MT,
               NU_NOTA_CN, NU_NOTA_CH, NU_NOTA_LC, NU_NOTA_MT,
               TX_RESPOSTAS_CN, TX_RESPOSTAS_CH, TX_RESPOSTAS_LC, TX_RESPOSTAS_MT
        FROM read_csv('{resultados}', delim=';', header=true,
                      encoding='latin-1', sample_size=-1)
        WHERE {filtro}
    """)
    n = con.execute("SELECT count(*) FROM res").fetchone()[0]
    log(f"  {n:,} alunos na população")
    if not n:
        return None

    partes = []
    for area, _ in AREAS:
        lingua = ("AND (i.TP_LINGUA IS NULL OR i.TP_LINGUA = r.TP_LINGUA)"
                  if area == "LC" else "")
        partes.append(f"""
            SELECT i.CO_ITEM,
                   any_value(i.TX_GABARITO) AS gab,
                   substr(r.TX_RESPOSTAS_{area}, i.pos, 1) AS marcada,
                   count(*) AS n
            FROM res r
            JOIN itens i ON i.CO_PROVA = r.CO_PROVA_{area} AND i.SG_AREA = '{area}'
            WHERE r.TP_PRESENCA_{area} = 1 AND r.TX_RESPOSTAS_{area} IS NOT NULL
              AND r.NU_NOTA_{area} IS NOT NULL
              {lingua}
            GROUP BY i.CO_ITEM, marcada
        """)
    log("  contando alternativas…")
    rows = con.execute(" UNION ALL ".join(partes)).fetchall()

    por_item = {}
    for co_item, gab, marcada, n in rows:
        d = por_item.setdefault(str(co_item), {"gab": gab, "c": [0] * 6, "n": 0})
        k = LETRAS.index(marcada) if marcada in LETRAS else 5   # 5 = branco/inválido
        d["c"][k] += n
        d["n"] += n
    log(f"  {len(por_item)} itens")
    return por_item


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--deploy", default="deploy",
                    help="pasta do deploy a anotar (deploy ou pr2_deploy)")
    ap.add_argument("--uf", default=None, help="restringe a um estado, ex. PR")
    ap.add_argument("--anos", type=int, nargs="+",
                    default=[2021, 2022, 2023, 2024, 2025])
    a = ap.parse_args()

    try:
        import duckdb
    except ImportError:
        sys.exit("precisa do duckdb: pip install duckdb  (o build_db.py já usa)")

    alvo = os.path.join(BASE, a.deploy, "api", "questoes")
    if not os.path.isdir(alvo):
        sys.exit(f"não achei {alvo}")

    t0 = time.time()
    con = duckdb.connect()
    escopo = a.uf or "Brasil"
    for ano in a.anos:
        dados = dados_de(ano)
        if not dados:
            log(f"! {ano}: microdados ausentes, pulando")
            continue
        caminho = os.path.join(alvo, f"{ano}.json")
        if not os.path.exists(caminho):
            log(f"! {ano}: {caminho} não existe, pulando")
            continue
        log(f"\n=== {ano} · {escopo} ===")
        por_item = um_ano(con, ano, dados, a.uf)
        if not por_item:
            continue
        doc = json.load(open(caminho, encoding="utf-8"))
        casados = 0
        for co_item, q in doc.get("itens", {}).items():
            d = por_item.get(co_item)
            if not d or not d["n"]:
                continue
            q["gab"] = d["gab"]
            q["alt"] = d["c"]
            q["alt_n"] = d["n"]
            casados += 1
        json.dump(doc, open(caminho, "w", encoding="utf-8"),
                  ensure_ascii=False, separators=(",", ":"))
        log(f"  anotados {casados}/{len(doc.get('itens', {}))} itens em {caminho}")
    con.close()
    log(f"\n✓ {time.time()-t0:.0f}s — só api/questoes/ foi alterado; "
        f"nenhum agregado, entidade ou SQLite tocado")


if __name__ == "__main__":
    main()
