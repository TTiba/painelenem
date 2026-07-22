/* Filtros globais persistentes — mantém uf/mun/esc/rede compartilhados entre
 * todas as páginas do painel via localStorage. Precedência ao carregar:
 *   1. URL query string (?uf=SP&rede=PUB…) — sempre vence, permite compartilhar link
 *   2. localStorage (última seleção do usuário)
 *   3. defaults (BR + rede T)
 *
 * Uso típico:
 *   const f = window.Filtros.carregar();   // {uf, mun, esc, rede}
 *   // aplica f no state e nos seletores da página
 *   window.Filtros.salvar(f);              // depois de qualquer alteração
 *
 * Chaves no localStorage começam com "enem.filtros.".
 */
(function () {
  const KEY = "enem.filtros";
  const REDES = new Set(["T", "PUB", "PRIV"]);
  const DEFAULTS = { uf: "", mun: "", esc: "", rede: "T" };

  function lerLS() {
    try {
      const raw = localStorage.getItem(KEY);
      if (!raw) return {};
      const o = JSON.parse(raw) || {};
      const out = {};
      if (typeof o.uf === "string")   out.uf   = o.uf.toUpperCase();
      if (typeof o.mun === "string")  out.mun  = o.mun;
      if (typeof o.esc === "string")  out.esc  = o.esc;
      if (REDES.has(o.rede))          out.rede = o.rede;
      return out;
    } catch { return {}; }
  }

  function lerURL() {
    const p = new URLSearchParams(location.search);
    const out = {};
    if (p.get("uf"))  out.uf  = p.get("uf").toUpperCase();
    if (p.get("mun")) out.mun = p.get("mun");
    if (p.get("esc")) out.esc = p.get("esc");
    if (REDES.has(p.get("rede"))) out.rede = p.get("rede");
    return out;
  }

  function carregar() {
    const url = lerURL();
    const ls  = lerLS();
    // uf vazio explícito na URL (ex.: veio de "Limpar") supera o LS
    const temUrlUf  = new URLSearchParams(location.search).has("uf");
    const temUrlMun = new URLSearchParams(location.search).has("mun");
    const temUrlEsc = new URLSearchParams(location.search).has("esc");
    return {
      uf:   temUrlUf  ? (url.uf   || "") : (url.uf   ?? ls.uf   ?? DEFAULTS.uf),
      mun:  temUrlMun ? (url.mun  || "") : (url.mun  ?? ls.mun  ?? DEFAULTS.mun),
      esc:  temUrlEsc ? (url.esc  || "") : (url.esc  ?? ls.esc  ?? DEFAULTS.esc),
      rede: url.rede  ?? ls.rede  ?? DEFAULTS.rede,
    };
  }

  function salvar(f) {
    try {
      localStorage.setItem(KEY, JSON.stringify({
        uf: f.uf || "", mun: f.mun || "", esc: f.esc || "",
        rede: REDES.has(f.rede) ? f.rede : "T",
      }));
    } catch { /* ignora */ }
  }

  function limpar() {
    try { localStorage.removeItem(KEY); } catch { /* ignora */ }
  }

  window.Filtros = { carregar, salvar, limpar };
})();
