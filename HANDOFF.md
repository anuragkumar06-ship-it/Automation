# Handoff: locator map generator

Written 2026-10-22. This is the full context for anyone — person or assistant —
picking the project up cold. Read `CLAUDE.md` first for the original brief; this
file records what was actually built, why it was built that way, and what is
still open.

---

## 1. What this is

A Python tool that makes geographic locator maps for Cognizant Foundation India
CSR funding proposals. It produces two kinds of map:

**Three-panel locator map** — India with the target state highlighted, the state
with the target district highlighted, the district with the target block(s)
highlighted and site points marked. Panels joined by connector lines.

**Coverage map** — a single panel of one state with several districts
highlighted, for showing where a programme is already active. Added in October
2026 at HR's request, with a Karnataka reference image showing 13 districts.

**Multi-state coverage map** — one continuous panel covering several states,
with the districts picked in each one marked. Added 2026-10-22 after feedback
from Madhura K (Communications): a programme running in three states could only
be mapped one state at a time. Only the marked districts are labelled, which is
the deliberate trade-off — a full set of district labels across several states
does not stay legible at A4.

**Per-district block maps** — written beside a multi-state coverage map, one
per chosen district. These exist because of a measurement, not a preference: a
block is 15.9 km across at the median, which is **1.3 mm** on a multi-state
sheet, **5.9 mm** even on a single-state panel, and **40 mm** on a map of its
own district. Blocks are only legible at district scale, so that is where their
names go. The overview draws their boundaries unnamed and the legend says where
the names are.

It replaces a manual process where these maps were made with AI image tools.
Those maps invented blocks that do not exist, missed real districts, and had an
unreliable India outline. **Accuracy is the first priority, image quality
second, ease of use third.**

Two front ends, one codebase:

- `app.py` — a Streamlit dashboard, which is how everyone actually uses it
- `python -m locator render maps/<config>.yaml` — the CLI, same code path
- `notebooks/locator_map_colab.ipynb` — a Colab form (built, not polished)

---

## 2. Where things stand right now

| Thing | State |
|---|---|
| Local app | Works. Current on all features. |
| Tests | 123 passing. Run with `.venv/Scripts/python.exe -m pytest tests/ -q` |
| GitHub | In sync. `anuragkumar06-ship-it/Automation`, branch `main`, HEAD `5ca32e1`, tree clean. |
| Live site | https://map-cognizant.streamlit.app/ — **needs a manual reboot** (see below) |
| Data coverage | All 36 states/UTs, 785 districts, 7,146 blocks |

### The one open action: reboot the Streamlit app

The live app crashed when rendering a coverage map:

```
KeyError
File "/mount/src/automation/app.py", line 561
File "/mount/src/automation/locator/cli.py", line 84
```

**Cause.** The hosted app was running two versions at once. Streamlit had
reloaded the new `app.py`, which sends `districts` (plural), while still holding
the older `locator/cli.py` in memory, which read `config["district"]`. Confirmed
by checking what line 84 was at each commit — it belongs to `75cbfe2`, three
commits behind. Auto-redeploy reruns the script but does not always reload an
already-imported module.

**Fix.** Two parts. `5ca32e1` hardened both sides so this mismatch can no longer
raise a bare KeyError: `run_from_config` reads every key defensively and
`app.py` sends both spellings. But the process still holds stale modules, so it
also needs a restart:

> share.streamlit.io → the app → **⋮** → **Reboot app**

Only the account owner can do this. After rebooting, render one coverage map and
one three-panel map on the live site to confirm.

---

## 3. Repository and environment

```
C:\Users\Anurag kumar\Downloads\Internship\Automation
```

Windows 11, PowerShell. Virtualenv at `.venv` — **use `.venv/Scripts/python.exe`,
not the system Python**, which has no pytest and no geopandas.

