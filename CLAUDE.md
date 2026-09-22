# Locator map generator: project brief

## Goal

Build a Python tool that produces a three-panel geographic locator map for CSR funding proposals at Cognizant Foundation (CF):

1. India with all states, target state highlighted
2. Target state with all districts, target district highlighted
3. Target district with all blocks, target block(s) highlighted and site points marked (hospitals, schools, camps)

Panels are joined by connector arrows. Output must be geographically accurate, print quality, and identical in style every time.

This replaces a manual process where maps were generated with AI image tools. Those maps contained invented blocks, missing districts and an unreliable India outline. Accuracy is the first priority, image quality second, ease of use third.

## Hard constraints

- **No AI anywhere in the pipeline.** No LLM or image-generation API calls in the code. The tool must be fully deterministic: same input, same output.
- **Never draw, approximate or invent a boundary.** Every polygon comes from a sourced dataset. If data is missing, stop and tell the user. Do not substitute a guess.
- **Runs two ways from one codebase:** locally via CLI on Windows/macOS, and in Google Colab via a form notebook. Users work in Google Workspace and are not technical.
- **Free, open-source dependencies only.** Prefer geopandas, shapely, pyproj, matplotlib, adjustText. Avoid anything needing paid API keys.
- **Do not enter passwords or create accounts.** If a portal needs login or registration (Survey of India, Bhuvan), ask the user to download the file manually and tell them exactly where to put it.

## Data sources

Record every dataset in `data/SOURCES.md` with URL, download date, licence, version and attribution text. Priority order:

| Layer | Preferred source | Notes |
|---|---|---|
| India outline and states | Survey of India official boundary | Required for anything CF publishes. External boundary must match the official depiction, including J&K and Ladakh. Confirm current download location and licence. |
| Names and codes (state, district, block) | LGD, Local Government Directory (lgdirectory.gov.in) | Authoritative register. Use for validation, not geometry. |
| Districts | Survey of India district layer if available; otherwise the most recent open dataset reconciled to LGD | Must reflect current districts (Tamil Nadu has 38). |
| Blocks (CD blocks) | Bhuvan (ISRO), state GIS portals (TNGIS for Tamil Nadu), PMGSY GeoSadak | Coverage varies by state. If blocks are unavailable for a state, fall back to sub-district/taluk and label the panel accordingly. Never label a taluk as a block. |

Store processed boundaries in `data/processed/` as GeoPackage or GeoParquet, simplified sensibly for rendering but not so much that shapes visibly change. Keep raw downloads in `data/raw/` (gitignored if large, with download instructions in SOURCES.md).

## Validation (must run before every render)

1. Target state, district and block names exist in LGD. Accept common spelling variants through an alias table (`data/aliases.csv`), for example Thirumangalam / Tirumangalam.
2. The count of districts in the state layer matches LGD. Report any missing or extra names by name.
3. The count of blocks in the district layer matches LGD, reported the same way.
4. Every site point falls inside the stated district. Report which block it actually falls in, and warn if that differs from what the user stated. Do not assume.
5. Geometries are valid (no self-intersections, no gaps between neighbouring units beyond a small tolerance).

A failed check stops the render with a plain-language message. A `--force` flag can override warnings but not missing data.

## Inputs

One config per map, as YAML in `maps/` or as Colab form fields:

```yaml
state: Tamil Nadu
district: Madurai
blocks: [Madurai East]
sites:
  - name: Government Rajaji Hospital (GRH)
    lat: 9.929   # verify on Google Maps before use
    lon: 78.134
    type: hospital
title: null        # optional override
output_name: madurai_locator
```

Sites use coordinates, not name lookup. Users copy coordinates by right-clicking in Google Maps.

## Rendering

**Projection.** India panel in Lambert Conformal Conic suited to India. State and district panels in a local projection (appropriate UTM zone or local LCC) so shapes are not stretched. Never plot raw latitude and longitude.

