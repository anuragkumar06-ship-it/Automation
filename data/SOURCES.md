# Data sources

Every polygon this tool draws comes from a dataset recorded here. Nothing is
drawn, approximated or invented. If a layer needed for a map is missing, the
tool stops and says so rather than substituting a guess.

Last reviewed: 2026-09-22

---

## Summary of what is used for what

| Map layer | Dataset used | Why |
|---|---|---|
| India outline and states | `SOI_States` | Survey of India geometry, official external boundary depiction |
| Districts | `LGD_Districts` | Current districts, LGD-coded. See "Why not SOI_Districts" below |
| Blocks (CD blocks) | `LGD_Blocks` | Block names and LGD block codes, tiles each district completely |
| Names and codes | LGD (Local Government Directory) | Authoritative register, used for validation not geometry |

---

## 1. SOI_States — India state and union territory boundaries

- **File:** `data/raw/SOI_States.parquet` (19 MB, GeoParquet)
- **Download:** https://github.com/ramSeraph/indian_admin_boundaries/releases/download/states/SOI_States.parquet
- **Original source:** Survey of India — https://onlinemaps.surveyofindia.gov.in/Digital_Product_Show.aspx
- **Distributed by:** `ramSeraph/indian_admin_boundaries` (the Indian Open Maps project)
- **Licence:** CC0 1.0, with attribution requested to datameet and the originating
  government source — https://github.com/ramSeraph/indianopenmaps/blob/main/DATA_LICENSE.md
- **Release date:** 2023-12-11
- **Downloaded:** 2026-09-22
- **CRS:** OGC:CRS84 (WGS 84, longitude/latitude)
- **Rows:** 40 — 36 states and union territories, plus 4 internal "DISPUTED"
  sliver polygons between states (LGD code 0). The slivers are kept so the
  national outline has no holes; they are never labelled.
- **Columns:** `STATE` (with diacritics), `STATE_C` (ASCII), `State_LGD`, `Shape_Leng`, `Shape_Area`

**External boundary check (performed 2026-09-22).** This layer carries the
official Indian depiction, not the de-facto one:

- Northern extent reaches 37.088 °N and western extent 72.51 °E, within the
  Ladakh polygon — i.e. Gilgit-Baltistan is included.
- Ladakh area 168,011 km², consistent with administered Ladakh plus Aksai Chin
  plus Gilgit-Baltistan.
- Jammu and Kashmir (LGD 1) and Ladakh (LGD 37) appear as separate units,
  matching the post-2019 reorganisation.
- Jammu and Kashmir area 54,111 km², consistent with administered J&K plus
  the Mirpur–Muzaffarabad area.

This is why an openly-licensed global dataset such as Natural Earth or
geoBoundaries must **not** be substituted here: those use the de-facto line and
would be wrong for anything Cognizant Foundation publishes.

**Attribution line to print on maps:** `Boundaries: Survey of India`

---

## 2. LGD_Districts — district boundaries

- **File:** `data/raw/LGD_Districts.parquet` (33 MB, GeoParquet)
- **Download:** https://github.com/ramSeraph/indian_admin_boundaries/releases/download/districts/LGD_Districts.parquet
- **Original source:** LGD / BharatMaps —
  https://mapservice.gov.in/gismapservice/rest/services/BharatMapService/Admin_Boundary_Village/MapServer/1
- **Licence:** CC0 1.0, attribution as above
- **Release date:** 2023-12-11
- **Downloaded:** 2026-09-22
- **CRS:** OGC:CRS84
- **Rows:** 785
- **Columns used:** `dtname`, `stname`, `dist_lgd`, `state_lgd`

**Verified 2026-09-22:** Tamil Nadu returns **38 districts**, which matches the
current LGD count and the project brief. Mayiladuthurai (created 2020) is
present, as are Tiruppur, Namakkal and Chengalpattu.

### Why not SOI_Districts

