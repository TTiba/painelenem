# Status — Painel ENEM 2021–2025 (produto Wayground)

> Este arquivo existe para dar contexto completo a uma nova sessão de Claude
> (ex.: Claude da empresa, sem acesso à memória pessoal desta conta). Leia
> isto antes de mexer em qualquer coisa. Última atualização: 2026-07-21,
> com a expansão para série histórica 2021–2025 e página de habilidades.

## O que é isto

Plataforma web de análise de desempenho no ENEM 2021–2025, navegável por
Estado > Município > Escola, com filtro de rede (pública/privada), mapa
coroplético do Brasil, e um indicador próprio — **Δ esperado (TRI)** — que
compara o acerto observado em cada item com o esperado pelo nível dos
próprios alunos daquela escola (não com a média nacional). Vai se tornar um
produto da Wayground (o usuário trabalha na Quizizz/Wayground). Visual
inspirado na identidade real do site wayground.com.

## Expansão 2021–2025 (2026-07-21)

- Pipeline agora aceita **`--ano`** e detecta automaticamente formato antigo
  (`MICRODADOS_ENEM_YYYY.csv` combinado, 2021–2023) vs novo (`RESULTADOS_YYYY.csv`
  separado, 2024–2025). Filtro de concluinte muda por ano:
  - 2024/2025: `CO_ESCOLA IS NOT NULL` (comportamento antigo).
  - 2021–2023: `TP_ST_CONCLUSAO=2 AND IN_TREINEIRO=0 AND TP_PRESENCA_LC=1 AND TP_PRESENCA_MT=1`
    (concluintes que fizeram os dois dias, município identificável).
- **`CO_ESCOLA` só existe em 2024–2025** — nível ESC ficou vazio em 2021–2023.
  Timeline por escola cobre apenas 2024–2025, com aviso explícito na UI
  (`hist_scope` no JSON e nota no card `.evolucao`).
- Novo `pipeline/build_all_years.py` roda os 5 anos em sequência.
- Novo `pipeline/build_hist_db.py` consolida os 5 SQLites em `data/enem_hist.sqlite`
  com `hist_resumo`, `hist_item`, `hist_hab`, `itens_meta_all`.
- `exporta_netlify.py` foi estendido — não removeu nada, todos os novos campos
  são aditivos:
  - `hist_resumo` embutido em `api/entidade/**` (KPI sparkline + card `.evolucao`).
  - `api/historico/{BR|UF|MUN}/{chave}.json` (itens por ano, lazy — ESC não emite).
  - `api/refs_hist/{ano}/{BR|UF/uf}.json` (refs BR/UF por ano, separado para não
    inflar cada arquivo de município — a otimização levou o deploy de 2.2 GB
    para 840 MB, ~46 k arquivos).
  - `api/habilidades/index.json` (matriz 4×30×5 pro heatmap).
  - `api/habilidades/{area}/{h}.json` (120 arquivos, drill-down por skill).
- **Frontend**:
  - `web/charts.js` — `sparkline`, `lineChart`, `heatmap` (SVG puro, sem lib).
  - `web/index.html` + `app.js` — sparkline em cada KPI, seção `.evolucao`
    entre `#kpis` e `.duo`, `#tabs-ano` na tabela de itens (default 2025;
    desabilitado quando é escola), badge ⚠ nos pontos de 2021.
  - `web/habilidades.html` + `habilidades-page.js` — nova página com heatmap
    30×5 (cobertura ou desempenho) e ranking cross-year.
  - `web/habilidade.html` + `habilidade.js` — card novo "Cobertura no ENEM
    2021–2025" com 5 stat-tiles e detalhes por ano (`<details>` recolhível).
  - `web/entenda.html` — nova seção "Comparações entre anos".
- Total de arquivos gerados no `deploy/`: **~46 k**, ~**840 MB**.

## Convenções da fase histórica

- **Nunca comparar 2021 com o resto sem contexto** — pandemia, aplicação em
  jan/2022, ~1 M concluintes vs ~2,7 M. O JSON marca `flag_pandemia: true` e
  a UI destaca visualmente.
- **KPI cards mostram sempre o ano mais recente**, com sparkline dos 5 anos
  embaixo. O único seletor de ano é `#tabs-ano` na tabela de itens.
- **Escola pré-2024 é intencionalmente ausente** — não tentar inferir por
  agregação (o pareamento por município+dependencia perde a identidade da
  escola específica e viraria seleção enviesada).

## Onde as coisas estão

- **Site principal (produção):** https://microdadosenem.netlify.app —
  confirmado no ar (HTTP 200) e refletindo o filtro de rede pública/privada.
