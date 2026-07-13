/* Painel ENEM 2025 — Wayground ------------------------------------------- */

const AREA_INFO = {
  RED: { nome: "Redação",     cor: "var(--rose)"  },
  LC:  { nome: "Linguagens",  cor: "var(--lilac)" },
  CH:  { nome: "Humanas",     cor: "var(--peach)" },
  CN:  { nome: "Natureza",    cor: "var(--mint)"  },
  MT:  { nome: "Matemática",  cor: "var(--lime)"  },
};
const NIVEL_NOME = { BR: "Brasil", UF: "Estado", MUN: "Município", ESC: "Escola" };

const $ = (s) => document.querySelector(s);
const fmt = (v, d = 1) =>
  v == null ? "–" : Number(v).toLocaleString("pt-BR", { minimumFractionDigits: d, maximumFractionDigits: d });
const fmtInt = (v) => (v == null ? "–" : Number(v).toLocaleString("pt-BR"));

const state = { uf: "", mun: "", esc: "", area: "MT", rede: "T" };
const REDE_NOME = { T: "todas as redes", PUB: "rede pública", PRIV: "rede privada" };

function nivelChave() {
  if (state.esc) return { nivel: "ESC", chave: state.esc };
  if (state.mun) return { nivel: "MUN", chave: state.mun };
  if (state.uf)  return { nivel: "UF",  chave: state.uf };
  return { nivel: "BR", chave: "BR" };
}

/* Em produção (Netlify) o site é estático: as respostas da API são arquivos
   JSON pré-gerados por pipeline/exporta_netlify.py (window.API_STATIC = 1).
   Listas e entidades BR/UF/MUN têm ramos por rede (T/PUB/PRIV); as referências
   por item (UF/BR) vivem em api/refs/{chave}.json e são juntadas aqui. */
const cacheEntidade = {};
const cacheRefs = {};

async function api(rota, params = {}) {
  const rede = state.rede || "T";
  if (!window.API_STATIC) {
    const qs = new URLSearchParams({ rede, ...params }).toString();
    const r = await fetch(`/api/${rota}?${qs}`);
    return r.json();
  }
  const j = (u) => fetch(u).then((r) => (r.ok ? r.json() : null));
  if (rota === "ufs")        return (await j("api/ufs.json"))[rede] || [];
  if (rota === "municipios")
    return (await j(`api/municipios/${params.uf}.json`))?.[rede] || [];
  if (rota === "escolas") {
    const lst = (await j(`api/escolas/${params.municipio}.json`)) || [];
    if (rede === "T") return lst;
    return lst.filter((e) =>
      rede === "PRIV" ? e.dependencia === 4 : e.dependencia !== 4);
  }
  const k = `${params.nivel}/${params.chave}`;
  if (!cacheEntidade[k]) cacheEntidade[k] = j(`api/entidade/${k}.json`);
  const ent = await cacheEntidade[k];
  if (!ent) return { erro: "não encontrado" };
  const ehEscola = params.nivel === "ESC";
  const ramo = ehEscola ? ent : ent[rede];
  if (!ramo) return rota === "resumo" ? { erro: "sem dados nesta rede" } : [];

  if (rota === "resumo") {
    if (ehEscola) {
      return { alvo: ent.resumo.alvo,
               contexto: ent.resumo.contexto_por_rede?.[rede] || [] };
    }
    return ramo.resumo;
  }
  if (rota === "itens") {
    const alvo = ehEscola ? ent.resumo.alvo : ramo.resumo.alvo;
    const uf = alvo.uf || alvo.escola?.uf || null;
    const refsDe = async (chave) => {
      if (!cacheRefs[chave]) cacheRefs[chave] = j(`api/refs/${chave}.json`);
      return (await cacheRefs[chave])?.[rede] || {};
    };
    const [ru, rb] = await Promise.all(
      [uf ? refsDe(uf) : {}, refsDe("BR")]);
    return ((ehEscola ? ent.itens : ramo.itens)[params.area] || []).map(
      ([item, n, p, p_esp, hab, b, lingua]) => ({
        item, n, p, p_esp, habilidade_inep: hab, param_b: b,
        tp_lingua: lingua,
        p_uf: ru[item] ?? null, p_br: rb[item] ?? null,
      }));
  }
}