`SOI_Districts` (Survey of India, 742 rows) was downloaded and compared. It
returns **37 districts for Tamil Nadu and is missing Mayiladuthurai**, so it is
one district out of date. The brief's stated priority is "Survey of India
district layer if available; otherwise the most recent open dataset reconciled
to LGD" — the SoI layer is available but not current, so `LGD_Districts` is used
instead. `SOI_Districts` is retained as a cross-check only.

Consequence to be aware of: the India/state panels use Survey of India geometry
and the district panel uses LGD geometry. The two agree closely but are not
bit-identical along shared edges. They are never drawn in the same panel.

---

## 3. LGD_Blocks — community development block boundaries

- **File:** `data/raw/LGD_Blocks.parquet` (96 MB, GeoParquet)
- **Download:** https://github.com/ramSeraph/indian_admin_boundaries/releases/download/blocks/LGD_Blocks.parquet
- **Original source:** LGD / BharatMaps —
  https://mapservice.gov.in/gismapservice/rest/services/BharatMapService/Admin_Boundary_GramPanchayat/MapServer/2
- **Licence:** CC0 1.0, attribution as above
- **Release date:** 2023-12-11
- **Downloaded:** 2026-09-22
- **CRS:** OGC:CRS84
- **Rows:** 7,146 blocks nationally
- **Columns used:** `block_name`, `block_lgd`, `district`, `dist_lgd`, `state`, `state_lgd`

**Verified 2026-09-22:**

- Tamil Nadu: 387 blocks across all 38 districts.
- Madurai district: **exactly 13 blocks**, matching the brief's expected list.
  LGD spellings are `ALANGANALLUR, CHELLAMPATTI, KALLIKUDI, KOTTAMPATTI,
  MADURAI EAST, MADURAI WEST, MELUR, SEDAPATTI, T.KALLUPATTI, TIRUMANGALAM,
  TIRUPPARANGUNRAM, USILAMPATTI, VADIPATTI`.
- The 13 block polygons sum to 3,713.9 km², identical to the Madurai district
  polygon area, so the blocks tile the district with no gap for the municipal
  corporation area.

None of the invented blocks from the old AI-generated map (Kallandiri,
Othakadai, Ayilangudi, Keela Kallandiri, Sakkimangalam, Vellikundram,
Kadakinaru, Mathur) exist in this layer.

---

## 3b. LGD_Subdistricts — tehsil / taluk boundaries, used as a fallback

- **File:** `data/raw/LGD_Subdistricts.parquet` (92 MB, GeoParquet)
- **Download:** https://github.com/ramSeraph/indian_admin_boundaries/releases/download/subdistricts/LGD_Subdistricts.parquet
- **Original source:** LGD / BharatMaps —
  https://mapservice.gov.in/gismapservice/rest/services/BharatMapService/Admin_Boundary_Village/MapServer/2
- **Licence:** CC0 1.0, attribution as above
- **Downloaded:** 2026-09-22
- **Rows:** 6,471
- **Columns used:** `sdtname`, `subdt_lgd`, `dtname`, `dist_lgd`, `stname`, `state_lgd`

Downloaded on demand, not at startup, because only a handful of districts need
it.

**Why it is selected by location rather than by code.** The seventeen Rajasthan
districts created in 2023 have no sub-districts filed under them in this layer,
exactly as they have no blocks. The tehsils that now make them up do exist —
filed under the district each was carved out of. So the tool takes every tehsil
whose area falls more than 50% inside the target district polygon.

This invents nothing: every polygon drawn is a published one, and the district
polygon defining the selection is published too. What it does do is re-attribute
published tehsils to a district the register has not caught up with, so the tool
reports the share of the district those tehsils cover and prints it on the map.
Verified 2026-09-22 across all seventeen: fourteen at 100%, the others at
81–98%.

They are labelled tehsils, never blocks.

## 4. PMGSY_Blocks — cross-check only, not used for rendering

- **File:** `data/raw/PMGSY_Blocks.parquet` (156 MB)
- **Download:** https://github.com/ramSeraph/indian_admin_boundaries/releases/download/blocks/PMGSY_Blocks.parquet
- **Original source:** PMGSY GeoSadak, Ministry of Rural Development
- **Rows:** 6,637
- **Not used because** it carries only numeric IDs (`BLOCK_ID`, `STATE_ID`,
  `DISTRICT_I`) and no names, so it cannot be validated against LGD without a
  separate code register.

