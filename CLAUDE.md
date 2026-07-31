# Instruções do repositório (`painelenem` — painel ENEM nacional)

Este repo é o **`plataforma/`**: o pipeline que gera os dois painéis. O
arquivo de estado canônico está no repo irmão `enemparana`, em `ESTADO.md` —
leia se ele estiver por perto (`~/Documents/enemparana/ESTADO.md`).
`status.md` aqui tem o detalhe deste repo.

## Fatos que já foram confundidos

1. **Este painel publica por push/merge na `main`** — o Netlify está
   conectado a este repo no GitHub, deploy automático
   (https://microdadosenem.netlify.app). O painel **Paraná** (repo
   `enemparana`) é o oposto: `netlify deploy --prod --dir=pr2_deploy`, manual.
2. **`pr2_deploy/` é derivado de `deploy/`** — `pr2/deploy_pr2.py` lê
   `deploy/api/` e `data/enem2025.sqlite`. Um rebuild corrige os dois
   painéis; não existe "rebuild só do Paraná".
3. **A 3PL vai sem o fator D** (`build_db.py:217`). Os `NU_PARAM_A` do INEP
   já são logísticos; `D=1,7` subestimava o acerto em ~2,5 pp. Agregação
   continua aluno a aluno, não no θ médio.
4. **Não afirme número que não mediu.** `verifica_calibracao.py <deploy>` mede
   a calibração sem precisar dos microdados; `diag_deploy.py <deploy>...`
   diz por que um deploy ficou sem dado avaliável.

## Cascata do dado

```
../microdados_enem_{ano}/DADOS  →  build_all_years.py  →  data/enem{ano}.sqlite
  →  build_hist_db.py  →  data/enem_hist.sqlite
       →  exporta_netlify.py  →  deploy/         (nacional)
       →  pr2/deploy_pr2.py   →  pr2_deploy/     (Paraná)
```

`bash pipeline/rebuild_d1.sh` faz tudo isso com backup automático antes e
verificação de calibração no fim.

## Branch

Desenvolvimento em `claude/replica-melhorias-paranav2`. Não mergear na `main`
sem pedido explícito — merge aqui **publica em produção**.
