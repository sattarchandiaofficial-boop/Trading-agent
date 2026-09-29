#!/data/data/com.termux/files/usr/bin/bash
# Press Enter, speak, get an answer. Requires the server to be running
# (see start_server.sh). All device actions are executed by the server
# itself since it runs on this same phone — this script just relays text.

URL="http://127.0.0.1:8765/analyze-text"

echo "Press Enter, then speak your command."
read -r
echo "Listening..."
TEXT=$(termux-speech-to-text 2>/dev/null)

if [ -z "$TEXT" ]; then
  termux-tts-speak "I didn't catch that."
  exit 0
fi

echo "You said: $TEXT"
RESPONSE=$(curl -s -X POST "$URL" -H "Content-Type: application/json" \
  --data-binary @<(python3 -c "import json,sys; print(json.dumps({'text': sys.argv[1]}))" "$TEXT"))

SPOKEN=$(echo "$RESPONSE" | python3 -c "import json,sys; print(json.load(sys.stdin).get('spoken_summary',''))")
echo "$SPOKEN"
termux-tts-speak "$SPOKEN"