---

## Standing caveats

1. **These files are a mirror, not a direct government download.** The
   geometry originates from Survey of India, LGD and BharatMaps, but it is
   redistributed by the `ramSeraph/indian_admin_boundaries` project. Survey of
   India's own portal requires registration, which this tool does not perform.
   If Cognizant Foundation needs a first-party download for a published map,
   obtain it manually — see "Manual download route" below.

2. **Vintage is December 2023.** The GeoParquet assets carry a March 2026
   upload date, but that is a re-encoding of the same 2023 snapshot, not fresher
   data. The Rajasthan district count proves it: the layer holds 50 districts,
   the count from the 2023 reorganisation, where the state has held 41 since
   January 2025. Ladakh likewise holds 2 districts rather than the 7 announced
   in 2024.

   Bharatlas, which advertises a 2024 LGD snapshot, was checked on 2026-09-22
   and carries the same 785 districts. No openly licensed dataset found so far
   reflects the newer reorganisations.

   Where a reference count is recorded, validation reports the mismatch by name,
   so a stale boundary surfaces as a warning rather than a silent error.

   **Seventeen Rajasthan districts created in 2023** (Balotra, Beawar, Phalodi,
   Sanchor, Salumbar, Shahpura, Jodhpur Gramin, Kekri, Didwana Kuchaman, Dudu,
   Anoopgarh, Neem Ka Thana and others) have a district polygon but no block
   polygons. Those render as a district-only third panel that says so on the
   map.

3. **Block coverage varies by state.** Where a state has no CD block layer, the
   tool must fall back to sub-district/taluk and label the panel accordingly.
   A taluk is never labelled as a block.

## Manual download route (first-party, requires registration)

If a first-party Survey of India file is required:

1. Go to https://onlinemaps.surveyofindia.gov.in/
2. Register and sign in. **Do this yourself — this tool does not create
   accounts or enter passwords.**
3. Under Digital Products, choose the Administrative Boundary Database, either
   "Entire country – District level" or "Entire country – Taluk level".
4. Save the download into `data/raw/soi_official/` and add an entry to this
   file recording the date, product name and licence terms shown at download.

---

## 5. Reference registers used for validation, not geometry

`data/lgd/reference_counts.csv` holds the counts the boundary layers are checked
against. It is kept separate from the geometry on purpose: checking an
LGD-derived layer against LGD numbers taken from that same layer would confirm
nothing. Each row records where its number came from.

Recorded so far:

| Level | Parent | Count | Source | Checked |
|---|---|---|---|---|
| District | Tamil Nadu | 38 | LGD district register, matching the list in the project brief | 2026-09-22 |
| Block | Madurai | 13 | LGD block list as stated in the project brief | 2026-09-22 |
| District | Bihar | 38 | Government of Bihar district register | 2026-09-22 |
| Block | Bhagalpur | 16 | Bhagalpur district administration, https://bhagalpur.nic.in/subdivision-blocks/ | 2026-09-22 |

**States with no row here are not silently accepted.** The validator raises a
warning saying the count has not been independently checked, which stops the
render unless `--force` is given. Adding a state means adding a row with a
citable source.

The Bhagalpur row is a genuine independent check: the names come from the
district administration's own website and four of them are spelled differently
there than in the boundary layer (Naugachia/Naugachhia, Rangra Chowk/
Rangrachowk, Sanhoula/Sonhaula, Pirpainty/Pirpainti). Those differences are
resolved through `data/aliases.csv`, and the count matched at 16.

## 6. Water body labels

`data/sea_labels.csv` holds the position of each sea or gulf label used on state
panels. These are **labels only** - no water polygon is drawn from them, and a
label appears only when its point falls inside the panel being drawn. Positions
are approximate label anchors, not boundaries, and are not used in any
measurement or containment test.
