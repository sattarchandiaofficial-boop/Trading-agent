# Mobile AI Trading Agent — Setup Guide

## Kya kya hai is project me

```
trading_agent/
├── data_layer.py         # OHLC + Chrome-research fetching (mechanical only)
├── raw_detectors.py       # All math/geometry: structure, S/R, SMC, ICT,
│                           # volatility, momentum, divergence, HMM+BOCPD
│                           # regime, correlation, anomaly, risk-reward
├── specialist_agents.py   # All 16 AI specialist agents (Groq Llama 3.3 70B)
├── head_agent.py           # Synthesizer — final verdict
├── memory_store.py         # Trade journal (Upstash Redis free tier)
├── orchestrator.py         # Ties everything together, runs agents in parallel
├── server.py                # FastAPI backend — the endpoint the app calls
├── frontend/index.html     # Tap-and-talk mobile web app (PWA)
└── requirements.txt
```

## Step 1 — Free accounts banayein (sab free, koi credit card nahi)

1. **Groq** — console.groq.com → API key banayein → `GROQ_API_KEY`
2. **API Ninjas** — api-ninjas.com/register → API key → `API_NINJAS_KEY`
3. **Upstash** (trade journal storage) — upstash.com → free Redis database banayein →
   `UPSTASH_REDIS_REST_URL` aur `UPSTASH_REDIS_REST_TOKEN` (dashboard me milenge)

## Step 2 — Environment variables set karein

```bash
export GROQ_API_KEY="..."
export API_NINJAS_KEY="..."
export UPSTASH_REDIS_REST_URL="..."
export UPSTASH_REDIS_REST_TOKEN="..."
```

## Step 3 — Local test (apne kisi bhi machine pe, sirf testing ke liye)

```bash
pip install -r requirements.txt
playwright install chromium   # Chrome research agents ke liye zaroori
python -c "from orchestrator import run_full_analysis; import json; print(json.dumps(run_full_analysis('XAUUSD'), indent=2, default=str))"
```

Ye direct terminal se ek poora analysis run karega — voice/server ke bina — taake sab
agents sahi kaam kar rahe hain ye confirm ho sake.

## Step 4 — Backend deploy karein (PC/VPS ke bina)

`server.py` ko kisi bhi **free-tier Python hosting** pe deploy karein — jaise Render,
Railway, ya Fly.io ka free tier. Wahan upar wale environment variables set karein
(unke dashboard me), aur `requirements.txt` se dependencies install ho jayengi.

Deploy hone ke baad aapko ek public URL milega (jaise `https://your-app.onrender.com`).

## Step 5 — Frontend wire karein

`frontend/index.html` me ye line dhoondein:

```js
const BACKEND_URL = "https://YOUR-DEPLOYED-BACKEND-URL/analyze";
```

Apne Step 4 wale URL se replace karein (`/analyze` end me zaroor rahe).

## Step 6 — Mobile pe use karein

`frontend/index.html` ko kahin host karein (GitHub Pages free hai, ya usi backend
host se static file serve kar sakte hain) — phir us link ko Chrome (mobile) me kholein,
aur "Add to Home Screen" karein. Ab ye ek app ki tarah use hoga.

## Zaroori notes

- **Chrome-research functions** (`fetch_upcoming_news`, `fetch_cot_report`,
  `fetch_seasonality` in `data_layer.py`) Playwright use karte hain — kuch selectors
  (jaise Forex Factory ka HTML structure) waqt ke sath badal sakte hain. Agar ye
  agents fail hon, pehle un teeno functions ke selectors check karein.
- **Forex pairs** (EURUSD, etc.) ke liye `data_layer.py` me `fetch_ohlc()` ka forex
  branch abhi placeholder hai — API Ninjas dashboard pe exact forex historical
  endpoint ka naam confirm kar ke wahan set karein.
- **DXY correlation** ke liye bhi sahi free source confirm karna hoga — abhi wahi
  `fetch_ohlc` pattern reuse ho raha hai.
- Groq free tier limits (30 req/min, ~1000 req/din) is design me har analysis ~17
  calls leta hai — din me lagbhag 55-58 poori analysis requests ho sakti hain, jo
  on-demand use ke liye kaafi hai.
