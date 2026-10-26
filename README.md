# VerifAI  (v3)

**An Integrated Multi-Agent System for Real-Time Research, Fact-Checking, and Bias Detection**

Ask a question, paste a link or text, upload a screenshot — or check a text for plagiarism. Five cooperating
agents (orchestrated by LangGraph) search the live web, verify each claim, try to *refute* the strong ones,
rate every source for credibility and political lean, and write a cited report while you watch each agent work.

```
Browser / Chrome extension ──REST + WebSocket──►  FastAPI  ──►  LangGraph pipeline
   question:  Research ─► Fact-Check ─► (low confidence? loop back, max 2×) ─► Critic ─► Bias Detector ─► Summarizer
   link/text/image:  Input ─► Fact-Check ─► Critic ─► Bias Detector ─► Summarizer
   plagiarism:  split text ─► search each passage on the web ─► compare ─► originality report
Services: Gemini API · Tavily web search · ChromaDB · SQLite (or PostgreSQL)
```

## What is new in v3
| Feature | What it does |
|---|---|
| **Clickable citations** | Every source is a numbered, clickable link. Each claim shows its evidence as `[1] supports`, `[3] refutes` chips that open the page. |
| **Plagiarism check** | Paste a text: each passage is searched on the web and compared with the pages found. You get an originality %, a risk level, matching sources and your text with copied parts highlighted. Also works on Indian-language text. |
| **Critic agent** | In *Deep* mode a fifth agent plays devil's advocate: it searches for evidence **against** the strongest claims and re-scores them. Each claim shows "Critic: upheld / weakened / downgraded". |
| **Link / text / image input** | Paste a URL, an article or a WhatsApp-style forward, or upload a screenshot. VerifAI reads it, picks out the claims and checks each one. |
| **Chrome extension** | Select text on any page → right-click → *Verify with VerifAI*. Also "Verify this page" and a plagiarism button. |
| **Feedback + analytics** | 👍/👎 on each verdict and on the whole report. A dashboard shows runs per day, time per agent, tokens, verdicts, Critic results and feedback. |
| **Accounts, history, export, sharing** | Register / log in, see your past checks, export a report as **PDF** or **Markdown**, and create a read-only **share link**. |
| **Summary originality check** | VerifAI checks its own summary for sentences copied from its sources. |
| **Safety & robustness** | Links from the web are never run as scripts, pages are fetched only from public addresses (no localhost / private networks), a per-IP rate limit protects your API quota, and your old database is upgraded automatically. |

---

## Run it — Windows

### Option A — you already have the v2 folder working (about 3 minutes)
1. **Close the running server** (Ctrl+C in its terminal).
2. Unzip `VerifAI_Project_v3.zip` and **copy everything inside its `verifai` folder over your existing `verifai` folder**
   (choose "Replace"). Your `.env`, `venv311` and database are not in the zip, so they are kept.
3. Open a terminal in your `verifai` folder and install the three new libraries:
   ```powershell
   venv311\Scripts\activate
   pip install -r requirements.txt
   ```
4. `.\check.bat`  → every line should say `[ OK ]` (it now also checks the new libraries).
5. `.\start.bat` → wait for `Ready`, then open **http://localhost:8000/**

Your existing history is kept — the database is upgraded automatically (you will see "Database upgraded: added …" once).

### Option B — fresh install (about 15 minutes)
1. Install **Python 3.11** from python.org (3.13 / 3.14 will not work).
2. Get two free keys: **Gemini** → https://aistudio.google.com/app/apikey  ·  **Tavily** → https://app.tavily.com
3. Unzip, open the `verifai` folder in VS Code (**File → Open Folder**), open a terminal and run `.\setup.bat`.
4. Open the new **`.env`** file, paste your keys, save:
   ```
   GEMINI_API_KEY=your-gemini-key
   TAVILY_API_KEY=tvly-your-tavily-key
   ```
5. `.\check.bat` (all `[ OK ]`), then `.\start.bat`, then open **http://localhost:8000/**

### Mac / Linux
`./setup.sh` → edit `.env` → `./check.sh` → `./start.sh` → open http://localhost:8000/

The first start downloads two small AI models (~250 MB) and can take a few minutes. Open the app at
**http://localhost:8000/** (do not open the HTML files directly).

---

## Using the features

**Verify page** — tabs: *Question · Link · Text · Image · Plagiarism*.
* **Deep (with Critic)** is slower and uses more API calls but is more trustworthy. **Quick** skips the Critic.
* After a result: **Export PDF / Export Markdown / Share link / Open as page**, and 👍 👎.
* A deep run makes roughly 15–25 model calls (10–15 in quick mode). On a free Gemini key, if you hit rate limits use
  Quick mode or lower `MAX_CLAIMS` in `.env`.

**Clickable citations** — in the *Citations* list every title is a link. In *Claim verification*, the `[n]` chips under
each claim open the exact page used as evidence (hover to see the quoted passage).

**Plagiarism** — paste at least ~15 words. Red = near-identical to a web page, amber = similar wording, green = checked
and original, grey = not checked (long texts are sampled to save API calls). Click `[n]` after a passage to jump to its source.

