"""Cognizant Foundation styling for the dashboard.

The palette and the type rules come from the Cognizant brand visual identity
guidelines (January 2025) and the Cognizant Foundation communication guidelines
(September 2024):

- Midnight blue is used for most text, in place of black.
- Grey shades carry tertiary information such as footnotes.
- Accent colours suit secondary headlines, lines and graphic elements, and are
  avoided for primary headlines.
- Headlines and copy are left-aligned, sentence case, never all caps.
- The logo sits in a corner, never centred, and is never recoloured, stretched
  or rotated.
"""

from __future__ import annotations

import base64
from functools import lru_cache
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
LOGO_PATH = PROJECT_ROOT / "assets" / "cognizant_foundation_india_logo.png"

# Base
MIDNIGHT_BLUE = "#000048"
WHITE = "#FFFFFF"

# Accent, three families
DARK_PLUM, MEDIUM_PLUM, LIGHT_PLUM = "#2E308E", "#7373D8", "#85A0F9"
DARK_BLUE, MEDIUM_BLUE, LIGHT_BLUE = "#2F78C4", "#6AA2DC", "#92BBE6"
DARK_TEAL, MEDIUM_TEAL, LIGHT_TEAL = "#05819B", "#06C7CC", "#26EFE9"

# Neutral
DARK_GRAY, MEDIUM_GRAY, LIGHT_GRAY = "#53565A", "#97999B", "#D0D0CE"

# Highlight, used sparingly
HIGHLIGHT_RED, HIGHLIGHT_YELLOW = "#B81F2D", "#E9C71D"

# The brand gradient runs across the three accent families. Used as a hairline
# rule, the way the Cognizant Foundation site divides its sections.
GRADIENT = (
    f"linear-gradient(90deg, {DARK_PLUM} 0%, {MEDIUM_PLUM} 18%, {DARK_BLUE} 42%, "
    f"{MEDIUM_BLUE} 58%, {DARK_TEAL} 80%, {LIGHT_TEAL} 100%)"
)


