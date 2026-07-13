#!/usr/bin/env python3
"""
Carrega o mapa próprio de habilidades por item no banco da plataforma.

Espera um CSV com cabeçalho e duas colunas (separador ; ou ,):
    CO_ITEM;HABILIDADE
    141562;EM13MAT302
    ...

A coluna HABILIDADE é livre (código BNCC, descritor próprio etc.) e passa a
ser exibida no painel no lugar da habilidade INEP.

Uso:  python3 pipeline/carrega_habilidades.py caminho/do/mapa.csv
"""
import csv
import os
import sqlite3
import sys

DB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                  "data", "enem2025.sqlite")

if len(sys.argv) != 2:
    sys.exit(__doc__)

caminho = sys.argv[1]
with open(caminho, newline="", encoding="utf-8-sig") as f:
    dialeto = csv.Sniffer().sniff(f.read(2048), delimiters=";,")
    f.seek(0)
    linhas = list(csv.DictReader(f, dialect=dialeto))

if not linhas:
    sys.exit("CSV vazio.")
cols = {c.strip().upper(): c for c in linhas[0]}
c_item = cols.get("CO_ITEM")
c_hab = cols.get("HABILIDADE")
if not c_item or not c_hab:
    sys.exit(f"Cabeçalho precisa ter CO_ITEM e HABILIDADE (achei: {list(cols)})")

con = sqlite3.connect(DB)
atualizados = 0
for ln in linhas:
    cur = con.execute(
        "UPDATE itens_meta SET habilidade_custom=? WHERE CO_ITEM=?",
        (ln[c_hab].strip(), int(ln[c_item])))
    atualizados += cur.rowcount
con.commit()

sem_mapa = con.execute(
    "SELECT count(*) FROM itens_meta WHERE habilidade_custom IS NULL").fetchone()[0]
con.close()
print(f"{atualizados} itens atualizados; {sem_mapa} itens ainda sem mapa próprio.")
