/* Mapa coroplético do Brasil — médias por UF, drill-down para municípios,
 * painel de detalhes lateral com KPIs, distribuição de nota (histograma +
 * curva do Brasil), top escolas e ranking. */

const NOME2UF = {
  "Acre":"AC","Alagoas":"AL","Amapá":"AP","Amazonas":"AM","Bahia":"BA",
  "Ceará":"CE","Distrito Federal":"DF","Espírito Santo":"ES","Goiás":"GO",
  "Maranhão":"MA","Mato Grosso":"MT","Mato Grosso do Sul":"MS","Minas Gerais":"MG",
  "Pará":"PA","Paraíba":"PB","Paraná":"PR","Pernambuco":"PE","Piauí":"PI",
  "Rio de Janeiro":"RJ","Rio Grande do Norte":"RN","Rio Grande do Sul":"RS",
  "Rondônia":"RO","Roraima":"RR","Santa Catarina":"SC","São Paulo":"SP",
  "Sergipe":"SE","Tocantins":"TO",
};
const UF2COD = {
  AC:12,AL:27,AP:16,AM:13,BA:29,CE:23,DF:53,ES:32,GO:52,MA:21,MT:51,MS:50,
  MG:31,PA:15,PB:25,PR:41,PE:26,PI:22,RJ:33,RN:24,RS:43,RO:11,RR:14,SC:42,
  SP:35,SE:28,TO:17,
};
const UF2NOME = Object.fromEntries(Object.entries(NOME2UF).map(([n, s]) => [s, n]));
const METRICAS = {
  media_geral: "Média geral", media_red: "Redação", media_lc: "Linguagens",
  media_ch: "Humanas", media_cn: "Natureza", media_mt: "Matemática",
};
const CAMPO_METRICA = {
  media_geral: "geral", media_lc: "lc", media_ch: "ch",
  media_cn: "cn", media_mt: "mt", media_red: "red",
};
const COR_CLARA = "#fdeef7", COR_ESCURA = "#b00073", SEM_DADOS = "#e9e5d4";
const W = 640, H = 600;
const $ = (s) => document.querySelector(s);
const fmt0 = (v) => (v == null ? "–" : Math.round(v).toLocaleString("pt-BR"));
const fmtInt = (v) => (v == null ? "–" : (+v).toLocaleString("pt-BR"));

/* filtros globais persistentes */
const globais = window.Filtros ? window.Filtros.carregar() : {};

let metrica = "media_geral";
let rede = globais.rede || "T";
let vista = { nivel: "BR" };
let dados = [];
let porChave = {};
let gPaths = null;
let chaveDe = null;
const cacheTopo = {};

const tip = $("#map-tip");
const wrap = $("#mapa-wrap");

