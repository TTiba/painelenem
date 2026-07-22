/* Habilidades críticas — tabela heatmap: linhas = habilidades, colunas =
 * anos + média + esperado TRI. Respeita filtros da URL (uf/mun/esc/rede).
 * Se sem filtro, mostra BR.
 */
const AREA_INFO = {
  LC: { nome: "Linguagens", cor: "var(--lilac)", chip: "LC" },
  CH: { nome: "Humanas",    cor: "var(--peach)", chip: "CH" },
  CN: { nome: "Natureza",   cor: "var(--mint)",  chip: "CN" },
  MT: { nome: "Matemática", cor: "var(--lime)",  chip: "MT" },
};
const ANOS = [2021, 2022, 2023, 2024, 2025];
const REDE_NOME = { T: "todas as redes", PUB: "rede pública", PRIV: "rede privada" };

const $ = (s) => document.querySelector(s);
const params = new URLSearchParams(location.search);

const globais = window.Filtros ? window.Filtros.carregar() : {};
const state = {
  area: params.get("area") || "",
  sort_col: "delta",    // "area"|"h"|"desc"|"a0..a4"|"media"|"esperado"|"delta"
  sort_dir: "asc",      // "asc" | "desc"
  uf: globais.uf || "",
  mun: globais.mun || "",
  esc: globais.esc || "",
  rede: globais.rede || "T",
  anos_ativos: new Set(ANOS),   // anos considerados no cálculo de média/esperado
};
// direção default por coluna: números começam "asc" (piores primeiro),
// texto começa "asc" (alfabético). Δ e média começam ascendente pra listar
// os mais críticos primeiro.
const SORT_DEFAULT_DIR = {
  area: "asc", h: "asc", desc: "asc",
  a0: "asc", a1: "asc", a2: "asc", a3: "asc", a4: "asc",
  media: "asc", esperado: "asc", delta: "asc",
};

function nivelChave() {
  if (state.esc) return { nivel: "ESC", chave: state.esc };
  if (state.mun) return { nivel: "MUN", chave: state.mun };
  if (state.uf)  return { nivel: "UF",  chave: state.uf };
  return { nivel: "BR", chave: "BR" };
}
function rotuloAlvo() {
  const partes = [];
  if (state.esc) partes.push(`Escola INEP ${state.esc}`);
  else if (state.mun) partes.push(`Município ${state.mun}`);
  else if (state.uf)  partes.push(state.uf);
  else partes.push("Brasil");
  partes.push(REDE_NOME[state.rede]);
  return partes.join(" · ");
}

let habIndex = null;   // api/habilidades/index.json (descrições + habilidades cobrando)
let dataAlvo = null;   // computação {area: {h: {anos:[5], media, esp}}}

/* ----------- fetches --------------------------------------------------- */
async function carregarDados() {
  habIndex = await fetch("api/habilidades/index.json").then((r) => r.json());
  const { nivel, chave } = nivelChave();

  // ESC não tem historico/. Fallback: usa BR e mostra aviso.
  if (nivel === "ESC") {
    return await carregarBR(); // simplifica
  }
  const hist = await fetch(`api/historico/${nivel}/${chave}.json`).then((r) => r.ok ? r.json() : null);
  if (!hist) return await carregarBR();
  return computarDeHistorico(hist);
}
async function carregarBR() {
  const hist = await fetch(`api/historico/BR/BR.json`).then((r) => r.ok ? r.json() : null);
  if (!hist) throw new Error("historico BR ausente");
  return computarDeHistorico(hist);
}

/* Agrega itens da 7-tupla [item, n, p, p_esp, hab, param_b, tp_lingua] em
 * médias ponderadas por (area, habilidade, ano). Também acumula esperado
 * pelo mesmo n. */
