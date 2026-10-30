# Locator map generator: project report

A complete technical and process record of the automation built for Cognizant
Foundation India between 22 September and 27 October 2026.

Prepared 30 October 2026. Every figure in this report was measured from the
repository on that date, not estimated. Where a number comes from a one-off
measurement rather than a count, the report says so.

---

## 1. Summary

| | |
|---|---|
| What it does | Generates geographic locator maps for CSR funding proposals |
| Replaces | Maps drawn by AI image tools, which invented place names |
| Built over | 36 days, 22 September to 27 October 2026 |
| Commits | 32 |
| Lines changed | 11,719 added, 944 removed |
| Python written | 7,940 lines across 17 files |
| Of which tests | 1,188 lines, 134 test cases |
| Documentation | 1,589 lines across 5 Markdown files |
| Administrative units covered | 36 states and union territories, 785 districts, 7,146 blocks |
| Boundary datasets | 4 used for geometry, 1 used only to cross-check |
| External services | 3 for place search, 1 for hosting, 1 for code hosting |
| Runtime dependencies | 9, all free and open source |
| Map types produced | 4 |
| Output formats per map | 4, plus a combined PDF and a render log |
| Live deployment | https://map-cognizant.streamlit.app/ |
| Repository | https://github.com/anuragkumar06-ship-it/Automation |
| Working tree on disk | 1.5 GB, of which 167 MB is git history |

---

## 2. The problem

Cognizant Foundation India includes a locator map in CSR funding proposals. The
map has to show where a programme runs: the state inside India, the district
inside the state, and the blocks inside the district, with site points for
hospitals, schools or camps.

Before this tool, those maps were produced with AI image generators. One
surviving example, for Madurai district in Tamil Nadu, contained eight block
names that do not exist in any government register: Kallandiri, Othakadai,
Ayilangudi, Keela Kallandiri, Sakkimangalam, Vellikundram, Kadakinaru and
Mathur. The same map omitted four real Tamil Nadu districts (Tiruppur,
Namakkal, Chengalpattu and Mayiladuthurai), misspelled Dindigul, and drew an
India outline that did not match the official depiction.

A funding proposal carrying invented administrative units is a problem of
accuracy before it is a problem of design. That is why the governing brief puts
accuracy first, image quality second and ease of use third, and why it forbids
any AI in the pipeline. The tool is deterministic: the same input produces a
byte-identical output every time.

---

## 3. What the tool produces

### 3.1 Four kinds of map

**Three-panel locator map.** India with the target state marked, the state with
the target district marked, and the district with its blocks and site points.
The panels are joined by detail callouts in the convention an atlas uses for an
inset. This is the original deliverable from the brief.

**Single-state coverage map.** One state with several districts marked, for
showing where a programme already runs across that state. Added in October 2026
after HR supplied a Karnataka reference image showing 13 districts.

**Multi-state coverage map.** One continuous panel covering several states,
with the districts picked in each one marked. Added 22 October 2026 after
written feedback from Madhura K in Communications, who pointed out that a
programme running in three states could only be mapped one state at a time,
producing three separate maps.

**Whole-state marking.** A state with no district picked is filled to its own
edge. Added 27 October 2026 at Deepak's request, for programmes that run across
a whole state rather than named districts. One state on its own gives India
with that state filled.

Beside a multi-state map the tool also writes one map per chosen district,
showing that district's blocks drawn large and named.

### 3.2 Output files

Each map is written in four formats: SVG and PDF as vectors, and PNG at 300 dpi
and 600 dpi. Every job also produces a single combined PDF holding all of its
maps in reading order, and a `render_log.txt` recording the inputs, the
validation result and the dataset versions used.

Measured output counts for the three example configurations in `maps/`:

| Configuration | Files written | Why |
|---|---|---|
| `madurai.yaml` | 18 | Strip, 3 panels separately, combined PDF, log |
| `karnataka_coverage.yaml` | 5 | One map, 4 formats, log |
| `multi_state_coverage.yaml` | 26 | Overview, 5 district maps, combined PDF, log |