/* ============================================================ mapa ======= */
function desenha(features, aoClicar, rotulo) {
  wrap.innerHTML = "";
  const svg = d3.select(wrap).append("svg")
    .attr("viewBox", `0 0 ${W} ${H}`).attr("width", "100%")
    .attr("role", "img");
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
      tip.innerHTML = r
        ? `<b>${r.nome}${vista.nivel === "BR" ? ` (${r.chave})` : ""}</b>
           ${METRICAS[metrica]}: <b style="color:var(--lime)">${fmt0(r[metrica])}</b><br>
           <span style="color:var(--rose)">${fmtInt(r.n_participantes)} concluintes</span>
           <span class="tip-cta">${vista.nivel === "BR"
             ? "Clique para abrir os municípios →"
             : "Clique para ver detalhes →"}</span>`
        : `<b>${rotulo(d)}</b>Sem concluintes com escola identificada em 2025.`;
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

  gPaths?.transition().duration(400).attr("fill", (d) => {
    const r = porChave[chaveDe(d)];
    return r && r[metrica] ? cor(+r[metrica]) : SEM_DADOS;
  });

  $("#leg-min").textContent = fmt0(mn);
  $("#leg-max").textContent = fmt0(mx);
  $(".leg-grad").style.background = `linear-gradient(90deg, ${COR_CLARA}, ${COR_ESCURA})`;

  // ranking (UFs ou municípios)
  $("#rank-titulo").textContent = vista.nivel === "BR"
    ? `Estados · ${METRICAS[metrica]}` : `Municípios · ${METRICAS[metrica]}`;
  const incluiPequenos = $("#chk-minn").checked;
  const ord = [...dados].filter((d) => d[metrica] &&
      (incluiPequenos || +d.n_participantes >= 30))
    .sort((a, b) => b[metrica] - a[metrica]);
  const conc = (n) => `${(+n).toLocaleString("pt-BR")} concluinte${+n === 1 ? "" : "s"}`;
  $("#ranking").innerHTML = ord.map((r, i) => {
    // BR: clique carrega municípios; UF: clique carrega detalhes do município
    const onclick = vista.nivel === "BR"
      ? `event.preventDefault(); abreEstado('${r.chave}')`
      : `event.preventDefault(); abreMunicipio('${r.chave}')`;
    return `<a class="rank-row" href="#" onclick="${onclick}">
      <span class="rank-pos">${i + 1}</span>
      <span class="rank-uf" title="${r.nome} · ${conc(r.n_participantes)}">
        ${r.nome}<small>${conc(r.n_participantes)}</small>
      </span>
      <span class="rank-bar"><span style="width:${
        Math.max(5, ((r[metrica] - mn) / (mx - mn || 1)) * 100)}%;
        background:${cor(+r[metrica])}"></span></span>
      <span class="rank-val">${fmt0(r[metrica])}</span>
    </a>`;
  }).join("");
}

/* ============================================================ vistas ==== */
async function j(url) { return fetch(url).then((r) => r.ok ? r.json() : null); }

async function abreBrasil() {
  vista = { nivel: "BR" };
  $("#mapa-titulo").textContent = "Brasil";
  $("#btn-brasil").hidden = true;
  history.replaceState(null, "", "mapa.html");

  const [ufsApi, topo] = await Promise.all([
    j("api/ufs.json").then((d) => d?.[rede] || []),
    cacheTopo.BR ? Promise.resolve(cacheTopo.BR)
      : j("https://cdn.jsdelivr.net/npm/datamaps@0.5.10/src/js/data/bra.topo.json")
          .then((t) => (cacheTopo.BR = topojson.feature(t, t.objects.bra))),
  ]);
  dados = ufsApi.map((r) => ({ ...r, nome: UF2NOME[r.chave] || r.chave }));
  porChave = Object.fromEntries(dados.map((d) => [d.chave, d]));
  chaveDe = (d) => NOME2UF[d.properties.name];
  desenha(cacheTopo.BR.features,
    (d) => abreEstado(NOME2UF[d.properties.name]),
    (d) => d.properties.name);
  pinta();
  await carregarDetalhes({ nivel: "BR", chave: "BR", nome: "Brasil" });
}

async function abreEstado(uf) {
  vista = { nivel: "UF", uf };
  $("#mapa-titulo").textContent = `${UF2NOME[uf]} · municípios`;
  $("#btn-brasil").hidden = false;
  history.replaceState(null, "", `mapa.html?uf=${uf}`);
  wrap.innerHTML = `<div class="skeleton">Carregando municípios de ${UF2NOME[uf]}…</div>`;

  const [muns, fc] = await Promise.all([
    j(`api/municipios/${uf}.json`).then((d) => d?.[rede] || []),
    cacheTopo[uf] ? Promise.resolve(cacheTopo[uf])
      : j(`https://servicodados.ibge.gov.br/api/v3/malhas/estados/${UF2COD[uf]}` +
          `?formato=application/json&qualidade=minima&intrarregiao=municipio`)
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
      if (r) abreMunicipio(r.chave);
    },
    (d) => `Município ${d.properties.codarea}`);
  pinta();
  await carregarDetalhes({ nivel: "UF", chave: uf, nome: UF2NOME[uf] });
}