function computarDeHistorico(hist) {
  const rede = state.rede;
  const out = { LC: {}, CH: {}, CN: {}, MT: {} };
  for (const area of Object.keys(out)) {
    for (const h of Object.keys(habIndex.areas[area] || {})) {
      out[area][h] = { anos: ANOS.map(() => null), esp: ANOS.map(() => null),
                        n: ANOS.map(() => 0) };
    }
  }
  for (let i = 0; i < ANOS.length; i++) {
    const ano = ANOS[i];
    const bloco = hist?.[rede]?.por_ano?.[String(ano)];
    if (!bloco) continue;
    for (const area of Object.keys(out)) {
      const lst = bloco[area] || [];
      const agg = {};   // hab → {sn, sp, se}
      for (const [, n, p, p_esp, hab] of lst) {
        if (hab == null || !n) continue;
        const a = agg[hab] || { sn: 0, sp: 0, se: 0, ne: 0 };
        a.sn += n;
        if (p != null) a.sp += p * n;
        if (p_esp != null) { a.se += p_esp * n; a.ne += n; }
        agg[hab] = a;
      }
      for (const [hab, a] of Object.entries(agg)) {
        if (!out[area][hab]) continue;
        out[area][hab].anos[i] = a.sn ? a.sp / a.sn : null;
        out[area][hab].esp[i] = a.ne ? a.se / a.ne : null;
        out[area][hab].n[i] = a.sn;
      }
    }
  }
  // agregações finais (média/esperado/delta) ficam a cargo de agregar(),
  // pra respeitar o filtro de anos ativos sem precisar refazer o fetch.
  return out;
}

/* Recalcula média/esperado/delta considerando somente state.anos_ativos.
 * É chamado no render — não é preciso refetch quando muda a seleção. */
function agregar(cell) {
  let sn = 0, sp = 0, se = 0, sne = 0;
  cell.anos.forEach((p, i) => {
    if (!state.anos_ativos.has(ANOS[i])) return;
    const n = cell.n[i];
    if (p != null && n) { sn += n; sp += p * n; }
    if (cell.esp[i] != null && n) { sne += n; se += cell.esp[i] * n; }
  });
  const media = sn ? sp / sn : null;
  const esperado = sne ? se / sne : null;
  const delta = (media != null && esperado != null) ? media - esperado : null;
  return { media, esperado, delta };
}

/* ----------- coloração --------------------------------------------------- */
function corAcerto(p) {
  if (p == null) return "transparent";
  // escala vermelho → amarelo → verde-lima (verde tipo Wayground)
  // p em [0..1], centrada em 0.5
  const t = Math.max(0, Math.min(1, p));
  const r1 = [255, 143, 143], y = [251, 235, 132], g = [187, 227, 138];
  const mix = (a, b, k) => `rgb(${Math.round(a[0] + (b[0]-a[0])*k)},${Math.round(a[1] + (b[1]-a[1])*k)},${Math.round(a[2] + (b[2]-a[2])*k)})`;
  if (t < 0.5) return mix(r1, y, t / 0.5);
  return mix(y, g, (t - 0.5) / 0.5);
}
function corDelta(d) {
  if (d == null) return "transparent";
  // divergente centrado em 0 (± 15pp = saturado)
  const t = Math.min(1, Math.abs(d) / 0.15);
  const base = d >= 0 ? [187, 227, 138] : [255, 143, 143];
  const alfa = 0.20 + t * 0.80;
  return `rgba(${base[0]},${base[1]},${base[2]},${alfa.toFixed(2)})`;
}