**Layout.** Three panels left to right, equal height, landscape. Each panel has a title, north arrow, scale bar in km, and legend. Solid connector arrows run from each highlighted unit to the next panel. A small source line sits at the bottom, for example "Boundaries: Survey of India; names: LGD; data as of <date>".

**Labels.** Label every state, district and block. Avoid overlaps (adjustText or custom placement). Use leader lines for small units. Label seas and neighbouring states in muted italic on the state panel.

**Style (Cognizant brand).**
- Text: midnight blue `#000048`. Sentence case everywhere, never all caps or title case. Left-aligned titles.
- Font: Gellix if installed, else Arial. Make the font configurable.
- Non-target units: light grey `#D0D0CE` fill, white hairline borders.
- Target unit: one accent group only, default teal. Highlight fill `#05819B`, secondary highlight `#06C7CC`.
- Site markers: simple, midnight blue or dark accent, with a legend entry. No gradients, drop shadows or dashed lines.
- Water: white or very light grey. No coloured sea fills unless needed for legibility.
- No logo by default.
- Keep all colours in `style/brand.yaml` so they can be changed in one place.

**Output.** Save to `output/<output_name>/`:
- SVG and PDF (vector, primary)
- PNG at 300 dpi and 600 dpi
- A `render_log.txt` with inputs, validation results and data versions

## Repository structure

```
locator-maps/
  CLAUDE.md
  README.md            # plain-language guide for non-technical users
  requirements.txt
  locator/
    __init__.py
    data.py            # load and cache boundaries
    validate.py
    render.py
    style.py
    cli.py
  data/
    raw/  processed/  SOURCES.md  aliases.csv  lgd/
  style/brand.yaml
  maps/                # example configs
  notebooks/locator_map_colab.ipynb
  tests/
  output/              # gitignored
```

## Colab notebook

- First cell clones the repo and installs requirements.
- A form cell using `#@param` fields for state, district, blocks and sites (name, lat, lon).
- Run renders the map, displays a preview and offers the files for download, or saves them to a chosen Google Drive folder.
- No code editing required from the user.

## Test cases and acceptance

**Case 1: Madurai (reproduce the existing map, correctly).**
- State: Tamil Nadu. District: Madurai. Block: Madurai East. Site: Government Rajaji Hospital.
- Madurai should show 13 blocks. Expected list, to be confirmed against LGD (LGD wins if different): Alanganallur, Chellampatti, Kallikudi, Kottampatti, Madurai East, Madurai West, Melur, Sedapatti, Thirumangalam, Thiruparankundram, T. Kallupatti, Usilampatti, Vadipatti.
- The old AI map showed non-existent blocks (Kallandiri, Othakadai, Ayilangudi, Keela Kallandiri, Sakkimangalam, Vellikundram, Kadakinaru, Mathur), missed Tamil Nadu districts (Tiruppur, Namakkal, Chengalpattu, Mayiladuthurai and others) and misspelled Dindigul. None of these errors may appear.
- Report which block GRH actually falls in. It sits in Madurai city, which may be under the municipal corporation rather than a rural block. Flag this for the user rather than forcing a block.

**Case 2: Bhagalpur, Bihar.** District-level only if block data is not yet available.

Acceptance for each case: all validation checks pass, every label is legible at A4 print size, no overlaps, and the PNG looks sharp at 100% zoom.

## Build order

1. Set up the repo, environment and requirements.
2. Acquire and document data for India states, Tamil Nadu districts and Madurai blocks. Stop and ask the user for any manual downloads.
3. Build the validation module and run it on Tamil Nadu.
4. Build the renderer and produce Case 1. Show the output to the user for review before continuing.
5. Add the CLI and the Colab notebook.
6. Produce Case 2.
7. Extend data coverage state by state.
8. Later: a CF programme layer, read from a CSV exported from a Google Sheet (programme name, partner, lat, lon), to plot existing CF work and list programmes in the same or adjacent districts.

## Working rules

- Show rendered output after each visual change and wait for the user's feedback on layout decisions.
- Write the README for someone who has never used a terminal.
- Keep commits small, with clear messages.
- If any fact in this brief conflicts with official data, trust the official data and tell the user.
