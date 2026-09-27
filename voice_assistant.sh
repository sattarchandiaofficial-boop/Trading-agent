#!/data/data/com.termux/files/usr/bin/bash
#
# Termux Voice Assistant
# ======================
# Runs entirely on the phone via Termux. Records your voice, sends it to
# the cloud backend (same one the web app uses), and either:
#   - plays back a spoken trading analysis, OR
#   - executes a device action locally (open app, torch, volume, etc.)
#
# Requirements (install once, see termux/SETUP.md):
#   pkg install termux-api curl jq
#   (Termux:API companion app must also be installed from F-Droid/Play)
#
# Usage: bash voice_assistant.sh
# (Add to Termux:Widget or Termux:Boot for one-tap / auto-start later.)

BACKEND_URL="https://YOUR-DEPLOYED-BACKEND-URL/analyze"  # same URL as the web app uses
RECORDING_FILE="$HOME/voice_input.wav"
RESPONSE_AUDIO="$HOME/voice_response.mp3"
RESPONSE_JSON="$HOME/voice_response.json"

echo "🎙️  Recording... speak now, press Enter when done."
termux-microphone-record -f "$RECORDING_FILE" -l 0 &
REC_PID=$!
read -r  # waits for Enter key
kill -2 "$REC_PID" 2>/dev/null
sleep 1

echo "📤 Sending to backend..."
HTTP_RESPONSE=$(curl -s -D - -o /tmp/response_body \
  -F "audio=@${RECORDING_FILE}" \
  "$BACKEND_URL")

CONTENT_TYPE=$(echo "$HTTP_RESPONSE" | grep -i "^content-type:" | tr -d '\r')

if echo "$CONTENT_TYPE" | grep -q "application/json"; then
  # Device action response — JSON, no audio
  cp /tmp/response_body "$RESPONSE_JSON"
  MODE=$(jq -r '.mode' "$RESPONSE_JSON")
  ACTION=$(jq -r '.action' "$RESPONSE_JSON")

  echo "🔧 Detected action: $ACTION"

  case "$ACTION" in
    open_whatsapp) termux-open-url "whatsapp://send" ;;
    open_youtube)  termux-open-url "https://youtube.com" ;;
    open_chrome)   termux-open-url "https://google.com" ;;
    torch_on)      termux-torch on ;;
    torch_off)     termux-torch off ;;
    volume_up)     termux-volume music 15 ;;
    volume_down)   termux-volume music 3 ;;
    vibrate)       termux-vibrate -d 500 ;;
    read_battery)
      BATT=$(termux-battery-status | jq -r '.percentage')
      termux-tts-speak "Battery is at ${BATT} percent"
      ;;
    read_time)
      termux-tts-speak "The time is $(date +'%I:%M %p')"
      ;;
    *)
      termux-tts-speak "Sorry, I don't know how to do that yet"
      ;;
  esac

else
  # Trading analysis / general Q&A response — audio + headers
  cp /tmp/response_body "$RESPONSE_AUDIO"
  ANALYSIS_JSON=$(echo "$HTTP_RESPONSE" | grep -i "^x-analysis-json:" | sed 's/^[Xx]-[Aa]nalysis-[Jj]son: *//' | tr -d '\r')
  echo "📊 $ANALYSIS_JSON" | head -c 500
  echo ""
  termux-media-player play "$RESPONSE_AUDIO"
fi

rm -f "$RECORDING_FILE" /tmp/response_body
echo "✅ Done."