```
Automation/
  CLAUDE.md          # the original brief - the source of truth on intent
  HANDOFF.md         # this file
  README.md          # written for someone who has never used a terminal
  DEPLOY.md          # Streamlit Cloud, and the route to an internal server
  requirements.txt
  app.py             # the Streamlit dashboard (681 lines)
  locator/
    cache.py         # builds data/processed from data/raw
    cli.py           # run_from_config() - the single entry point
    data.py          # loads boundaries from the per-state cache
    geocode.py       # place-name search (Nominatim, Photon, Google)
    names.py         # name normalisation and the alias table
    render.py        # all drawing (1,264 lines)
    sites.py         # cleaning the sites table
    style.py         # reads style/brand.yaml
    theme.py         # the dashboard's CF-branded CSS
    validate.py      # the five checks
  data/
    raw/             # 438 MB, gitignored - see SOURCES.md to re-download
    processed/       # 104 MB, COMMITTED - the per-state cache the app reads
    SOURCES.md       # every dataset, URL, date, licence, attribution
    aliases.csv      # spelling variants
    lgd/             # reference counts for validation
    sea_labels.csv
  style/brand.yaml   # every colour, font, marker and size in one file
  maps/              # madurai, bhagalpur, balotra, karnataka_coverage,
                     #   multi_state_coverage
  assets/            # the CF logo
  tests/             # 123 tests
  output/            # gitignored
  .streamlit/config.toml   # CF palette for the dashboard chrome
```

---

## 4. The data

Everything is in `data/SOURCES.md` with URLs, download dates and licences. In
summary:

| Layer | Source | Count |
|---|---|---|
| States / UTs | Survey of India official depiction | 40 rows, 36 states/UTs |
| Districts | LGD-reconciled open dataset | 785 |
| Blocks (CD blocks) | LGD-reconciled open dataset | 7,146 |
| Sub-districts / tehsils | fallback layer | 8 states need it |

The official depiction matters: the external boundary must show J&K, Ladakh and
Gilgit-Baltistan as India depicts them. This was verified, not assumed.

### The cache

`data/raw` is 438 MB and is **not** committed. `python -m locator prepare` turns
it into `data/processed`, which **is** committed (104 MB) — that is what lets the
app deploy without a 1.5 GB preparation step.

The cache splits the national files per state and writes `index.parquet` and
`units_index.parquet` with no geometry, so the dropdowns can be populated
without loading any shapes. This matters: loading all of India at startup used
1,016 MB and would have been killed on a hosted plan. It is now 110 MB.

Compression is zstd level 15. States are simplified to 150 m; district and block
geometry passes through unchanged.

`prepare` also repairs self-intersecting outlines with `make_valid()` — 297
polygons across all layers. The largest area change measured is 0.000000 per
cent, at most 0.2 m². The crossing is untangled; no boundary moves. This is what
fixed the Kaduthuruthy geometry warning.

### Known data gaps

- **17 districts have no blocks.** For 14 of them (Rajasthan) tehsils were
  recovered by spatial containment at 100 % coverage. They are **labelled
  tehsils, never blocks** — the brief is explicit that a taluk must never be
  called a block.
- `data/lgd/reference_counts.csv` is only populated for Tamil Nadu, Bihar,
  Bhagalpur and Madurai. Checks 2 and 3 below are therefore strict only for
  those; elsewhere they pass quietly.

---

## 5. Validation — the five checks

In `locator/validate.py`. Every render runs them first. An error stops the
render; `--force` lets warnings through but never missing data.

1. State, district and block names exist, resolved through `data/aliases.csv`
   (Thirumangalam / Tirumangalam, Mysore / Mysuru, Bangalore Urban / Bengaluru
   Urban, and so on).
2. District count in the state layer matches LGD; any missing or extra name is
   reported by name.
3. Block count in the district layer matches LGD, same reporting.
4. Every site point falls inside the stated district, and the block it actually
   falls in is reported. A mismatch with what the user said is a warning, never
   a silent correction.