/* ---------- seletores ---------------------------------------------------- */
function fillSelect(sel, itens, placeholder, valor, rotulo) {
  sel.innerHTML = `<option value="">${placeholder}</option>` +
    itens.map((i) => `<option value="${i[valor]}">${i[rotulo]}</option>`).join("");
  sel.disabled = itens.length === 0;
}

async function initUFs() {
  const ufs = await api("ufs");
  fillSelect($("#sel-uf"), ufs, "Brasil (todos)", "chave", "nome");
}

$("#sel-uf").addEventListener("change", async (e) => {
  state.uf = e.target.value; state.mun = ""; state.esc = "";
  setEscolas([]);
  if (state.uf) {
    const muns = await api("municipios", { uf: state.uf });
    fillSelect($("#sel-mun"), muns, "Todos os municípios", "chave", "nome");
  } else {
    fillSelect($("#sel-mun"), [], "—");
  }
  refresh();
});

$("#sel-mun").addEventListener("change", async (e) => {
  state.mun = e.target.value; state.esc = "";
  if (state.mun) {
    const escs = await api("escolas", { municipio: state.mun });
    setEscolas(escs.map((x) => ({
      chave: x.chave,
      rotulo: `${x.rotulo}`,
      n: x.n_participantes,
      busca: `${x.rotulo} ${x.chave}`.toLowerCase(),
    })));
  } else {
    setEscolas([]);
  }
  refresh();
});

/* ---------- combobox de escolas (busca digitável) ------------------------- */
let escolasMun = [];
const inpEsc = $("#inp-esc");
const comboList = $("#combo-list");

function setEscolas(lista) {
  escolasMun = lista;
  inpEsc.value = "";
  inpEsc.disabled = lista.length === 0;
  inpEsc.placeholder = lista.length
    ? `Digite para buscar entre ${lista.length} escolas…` : "Digite para buscar…";
  comboList.hidden = true;
}

function renderCombo(filtro) {
  const q = filtro.trim().toLowerCase();
  const achadas = escolasMun.filter((e) => e.busca.includes(q)).slice(0, 50);
  comboList.innerHTML = achadas.length
    ? achadas.map((e) =>
        `<button type="button" data-chave="${e.chave}">
           <span>${e.rotulo}</span><small>${fmtInt(e.n)} alunos</small>
         </button>`).join("")
    : `<div class="combo-vazio">Nenhuma escola encontrada</div>`;
  comboList.hidden = false;
}

inpEsc.addEventListener("input", () => {
  if (inpEsc.value === "" && state.esc) { state.esc = ""; refresh(); }
  renderCombo(inpEsc.value);
});
inpEsc.addEventListener("focus", () => { if (escolasMun.length) renderCombo(inpEsc.value); });
document.addEventListener("click", (e) => {
  if (!e.target.closest(".combo")) comboList.hidden = true;
});
comboList.addEventListener("click", (e) => {
  const b = e.target.closest("button");
  if (!b) return;
  state.esc = b.dataset.chave;
  inpEsc.value = escolasMun.find((x) => x.chave == state.esc)?.rotulo || "";
  comboList.hidden = true;
  refresh();
});

