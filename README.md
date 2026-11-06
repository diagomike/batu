# Batu City Administration portal (demo)

Working demo of **batu.gov.et**: city services, kebele finder, city government, Discover Batu, Invest, news and notices, online requests, payments (simulated Telebirr), tracking, a staff desk, and **Ask Batu**, a retrieval-based assistant that answers only from the city's own pages.

Languages: Afaan Oromoo (default), Amharic and English. Afaan Oromoo and Amharic are machine translated with Google Translate and labelled as such on every page.

## Run it

```bash
pip install -r requirements.txt
copy .env.example .env      # then add GEMINI_API_KEY (free) and an ADMIN_TOKEN
python -m uvicorn app.main:app --reload --port 8000
```

Open http://localhost:8000. Staff desk: http://localhost:8000/admin (token from `.env`, default `batu-demo-admin`).

## Static preview (GitHub Pages)

Every push to `main` runs `.github/workflows/pages.yml`, which renders all public pages in all three languages to plain HTML and publishes them to GitHub Pages. English is at the site root, Afaan Oromoo under `om/`, Amharic under `am/`.

```bash
python tools/build_static.py --base /batu/ --out build   # same build locally
```

The static copy is a preview: the assistant, forms, payments and tracking need the server, so on the static site they show a short note instead. One-time setup: in the GitHub repository, **Settings → Pages → Source: GitHub Actions**.

## How it is built

| Part | Where | Notes |
|---|---|---|
| Content | `data/*.json` | English source text. Items marked `sample` are placeholders until the city confirms them. |
| Translations | `data/i18n/om.json`, `am.json` | `{english: translation}`. Run `python tools/translate.py` after changing content; edit the files to correct a translation. |
| Pages | `templates/`, `static/css/site.css` | Server-rendered, light on slow networks. "Hora Dambal" design system. Low-data mode hides photos and web fonts. Motion lives in `motion.css` and `cinema.css`. |
| Storage | `var/batu.db` (SQLite) | Requests, payments, news and notices, assistant log, subscriptions. Created on first run. |
| Payments | `app/payments.py` | `DemoProvider` simulates checkout. Put your Telebirr integration in `TelebirrProvider` and set `PAYMENT_PROVIDER=telebirr`. |
| Assistant | `app/rag/` | See below. |
| Photos | `static/img`, `data/media.json` | Wikimedia Commons photos with credits and licences (see /about#credits). `tools/fetch_images.py` downloads them. |

## Mobile-first and motion

- Base styles are for phones; `@media (min-width:981px)` adds the desktop layout. Phones get a bottom tab bar (Home, Services, Ask, Pay, Track), a sticky main action on service pages, swipeable task chips and 44 px+ tap targets.
- Page-to-page navigation uses cross-document View Transitions (`static/css/motion.css`); story photos carry over into the place page.
- Report, booking and apply forms are stepped flows with a progress bar, per-step validation, a review step and slide animations (`form[data-stepper]` in `static/js/site.js`). Without JavaScript they are ordinary one-page forms.
- State changes animate: button loading, checkout "waiting for confirmation → confirmed", a drawn success tick, staggered status timeline, chat typing dots, and the assistant as a bottom sheet on phones.
- Entrances (`static/css/cinema.css`, `static/js/cinema.js`). On the home page a gold line is drawn across the screen and opens into the lake photograph while the title rises word by word, coordinates settle from noise, the scale bar draws and the search types its own example. Inner pages build their header the same way. Further down, story photos open like an aperture, section rules draw and their sheet labels type in, numbers count up, and cards rise in reading order. The first page of a visit plays at full length; later pages play faster.
- How it stays clean: hidden starting states are set in `<head>` before first paint, so nothing appears and then vanishes. The entrance starts only once fonts and the hero photo are ready (capped at 1.3 s). Only transforms, opacity and clip paths animate, so layout shift measures 0. If `cinema.js` has not started within 3.5 s, the page is simply shown.
- Fonts are self-hosted (`static/fonts`, downloaded by `tools/fetch_fonts.py`), and the three seen on first paint are preloaded.
- All motion is switched off for visitors who ask for reduced motion, in print, in low-data mode for photos, and without JavaScript.

## Translation status

Afaan Oromoo (1,122 of 1,144 strings) and Amharic (1,130 of 1,136) are machine translated with Google Translate. To translate new or missed strings:

```bash
python tools/translate.py                    # Google's free endpoint; add --wait to sit out rate limits
python tools/translate.py --engine gemini    # uses GEMINI_API_KEY instead
```

Set `GOOGLE_TRANSLATE_API_KEY` to use the official Cloud Translation API. The site shows English for any string not yet translated. `DEFAULT_LANG` picks the starting language.

## Ask Batu (lightweight RAG)

1. `corpus.py` turns services, offices, kebeles, places, events, facts, projects, news, notices, tenders and vacancies into about 100 small documents, each with a link and a "sample" flag.
2. `index.py` builds a BM25 keyword index over English plus the Oromo and Amharic translations. With `GEMINI_API_KEY` it also embeds every document in all three languages (`gemini-embedding-2`, cached in `var/vectors.npz`), so an Oromo or Amharic question finds the record directly, and merges both rankings.
3. `agent.py` answers:
   - emergency words (any of the three languages) → emergency numbers immediately, no model;
   - politics, legal or medical questions → polite redirect;
   - otherwise the top 4 documents go to Gemini, each in English and in the selected language, with a glossary of the site's own terms (Tajaajiloota, Gandoota, Bulchiinsa Magaalaa…). The answer must be in the language selected on the site, whatever language the question is in;
   - `lang.py` checks the answer's language; if it is wrong, one rewrite is requested, and if that fails the record is quoted instead;
   - the last two exchanges go along, so follow-ups ("how long does it take?") work;
   - with no key, on an API error, or after `ASK_DAILY_LIMIT` AI answers in a day → the best matching record is quoted directly.
4. Model choice saves tokens: the newest Flash-Lite answers, a full Flash model steps in only when Lite is rate limited. Pin models with `GEMINI_MODEL` (comma-separated).
5. Questions are logged with phone and ID numbers removed (`/admin#asks`). `/assistant` is the public "how it works" page.

### Assistant API for the static site (Render)

The static copy on GitHub Pages cannot run Python, so it sends questions to this app running on Render's free plan (`render.yaml`):

1. render.com → **New → Blueprint** → pick this repository → enter `GEMINI_API_KEY` when asked.
2. If the service URL is not `https://batu-ask.onrender.com`, set the repository variable `ASK_API_URL` (GitHub → Settings → Secrets and variables → Actions → Variables) and re-run the Pages workflow.
3. `.github/workflows/keep-awake.yml` pings `/api/health` every 10 minutes so the free server does not fall asleep.

`ALLOWED_ORIGINS` lists the sites that may call the API from a browser. The free Gemini tier may use inputs to improve Google's products: do not send personal data in the demo. The model sits behind `rag/llm.py` and can be swapped.

## Push news from another system

```bash
curl -X POST http://localhost:8000/api/admin/news \
  -H "Authorization: Bearer <ADMIN_TOKEN>" -H "Content-Type: application/json" \
  -d '{"kind":"news","title":"...","summary":"...","body":"...","source":"City of Batu","date":"2026-11-05"}'
```

Use `"kind":"notice"` for service notices. The assistant re-indexes automatically. Public feed: `GET /api/news`. API docs: `/api/docs`.

## Before launch

See `../Batu_Portal_Information_Request.docx` for the ten items the Mayor's Office needs to confirm.