---

## 4. Architecture

### 4.1 Code inventory

Measured 30 October 2026 with `wc -l`.

| File | Lines | Responsibility |
|---|---|---|
| `locator/render.py` | 2,337 | All drawing, layout, projection and labelling |
| `locator/validate.py` | 1,142 | The five pre-render checks |
| `app.py` | 933 | Streamlit dashboard |
| `tests/test_multi_state.py` | 478 | Multi-state, block detail, framing, bundling |
| `locator/geocode.py` | 452 | Place-name search across three services |
| `locator/data.py` | 405 | Dataset registry and boundary loading |
| `locator/cli.py` | 353 | Command line, and the shared entry point |
| `locator/cache.py` | 310 | Builds the per-state cache from raw files |
| `locator/theme.py` | 254 | Dashboard CSS in the CF palette |
| `tests/test_sites.py` | 253 | Sites table cleaning |
| `tests/test_validate.py` | 230 | The Madurai case and the tehsil fallback |
| `tests/test_names.py` | 227 | Name normalisation and aliases |
| `locator/style.py` | 220 | Reads `style/brand.yaml`, projections |
| `locator/names.py` | 177 | Name keys and the alias table |
| `locator/sites.py` | 153 | Cleaning the sites table |
| `locator/__init__.py` | 8 | Package marker |
| `locator/__main__.py` | 8 | `python -m locator` |
| **Total** | **7,940** | |

Application code accounts for 6,752 lines and tests for 1,188, a ratio of about
5.7 lines of code to 1 line of test.

### 4.2 Documentation inventory

| File | Lines | Audience |
|---|---|---|
| `README.md` | 516 | Someone who has never opened a terminal |
| `HANDOFF.md` | 492 | Anyone picking the project up cold |
| `data/SOURCES.md` | 275 | Anyone auditing where a boundary came from |
| `DEPLOY.md` | 160 | Whoever hosts it next |
| `CLAUDE.md` | 146 | The original brief, the source of truth on intent |
| **Total** | **1,589** | |

Configuration adds 140 lines of `style/brand.yaml`, 105 lines across five
example map configurations, and 16 lines of `requirements.txt`.

### 4.3 How a render flows

A request enters through one of three front ends, and all three converge on
`locator.cli.run_from_config()`. That single entry point is deliberate: the
dashboard and the command line cannot drift apart, because they execute the
same function.

```
front end (dashboard / CLI / Colab)
        |
        v
locator.cli.validate_config()      picks single-state or multi-state checks
        |
        v
locator.validate                   five checks, all must pass
        |
        v
locator.data + locator.cache       loads only the states the map needs
        |
        v
locator.render.render_map()        projects, lays out, labels, draws
        |
        v
SVG + PDF + PNG 300 + PNG 600 + combined PDF + render log
```

If validation fails, nothing is drawn. The `--force` flag lets warnings through
but never missing data.

---

## 5. The data layer

### 5.1 Datasets used

Four datasets provide geometry. A fifth is kept only to cross-check block
counts and is never drawn. Every one is recorded in `data/SOURCES.md` with its
URL, download date, licence and attribution text.

| Dataset | Provides | Rows | Licence |
|---|---|---|---|
| `SOI_States` | State and UT boundaries, Survey of India depiction | 40 | CC0 1.0 |
| `LGD_Districts` | District boundaries | 785 | CC0 1.0 |
| `LGD_Blocks` | Community development block boundaries | 7,146 | CC0 1.0 |
| `LGD_Subdistricts` | Tehsil boundaries, fallback only | fetched on demand | CC0 1.0 |
| `PMGSY_Blocks` | Cross-check only, never rendered | not loaded at runtime | CC0 1.0 |

