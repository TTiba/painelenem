#!/usr/bin/env python3
"""
Pipeline ENEM — agrega microdados em SQLite para a plataforma.

Níveis: BR > UF > MUN (município) > ESC (escola).
Métricas: notas médias por área + redação (e 5 competências) e acerto por item.

Escopo por ano:
- 2024, 2025: formato novo (RESULTADOS_YYYY.csv), CO_ESCOLA presente → nível ESC
  populado. Filtro: CO_ESCOLA IS NOT NULL (concluintes com escola).
- 2021, 2022, 2023: formato antigo (MICRODADOS_ENEM_YYYY.csv), sem CO_ESCOLA →
  nível ESC ausente. Filtro: TP_ST_CONCLUSAO=2 AND IN_TREINEIRO=0 AND
  TP_PRESENCA_LC=1 AND TP_PRESENCA_MT=1 (concluintes que fizeram os dois dias).

Uso:
    .venv/bin/python pipeline/build_db.py                       # ENEM 2025 (default)
    .venv/bin/python pipeline/build_db.py --ano 2024
    .venv/bin/python pipeline/build_db.py --ano 2021 --dados ../microdados_enem_2021/DADOS
"""
import argparse
import os
import sqlite3
import time

import duckdb

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AREAS = [("LC", 0), ("CH", 45), ("CN", 90), ("MT", 135)]


