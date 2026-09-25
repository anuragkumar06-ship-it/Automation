# Putting the dashboard online for your team

Two routes. **Streamlit Community Cloud** is free and takes about fifteen
minutes; it is the right first step. **A server inside Cognizant** is where this
should end up if the tool sticks — that section is at the bottom.

---

## Before you start: three things to decide

**1. The repository will be public.** Streamlit Community Cloud only deploys
from public GitHub repositories on the free plan. That means the code, the
boundary data and `assets/cognizant_foundation_india_logo.png` are all visible
to anyone. The code and boundary data are fine — the data is CC0 and the code
is yours. The logo is a Cognizant brand asset, so check that publishing it in a
public repository is acceptable before you push. If it is not, set
`logo.show: false` in `style/brand.yaml` and delete the file; everything else
works without it.

**2. Anyone with the link can use the app.** Streamlit Community Cloud apps are
public by default. You can restrict viewers to specific Google accounts in the
app settings — do that if these maps relate to unannounced programmes.

**3. Logo approval.** The communication guidelines require Cognizant Foundation
approval each time the logo is used. A dashboard that stamps it on every map is
worth raising with them once, rather than per map.

---

## Route 1: Streamlit Community Cloud

### Step 1 — check the data cache is built

The app reads `data/processed/`, which must be committed. Confirm it is there:

```bash
git ls-files data/processed | head
```

If that prints nothing, build it first. You need the raw files and about 1.5 GB
of free memory; it takes a few minutes and only has to happen once:

```bash
.venv/Scripts/python.exe -m locator prepare
```

Then commit the result. It is roughly 104 MB, which GitHub accepts — no single
file is anywhere near the 100 MB per-file limit.

### Step 2 — put it on GitHub

Create an empty repository on github.com (no README, no .gitignore — this
project has both). Then:

```bash
git remote add origin https://github.com/YOUR-USERNAME/YOUR-REPO.git
```

```bash
git push -u origin main
```

The first push moves about 110 MB, so give it a minute.

### Step 3 — deploy

1. Go to [share.streamlit.io](https://share.streamlit.io) and sign in with GitHub.
2. **Create app** → **Deploy a public app from GitHub**.
3. Repository: the one you just pushed. Branch: `main`. Main file path: `app.py`.
4. Open **Advanced settings** and set **Python version** to **3.12**.
5. **Deploy**.

The first build takes five to ten minutes while it installs geopandas. After
that it starts in seconds.

### Step 4 — update the Colab notebook

`notebooks/locator_map_colab.ipynb` still clones from a placeholder address.
Open it and change:

```python
repo_url = "https://github.com/YOUR-ORG/locator-maps.git"
```

to your actual repository, then commit. Otherwise the notebook route is broken
for whoever tries it.

---

## What will and will not work once it is up

**Memory.** A full render of Madurai peaks at about 370 MB against the 1 GB a
free app is allowed. That headroom exists because the boundary data is split
into one file per state; loading all of India took 1,072 MB and would have been
killed. If you ever change `locator/cache.py` to stop splitting, the app will
start dying on deploy and the reason will not be obvious, so do not.

**Speed.** First page load takes about ten seconds while the state and district
indexes load. A map takes fifteen to twenty seconds. The free tier sleeps an app
after a week of no visitors; the next visitor wakes it, which takes a minute.

**Place-name search.** This calls Nominatim, OpenStreetMap's free service. Two
things to know:

- Their usage policy allows light use only, and a hosted app shares an IP
  address with other Streamlit apps. If your team searches heavily you may see
  "the service is asking us to slow down". The app already limits itself to one
  request a second and identifies itself, which is what the policy asks for.
- If it does get blocked, the fallback is unchanged: type coordinates in by
  hand. Nothing else in the tool depends on it.

**What the app cannot do on the free tier.** It cannot write anywhere permanent.
Rendered maps are downloaded by the person who made them and are not kept on the
server, which is the behaviour you want anyway.

---

## Route 2: a server inside Cognizant

Better long term: the repository stays private, viewers are controlled by your
own network, there is no memory ceiling, and nothing leaves Cognizant except the
place-name lookups.

Whoever runs it needs:

- Python 3.10 or newer, and the ability to `pip install -r requirements.txt`
- The repository, including `data/processed/` (about 104 MB)
- One command: `streamlit run app.py --server.port 8501 --server.address 0.0.0.0`
- Port 8501 reachable from your network, or a reverse proxy in front of it

Two notes worth passing on:

- The app needs outbound HTTPS to `nominatim.openstreetmap.org` for place-name
  search. If outbound traffic is blocked, everything else still works and the
  search reports that it cannot reach the service.
- It needs no database, no credentials and no API keys. All state lives in the
  browser session.

For anything beyond a handful of concurrent users, run it under a process
manager so it restarts on failure, and give it 2 GB of memory so several people
can render at once.

---

## Keeping the data current

The boundaries are a 2023 snapshot. When a newer one is published:

```bash
.venv/Scripts/python.exe -m locator fetch
```

```bash
.venv/Scripts/python.exe -m locator prepare
```

Commit the changed files under `data/processed/` and push. Streamlit Cloud
redeploys by itself when it sees a new commit. Update the "as of" date in
`locator/render.py` and the entries in `data/SOURCES.md` at the same time, so
the source line on the map stays honest.
