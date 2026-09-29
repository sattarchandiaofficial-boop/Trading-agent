#!/data/data/com.termux/files/usr/bin/bash
# Starts Nexus's backend on the phone. Run this once (or let boot/start_nexus.sh
# do it automatically), then use nexus_talk.sh or nexus_hands_free.sh to talk to it.

cd "$(dirname "$0")/../app" || exit 1

if [ -f "$HOME/.nexus_env" ]; then
  set -a; source "$HOME/.nexus_env"; set +a
else
  echo "⚠️  $HOME/.nexus_env not found — create it with your API keys first (see SETUP.md)."
  exit 1
fi

termux-wake-lock
echo "Starting Nexus server on http://127.0.0.1:8765 ..."
python3 -m uvicorn server:app --host 127.0.0.1 --port 8765