The state layer holds 40 rows: 36 states and union territories, plus 4 rows
marked disputed. The disputed rows exist so the external boundary can be drawn
as India officially depicts it, including Jammu and Kashmir, Ladakh and
Gilgit-Baltistan. They are excluded everywhere a user can pick a state. This
was verified against the official depiction rather than assumed.

Names and codes are validated against the Local Government Directory, the
government's own register. Geometry and names come from separate places on
purpose: checking an LGD-derived layer against itself would confirm nothing.

### 5.2 The cache, and why it exists

Raw downloads total 438 MB across 6 files and are not committed. Running
`python -m locator prepare` turns them into `data/processed`, which is 104 MB
and is committed, so the application deploys without a 1.5 GB preparation step
on the host.

| Cache component | Files | Size |
|---|---|---|
| `blocks/` | 36 | 72 MB |
| `districts/` | 36 | 27 MB |
| `subdistricts/` | 1 | 3.8 MB |
| `states.parquet` | 1 | 874 KB |
| `units_index.parquet` | 1 | 79 KB |
| `index.parquet` | 1 | 19 KB |

The working tree on disk is 1.5 GB in total, which includes the uncommitted raw
downloads and rendered output. The git history itself is 167 MB, most of it the
committed cache.

The two index files carry names and codes with no geometry at all, which is
what lets the dashboard populate its dropdowns without loading a single shape.
That mattered for a measured reason: loading the national district and block
layers at startup used 1,016 MB, which would have exceeded what the hosting
plan allows and killed the application on its first boot. After the split it
uses 110 MB.

Compression is zstd at level 15. State geometry is simplified to 150 m;
district and block geometry passes through unchanged.

The prepare step also repairs self-intersecting outlines using Shapely's
`make_valid()`. It repaired 297 polygons across all layers. The largest area
change measured was 0.000000 per cent, at most 0.2 square metres: the crossing
is untangled and no boundary moves.

### 5.3 Supporting tables

| Table | Rows | Purpose |
|---|---|---|
| `data/aliases.csv` | 51 | Spelling variants, e.g. Thirumangalam to TIRUMANGALAM |
| `data/lgd/reference_counts.csv` | 4 | Independent counts for strict validation |
| `data/sea_labels.csv` | 12 | Names of seas and gulfs for the state panel |

### 5.4 Known gaps in the data

Seventeen districts have no published block boundaries. For fourteen of them,
all in Rajasthan, tehsils were recovered by spatial containment at 100 per cent
coverage. Those are labelled tehsils everywhere they appear, never blocks,
because the brief is explicit that a taluk must never be called a block.

`reference_counts.csv` holds only four rows: districts in Tamil Nadu, districts
in Bihar, blocks in Madurai and blocks in Bhagalpur. Checks 2 and 3 are
therefore strict only in those four places. Elsewhere they report that no
independent reference is recorded rather than silently passing, which is a
deliberate choice: the map says what has been verified and what has not.

---

## 6. Validation

Five checks run before anything is drawn. They live in `locator/validate.py`.

1. State, district and block names exist in the boundary layer, resolved
   through the alias table.
2. The district count in the state layer matches the LGD reference, with any
   missing or extra name reported by name.
3. The block count in the district layer matches the LGD reference, reported
   the same way.
4. Every site point falls inside the stated district, and the block it actually
   falls in is reported. A mismatch with what the user said is a warning, never
   a silent correction.
5. Geometries are valid, with no self-intersections and no gaps beyond
   tolerance.

Three structural decisions sit underneath these checks, and each exists because
a name-based approach failed.

Districts join to states by LGD code, not by name. The state layer writes
"DADRA & NAGAR HAVELI & DAMAN & DIU" where the district layer writes
"DADRA,NAGAR HAVELI,DAMAN & DIU", and a name join silently loses that union
territory. All 785 districts match a state by code.