5. Geometries are valid — no self-intersections, no gaps beyond tolerance.

`validate_request` takes both `district=` (one) and `districts=` (several).
`ResolvedTarget.multi_district` drives the coverage-map path, which refuses
blocks (one district at a time) and checks sites against the union of districts.

`validate_coverage_request` is the multi-state path, taking one `{state,
districts}` entry per state. Each state is resolved against its own district
layer and counted against its own LGD reference, so nothing carries from one to
the next. `locator.cli.validate_config` picks between the two and is what both
the CLI and the dashboard call, so the check and the render can never disagree.

**A multi-state map marks districts by LGD code, not by name.** A district name
is only unique inside its own state — Bilaspur is in both Himachal Pradesh and
Chhattisgarh, Hyderabad is a district of Telangana and not of Karnataka — so a
name-based mask would mark the wrong district with every check still passing.
There is a test for this.

`DistrictDetail` carries one chosen district's blocks, built by
`_detail_for_district`. Blocks to mark are keyed by district in the config
(`blocks: {Mysuru: [...]}`) for the same reason: a block name is only unique
inside its own district. `_units_for_district` is shared with the single-state
path, so the tehsil fallback behaves identically on both.

**Districts join to states by LGD code, not by name.** The two layers spell
Dadra & Nagar Haveli and Daman & Diu differently, and joining by name loses it.

---

## 6. Rendering

`locator/render.py`. Key entry points:

- `render_map()` — dispatches to the three-panel or coverage path
- `_render_coverage()` — single panel, one state, several districts
- `_write_panels_separately()` — each panel redrawn as its own file with its own
  title, legend and source line. HR asked for this; they need the panels
  individually, not only as a strip.
- `_write_figure()` — writes SVG, PDF, PNG at 300 dpi and PNG at 600 dpi
- `_write_bundle()` — every map of one job in a single PDF (`<name>_all_maps.pdf`),
  main map first, then one page per district. Uses matplotlib's own `PdfPages`,
  so it adds no dependency. The figure writers therefore **return their figures
  instead of closing them**; the caller closes them after the bundle is written.
  Pages keep their own sizes, because the maps are different shapes.
- `_frame_panel()` — **must call `ax.set_xlabel("")` and `ax.set_ylabel("")`**.
  Matplotlib otherwise prints "Easting [metre]" / "Northing [metre]" on every
  panel. This was a regression once already; do not drop it again.

**Projections.** India panel in Lambert Conformal Conic. State and district
panels in the local UTM zone via `estimate_utm_crs()`. Raw lat/long is never
plotted. A **multi-state** coverage panel uses the conic, not UTM: three states
can span a third of the country, and one UTM zone stretches whatever falls near
its edges.

**Framing a multi-state map.** States scattered down the country give a tall,
narrow bounding box, which printed as a ribbon down a third of the sheet with
the land cut to a rectangle around it. `_widen_extent()` opens the frame out
sideways to the page's proportions, never past the country's own bounds; and
once it has opened out past `COUNTRY_SNAP` (0.8) of the country's width it
shows the country whole rather than slicing the outline across the north.

**Titles name the state and the kind of map**, at HR's request:
`"India: states and union territories"`, `"Tamil Nadu district map"`,
`"Madurai district: blocks"`.

**Determinism.** adjustText defaults to a one-second time limit, which makes
output depend on how busy the machine is. `iter_lim` is pinned
(`LABEL_ITERATIONS = 260`) so the same input gives the same file every time.
Do not remove that.

**Speed.** Exact `.distance()` against full-resolution coastlines took 63 s of an
80 s render. Simplifying neighbours (`NEIGHBOUR_SIMPLIFY_M = 500`) and using a
spatial index brought the whole render to 14 s.

