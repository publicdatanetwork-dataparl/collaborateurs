#!/usr/bin/env bash
# Runner « europarl » sur Home Assistant (ou toute machine avec Docker).
# Usage : ./install-runner-europarl-docker.sh <TOKEN>
# Sur Home Assistant OS : installer le module complémentaire « Advanced SSH
# and Web Terminal », s'y connecter, puis lancer ce script. Le conteneur
# redémarre tout seul (unless-stopped) : plus besoin du MacBook allumé.
set -euo pipefail

TOKEN="${1:-}"
if [ -z "$TOKEN" ]; then
  echo "Erreur : passer le token d'enregistrement en argument." >&2
  echo "Usage: $0 <TOKEN>" >&2
  echo "Token : GitHub → dataparl/collaborateurs → Settings → Actions → Runners → New self-hosted runner" >&2
  exit 1
fi

command -v docker >/dev/null 2>&1 || { echo "Erreur : docker introuvable." >&2; exit 1; }

if docker ps -a --format '{{.Names}}' | grep -qx dataparl-runner; then
  echo "→ Le conteneur dataparl-runner existe déjà. Pour réinstaller :"
  echo "  docker rm -f dataparl-runner && docker volume rm dataparl-runner"
  exit 1
fi

docker volume create dataparl-runner >/dev/null

# Image communautaire éprouvée : inscrit le runner, le lance, et le
# réenregistre à chaque redémarrage. Étiquette « europarl » = cible du
# workflow « Suivi Parlement européen ».
docker run -d \
  --name dataparl-runner \
  --restart unless-stopped \
  -e REPO_URL=https://github.com/dataparl/collaborateurs \
  -e RUNNER_TOKEN="$TOKEN" \
  -e RUNNER_LABELS=europarl \
  -e RUNNER_NAME=europarl-homeassistant \
  -e RUNNER_WORK_DIRECTORY=/work \
  -v dataparl-runner:/work \
  myoung34/github-runner:latest

echo ""
echo "✅ Conteneur dataparl-runner démarré (redémarrage automatique)."
echo "Vérifier : docker logs -f dataparl-runner (attendre « Listening for Jobs »)"
echo "puis https://github.com/dataparl/collaborateurs/settings/actions/runners"
echo "(deux runners étiquetés europarl : le Mac quand il est allumé, sinon ce conteneur)."