A multi-state map marks districts by LGD code for the same class of reason. A
district name is only unique within its own state: Bilaspur is in both Himachal
Pradesh and Chhattisgarh, and Hyderabad is a district of Telangana but not of
Karnataka. A name-based mask would mark the wrong district while all five
checks still passed. There is a test for this.

Blocks to mark are keyed by district in the configuration, because a block name
is only unique inside its own district.

### 6.1 The lesson that shaped the project

The coordinate for Government Rajaji Hospital in `maps/madurai.yaml` was
originally typed from memory. It sat 1,482 metres from the real hospital. All
five validation checks passed, because the point was still inside Madurai
district and still inside a plausible block. Nothing caught it.

That is the clearest argument for the no-AI rule in the brief. A coordinate
that validates is not a coordinate that is correct. Site coordinates now come
from a Google Maps right-click or from a geocoding service that returns a real
record, never from recall.

---

## 7. Rendering

### 7.1 Projections

The India panel uses Lambert Conformal Conic fitted to India. State and district
panels use the local UTM zone chosen by `estimate_utm_crs()`. Raw latitude and
longitude is never plotted.

A multi-state panel uses the conic rather than UTM. Three states can span a
third of the country, and a single UTM zone visibly stretches whatever falls
near its edges.

### 7.2 Framing

States scattered down the country produce a tall, narrow bounding box. Framed on
that alone, the map printed as a ribbon down a third of the sheet with the
surrounding land cut to a rectangle. `_widen_extent()` opens the frame sideways
to the page's own proportions and never past the country's bounds. Once the
frame has opened past 0.8 of the country's width, it shows the country whole
rather than slicing the outline across the north, which matters for anything
published with an India map on it.

### 7.3 Labelling

The three-panel and single-state maps use adjustText. Its default one-second
time limit makes output depend on how busy the machine is, so `iter_lim` is
pinned at 260 iterations to keep renders reproducible.

The multi-state map uses a purpose-built placer, `_label_callout_map`. Each
label is tried on rings around the thing it names, nearest first, and may not
touch a chosen state's outline, a covered area, a dot, a site marker, the scale
bar, the north arrow or another label. Crossing another border or the coast is
allowed but carries a cost, so a clear position wins when one exists. It is
deterministic by construction. Started on the shape, as adjustText does, labels
sat across coastlines and state outlines.

A covered district too small to see at national scale, such as Kolkata, also
gets a dot so it cannot vanish.

### 7.4 Scale thresholds

Three thresholds decide what is drawn at what size, all measured in points on
the printed page.

| Constant | Value | Effect |
|---|---|---|
| `SUBLAYER_MIN_PT` | 6.0 | Block boundaries appear on the overview only above this |
| `SMALL_MARK_PT` | 6.0 | Below this a covered district also gets a dot |
| `RIM_MIN_PT` | 3.0 | Outline parts smaller than this are skipped |

The block threshold exists because of a measurement. The median block across a
sample of ten districts is 15.9 km across. That is 1.3 mm on a multi-state
sheet, 5.9 mm on a single-state panel, and 40 mm on a map of its own district.
A block name needs roughly 12 to 15 mm. Blocks are therefore only legible at
district scale, which is why each district gets its own map, and why block
boundaries are drawn unnamed on the overview and dropped entirely at national
scale, where the white lines buried the district's own fill.

### 7.5 Brand

Every colour, font, marker and size lives in `style/brand.yaml`: 18 colours, 14
site types each with a distinct marker, 9 type sizes and 8 line widths.

Text is midnight blue `#000048`. Non-target units are light grey `#D0D0CE` with
white hairline borders. The standard highlight is teal `#05819B`. Water is
white. Sentence case everywhere, left-aligned titles, no gradients, no shadows
and no dashed lines. Colours come from the CF brand visual identity guidelines
of January 2025 and the communication guidelines of September 2024.

