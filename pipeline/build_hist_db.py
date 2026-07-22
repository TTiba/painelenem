#!/usr/bin/env python3
"""
Consolida os SQLites por ano (data/enem20XX.sqlite) num único
data/enem_hist.sqlite com o rollup cross-year usado pelo exporter.

Tabelas:
- hist_resumo(ano, nivel, chave, rede, ...) — timeline por entidade × rede
- hist_item(ano, nivel, chave, rede, CO_ITEM, n, p_acerto, p_esp)
- hist_hab(ano, area, h, n_itens, n_amostra, media_p_acerto)
- itens_meta_all(CO_ITEM, area, habilidade_inep, param_a/b/c, tp_lingua, anos)

Uso: .venv/bin/python pipeline/build_hist_db.py
"""
import argparse
import os
import sqlite3
import time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_ANOS = [2021, 2022, 2023, 2024, 2025]


def build_hist(anos, db_out):
    t0 = time.time()
    def log(m):
        print(f"[hist · {time.time()-t0:5.1f}s] {m}", flush=True)

    fontes = [(a, os.path.join(BASE, "data", f"enem{a}.sqlite")) for a in anos]
    for a, f in fontes:
        if not os.path.exists(f):
            raise SystemExit(f"faltando: {f}")

    if os.path.exists(db_out):
        os.remove(db_out)
    con = sqlite3.connect(db_out)

    for a, f in fontes:
        con.execute(f"ATTACH DATABASE '{f}' AS y{a}")
    log(f"anos anexados: {', '.join(str(a) for a,_ in fontes)}")

    # ---------------- hist_resumo
    log("hist_resumo…")
    parts = [
        f"""SELECT {a} AS ano, nivel, chave, rede, nome, uf,
                   n_participantes, media_geral,
                   media_cn, media_ch, media_lc, media_mt, media_red,
                   media_comp1, media_comp2, media_comp3, media_comp4, media_comp5
            FROM y{a}.agg_resumo""" for a, _ in fontes
    ]
    con.executescript(
        "CREATE TABLE hist_resumo AS " + " UNION ALL ".join(parts) + ";"
    )
    n = con.execute("SELECT count(*) FROM hist_resumo").fetchone()[0]
    log(f"  {n:,} rows")

    # ---------------- hist_item (com p_acerto e p_esp médios calculados)
    log("hist_item…")
    parts = [
        f"""SELECT {a} AS ano, nivel, chave, rede, CO_ITEM,
                   n,
                   CASE WHEN n>0 THEN CAST(acertos AS REAL)/n END AS p_acerto,
                   CASE WHEN n>0 THEN esperado/n END AS p_esp
            FROM y{a}.agg_item WHERE n>0""" for a, _ in fontes
    ]
    con.executescript(
        "CREATE TABLE hist_item AS " + " UNION ALL ".join(parts) + ";"
    )
    n = con.execute("SELECT count(*) FROM hist_item").fetchone()[0]
    log(f"  {n:,} rows")

    # ---------------- hist_hab
    #
    # Contagem de itens e média de acerto por habilidade × área × ano,
    # medida em BR × rede='T' (rede-agnóstico p/ o número de itens no exame;
    # p_acerto BR ponderado por n).
    log("hist_hab…")
    parts = [
        f"""SELECT {a} AS ano, im.area, im.habilidade_inep AS h,
                   count(*) AS n_itens,
                   sum(ai.n) AS n_amostra,
                   sum(ai.acertos)*1.0 / NULLIF(sum(ai.n),0) AS media_p_acerto
            FROM y{a}.agg_item ai
            JOIN y{a}.itens_meta im ON im.CO_ITEM = ai.CO_ITEM
            WHERE ai.nivel='BR' AND ai.rede='T'
            GROUP BY im.area, im.habilidade_inep""" for a, _ in fontes
    ]
    con.executescript(
        "CREATE TABLE hist_hab AS " + " UNION ALL ".join(parts) + ";"
    )
    n = con.execute("SELECT count(*) FROM hist_hab").fetchone()[0]
    log(f"  {n:,} rows")

    # ---------------- itens_meta_all
    #
    # Union das metas — mesmo CO_ITEM pode reaparecer entre anos com params
    # potencialmente ligeiramente diferentes por recalibração. Guardamos os
    # do ano mais recente (max ano) e a lista de anos como CSV.
    log("itens_meta_all…")
    union_meta = " UNION ALL ".join(
        f"SELECT {a} AS ano, CO_ITEM, area, habilidade_inep, param_a, param_b, param_c, tp_lingua FROM y{a}.itens_meta"
        for a, _ in fontes
    )
    con.executescript(f"""
        CREATE TABLE _meta_union AS {union_meta};
        CREATE TABLE itens_meta_all AS
        WITH latest AS (
            SELECT CO_ITEM, max(ano) AS ano_max FROM _meta_union GROUP BY CO_ITEM
        )
        SELECT m.CO_ITEM, m.area, m.habilidade_inep,
               m.param_a, m.param_b, m.param_c, m.tp_lingua,
               (SELECT group_concat(ano) FROM (
                    SELECT DISTINCT ano FROM _meta_union
                    WHERE CO_ITEM = m.CO_ITEM ORDER BY ano)) AS anos
        FROM _meta_union m JOIN latest l
          ON l.CO_ITEM = m.CO_ITEM AND l.ano_max = m.ano;
        DROP TABLE _meta_union;
    """)
    n = con.execute("SELECT count(*) FROM itens_meta_all").fetchone()[0]
    log(f"  {n:,} itens distintos")

    # ---------------- índices
    log("índices…")
    con.executescript("""
        CREATE INDEX ix_hr ON hist_resumo(nivel, chave, rede, ano);
        CREATE INDEX ix_hi ON hist_item(nivel, chave, rede, ano);
        CREATE INDEX ix_hh ON hist_hab(area, h, ano);
        CREATE INDEX ix_ima ON itens_meta_all(CO_ITEM);
        CREATE INDEX ix_ima_ah ON itens_meta_all(area, habilidade_inep);
        ANALYZE;
    """)

    for a, _ in fontes:
        con.execute(f"DETACH DATABASE y{a}")
    con.close()
    log(f"OK — {db_out} ({os.path.getsize(db_out)/1e6:.0f} MB)")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--anos", type=int, nargs="+", default=DEFAULT_ANOS)
    p.add_argument("--out", default=os.path.join(BASE, "data", "enem_hist.sqlite"))
    args = p.parse_args()
    build_hist(args.anos, args.out)


if __name__ == "__main__":
    main()
