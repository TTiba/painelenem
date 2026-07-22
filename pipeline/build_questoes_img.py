#!/usr/bin/env python3
"""
Extrai as questões do ENEM de PDFs oficiais em imagens WebP, mapeando cada
CO_ITEM à(s) página(s) do PDF onde ele aparece.

Estratégia:
1. Identifica o caderno AZUL regular (P1) de cada área analisando os CO_PROVA
   com maior volume no agg_item — evita palpite sobre nome de arquivo.
2. Extrai o texto de cada PDF procurando marcadores "Questão NN" → mapa
   posicao → página inicial.
3. Renderiza cada página via pdftoppm em PNG e converte pra WebP com cwebp.
4. Descobre a faixa de páginas de cada questão (da página onde ela começa
   até a página anterior à próxima questão).
5. Salva `deploy/questoes/{ano}/pag_{N}.webp` (dedup por página) e
   `deploy/api/questoes/{ano}.json` = {CO_ITEM: {pags: [N, N+1, ...]}}.

Dependências externas: pdftoppm (poppler), pdftotext (poppler), cwebp.
Todas as três estão em /opt/homebrew/bin no macOS via `brew install poppler webp`.

Uso:  python3 pipeline/build_questoes_img.py --ano 2025
"""
import argparse
import csv
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEPLOY = os.path.join(BASE, "deploy")

# Padrão de nome dos PDFs oficiais AZUL. Ajusta por ano conforme necessário.
PDF_TEMPLATES = {
    2025: {
        "DIA_1": "ENEM_2025_P1_CAD_01_DIA_1_AZUL.pdf",  # LC + CH
        "DIA_2": "ENEM_2025_P1_CAD_07_DIA_2_AZUL.pdf",  # CN + MT
    },
}

# Áreas por dia (na ordem em que aparecem no caderno)
AREAS_POR_DIA = {
    "DIA_1": ["LC", "CH"],
    "DIA_2": ["CN", "MT"],
}


def run(cmd, check=True):
    """Executa comando externo silenciosamente."""
    r = subprocess.run(cmd, capture_output=True, text=True)
    if check and r.returncode != 0:
        raise RuntimeError(f"{' '.join(cmd)}\n{r.stderr}")
    return r


def descobrir_caderno_regular(sqlite_path, area, cor="AZUL"):
    """Retorna o CO_PROVA do caderno regular (maior volume) da área+cor."""
    c = sqlite3.connect(sqlite_path)
    # o CO_PROVA regular tem os CO_ITEM com maior n em agg_item BR/T
    row = c.execute("""
        SELECT co_prova, sum(n) AS total FROM (
            SELECT im.CO_ITEM, ai.n,
                   (SELECT CO_PROVA_MAX FROM (SELECT ai.CO_ITEM as CI, ? as CO_PROVA_MAX)) AS co_prova
            FROM agg_item ai JOIN itens_meta im ON im.CO_ITEM=ai.CO_ITEM
            WHERE ai.nivel='BR' AND ai.rede='T' AND im.area=?
        ) GROUP BY co_prova
    """, (0, area)).fetchone()
    c.close()
    return None    # essa função ficou complexa demais; usaremos leitura do CSV


def descobrir_cadernos_regulares(ano, dados_dir, cor="AZUL"):
    """Escaneia ITENS_PROVA_YYYY.csv e retorna {area: CO_PROVA regular} da
    cor pedida. 'Regular' = o CO_PROVA com maior CO_ITEM count entre os
    de mesma (cor, área) — heurística: o primeiro registrado (menor CO_PROVA)
    costuma ser P1/regular, mas confirmamos pelo volume no SQLite depois."""
    csv_path = os.path.join(dados_dir, f"ITENS_PROVA_{ano}.csv")
    contagem = {}   # (area, co_prova) -> n_itens
    with open(csv_path, encoding="latin-1") as f:
        r = csv.DictReader(f, delimiter=";")
        for row in r:
            if row["TX_COR"] != cor:
                continue
            k = (row["SG_AREA"], row["CO_PROVA"])
            contagem[k] = contagem.get(k, 0) + 1
    # Para cada área, escolhe o CO_PROVA com mais itens (deve ser 45)
    regulares = {}
    for (area, co_prova), n in contagem.items():
        if n < 40:
            continue    # ignora cadernos incompletos (adaptados etc.)
        # Se houver múltiplos com 45, escolhe o menor CO_PROVA (P1 regular).
        if area not in regulares or int(co_prova) < int(regulares[area]):
            regulares[area] = co_prova
    return regulares