The multi-state map uses three strengths of the one teal, after HR reported
that grey states next to grey country looked awkward. A chosen state is washed
in `#D2E8ED`, its covered districts sit on top in `#034F62`, and covered blocks
stay `#06C7CC`. The deep shade was added because the standard highlight sat too
close in tone to the pale wash and the districts disappeared into their own
state. This applies only to the multi-state map; the other map types have no
pale wash to compete with and keep the standard highlight.

---

## 8. The three front ends

**Streamlit dashboard (`app.py`, 933 lines).** How everyone actually uses it.
States and districts come from dropdowns populated out of the geometry-free
index, so nothing has to be typed or spelled. Sites can be entered as
coordinates or found by name. Each session gets its own temporary output
directory, so two people rendering at once do not overwrite each other.

**Command line (`python -m locator`).** Four subcommands: `check` runs
validation and draws nothing, `render` validates then draws, `fetch` downloads
the boundary data ahead of time, and `prepare` builds the cache from raw files.

**Colab notebook.** A form interface for users who would rather not install
anything. Built and working, though less polished than the dashboard.

---

## 9. External services and platforms

Eight external services are involved across development, hosting and runtime.

| Service | Used for | Cost | Required |
|---|---|---|---|
| GitHub | Code hosting, data releases | Free | Yes |
| Streamlit Community Cloud | Hosting the live dashboard | Free | For the live site |
| Google Colab | Notebook front end | Free | No |
| Nominatim (OpenStreetMap) | Place-name search, first choice | Free | No |
| Photon (Komoot) | Place-name search, fallback | Free | No |
| Google Places API | Place-name search, last resort | Paid | No, off by default |
| Google Maps | Where users copy site coordinates | Free | No |
| Local Government Directory | Name and count reference | Free | Reference only |

Place search runs as a cascade in `search_best()`: Nominatim, then Photon, then
Google Places, stopping at the first usable answer. Nominatim's usage policy
requires an identifying User-Agent and a request interval, so the client sends
one and waits 1.1 seconds between calls. Google Places stays off unless a
`GOOGLE_MAPS_API_KEY` is supplied, which keeps the free-and-open-source
constraint intact.

Every result is filtered by the caller's predicate, because Photon's bounding
box is a hint rather than a filter. Nominatim is called with a viewbox bounded
to the chosen district, which is what stopped a search for a place in Jammu
returning a result in Srinagar.

---

## 10. Dependencies

Nine runtime dependencies, all free and open source. No paid API key is needed
to run the tool.

| Package | Declared | Installed | Used for |
|---|---|---|---|
| geopandas | >=1.0,<2.0 | 1.1.4 | Vector data handling |
| shapely | >=2.0,<3.0 | 2.1.2 | Geometry operations |
| pyproj | >=3.6 | 3.8.0 | Projections |
| pyarrow | >=15.0 | 25.0.1 | Reads GeoParquet, including zstd |
| matplotlib | >=3.8 | 3.11.2 | Rendering and PDF output |
| adjustText | >=1.1 | 1.4.0 | Label placement |
| PyYAML | >=6.0 | 6.x | Config and brand files |
| pandas | >=2.0 | 3.0.6 | Tabular data |
| streamlit | >=1.40 | 1.64.0 | The dashboard |

Running on Python 3.12.10. Place-name search uses `urllib` from the standard
library, so it adds no dependency. The combined PDF uses matplotlib's own
`PdfPages`, chosen over a PDF library for the same reason.

---

## 11. Testing

134 test cases, written as 118 test functions across 4 files. The difference is
parametrised tests, where one function runs against several inputs.

| File | Cases | Functions | Covers |
|---|---|---|---|
| `test_multi_state.py` | 42 | 42 | Multi-state validation, block detail, framing, bundling |
| `test_sites.py` | 36 | 25 | Sites table cleaning and coordinate handling |
| `test_validate.py` | 29 | 24 | The Madurai acceptance case, tehsil fallback |
| `test_names.py` | 27 | 27 | Name keys, aliases, normalisation |