/* ----------- render ----------------------------------------------------- */
function render() {
  if (!dataAlvo || !habIndex) return;
  const alvoTxt = rotuloAlvo();
  const alvoEl = document.getElementById("crit-alvo");
  alvoEl.innerHTML = `Analisando: <b>${alvoTxt}</b>`;
  alvoEl.hidden = false;

  const areas = state.area ? [state.area] : ["LC", "CH", "CN", "MT"];
  const linhas = [];
  for (const area of areas) {
    const cells = habIndex.areas[area] || {};
    for (const [h, info] of Object.entries(cells)) {
      const cell = dataAlvo[area]?.[h];
      if (!cell) continue;
      const agg = agregar(cell);
      linhas.push({
        area, h: parseInt(h, 10), desc: info.desc || "",
        anos: cell.anos, media: agg.media, esperado: agg.esperado, delta: agg.delta,
      });
    }
  }

  // ordena conforme coluna clicada
  const col = state.sort_col;
  const dir = state.sort_dir === "desc" ? -1 : 1;
  const AREA_ORDER = ["LC", "CH", "CN", "MT"];
  function chave(l) {
    if (col === "area") return AREA_ORDER.indexOf(l.area) * 100 + l.h;   // preserva Hs dentro da área
    if (col === "h") return l.h;
    if (col === "desc") return (l.desc || "").toLowerCase();
    if (col.startsWith("a")) return l.anos[parseInt(col.slice(1), 10)];
    return l[col];
  }
  linhas.sort((a, b) => {
    const va = chave(a), vb = chave(b);
    // null/undefined sempre no fim
    const nullA = va == null || va === "";
    const nullB = vb == null || vb === "";
    if (nullA && nullB) return 0;
    if (nullA) return 1;
    if (nullB) return -1;
    if (typeof va === "string" && typeof vb === "string") {
      return va.localeCompare(vb, "pt-BR") * dir;
    }
    return (va - vb) * dir;
  });

  // atualiza indicadores nos <th>
  document.querySelectorAll("#crit-thead th.sortable").forEach((th) => {
    th.classList.remove("sort-asc", "sort-desc");
    if (th.dataset.sort === col) th.classList.add(dir === 1 ? "sort-asc" : "sort-desc");
  });

  // sumário
  $("#crit-resumo").innerHTML = `${linhas.length} habilidades no grupo`;

  // atualiza rótulo da coluna Média conforme anos ativos
  const anosSel = ANOS.filter((a) => state.anos_ativos.has(a));
  const lblMed = $("#crit-media-lbl");
  if (lblMed) {
    if (anosSel.length === ANOS.length) {
      lblMed.textContent = "2021 – 2025";
    } else if (anosSel.length === 1) {
      lblMed.textContent = String(anosSel[0]);
    } else if (anosSel.length && anosSel[anosSel.length-1] - anosSel[0] === anosSel.length - 1) {
      lblMed.textContent = `${anosSel[0]} – ${anosSel[anosSel.length-1]}`;
    } else {
      lblMed.textContent = anosSel.join(" · ");
    }
  }

  // linhas
  const tb = document.getElementById("crit-tbody");
  tb.innerHTML = linhas.map((l) => {
    const info = AREA_INFO[l.area];
    const cel = (p, extraCls = "") => {
      if (p == null) return `<td class="crit-cel-vazio ${extraCls}">—</td>`;
      const pct = Math.round(p * 100);
      return `<td class="crit-cel ${extraCls}" style="background:${corAcerto(p)}">${pct}%</td>`;
    };
    const celEsp = (p) => {
      if (p == null) return `<td class="crit-cel-vazio crit-col-esp">—</td>`;
      const pct = Math.round(p * 100);
      return `<td class="crit-cel crit-col-esp" style="background:${corAcerto(p)}">${pct}%</td>`;
    };
    const celAno = (p, i) => {
      const inativo = !state.anos_ativos.has(ANOS[i]) ? "crit-ano-inativo" : "";
      return cel(p, inativo);
    };
    const celDelta = () => {
      if (l.delta == null) return `<td class="crit-cel-vazio">—</td>`;
      const pp = l.delta * 100;
      const sign = pp >= 0 ? "+" : "";
      return `<td class="crit-cel crit-delta" style="background:${corDelta(l.delta)}">${sign}${pp.toFixed(0)} pp</td>`;
    };
    const desc = l.desc.length > 80 ? l.desc.slice(0, 78) + "…" : l.desc;
    const linkQs = new URLSearchParams({
      area: l.area, h: l.h,
      ...(state.uf ? { uf: state.uf } : {}),
      ...(state.mun ? { mun: state.mun } : {}),
      ...(state.esc ? { esc: state.esc } : {}),
      ...(state.rede !== "T" ? { rede: state.rede } : {}),
    }).toString();
    return `<tr>
      <td class="crit-col-area"><span class="chip-area-tag" style="background:${info.cor}">${info.chip}</span></td>
      <td class="crit-col-h"><a class="chip-hab" href="habilidade.html?${linkQs}" target="_blank">H${l.h}</a></td>
      <td class="crit-col-desc" title="${l.desc.replace(/"/g,"&quot;")}">${desc}</td>
      ${l.anos.map(celAno).join("")}
      ${cel(l.media)}
      ${celEsp(l.esperado)}
      ${celDelta()}
    </tr>`;
  }).join("");
}

