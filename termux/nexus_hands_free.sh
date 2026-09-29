#!/data/data/com.termux/files/usr/bin/bash
#
# Nexus — Hands-Free Loop. Say "Hey Nexus" then your command. No button.
# Wake-word detection is free/on-device (Android's speech recognizer via
# termux-speech-to-text). Requires the server to already be running
# (start_server.sh) — this script only talks to it over localhost.

URL="http://127.0.0.1:8765/analyze-text"
WAKE_PHRASE="hey nexus"

termux-wake-lock
trap 'termux-wake-unlock; echo "Nexus stopped."; exit 0' SIGINT SIGTERM

echo "🟢 Nexus is listening for \"Hey Nexus\"... (Ctrl+C to stop)"

while true; do
  HEARD=$(termux-speech-to-text 2>/dev/null | tr '[:upper:]' '[:lower:]')

  if [[ "$HEARD" == *"$WAKE_PHRASE"* ]]; then
    termux-tts-speak "Yes?"
    echo "👂 Wake word detected. Listening for command..."
    COMMAND_TEXT=$(termux-speech-to-text 2>/dev/null)

    if [ -z "$COMMAND_TEXT" ]; then
      termux-tts-speak "I didn't catch that."
      continue
    fi

    echo "📝 Command: $COMMAND_TEXT"
    RESPONSE=$(curl -s -X POST "$URL" -H "Content-Type: application/json" \
      --data-binary @<(python3 -c "import json,sys; print(json.dumps({'text': sys.argv[1]}))" "$COMMAND_TEXT"))

    SPOKEN=$(echo "$RESPONSE" | python3 -c "import json,sys; print(json.load(sys.stdin).get('spoken_summary','Sorry, something went wrong.'))")
    echo "$SPOKEN"
    termux-tts-speak "$SPOKEN"
    echo "🟢 Listening for \"Hey Nexus\" again..."
  fi
done
