# Locator map generator

Makes the three-panel location map that goes into a Cognizant Foundation
funding proposal:

1. **India**, with the state you are working in picked out in teal
2. **The state**, with every district shown and your district picked out
3. **The district**, with every block shown, your block picked out, and your
   sites marked

Arrows join each panel to the next. The map comes out as a picture you can drop
straight into a document or a deck.

## What makes this different from drawing a map by hand or with an AI tool

Every boundary on the map comes from a published government dataset. The tool
cannot draw a boundary, guess one, or make one up. If it does not have the data
it needs, it stops and tells you, rather than inventing something.

Before it draws anything it checks:

- that the state, district and block names you gave are real
- that the district count for the state matches the official register
- that the block count for the district matches the official register
- that each of your sites actually falls inside the district you said, and
  **which block it really falls in**
- that the block shapes fit together with no gaps

If a check fails you get a plain-English message saying what is wrong.

---

## Three ways to use it

**The dashboard** is the easy way. A web page with dropdowns, no commands to
type and no files to edit. Start here.

**Google Colab** if you would rather not install anything at all.

**The command line** if you make a lot of maps and want to script them.

---

## The dashboard

Open a terminal in this folder and run:

```bash
.venv/Scripts/python.exe -m streamlit run app.py
```

On a Mac:

```bash
.venv/bin/python -m streamlit run app.py
```

Your browser opens at `http://localhost:8501`. If it does not, open that address
yourself.

Pick the state, district and blocks from the dropdowns. They are built from the
boundary data itself, so a misspelt name is not something you can produce. Add
your sites in the little table, press **Make the map**, and the map appears with
download buttons under it.

The dashboard runs exactly the same checks and the same renderer as the command
line, so the files it gives you are identical.

---

## Using it in Google Colab

1. Open `notebooks/locator_map_colab.ipynb` in Google Colab.
2. Run the first cell (**Set up the tool**). This takes a few minutes the first
   time. You only do it once per session.
3. Fill in the boxes in the second cell: state, district, block, and your sites.
4. Run the third cell. The map appears underneath it.
5. Run one of the last two cells to download the files or save them to Google
   Drive.

You never need to edit any code.

---

## Using it on your computer

### One-time setup