/* ----------- handlers --------------------------------------------------- */
document.querySelectorAll("#crit-rede button").forEach((b) => {
  b.addEventListener("click", async () => {
    document.querySelectorAll("#crit-rede button").forEach((x) => x.classList.remove("on"));
    b.classList.add("on");
    state.rede = b.dataset.rede;
    // repopula seletores considerando que a lista muda por rede
    const ufs = await apiUfs();
    fillSelect($("#sel-uf"), ufs, "Brasil (todos)", "chave", "nome");
    if (state.uf && ufs.some((u) => u.chave === state.uf)) {
      $("#sel-uf").value = state.uf;
      const muns = await apiMuns(state.uf);
      fillSelect($("#sel-mun"), muns, "Todos os municípios", "chave", "nome");
      if (state.mun && muns.some((m) => String(m.chave) === state.mun)) {
        $("#sel-mun").value = state.mun;
        const escs = await apiEscolas(state.mun);
        montarEscolas(escs);
        if (state.esc && !escolasMun.some((e) => String(e.chave) === state.esc)) {
          state.esc = "";
        } else if (state.esc) {
          const e = escolasMun.find((x) => String(x.chave) === state.esc);
          if (e) $("#inp-esc").value = e.rotulo;
        }
      } else {
        state.mun = ""; state.esc = ""; montarEscolas([]);
      }
    } else {
      state.uf = state.mun = state.esc = "";
      fillSelect($("#sel-mun"), [], "—");
      montarEscolas([]);
    }
    atualizarURL();
    await recarregarAlvo();
  });
});
document.querySelectorAll("#crit-area button").forEach((b) => {
  b.addEventListener("click", () => {
    document.querySelectorAll("#crit-area button").forEach((x) => x.classList.remove("on"));
    b.classList.add("on");
    state.area = b.dataset.area;
    atualizarURL();
    render();
  });
});
document.addEventListener("click", (e) => {
  const th = e.target.closest("#crit-thead th.sortable");
  if (!th) return;
  const col = th.dataset.sort;
  if (state.sort_col === col) {
    state.sort_dir = state.sort_dir === "asc" ? "desc" : "asc";
  } else {
    state.sort_col = col;
    state.sort_dir = SORT_DEFAULT_DIR[col] || "asc";
  }
  render();
});
/* toggle de anos ativos — clica pra excluir/incluir do cálculo de média/esp */
document.querySelectorAll("#crit-anos button").forEach((b) => {
  b.addEventListener("click", () => {
    const ano = parseInt(b.dataset.ano, 10);
    if (state.anos_ativos.has(ano)) {
      if (state.anos_ativos.size === 1) return;   // não deixa apagar todos
      state.anos_ativos.delete(ano);
      b.classList.remove("on");
    } else {
      state.anos_ativos.add(ano);
      b.classList.add("on");
    }
    // marca colunas do header
    document.querySelectorAll("#crit-thead th").forEach((th) => {
      const s = th.dataset.sort;
      if (!s || !s.startsWith("a")) return;
      const anoI = ANOS[parseInt(s.slice(1), 10)];
      th.classList.toggle("crit-th-inativo", !state.anos_ativos.has(anoI));
    });
    render();
  });
});

function atualizarURL() {
  const p = new URLSearchParams();
  if (state.uf)   p.set("uf", state.uf);
  if (state.mun)  p.set("mun", state.mun);
  if (state.esc)  p.set("esc", state.esc);
  if (state.rede !== "T") p.set("rede", state.rede);
  if (state.area) p.set("area", state.area);
  const qs = p.toString();
  history.replaceState(null, "", qs ? "?" + qs : location.pathname);
  if (window.Filtros) window.Filtros.salvar({
    uf: state.uf, mun: state.mun, esc: state.esc, rede: state.rede,
  });
}

/* ----------- Seletores UF > MUN > ESC (idem ao painel) ------------------- */
async function apiJson(url) {
  return fetch(url).then((r) => r.ok ? r.json() : null);
}
async function apiUfs()        { return (await apiJson("api/ufs.json"))?.[state.rede] || []; }
async function apiMuns(uf)     { return (await apiJson(`api/municipios/${uf}.json`))?.[state.rede] || []; }
async function apiEscolas(mun) {
  const lst = (await apiJson(`api/escolas/${mun}.json`)) || [];
  if (state.rede === "T") return lst;
  return lst.filter((e) => state.rede === "PRIV" ? e.dependencia === 4 : e.dependencia !== 4);
}
function fillSelect(sel, itens, placeholder, valor, rotulo) {
  sel.innerHTML = `<option value="">${placeholder}</option>` +
    itens.map((i) => `<option value="${i[valor]}">${i[rotulo]}</option>`).join("");
  sel.disabled = itens.length === 0;
}

async function initSelects() {
  const ufs = await apiUfs();
  fillSelect($("#sel-uf"), ufs, "Brasil (todos)", "chave", "nome");
  if (state.uf) $("#sel-uf").value = state.uf;
  if (state.uf) {
    const muns = await apiMuns(state.uf);
    fillSelect($("#sel-mun"), muns, "Todos os municípios", "chave", "nome");
    if (state.mun) $("#sel-mun").value = state.mun;
    if (state.mun) {
      const escs = await apiEscolas(state.mun);
      montarEscolas(escs);
      if (state.esc) {
        const e = escolasMun.find((x) => String(x.chave) === String(state.esc));
        if (e) $("#inp-esc").value = e.rotulo;
      }
    }
  }
}