**Brand.** Everything lives in `style/brand.yaml` — midnight blue `#000048` text,
light grey `#D0D0CE` non-target fill, teal `#05819B` highlight, white water,
14 site types each with a visually distinct marker, logo top-right. Sentence
case everywhere, left-aligned titles, no gradients, no shadows, no dashed lines.
Colours come from the CF brand visual identity guidelines (January 2025) and
communication guidelines (September 2024).

**Logo.** `logo.show: true` in brand.yaml. The communication guidelines require
CF approval for each use, and the repository is public, so this is worth
confirming with CF once rather than per map.

---

## 7. The dashboard

`app.py`, Streamlit. Branded with `locator/theme.py`, whose CSS selectors are
scoped `html body` to out-specify Streamlit's own, with icon fonts explicitly
preserved.

Notes that matter:

- `SITES_SCHEMA = 2`. Bumping this resets a returning browser's stale
  `session_state`. Bump it whenever the shape of the sites table changes.
- `_output_root()` gives each session its own temp directory, so two people
  rendering at once do not overwrite each other.
- **The render result lives in `st.session_state["last_result"]`, not in the
  `if go:` branch.** A `st.download_button` click reruns the script, and a
  button reads True only on the run it was clicked — so results drawn inside
  `if go:` vanished as soon as the user downloaded one file, and they could
  not fetch the other formats. Anything the download section needs is stored
  in that dict, not read back off the sidebar widgets.
- District selection is a **multiselect**. One district → three-panel map.
  Several → coverage map.
- `_build_config()` sends both `districts` (list) and `district` (first one), so
  an older reader still finds something.
- Downloads are grouped: the combined map, then each panel separately.

---

## 8. Place-name search

`locator/geocode.py`. A cascade in `search_best()`: Nominatim → Photon → Google
Places (New), stopping at the first usable answer.

- `MIN_INTERVAL_SECONDS = 1.1` and an identifying `USER_AGENT` — Nominatim's
  terms require both.
- Every result is filtered by the caller's `keep` predicate, because Photon's
  bounding box is only a hint, not a filter.
- Nominatim is called with `viewbox` + `bounded=1` aimed at the chosen district.
  This is what fixed "Raghunath Bazar" returning a Srinagar result when the user
  meant Jammu. Note that Raghunath Bazar genuinely is not in OSM — returning
  nothing is the correct answer there, not a bug.
- Google Places is optional and needs a key. It is off unless one is supplied.

---

## 9. Bugs already fixed — do not reintroduce

| Symptom | Cause | Fix |
|---|---|---|
| Same input, different output | adjustText's 1 s time limit | pinned `iter_lim` |
| 80 s renders | exact distance on full-res coastlines | simplify + spatial index |
| DNH&DD missing | joined districts to states by name | join by LGD code |
| Sites showing "Nan" | `float('nan')` is truthy, so `str(v or "")` gave `"nan"` | `locator/sites.py` |
| Sites "not inside Kota district" | seeded Madurai default + data_editor state loop | schema reset + delta tracking |
| Jammu search returning Srinagar | unbounded Nominatim query | `viewbox` + `bounded=1` |
| Kaduthuruthy geometry warning | 185 invalid block polygons | `make_valid()` at cache build |
| App killed on deploy | 1,016 MB at startup | geometry-free index files |
| "Easting [metre]" on panels | `set_axis_off()` dropped when frames were added | explicit `set_xlabel("")` |
| Coverage map 10 in tall | fitted one dimension only | fit both, then trim the page |
| Live KeyError | new `app.py` against cached old `cli.py` | defensive reads + reboot |
| Maps vanished after one download | results drawn inside `if go:`; a download rerun makes the button False | result kept in `session_state` |

### The GRH lesson

The Government Rajaji Hospital coordinate in `maps/madurai.yaml` was originally
typed from memory and sat **1,482 m from the real hospital**. Every one of the
five validation checks passed — it was still inside Madurai district, still
inside a plausible block. Nothing caught it.