async function abreMunicipio(chave) {
  const r = porChave[String(chave)];
  const nome = r ? r.nome : `Município ${chave}`;
  await carregarDetalhes({ nivel: "MUN", chave: String(chave), nome });
}

window.abreEstado = abreEstado;
window.abreMunicipio = abreMunicipio;

/* ============================================================ detalhes == */
async function carregarDetalhes(alvo) {
  try {
    const { nivel, chave, nome } = alvo;
    $("#det-titulo").textContent = nome;
    $("#det-sub").textContent = REDE_TXT();
    $("#det-kpis").innerHTML = `<div class="skeleton">Carregando…</div>`;
    $("#card-hist").hidden = true;
    $("#top-esc-body").innerHTML =
      `<div class="skeleton" style="padding:12px">Carregando…</div>`;

    const ent = await j(`api/entidade/${nivel}/${chave}.json`);
    if (!ent) {
      $("#det-kpis").innerHTML = `<div class="skeleton">Sem dados.</div>`;
      $("#top-esc-body").innerHTML = "";
      return;
    }
    const bloco = ent[rede];
    const alvoResumo = bloco?.resumo?.alvo || (nivel === "ESC" ? ent.resumo?.alvo : null);
    if (!alvoResumo) {
      $("#det-kpis").innerHTML =
        `<div class="skeleton">Sem dados na ${REDE_TXT()}.</div>`;
      $("#top-esc-body").innerHTML = "";
      return;
    }
    renderKpis(alvoResumo, nivel, chave);
    await renderHistograma(bloco?.hist_nota, nome, alvo);
    await renderTopEscolas(alvo);
  } catch (err) {
    console.error("carregarDetalhes:", err);
    $("#det-kpis").innerHTML =
      `<div class="skeleton" style="color:var(--red-bad)">Erro: ${err.message}</div>`;
    $("#top-esc-body").innerHTML = "";
  }
}

function REDE_TXT() {
  return { T: "todas as redes", PUB: "rede pública", PRIV: "rede privada" }[rede];
}

function renderKpis(alvo, nivel, chave) {
  const el = $("#det-kpis");
  const linkPainel = nivel === "BR"
    ? `index.html`
    : nivel === "UF"
      ? `index.html?uf=${chave}`
      : `index.html?uf=${alvo.uf}&mun=${chave}`;

  el.innerHTML = `
    <div class="det-n">
      <div class="det-n-val">${fmtInt(alvo.n_participantes)}</div>
      <div class="det-n-lbl">concluintes com escola em 2025 · ${REDE_TXT()}</div>
    </div>
    <div class="det-medias">
      ${[
        ["Média geral", "media_geral", "var(--pink)"],
        ["Redação",     "media_red",   "var(--rose)"],
        ["Linguagens",  "media_lc",    "var(--lilac)"],
        ["Humanas",     "media_ch",    "var(--peach)"],
        ["Natureza",    "media_cn",    "var(--mint)"],
        ["Matemática",  "media_mt",    "var(--lime)"],
      ].map(([nome, campo, cor]) => `
        <div class="det-m">
          <div class="det-m-lbl" style="border-left:3px solid ${cor}">${nome}</div>
          <div class="det-m-val">${fmt0(alvo[campo])}</div>
        </div>`).join("")}
    </div>
    <a class="det-cta" href="${linkPainel}">Abrir painel completo →</a>`;
}

