# Publicar o painel nacional (`microdadosenem.netlify.app`)

Tutorial para publicar o rebuild com `p_esp` em **D=1**.

Este painel é **ligado ao git**: o Netlify está conectado a
`github.com/TTiba/painelenem` e publica automaticamente a cada push na
`main`. Você não roda `netlify deploy` aqui — você mergeia.

> O painel **Paraná** é o oposto (deploy manual, `netlify deploy --prod
> --dir=pr2_deploy`) e neste momento **não deve ser publicado** — o
> `pr2_deploy` saiu do rebuild sem dado avaliável. Ver `ESTADO.md`, "Em aberto".

Tudo abaixo roda na raiz do `plataforma`:

```bash
cd ~/Documents/Microdados\ ENEM/plataforma
```

---

## Passo 1 — Trazer os arquivos de apoio

```bash
git pull origin claude/replica-melhorias-paranav2
```

Isso traz o `diag_deploy.py`, o `PUBLICAR.md` e — importante — o `.gitignore`
atualizado, que impede o `git add -A` de tentar commitar a pasta
`backup-d17-*/` (são ~58 mil arquivos, ~450 MB).

## Passo 2 — Conferir que os cinco anos foram reconstruídos

```bash
ls -l data/*.sqlite
```

**Esperado:** cinco arquivos (`enem2021`…`enem2025`) mais o `enem_hist`, todos
com data/hora do rebuild. Se algum estiver com data antiga, aquele ano não
entrou — o `build_all_years.py` pula ano cujo microdado não encontra, e avisa
no log. Nesse caso pare e veja o `rebuild-d1.log`.

## Passo 3 — Conferir a calibração

```bash
python3 pipeline/verifica_calibracao.py deploy
```

**Esperado:** última linha `✓ CALIBRADO`, com erro médio dentro de ±1 pp.
Na medição de 29/07 deu **+0,02 pp** (antes do rebuild era −2,54 pp).

Se der `✗ DESCALIBRADO` com algo perto de −2,5 pp, **pare** — o rebuild não
pegou, e publicar colocaria os valores errados no ar.

## Passo 4 — Conferir que não sobrou `p_esp` nulo

```bash
python3 pipeline/diag_deploy.py deploy
```

**Esperado:** `p_esp nulo 0` em BR, UF/PR e UF/SP, e `p_esp nulo 0 (0%)` nas
amostras de MUN e ESC. Qualquer número diferente de zero significa item
perdido — anote quantos e me diga antes de publicar.

## Passo 5 — Conferir que o "2025" saiu do título

```bash
grep -c 'Painel ENEM 2025' deploy/*.html
```

**Esperado:** `0` em todos os seis arquivos.

Se algum der `1` ou mais, o `git pull` que você fez antes do rebuild foi
anterior ao commit do rodapé. Conserto sem refazer os SQLites:

```bash
python3 pipeline/exporta_netlify.py
grep -c 'Painel ENEM 2025' deploy/*.html      # tem que virar 0
```

## Passo 6 — Commitar

```bash
git status --short | head
git add -A
git status --short | wc -l
```

**Esperado:** algo em torno de **35 mil arquivos** modificados — são as
entidades (BR + 27 UFs + 5.557 municípios + 29.290 escolas) mais o histórico.

⚠️ Se aparecer `backup-d17-…` na lista, **pare**: o Passo 1 não foi feito.
Rode `git reset` e volte ao Passo 1.

```bash
git commit -m "Rebuild com p_esp em D=1"
```

## Passo 7 — Push e conferir o preview

```bash
git push origin claude/replica-melhorias-paranav2
```

O push é grande (dezenas de milhares de JSONs) e pode demorar vários minutos.

O Netlify constrói um **Deploy Preview** da branch e comenta a URL no PR #2:
https://github.com/TTiba/painelenem/pull/2

Abra a URL do preview e confira:

- o cabeçalho diz **Painel ENEM** (sem 2025)
- a página **Análise** mostra Δ esperado — os valores mudaram em relação à
  produção, é o efeito esperado do D=1
- uma habilidade qualquer abre o **carrossel de questões**
- passar o mouse num cabeçalho de tabela mostra o **tooltip novo**

## Passo 8 — Mergear (é isto que publica)

No PR #2, botão **Merge**. O Netlify detecta o push na `main` e publica em
`microdadosenem.netlify.app`. Leva alguns minutos.

## Passo 9 — Conferir no ar

```bash
curl -s https://microdadosenem.netlify.app | grep -o '<title>[^<]*</title>'
```

**Esperado:** `<title>Painel ENEM · Wayground</title>` — sem 2025.

E confira a página Análise no navegador, com o filtro de rede pública, pra ver
o Δ esperado novo.

---

## Se der errado: rollback

**Caminho rápido, sem tocar no git** — no painel do Netlify, site
`microdadosenem` → **Deploys** → escolher o deploy anterior ao merge →
**Publish deploy**. Volta em segundos, sem rebuild.

**Caminho pelo git** — reverter o merge na `main`:

```bash
git checkout main && git pull
git revert -m 1 <sha-do-merge>
git push origin main
```

**Restaurar os arquivos locais em D=1,7** — o `rebuild_d1.sh` guardou tudo
antes de mexer:

```bash
ls -d backup-d17-*          # acha a pasta
cat backup-d17-*/LEIA-ME.txt
```

---

## Depois de publicar

Falta resolver, na ordem (ver `ESTADO.md`):

1. **Paraná** — diagnosticar o `pr2_deploy` sem dado avaliável
   (`python3 pipeline/diag_deploy.py pr2_deploy`), corrigir, e publicar
   manualmente com `netlify deploy --prod --dir=pr2_deploy`.
2. **PR #1 do `enemparana`** — mergear pra `main` parar de ficar 21 commits
   atrás. Só depois disso dá pra linkar aquele repo ao Netlify e publicar o
   Paraná sem terminal.
3. **`COALESCE(NU_PARAM_C, 0)`** no `build_db.py` — item sem `c` cadastrado
   hoje rende `p_esp` nulo.
