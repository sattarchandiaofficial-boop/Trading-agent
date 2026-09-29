# Nexus — Mobile AI Trading Agent (runs entirely on your phone, in Termux)

No PC, no VPS, no Render/Hugging Face, no card. Everything — the backend,
the 16 specialist agents, the Head Agent, the data fetching, and the voice
loop — runs inside Termux on your Android phone. The web app talks to the
server at `http://127.0.0.1:8765`, which is your own phone, not the internet.

## What's in this folder

```
app/
├── data_layer.py         # Price candles (API Ninjas/Twelve Data), news
│                          # (Forex Factory JSON), COT (CFTC API), seasonality —
│                          # plain HTTP feeds only, no browser needed anywhere
├── raw_detectors.py       # All math: structure, S/R, SMC, ICT, RSI/divergence,
│                          # HMM regime + BOCPD (pure numpy), correlation, anomaly
├── llm.py                  # Talks to Groq, paced to its free-tier token limits
├── specialist_agents.py    # All 16 AI agents — open-ended prompts, no hardcoded rules
├── head_agent.py            # Synthesizer — reasons its own final verdict
├── memory_store.py           # Trade journal via Upstash Redis (free tier)
├── orchestrator.py            # Ties it all together
├── server.py                   # The local server — also executes device actions directly
├── static/index.html            # Tap-and-talk web app
└── requirements.txt

termux/
├── start_server.sh        # Starts the local server
├── nexus_talk.sh            # Press Enter, speak, get an answer
├── nexus_hands_free.sh        # Say "Hey Nexus" — no button at all
└── boot/start_nexus.sh          # Auto-starts everything when the phone boots
```

## Step 1 — Install Termux (F-Droid, not Play Store)

1. Install **F-Droid**: https://f-droid.org
2. From F-Droid install: **Termux** and **Termux:API**
3. (Optional, for hands-free auto-start) also install **Termux:Boot**

## Step 2 — One-time Termux setup

Open Termux and run:

```bash
pkg update -y
pkg install -y python git termux-api
termux-setup-storage      # allow the storage permission popup
```

## Step 3 — Get the code onto your phone

```bash
cd ~
git clone https://github.com/YOUR-USERNAME/Trading-agent.git nexus-src
mkdir -p ~/nexus
cp -r ~/nexus-src/app ~/nexus-src/termux ~/nexus/
cd ~/nexus/app
pip install -r requirements.txt
```

(This reuses your existing GitHub repo — just push this new `nexus/` folder
to it first from wherever you're reading this, the same way you uploaded
files to GitHub before.)

## Step 4 — Add your API keys

```bash
cat > ~/.nexus_env << 'EOF'
GROQ_API_KEY=your_groq_key_here
API_NINJAS_KEY=your_api_ninjas_key_here
UPSTASH_REDIS_REST_URL=your_upstash_url_here
UPSTASH_REDIS_REST_TOKEN=your_upstash_token_here
EOF
```

Paste your real values in place of the placeholders (use `nano ~/.nexus_env`
if `cat >` is awkward on your keyboard — `Ctrl+O` then Enter to save, `Ctrl+X`
to exit).

**Forex pairs (EURUSD etc.) need one more free key** — gold works without
it. Get a free key at https://twelvedata.com (no card) and add a line:
```
TWELVE_DATA_KEY=your_twelvedata_key_here
```

## Step 5 — Start it and test

```bash
cd ~/nexus/termux
bash start_server.sh
```

Leave that running, open a **second Termux session** (swipe from the left
edge → "New session") and test:

```bash
curl http://127.0.0.1:8765/health
```

You should see `{"status":"ok",...}`. Now try a real question:

```bash
bash nexus_talk.sh
```

Press Enter, say "what's gold's regime right now", and listen.

## Step 6 — Use the web app

With the server running, open **Chrome on the same phone** and go to:

```
http://127.0.0.1:8765/app/
```

Tap and hold the mic button, speak, release. You'll see the full 17-agent
breakdown and hear the verdict spoken back.

## Step 7 — Hands-free ("Hey Nexus", no button)

```bash
bash nexus_hands_free.sh
```

Say **"Hey Nexus"**, wait for "Yes?", then speak your command.

## Step 8 — Auto-start on boot (never open Termux manually)

```bash
mkdir -p ~/.termux/boot
cp ~/nexus/termux/boot/start_nexus.sh ~/.termux/boot/
chmod +x ~/.termux/boot/start_nexus.sh
```

Then: phone Settings → Apps → Termux → Battery → **Unrestricted** (otherwise
Android may kill the background process after a while — this is Android's
own battery-saving behavior, not a bug here). Restart your phone; Nexus
should already be listening for "Hey Nexus" afterward.

**Honest note:** some phone brands (Xiaomi, Oppo, Vivo) have their own
extra-aggressive battery managers beyond stock Android settings — if Nexus
stops responding after a while, check that brand's own battery/autostart
menu too.

## Honest limitations, up front

- **Gold price data is ~15 minutes delayed** on the free API Ninjas plan.
  Always confirm the live price on your own broker before actually placing
  a trade — Nexus is for analysis, not execution.
- **Groq's free tier has token-per-minute limits.** A full 17-agent analysis
  can take noticeably longer than a single-agent question because of the
  pacing in `llm.py` — this is intentional, it avoids failed requests.
- **News/COT/seasonality depend on third-party free feeds** (Forex Factory,
  CFTC) that can occasionally change format or go down; if one of those
  agents reports an error, the rest of the analysis still runs normally.
- **Order Flow was intentionally left out** — no free feed provides real
  bid/ask depth data, especially for OTC forex.
- Device actions require the **Termux:API app** (not just the `termux-api`
  package) to be installed and given its permissions.
