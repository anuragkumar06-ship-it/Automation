"""Rebuild the two figures at print resolution, in Cognizant Foundation colours."""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

MIDNIGHT = "#000048"
DARK_GRAY = "#53565A"
MED_GRAY = "#97999B"
LIGHT_GRAY = "#D0D0CE"
TEAL = "#05819B"
RED = "#B81F2D"
GREEN = "#1E7B34"

plt.rcParams["font.family"] = ["Arial", "DejaVu Sans"]


def box(ax, x, y, w, h, label, sub, accent=False):
    ax.add_patch(FancyBboxPatch(
        (x, y), w, h, boxstyle="round,pad=0,rounding_size=0.08",
        facecolor=TEAL if accent else "white", alpha=0.12 if accent else 1.0,
        edgecolor="none", zorder=1))
    ax.add_patch(FancyBboxPatch(
        (x, y), w, h, boxstyle="round,pad=0,rounding_size=0.08",
        facecolor="none", edgecolor=TEAL if accent else DARK_GRAY,
        linewidth=1.8 if accent else 1.1, zorder=2))
    ax.text(x + w / 2, y + h * 0.60, label, ha="center", va="center",
            fontsize=10.5, fontweight="bold", color=MIDNIGHT, zorder=3)
    ax.text(x + w / 2, y + h * 0.27, sub, ha="center", va="center",
            fontsize=8.6, color=DARK_GRAY, zorder=3)


def arrow(ax, x1, y1, x2, y2, colour):
    ax.add_patch(FancyArrowPatch(
        (x1, y1), (x2, y2), arrowstyle="-|>", mutation_scale=13,
        linewidth=1.2, color=colour, shrinkA=0, shrinkB=0, zorder=2))


# ---- figure 1: how a map gets made ------------------------------------
fig, ax = plt.subplots(figsize=(9.2, 3.5))
ax.set_xlim(0, 100); ax.set_ylim(4, 38); ax.axis("off")

w, h, y = 19, 9, 22
xs = [4, 28, 52, 78]
box(ax, xs[0], y, w, h, "1. Choose", "state, district, sites")
box(ax, xs[1], y, w, h, "2. Check", "five tests on the data")
box(ax, xs[2], y, w, h, "3. Draw", "three panels, to scale", accent=True)

for a, b in ((0, 1), (1, 2)):
    arrow(ax, xs[a] + w, y + h / 2, xs[b], y + h / 2, DARK_GRAY)
arrow(ax, xs[2] + w, y + h / 2, xs[3], y + h / 2, DARK_GRAY)

ax.add_patch(FancyBboxPatch((xs[3], y - 3), 15, h + 6,
             boxstyle="round,pad=0,rounding_size=0.08", facecolor="none",
             edgecolor=DARK_GRAY, linewidth=1.1))
ax.text(xs[3] + 7.5, y + h + 0.4, "Files", ha="center", fontsize=10.5,
        fontweight="bold", color=MIDNIGHT)
for i, f in enumerate(["SVG", "PDF", "PNG x 2", "log"]):
    ax.text(xs[3] + 7.5, y + h - 2.6 - i * 2.4, f, ha="center", fontsize=8.6, color=DARK_GRAY)

arrow(ax, xs[1] + w / 2, y, xs[1] + w / 2, y - 6, RED)
ax.add_patch(FancyBboxPatch((xs[1] - 1.5, y - 13), w + 3, 6.6,
             boxstyle="round,pad=0,rounding_size=0.08", facecolor="none",
             edgecolor=RED, linewidth=1.1))
ax.text(xs[1] + w / 2, y - 9.7, "Something does not match:\nnothing is drawn",
        ha="center", va="center", fontsize=8.6, color=MIDNIGHT)

ax.text(4, 34, "How a map gets made", fontsize=13, fontweight="bold", color=MIDNIGHT)
ax.text(4, 5.2, "No step calls an AI. The same choices always produce the same map.",
        fontsize=8.6, color=MED_GRAY)
fig.savefig(".docbuild/fig_pipeline.png", dpi=300, bbox_inches="tight",
            facecolor="white", pad_inches=0.15)
plt.close(fig)

# ---- figure 2: memory before and after --------------------------------
fig, ax = plt.subplots(figsize=(7.4, 3.7))
stages, values = ["Before", "After"], [1072, 370]
colours = [RED, GREEN]
bars = ax.bar(stages, values, width=0.44, color=colours, alpha=0.88, zorder=3)

ax.axhline(1024, linestyle=(0, (5, 4)), linewidth=1.4, color=MED_GRAY, zorder=4)
ax.text(1.62, 1040, "1,024 MB limit", va="bottom", ha="right", fontsize=9, color=DARK_GRAY)

for bar, v in zip(bars, values):
    ax.text(bar.get_x() + bar.get_width() / 2, v + 28, f"{v:,} MB",
            ha="center", fontsize=10.5, fontweight="bold", color=MIDNIGHT)

for note, x in (("whole of India loaded", 0), ("one state loaded", 1)):
    ax.text(x, -112, note, ha="center", fontsize=8.6, color=MED_GRAY)

ax.set_ylim(0, 1250); ax.set_xlim(-0.55, 1.68)
ax.set_yticks([0, 250, 500, 750, 1000, 1250])
ax.set_yticklabels([f"{t:,}" for t in [0, 250, 500, 750, 1000, 1250]],
                   fontsize=9, color=DARK_GRAY)
ax.tick_params(axis="x", labelsize=10.5, colors=MIDNIGHT, length=0)
for label in ax.get_xticklabels():
    label.set_fontweight("bold")
ax.grid(axis="y", color=LIGHT_GRAY, linewidth=0.7, zorder=0)
ax.set_axisbelow(True)
for side in ("top", "right", "left"):
    ax.spines[side].set_visible(False)
ax.spines["bottom"].set_color(DARK_GRAY)
ax.set_title("Splitting the data by state brought it under the limit",
             fontsize=12.5, fontweight="bold", color=MIDNIGHT, loc="left", pad=22)
ax.text(0, 1.03, "Memory used to draw one map (megabytes)", transform=ax.transAxes,
        fontsize=9, color=DARK_GRAY)
fig.savefig(".docbuild/fig_memory.png", dpi=300, bbox_inches="tight",
            facecolor="white", pad_inches=0.15)
plt.close(fig)
print("figures written")