document.querySelectorAll("#tabs-rede button").forEach((b) => {
  b.addEventListener("click", async () => {
    document.querySelectorAll("#tabs-rede button").forEach((x) => x.classList.remove("on"));
    b.classList.add("on");
    state.rede = b.dataset.rede;
    // recarrega listas dependentes preservando a seleção quando possível
    if (state.uf) {
      const muns = await api("municipios", { uf: state.uf });
      fillSelect($("#sel-mun"), muns, "Todos os municípios", "chave", "nome");
      if (muns.some((m) => String(m.chave) === state.mun)) {
        $("#sel-mun").value = state.mun;
      } else {
        state.mun = ""; state.esc = ""; setEscolas([]);
      }
    }
    if (state.mun) {
      const rotuloAtual = inpEsc.value;
      const escs = await api("escolas", { municipio: state.mun });
      setEscolas(escs.map((x) => ({
        chave: x.chave, rotulo: x.rotulo, n: x.n_participantes,
        busca: `${x.rotulo} ${x.chave}`.toLowerCase(),
      })));
      if (state.esc && escolasMun.some((e) => String(e.chave) === state.esc)) {
        inpEsc.value = rotuloAtual;   // escola continua válida nesta rede
      } else {
        state.esc = "";
      }
    }
    refresh();
  });
});

$("#btn-limpar").addEventListener("click", () => {
  state.uf = state.mun = state.esc = "";
  $("#sel-uf").value = "";
  fillSelect($("#sel-mun"), [], "—");
  setEscolas([]);
  refresh();
});

/* ---------- render: cabeçalho + KPIs ------------------------------------- */
function kpiCard(sigla, alvo, ctx) {
  const campo = sigla === "RED" ? "media_red" : `media_${sigla.toLowerCase()}`;
  const info = sigla === "GERAL"
    ? { nome: "Média geral", cor: "var(--pink)" } : AREA_INFO[sigla];
  const c = sigla === "GERAL" ? "media_geral" : campo;
  const val = alvo[c];
  const ref = ctx.length ? ctx[ctx.length - 1][c] : null; // último = Brasil
  let cmp = "";
  if (ref != null && val != null) {
    const d = val - ref;
    const cls = d >= 0 ? "up" : "down";
    cmp = `<span class="${cls}">${d >= 0 ? "+" : ""}${fmt(d)}</span> vs Brasil`;
  }
  return `<div class="kpi">
    <div class="kpi-top" style="background:${info.cor}">${info.nome}</div>
    <div class="kpi-body">
      <div class="kpi-num">${fmt(val)}</div>
      <div class="kpi-cmp">${cmp}</div>
    </div></div>`;
}

function renderResumo(data) {
  const { alvo, contexto } = data;
  $("#ent-nome").textContent = alvo.nome;
  $("#ent-chip").textContent = NIVEL_NOME[alvo.nivel];

  let meta = `${fmtInt(alvo.n_participantes)} concluintes participantes`;
  if (state.rede !== "T" && !alvo.escola) meta += ` · ${REDE_NOME[state.rede]}`;
  if (alvo.escola) {
    const e = alvo.escola;
    meta += ` · ${e.dependencia_nome || ""} · ${e.municipio}/${e.uf} · código INEP ${e.chave}`;
  } else if (alvo.nivel === "MUN") {
    meta += ` · ${alvo.uf}`;
  }
  $("#ent-meta").textContent = meta;

  $("#kpis").innerHTML =
    ["GERAL", "RED", "LC", "CH", "CN", "MT"].map((s) => kpiCard(s, alvo, contexto)).join("");

  // competências da redação (0–200): alvo vs contexto
  const linhas = [alvo, ...contexto];
  $("#comps").innerHTML = [1, 2, 3, 4, 5].map((i) => {
    const rows = linhas.map((l, ix) => barRow(
      ix === 0 ? nomeCurto(l) : nomeCurto(l),
      l[`media_comp${i}`], 200,
      ix === 0 ? "var(--rose)" : "var(--ink-12)",
      fmt(l[`media_comp${i}`], 0)
    )).join("");
    return `<div class="grp"><span class="dot" style="background:var(--rose)"></span>
            Competência ${i}</div>${rows}`;
  }).join("");

  // comparação por área
  $("#areas-comp").innerHTML = ["LC", "CH", "CN", "MT", "RED"].map((s) => {
    const campo = s === "RED" ? "media_red" : `media_${s.toLowerCase()}`;
    const info = AREA_INFO[s];
    const rows = linhas.map((l, ix) => barRow(
      nomeCurto(l), l[campo], 1000,
      ix === 0 ? info.cor : "var(--ink-12)",
      fmt(l[campo], 0)
    )).join("");
    return `<div class="grp"><span class="dot" style="background:${info.cor}"></span>
            ${info.nome}</div>${rows}`;
  }).join("");
}

