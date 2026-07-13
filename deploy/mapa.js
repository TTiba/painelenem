/* Mapa coroplético do Brasil — médias por UF, com drill-down para municípios */

const NOME2UF = {
  "Acre": "AC", "Alagoas": "AL", "Amapá": "AP", "Amazonas": "AM",
  "Bahia": "BA", "Ceará": "CE", "Distrito Federal": "DF",
  "Espírito Santo": "ES", "Goiás": "GO", "Maranhão": "MA",
  "Mato Grosso": "MT", "Mato Grosso do Sul": "MS", "Minas Gerais": "MG",
  "Pará": "PA", "Paraíba": "PB", "Paraná": "PR", "Pernambuco": "PE",
  "Piauí": "PI", "Rio de Janeiro": "RJ", "Rio Grande do Norte": "RN",
  "Rio Grande do Sul": "RS", "Rondônia": "RO", "Roraima": "RR",
  "Santa Catarina": "SC", "São Paulo": "SP", "Sergipe": "SE", "Tocantins": "TO",
};
const UF2COD = {
  AC: 12, AL: 27, AP: 16, AM: 13, BA: 29, CE: 23, DF: 53, ES: 32, GO: 52,
  MA: 21, MT: 51, MS: 50, MG: 31, PA: 15, PB: 25, PR: 41, PE: 26, PI: 22,
  RJ: 33, RN: 24, RS: 43, RO: 11, RR: 14, SC: 42, SP: 35, SE: 28, TO: 17,
};
const UF2NOME = Object.fromEntries(Object.entries(NOME2UF).map(([n, s]) => [s, n]));
const METRICAS = {
  media_geral: "Média geral", media_red: "Redação", media_lc: "Linguagens",
  media_ch: "Humanas", media_cn: "Natureza", media_mt: "Matemática",
};
const COR_CLARA = "#fdeef7", COR_ESCURA = "#b00073", SEM_DADOS = "#e9e5d4";
const W = 640, H = 600;

let metrica = "media_geral";
let rede = "T";                        // T | PUB | PRIV
let vista = { nivel: "BR" };          // ou { nivel: "UF", uf: "PR" }
let dados = [];                        // linhas da API na vista atual
let porChave = {};                     // chave -> linha
let gPaths = null;
let chaveDe = null;                    // (feature) -> chave nos dados
const cacheTopo = {};                  // uf -> FeatureCollection

const fmt0 = (v) => (v == null ? "–" : Math.round(v).toLocaleString("pt-BR"));
const tip = document.getElementById("map-tip");
const wrap = document.getElementById("mapa-wrap");

function desenha(features, aoClicar, rotulo) {
  wrap.innerHTML = "";
  const svg = d3.select(wrap).append("svg")
    .attr("viewBox", `0 0 ${W} ${H}`).attr("width", "100%")
    .attr("role", "img")
    .attr("aria-label", "Mapa coroplético com as médias do ENEM 2025");
  const fc = { type: "FeatureCollection", features };
  const path = d3.geoPath(d3.geoMercator().fitSize([W, H], fc));

  gPaths = svg.append("g").selectAll("path")
    .data(features).join("path")
    .attr("d", path)
    .attr("stroke", "#3b142a")
    .attr("stroke-width", vista.nivel === "BR" ? 0.8 : 0.4)
    .style("cursor", "pointer")
    .on("mousemove", (ev, d) => {
      const r = porChave[chaveDe(d)];
      tip.hidden = false;
      tip.innerHTML = r ? `<b>${r.nome}${vista.nivel === "BR" ? ` (${r.chave})` : ""}</b>
          ${METRICAS[metrica]}: <b style="color:var(--lime)">${fmt0(r[metrica])}</b><br>
          Geral ${fmt0(r.media_geral)} · Redação ${fmt0(r.media_red)}<br>
          LC ${fmt0(r.media_lc)} · CH ${fmt0(r.media_ch)} ·
          CN ${fmt0(r.media_cn)} · MT ${fmt0(r.media_mt)}<br>
          <span style="color:var(--rose)">${(+r.n_participantes).toLocaleString("pt-BR")} concluintes</span>
          <span class="tip-cta">${vista.nivel === "BR"
            ? "Clique para ver os municípios →" : "Clique para abrir no painel →"}</span>`
        : `<b>${rotulo(d)}</b>Sem concluintes com escola identificada no ENEM 2025.`;
      tip.style.left = `${Math.min(ev.clientX + 14, innerWidth - 350)}px`;
      tip.style.top = `${ev.clientY + 14}px`;
    })
    .on("mouseleave", () => { tip.hidden = true; })
    .on("click", (ev, d) => { tip.hidden = true; aoClicar(d); });

  if (vista.nivel === "BR") {
    svg.append("g").selectAll("text")
      .data(features).join("text")
      .attr("transform", (d) => `translate(${path.centroid(d)})`)
      .attr("text-anchor", "middle").attr("dy", "0.35em")
      .style("font", "700 11px 'DM Sans', sans-serif")
      .style("pointer-events", "none")
      .text((d) => path.area(d) > 900 ? chaveDe(d) : "");
  }
}

