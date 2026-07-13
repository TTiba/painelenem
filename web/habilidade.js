/* Página de habilidade — 4 trilhas demo -------------------------------------- */

const AREA_INFO = {
  LC: { nome: "Linguagens, Códigos e suas Tecnologias", cor: "var(--lilac)" },
  CH: { nome: "Ciências Humanas e suas Tecnologias",    cor: "var(--peach)" },
  CN: { nome: "Ciências da Natureza e suas Tecnologias", cor: "var(--mint)" },
  MT: { nome: "Matemática e suas Tecnologias",          cor: "var(--lime)" },
};

const params = new URLSearchParams(location.search);
const area = params.get("area") || "MT";
const h = parseInt(params.get("h") || "1", 10);
const info = AREA_INFO[area] || AREA_INFO.MT;
const desc = (window.HABILIDADES?.[area] || {})[h] || "";

// tema curto para batizar as atividades demo (usado no hero e como sub-rótulo)
let tema = desc.split(/[,.;]/)[0]
  .replace(/^(Reconhecer|Identificar|Interpretar|Analisar|Avaliar|Utilizar|Relacionar|Compreender|Resolver|Associar|Comparar|Selecionar|Aplicar|Calcular)\s+/i, "")
  .trim();
if (tema.length > 40) tema = tema.slice(0, 40).replace(/\s+\S*$/, "") + "…";
const temaCap = tema.charAt(0).toUpperCase() + tema.slice(1);
const areaNome = { LC: "Linguagens", CH: "Humanas", CN: "Natureza", MT: "Matemática" }[area];
const habTag = `H${h} · ${areaNome}`;

document.title = `${area} · H${h} · Painel ENEM 2025`;
document.getElementById("hab-banda").style.background = info.cor;
document.getElementById("hab-chips").innerHTML =
  `<span class="chip-hab" style="background:${info.cor}">H${h}</span>
   <span class="chip-area">${info.nome}</span>`;
document.getElementById("hab-titulo").textContent = temaCap || `Habilidade ${h}`;
document.getElementById("hab-desc").textContent = desc;

/* ------------- 4 trilhas: conteúdo, prática, aprofundamento, recomposição -- */
const wg = (q) => `https://wayground.com/admin/search?query=${encodeURIComponent(q)}`;
const rco = () => `https://rco.pr.gov.br/`;

const TRILHAS = {
  "col-estruturado": {
    plataforma: "RCO",
    href: rco(),
    icone: "📘",
    itens: [
      { nome: "Aula 1 · conceitos fundamentais",
        meta: "3ª série EM · 2 aulas · aula expositiva" },
      { nome: "Aula 2 · situações-problema",
        meta: "3ª série EM · 2 aulas · resolução guiada" },
      { nome: "Sequência didática completa",
        meta: "3ª série EM · 4 aulas · aplicação e prática" },
      { nome: "Aula de sistematização",
        meta: "3ª série EM · 1 aula · fechamento" },
    ],
  },
  "col-pratica": {
    plataforma: "Wayground",
    href: null,
    icone: "✏️",
    itens: [
      { nome: "Lista dirigida",
        meta: "10 questões · 30 min · autoavaliação",
        tipo: "Lista de exercícios" },
      { nome: "Quiz rápido",
        meta: "6 questões · 10 min · gamificado",
        tipo: "Quiz" },
      { nome: "Prática de aplicação",
        meta: "8 questões · 25 min · contextualizada",
        tipo: "Ficha de atividade" },
      { nome: "Flashcards de conceitos",
        meta: "20 cards · revisão espaçada",
        tipo: "Flashcards" },
    ],
  },
  "col-aprofundamento": {
    plataforma: "Wayground",
    href: null,
    icone: "🚀",
    itens: [
      { nome: `Desafio ENEM · ${habTag}`,
        meta: "5 itens de alta dificuldade",
        tipo: "Desafio" },
      { nome: "Estudo de caso aplicado",
        meta: "leitura + discussão · 1 aula",
        tipo: "Projeto" },
      { nome: "Simulado temático",
        meta: "15 questões ENEM · 45 min",
        tipo: "Simulado" },
      { nome: "Vídeo-aula avançada",
        meta: "20 min · perguntas embutidas",
        tipo: "Vídeo interativo" },
    ],
  },
  "col-recomposicao": {
    plataforma: "Wayground",
    href: null,
    icone: "🔁",
    itens: [
      { nome: "Diagnóstico de lacunas",
        meta: "8 questões · mapeia dificuldades",
        tipo: "Avaliação diagnóstica" },
      { nome: "Retomada guiada",
        meta: "3 vídeos curtos + 6 questões",
        tipo: "Aula de reforço" },
      { nome: "Trilha de recuperação",
        meta: "sequência progressiva · 4 níveis",
        tipo: "Trilha adaptativa" },
      { nome: "Sala de dúvidas",
        meta: "vídeo-comentário + banco de exercícios",
        tipo: "Apoio" },
    ],
  },
};

for (const [colId, cfg] of Object.entries(TRILHAS)) {
  const el = document.getElementById(colId);
  el.innerHTML = cfg.itens.map((it) => {
    const href = cfg.href || wg(it.nome);
    const sub = it.tipo ? `${it.tipo} · ${cfg.plataforma}` : cfg.plataforma;
    return `<a class="link-item link-trilha" href="${href}" target="_blank">
      <span class="li-ico">${cfg.icone}</span>
      <span class="li-txt"><b>${it.nome}</b><small>${it.meta} · ${sub}</small></span>
      <span class="li-seta">→</span>
    </a>`;
  }).join("");
}
