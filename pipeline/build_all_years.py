#!/usr/bin/env python3
"""
Roda build_db para 2021..2025, gerando data/enem20XX.sqlite em cada um.

Uso: .venv/bin/python pipeline/build_all_years.py [--anos 2021 2022 ...]
"""
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build_db import build, BASE  # noqa: E402

DEFAULT_ANOS = [2021, 2022, 2023, 2024, 2025]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--anos", type=int, nargs="+", default=DEFAULT_ANOS)
    args = p.parse_args()

    t0 = time.time()
    for ano in args.anos:
        dados = os.path.join(os.path.dirname(BASE),
                             f"microdados_enem_{ano}", "DADOS")
        db_out = os.path.join(BASE, "data", f"enem{ano}.sqlite")
        if not os.path.isdir(dados):
            print(f"! {ano}: {dados} não existe, pulando")
            continue
        print(f"\n{'='*60}\n  ENEM {ano}\n{'='*60}")
        build(ano, dados, db_out)
    print(f"\nTotal: {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