function pinta() {
  const vals = dados.map((d) => +d[metrica]).filter(Boolean);
  const [mn, mx] = [Math.min(...vals), Math.max(...vals)];
  const cor = d3.scaleLinear().domain([mn, mx])
    .range([COR_CLARA, COR_ESCURA]).interpolate(d3.interpolateLab);

  gPaths.transition().duration(400).attr("fill", (d) => {
    const r = porChave[chaveDe(d)];
    return r && r[metrica] ? cor(+r[metrica]) : SEM_DADOS;
  });

  document.getElementById("leg-min").textContent = fmt0(mn);
  document.getElementById("leg-max").textContent = fmt0(mx);
  document.querySelector(".leg-grad").style.background =
    `linear-gradient(90deg, ${COR_CLARA}, ${COR_ESCURA})`;

  document.getElementById("rank-titulo").textContent =
    `Ranking · ${METRICAS[metrica]}`;
  const incluiPequenos = document.getElementById("chk-minn").checked;
  const ord = [...dados].filter((d) => d[metrica] &&
      (incluiPequenos || +d.n_participantes >= 30))
    .sort((a, b) => b[metrica] - a[metrica]);
  const conc = (n) => `${(+n).toLocaleString("pt-BR")} concluinte${+n === 1 ? "" : "s"}`;
  const linkDe = (r) => vista.nivel === "BR"
    ? `mapa.html?uf=${r.chave}` : `index.html?uf=${vista.uf}&mun=${r.chave}`;
  document.getElementById("ranking").innerHTML = ord.map((r, i) => `
    <a class="rank-row" href="${linkDe(r)}" ${vista.nivel === "BR"
        ? `onclick="event.preventDefault(); abreEstado('${r.chave}')"` : ""}>
      <span class="rank-pos">${i + 1}</span>
      <span class="rank-uf" title="${r.nome} · ${conc(r.n_participantes)}">
        ${r.nome}<small>${conc(r.n_participantes)}</small>
      </span>
      <span class="rank-bar"><span style="width:${
        Math.max(5, ((r[metrica] - mn) / (mx - mn || 1)) * 100)}%;
        background:${cor(+r[metrica])}"></span></span>
      <span class="rank-val">${fmt0(r[metrica])}</span>
    </a>`).join("");
}

/* ---------------- vistas --------------------------------------------------- */
async function abreBrasil() {
  vista = { nivel: "BR" };
  document.getElementById("mapa-titulo").textContent = "Brasil";
  document.getElementById("btn-brasil").hidden = true;
  history.replaceState(null, "", "mapa.html");

  const [ufsApi, topo] = await Promise.all([
    fetch(window.API_STATIC ? "api/ufs.json" : `/api/ufs?rede=${rede}`)
      .then((r) => r.json())
      .then((d) => (window.API_STATIC ? d[rede] || [] : d)),
    cacheTopo.BR ? Promise.resolve(cacheTopo.BR)
      : fetch("https://cdn.jsdelivr.net/npm/datamaps@0.5.10/src/js/data/bra.topo.json")
          .then((r) => r.json())
          .then((t) => (cacheTopo.BR = topojson.feature(t, t.objects.bra))),
  ]);
  dados = ufsApi.map((r) => ({ ...r, nome: UF2NOME[r.chave] || r.chave }));
  porChave = Object.fromEntries(dados.map((d) => [d.chave, d]));
  chaveDe = (d) => NOME2UF[d.properties.name];
  desenha(cacheTopo.BR.features,
    (d) => abreEstado(NOME2UF[d.properties.name]),
    (d) => d.properties.name);
  pinta();
}

async function abreEstado(uf) {
  vista = { nivel: "UF", uf };
  document.getElementById("mapa-titulo").textContent =
    `${UF2NOME[uf]} · municípios`;
  document.getElementById("btn-brasil").hidden = false;
  history.replaceState(null, "", `mapa.html?uf=${uf}`);
  wrap.innerHTML = `<div class="skeleton">Carregando municípios de ${UF2NOME[uf]}…</div>`;

  const [muns, fc] = await Promise.all([
    fetch(window.API_STATIC ? `api/municipios/${uf}.json`
                            : `/api/municipios?uf=${uf}&rede=${rede}`)
      .then((r) => r.json())
      .then((d) => (window.API_STATIC ? d[rede] || [] : d)),
    cacheTopo[uf] ? Promise.resolve(cacheTopo[uf])
      : fetch(`https://servicodados.ibge.gov.br/api/v3/malhas/estados/${UF2COD[uf]}` +
              `?formato=application/json&qualidade=minima&intrarregiao=municipio`)
          .then((r) => r.json())
          .then((t) => {
            const k = Object.keys(t.objects)[0];
            return (cacheTopo[uf] = topojson.feature(t, t.objects[k]));
          }),
  ]);
  dados = muns;
  porChave = Object.fromEntries(dados.map((d) => [String(d.chave), d]));
  chaveDe = (d) => String(d.properties.codarea);
  desenha(cacheTopo[uf].features,
    (d) => {
      const r = porChave[chaveDe(d)];
      if (r) location.href = `index.html?uf=${uf}&mun=${r.chave}`;
    },
    (d) => `Município ${d.properties.codarea}`);
  pinta();
}
window.abreEstado = abreEstado;

document.getElementById("btn-brasil").addEventListener("click", abreBrasil);
document.getElementById("chk-minn").addEventListener("change", pinta);
document.querySelectorAll("#tabs-rede button").forEach((b) => {
  b.addEventListener("click", () => {
    document.querySelectorAll("#tabs-rede button").forEach((x) => x.classList.remove("on"));
    b.classList.add("on");
    rede = b.dataset.rede;
    vista.nivel === "BR" ? abreBrasil() : abreEstado(vista.uf);
  });
});
document.querySelectorAll("#tabs-metrica button").forEach((b) => {
  b.addEventListener("click", () => {
    document.querySelectorAll("#tabs-metrica button").forEach((x) => x.classList.remove("on"));
    b.classList.add("on");
    metrica = b.dataset.m;
    pinta();
  });
});

/* deep-link: mapa.html?uf=PR abre direto no estado */
const ufInicial = new URLSearchParams(location.search).get("uf");
if (ufInicial && UF2COD[ufInicial.toUpperCase()]) {
  abreEstado(ufInicial.toUpperCase());
} else {
  abreBrasil();
}
