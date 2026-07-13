#!/usr/bin/env python3
"""
Carrega nomes de escolas no banco da plataforma a partir de um CSV.

Aceita qualquer CSV (separador ; ou ,) que tenha uma coluna com o código INEP
(INEP, CO_ESCOLA ou CODIGO_INEP) e uma com o nome (ESCOLA, NOME ou NO_ESCOLA).
Linhas cujo código não existe no banco (escola sem participantes no ENEM 2025)
são ignoradas.

Uso:  python3 pipeline/carrega_nomes_escolas.py caminho/escolas.csv
"""
import csv
import os
import sqlite3
import sys

DB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                  "data", "enem2025.sqlite")

COLS_INEP = {"INEP", "CO_ESCOLA", "CODIGO_INEP", "CO_ENTIDADE"}
COLS_NOME = {"ESCOLA", "NOME", "NO_ESCOLA", "NO_ENTIDADE"}

if len(sys.argv) != 2:
    sys.exit(__doc__)

caminho = sys.argv[1]
with open(caminho, newline="", encoding="utf-8-sig") as f:
    dialeto = csv.Sniffer().sniff(f.read(2048), delimiters=";,")
    f.seek(0)
    linhas = list(csv.DictReader(f, dialect=dialeto))

if not linhas:
    sys.exit("CSV vazio.")
cab = {c.strip().upper(): c for c in linhas[0]}
c_inep = next((cab[c] for c in cab if c in COLS_INEP), None)
c_nome = next((cab[c] for c in cab if c in COLS_NOME), None)
if not c_inep or not c_nome:
    sys.exit(f"Não achei colunas de INEP e nome no cabeçalho: {list(cab)}")

con = sqlite3.connect(DB)
atualizadas, ignoradas = 0, 0
for ln in linhas:
    inep = ln[c_inep].strip()
    nome = " ".join(ln[c_nome].split()).strip()
    if not inep.isdigit() or not nome:
        ignoradas += 1
        continue
    cur = con.execute("UPDATE escolas SET nome=? WHERE chave=?", (nome, inep))
    if cur.rowcount:
        atualizadas += 1
    else:
        ignoradas += 1          # escola sem participantes no ENEM 2025
con.commit()

total, com_nome = con.execute(
    "SELECT count(*), count(nome) FROM escolas").fetchone()
con.close()
print(f"{atualizadas} escolas nomeadas ({ignoradas} linhas sem correspondência). "
      f"Banco: {com_nome}/{total} escolas com nome.")