let histBRcache = {};
async function renderHistograma(histAlvo, nomeAlvo, alvo) {
  if (!histAlvo) {
    $("#card-hist").hidden = true;
    return;
  }
  $("#card-hist").hidden = false;
  $("#hist-titulo").textContent =
    `Distribuição da nota · ${METRICAS[metrica]}`;
  // busca a mesma métrica no Brasil pra sobrepor como referência
  if (!histBRcache[rede]) {
    const br = await j(`api/entidade/BR/BR.json`);
    histBRcache[rede] = br?.[rede]?.hist_nota || null;
  }
  const campo = CAMPO_METRICA[metrica];
  const distAlvo = histAlvo[campo] || {};
  const distBR = (histBRcache[rede] || {})[campo] || {};
  if (alvo.nivel === "BR") {
    // já é o próprio Brasil — não sobrepõe (linha idêntica)
    desenharHistograma(distAlvo, null, nomeAlvo);
    $("#hist-hint").textContent = "distribuição em faixas de 25 pontos (nota TRI 0-1000)";
  } else {
    desenharHistograma(distAlvo, distBR, nomeAlvo);
    $("#hist-hint").innerHTML = `barras = ${nomeAlvo} · <span style="color:var(--lilac);font-weight:700">linha</span> = Brasil (mesma rede)`;
  }
}

function desenharHistograma(dist, distRef, nomeAlvo) {
  const buckets = [];
  for (let b = 0; b <= 975; b += 25) buckets.push(b);
  const nAlvo = buckets.map((b) => dist[b] || 0);
  const totalAlvo = nAlvo.reduce((s, v) => s + v, 0);
  const pctAlvo = totalAlvo ? nAlvo.map((v) => v / totalAlvo) : nAlvo;

  const pctRef = distRef ? (() => {
    const nRef = buckets.map((b) => distRef[b] || 0);
    const t = nRef.reduce((s, v) => s + v, 0) || 1;
    return nRef.map((v) => v / t);
  })() : null;

  const maxY = Math.max(
    ...pctAlvo,
    ...(pctRef || [0]),
  ) * 1.05 || 0.01;

  const W = 620, H = 240, padL = 44, padR = 12, padT = 12, padB = 30;
  const iw = W - padL - padR;
  const ih = H - padT - padB;
  const bw = iw / buckets.length;
  const xFor = (i) => padL + i * bw;
  const yFor = (p) => padT + ih - (p / maxY) * ih;

  // eixo Y (5 gridlines em % dos alunos)
  let grids = "";
  for (let i = 0; i <= 4; i++) {
    const yv = (maxY * i) / 4;
    const y = yFor(yv).toFixed(1);
    grids += `<line class="grid" x1="${padL}" x2="${W-padR}" y1="${y}" y2="${y}"/>
              <text class="axis" x="${padL-6}" y="${y}" text-anchor="end" dy="0.32em">${Math.round(yv*100)}%</text>`;
  }
  // eixo X (marcas em 0, 250, 500, 750, 1000)
  let xax = "";
  [0, 250, 500, 750, 1000].forEach((v) => {
    const ix = Math.round(v / 25);
    xax += `<text class="axis" x="${xFor(ix) + bw/2}" y="${H - padB + 16}" text-anchor="middle">${v}</text>`;
  });

  // barras
  const bars = pctAlvo.map((p, i) => {
    const h = ih - (yFor(p) - padT);
    return `<rect class="h-bar" x="${xFor(i) + 1}" y="${yFor(p)}"
                  width="${(bw - 2).toFixed(1)}" height="${h.toFixed(1)}"
                  data-bucket="${buckets[i]}" data-p="${p}"/>`;
  }).join("");
  // linha de referência (BR)
  let refPath = "";
  if (pctRef) {
    let d = "";
    pctRef.forEach((p, i) => {
      const cx = xFor(i) + bw / 2, cy = yFor(p);
      d += (i === 0 ? "M" : "L") + cx.toFixed(1) + " " + cy.toFixed(1);
    });
    refPath = `<path d="${d}" fill="none" stroke="var(--lilac)" stroke-width="2.5"
                     stroke-linecap="round" stroke-linejoin="round"/>`;
  }
  $("#hist-body").innerHTML = `
    <div class="hist-wrap">
      <svg class="hist-svg" viewBox="0 0 ${W} ${H}" preserveAspectRatio="xMidYMid meet">
        ${grids}${xax}${bars}${refPath}
      </svg>
      <div class="hist-legend">
        <span class="hist-total">Total: ${fmtInt(totalAlvo)} concluintes</span>
      </div>
    </div>`;
}