The suite runs in about 28 seconds against the real boundary data, not against
fixtures. If the boundary data is absent the module skips rather than failing,
so a fresh clone can still run the rest.

Several tests encode specific past failures. One asserts that each of the eight
block names invented by the old AI map is rejected. Another checks that
Bilaspur in Himachal Pradesh and Bilaspur in Chhattisgarh resolve to two
different LGD codes. A third checks that a block of one district cannot be
marked on another.

---

## 12. Measured performance

Render times measured on the development machine, 30 October 2026, as a full
cold `python -m locator render` including interpreter startup and data loading.

| Map | Time | Files |
|---|---|---|
| Three-panel locator (Madurai) | 19.5 s | 18 |
| Single-state coverage (Karnataka) | 6.1 s | 5 |
| Multi-state coverage, 5 districts | 17.4 s | 26 |

Two optimisations account for most of the difference from where it started.
Computing exact distances against full-resolution coastlines took 63 seconds of
an 80 second render; simplifying neighbours to 500 m and using a spatial index
brought the whole render to 14 seconds. Splitting the national files into a
per-state cache cut startup memory from 1,016 MB to 110 MB.

---

## 13. Development history

32 commits between 22 September and 27 October 2026, across six working days.

| Date | Commits | Theme |
|---|---|---|
| 22 Sep 2026 | 8 | Scaffold, first working map, reproducibility, brand |
| 25 Sep 2026 | 5 | GRH coordinate fix, per-state cache, place search, deployment |
| 28 Sep 2026 | 5 | Sites table fixes, 14 site types, geometry repair, memory |
| 29 Sep 2026 | 5 | Coverage maps, panel-per-file output, titles, deploy hardening |
| 22 Oct 2026 | 6 | Handoff doc, Colab fix, multi-state maps, block maps, combined PDF, colour |
| 27 Oct 2026 | 3 | National-scale labelling, whole-state marking, documentation |

All 32 commits carry a `Co-Authored-By` trailer recording the model used: 29
for Claude Opus 5 and 3 for Claude Opus 5.5. The work was done in a
conversational development loop, with the brief in `CLAUDE.md` acting as the
standing specification and rendered output reviewed after each visual change.

### 13.1 How requirements arrived

The project did not start with a complete specification. Four features came
from named stakeholders after the tool was already in use:

| Request | From | Date | Result |
|---|---|---|---|
| Coverage map for a whole state | HR, with a Karnataka reference image | Oct 2026 | Single-state coverage map |
| Maps spanning several states | Madhura K, Communications | 22 Oct 2026 | Multi-state coverage map |
| Blocks visible on those maps | Madhura K, Communications | 22 Oct 2026 | Per-district block maps |
| Mark whole states with no district | Deepak | 27 Oct 2026 | Whole-state marking |

Two further changes came from direct observation of the tool in use: the states
on a multi-state map reading as grey and looking awkward, and downloads
clearing the rendered maps off the page.

---

## 14. Defects found and fixed

Fifteen distinct defects were diagnosed and fixed during development. Each is
recorded with its cause, because the cause is what stops it returning.

