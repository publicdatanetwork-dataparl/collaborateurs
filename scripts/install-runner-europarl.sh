#!/usr/bin/env bash
# Installation du runner auto-hébergé « europarl » pour dataparl/collaborateurs.
# Usage : ./install-runner-europarl.sh <TOKEN>
# Le TOKEN est obtenu sur GitHub : Settings → Actions → Runners → New self-hosted runner.
# Il expire au bout d'une heure : ne le générer qu'au moment de l'installation.
set -euo pipefail

TOKEN="${1:-}"
if [ -z "$TOKEN" ]; then
  echo "Erreur : passer le token d'enregistrement en argument." >&2
  echo "Usage: $0 <TOKEN>" >&2
  exit 1
fi

REPO_URL="https://github.com/dataparl/collaborateurs"
RUNNER_DIR="$HOME/actions-runner"
LABELS="europarl,self-hosted"

# 1. Dossier
mkdir -p "$RUNNER_DIR"
cd "$RUNNER_DIR"

# 2. Déjà configuré ?
if [ -f .runner ]; then
  echo "→ Un runner est déjà configuré dans $RUNNER_DIR (fichier .runner présent)."
  echo "  Pour réinstaller : rm -rf $RUNNER_DIR puis relancer ce script."
  exit 1
fi

# 3. Dernière version du runner (Linux x64)
echo "→ Téléchargement de la dernière version du runner Actions (Linux x64)…"
VER=$(curl -s https://api.github.com/repos/actions/runner/releases/latest | grep -oP '"tag_name":\s*"v\K[0-9.]+' | head -1)
if [ -z "$VER" ]; then echo "Erreur : impossible de récupérer la version du runner." >&2; exit 1; fi
curl -o actions-runner.tar.gz -L "https://github.com/actions/runner/releases/download/v${VER}/actions-runner-linux-x64-${VER}.tar.gz"
tar xzf actions-runner.tar.gz && rm actions-runner.tar.gz

# 4. Dépendances
echo "→ Vérification des dépendances…"
./bin/installdependencies.sh >/dev/null 2>&1 || true

# 5. Enregistrement avec l'étiquette europarl (obligatoire : cible du workflow)
echo "→ Enregistrement du runner (étiquettes : $LABELS)…"
./config.sh --url "$REPO_URL" --token "$TOKEN" --labels "$LABELS" --name "europarl-$(hostname)" --work _work

# 6. Service au démarrage
echo "→ Installation du service (démarrage automatique)…"
if command -v systemctl >/dev/null 2>&1; then
  sudo ./svc.sh install
  sudo ./svc.sh start
  echo "✅ Runner installé et démarré en service."
else
  echo "⚠ systemd absent : lancer le runner manuellement avec ./run.sh"
fi

cat <<'EOF'

Prochaines étapes :
  1. Vérifier que le runner apparaît « Idle » sur
     https://github.com/dataparl/collaborateurs/settings/actions/runners
  2. Diagnostiquer le WAF depuis ce poste : python -m collabs diag europarl
  3. Lancer un premier dry-run : Actions → « Suivi Parlement européen » →
     Run workflow (DRY RUN coché)
EOF