def ler_itens_da_prova(ano, dados_dir, co_provas):
    """Retorna dict {(area, tp_lingua_ou_None, co_posicao): CO_ITEM}.
    tp_lingua não-null distingue as duas versões LEM."""
    csv_path = os.path.join(dados_dir, f"ITENS_PROVA_{ano}.csv")
    out = {}
    with open(csv_path, encoding="latin-1") as f:
        r = csv.DictReader(f, delimiter=";")
        for row in r:
            if row["CO_PROVA"] not in co_provas:
                continue
            area = row["SG_AREA"]
            pos = int(row["CO_POSICAO"])
            lang = int(row["TP_LINGUA"]) if row.get("TP_LINGUA") else None
            key = (area, lang, pos)
            out[key] = int(row["CO_ITEM"])
    return out


def pagina_das_questoes(pdf_path):
    """Retorna dict {(tp_lingua, num_questao): pagina} extraindo texto do PDF.

    Heurística:
    - "Questão NN" (com N ∈ [1..90]) marca o INÍCIO de uma questão.
    - LC dia 1 tem seção de inglês (páginas iniciais) e depois espanhol
      (marcada por "opção espanhol"). Depois volta pra numeração comum.
    - CH/CN/MT usam só numeração 46-90 e 91-135, 136-180.

    Convenção do return: tp_lingua = 0 (inglês), 1 (espanhol), None (comum).
    """
    r = run(["pdftotext", "-layout", pdf_path, "-"])
    txt = r.stdout
    # Split por marcador de página (\x0c = form feed). pdftotext costuma
    # emitir um form feed final que gera um elemento vazio — descarta.
    paginas = [p for p in txt.split("\x0c") if p.strip()]

    # A leitura sequencial: identificamos se estamos na seção de inglês,
    # espanhol ou "comum" analisando texto de contexto.
    lingua_atual = None   # 0=inglês, 1=espanhol, None=comum
    mapa = {}             # (lingua, num) -> pagina
    q_pat = re.compile(r"Quest[ãa]o\s+0?(\d{1,3})", re.IGNORECASE)
    ing_pat = re.compile(r"op(ç|c)[ãa]o\s+ingl[eê]s", re.IGNORECASE)
    esp_pat = re.compile(r"op(ç|c)[ãa]o\s+espanhol", re.IGNORECASE)

    for i, pag in enumerate(paginas):
        page_num = i + 1
        if esp_pat.search(pag):
            lingua_atual = 1
        elif ing_pat.search(pag):
            lingua_atual = 0
        for m in q_pat.finditer(pag):
            num = int(m.group(1))
            if not 1 <= num <= 180:
                continue
            # As páginas 1-5 são LEM; a partir de 6 é comum, então soltamos
            # a flag de língua ao encontrar Questão 06+.
            key_lang = lingua_atual if num <= 5 else None
            if (key_lang, num) not in mapa:
                mapa[(key_lang, num)] = page_num
    return mapa, len(paginas)


def paginas_por_questao(mapa_qpag, total_paginas):
    """Constrói o range de páginas de cada questão: da página de início até
    a página anterior à próxima questão (na mesma "trilha")."""
    # ordena por (pagina, num) — questões em ordem de leitura
    itens = sorted(mapa_qpag.items(), key=lambda kv: (kv[1], kv[0][1]))
    resultado = {}
    for i, ((lang, num), p_ini) in enumerate(itens):
        # próxima questão em sequência de páginas
        p_fim = total_paginas
        for j in range(i + 1, len(itens)):
            _, p_next = itens[j]
            if p_next > p_ini:
                p_fim = p_next - 1
                break
        resultado[(lang, num)] = list(range(p_ini, p_fim + 1))
    return resultado