def build(ano: int, dados_dir: str, db_out: str) -> None:
    t0 = time.time()
    def log(msg):
        print(f"[{ano} · {time.time() - t0:6.1f}s] {msg}", flush=True)

    tem_co_escola = ano >= 2024

    resultados_novo = os.path.join(dados_dir, f"RESULTADOS_{ano}.csv")
    resultados_antigo = os.path.join(dados_dir, f"MICRODADOS_ENEM_{ano}.csv")
    if os.path.exists(resultados_novo):
        resultados = resultados_novo
    elif os.path.exists(resultados_antigo):
        resultados = resultados_antigo
    else:
        raise SystemExit(f"CSV de resultados não encontrado em {dados_dir}")
    itens = os.path.join(dados_dir, f"ITENS_PROVA_{ano}.csv")
    if not os.path.exists(itens):
        raise SystemExit(f"CSV de itens não encontrado: {itens}")

    log(f"fonte: {os.path.basename(resultados)}  (tem_co_escola={tem_co_escola})")

    con = duckdb.connect()
    con.execute("SET memory_limit='14GB'")
    con.execute("SET preserve_insertion_order=false")

    # ------------------------------------------------------------ itens
    log("Lendo itens…")
    con.execute(f"""
        CREATE TABLE itens AS
        SELECT * FROM read_csv('{itens}', delim=';', header=true,
                               encoding='latin-1', sample_size=-1)
        WHERE IN_ITEM_ABAN = 0
    """)
    con.execute("""
        ALTER TABLE itens ADD COLUMN pos INTEGER;
        UPDATE itens SET pos = CO_POSICAO - CASE SG_AREA
            WHEN 'LC' THEN 0 WHEN 'CH' THEN 45 WHEN 'CN' THEN 90 ELSE 135 END;
    """)

    con.execute("""
        CREATE TABLE itens_meta AS
        SELECT CO_ITEM,
               any_value(SG_AREA)        AS area,
               any_value(CO_HABILIDADE)  AS habilidade_inep,
               any_value(TX_GABARITO)    AS gabarito,
               any_value(NU_PARAM_A)     AS param_a,
               any_value(NU_PARAM_B)     AS param_b,
               any_value(NU_PARAM_C)     AS param_c,
               any_value(TP_LINGUA)      AS tp_lingua,
               CAST(NULL AS VARCHAR)     AS habilidade_custom
        FROM itens GROUP BY CO_ITEM
    """)

    # ------------------------------------------------------------ resultados
    #
    # Formato novo (2024+): colunas de escola vêm no RESULTADOS_YYYY.csv.
    # Formato antigo (2021-2023): tudo num arquivo só, sem CO_ESCOLA — usamos
    # NULL como stub para preservar o shape dos rollups.
    if tem_co_escola:
        cols_extra = "CO_ESCOLA"
        where_filtro = "CO_ESCOLA IS NOT NULL"
    else:
        # sintetiza CO_ESCOLA=NULL sem quebrar o cast VARCHAR downstream.
        cols_extra = "CAST(NULL AS BIGINT) AS CO_ESCOLA"
        where_filtro = (
            "TP_ST_CONCLUSAO = 2 AND IN_TREINEIRO = 0 "
            "AND CO_MUNICIPIO_ESC IS NOT NULL "
            "AND TP_PRESENCA_LC = 1 AND TP_PRESENCA_MT = 1"
        )

    cols = f"""
        {cols_extra}, CO_MUNICIPIO_ESC, NO_MUNICIPIO_ESC,
        SG_UF_ESC, TP_DEPENDENCIA_ADM_ESC, TP_LOCALIZACAO_ESC,
        TP_PRESENCA_CN, TP_PRESENCA_CH, TP_PRESENCA_LC, TP_PRESENCA_MT,
        CO_PROVA_CN, CO_PROVA_CH, CO_PROVA_LC, CO_PROVA_MT,
        NU_NOTA_CN, NU_NOTA_CH, NU_NOTA_LC, NU_NOTA_MT,
        TX_RESPOSTAS_CN, TX_RESPOSTAS_CH, TX_RESPOSTAS_LC, TX_RESPOSTAS_MT,
        TP_LINGUA, TP_STATUS_REDACAO, NU_NOTA_REDACAO,
        NU_NOTA_COMP1, NU_NOTA_COMP2, NU_NOTA_COMP3, NU_NOTA_COMP4, NU_NOTA_COMP5
    """
    log(f"Lendo {os.path.basename(resultados)}…")
    con.execute(f"""
        CREATE TABLE res AS
        SELECT {cols} FROM read_csv('{resultados}', delim=';', header=true,
                                    encoding='latin-1', sample_size=-1)
        WHERE {where_filtro}
    """)
    n = con.execute("SELECT count(*) FROM res").fetchone()[0]
    log(f"Concluintes: {n:,}")

    con.execute("""
        CREATE VIEW res_k AS
        SELECT *,
            CAST(CO_ESCOLA AS VARCHAR)        AS k_esc,
            CAST(CO_MUNICIPIO_ESC AS VARCHAR) AS k_mun,
            SG_UF_ESC                         AS k_uf,
            CASE WHEN TP_DEPENDENCIA_ADM_ESC = 4 THEN 'PRIV' ELSE 'PUB' END AS rede
        FROM res
    """)

    # ------------------------------------------------------------ resumo
    log("Agregando notas por nível…")

    def resumo_select(nivel, chave, nome, uf, grupo=None, rede_val="T",
                      where_extra=""):
        group_by = f"GROUP BY {grupo}" if grupo else ""
        return f"""
            SELECT '{nivel}' AS nivel, {chave} AS chave, '{rede_val}' AS rede,
                {nome} AS nome, {uf} AS uf,
                count(*) AS n_participantes,
                count(NU_NOTA_CN)  AS n_cn,  round(avg(NU_NOTA_CN),1)  AS media_cn,
                count(NU_NOTA_CH)  AS n_ch,  round(avg(NU_NOTA_CH),1)  AS media_ch,
                count(NU_NOTA_LC)  AS n_lc,  round(avg(NU_NOTA_LC),1)  AS media_lc,
                count(NU_NOTA_MT)  AS n_mt,  round(avg(NU_NOTA_MT),1)  AS media_mt,
                count(NU_NOTA_REDACAO) AS n_red,
                round(avg(NU_NOTA_REDACAO),1) AS media_red,
                round(avg(NU_NOTA_COMP1),1) AS media_comp1,
                round(avg(NU_NOTA_COMP2),1) AS media_comp2,
                round(avg(NU_NOTA_COMP3),1) AS media_comp3,
                round(avg(NU_NOTA_COMP4),1) AS media_comp4,
                round(avg(NU_NOTA_COMP5),1) AS media_comp5,
                round(avg((NU_NOTA_CN+NU_NOTA_CH+NU_NOTA_LC+NU_NOTA_MT+NU_NOTA_REDACAO)/5),1)
                    AS media_geral
            FROM res_k {where_extra} {group_by}
        """

    partes_resumo = []
    if tem_co_escola:
        partes_resumo.append(
            resumo_select('ESC', 'k_esc', "'Escola INEP ' || k_esc",
                          'any_value(k_uf)', 'k_esc')
        )
    for rv in ("T", "PUB", "PRIV"):
        w = "" if rv == "T" else f"WHERE rede = '{rv}'"
        partes_resumo += [
            resumo_select('BR', "'BR'", "'Brasil'", "CAST(NULL AS VARCHAR)",
                          rede_val=rv, where_extra=w),
            resumo_select('UF', 'k_uf', 'any_value(k_uf)', 'any_value(k_uf)',
                          'k_uf', rede_val=rv, where_extra=w),
            resumo_select('MUN', 'k_mun', "any_value(NO_MUNICIPIO_ESC)",
                          'any_value(k_uf)', 'k_mun', rede_val=rv, where_extra=w),
        ]
    con.execute("CREATE TABLE agg_resumo AS " + " UNION ALL ".join(partes_resumo))

    # ------------------------------------------------------------ escolas
    if tem_co_escola:
        con.execute("""
            CREATE TABLE escolas AS
            SELECT k_esc AS chave,
                   any_value(k_mun) AS co_municipio,
                   any_value(NO_MUNICIPIO_ESC) AS municipio,
                   any_value(k_uf) AS uf,
                   any_value(TP_DEPENDENCIA_ADM_ESC) AS dependencia,
                   any_value(TP_LOCALIZACAO_ESC) AS localizacao,
                   count(*) AS n_participantes,
                   CAST(NULL AS VARCHAR) AS nome
            FROM res_k GROUP BY k_esc
        """)
    else:
        # tabela vazia com schema correto — simplifica o exporter
        con.execute("""
            CREATE TABLE escolas (
                chave VARCHAR, co_municipio VARCHAR, municipio VARCHAR,
                uf VARCHAR, dependencia INTEGER, localizacao INTEGER,
                n_participantes BIGINT, nome VARCHAR
            )
        """)

    # ------------------------------------------------------------ itens longos
    log("Explodindo respostas item a item…")
    partes = []
    for area, off in AREAS:
        lingua = ""
        if area == "LC":
            lingua = "AND (i.TP_LINGUA IS NULL OR i.TP_LINGUA = r.TP_LINGUA)"
        partes.append(f"""
            SELECT r.k_esc, r.k_mun, r.k_uf, r.rede, i.CO_ITEM,
                   CASE WHEN substr(r.TX_RESPOSTAS_{area}, i.pos, 1) = i.TX_GABARITO
                        THEN 1 ELSE 0 END AS acerto,
                   i.NU_PARAM_C + (1 - i.NU_PARAM_C) /
                     (1 + exp(-1.7 * i.NU_PARAM_A *
                              ((r.NU_NOTA_{area} - 500) / 100.0 - i.NU_PARAM_B)))
                     AS p_esp
            FROM res_k r
            JOIN itens i ON i.CO_PROVA = r.CO_PROVA_{area} AND i.SG_AREA = '{area}'
            WHERE r.TP_PRESENCA_{area} = 1 AND r.TX_RESPOSTAS_{area} IS NOT NULL
              AND r.NU_NOTA_{area} IS NOT NULL
              {lingua}
        """)
    longo_sql = " UNION ALL ".join(partes)

    log("Agregando acertos por item e nível…")
    # município × rede é a base compacta pra rollups UF/BR (e MUN direto).
    con.execute(f"""
        CREATE TABLE mun_item AS
        WITH longo AS ({longo_sql})
        SELECT k_mun, k_uf, rede, CO_ITEM,
               CAST(count(*) AS BIGINT) AS n,
               CAST(sum(acerto) AS BIGINT) AS acertos,
               sum(p_esp) AS esperado
        FROM longo GROUP BY k_mun, k_uf, rede, CO_ITEM
    """)
    partes_agg = []
    if tem_co_escola:
        # ESC × T: uma escola vive em uma única rede → agregação direta em k_esc.
        con.execute(f"""
            CREATE TABLE agg_item_esc AS
            WITH longo AS ({longo_sql})
            SELECT 'ESC' AS nivel, k_esc AS chave, 'T' AS rede, CO_ITEM,
                   CAST(count(*) AS BIGINT) AS n,
                   CAST(sum(acerto) AS BIGINT) AS acertos,
                   sum(p_esp) AS esperado
            FROM longo GROUP BY k_esc, CO_ITEM
        """)
        partes_agg.append("SELECT * FROM agg_item_esc")

    # o primeiro SELECT de um UNION define os nomes das colunas — precisa
    # ter aliases explícitos quando não vem antes o agg_item_esc.
    partes_agg += [
        """SELECT 'MUN' AS nivel, k_mun AS chave, rede, CO_ITEM,
                  n, acertos, esperado FROM mun_item""",
        """SELECT 'MUN', k_mun, 'T', CO_ITEM, CAST(sum(n) AS BIGINT),
                  CAST(sum(acertos) AS BIGINT), sum(esperado)
           FROM mun_item GROUP BY k_mun, CO_ITEM""",
        """SELECT 'UF', k_uf, rede, CO_ITEM, CAST(sum(n) AS BIGINT),
                  CAST(sum(acertos) AS BIGINT), sum(esperado)
           FROM mun_item GROUP BY k_uf, rede, CO_ITEM""",
        """SELECT 'UF', k_uf, 'T', CO_ITEM, CAST(sum(n) AS BIGINT),
                  CAST(sum(acertos) AS BIGINT), sum(esperado)
           FROM mun_item GROUP BY k_uf, CO_ITEM""",
        """SELECT 'BR', 'BR', rede, CO_ITEM, CAST(sum(n) AS BIGINT),
                  CAST(sum(acertos) AS BIGINT), sum(esperado)
           FROM mun_item GROUP BY rede, CO_ITEM""",
        """SELECT 'BR', 'BR', 'T', CO_ITEM, CAST(sum(n) AS BIGINT),
                  CAST(sum(acertos) AS BIGINT), sum(esperado)
           FROM mun_item GROUP BY CO_ITEM""",
    ]
    con.execute("CREATE TABLE agg_item AS " + " UNION ALL ".join(partes_agg))
    con.execute("DROP TABLE IF EXISTS agg_item_esc; DROP TABLE mun_item;")
    n_item = con.execute("SELECT count(*) FROM agg_item").fetchone()[0]
    log(f"agg_item: {n_item:,} linhas")

    # ------------------------------------------------------------ SQLite
    log("Gravando SQLite…")
    os.makedirs(os.path.dirname(db_out), exist_ok=True)
    if os.path.exists(db_out):
        os.remove(db_out)

    con.execute("INSTALL sqlite; LOAD sqlite;")
    con.execute(f"ATTACH '{db_out}' AS out (TYPE sqlite)")
    for t in ["agg_resumo", "escolas", "agg_item", "itens_meta"]:
        con.execute(f"CREATE TABLE out.{t} AS SELECT * FROM {t}")
        log(f"  gravada {t}")
    con.execute("DETACH out")
    con.close()

    sq = sqlite3.connect(db_out)
    sq.executescript("""
        CREATE INDEX ix_resumo ON agg_resumo(nivel, chave, rede);
        CREATE INDEX ix_item   ON agg_item(nivel, chave, rede);
        CREATE INDEX ix_esc_mun ON escolas(co_municipio);
        CREATE INDEX ix_meta   ON itens_meta(CO_ITEM);
        ANALYZE;
    """)
    sq.close()
    log(f"OK — {db_out} ({os.path.getsize(db_out)/1e6:.0f} MB)")


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    p.add_argument("--ano", type=int, default=2025)
    p.add_argument("--dados", type=str, default=None,
                   help="pasta DADOS/ (default: ../microdados_enem_{ano}/DADOS)")
    p.add_argument("--sqlite", type=str, default=None,
                   help="arquivo de saída (default: data/enem{ano}.sqlite)")
    args = p.parse_args()

    dados = args.dados or os.path.join(
        os.path.dirname(BASE), f"microdados_enem_{args.ano}", "DADOS")
    db_out = args.sqlite or os.path.join(BASE, "data", f"enem{args.ano}.sqlite")
    build(args.ano, dados, db_out)


if __name__ == "__main__":
    main()
