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

## Two ways to use it

**Google Colab** is the easy way. Nothing to install, works in a browser, no
typing of commands. Skip to [Using it in Google Colab](#using-it-in-google-colab).

**On your own computer** is faster if you make a lot of maps. See
[Using it on your computer](#using-it-on-your-computer).

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