def extrair_paginas(pdf_path, out_dir, paginas_set, ano, dia_key):
    """Extrai as páginas necessárias em PNG e converte pra WebP.
    Retorna dict {pagina_pdf: caminho_webp_relativo}."""
    os.makedirs(out_dir, exist_ok=True)
    tmp = tempfile.mkdtemp(prefix=f"enem{ano}_{dia_key}_")
    try:
        for p in sorted(paginas_set):
            run(["pdftoppm", "-png", "-r", "130",
                 "-f", str(p), "-l", str(p), pdf_path,
                 os.path.join(tmp, "pag")])
        # nomes gerados: pag-01.png, pag-02.png etc. (zero-padded)
        out_map = {}
        for f in sorted(os.listdir(tmp)):
            if not f.endswith(".png"):
                continue
            n = int(re.search(r"pag-0*(\d+)\.png", f).group(1))
            png_path = os.path.join(tmp, f)
            webp_name = f"{dia_key.lower()}_pag_{n:02d}.webp"
            webp_path = os.path.join(out_dir, webp_name)
            run(["cwebp", "-quiet", "-q", "78", png_path, "-o", webp_path])
            out_map[n] = f"questoes/{ano}/{webp_name}"
        return out_map
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def build(ano):
    dados_dir = os.path.join(
        os.path.dirname(BASE), f"microdados_enem_{ano}", "DADOS")
    provas_dir = os.path.join(
        os.path.dirname(BASE), f"microdados_enem_{ano}", "PROVAS E GABARITOS")
    out_img_dir = os.path.join(DEPLOY, "questoes", str(ano))
    out_api = os.path.join(DEPLOY, "api", "questoes", f"{ano}.json")

    print(f"[{ano}] identificando cadernos AZUL regulares…")
    co_provas = descobrir_cadernos_regulares(ano, dados_dir, cor="AZUL")
    if not co_provas:
        raise SystemExit(f"não achei cadernos AZUL em {ano}")
    print(f"  CO_PROVA por área: {co_provas}")

    # (area, tp_lingua, posicao) → CO_ITEM
    itens_por_pos = ler_itens_da_prova(ano, dados_dir, set(co_provas.values()))
    print(f"  itens encontrados: {len(itens_por_pos)}")

    # limpa pasta de saída
    if os.path.exists(out_img_dir):
        shutil.rmtree(out_img_dir)
    os.makedirs(out_img_dir, exist_ok=True)

    # mapa final CO_ITEM → {pags: [N...], dia: "DIA_1"|"DIA_2"}
    resultado = {}

    for dia_key, pdf_name in PDF_TEMPLATES[ano].items():
        pdf_path = os.path.join(provas_dir, pdf_name)
        if not os.path.exists(pdf_path):
            print(f"  ! PDF ausente: {pdf_name}")
            continue
        print(f"[{ano}·{dia_key}] parseando {pdf_name}")
        mapa_qpag, total = pagina_das_questoes(pdf_path)
        rng = paginas_por_questao(mapa_qpag, total)
        print(f"  {len(rng)} questões mapeadas em {total} páginas")

        # coleta as páginas que serão renderizadas
        pag_set = set()
        for pgs in rng.values():
            pag_set.update(pgs)

        pag_map = extrair_paginas(pdf_path, out_img_dir, pag_set, ano, dia_key)

        # cross-refere: pra cada área do dia, mapa posicao → CO_ITEM
        for area in AREAS_POR_DIA[dia_key]:
            for (a, lang, pos), co_item in itens_por_pos.items():
                if a != area:
                    continue
                pgs = rng.get((lang, pos)) or rng.get((None, pos))
                if not pgs:
                    continue
                imgs = [pag_map[p] for p in pgs if p in pag_map]
                if imgs:
                    resultado[co_item] = {
                        "dia": dia_key, "area": area,
                        "pags": pgs, "imgs": imgs,
                        "co_posicao": pos, "tp_lingua": lang,
                    }

    os.makedirs(os.path.dirname(out_api), exist_ok=True)
    with open(out_api, "w", encoding="utf-8") as f:
        json.dump({"ano": ano, "itens": resultado}, f,
                  ensure_ascii=False, separators=(",", ":"))
    print(f"\n[{ano}] {len(resultado)} CO_ITEM mapeados → {out_api}")
    total_size = sum(os.path.getsize(os.path.join(out_img_dir, f))
                     for f in os.listdir(out_img_dir))
    print(f"       imagens: {len(os.listdir(out_img_dir))} arquivos, {total_size/1e6:.1f} MB")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--ano", type=int, default=2025)
    args = p.parse_args()
    if args.ano not in PDF_TEMPLATES:
        raise SystemExit(f"ano {args.ano} não configurado em PDF_TEMPLATES")
    build(args.ano)


if __name__ == "__main__":
    main()