This is the central argument for the brief's no-AI rule, and it is worth keeping
in mind: a coordinate that validates is not a coordinate that is right. Sites
come from a Google Maps right-click, or from a geocoding service that returns a
real record, never from a model's recall.

---

## 10. Hard rules, from the brief and from experience

- **No AI anywhere in the pipeline.** No LLM, no image generation. Fully
  deterministic.
- **Never draw, approximate or invent a boundary.** Every polygon comes from a
  sourced dataset. If data is missing, stop and say so.
- **Never label a taluk as a block.**
- **Free and open source only.** No paid API keys required to run.
- **Do not create accounts or enter passwords.** If a portal needs a login, ask
  the user to download the file and say exactly where to put it.
- **The users are not technical** and work in Google Workspace. Write for
  someone who has never opened a terminal.
- **Show rendered output after each visual change** and wait for feedback before
  carrying on.
- Keep commits small, with clear messages.
- If the brief conflicts with official data, trust the official data and say so.

---

## 11. Running it

Start the dashboard:

```bash
.venv/Scripts/python.exe -m streamlit run app.py
```

Render from a config:

```bash
.venv/Scripts/python.exe -m locator render maps/madurai.yaml
```

Check a config without drawing:

```bash
.venv/Scripts/python.exe -m locator check maps/madurai.yaml
```

Rebuild the cache after changing raw data (needs `data/raw`, about 1.5 GB of
working memory, several minutes):

```bash
.venv/Scripts/python.exe -m locator prepare
```

Tests:

```bash
.venv/Scripts/python.exe -m pytest tests/ -q
```

---

## 12. Open items

1. **Reboot the Streamlit app** (section 2). Then verify both map types live.
2. `notebooks/locator_map_colab.ipynb` still has a placeholder repo URL —
   `https://github.com/YOUR-ORG/locator-maps.git` should become
   `https://github.com/anuragkumar06-ship-it/Automation.git`.
3. `data/lgd/reference_counts.csv` covers only Tamil Nadu, Bihar, Bhagalpur and
   Madurai. Filling in more states makes checks 2 and 3 strict elsewhere.
4. CF approval for logo use, now that the repository is public.
5. From the brief, not yet started: **step 8**, a CF programme layer read from a
   CSV exported from a Google Sheet (programme name, partner, lat, lon), to plot
   existing CF work and list programmes in the same or adjacent districts.
6. Streamlit Community Cloud sleeps an idle app. `DEPLOY.md` has the route to an
   internal Cognizant server, which is where this should end up if the tool
   sticks.

---

## 13. Deliverables already produced

- **`Locator map generator - how it works.docx`** — a plain-English technical
  explainer for HR to present company-wide. 1,868 words, 2 figures, 5 tables.
  Author set to "Cognizant Foundation India", no personal name in it.
- The same content as a Claude doc: artifact `25e91b4e-d0e4-44f7-b2a9-ac0e15d4b2e0`.
- `README.md` for non-technical users, `DEPLOY.md` for hosting.

---

## 14. Acceptance cases from the brief

**Case 1 — Madurai.** Tamil Nadu / Madurai / Madurai East, site Government
Rajaji Hospital. Madurai has 13 blocks. The old AI map invented eight blocks
(Kallandiri, Othakadai, Ayilangudi, Keela Kallandiri, Sakkimangalam,
Vellikundram, Kadakinaru, Mathur), missed several Tamil Nadu districts
(Tiruppur, Namakkal, Chengalpattu, Mayiladuthurai) and misspelled Dindigul. None
of those appear now. GRH falls in **Madurai West**, not Madurai East — the tool
reports that rather than forcing the user's answer.

**Case 2 — Bhagalpur, Bihar.** Config at `maps/bhagalpur.yaml`.

Acceptance for each: all checks pass, every label legible at A4 print size, no
overlaps, PNG sharp at 100 % zoom.
