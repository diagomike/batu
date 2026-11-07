# Running batu.gov.et

One Python service (FastAPI) serves everything: the public site in English, Afaan Oromoo
and Amharic, the forms, tracking and payments, the "Ask Batu" assistant, and **Batu Studio**,
the staff side at `/admin`. Everything it stores lives in one database: PostgreSQL in
production, a SQLite file on a laptop.

```
                 ┌──────────────────────────── container (Dockerfile) ───────────────────────────┐
 residents ───▶  │ public pages /, /om/, /am/   forms /report /book /pay /track   /api/ask        │
 staff ───────▶  │ Batu Studio /admin: content, photos, translations, requests, users, AI key    │
                 └───────────────────────────────────────┬───────────────────────────────────────┘
                                                         │ DATABASE_URL
                                     ┌───────────────────▼──────────────────────┐
                                     │ PostgreSQL                               │
                                     │ requests, payments, sign-ups, ask log,   │
                                     │ content + history, photos, staff, keys   │
                                     └──────────────────────────────────────────┘
```

Studio edits go live as soon as they are saved, and they survive redeploys because they are
in the database. The JSON files in `data/` are the starting content (see "Content" below).

## Recommended host: Render

Render already runs this repository as `batu-ask` (the assistant behind the GitHub Pages
preview), so the city site can grow from it. You get the web service plus managed PostgreSQL
with daily backups, free TLS for `batu.gov.et`, and deploys on every push. Railway and Fly.io
work the same way with the Dockerfile; see "Other hosts".

### Steps

1. **Database.** Create a PostgreSQL database in the Render dashboard (*New → PostgreSQL*,
   region Frankfurt, plan **Basic 256 MB**, about $6/month; the free plan is deleted after
   30 days). Alternatively, uncomment the `databases` block and the `DATABASE_URL` lines in
   `render.yaml`, and the next blueprint sync creates and connects it.
2. **Connect it.** In the `batu-ask` service, under *Environment*, set `DATABASE_URL` to the
   database's *Internal Database URL*. The app creates its tables on first start (Alembic
   migrations run automatically) and loads the content from `data/`.
3. **Secrets** (*Environment*). `render.yaml` already generates `SECRET_KEY`,
   `STUDIO_SETUP_TOKEN` and `ADMIN_TOKEN`. Add `GEMINI_API_KEY`, or set the key later in the
   studio. Set `ALLOWED_ORIGINS` to every site that calls the assistant from a browser
   (e.g. `https://diagomike.github.io,https://batu.gov.et`).
4. **First studio account.** Open `https://<service>.onrender.com/admin`, enter the
   `STUDIO_SETUP_TOKEN` shown in Render's *Environment* page, and choose the administrator's
   name and password. Add the other staff under *Users*.
5. **Domain.** In the service's *Settings → Custom Domains*, add `batu.gov.et` and
   `www.batu.gov.et`, then create the DNS records Render shows at your registrar. TLS
   certificates are issued automatically.
6. **Plan.** The free web plan sleeps after 15 minutes without visitors (the first visit then
   takes about a minute). For the city site use **Starter** (about $7/month): always on.

## Environment variables

| Variable | Needed | What it does |
|---|---|---|
| `DATABASE_URL` | production | `postgresql://user:pass@host:5432/db` (Render's `postgres://` form works too). MySQL: `mysql://...` plus `pip install pymysql`. Unset: SQLite file `var/batu.db`. |
| `SECRET_KEY` | production | Signs studio sign-in cookies. Long and random. Unset: one is generated and kept in the database. |
| `STUDIO_SETUP_TOKEN` | first run | Lets you create the first studio account from the internet. Not needed after that. |
| `GEMINI_API_KEY` | optional | AI-written answers. A key saved in the studio (*AI assistant*) takes priority; without any key the assistant quotes the city's records. |
| `ASK_DAILY_LIMIT` | optional | AI answers per day before the assistant switches to quoting (default 300). |
| `ALLOWED_ORIGINS` | optional | Other sites allowed to call `/api/ask` from the browser, comma-separated. |
| `ADMIN_TOKEN` | optional | Bearer token for machines that push news to `POST /api/admin/news`. |
| `DEFAULT_LANG` | optional | Language at `/` (`en`; `om` once the Oromo text is reviewed). |
| `PORT` | set by the host | Port to listen on (default 8000). |

## Content: the database and `data/`

- On every start, files in `data/` that nobody has edited in the studio are loaded into the
  database. Translation fixes committed to git therefore go live on the next deploy.
- Once staff edit a document in the studio, the studio version wins. If its file in git
  changes later, *Studio → Backup* flags it and offers **Load from code**.
- *Backup → Download all content* gives the whole site as the `data/` JSON files. Unzip them
  over `portal/data/` and commit them to put studio edits into git, or load the zip into
  another server.
- Photos uploaded in the studio, and photos residents attach to reports, are stored in the
  database. The photos in `static/img/` ship with the code.
- History keeps the last 50 versions of every document; any of them can be restored.

## Backups

- **Database:** Render Postgres (paid plans) takes daily backups. Before big changes, run
  `pg_dump "$DATABASE_URL" > batu-$(date +%F).sql`.
- **Content only:** *Studio → Backup → Download all content*.

## Other hosts

The `Dockerfile` runs anywhere that runs containers.

- **Railway:** *New project → Deploy from GitHub* (root `portal/`), add the PostgreSQL plugin,
  set `DATABASE_URL=${{Postgres.DATABASE_URL}}` and the secrets above.
- **Fly.io:** `fly launch` in `portal/`, then `fly postgres create`, `fly postgres attach`, and
  `fly secrets set SECRET_KEY=... STUDIO_SETUP_TOKEN=...`.
- **Your own server:** `docker compose up -d` with `docker-compose.yml` (portal + PostgreSQL),
  behind a reverse proxy such as Caddy for TLS.

The container health check calls `/health`, which also checks the database.

## Local development

```bash
cd portal
pip install -r requirements.txt
python -m uvicorn app.main:app --reload --port 8000     # SQLite in var/batu.db
```

Open http://localhost:8000/admin. On this computer the first visit creates the
administrator. To run against PostgreSQL locally, use `docker compose up --build`, or set
`DATABASE_URL`.

**Changing tables:** edit `app/database.py`, then run
`alembic revision --autogenerate -m "what changed"`, review the file in `migrations/versions/`,
and commit it. The app applies it on its next start.

## Scaling notes

- Run **one process** per instance. Rate limits and the studio's background jobs
  (translation runs) live in memory. A second instance would need Redis for those.
- The GitHub Pages copy (`tools/build_static.py`) is a static preview built from `data/` in
  git. It does not show studio edits until they are exported and committed.