| Symptom | Cause | Fix |
|---|---|---|
| Same input gave different output | adjustText's 1 s time limit | Pinned `iter_lim` |
| 80 second renders | Exact distance on full-resolution coastlines | Simplify plus spatial index |
| Dadra & Nagar Haveli missing | Districts joined to states by name | Join by LGD code |
| Sites showing "Nan" | `float('nan')` is truthy, so `str(v or "")` gave `"nan"` | Explicit NaN handling |
| Sites rejected as outside Kota | Seeded default plus a data editor state loop | Schema reset and delta tracking |
| Jammu search returning Srinagar | Unbounded Nominatim query | `viewbox` plus `bounded=1` |
| Geometry warning on Kaduthuruthy | 185 invalid block polygons | `make_valid()` at cache build |
| Application killed on deploy | 1,016 MB at startup | Geometry-free index files |
| "Easting [metre]" printed on panels | `set_axis_off()` dropped when frames were added | Explicit `set_xlabel("")` |
| Coverage map 10 inches tall | Fitted one dimension only | Fit both, then trim the page |
| KeyError on the live site | New `app.py` against a cached old `cli.py` | Defensive reads plus reboot |
| Maps vanished after one download | Results drawn inside `if go:` | Result kept in `session_state` |
| Covered districts a white scribble | Block boundaries drawn at any size | `SUBLAYER_MIN_PT` threshold |
| Dark specks over Tamil Nadu and the Bengal coast | State rim drawn round enclaves and islands | Outer-edge-only outlines |
| Labels across coastlines and outlines | adjustText starts each label on its shape | Purpose-built callout placer |

Three cells of the Colab notebook also contained a raw newline where an escaped
one was intended, which split Python string literals across lines and made
those cells fail to compile. Found by compiling every cell rather than by
running the notebook.

---

## 15. Constraints the project worked under

These come from the brief and were treated as non-negotiable.

No AI anywhere in the pipeline: no language model call, no image generation,
fully deterministic output. The tool was built conversationally with an AI
assistant, but nothing in the shipped pipeline calls one.

Never draw, approximate or invent a boundary. Every polygon comes from a sourced
dataset. If data is missing the tool stops and says so rather than substituting
a guess.

Never label a taluk as a block. Where block data does not exist, the fallback is
clearly labelled as tehsils on the face of the map.

Free and open source only, with no paid API key required to run.

No account creation or password entry. Where a portal requires registration, the
instructions tell the user to download the file manually and say where to put
it.

Users are non-technical and work in Google Workspace, so the README is written
for someone who has never opened a terminal.

---

## 16. Open items

1. Reboot the Streamlit app. The live site needs a manual restart from
   share.streamlit.io before the most recent work is visible, because an
   auto-redeploy reruns the script without reliably reloading modules already
   imported.
2. `reference_counts.csv` covers four entries. Filling in more states would make
   checks 2 and 3 strict in more places.
3. CF approval for logo use, now that the repository is public. The
   communication guidelines require approval per use.
4. From the brief, not started: a CF programme layer read from a CSV exported
   from a Google Sheet, to plot existing CF work and list programmes in the same
   or adjacent districts.
5. Streamlit Community Cloud sleeps an idle application. `DEPLOY.md` records the
   route to an internal Cognizant server if the tool is adopted permanently.

---

## 17. Deliverables produced

| Deliverable | Form | Audience |
|---|---|---|
| The tool itself | Python package plus Streamlit app | CF proposal writers |
| `README.md` | 516 lines | Non-technical users |
| `HANDOFF.md` | 492 lines | Next developer |
| `data/SOURCES.md` | 275 lines | Anyone auditing a boundary |
| `DEPLOY.md` | 160 lines | Whoever hosts it |
| `Locator map generator - how it works.docx` | 1,868 words, 2 figures, 5 tables | HR, for company-wide presentation |
| Example configurations | 5 YAML files | Users, as starting points |
| This report | | Internship submission |

---

## 18. Acceptance against the brief

**Case 1, Madurai.** Tamil Nadu, Madurai district, Madurai East block, with
Government Rajaji Hospital as a site. Madurai shows 13 blocks, matching the LGD
list. None of the eight invented block names appear. All four previously missing
Tamil Nadu districts appear, and Dindigul is spelled correctly. The hospital
falls in Madurai West, not Madurai East as originally stated, and the tool
reports that rather than forcing the user's answer.

**Case 2, Bhagalpur, Bihar.** Configuration at `maps/bhagalpur.yaml`. Bhagalpur
shows 16 blocks, matching the district administration's published list.

Both cases pass all five checks with no errors and no warnings.
