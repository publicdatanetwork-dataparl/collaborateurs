#!/usr/bin/env bash
# Installation du runner auto-hébergé « europarl » pour dataparl/collaborateurs — macOS (Apple Silicon).
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

# macOS obligatoire sur Apple Silicon
if [ "$(uname)" != "Darwin" ] || [ "$(uname -m)" != "arm64" ]; then
  echo "Erreur : ce script cible macOS arm64 (Apple Silicon). Utilise install-runner-europarl.sh pour Linux x64." >&2
  exit 1
fi

REPO_URL="https://github.com/dataparl/collaborateurs"
RUNNER_DIR="$HOME/actions-runner"
LABELS="europarl,self-hosted"

mkdir -p "$RUNNER_DIR"
cd "$RUNNER_DIR"

if [ -f .runner ]; then
  echo "→ Un runner est déjà configuré dans $RUNNER_DIR."
  echo "  Pour réinstaller : rm -rf $RUNNER_DIR puis relancer ce script."
  exit 1
fi

echo "→ Téléchargement de la dernière version du runner Actions (macOS arm64)…"
VER=$(curl -s https://api.github.com/repos/actions/runner/releases/latest | grep -oE '"tag_name": ?"v[0-9.]+"' | grep -oE '[0-9.]+' | head -1)
if [ -z "$VER" ]; then echo "Erreur : impossible de récupérer la version du runner." >&2; exit 1; fi
curl -o actions-runner.tar.gz -L "https://github.com/actions/runner/releases/download/v${VER}/actions-runner-osx-arm64-${VER}.tar.gz"
tar xzf actions-runner.tar.gz && rm actions-runner.tar.gz

echo "→ Enregistrement du runner (étiquettes : $LABELS)…"
./config.sh --url "$REPO_URL" --token "$TOKEN" --labels "$LABELS" --name "europarl-$(hostname -s)" --work _work

# Pas de svc.sh sur macOS : service via launchd
cat > "$HOME/Library/LaunchAgents/fr.dataparl.runner-europarl.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
  <dict>
    <key>Label</key><string>fr.dataparl.runner-europarl</string>
    <key>ProgramArguments</key>
    <array>
      <string>$RUNNER_DIR/run.sh</string>
    </array>
    <key>WorkingDirectory</key><string>$RUNNER_DIR</string>
    <key>RunAtLoad</key><true/>
    <key>KeepAlive</key><true/>
    <key>StandardOutPath</key><string>$RUNNER_DIR/runner.log</string>
    <key>StandardErrorPath</key><string>$RUNNER_DIR/runner.log</string>
  </dict>
</plist>
PLIST
launchctl unload "$HOME/Library/LaunchAgents/fr.dataparl.runner-europarl.plist" 2>/dev/null || true
launchctl load "$HOME/Library/LaunchAgents/fr.dataparl.runner-europarl.plist"
echo "✅ Runner installé et démarré (service launchd, redémarre avec la session)."

cat <<'EOF'

Prochaines étapes :
  1. Vérifier que le runner apparaît « Idle » sur
     https://github.com/dataparl/collaborateurs/settings/actions/runners
  2. Diagnostiquer le WAF depuis ce poste : python3 -m collabs diag europarl
  3. Lancer un premier dry-run : Actions → « Suivi Parlement européen » →
     Run workflow (DRY RUN coché)
EOF