@lru_cache(maxsize=1)
def logo_data_uri() -> str:
    """Return the logo as a data URI, or an empty string if the file is absent."""
    if not LOGO_PATH.exists():
        return ""
    encoded = base64.b64encode(LOGO_PATH.read_bytes()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def css() -> str:
    """Return the stylesheet that makes the dashboard look like CF's own site."""
    return f"""
<style>
  /* Arial is the brand's everyday font. Gellix is the design font but it is
     licensed, so it is only used if the viewer happens to have it.
     Deliberately not applied with a broad [class*="st-"] selector: that also
     catches Streamlit's icon spans, whose glyphs are ligatures in an icon
     font, and they come out as the literal text "arrow_right". */
  html, body, .stMarkdown, .stMarkdown p, .stMarkdown li,
  label, button, input, select, textarea,
  h1, h2, h3, h4, h5, h6 {{
    font-family: Gellix, Arial, Helvetica, sans-serif;
  }}

  /* Leave every icon font exactly as Streamlit set it. */
  span[data-testid="stIconMaterial"],
  .material-icons, .material-icons-outlined,
  [class*="material-symbols"],
  span[translate="no"] {{
    font-family: "Material Symbols Rounded", "Material Symbols Outlined",
                 "Material Icons", sans-serif !important;
  }}

  /* Streamlit floats a toolbar over the top of the page, so the content needs
     to start below it or the first heading is clipped. */
  html body .block-container {{
    padding-top: 3.4rem !important;
    padding-bottom: 3rem;
    max-width: 1500px;
  }}

  /* Headings: midnight blue, left aligned, sentence case, generous weight.
     Streamlit ships its own heading rules, so these are scoped from html body
     to out-specify them rather than relying on !important alone. */
  html body h1, html body h2, html body h3, html body h4 {{
    color: {MIDNIGHT_BLUE} !important;
    letter-spacing: -0.015em !important;
    text-align: left !important;
  }}
  html body h1 {{
    font-weight: 700 !important;
    font-size: 1.78rem !important;
    line-height: 1.22 !important;
    margin-bottom: 0.15rem !important;
    padding-top: 0 !important;
  }}
  html body h2 {{
    font-weight: 700 !important;
    font-size: 1.28rem !important;
    padding-top: 0 !important;
    margin-top: 1.7rem !important;
  }}
  html body h3 {{ font-weight: 600 !important; font-size: 1.04rem !important; }}

  /* The header block: logo in the corner, never centred. */
  .cf-header {{
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 2rem;
    padding: 0.2rem 0 0.9rem 0;
  }}
  .cf-header-text {{ min-width: 0; }}
  .cf-header-text p {{
    color: {DARK_GRAY};
    font-size: 0.94rem;
    margin: 0.35rem 0 0 0;
    max-width: 62ch;
    line-height: 1.5;
  }}
  html body .cf-header img {{
    height: 58px;
    width: auto;
    flex: 0 0 auto;
    margin-top: 2px;
  }}

  /* The gradient hairline the CF site uses between sections. */
  /* Streamlit styles bare <hr> down to a 1px grey line, so these need to say
     so explicitly to keep the gradient visible. */
  html body hr.cf-rule, html body hr.cf-rule-thin {{
    border: none !important;
    border-radius: 2px;
    background-image: {GRADIENT} !important;
    background-color: transparent !important;
    opacity: 1 !important;
  }}
  html body hr.cf-rule {{
    height: 3px !important;
    margin: 0 0 1.5rem 0 !important;
  }}
  html body hr.cf-rule-thin {{
    height: 2px !important;
    margin: 2rem 0 1.2rem 0 !important;
    opacity: 0.6 !important;
  }}

  /* Primary action: the light teal pill from the CF site, midnight blue text
     on it for contrast. */
  html body .stButton > button[kind="primary"] {{
    background: {LIGHT_TEAL};
    color: {MIDNIGHT_BLUE};
    border: 1px solid {LIGHT_TEAL};
    border-radius: 999px;
    font-weight: 600;
    padding: 0.55rem 1.25rem;
  }}
  html body .stButton > button[kind="primary"]:hover {{
    background: {MEDIUM_TEAL};
    border-color: {MEDIUM_TEAL};
    color: {MIDNIGHT_BLUE};
  }}
  html body .stButton > button[kind="secondary"] {{
    background: {WHITE};
    color: {MIDNIGHT_BLUE};
    border: 1.5px solid {MIDNIGHT_BLUE};
    border-radius: 999px;
    font-weight: 600;
    padding: 0.5rem 1.2rem;
  }}
  html body .stButton > button[kind="secondary"]:hover {{
    background: {MIDNIGHT_BLUE};
    color: {WHITE};
  }}
  html body .stDownloadButton > button {{
    border-radius: 999px;
    border: 1.5px solid {DARK_TEAL};
    color: {DARK_TEAL};
    background: {WHITE};
    font-weight: 600;
  }}
  html body .stDownloadButton > button:hover {{
    background: {DARK_TEAL};
    color: {WHITE};
  }}

  /* Sidebar: a quiet off-white panel with a gradient edge. */
  section[data-testid="stSidebar"] {{
    background: #FAFAF9;
    border-right: 1px solid {LIGHT_GRAY};
  }}
  section[data-testid="stSidebar"] h2 {{
    font-size: 1.02rem;
    margin-top: 1.1rem;
  }}

  /* Status blocks, recoloured off Streamlit's defaults onto the brand. */
  div[data-testid="stAlert"] {{ border-radius: 6px; }}

  .cf-note {{
    border-left: 3px solid {DARK_TEAL};
    background: #F4FBFC;
    padding: 0.75rem 1rem;
    color: {MIDNIGHT_BLUE};
    font-size: 0.93rem;
    line-height: 1.55;
  }}
  .cf-caption {{
    color: {MEDIUM_GRAY};
    font-size: 0.8rem;
    line-height: 1.5;
  }}

  /* The map sits on white with a hairline, matching the panel frames on it. */
  .cf-map img {{
    border: 1px solid {LIGHT_GRAY};
    border-radius: 4px;
  }}

  div[data-testid="stExpander"] details {{
    border: 1px solid {LIGHT_GRAY};
    border-radius: 6px;
  }}
</style>
"""


def header_html(title: str, standfirst: str) -> str:
    """The page header: heading on the left, logo in the top-right corner."""
    logo = logo_data_uri()
    logo_tag = (
        f'<img src="{logo}" alt="Cognizant Foundation India">' if logo else ""
    )
    return f"""
<div class="cf-header">
  <div class="cf-header-text">
    <h1>{title}</h1>
    <p>{standfirst}</p>
  </div>
  {logo_tag}
</div>
<hr class="cf-rule">
"""


def rule_html() -> str:
    return '<hr class="cf-rule-thin">'
