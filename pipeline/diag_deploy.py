#!/usr/bin/env python3
"""Diagnostico: por que o verificador nao acha dado avaliavel num deploy."""
import glob
import json
import os
import sys

AREAS = ("CN", "CH", "LC", "MT")


def conta(bloco):
    tot = nulo_esp = nulo_p = sem_n = 0
    for area in AREAS:
        for a in bloco.get("itens", {}).get(area, []):
            tot += 1
            if a[3] is None:
                nulo_esp += 1
            if a[2] is None:
                nulo_p += 1
            if not a[1]:
                sem_n += 1
    return tot, nulo_esp, nulo_p, sem_n


for base in sys.argv[1:]:
    print("=" * 62)
    print(base, "" if os.path.isdir(base) else "  <<< PASTA NAO EXISTE")
    if not os.path.isdir(base):
        continue
    for k in ("BR/BR", "UF/PR", "UF/SP"):
        p = os.path.join(base, "api", "entidade", k + ".json")
        if not os.path.exists(p):
            print(f"  {k:<8} ausente")
            continue
        d = json.load(open(p, encoding="utf-8"))
        print(f"  {k:<8} redes={list(d.keys())}")
        for rede in ("T", "PUB"):
            b = d.get(rede)
            if not isinstance(b, dict):
                print(f"      {rede}: bloco ausente")
                continue
            tot, ne, np_, sn = conta(b)
            print(f"      {rede}: {tot:>4} itens · p_esp nulo {ne:>4}"
                  f" · p nulo {np_:>4} · n vazio {sn:>4}"
                  + ("   <<< NADA AVALIAVEL" if tot and ne == tot else ""))
    for niv in ("MUN", "ESC"):
        fs = sorted(glob.glob(os.path.join(base, "api", "entidade", niv, "*.json")))
        if not fs:
            print(f"  {niv}: 0 arquivos")
            continue
        amostra = fs[:40]
        tots = nulos = 0
        for f in amostra:
            d = json.load(open(f, encoding="utf-8"))
            b = d.get("PUB") if isinstance(d.get("PUB"), dict) else d
            if isinstance(b, dict):
                t, ne, _, _ = conta(b)
                tots += t
                nulos += ne
        pct = 100 * nulos / tots if tots else 0
        print(f"  {niv}: {len(fs)} arquivos · nos 40 primeiros:"
              f" {tots} itens, p_esp nulo {nulos} ({pct:.0f}%)")
