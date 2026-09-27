#!/data/data/com.termux/files/usr/bin/bash
#
# Nexus — Hands-Free Voice Assistant
# ====================================
# Runs continuously in Termux. No button press needed — just say "Hey Nexus"
# followed by your command. Uses Android's free on-device speech recognition
# (termux-speech-to-text) for wake-word detection, so no cloud cost for
# listening — only actual commands go to the backend.
#
# Requirements: same as voice_assistant.sh, see termux/SETUP.md
#
# Start it: bash nexus_hands_free.sh
# Stop it: Ctrl+C, or close Termux
# For it to survive screen-off: this script takes a wake-lock automatically.

BACKEND_TEXT_URL="https://YOUR-DEPLOYED-BACKEND-URL/analyze-text"
WAKE_PHRASE="hey nexus"

termux-wake-lock  # keeps this script running even with the screen off
trap 'termux-wake-unlock; echo "Nexus stopped."; exit 0' SIGINT SIGTERM

echo "🟢 Nexus is listening for \"Hey Nexus\"... (Ctrl+C to stop)"

while true; do
  # Short listening window for the wake phrase — free, on-device, no network needed
  HEARD=$(termux-speech-to-text 2>/dev/null | tr '[:upper:]' '[:lower:]')

  if [[ "$HEARD" == *"$WAKE_PHRASE"* ]]; then
    termux-tts-speak "Yes?"
    echo "👂 Wake word detected. Listening for command..."

    # Capture the actual command — also free, on-device
    COMMAND_TEXT=$(termux-speech-to-text 2>/dev/null)

    if [ -z "$COMMAND_TEXT" ]; then
      termux-tts-speak "I didn't catch that."
      continue
    fi

    echo "📝 Command: $COMMAND_TEXT"
    echo "📤 Sending to Nexus backend..."

    HTTP_RESPONSE=$(curl -s -D - -o /tmp/nexus_response \
      -H "Content-Type: application/json" \
      -d "{\"text\": \"${COMMAND_TEXT}\"}" \
      "$BACKEND_TEXT_URL")

    CONTENT_TYPE=$(echo "$HTTP_RESPONSE" | grep -i "^content-type:" | tr -d '\r')

    if echo "$CONTENT_TYPE" | grep -q "application/json"; then
      # Device action
      ACTION=$(jq -r '.action' /tmp/nexus_response 2>/dev/null)
      echo "🔧 Action: $ACTION"
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
      # Trading analysis / general Q&A — audio response
      cp /tmp/nexus_response "$HOME/nexus_response.mp3"
      termux-media-player play "$HOME/nexus_response.mp3"
    fi

    rm -f /tmp/nexus_response
    echo "🟢 Listening for \"Hey Nexus\" again..."
  fi
done
