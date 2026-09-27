# Nexus — Termux Voice Assistant Setup (Mobile Only)

## Step 1: Install two free apps

1. **F-Droid** — foss app store, download from f-droid.org (Play Store's Termux is outdated/broken)
2. From F-Droid, install:
   - **Termux**
   - **Termux:API**

## Step 2: Open Termux, run these commands (one time)

```bash
pkg update -y
pkg install -y termux-api curl jq
termux-setup-storage
```

`termux-setup-storage` will ask for a storage permission — allow it.

## Step 3: Get this script onto your phone

Easiest way: in Termux, run:

```bash
curl -o voice_assistant.sh "https://raw.githubusercontent.com/YOUR-USERNAME/trading-agent/main/termux/voice_assistant.sh"
```

(Replace with your actual GitHub raw file URL once you've uploaded the project — same repo you used for the backend/frontend.)

## Step 4: Edit the backend URL

```bash
nano voice_assistant.sh
```

Find the `BACKEND_URL` line, replace with your Render URL + `/analyze` (same one used in `frontend/index.html`). Save with `Ctrl+O`, `Enter`, exit with `Ctrl+X`.

## Step 5: Run it

```bash
bash voice_assistant.sh
```

Speak your command, press Enter when done. It will either speak back a trading analysis, or perform the device action (open app, torch, etc.) directly.

## Notes

- First run will ask for microphone permission via a popup — allow it.
- To make this a one-tap shortcut: install **Termux:Widget** (also free, F-Droid) — it adds a home-screen icon that runs this script directly.
- Device action list currently supported: open WhatsApp/YouTube/Chrome, torch on/off, volume up/down, vibrate, read battery, read time. More can be added by extending `DEVICE_ACTIONS` in `server.py` and the matching `case` in this script.

## Hands-Free Mode (no button press — say "Hey Nexus")

Instead of `voice_assistant.sh`, run:

```bash
curl -o nexus_hands_free.sh "https://raw.githubusercontent.com/YOUR-USERNAME/trading-agent/main/termux/nexus_hands_free.sh"
nano nexus_hands_free.sh   # set BACKEND_TEXT_URL to your Render URL + /analyze-text
bash nexus_hands_free.sh
```

This runs continuously — say **"Hey Nexus"**, wait for it to say "Yes?", then speak your command. It keeps listening in a loop until you stop it (Ctrl+C).

**Honest limitations:**
- Wake-word detection isn't perfect — it may occasionally miss it or false-trigger on similar-sounding speech
- Uses more battery than the tap-to-talk version, since it's always listening
- Termux must stay running (don't force-stop the app) — screen can be off, the script holds a wake-lock so it keeps working
- Wake-word listening itself is free and on-device (no internet needed for that part); only actual commands after "Hey Nexus" get sent to the backend

## Auto-Start on Boot (never open Termux manually)

By default you have to open Termux and run the script yourself each time. To make Nexus start automatically whenever your phone turns on:

### Step 1: Install Termux:Boot
From F-Droid (same place as Termux and Termux:API) — free.

### Step 2: Open Termux:Boot once
Just open the app once after installing (it needs to run once for Android to register it) — you can close it right after, nothing to configure inside it.

### Step 3: Create the boot folder and script
In Termux:

```bash
mkdir -p ~/.termux/boot
curl -o ~/.termux/boot/start_nexus.sh "https://raw.githubusercontent.com/YOUR-USERNAME/trading-agent/main/termux/boot/start_nexus.sh"
chmod +x ~/.termux/boot/start_nexus.sh
```

### Step 4: Turn off battery optimization for Termux
Phone Settings → Apps → Termux → Battery → **Unrestricted / No restrictions**.
(Also do this for Termux:Boot if the option appears for it.)
Without this, Android may silently kill Nexus in the background after a while — this is Android's own battery-saving behavior, not a bug in the script.

### Step 5: Restart your phone
After restart, Nexus should already be listening — try saying "Hey Nexus" without opening any app.

**Honest note:** even with this set up, Android *can* still occasionally kill background processes on some phone brands (especially Xiaomi/Oppo/Vivo, which are known for aggressive battery management beyond stock Android settings) — if Nexus stops responding after a while, that brand may have its own extra battery-saver menu to whitelist Termux in as well.
