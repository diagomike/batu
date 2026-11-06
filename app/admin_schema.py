"""What the studio can edit, described once. The studio builds every form from this.

A field is F(key, label, type, ...). Types:
  text, textarea, longtext (paragraphs), url, number, int, bool, date, month,
  select (fixed options, or `source` = categories / offices / media / trip kinds),
  lines (a list of short texts, one per line), coords ([lat, lng]),
  image (a photo from the media library), object (fields inside a dict), rows (a list of small dicts).
Collections are lists of records inside a content file; singles are one record (a whole file or part of it).
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class F:
    key: str
    label: str
    type: str = "text"
    help: str = ""
    required: bool = False
    options: list | None = None
    source: str | None = None
    sub: list | None = None
    translate: bool = True  # shown to residents, so it goes through translation


@dataclass
class Collection:
    name: str
    title: str
    file: str
    path: str  # key inside the file that holds the list
    fields: list
    label: str = "title"  # field shown in lists
    cols: list = field(default_factory=list)  # extra columns in the list view
    id_key: str | None = "id"  # None: records are identified by position
    group: str = "Content"
    new_at_top: bool = False
    sort_key: str | None = None  # list view order (e.g. date)
    help: str = ""
    public_url: str | None = None  # e.g. "/services/{id}"


@dataclass
class Single:
    name: str
    title: str
    file: str
    fields: list
    path: str | None = None  # None: the whole file
    group: str = "Content"
    help: str = ""


SAMPLE = F("sample", "Sample (placeholder until confirmed)", "bool", translate=False,
           help="Ticked items show a 'Sample' label on the site.")

ONLINE_KINDS = ["apply", "pay", "book", "report", "visit", "link", "external"]

COLLECTIONS: dict[str, Collection] = {c.name: c for c in [
    Collection("services", "Services", "services.json", "services", group="Services", cols=["category", "office"],
               public_url="/services/{id}", help="Each service page: who can apply, documents, steps, fee and office.", fields=[
        F("id", "Web address name", required=True, translate=False, help="Lowercase words with dashes, e.g. building-permit. Changing it breaks old links."),
        F("category", "Category", "select", required=True, source="categories", translate=False),
        F("title", "Title", required=True),
        F("summary", "Short summary", "textarea", required=True),
        F("who", "Who can apply", "textarea"),
        F("documents", "Documents to bring", "lines", help="One per line."),
        F("steps", "Steps", "lines", help="One step per line, in order."),
        F("fee", "Fee", "object", sub=[
            F("amount", "Amount (birr, 0 = free)", "number", translate=False),
            F("unit", "Unit", "select", options=["birr", "birr per month", "birr per day", "birr per boat"]),
            F("note", "Fee note"),
        ]),
        F("time", "How long it takes"),
        F("office", "Office in charge", "select", source="offices", translate=False),
        F("online", "Online actions", "rows", help="Buttons on the service page.", sub=[
            F("kind", "Kind", "select", options=ONLINE_KINDS, translate=False),
            F("label", "Button text"),
            F("url", "Link (for link / external)", "url", translate=False),
        ]),
        F("keywords", "Search words", "lines", translate=False,
          help="Words people might search for, in any language, one per line."),
    ]),
    Collection("categories", "Service categories", "services.json", "categories", group="Services", fields=[
        F("id", "Web address name", required=True, translate=False, help="Also picks the icon: living, land, business, health, water, visiting."),
        F("title", "Title", required=True),
        F("summary", "Summary", "textarea"),
    ]),
    Collection("offices", "Offices", "offices.json", "offices", label="name", cols=["head"], group="Government", fields=[
        F("id", "Short name", required=True, translate=False),
        F("name", "Office name", required=True),
        F("head", "Head of office", translate=False),
        F("head_status", "About the head (source, to confirm)"),
        F("does", "What the office does", "textarea"),
    ]),
    Collection("kebeles", "Kebeles", "kebeles.json", "kebeles", label="name", cols=["administrator", "waste_day"],
               group="Government", fields=[
        F("id", "Short name", required=True, translate=False),
        F("name", "Kebele name", required=True, translate=False),
        F("name_status", "Where the name comes from"),
        F("area", "Area"),
        F("landmarks", "Landmarks", "lines"),
        F("office", "Office location", "coords", translate=False, help="Latitude, longitude, e.g. 7.9445, 38.7235"),
        F("administrator", "Administrator"),
        F("waste_day", "Waste collection day", "select",
          options=["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "To be confirmed"]),
        SAMPLE,
    ]),
    Collection("projects", "Projects", "projects.json", "projects", cols=["status", "progress"], group="Government", fields=[
        F("id", "Short name", required=True, translate=False),
        F("title", "Title", required=True),
        F("kind", "Kind", "select", options=["Road", "Highway", "Public space", "Investment", "Heritage", "Water", "Building"]),
        F("length", "Size or length"),
        F("status", "Status", "select", options=["Planned", "Under construction", "Under construction (federal project)",
                                                  "Ongoing", "Open to investors", "Reopened", "Completed"]),
        F("progress", "Progress (%)", "int", translate=False),
        F("progress_sample", "Progress is a sample figure", "bool", translate=False),
        F("start", "Start (year-month)", "month", translate=False),
        F("end", "End", help="Year-month, or 'To be confirmed'."),
        F("office", "Office in charge", "select", source="offices", translate=False),
        F("source", "Source of the information", translate=False),
        F("coords", "Location", "coords", translate=False),
    ]),
    Collection("places", "Places", "discover.json", "places", cols=["kind"], group="Discover", public_url="/discover/{id}", fields=[
        F("id", "Web address name", required=True, translate=False),
        F("kind", "Kind", "select", options=["heritage", "nature", "festival", "food"], translate=False),
        F("title", "Title", required=True),
        F("kicker", "Small heading above the title"),
        F("image", "Photo", "image", translate=False),
        F("summary", "Summary", "textarea", required=True),
        F("body", "Story", "longtext", help="Leave an empty line between paragraphs."),
        F("facts", "Quick facts", "lines"),
        F("coords", "Location", "coords", translate=False),
        F("sources", "Sources", "lines", translate=False),
    ]),
    Collection("day_trips", "Day trips", "discover.json", "day_trips", id_key=None, cols=["distance"], group="Discover", fields=[
        F("title", "Place", required=True), F("distance", "Distance"), F("text", "Description", "textarea"),
    ]),
    Collection("stays", "Where to stay", "discover.json", "stays", id_key=None, label="name", cols=["where"], group="Discover", fields=[
        F("name", "Name", required=True, translate=False), F("where", "Where"), F("text", "Description", "textarea"),
        F("sample_contact", "Contact details not confirmed", "bool", translate=False),
    ]),
    Collection("events", "Festivals and events", "discover.json", "events", id_key=None, cols=["date", "where"],
               sort_key="date", group="Discover", fields=[
        F("date", "Date", "date", required=True, translate=False), F("title", "Event", required=True), F("where", "Where"),
    ]),
    Collection("news", "News", "news.json", "news", cols=["date", "category"], sort_key="date", new_at_top=True,
               group="News", public_url="/news/{id}", fields=[
        F("id", "Web address name", translate=False, help="Left empty, it is made from the date and title."),
        F("date", "Date", "date", required=True, translate=False),
        F("category", "Category", "select", options=["City", "Development", "Investment", "Tourism", "Culture",
                                                      "Education", "Environment", "Health", "Water"]),
        F("title", "Headline", required=True),
        F("summary", "Summary", "textarea", required=True),
        F("body", "Full story", "longtext", help="Leave an empty line between paragraphs."),
        F("image", "Photo", "image", translate=False),
        F("source", "Source", translate=False),
        F("url", "Source link", "url", translate=False),
    ]),
    Collection("notices", "Notices", "news.json", "notices", cols=["date", "kind"], sort_key="date", new_at_top=True,
               group="News", help="Short notices: water cuts, closures, events. The newest four show on the home page.", fields=[
        F("id", "Short name", translate=False, help="Left empty, it is made from the date and title."),
        F("date", "Date", "date", required=True, translate=False),
        F("kind", "Kind", "select", options=["Service", "Water", "Event", "Road", "Health", "Election"]),
        F("title", "Title", required=True),
        F("text", "Text", "textarea", required=True),
        SAMPLE,
    ]),
    Collection("tenders", "Tenders", "news.json", "tenders", cols=["deadline", "status"], sort_key="published",
               new_at_top=True, group="News", fields=[
        F("id", "Short name", translate=False),
        F("title", "Title", required=True),
        F("office", "Office"),
        F("published", "Published", "date", translate=False),
        F("deadline", "Deadline", "date", translate=False),
        F("status", "Status", "select", options=["Open", "Closed"]),
        F("fee", "Document fee (birr)", "int", translate=False),
        F("source_url", "Link to the notice", "url", translate=False),
        SAMPLE,
    ]),
    Collection("vacancies", "Jobs", "news.json", "vacancies", cols=["deadline", "positions"], sort_key="deadline",
               new_at_top=True, group="News", fields=[
        F("id", "Short name", translate=False),
        F("title", "Job title", required=True),
        F("office", "Office"),
        F("deadline", "Apply by", "date", translate=False),
        F("positions", "Positions", "int", translate=False),
        SAMPLE,
    ]),
]}

SINGLES: dict[str, Single] = {s.name: s for s in [
    Single("city", "City details", "site.json", group="City", fields=[
        F("city", "City", "object", sub=[
            F("name", "Name", translate=False), F("name_om", "Name in Afaan Oromoo", translate=False),
            F("name_am", "Name in Amharic", translate=False), F("former_name", "Former name"),
            F("region", "Region"), F("zone", "Zone"), F("domain", "Web domain", translate=False),
            F("coords", "City centre", "coords", translate=False), F("jetty", "Jetty", "coords", translate=False),
        ]),
        F("hours", "Office hours", "textarea"),
        F("hours_sample", "Office hours not confirmed", "bool", translate=False),
        F("placeholder_note", "Note about placeholder content", "textarea"),
    ]),
    Single("emergency", "Emergency numbers", "site.json", group="City", fields=[
        F("emergency", "National numbers", "rows", sub=[
            F("id", "Short name", translate=False), F("label", "Service"), F("number", "Number", translate=False), F("note", "Note"),
        ]),
        F("local_emergency", "Local numbers", "rows", sub=[
            F("label", "Service"), F("number", "Number", translate=False), F("sample", "Not confirmed", "bool", translate=False),
        ]),
    ]),
    Single("mayor", "Mayor", "site.json", path="mayor", group="City", fields=[
        F("name", "Name", translate=False), F("title", "Title"), F("status", "Source (to confirm)"),
        F("message", "Message on the home page", "longtext"),
        F("message_sample", "Message is a draft", "bool", translate=False),
    ]),
    Single("numbers", "Batu in numbers", "site.json", group="City", fields=[
        F("numbers", "Figures", "rows", sub=[
            F("value", "Figure", translate=False, help="e.g. 440 km²"), F("label", "What it measures"), F("source", "Source", translate=False),
        ]),
    ]),
    Single("facts", "Questions and answers", "site.json", group="City",
           help="Used on the About page and by the assistant.", fields=[
        F("facts", "Questions", "rows", sub=[F("q", "Question"), F("a", "Answer", "textarea")]),
    ]),
    Single("getting_here", "Getting here", "discover.json", group="Discover", fields=[
        F("getting_here", "How to get to Batu", "longtext"),
    ]),
    Single("kebele_note", "Kebele page note", "kebeles.json", group="Government", fields=[F("note", "Note", "textarea")]),
    Single("projects_note", "Projects page note", "projects.json", group="Government", fields=[F("note", "Note", "textarea")]),
]}

GROUPS = ["City", "Services", "Government", "Discover", "News"]


def options_for(f: F, content) -> list[tuple[str, str]]:
    """(value, label) pairs for a select field."""
    if f.options:
        return [(o, o) for o in f.options]
    if f.source == "categories":
        return [(c["id"], c["title"]) for c in content.services_data()["categories"]]
    if f.source == "offices":
        return [(o["id"], o["name"]) for o in content.offices().values()]
    if f.source == "media":
        return [(k, k) for k in sorted(content.media())]
    return []


def translatable_strings(fields: list, record) -> list[str]:
    """Resident-facing texts in a record, as the translation tables key them."""
    out = []
    for f in fields:
        if not f.translate or not isinstance(record, dict):
            continue
        v = record.get(f.key)
        if f.type in ("object",) and isinstance(v, dict):
            out += translatable_strings(f.sub, v)
        elif f.type == "rows" and isinstance(v, list):
            for r in v:
                out += translatable_strings(f.sub, r)
        elif f.type == "lines" and isinstance(v, list):
            out += [x for x in v if isinstance(x, str) and x.strip()]
        elif f.type in ("text", "textarea", "select") and isinstance(v, str) and v.strip():
            out.append(v)
        elif f.type == "longtext" and isinstance(v, str) and v.strip():
            out.append(v)
            out += [p.strip() for p in v.split("\n\n") if p.strip()]
    return out