You need Python 3.10 or newer. If you do not have it, get it from
[python.org/downloads](https://www.python.org/downloads/). On Windows, tick
**"Add Python to PATH"** on the first screen of the installer.

Open a terminal in this folder. On Windows that is PowerShell; on a Mac it is
Terminal. Then run these three commands, one at a time, waiting for each to
finish.

Make a private space for the tool's parts:

```bash
python -m venv .venv
```

Switch into it. On **Windows**:

```bash
.venv\Scripts\activate
```

On **Mac**:

```bash
source .venv/bin/activate
```

Install what it needs:

```bash
pip install -r requirements.txt
```

Download the boundary data. This is about 150 MB and only happens once:

```bash
python -m locator fetch
```

Setup is done. Next time you only need the `activate` step.

### Making a map

Maps are described by a small text file in the `maps` folder. Open
`maps/madurai.yaml` in any text editor to see one:

```yaml
state: Tamil Nadu
district: Madurai
blocks: [Madurai West]

sites:
  - name: Government Rajaji Hospital (GRH)
    lat: 9.9195
    lon: 78.1193
    type: hospital

title: null
output_name: madurai_locator
```

To make your own map, copy that file, give it a new name ending in `.yaml`, and
change the values. Then run:

```bash
python -m locator render maps/your-file.yaml
```

The finished files appear in `output/`, in a folder named after `output_name`.

### Getting the coordinates for a site

1. Find the place in [Google Maps](https://maps.google.com).
2. Right-click on the exact spot.
3. At the top of the menu that appears there is a pair of numbers, like
   `9.9195, 78.1193`. Click it to copy.
4. The **first** number is `lat`. The **second** is `lon`.

Getting these the wrong way round is the most common mistake. The tool checks
for it and will tell you.

### Checking before you draw

To run the checks without making a picture:

```bash
python -m locator check maps/your-file.yaml
```

---

## What you get

Each map produces a folder in `output/` containing:

| File | What it is for |
|---|---|
| `*.svg` | Vector. Best for a designer, scales to any size |
| `*.pdf` | Vector. Best for printing |
| `*_300dpi.png` | Picture. Good for documents and decks |
| `*_600dpi.png` | Picture. Use if it will be printed large |
| `render_log.txt` | A record of what was used and what was checked |

Keep `render_log.txt`. It records which datasets were used and which checks
passed, which is what you need if anyone asks where the map came from.

---

## When something goes wrong

The tool prints messages marked `ERROR`, `WARNING` or `INFO`.

**`ERROR` means it will not draw the map.** Something is wrong that cannot be
worked around: a name that does not exist, a site in the wrong district, or a
missing data file. Fix it and run again.

**`WARNING` means it stopped, but you can overrule it.** For example, if your
site turns out to be in a different block from the one you named. Read the
warning first. If you are sure it is fine, run the same command again with
`--force` on the end:

```bash
python -m locator render maps/your-file.yaml --force
```

`--force` never gets past an `ERROR`. Missing data always stops the map.

**`INFO` is just a note.** Nothing is wrong.

### "X is not a district of Y"

Check the spelling. The tool suggests the closest real name. If your spelling is
a legitimate local variant, add it to `data/aliases.csv` as a new line:

```
district,Your spelling,Official spelling,why you added it
```

Then it will be accepted from then on.

### "No LGD reference is recorded for districts in X"

The tool knows the shapes but has not been told how many districts that state
should have, so it cannot double-check the count. Add a line to
`data/lgd/reference_counts.csv` with the official number and the tool will check
it from then on.

---

## The Cognizant Foundation brand

Colours, type and logo rules follow the Cognizant brand visual identity
guidelines (January 2025) and the Cognizant Foundation communication guidelines
(September 2024):

- Midnight blue `#000048` for most text, in place of black
- Light grey `#D0D0CE` for units that are not the target, which is what the
  guide means by grey as a background for charts
- Dark teal `#05819B` for the highlighted unit; the guide allows teal as a
  general highlight colour
- Dark grey `#53565A` and medium grey `#97999B` for secondary and tertiary text
- Gellix where it is installed, Arial everywhere else
- Sentence case throughout, left-aligned, never all caps

### The logo

The map and the dashboard both carry the Cognizant Foundation India logo in a
corner, never centred, never recoloured, stretched or rotated. Its aspect ratio
is read from the image file so it cannot be distorted, and its width is floored
at the brand print minimum of 0.6875 inches.

**Cognizant Foundation requires approval for each use of the logo.** Because of
that it is controlled by a single switch in `style/brand.yaml`:

```yaml
logo:
  show: true
```

Set it to `false` for any map that has not been approved.

---

## Changing how the map looks

All the colours, type sizes and line weights live in one file:
`style/brand.yaml`. Open it in a text editor and change a value. You do not need
to touch any code.

The most likely things to change:

- `colours.highlight` — the teal used for the target unit
- `font.family` — the tool uses Gellix if it is installed on your machine and
  falls back to Arial if not
- `layout.figure_width_in` — how wide the finished map is, in inches

The height adjusts itself to suit the shapes being drawn, so a wide state like
Bihar produces a shorter image than a tall one like Tamil Nadu.

---

## How much of India is covered

All of it. Every one of the 785 districts in 36 states and union territories
produces a map.

Most get all three panels with real blocks. Seventeen districts of Rajasthan
created in 2023 — Balotra, Beawar, Phalodi, Sanchor and the rest — have a
published district boundary but no published blocks. For those the tool falls
back to the **tehsils** that fall inside the district, which do exist in the
sub-district register, just filed under the district each was carved out of.

Those maps say so on their face: the panel prints *"Sub-districts (tehsils)
shown: block boundaries are not published for this district"* together with the
share of the district they cover. A tehsil is never labelled a block.

If neither blocks nor tehsils exist, the third panel shows the district on its
own and says that too. The map never implies a detail it does not have.

### A word on how current the data is

The district and block boundaries are a 2023 snapshot. That matters in a few
places:

- **Rajasthan** shows 50 districts. The state cut back to 41 in January 2025.
- **Ladakh** shows 2 districts, not the 7 announced in 2024.

No openly licensed boundary dataset reflects those changes yet. The Local
Government Directory publishes new names and codes promptly, but the polygons
lag well behind, and Survey of India's own portal needs registration. Where an
independent count is recorded in `data/lgd/reference_counts.csv`, the tool
compares against it and warns by name when they disagree — so a stale boundary
shows up as a warning rather than a quietly wrong map.

---

## Where the data comes from

Recorded in full in [`data/SOURCES.md`](data/SOURCES.md), including download
links, licences and the date each one was checked. In short:

- **State boundaries and the India outline**: Survey of India. This matters —
  it carries India's official external boundary, which general-purpose world
  datasets do not.
- **District and block boundaries**: the Local Government Directory via
  BharatMaps, which carries official LGD codes.

Every map prints a source line along the bottom.

---

## For developers

```
locator/
  names.py      name normalisation, alias matching, display capitalisation
  data.py       downloading, caching and loading the boundary layers
  validate.py   every pre-render check
  style.py      brand settings, font resolution, projection choices
  render.py     the three-panel figure
  cli.py        command line, and the entry point Colab calls
```

Run the tests with:

```bash
python -m pytest tests/ -q
```

The validation tests use the real boundary layers and skip themselves if the
data has not been downloaded.

Two rules hold throughout the codebase: no part of the pipeline calls a language
model or an image generator, and no boundary is ever drawn, approximated or
invented. Same input, same data, same picture, every time.

---

## A note on reproducibility

The same config, the same data files and the same day produce a byte-identical
image. Two things were needed to make that true:

- The label placement library stops after a one-second time limit by default,
  which makes the result depend on how busy the machine is. This tool pins it to
  a fixed number of passes instead.
- The source line carries the date the map was generated, so a map made
  tomorrow differs from one made today by that line alone. That is deliberate,
  because the date belongs on the map.
