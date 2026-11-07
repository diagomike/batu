# Putting batu.gov.et online (Plesk "Linux Bronze")

The public site is plain files: every page in English, Afaan Oromoo and Amharic, plus a
small set of PHP services for the things residents send in (reports, complaints,
applications, bookings, sign-ups) and for tracking and payment. Staff edit everything in
**Batu Studio** on an office computer and press **Publish**.

```
office computer                                   Plesk host (batu.gov.et)
┌──────────────────────────┐   Publish (FTPS)    ┌─────────────────────────────────┐
│ Batu Studio /admin       │ ─────────────────▶  │ httpdocs/  static pages, photos │
│ edits data/*.json        │                     │ httpdocs/api/*.php  forms, pay, │
│ builds dist/httpdocs     │ ◀── requests ─────  │   tracking, admin API           │
│ (python tools/build.py)  │   (admin API)       │ private/  database, uploads     │
└──────────────────────────┘                     └─────────────────────────────────┘
```

## What the plan gives you, and what the site uses

| Plan | Site |
|---|---|
| 5 GB storage | About 15 MB of files today; photos are the bulk (7.4 MB). |
| 50 GB bandwidth a month | A first visit to the home page loads about 1.2 MB (2–2.5 MB if someone scrolls the whole page). Photos, fonts and scripts are then cached for a week. That is roughly **20,000–40,000 first visits a month**. If traffic grows past that, upgrade the plan or put the site behind a free CDN. |
| 1 database | Optional. The PHP services use SQLite (a single file) by default; switch to MySQL in `config.php` if you prefer. |
| Free SSL | Turn on Let's Encrypt (step 2). |

## One-time setup in Plesk

1. **PHP.** *Websites & Domains → batu.gov.et → PHP Settings*: PHP 8.1 or newer (7.4 works),
   served by **FPM application served by Apache**. Keep *Hosting Settings → Proxy mode* on
   (the default), so the `.htaccess` rules work.
2. **SSL.** *SSL/TLS Certificates → Let's Encrypt*: tick the domain and `www`, then turn on
   *Redirect from HTTP to HTTPS* in *Hosting Settings*.
3. **Private folder.** In *Files*, create `private/` next to `httpdocs/` (not inside it).
   The database file and residents' photos go there, out of reach of the web.
4. **First upload.** Either
   - in the studio: *Publish* without upload, then upload `dist/batu-site-<date>.zip` in
     *Files → httpdocs → Upload*, and *Extract*; or
   - from the studio with FTPS (see "Publishing from the studio" below).
5. **Settings.** In *Files → httpdocs/api*, copy `config.sample.php` to `config.php` and edit:
   - `admin_token`: a long random value (24+ characters). The studio needs the same value.
   - `payments`: leave `'off'` until Telebirr is connected. `'demo'` shows a test checkout
     where no money moves. Use it only for trials, because it marks bills as paid.
   - For MySQL: *Databases → Add Database*, then set `'db' => 'mysql'` and the DSN, user and
     password. Otherwise leave SQLite.

   `config.php` is never part of a build, so publishing never overwrites it.
6. **Check.** Open https://batu.gov.et/ and run the checklist at the end.

## Publishing from the studio

Run the studio on the office computer:

```bash
cd portal
python -m uvicorn app.main:app --port 8000
```

Open http://localhost:8000/admin. The first visit creates the first administrator, who can
then add editors under *Users*. Then add these lines to `portal/.env` (the file stays on that
computer and is not in the code repository):

```
# FTPS upload (Plesk: Websites & Domains > FTP Access; use the domain's FTP user)
FTP_HOST=batu.gov.et
FTP_USER=...
FTP_PASSWORD=...
FTP_DIR=httpdocs

# Read and update residents' requests on the host
REMOTE_API=https://batu.gov.et
REMOTE_API_TOKEN=<the admin_token from api/config.php>

# Until the assistant runs in PHP, "Ask Batu" answers from the Python server, e.g. Render.
# That server must allow https://batu.gov.et in ALLOWED_ORIGINS.
ASK_API_URL=https://batu-ask.onrender.com
```

Restart the studio after changing `.env`. **Publish** then:

1. renders every page in the three languages into `dist/httpdocs` (about a minute),
2. adds the PHP services, `.htaccess`, `sitemap.xml` and `robots.txt`,
3. packs `dist/batu-site-<date>.zip`,
4. with *Upload* ticked, sends only the files that changed since the last upload over FTPS.
   It never deletes files on the host.

The same from a terminal:

```bash
python tools/build.py --zip --upload
```

## What runs where

| Feature | On the host | Notes |
|---|---|---|
| All pages, 3 languages | static files | English at `/`, Afaan Oromoo at `/om/`, Amharic at `/am/` |
| Report a problem, complaint | `api/report.php` | Photos go to `private/uploads` |
| Apply for a service | `api/apply.php` | Fees come from the services list at build time |
| Boat trip and venue booking | `api/book.php` | Then the payment page |
| Track a request | `api/request.php` + `static/js/plesk.js` | The public view shows no names or phone numbers |
| Pay a bill | `api/pay.php` + `plesk.js` | `'payments' => 'off'` explains how to pay at the office |
| Notices sign-up | `api/subscribe.php` | Lists are under *Subscribers* in the studio |
| Staff status updates | `api/admin.php` | Token in `config.php`; the studio uses it when `REMOTE_API` is set |
| Ask Batu (assistant) | Python server for now | A PHP version will replace it |

Without JavaScript, every form still works: it posts to PHP and the visitor lands on the
tracking or payment page.

## Checklist after each publish

- [ ] https://batu.gov.et/, /om/ and /am/ open, and the language switch keeps the same page.
- [ ] *Report a problem*: send a test report. It should open the tracking page with a reference.
- [ ] https://batu.gov.et/api/request/LL-BTU-0001 returns the sample bill as JSON.
- [ ] https://batu.gov.et/api/config.php and /api/lib.php are refused (403).
- [ ] In the studio, *Requests* shows `https://batu.gov.et` as the source and lists the test report.
      Set it to *Resolved* and refresh the tracking page.
- [ ] Delete test requests later from the database, or leave them as *Closed*.

## If something goes wrong

- **"City services are not set up yet"**: `api/config.php` is missing (step 5).
- **Forms show a "404 / Method not allowed"**: `.htaccess` is not applied. Check that Proxy
  mode is on and that the domain runs PHP with Apache.
- **The studio says it cannot reach the host**: check `REMOTE_API`, and that `admin_token` in
  `config.php` matches `REMOTE_API_TOKEN`.
- **PHP errors**: *Websites & Domains → Logs*.
- **Roll back content**: in the studio, *History* holds the last 50 versions of every content
  file. Restore one, then Publish.