function nomeCurto(l) {
  if (l.nivel === "ESC") return `<span title="${l.nome}">Escola</span>`;
  if (l.nivel === "MUN") return l.nome.length > 16 ? l.nome.slice(0, 15) + "…" : l.nome;
  return l.nome;
}

function barRow(lbl, val, max, cor, valTxt) {
  const w = val == null ? 0 : Math.min(100, (val / max) * 100);
  return `<div class="bar-row">
    <div class="lbl">${lbl}</div>
    <div class="bar-track"><div class="bar-fill" style="width:${w}%;background:${cor}"></div></div>
    <div class="bar-val">${valTxt}</div></div>`;
}

/* ---------- render: itens ------------------------------------------------- */
function classifB(b) {
  if (b == null) return ["", "–"];
  if (b < 0)   return ["b-facil", `${fmt(b)} · fácil`];
  if (b < 1.2) return ["b-media", `${fmt(b)} · média`];
  return ["b-dificil", `${fmt(b)} · difícil`];
}

function renderItens(rows, nivel) {
  const tb = $("#tbl-itens tbody");
  if (!rows.length) {
    tb.innerHTML = `<tr><td colspan="8" class="skeleton">Sem dados para esta seleção.</td></tr>`;
    return;
  }
  const cor = AREA_INFO[state.area].cor;
  tb.innerHTML = rows.map((r) => {
    const hab = r.habilidade_custom || (r.habilidade_inep ? `H${r.habilidade_inep}` : "–");
    const chip = r.habilidade_inep
      ? `<a class="chip-hab" target="_blank"
            href="habilidade.html?area=${state.area}&h=${r.habilidade_inep}"
            data-area="${state.area}" data-h="${r.habilidade_inep}">${hab}</a>`
      : `<span class="chip-hab">${hab}</span>`;
    const lang = r.tp_lingua === 0 ? `<span class="chip-lang">EN</span>`
               : r.tp_lingua === 1 ? `<span class="chip-lang">ES</span>` : "";
    const [bCls, bTxt] = classifB(r.param_b);
    const badge = (d) => d == null ? `<span class="delta-flat">–</span>`
      : Math.abs(d) < 0.005 ? `<span class="delta-flat">=</span>`
      : d > 0 ? `<span class="delta-up">+${fmt(d * 100, 0)} pp</span>`
              : `<span class="delta-down">${fmt(d * 100, 0)} pp</span>`;
    const dHtml = badge(r.p_br == null ? null : r.p - r.p_br);
    const dEspHtml = badge(r.p_esp == null ? null : r.p - r.p_esp);
    const ufTd = nivel === "BR" || nivel === "UF" || r.p_uf == null ? "–" : `${fmt(r.p_uf * 100, 0)}%`;
    return `<tr>
      <td class="item-code">${r.item}${lang}</td>
      <td>${chip}</td>
      <td class="${bCls}">${bTxt}</td>
      <td class="col-bar">
        <div class="mini-track">
          <div class="mini-fill" style="width:${r.p * 100}%;background:${cor}"></div>
          ${r.p_esp == null ? "" :
            `<div class="mini-mark" style="left:${r.p_esp * 100}%"
                  title="Esperado pela TRI: ${fmt(r.p_esp * 100, 0)}%"></div>`}
        </div>
      </td>
      <td class="pct">${fmt(r.p * 100, 0)}%</td>
      <td>${ufTd} · ${r.p_br == null ? "–" : fmt(r.p_br * 100, 0) + "% BR"}</td>
      <td>${dHtml}</td>
      <td>${dEspHtml}</td>
    </tr>`;
  }).join("");
  // cabeçalho UF/BR compacto
  const ths = document.querySelectorAll("#tbl-itens th");
  ths[4].textContent = "% acerto";
  ths[5].textContent = "Referências";
  ths[6].textContent = "Δ Brasil";
}