- **Repositório:** `plataforma/` é um repo git próprio (não a raiz do
  projeto), remote `https://github.com/TTiba/painelenem.git`, branch `main`,
  1 commit ("Painel ENEM 2025 · commit inicial", 13/07/2026), working tree
  limpo. O deploy no Netlify está conectado a este repo via GitHub (deploy
  automático a cada push).
- **Netlify CLI**: instalado e logado (conta `raphacorrea@gmail.com`, team
  `Nerd`). `netlify sites:list` mostra o site `microdadosenem` ligado a este
  repo, mais 4 sites `painel-enem-sp*` (variante de SP — ver seção "Partes
  não documentadas" abaixo).
- **Microdados fonte:** `../microdados_enem_2025/DADOS/` (fora deste repo,
  não versionado — são os CSVs brutos do INEP, ~2,5 GB).

## Arquitetura

```
microdados_enem_2025/DADOS/*.csv (INEP, brutos)
        │
        ▼  pipeline/build_db.py  (DuckDB, ~1 min)
data/enem2025.sqlite  (~470 MB, GITIGNORED — não está no repo)
        │
        ├──▶ server.py            (stdlib http.server + sqlite3, modo dinâmico local)
        │        │
        │        ▼
        │    web/*.html + app.js + mapa.js   (frontend vanilla JS)
        │
        └──▶ pipeline/exporta_netlify.py  (pré-gera toda a API como JSON)
                 │
                 ▼
             deploy/   (site 100% estático — é isto que vai pro Netlify)
```

Não tem backend em produção. O Netlify serve só arquivos estáticos; toda
"API" em produção é um monte de `.json` pré-computado em `deploy/api/`. O
`web/app.js` e `web/mapa.js` detectam `window.API_STATIC` (injetado pelo
exportador) e trocam `fetch("/api/...")` por `fetch("api/....json")`.

### Arquivos principais

| Arquivo | O que faz |
|---|---|
| `pipeline/build_db.py` | Lê os CSVs do INEP, agrega em `agg_resumo` (notas por nível/rede) e `agg_item` (acerto + esperado TRI por item/nível/rede), grava SQLite |
| `pipeline/carrega_nomes_escolas.py <csv>` | Injeta nomes de escola (microdados só têm código INEP) |
| `pipeline/carrega_habilidades.py <csv>` | Injeta mapa próprio item→habilidade (sobrepõe a habilidade INEP no front) |
| `pipeline/exporta_netlify.py` | Gera `deploy/` inteiro a partir do SQLite — **rodar sempre antes de dar push** se o banco ou o `web/` mudou |
| `server.py` | Servidor dinâmico local, porta padrão 8090/8765 |
| `server_sp.py` | Variante paralela servindo a pasta `sp/` (ver abaixo) |
| `web/index.html` + `app.js` | Painel principal: seletores, KPIs, competências de redação, tabela de itens |
| `web/mapa.html` + `mapa.js` | Mapa coroplético Brasil→UF→município (D3 + malhas do IBGE) |
| `web/entenda.html` | Infográfico explicando cada indicador do painel |
| `web/habilidade.html` + `habilidade.js` + `habilidades.js` | Página por habilidade (descrição da Matriz de Referência + aulas/atividades demo) |

## Conceitos de domínio (para não rederivar do zero)

- **Δ Brasil**: `% acerto da seleção − % acerto do Brasil`, no mesmo item.
  Compara com todo mundo, sem levar em conta o nível dos alunos.
- **Δ esperado (o indicador-chave)**: usa a curva TRI de cada item
  (parâmetros oficiais `a,b,c` do INEP) para calcular quanto um aluno daquele
  nível de proficiência (θ = (nota−500)/100) deveria acertar, em média, e
  compara com o observado. Fórmula 3PL: `P(θ) = c + (1−c)/(1+e^(−1.7·a·(θ−b)))`.
  Isola "qualidade do ensino naquele conteúdo" de "nível geral da turma".
  Validado: delta médio no nível Brasil ≈ 0 (confirma a calibração).
- **Rede**: `T` (todas), `PUB` (federal+estadual+municipal), `PRIV`
  (`TP_DEPENDENCIA_ADM_ESC = 4`). Existe em toda a cadeia — banco, API,
  export estático, frontend (abas no topo do painel e do mapa).
- **Quem entra na conta**: só concluintes com `CO_ESCOLA` preenchido
  (~1,74 milhão em 2025) — treineiros ficam fora automaticamente porque o
  INEP só atribui escola a quem está concluindo o ensino médio.
- **Cuidado estatístico**: cada prova tem só 1–3 itens por habilidade (30
  habilidades por área). Conclusão de habilidade num item isolado é
  hipótese, não veredito; várias no mesmo sentido é diagnóstico.

Explicação completa e didática (com gráficos) está em `web/entenda.html` —
vale ler antes de alterar qualquer indicador.

## Como rodar localmente

```bash
# 1. (só se o banco não existir ou os CSVs mudaram) gerar o SQLite
cd "plataforma"
.venv/bin/python pipeline/build_db.py          # ~1 min
python3 pipeline/carrega_nomes_escolas.py <csv-de-nomes>   # opcional, refaz sempre que o passo 1 rodar

# 2. servidor dinâmico
python3 server.py 8090
# abrir http://localhost:8090

# 3. testar o modo estático (o que realmente vai pro ar)
python3 pipeline/exporta_netlify.py            # gera deploy/ (~40 mil arquivos, ~400 MB, ~50 s)
python3 -m http.server 8791 -d deploy
# abrir http://localhost:8791
```

`.claude/launch.json` (na raiz do projeto, fora deste repo) já tem as duas
configs de preview: `painel-enem` e `painel-netlify-estatico`.

## Publicar

```bash
git add -A
git commit -m "..."
git push          # dispara build automático no Netlify (site microdadosenem)
```

Importante: **rodar `pipeline/exporta_netlify.py` antes do commit** sempre
que `web/` ou o banco mudarem — o Netlify serve o conteúdo de `deploy/`
como está, não regenera nada sozinho no build (não há passo de build
configurado, é publicação direta de estático).

## Armadilhas conhecidas

- **SQLite guarda `n`/`acertos` de `agg_item` como texto** se o `CAST`
  explícito for esquecido no `build_db.py` — já corrigido, mas se voltar a
  ver `TypeError: can't multiply sequence by non-int` na API, é isso.
- **Rebuild do banco apaga nomes de escola** — sempre rodar
  `carrega_nomes_escolas.py` de novo depois de `build_db.py`.
- **Porta 8765/8080 costumam estar ocupadas** por outros processos desta
  máquina — usar 8090 ou deixar o `autoPort` do launch.json escolher.
- **`deploy/` pode ficar dessincronizado do banco** se você mudar o SQLite
  e esquecer de re-exportar — não há checagem automática disso.
- **Nomes de escola só existem para redes públicas do PR** (carregados de
  `~/outputs/api_estado_ineps_20260707/ineps_escolas_api_estado_pr.csv`).
  Demais UFs e todas as privadas aparecem como "Escola INEP {código}".
- **`itens_meta.habilidade_custom`** fica `NULL` até alguém carregar um mapa
  próprio item→habilidade; até lá o front mostra a habilidade oficial do
  INEP (H1–H30 por área).

## Partes do repositório que eu não documentei com confiança

Ao investigar o estado atual do repo (13/07) encontrei arquivos que **não
foram construídos nesta linha de trabalho** e cujo propósito exato não
verifiquei em profundidade — não invente contexto sobre eles, confirme
com o Raphael antes de mexer:

- **`sp/`, `server_sp.py`, `sp_deploy/`** — uma variante do painel focada em
  São Paulo (`<title>Painel ENEM 2025 · São Paulo · Wayground</title>`),
  servida por `server_sp.py` na porta 8092. Há **4 sites Netlify** distintos
  ligados a essa variante (`painel-enem-sp`, `painel-enem-sp-vendas`,
  `painel-enem-2025-sp`, `painel-enem-sp-wayground`) — não está claro qual é
  o canônico/em uso.
- **`deck/`** — script Playwright (`capturar.py`) que tira prints do portal
  para montar um deck de apresentação; o HTML interno referencia
  "SEED-PR" (provavelmente Secretaria de Estado da Educação do Paraná).
- Essas três pastas estão no `.gitignore` deste repo (não versionadas) —
  então existem só localmente nesta máquina.

## Próximos passos em aberto (da última sessão de trabalho)

1. Confirmar se `web/entenda.html` precisa de uma seção explicando o filtro
   de rede (hoje não menciona isso — o card do Δ esperado, por exemplo, não
   avisa que comparar pública vs. privada tem viés de seleção ainda maior
   que comparar dentro da mesma rede).
2. Re-rodar `exporta_netlify.py` e conferir se `deploy/` está 100% em sync
   com o SQLite atual (havia uma pequena divergência de horário de geração
   detectada em 08/07 — o site em produção já parece refletir o filtro de
   rede corretamente, mas vale checar após qualquer mudança nova).
3. Decidir sobre nomes de escola das demais UFs (hoje só PR-pública tem
   nome) — provavelmente via Catálogo de Escolas do INEP/Censo Escolar.
4. Entender e consolidar (ou descartar) a variante `sp/` e os 4 sites
   Netlify duplicados antes que virem dívida técnica.