**Accounts** — *Log in / Register* in the top bar. Runs made while logged in appear in **History**. You can also use
VerifAI without an account (no history, but export and sharing still work for that session's report page).

**Share links** — *Share link* copies an address like `http://localhost:8000/ui/report.html?share=…`. It is read-only
(no feedback, no run details). It only works for people who can reach your server, so on a laptop it works for you only —
deploy the app (e.g. Render) to share with others. *Stop sharing* on the report page revokes it.

**Analytics** — log in, then open **Analytics**: runs per day, average time per agent, model calls and tokens per run,
claim verdicts, Critic outcomes, error rate and feedback.

### Chrome extension
1. Make sure the server is running (`start.bat`).
2. Chrome → address bar `chrome://extensions` → switch on **Developer mode** (top right) → **Load unpacked** →
   choose the **`extension`** folder inside `verifai`.
3. Pin the VerifAI icon (puzzle-piece menu → pin).
4. Use it: select text on any page → **right-click → Verify "…" with VerifAI** (a small window opens and streams the result),
   or click the toolbar icon (it picks up your current selection), or right-click anywhere → **Verify this page**.
5. If your server is not at `http://localhost:8000`, click ⚙ in the popup and enter the address (Chrome will ask permission).

Chrome's own pages (`chrome://…`, the Web Store) cannot be read by extensions — type or paste the text instead.

---

## Settings (`.env`)
| Setting | Default | Meaning |
|---|---|---|
| `GEMINI_API_KEY`, `TAVILY_API_KEY` | – | required |
| `GEMINI_MODEL_STRONG` / `GEMINI_MODEL_FAST` | `gemini-2.5-flash` / `gemini-2.5-flash-lite` | Google retires models over time. On a 404 run `python list_models.py` (in `backend`) and use a name from the list. |
| `MAX_CLAIMS` | 5 | Claims verified per run |
| `ENABLE_CRITIC`, `CRITIC_MAX_CLAIMS` | true, 3 | The Critic agent in Deep mode |
| `RUNS_PER_MINUTE` | 8 | Per-IP limit on runs |
| `DATABASE_URL` | built-in SQLite file | Only set to use PostgreSQL |

## Tests (optional)
```powershell
venv311\Scripts\activate
pip install -r requirements-dev.txt
cd backend
python -m pytest tests -q            # 38 tests: pipeline, Critic, inputs, plagiarism, API, export, sharing, analytics …
```
They use a fake model and fake search, so they cost nothing and need no keys. The two browser-side suites
(`frontend/tests`, `extension/tests`) need Node.js: `cd frontend/tests && npm install && npm test`.

## Troubleshooting
| What you see | Cause and fix |
|---|---|
| `ModuleNotFoundError: bs4` / `fpdf` | The new libraries are missing. Activate `venv311` and run `pip install -r requirements.txt`. |
| `ModuleNotFoundError` (anything else) | Wrong environment. Use `.\start.bat`, or run `setup.bat` again. |
| `Could not open requirements file` | You are in the wrong folder — `cd` into the one containing `requirements.txt` and `setup.bat`. |
| Page cannot reach the server | Server not running, or you opened an HTML file directly. Use http://localhost:8000/ |
| Card turns red: `404 models/…` | Model retired → `python list_models.py`, edit `GEMINI_MODEL_*` in `.env`, restart. |
| `429` / quota / "Too many requests" | Free-tier or per-IP limit. Wait a minute, use Quick mode, lower `MAX_CLAIMS`. |
| "No sources retrieved" | Tavily key wrong/empty → run `check.bat`. |
| Link tab: "private or local network" | Only public websites can be fetched (a safety rule). |
| Link tab: error 403/404 or "not enough readable text" | Some sites block automated readers, need a login, or build the page with JavaScript. Copy the article text and use the **Text** tab. |
| Image tab: "No readable text" | The image is too blurry or has no text. |
| Export PDF fails | Run `pip install -r requirements.txt` (needs `fpdf2`). |
| Extension: "Cannot reach the VerifAI server" | Start the server; check the address under ⚙. Reload the extension at `chrome://extensions` after changing files. |
| Extension: right-click menu missing | Reload the extension, then reload the web page. |
| Analytics / History redirect to login | They need a login (top right → Log in / Register). |
| Address already in use (port 8000) | Another copy is running — close it, or change `--port 8000` in `start.bat`. |

Harmless messages you can ignore: *huggingface_hub … symlinks*, *hf_xet*, *LLM is explicitly disabled. Using MockLLM*.

## Project structure
```
verifai/
├── setup.bat / check.bat / start.bat  (and .sh for Mac/Linux)   .env.example  requirements*.txt  Dockerfile
├── frontend/   index.html  login.html  history.html  report.html  analytics.html  common.js  app.css  tests/
├── extension/  manifest.json  background.js  popup.html/js/css  icons/  tests/        ← Chrome extension
└── backend/
    ├── main.py  config.py  dependencies.py  check_setup.py  list_models.py
    ├── agents/    state  ingest  research  factcheck  critic  bias_detector  summarizer  plagiarism  pipeline
    ├── routers/   research  plagiarism  reports  history  feedback  analytics  auth  health
    ├── services/  llm_factory  tavily_client  vector_store  web_fetch  similarity  export_service
    │              metrics  inputs  rate_limit  ws_manager  session_store  json_utils
    ├── models/    db_models  schemas
    └── tests/     pytest suite
```

## Known limitations
* The plagiarism check only compares against pages a web search returns — not paywalled, offline or private documents.
  A clean result is **not proof of originality**; a high result is a lead to investigate, not a verdict.
* Source credibility uses a small built-in list (~24 domains) plus an LLM estimate for the rest — illustrative, not a
  licensed rating database.
* Accuracy has **not** been measured yet (that is the evaluation work). Do not quote accuracy figures until you have run one.
* The Critic improves caution but costs extra API calls; it is skipped in Quick mode.
* Analytics shows aggregate numbers to any logged-in user (there are no admin roles).
* `POST /research` is open (no login needed) so the demo works out of the box.