async function loadItens() {
  const { nivel, chave } = nivelChave();
  $("#tbl-itens tbody").innerHTML =
    `<tr><td colspan="8" class="skeleton">Carregando itens…</td></tr>`;
  const rows = await api("itens", { nivel, chave, area: state.area });
  renderItens(rows, nivel);
}

document.querySelectorAll("#tabs-area button").forEach((b) => {
  b.addEventListener("click", () => {
    document.querySelectorAll("#tabs-area button").forEach((x) => x.classList.remove("on"));
    b.classList.add("on");
    state.area = b.dataset.area;
    loadItens();
  });
});

/* ---------- tooltip das habilidades --------------------------------------- */
const tip = document.createElement("div");
tip.className = "tooltip";
tip.hidden = true;
document.body.appendChild(tip);

document.addEventListener("mouseover", (e) => {
  const c = e.target.closest(".chip-hab[data-h]");
  if (!c) { tip.hidden = true; return; }
  const desc = (window.HABILIDADES?.[c.dataset.area] || {})[c.dataset.h];
  if (!desc) return;
  tip.innerHTML = `<b>H${c.dataset.h} · ${AREA_INFO[c.dataset.area].nome}</b>
    ${desc}<span class="tip-cta">Clique para ver aulas do RCO e atividades →</span>`;
  tip.hidden = false;
  const r = c.getBoundingClientRect();
  const left = Math.max(8, Math.min(r.left, innerWidth - 348));
  const top = r.bottom + 336 > innerHeight ? r.top - tip.offsetHeight - 8 : r.bottom + 8;
  tip.style.left = `${left}px`;
  tip.style.top = `${top}px`;
});

/* ---------- ciclo principal ---------------------------------------------- */
async function refresh() {
  const { nivel, chave } = nivelChave();
  const data = await api("resumo", { nivel, chave });
  if (data.erro) {
    $("#ent-nome").textContent = "Sem dados nesta rede";
    $("#ent-meta").textContent =
      `A seleção atual não tem concluintes na ${REDE_NOME[state.rede]}.`;
    $("#ent-chip").textContent = NIVEL_NOME[nivel];
    $("#kpis").innerHTML = "";
    $("#comps").innerHTML = "";
    $("#areas-comp").innerHTML = "";
    $("#tbl-itens tbody").innerHTML =
      `<tr><td colspan="8" class="skeleton">Sem dados para esta seleção.</td></tr>`;
    return;
  }
  renderResumo(data);
  loadItens();
}

initUFs().then(async () => {
  // deep-link vindo do mapa: index.html?uf=PR ou ?uf=PR&mun=4106902
  const params = new URLSearchParams(location.search);
  const uf = params.get("uf");
  const mun = params.get("mun");
  if (!uf) { refresh(); return; }
  $("#sel-uf").value = uf.toUpperCase();
  $("#sel-uf").dispatchEvent(new Event("change"));
  if (mun) {
    for (let i = 0; i < 40; i++) {
      if ($("#sel-mun").options.length > 1) break;
      await new Promise((r) => setTimeout(r, 150));
    }
    if ([...$("#sel-mun").options].some((o) => o.value === mun)) {
      $("#sel-mun").value = mun;
      $("#sel-mun").dispatchEvent(new Event("change"));
    }
  }
});