/* combobox de escolas — mesmo padrão do app.js */
let escolasMun = [];
function montarEscolas(escs) {
  escolasMun = escs.map((x) => ({
    chave: x.chave, rotulo: x.rotulo, n: x.n_participantes,
    busca: `${x.rotulo} ${x.chave}`.toLowerCase(),
  }));
  const inp = $("#inp-esc");
  inp.value = "";
  inp.disabled = !escolasMun.length;
  inp.placeholder = escolasMun.length
    ? `Digite para buscar entre ${escolasMun.length} escolas…`
    : "Digite para buscar…";
  $("#combo-list").hidden = true;
}
function renderCombo(filtro) {
  const q = filtro.trim().toLowerCase();
  const achadas = escolasMun.filter((e) => e.busca.includes(q)).slice(0, 50);
  const lst = $("#combo-list");
  lst.innerHTML = achadas.length
    ? achadas.map((e) =>
        `<button type="button" data-chave="${e.chave}">
           <span>${e.rotulo}</span><small>${e.n?.toLocaleString?.("pt-BR") || ""} alunos</small>
         </button>`).join("")
    : `<div class="combo-vazio">Nenhuma escola encontrada</div>`;
  lst.hidden = false;
}

$("#sel-uf").addEventListener("change", async (e) => {
  state.uf = e.target.value; state.mun = ""; state.esc = "";
  fillSelect($("#sel-mun"), [], "—");
  montarEscolas([]);
  if (state.uf) {
    const muns = await apiMuns(state.uf);
    fillSelect($("#sel-mun"), muns, "Todos os municípios", "chave", "nome");
  }
  atualizarURL();
  await recarregarAlvo();
});
$("#sel-mun").addEventListener("change", async (e) => {
  state.mun = e.target.value; state.esc = "";
  if (state.mun) {
    const escs = await apiEscolas(state.mun);
    montarEscolas(escs);
  } else {
    montarEscolas([]);
  }
  atualizarURL();
  await recarregarAlvo();
});
$("#inp-esc").addEventListener("input", () => {
  if ($("#inp-esc").value === "" && state.esc) {
    state.esc = "";
    atualizarURL();
    recarregarAlvo();
  }
  renderCombo($("#inp-esc").value);
});
$("#inp-esc").addEventListener("focus", () => {
  if (escolasMun.length) renderCombo($("#inp-esc").value);
});
document.addEventListener("click", (e) => {
  if (!e.target.closest(".combo")) $("#combo-list").hidden = true;
});
$("#combo-list").addEventListener("click", (e) => {
  const b = e.target.closest("button");
  if (!b) return;
  state.esc = b.dataset.chave;
  $("#inp-esc").value = escolasMun.find((x) => x.chave == state.esc)?.rotulo || "";
  $("#combo-list").hidden = true;
  atualizarURL();
  recarregarAlvo();
});
$("#btn-limpar").addEventListener("click", async () => {
  state.uf = state.mun = state.esc = "";
  $("#sel-uf").value = "";
  fillSelect($("#sel-mun"), [], "—");
  montarEscolas([]);
  atualizarURL();
  await recarregarAlvo();
});

async function recarregarAlvo() {
  document.getElementById("crit-tbody").innerHTML =
    `<tr><td colspan="11" class="skeleton" style="padding:24px;text-align:center">Carregando…</td></tr>`;
  try {
    dataAlvo = await carregarDados();
    render();
  } catch (e) {
    console.error(e);
    document.getElementById("crit-tbody").innerHTML =
      `<tr><td colspan="11" class="skeleton" style="padding:24px;text-align:center;color:var(--red-bad)">
         Erro ao carregar dados desse grupo.
       </td></tr>`;
  }
}

/* aplica seleções da URL nos tabs */
document.querySelectorAll("#crit-rede button").forEach((x) => {
  x.classList.toggle("on", x.dataset.rede === state.rede);
});
if (state.area) {
  document.querySelectorAll("#crit-area button").forEach((x) => {
    x.classList.toggle("on", x.dataset.area === state.area);
  });
}

/* ----------- boot ------------------------------------------------------- */
(async () => {
  await initSelects();
  try {
    dataAlvo = await carregarDados();
    render();
  } catch (e) {
    console.error(e);
    document.getElementById("crit-tbody").innerHTML =
      `<tr><td colspan="11" class="skeleton" style="padding:24px;text-align:center;color:var(--red-bad)">
         Erro ao carregar dados. Verifique se o servidor está rodando e os JSONs em api/ existem.
       </td></tr>`;
  }
})();