/* -------- top escolas --------------------------------------------------- */
async function renderTopEscolas(alvo) {
  const { nivel, chave, nome } = alvo;
  $("#top-esc-titulo").textContent = `Top escolas · ${nome}`;
  const url = nivel === "BR" ? `api/top_escolas/BR.json`
            : nivel === "UF" ? `api/top_escolas/UF/${chave}.json`
            :                  `api/top_escolas/MUN/${chave}.json`;
  const data = await j(url);
  const lst = (data && data[rede]) || [];
  if (!lst.length) {
    $("#top-esc-body").innerHTML =
      `<div class="skeleton" style="padding:12px">Nenhuma escola na ${REDE_TXT()}.</div>`;
    return;
  }
  const linhas = lst.slice(0, 10).map((e, i) => {
    const rot = e.nome || `Escola INEP ${e.chave}`;
    const dep = e.dependencia_nome ? ` · ${e.dependencia_nome}` : "";
    const loc = nivel === "BR" ? ` · ${e.municipio}/${e.uf}`
              : nivel === "UF" ? ` · ${e.municipio}` : "";
    return `<a class="top-esc-row"
              href="index.html?uf=${e.uf}&mun=${e.co_municipio || ""}&esc=${e.chave}"
              title="${rot}${dep}${loc}">
      <span class="rank-pos">${i + 1}</span>
      <span class="top-esc-nome">
        ${rot}<small>${dep}${loc} · ${fmtInt(e.n_participantes)} concluintes</small>
      </span>
      <span class="top-esc-val">${fmt0(e.media_geral)}</span>
    </a>`;
  }).join("");
  // botão "Ver todas" — só faz sentido em BR e UF (MUN quase sempre mostra tudo)
  const linkFull = nivel === "BR" ? `ranking_escolas.html`
                : nivel === "UF" ? `ranking_escolas.html?uf=${chave}` : "";
  const verTodas = (nivel !== "MUN" && lst.length > 10)
    ? `<a class="top-esc-vermais" href="${linkFull}">
         Ver todas as ${fmtInt(lst.length)}+ escolas →
       </a>`
    : "";
  $("#top-esc-body").innerHTML = linhas + verTodas;
}

/* ============================================================ handlers == */
$("#btn-brasil").addEventListener("click", abreBrasil);
$("#chk-minn").addEventListener("change", pinta);
document.querySelectorAll("#tabs-rede button").forEach((b) => {
  b.addEventListener("click", () => {
    document.querySelectorAll("#tabs-rede button").forEach((x) => x.classList.remove("on"));
    b.classList.add("on");
    rede = b.dataset.rede;
    histBRcache = {};
    if (window.Filtros) window.Filtros.salvar({ ...globais, rede });
    vista.nivel === "BR" ? abreBrasil() : abreEstado(vista.uf);
  });
});
if (rede !== "T") {
  document.querySelectorAll("#tabs-rede button").forEach((x) => {
    x.classList.toggle("on", x.dataset.rede === rede);
  });
}
document.querySelectorAll("#tabs-metrica button").forEach((b) => {
  b.addEventListener("click", () => {
    document.querySelectorAll("#tabs-metrica button").forEach((x) => x.classList.remove("on"));
    b.classList.add("on");
    metrica = b.dataset.m;
    pinta();
    // recarrega histograma (mudou a métrica → mudou o campo)
    const alvoAtual = { nivel: "BR", chave: "BR", nome: "Brasil" };
    if (vista.nivel === "UF") {
      alvoAtual.nivel = "UF"; alvoAtual.chave = vista.uf; alvoAtual.nome = UF2NOME[vista.uf];
    }
    carregarDetalhes(alvoAtual);
  });
});

/* deep-link: mapa.html?uf=PR */
const ufInicial = new URLSearchParams(location.search).get("uf")
  || globais.uf;
if (ufInicial && UF2COD[ufInicial.toUpperCase()]) {
  abreEstado(ufInicial.toUpperCase());
} else {
  abreBrasil();
}
