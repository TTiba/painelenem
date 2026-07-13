#!/usr/bin/env python3
"""
API + estáticos da plataforma ENEM (stdlib apenas — sem dependências).

  GET /api/ufs
  GET /api/municipios?uf=SP
  GET /api/escolas?municipio=3550308
  GET /api/resumo?nivel=ESC|MUN|UF|BR&chave=...
  GET /api/itens?nivel=...&chave=...&area=CN|CH|LC|MT

Uso: python3 server.py [porta]   (padrão 8765)
"""
import json
import os
import sqlite3
import sys
from http.server import HTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, "data", "enem2025.sqlite")
WEB = os.path.join(BASE, "web")

DEPENDENCIA = {1: "Federal", 2: "Estadual", 3: "Municipal", 4: "Privada"}


def q(sql, params=()):
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    rows = [dict(r) for r in con.execute(sql, params).fetchall()]
    con.close()
    return rows


def resumo_row(nivel, chave, rede="T"):
    if nivel == "ESC":
        rede = "T"          # escola pertence a uma única rede
    r = q("SELECT * FROM agg_resumo WHERE nivel=? AND chave=? AND rede=?",
          (nivel, chave, rede))
    return r[0] if r else None


def rede_de(qs):
    r = qs.get("rede", ["T"])[0].upper()
    return r if r in ("T", "PUB", "PRIV") else "T"


def api(path, qs):
    rede = rede_de(qs)

    if path == "/api/ufs":
        return q("""SELECT chave, nome, n_participantes, media_geral,
                           media_red, media_lc, media_ch, media_cn, media_mt
                    FROM agg_resumo WHERE nivel='UF' AND rede=?
                    ORDER BY chave""", (rede,))

    if path == "/api/municipios":
        uf = qs.get("uf", [""])[0]
        return q("""SELECT chave, nome, n_participantes, media_geral,
                           media_red, media_lc, media_ch, media_cn, media_mt
                    FROM agg_resumo WHERE nivel='MUN' AND uf=? AND rede=?
                    ORDER BY nome""", (uf, rede))

    if path == "/api/escolas":
        mun = qs.get("municipio", [""])[0]
        filtro_rede = {"PUB": "AND COALESCE(e.dependencia, 0) != 4",
                       "PRIV": "AND e.dependencia = 4"}.get(rede, "")
        rows = q(f"""SELECT e.chave, e.nome, e.dependencia, e.n_participantes,
                           r.media_geral
                    FROM escolas e
                    JOIN agg_resumo r ON r.nivel='ESC' AND r.chave=e.chave
                                     AND r.rede='T'
                    WHERE e.co_municipio=? {filtro_rede}
                    ORDER BY e.n_participantes DESC""", (mun,))
        for r in rows:
            dep = DEPENDENCIA.get(r["dependencia"], "")
            r["rotulo"] = (r["nome"] or f"Escola INEP {r['chave']}") + \
                          (f" · {dep}" if dep else "")
        return rows

    if path == "/api/resumo":
        nivel = qs.get("nivel", ["BR"])[0]
        chave = qs.get("chave", ["BR"])[0]
        alvo = resumo_row(nivel, chave, rede)
        if not alvo:
            return {"erro": "não encontrado"}
        ctx = []
        if nivel == "ESC":
            esc = q("SELECT * FROM escolas WHERE chave=?", (chave,))
            if esc:
                if esc[0]["nome"]:
                    alvo["nome"] = esc[0]["nome"]
                alvo["escola"] = esc[0]
                alvo["escola"]["dependencia_nome"] = DEPENDENCIA.get(
                    esc[0]["dependencia"], "")
                m = resumo_row("MUN", str(esc[0]["co_municipio"]), rede)
                u = resumo_row("UF", esc[0]["uf"], rede)
                ctx = [x for x in (m, u) if x]
        elif nivel == "MUN":
            u = resumo_row("UF", alvo.get("uf") or "", rede)
            ctx = [x for x in (u,) if x]
        br = resumo_row("BR", "BR", rede)
        if nivel != "BR" and br:
            ctx.append(br)
        return {"alvo": alvo, "contexto": ctx}

    if path == "/api/itens":
        nivel = qs.get("nivel", ["BR"])[0]
        chave = qs.get("chave", ["BR"])[0]
        area = qs.get("area", ["MT"])[0]
        # referência: UF da entidade (ou BR se a entidade for UF/BR)
        uf = None
        if nivel == "ESC":
            e = q("SELECT uf FROM escolas WHERE chave=?", (chave,))
            uf = e[0]["uf"] if e else None
        elif nivel == "MUN":
            r = q("SELECT uf FROM agg_resumo WHERE nivel='MUN' AND chave=?",
                  (chave,))
            uf = r[0]["uf"] if r else None
        elif nivel == "UF":
            uf = chave
        rede_alvo = "T" if nivel == "ESC" else rede
        rows = q("""
            SELECT a.CO_ITEM AS item, a.n, CAST(a.acertos AS INTEGER) AS acertos,
                   round(1.0*a.acertos/a.n, 3) AS p,
                   round(1.0*a.esperado/a.n, 3) AS p_esp,
                   m.habilidade_inep, m.habilidade_custom,
                   m.param_b, m.gabarito, m.tp_lingua,
                   round(1.0*u.acertos/u.n, 3) AS p_uf,
                   round(1.0*b.acertos/b.n, 3) AS p_br
            FROM agg_item a
            JOIN itens_meta m ON m.CO_ITEM = a.CO_ITEM AND m.area = ?
            LEFT JOIN agg_item u ON u.nivel='UF' AND u.chave=? AND u.rede=?
                                AND u.CO_ITEM=a.CO_ITEM
            LEFT JOIN agg_item b ON b.nivel='BR' AND b.chave='BR' AND b.rede=?
                                AND b.CO_ITEM=a.CO_ITEM
            WHERE a.nivel=? AND a.chave=? AND a.rede=?
            ORDER BY p ASC""",
            (area, uf or "", rede, rede, nivel, chave, rede_alvo))
        # descarta itens de cadernos minoritários (reaplicação/adaptados),
        # que apareceriam com pouquíssimos respondentes na entidade
        if rows:
            n_max = max(r["n"] for r in rows)
            rows = [r for r in rows if r["n"] >= 0.25 * n_max]
        return rows

    return {"erro": "rota desconhecida"}


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=WEB, **kw)

    def log_message(self, *a):
        pass

    def do_GET(self):
        u = urlparse(self.path)
        if u.path.startswith("/api/"):
            try:
                body = json.dumps(api(u.path, parse_qs(u.query)),
                                  ensure_ascii=False).encode()
                self.send_response(200)
            except Exception as e:  # noqa: BLE001
                body = json.dumps({"erro": str(e)}).encode()
                self.send_response(500)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            super().do_GET()


if __name__ == "__main__":
    porta = int(sys.argv[1] if len(sys.argv) > 1 else os.environ.get("PORT", 8765))
    print(f"Plataforma ENEM em http://localhost:{porta}", flush=True)
    HTTPServer(("127.0.0.1", porta), Handler).serve_forever()
