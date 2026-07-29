#!/usr/bin/env bash
#
# Rebuild completo com o p_esp em D=1 e republicação dos dois painéis.
#
# Roda na raiz do plataforma (a pasta que tem pipeline/, web/, pr2/, data/).
# Precisa dos microdados em ../microdados_enem_{2021..2025}/DADOS.
#
# Por que um script só pros dois painéis: o pr2_deploy (Paraná) é derivado
# do deploy nacional — pr2/deploy_pr2.py lê deploy/api/ e data/enem2025.sqlite.
# Um rebuild corrige a origem e os dois painéis saem certos, sem aproximação:
# o p_esp é recalculado aluno a aluno a partir do θ real de cada ano.
#
# Uso:  bash pipeline/rebuild_d1.sh
#
set -euo pipefail

BASE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$BASE"

PY=python3
[ -x .venv/bin/python ] && PY=.venv/bin/python

STAMP="$(date +%Y%m%d-%H%M)"
BKP="backup-d17-$STAMP"

hr() { printf '\n\033[1m== %s\033[0m\n' "$1"; }

# ---------------------------------------------------------------- 0. sanidade
hr "0/6  Conferindo que o build_db.py está em D=1"
if grep -q 'exp(-1.7 \* i.NU_PARAM_A' pipeline/build_db.py; then
  echo "! build_db.py ainda tem o fator 1.7 — abortando."
  echo "  Puxe a branch com a correção antes de rodar."
  exit 1
fi
grep -q 'exp(-i.NU_PARAM_A' pipeline/build_db.py \
  || { echo "! não achei a 3PL esperada em build_db.py — abortando."; exit 1; }
echo "ok — 3PL sem o fator D."

for ano in 2021 2022 2023 2024 2025; do
  d="../microdados_enem_${ano}/DADOS"
  [ -d "$d" ] && echo "  microdados $ano ok" || echo "  ! microdados $ano AUSENTES ($d) — o ano será pulado"
done

# ---------------------------------------------------------------- 1. backup
hr "1/6  Backup do que está no ar  →  $BKP/"
# cp -al = hardlinks: instantâneo e sem gastar disco. O rebuild reescreve os
# arquivos (novos inodes), então o backup fica intacto.
mkdir -p "$BKP"
for d in deploy pr2_deploy data; do
  [ -d "$d" ] || continue
  cp -al "$d" "$BKP/$d"
  echo "  $d  →  $BKP/$d  ($(du -sh --apparent-size "$d" | cut -f1))"
done
cat > "$BKP/LEIA-ME.txt" <<TXT
Backup do painel ANTES da correção D=1, feito em $STAMP.
Conteúdo: deploy/ (nacional), pr2_deploy/ (Paraná) e data/ (SQLites), todos
com o p_esp calculado em D=1,7 — exatamente o que estava publicado.

Para voltar o site ao ar sem refazer nada:
    netlify deploy --prod --dir=$BKP/deploy      # nacional
    netlify deploy --prod --dir=$BKP/pr2_deploy  # Paraná

Para restaurar as pastas de trabalho:
    rm -rf deploy pr2_deploy data
    cp -al $BKP/deploy $BKP/pr2_deploy $BKP/data .
TXT
echo "  instruções de rollback em $BKP/LEIA-ME.txt"

# ---------------------------------------------------------------- 2. SQLites
hr "2/6  build_all_years.py — p_esp aluno a aluno, D=1, 2021-2025  (demorado)"
$PY pipeline/build_all_years.py

hr "3/6  build_hist_db.py — rollup cross-year"
$PY pipeline/build_hist_db.py

# ---------------------------------------------------------------- 4. deploys
hr "4/6  exporta_netlify.py — painel nacional"
$PY pipeline/exporta_netlify.py

hr "5/6  pr2/deploy_pr2.py — painel Paraná (herda o deploy/api corrigido)"
$PY pr2/deploy_pr2.py

# ---------------------------------------------------------------- 6. conferir
hr "6/6  Calibração — o erro tem que cair de ~-2,4 pp para |erro| < 1 pp"
$PY pipeline/verifica_calibracao.py deploy
$PY pipeline/verifica_calibracao.py pr2_deploy

hr "Pronto"
cat <<TXT
Se a calibração acima ficou dentro de |erro| < 1 pp, publique:

    netlify deploy --prod --dir=deploy        # nacional
    netlify deploy --prod --dir=pr2_deploy    # Paraná

Rollback a qualquer momento: $BKP/LEIA-ME.txt
TXT
