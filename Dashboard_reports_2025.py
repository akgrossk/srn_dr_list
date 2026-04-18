import streamlit as st 
import pandas as pd
import numpy as np
from collections import defaultdict
import altair as alt
from io import BytesIO
import requests
from urllib.parse import urlencode
#from openai import OpenAI
import uuid
#from supabase import create_client, Client

# ---- FORCE LIGHT MODE (UI + charts) ----
st.set_page_config(layout="wide", initial_sidebar_state="expanded")

def _force_light_mode():
    st.markdown("""
    <style>
    /* Primary (blue) — only real primary buttons */
    button[data-testid="baseButton-primary"] {
      background: var(--primary-color) !important;
      color: #ffffff !important;
      border: 1px solid var(--primary-color) !important;
      box-shadow: none !important;
    }
    
    /* Secondary (white) — secondary buttons + popover trigger */
    button[data-testid="baseButton-secondary"],
    [data-testid="stPopover"] > button {
      background: #ffffff !important;
      color: #111111 !important;
      border: 1px solid #d0d5dd !important;
      box-shadow: none !important;
    }
    button[data-testid="baseButton-secondary"]:hover,
    [data-testid="stPopover"] > button:hover {
      background: #f4f6fa !important;
    }
    
    /* Link buttons — force secondary look even if rendered as primary */
    div[data-testid="stLinkButton"] a,
    div[data-testid="stLinkButton"] a[data-testid="baseButton-primary"],
    div[data-testid="stLinkButton"] a[data-testid="baseButton-secondary"] {
      background: #ffffff !important;
      background-image: none !important;
      color: #111111 !important;
      border: 1px solid #d0d5dd !important;
      box-shadow: none !important;
    }
    div[data-testid="stLinkButton"] a:hover {
      background: #f4f6fa !important;
    }
    /* extra space below the ISIN / Country / Sector / Industry line */
    .firm-meta {
      display: block;
      margin: 6px 0 18px 0 !important;
      line-height: 1.6;
    }

    /* Prior year toggle disabled state */
    .prior-year-disabled {
      opacity: 0.45;
      pointer-events: none;
      filter: grayscale(0.4);
    }
    .prior-year-note {
      font-size: 0.78rem;
      color: #888;
      margin-top: 2px;
    }
    </style>
    """, unsafe_allow_html=True)

    # Force Altair/Vega to light mode
    alt_light = {
        "config": {
            "background": "white",
            "view": {"stroke": "transparent"},
            "axis": {"labelColor": "#111111", "titleColor": "#111111", "gridColor": "#e6e6e6"},
            "legend": {"labelColor": "#111111", "titleColor": "#111111"},
            "title": {"color": "#111111"},
        }
    }
    try:
        alt.themes.register("force_light", lambda: alt_light)
        alt.themes.enable("force_light")
    except Exception:
        pass

_force_light_mode()

# ========= VARIANT / TREATMENT ARMS =========

VARIANT_KEYS = ["v1", "v2", "v3"]
DEFAULT_VARIANT = None  # None => randomize when URL lacks ?v=

def _qp_get(key, default=None):
    try:
        v = st.query_params.get(key, default)
        if isinstance(v, list):
            return v[0] if v else default
        return v
    except Exception:
        qp = st.experimental_get_query_params()
        v = qp.get(key, [default])
        return v[0] if isinstance(v, list) else v

def _qp_update(**params):
    try:
        st.query_params.update(params)
    except Exception:
        cur = st.experimental_get_query_params()
        cur.update(params)
        st.experimental_set_query_params(**cur)

def _get_variant():
    v = (_qp_get("v", "") or "").lower()
    if v in VARIANT_KEYS:
        st.session_state["variant"] = v
        return v

    v = st.session_state.get("variant")
    if v not in VARIANT_KEYS:
        v = DEFAULT_VARIANT or np.random.choice(VARIANT_KEYS)
        st.session_state["variant"] = v

    _qp_update(v=v)
    return v

DEV_MODE = str(_qp_get("dev", "") or "").lower() in ("1", "true", "yes")
try:
    if st.secrets.get("DEV_MODE"):
        DEV_MODE = True
except Exception:
    pass

VARIANT = _get_variant()


# ========= CONFIG =========
DEFAULT_DATA_URL = "https://github.com/akgrossk/srn_dr_list/blob/main/flagship_dashboard.xlsx"
#openai = OpenAI(api_key=st.secrets["OPENAI_API_KEY"])

# ========= SUPABASE CONFIG =========
supabase = None
SUPABASE_ENABLED = False

FIRM_NAME_COL_CANDIDATES = ["display_name", "name","company", "firm"]
FIRM_ID_COL_CANDIDATES   = ["isin", "ticker"]
COUNTRY_COL_CANDIDATES   = ["country", "Country"]
YEAR_COL_CANDIDATES      = ["year", "Year", "fiscal_year", "reporting_year"]

INDUSTRY_COL_CANDIDATES  = ["primary_sics_industry", "industry", "Industry"]
SECTOR_COL_CANDIDATES    = [ "sector", "Sector"]

YES_SET = {"yes", "ja", "true", "1"}
NO_SET  = {"no", "nein", "false", "0"}
PILLAR_LABEL = {"E": "Environment", "S": "Social", "G": "Governance"}

ESRS_LABELS = {
    "E1": "ESRS E1 — Climate change",
    "E2": "ESRS E2 — Pollution",
    "E3": "ESRS E3 — Water and marine resources",
    "E4": "ESRS E4 — Biodiversity and ecosystems",
    "E5": "ESRS E5 — Resource use and circular economy",
    "S1": "ESRS S1 — Own workforce",
    "S2": "ESRS S2 — Workers in the value chain",
    "S3": "ESRS S3 — Affected communities",
    "S4": "ESRS S4 — Consumers and end-users",
    "G1": "ESRS G1 — Governance and business conduct",
}

SHORT_ESRS_LABELS = {
    "E1": "E1 - Climate change",
    "E2": "E2 - Pollution",
    "E3": "E3 - Water and marine resources",
    "E4": "E4 - Biodiversity and ecosystems",
    "E5": "E5 - Resource use and circular economy",
    "S1": "S1 - Own workforce",
    "S2": "S2 - Workers in the value chain",
    "S3": "S3 - Affected communities",
    "S4": "S4 - Consumers and end-users",
    "G1": "G1 - Governance and business conduct",
}

def parse_label_block(text: str) -> dict:
    labels = {}
    for raw in text.strip().splitlines():
        if not raw.strip():
            continue
        parts = raw.split("\t", 1)
        if len(parts) == 2:
            code, name = parts
            labels[code.strip()] = name.strip()
    return labels

DR_LABELS = parse_label_block(r"""
E1-GOV-3	Disclosure requirement related to ESRS 2 GOV-3 Integration of sustainability-related performance in incentive schemes
E1-1	Transition plan for climate change mitigation
E1-SBM-3	Material impacts, risks and opportunities and their interaction with strategy and business model
E1-IRO-1	Description of the processes to identify and assess material climate-related impacts, risks and opportunities
E1-2	Policies related to climate change mitigation and adaptation
E1-3	Actions and resources in relation to climate change policies
E1-4	Targets related to climate change mitigation and adaptation
E1-5	Energy consumption and mix
E1-6	Gross Scopes 1, 2, 3 and Total GHG emissions
E1-7	GHG removals and GHG mitigation projects financed through carbon credits
E1-8	Internal carbon pricing
E1-9	Anticipated financial effects from material physical and transition risks and potential climate-related opportunities
E2-IRO-1	Description of the processes to identify and assess material pollution-related impacts, risks and opportunities
E2-1	Policies related to pollution
E2-2	Actions and resources related to pollution
E2-3	Targets related to pollution
E2-4	Pollution of air, water and soil
E2-5	Substances of concern and substances of very high concern
E2-6	Anticipated financial effects from pollution-related impacts, risks and opportunities
E3-IRO-1	Description of the processes to identify and assess material water and marine resources-related impacts, risks and opportunities
E3-1	Policies related to water and marine resources
E3-2	Actions and resources related to water and marine resources
E3-3	Targets related to water and marine resources
E3-4	Water consumption
E3-5	Anticipated financial effects from water and marine resources-related impacts, risks and opportunities
E4-1	Transition plan and consideration of biodiversity and ecosystems in strategy and business model
E4-SBM-3	Material impacts, risks and opportunities and their interaction with strategy and business model
E4-IRO-1	Description of processes to identify and assess material biodiversity and ecosystem-related impacts, risks and opportunities
E4-2	Policies related to biodiversity and ecosystems
E4-3	Actions and resources related to biodiversity and ecosystems
E4-4	Targets related to biodiversity and ecosystems
E4-5	Impact metrics related to biodiversity and ecosystems change
E4-6	Anticipated financial effects from biodiversity and ecosystem-related impacts, risks and opportunities
E5-IRO-1	Description of the processes to identify and assess material resource use and circular economy-related impacts, risks and opportunities
E5-1	Policies related to resource use and circular economy
E5-2	Actions and resources related to resource use and circular economy
E5-3	Targets related to resource use and circular economy
E5-4	Resource inflows
E5-5	Resource outflows
E5-6	Anticipated financial effects from resource use and circular economy-related impacts, risks and opportunities
S1-SBM-2	Interests and views of stakeholders
S1-SBM-3	Material impacts, risks and opportunities and their interaction with strategy and business model
S1-1	Policies related to own workforce
S1-2	Processes for engaging with own workers and workers' representatives about impacts
S1-3	Processes to remediate negative impacts and channels for own workers to raise concerns
S1-4	Taking action on material impacts on own workforce, and approaches to mitigating material risks and pursuing material opportunities related to own workforce, and effectiveness of those actions
S1-5	Targets related to managing material negative impacts, advancing positive impacts, and managing material risks and opportunities
S1-6	Characteristics of the undertaking's employees
S1-7	Characteristics of non-employee workers in the undertaking's own workforce
S1-8	Collective bargaining coverage and social dialogue
S1-9	Diversity metrics
S1-10	Adequate wages
S1-11	Social protection
S1-12	Persons with disabilities
S1-13	Training and skills development metrics
S1-14	Health and safety metrics
S1-15	Work-life balance metrics
S1-16	Compensation metrics (pay gap and total compensation)
S1-17	Incidents, complaints and severe human rights impacts
S2-SBM-2	Interests and views of stakeholders
S2-SBM-3	Material impacts, risks and opportunities and their interaction with strategy and business model
S2-1	Policies related to value chain workers
S2-2	Processes for engaging with value chain workers about impacts
S2-3	Processes to remediate negative impacts and channels for value chain workers to raise concerns
S2-4	Taking action on material impacts on value chain workers, and approaches to mitigating material risks and pursuing material opportunities related to value chain workers, and effectiveness of those actions
S2-5	Targets related to managing material negative impacts, advancing positive impacts, and managing material risks and opportunities
S3-SBM-2	Interests and views of stakeholders
S3-SBM-3	Material impacts, risks and opportunities and their interaction with strategy and business model
S3-1	Policies related to affected communities
S3-2	Processes for engaging with affected communities about impacts
S3-3	Processes to remediate negative impacts and channels for affected communities to raise concerns
S3-4	Taking action on material impacts on affected communities, and approaches to mitigating material risks and pursuing material opportunities related to affected communities, and effectiveness of those actions
S3-5	Targets related to managing material negative impacts, advancing positive impacts, and managing material risks and opportunities
S4-SBM-2	Interests and views of stakeholders
S4-SBM-3	Material impacts, risks and opportunities and their interaction with strategy and business model
S4-1	Policies related to consumers and end-users
S4-2	Processes for engaging with consumers and end-users about impacts
S4-3	Processes to remediate negative impacts and channels for consumers and end-users to raise concerns
S4-4	Taking action on material impacts on consumers and end-users, and approaches to mitigating material risks and pursuing material opportunities related to consumers and end-users, and effectiveness of those actions
S4-5	Targets related to managing material negative impacts, advancing positive impacts, and managing material risks and opportunities
G1-IRO-1	Description of the processes to identify and assess material impacts, risks and opportunities
G1-GOV-1	The role of the administrative, supervisory and management bodies
G1-1	Corporate culture and business conduct policies
G1-2	Management of relationships with suppliers
G1-3	Prevention and detection of corruption or bribery
G1-4	Confirmed incidents of corruption or bribery
G1-5	Political influence and lobbying activities
G1-6	Payment practices
""")


# === Overview palettes ===
E_STANDARDS = ["E1", "E2", "E3", "E4", "E5"]
S_STANDARDS = ["S1", "S2", "S3", "S4"]
G_STANDARDS = ["G1"]
PALETTE_E = [
    "#003d1f",
    "#006d2c",
    "#00a65a",
    "#5ec962",
    "#b8e3c6"
]
PALETTE_S = ["#6B0F0F", "#C01818", "#FF3B2F", "#FFB3A8"]
PALETTE_G = ["#F0CB51"]
STD_ORDER = E_STANDARDS + S_STANDARDS + G_STANDARDS
STD_COLOR = {
    **{s: c for s, c in zip(E_STANDARDS, PALETTE_E)},
    **{s: c for s, c in zip(S_STANDARDS, PALETTE_S)},
    **{s: c for s, c in zip(G_STANDARDS, PALETTE_G)},
}
STD_TOTAL_OVERRIDES = {
    "E1": 9, "E2": 6, "E3": 5, "E4": 6, "E5": 6,
    "S1": 17, "S2": 5, "S3": 5, "S4": 5,
    "G1": 6,
}

STD_COLOR_V1 = STD_COLOR
STD_COLOR_V2 = STD_COLOR
STD_COLOR_V3 = STD_COLOR

if VARIANT == "v3":
    STD_COLOR = STD_COLOR_V2
elif VARIANT == "v2":
    STD_COLOR = STD_COLOR_V3

TILE_OK = "#4200ff"
TILE_NO = "#d6ccff"
TILE_PHASE = "#7F7EA8"  # medium purple for phase-in DRs

STD_RANK = {code: i for i, code in enumerate(STD_ORDER)}

COMP_TO_PARAM = {
    "No comparison": "none",
    "Country": "country",
    "Sector": "sector",
    "Industry": "industry",
    "Custom peers": "custom",
}
PARAM_TO_COMP = {v: k for k, v in COMP_TO_PARAM.items()}

# ========= HELPERS =========

def normalize_yes_no(val):
    """Convert Yes/No strings (and variants) to 1/0. Leaves numeric values unchanged."""
    if pd.isna(val):
        return np.nan
    s = str(val).strip().lower()
    if s in YES_SET:
        return 1
    if s in NO_SET:
        return 0
    # already numeric?
    try:
        return float(val)
    except (ValueError, TypeError):
        return np.nan

def normalize_esg_columns(df: pd.DataFrame, esg_cols: list) -> pd.DataFrame:
    """Convert all ESG columns from Yes/No strings to 1/0 numeric in-place."""
    for col in esg_cols:
        if col in df.columns:
            df[col] = df[col].apply(normalize_yes_no)
    return df

def pretty_value(v):
    if pd.isna(v):
        return "—"
    try:
        fv = float(v)
        if fv == 1.0:
            return "✅ Yes"
        if fv == 0.0:
            return "❌ No"
    except (ValueError, TypeError):
        pass
    s = str(v).strip().lower()
    if s in YES_SET:
        return "✅ Yes"
    if s in NO_SET:
        return "❌ No"
    return str(v)

import re as _re

def group_key(col: str):
    if not isinstance(col, str) or not col or col[0] not in "ESGesg":
        return None
    # Old hyphen format
    if "-" in col:
        parts = col.split("-")
        if len(parts) >= 2 and not parts[1].isdigit():
            return f"{parts[0].upper()}-{parts[1]}"
        return parts[0].upper()
    # New compact format: letter + std_digit + dr_digits[+ suffix]
    m = _re.match(r'^([ESGesg])(\d)', col)
    if m:
        return m.group(1).upper() + m.group(2)   # e.g. "E1", "S2", "G1"
    return None

def build_hierarchy(columns):
    groups = defaultdict(list)
    for c in columns:
        g = group_key(c)
        if g:
            groups[g].append(c)
    def mkey(c):
        last = c.split("-")[-1]
        try:
            return (int(last), c)
        except Exception:
            return (10_000, c)

    for g in list(groups.keys()):
        groups[g] = sorted(groups[g], key=mkey)

    by_pillar = {"E": [], "S": [], "G": []}
    for g in groups:
        by_pillar[g[0]].append(g)

    def gkey(gname):
        base = gname.split("-")[0]
        try:
            return (gname[0], int(base[1:]), gname)
        except Exception:
            return (gname[0], 9999, gname)

    for p in by_pillar:
        by_pillar[p] = sorted(by_pillar[p], key=gkey)
    return groups, by_pillar

def pillar_columns(pillar: str, groups, by_pillar):
    cols, seen, out = [], set(), []
    for g in by_pillar.get(pillar, []):
        cols.extend(groups[g])
    for c in cols:
        if c not in seen:
            out.append(c)
            seen.add(c)
    return out

def normalize_github_raw_url(url: str) -> str:
    u = url.strip()
    if "github.com" in u and "/blob/" in u:
        u = u.replace("https://github.com/", "https://raw.githubusercontent.com/").replace("/blob/", "/")
    return u

@st.cache_data(show_spinner=False)
def load_table(url: str) -> pd.DataFrame:
    u = normalize_github_raw_url(url)
    headers = {}
    try:
        token = st.secrets.get("GITHUB_TOKEN")
        if token:
            headers["Authorization"] = f"token {token}"
    except Exception:
        pass
    try:
        r = requests.get(u, headers=headers, timeout=30)
        r.raise_for_status()
        data = BytesIO(r.content)
        if u.lower().endswith((".xlsx", ".xls")):
            excel_df = pd.read_excel(data)
            # Use left merge so rows without a matching document_id (e.g. new-year rows)
            # are kept rather than silently dropped by an inner join.
            if 'company_id' in excel_df.columns:
                try:
                    api_df = (
                        pd.read_json("https://api.srnav.com/documents")
                          .assign(company_id=lambda y: [z["id"] for z in y["company"]])
                          .loc[:, ['company_id', 'id']]
                          .rename(columns={'id': 'document_id'})
                    )
                    # Left merge: keep all Excel rows, only fill document_id where available
                    merged = excel_df.merge(api_df[['company_id', 'document_id']], on='company_id', how='left')
                    # If document_id already existed in Excel, fill from API only where missing
                    if 'document_id' in excel_df.columns and 'document_id_api' in merged.columns:
                        merged['document_id'] = merged['document_id'].fillna(merged['document_id_api'])
                        merged = merged.drop(columns=['document_id_api'], errors='ignore')
                    return merged
                except Exception:
                    pass
            return excel_df
        return pd.read_csv(data)
    except Exception as e:
        st.error(f"Failed to fetch data from GitHub: {e}")
    return pd.DataFrame()

def first_present(cols, candidates):
    for c in candidates:
        if c in cols:
            return c
    return None

def read_query_param(key: str, default=None):
    try:
        v = st.query_params.get(key, default)
        if isinstance(v, list):
            v = v[0] if v else default
        return v
    except Exception:
        qp = st.experimental_get_query_params()
        v = qp.get(key, [default])
        return v[0] if isinstance(v, list) else v

def set_query_params(**params):
    try:
        st.query_params.update(params)
    except Exception:
        st.experimental_set_query_params(**params)

def build_peers(df, comp_col, current_row):
    if not comp_col:
        return None, 0, ""
    current_val = str(current_row.get(comp_col, ""))
    if current_val == "":
        return None, 0, ""
    peers = df[df[comp_col].astype(str) == current_val].copy()
    try:
        peers = peers.drop(current_row.name, errors="ignore")
    except Exception:
        pass
    label = friendly_col_label(comp_col)
    note = f" ({label} = {current_val}, n={len(peers)})"
    return peers, len(peers), note

def build_custom_peers(df, label_col, selected_labels, current_row):
    if not label_col or not selected_labels:
        return None, 0, ""
    target = set(map(str, selected_labels))
    peers = df[df[label_col].astype(str).isin(target)].copy()
    try:
        peers = peers.drop(current_row.name, errors="ignore")
    except Exception:
        pass
    note = f" (custom peers, n={len(peers)})"
    return peers, len(peers), note

MISSING_SWATCH_COLOR = "#C2C2C2"

def render_inline_legend_with_single_missing(codes, colors, label_text="Not reported"):
    _inject_fizzy_filter()
    items = "".join(
        f'<span class="swatch" style="background:{colors[c]}"></span>'
        f'<span class="lab">{c}</span>'
        for c in codes
    )
    items += (
        f'<span class="swatch miss" style="--miss:{MISSING_SWATCH_COLOR}"></span>'
        f'<span class="lab">{label_text}</span>'
    )
    st.markdown(
        """
        <style>
        .legend-inline{display:flex;flex-wrap:wrap;gap:.5rem 1rem;align-items:center;margin-top:.35rem;}
        .legend-inline .swatch{display:inline-block;width:12px;height:12px;border-radius:2px;margin-right:.35rem;}
        .legend-inline .lab{font-size:0.9rem;}
        .legend-inline .swatch.miss{
          background: var(--miss);
          opacity: .6;
          border: 1.5px dashed var(--miss);
          filter: url(#fizzyEdge);
        }
        @supports not (filter: url(#fizzyEdge)) {
          .legend-inline .swatch.miss{
            -webkit-mask-image: radial-gradient(circle at 50% 50%, #000 84%, transparent 88%);
                    mask-image: radial-gradient(circle at 50% 50%, #000 84%, transparent 88%);
          }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    st.markdown(f'<div class="legend-inline">{items}</div>', unsafe_allow_html=True)


def render_pillar_legend_single_missing(stds_in_pillar, colors, label_text="Not reported"):
    _inject_fizzy_filter()
    items = "".join(
        f'<span class="swatch" style="background:{colors[c]}"></span>'
        f'<span class="lab">{c}</span>'
        for c in stds_in_pillar
    )
    items += (
        f'<span class="swatch miss" style="--miss:{MISSING_SWATCH_COLOR}"></span>'
        f'<span class="lab">{label_text}</span>'
    )
    st.markdown(
        """
        <style>
        .legend-inline{display:flex;flex-wrap:wrap;gap:.5rem 1rem;align-items:center;margin-top:.35rem;}
        .legend-inline .swatch{display:inline-block;width:12px;height:12px;border-radius:2px;margin-right:.35rem;}
        .legend-inline .lab{font-size:0.9rem;}
        .legend-inline .swatch.miss{
          background: var(--miss);
          opacity: .6;
          border: 1.5px dashed var(--miss);
          filter: url(#fizzyEdge);
        }
        @supports not (filter: url(#fizzyEdge)) {
          .legend-inline .swatch.miss{
            -webkit-mask-image: radial-gradient(circle at 50% 50%, #000 84%, transparent 88%);
                    mask-image: radial-gradient(circle at 50% 50%, #000 84%, transparent 88%);
          }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    st.markdown(f'<div class="legend-inline">{items}</div>', unsafe_allow_html=True)

def render_inline_legend(codes, colors):
    items = "".join(
        f'<span class="swatch" style="background:{colors[c]}"></span>'
        f'<span class="lab">{c}</span>'
        for c in codes
    )
    st.markdown(
        """
        <style>
        .legend-inline{display:flex;flex-wrap:wrap;gap:.5rem 1rem;align-items:center; margin-top:.35rem;}
        .legend-inline .swatch{display:inline-block;width:12px;height:12px;border-radius:2px;margin-right:.35rem;}
        .legend-inline .lab{font-size:0.9rem;}
        </style>
        """,
        unsafe_allow_html=True,
    )
    st.markdown(f'<div class="legend-inline">{items}</div>', unsafe_allow_html=True)

def render_section_header(title: str, codes):
    left, right = st.columns([1, 3])
    with left:
        st.subheader(title)
    with right:
        render_inline_legend(codes, STD_COLOR)
    st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)

MISSING_CODES = ["E_MISS", "S_MISS", "G_MISS"]
MISSING_COLOR = {
    "E_MISS": "#C2C2C2",
    "S_MISS": "#C2C2C2",
    "G_MISS": "#C2C2C2",
}

def pillar_color(p: str) -> str:
    if p == "E":
        return STD_COLOR.get("E1", "#0b7a28")
    if p == "S":
        return STD_COLOR.get("S1", "#8f1414")
    return STD_COLOR.get("G1", "#f2c744")

def missing_label_for_variant(pillar: str) -> str:
    base = {"E":"E — ", "S":"S — ", "G":"G — "}[pillar]
    return base + ("Not reported" if VARIANT == "v3" else "Missing")

def std_missing_label(std_code: str) -> str:
    return f"{std_code} — {'Not reported' if VARIANT=='v2' else 'Missing'}"

def _inject_fizzy_filter():
    st.markdown(
        """
        <svg width="0" height="0" style="position:absolute;left:-9999px;top:-9999px;">
          <defs>
            <filter id="fizzyEdge" x="-20%" y="-20%" width="140%" height="140%" color-interpolation-filters="sRGB">
              <feTurbulence type="fractalNoise" baseFrequency="0.9" numOctaves="2" seed="3" result="noise"/>
              <feDisplacementMap in="SourceGraphic" in2="noise" scale="4" xChannelSelector="R" yChannelSelector="G"/>
            </filter>
          </defs>
        </svg>
        """,
        unsafe_allow_html=True,
    )

def render_inline_legend_with_missing(codes, colors):
    _inject_fizzy_filter()
    items = "".join(
        f'<span class="swatch" style="background:{colors[c]}"></span>'
        f'<span class="lab">{c}</span>'
        for c in codes
    )
    miss_bits = []
    for p, code in zip(["E", "S", "G"], MISSING_CODES):
        base = MISSING_COLOR.get(code, pillar_color(p))
        miss_bits.append(
            f'<span class="swatch miss" style="--miss:{base}"></span>'
            f'<span class="lab">{missing_label_for_variant(p)}</span>'
        )
    items += "".join(miss_bits)

    st.markdown(
        """
        <style>
        .legend-inline{display:flex;flex-wrap:wrap;gap:.5rem 1rem;align-items:center;margin-top:.35rem;}
        .legend-inline .swatch{display:inline-block;width:12px;height:12px;border-radius:2px;margin-right:.35rem;}
        .legend-inline .lab{font-size:0.9rem;}
        .legend-inline .swatch.miss{
          background: var(--miss);
          opacity: .6;
          border: 1.5px dashed var(--miss);
          filter: url(#fizzyEdge);
        }
        @supports not (filter: url(#fizzyEdge)) {
          .legend-inline .swatch.miss{
            -webkit-mask-image: radial-gradient(circle at 50% 50%, #C2C2C2 84%, transparent 88%);
                    mask-image: radial-gradient(circle at 50% 50%, #C2C2C2 84%, transparent 88%);
          }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    st.markdown(f'<div class="legend-inline">{items}</div>', unsafe_allow_html=True)

def render_pillar_legend_with_missing(stds_in_pillar, colors, pillar):
    _inject_fizzy_filter()
    items = "".join(
        f'<span class="swatch" style="background:{colors[c]}"></span>'
        f'<span class="lab">{c}</span>'
        for c in stds_in_pillar
    )
    base = MISSING_COLOR[f"{pillar}_MISS"]
    items += (
        f'<span class="swatch miss" style="--miss:{base}"></span>'
        f'<span class="lab">{missing_label_for_variant(pillar)}</span>'
    )
    st.markdown(
        """
        <style>
        .legend-inline{display:flex;flex-wrap:wrap;gap:.5rem 1rem;align-items:center;margin-top:.35rem;}
        .legend-inline .swatch{display:inline-block;width:12px;height:12px;border-radius:2px;margin-right:.35rem;}
        .legend-inline .lab{font-size:0.9rem;}
        .legend-inline .swatch.miss{
          background: var(--miss);
          opacity: .6;
          border: 1.5px dashed var(--miss);
          filter: url(#fizzyEdge);
        }
        @supports not (filter: url(#fizzyEdge)) {
          .legend-inline .swatch.miss{
            -webkit-mask-image: radial-gradient(circle at 50% 50%, #000 84%, transparent 88%);
                    mask-image: radial-gradient(circle at 50% 50%, #000 84%, transparent 88%);
          }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    st.markdown(f'<div class="legend-inline">{items}</div>', unsafe_allow_html=True)

def friendly_col_label(comp_col: str) -> str:
    try:
        if comp_col == country_col:
            return "Country"
        if comp_col == sector_col:
            return "Sector"
        if comp_col == industry_col:
            return "Industry"
    except Exception:
        pass
    return str(comp_col)

def log_user_event(user_id: str, event: str, value: str = ""):
    if not SUPABASE_ENABLED or not supabase or not user_id:
        return False
    try:
        if not user_id.count('-') == 4:
            user_uuid = str(uuid.uuid5(uuid.NAMESPACE_DNS, user_id))
        else:
            user_uuid = user_id
        clean_event = str(event).strip()[:100]
        clean_value = str(value).strip()[:500] if value else ""
        data = {
            "user_id": user_uuid,
            "event": clean_event,
            "value": clean_value
        }
        result = supabase.table("log_drlists").insert(data).execute()
        return bool(result.data)
    except Exception:
        return False

def get_context_from_srnapi(document_id, query):
    pages = requests.get(
        f"https://api.srnav.com/documents/{document_id}/query",
        params={
            "document_id": document_id,
            "query": query,
            "top_k": 10
        }
    ).json()
    return "\n".join([x["content"] for x in pages])

# ========= YEAR HELPERS =========

def get_firm_years(df, firm_id_col, firm_name_col, firm_label, year_col):
    """Return sorted list of years available for this firm (descending)."""
    if year_col is None:
        return []
    try:
        if firm_name_col:
            mask = df[firm_name_col].astype(str) == str(firm_label)
        elif firm_id_col:
            mask = df[firm_id_col].astype(str) == str(firm_label)
        else:
            return []
        firm_df = df[mask]
        years = firm_df[year_col].dropna().astype(str).unique().tolist()
        # Sort descending (newest first)
        try:
            years = sorted(years, key=lambda y: float(y), reverse=True)
        except Exception:
            years = sorted(years, reverse=True)
        return years
    except Exception:
        return []

def get_current_row_for_year(df, firm_id_col, firm_name_col, firm_label, year_col, year_val):
    """Retrieve a row for a specific firm + year combination."""
    try:
        if firm_name_col:
            mask = df[firm_name_col].astype(str) == str(firm_label)
        elif firm_id_col:
            mask = df[firm_id_col].astype(str) == str(firm_label)
        else:
            return None
        if year_col:
            mask = mask & (df[year_col].astype(str) == str(year_val))
        result = df[mask]
        if len(result) == 0:
            return None
        return result.iloc[0]
    except Exception:
        return None

def is_yes_val(v) -> bool:
    """Check if a (possibly numeric) value represents 'yes' / reported."""
    if pd.isna(v):
        return False
    try:
        return float(v) == 1.0
    except (ValueError, TypeError):
        return str(v).strip().lower() in YES_SET

def col_to_dr_code(col: str) -> str:
    """Convert compact Stata column name to ESRS DR code.
    e.g. e11 -> E1-1, s117 -> S1-17, g16 -> G1-6
    """
    import re
    m = re.match(r'^([ESGesg])(\d)(\d+)(?:_.*)?$', col)
    if m:
        pillar = m.group(1).upper()
        std    = m.group(2)
        dr     = str(int(m.group(3)))
        return f"{pillar}{std}-{dr}"
    return col

def keep_latest_year(df: pd.DataFrame, firm_name_col, firm_id_col, year_col) -> pd.DataFrame:
    """Keep only the most recent year's row per firm."""
    if year_col is None:
        return df
    id_col = firm_name_col if firm_name_col else firm_id_col
    if id_col is None:
        return df
    try:
        df = df.copy()
        df[year_col] = pd.to_numeric(df[year_col], errors="coerce")
        idx = df.groupby(id_col)[year_col].idxmax()
        return df.loc[idx].reset_index(drop=True)
    except Exception:
        return df
        
# ========= LOAD DATA =========
df = load_table(DEFAULT_DATA_URL)
if df.empty:
    st.stop()

# Detect columns early so we can normalize ESG columns
esg_columns_raw = [c for c in df.columns if isinstance(c, str) and c[:1] in ("E", "S", "G", "e", "s", "g")
                   and "-" in c]
df = normalize_esg_columns(df, esg_columns_raw)

df_latest = keep_latest_year(df, 
    first_present(df.columns, FIRM_NAME_COL_CANDIDATES),
    first_present(df.columns, FIRM_ID_COL_CANDIDATES),
    first_present(df.columns, YEAR_COL_CANDIDATES)
)

user_qp = read_query_param("user", None)

# --- Variant switcher ---
st.sidebar.caption(f"Variant: **{VARIANT.upper()}**")

try:
    new_variant = st.sidebar.segmented_control(
        "View style",
        options=VARIANT_KEYS,
        default=VARIANT,
        format_func=lambda x: x.upper(),
    )
except Exception:
    new_variant = st.sidebar.radio(
        "View style",
        options=VARIANT_KEYS,
        index=VARIANT_KEYS.index(VARIANT),
        format_func=lambda x: x.upper(),
        horizontal=True,
    )

if new_variant != VARIANT:
    VARIANT = new_variant
    st.session_state["variant"] = VARIANT
    if user_qp:
        log_user_event(user_qp, "variant_changed", new_variant)
    try:
        st.query_params.update({"v": VARIANT})
    except Exception:
        cur = st.experimental_get_query_params()
        cur["v"] = VARIANT
        st.experimental_set_query_params(**cur)
    st.rerun()


# ========= DETECT COLUMNS =========
firm_name_col = first_present(df.columns, FIRM_NAME_COL_CANDIDATES)
firm_id_col   = first_present(df.columns, FIRM_ID_COL_CANDIDATES)
country_col   = first_present(df.columns, COUNTRY_COL_CANDIDATES)
industry_col  = first_present(df.columns, INDUSTRY_COL_CANDIDATES)
sector_col    = first_present(df.columns, SECTOR_COL_CANDIDATES)
year_col      = first_present(df.columns, YEAR_COL_CANDIDATES)

# Read URL params
firm_qp  = read_query_param("firm", None)
comp_qp  = (read_query_param("comp", "none") or "none").lower()
peers_qp = read_query_param("peers", "")
mode_qp  = (read_query_param("mode", "charts") or "charts").lower()
preselected_peers = [p for p in peers_qp.split(",") if p] if peers_qp else []

LANDING_MD = """
### Welcome to the SRN Disclosure Requirements Dashboard!

Use this dashboard to explore the **Disclosure Requirements (DR)** that companies report under the European Sustainability Reporting Standards (ESRS). Each standard is organized into disclosure requirements, which specify the data points companies have to disclose for topics they identify as material (e.g., ESRS 1.44 (a): Gross Scope 1 GHG emissions).

"""

# ========= FIRM PICKER =========
st.sidebar.subheader("Firm Selection")

selected_country = "All"
if country_col:
    countries = ["All"] + sorted(df[country_col].dropna().astype(str).unique().tolist())
    prev_country = st.session_state.get("selected_country", "All")
    selected_country = st.sidebar.selectbox("Filter by Country", countries, index=0)
    if selected_country != prev_country:
        if user_qp:
            log_user_event(user_qp, "country_filter_changed", selected_country)
        st.session_state["selected_country"] = selected_country

selected_sector = "All"
if sector_col:
    sectors = ["All"] + sorted(df[sector_col].dropna().astype(str).unique().tolist())
    prev_sector = st.session_state.get("selected_sector", "All")
    selected_sector = st.sidebar.selectbox("Filter by Sector", sectors, index=0)
    if selected_sector != prev_sector:
        if user_qp:
            log_user_event(user_qp, "sector_filter_changed", selected_sector)
        st.session_state["selected_sector"] = selected_sector

filtered_df = df.copy()
if selected_country != "All":
    filtered_df = filtered_df[filtered_df[country_col].astype(str) == selected_country]
if selected_sector != "All":
    filtered_df = filtered_df[filtered_df[sector_col].astype(str) == selected_sector]

if firm_name_col:
    firms = filtered_df[firm_name_col].dropna().astype(str).unique().tolist()
    default_index = firms.index(firm_qp) if (firm_qp in firms) else None
    try:
        firm_label = st.sidebar.selectbox("Firm", firms, index=default_index, placeholder="Select a firm…")
    except TypeError:
        options = ["— Select firm —"] + firms
        idx = 0 if firm_qp is None else (options.index(firm_qp) if firm_qp in options else 0)
        firm_label = st.sidebar.selectbox("Firm", options, index=idx)
        if firm_label == "— Select firm —":
            st.stop()
    if not firm_label:
        st.markdown(LANDING_MD)
        st.info("Select a firm on the left to see which Disclosure Requirements it includes in its report.")
        st.stop()
    current_row = filtered_df[filtered_df[firm_name_col].astype(str) == str(firm_label)].iloc[0]
    if user_qp:
        log_user_event(user_qp, "firm_selected", str(firm_label))
elif firm_id_col:
    firms = filtered_df[firm_id_col].dropna().astype(str).unique().tolist()
    default_index = firms.index(firm_qp) if (firm_qp in firms) else None
    try:
        firm_label = st.sidebar.selectbox("Firm (ID)", firms, index=default_index, placeholder="Select a firm…")
    except TypeError:
        options = ["— Select firm —"] + firms
        idx = 0 if firm_qp is None else (options.index(firm_qp) if firm_qp in options else 0)
        firm_label = st.sidebar.selectbox("Firm (ID)", options, index=idx)
        if firm_label == "— Select firm —":
            st.markdown(LANDING_MD)
            st.info("Select a firm from the sidebar to view details.")
            st.stop()
    if not firm_label:
        st.markdown(LANDING_MD)
        st.info("Select a firm from the sidebar to view details.")
        st.stop()
    current_row = filtered_df[filtered_df[firm_id_col].astype(str) == str(firm_label)].iloc[0]
    if user_qp:
        log_user_event(user_qp, "firm_selected", str(firm_label))
else:
    st.error("No firm identifier column found (looked for: name/company/firm or isin/ticker).")
    st.stop()

# ========= YEAR HANDLING =========
# Determine which years are available for the selected firm
firm_years = get_firm_years(df, firm_id_col, firm_name_col, firm_label, year_col)

# Determine current year and prior year
if firm_years:
    # newest year available = "current year" shown by default
    current_year = firm_years[0]
    prior_year = firm_years[1] if len(firm_years) > 1 else None
    # If we have multiple years, get the current_row for the most recent year
    current_row_for_year = get_current_row_for_year(
        df, firm_id_col, firm_name_col, firm_label, year_col, current_year
    )
    if current_row_for_year is not None:
        current_row = current_row_for_year
else:
    current_year = None
    prior_year = None

prior_year_row = None
if prior_year is not None:
    prior_year_row = get_current_row_for_year(
        df, firm_id_col, firm_name_col, firm_label, year_col, prior_year
    )

# ========= ESG STRUCTURE =========
esg_columns = [c for c in df.columns if isinstance(c, str) and c[:1] in ("E", "S", "G", "e", "s", "g") 
               and "-" in c and "_phase_in" not in c and "fully_phased" not in c]
groups, by_pillar = build_hierarchy(esg_columns)
# ========= HEADER =========
st.title(str(firm_label))
isin_txt     = f"ISIN: <strong>{current_row.get(firm_id_col, 'n/a')}</strong>" if firm_id_col else ""
country_txt  = f"Country: <strong>{current_row.get(country_col, 'n/a')}</strong>" if country_col else ""
sector_txt   = f"Sector: <strong>{current_row[sector_col] if sector_col and sector_col in current_row.index and pd.notna(current_row[sector_col]) else 'n/a'}</strong>" if sector_col else ""

industry_txt = f"Industry: <strong>{current_row.get(industry_col, 'n/a')}</strong>" if industry_col else ""
year_txt     = f"Year: <strong>{current_year}</strong>" if current_year else ""
sub = " · ".join([t for t in [isin_txt, country_txt, sector_txt, industry_txt, year_txt] if t])
if sub:
    st.markdown(f"<div class='firm-meta'>{sub}</div>", unsafe_allow_html=True)

# ====== REPORT BUTTON + AUDITOR POPOVER ======
#link_sr = str(current_row.get("Link_SR", "")).strip()
#link_ar = str(current_row.get("Link_AR", "")).strip()
link_sr = str(current_row.get("Report Link", "")).strip()
link_ar = ""

def _valid_url(u: str) -> bool:
    try:
        return u.lower().startswith(("http://", "https://"))
    except Exception:
        return False

link_url = link_sr if _valid_url(link_sr) else (link_ar if _valid_url(link_ar) else "")

aud_col = "auditor"
auditor_val = ""
if aud_col in df.columns:
    v = current_row.get(aud_col, "")
    auditor_val = "" if (pd.isna(v)) else str(v).strip()

btn_col1, btn_col2, btn_col3, btn_col4 = st.columns([1, 1, 2, 1])

st.markdown("""
<style>
.stButton > button, .stLinkButton > a {
  width: 100%;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
</style>
""", unsafe_allow_html=True)

with btn_col1:
    if _valid_url(link_url):
        st.link_button("Open firm report", link_url, help="Open the firm's report in a new tab")
    else:
        if st.button("Open firm report"):
            try:
                st.toast("No report link available yet.", icon="ℹ️")
            except Exception:
                st.info("No report link available yet.")

with btn_col2:
    try:
        with st.popover("Show auditor"):
            st.markdown(f"**Auditor:** {auditor_val or '—'}")
    except Exception:
        if st.button("Show auditor"):
            st.info(f"Auditor: {auditor_val or '—'}")

with btn_col3:
    prompt = st.chat_input("Query and search the company's report with AI")
    if prompt:
        with st.spinner():
            context = get_context_from_srnapi(current_row.get('document_id'), prompt)
            with st.expander("AI chatbot", expanded=True):
                with st.chat_message("user"):
                    st.text(prompt)
                with st.chat_message("assistant"):
                    st.write_stream(
                        openai.chat.completions.create(
                            model="gpt-4.1",
                            messages=[
                                {"role": "system", "content": "You are an expert in gathering information from sustainability reports."},
                                {"role": "user", "content": f"The user asks you the following question {prompt}. Use the following context from the sustainability report to answer the question."},
                                {"role": "user", "content": context},
                                {"role": "user", "content": "Be concise and provide the most relevant information from the texts only. Do not use the internet or general knowledge."},
                            ],
                            stream=True
                        )
                    )

with btn_col4:
    if st.session_state.get("show_prior_year", False) and prior_year_row is not None:
        prior_link = str(prior_year_row.get("original_link", "")).strip()
        if _valid_url(prior_link):
            st.link_button(f"Open {prior_year} report", prior_link)
            
tab_dr, = st.tabs(["Overview"])


# ========= NAV & COMPARISON =========
valid_views = ["Total", "E", "S", "G", "Text characteristics"]
current_view = read_query_param("view", "Total")
if current_view == "Combined":
    current_view = "Total"
if current_view not in valid_views:
    current_view = "Total"

st.sidebar.subheader("Section")
view = st.sidebar.radio("Section", valid_views, index=valid_views.index(current_view), label_visibility="collapsed")

# ── Comparison heading ────────────────────────────────────────────────────────
st.sidebar.subheader("Comparison")

# Prior year checkbox — directly under Comparison heading
has_prior_year = (prior_year is not None and prior_year_row is not None)

if not year_col:
    show_prior_year = False
elif has_prior_year:
    show_prior_year = st.sidebar.checkbox(
    f"Compare with prior year ({prior_year})",
    value=False,
    key="show_prior_year",  # <-- add this
    help=f"Add a row showing {prior_year} data alongside {current_year}",
)
else:
    _next_year = str(int(current_year) + 1) if (current_year and str(current_year).isdigit()) else "next year"
    st.sidebar.checkbox(
        "Compare with prior year",
        value=False,
        disabled=True,
        help=f"{_next_year} not yet available",
    )
    show_prior_year = False

# Peer firms selectbox — label size matches "Filter by Country"
comp_options = ["No comparison", "Index", "Sector", "Custom peers"]
comp_default_label = PARAM_TO_COMP.get(comp_qp, "No comparison")
if comp_default_label not in comp_options:
    comp_default_label = "No comparison"
comparison = st.sidebar.selectbox("Peer firms", comp_options, index=comp_options.index(comp_default_label))
selected_peer_index = None
if comparison == "Index":
    selected_peer_index = st.sidebar.radio(
        "Index",
        ["DAX40", "EuroStoxx50"],
        horizontal=True,
        label_visibility="collapsed",
    )
if comparison == "Country" and not country_col:
    st.sidebar.info("No country column found; comparison will be disabled.")
if comparison == "Sector" and not sector_col:
    st.sidebar.info("No sector column found; comparison will be disabled.")


# ── Peer firm list ─────────────────────────────────────────────────────────────
label_col = firm_name_col if firm_name_col else firm_id_col

# Custom peers multiselect (only shown when Custom peers is selected)
selected_custom_peers = []
if comparison == "Custom peers" and label_col:
    all_firms = df[label_col].dropna().astype(str).unique().tolist()
    try:
        all_firms = [f for f in all_firms if str(f) != str(current_row.get(label_col, ""))]
    except Exception:
        pass
    default_peers = [p for p in preselected_peers if p in all_firms]
    selected_custom_peers = st.sidebar.multiselect("Custom peers (max 4)", all_firms, default=default_peers)
    if len(selected_custom_peers) > 4:
        st.sidebar.warning("Using only the first 4 selected peers.")
        selected_custom_peers = selected_custom_peers[:4]

_peers_df, _n_peers, _peer_note = (None, 0, "")
if comparison == "Country" and country_col:
    _peers_df, _n_peers, _peer_note = build_peers(df_latest, country_col, current_row)
elif comparison == "Index" and "dax40" in df.columns:
    if selected_peer_index == "DAX40":
        _peers_df = df_latest[df_latest["dax40"].astype(str).isin(["1", "1.0", "True", "true"])].copy()
    else:
        _peers_df = df_latest[df_latest["es50"].astype(str).isin(["1", "1.0", "True", "true"])].copy()
    try:
        _peers_df = _peers_df.drop(current_row.name, errors="ignore")
    except Exception:
        pass
    _n_peers = len(_peers_df)
    _peer_note = f" (Index = {selected_peer_index}, n={_n_peers})"
elif comparison == "Sector" and sector_col:
    _peers_df, _n_peers, _peer_note = build_peers(df_latest, sector_col, current_row)
elif comparison == "Industry" and industry_col:
    _peers_df, _n_peers, _peer_note = build_peers(df_latest, industry_col, current_row)
elif comparison == "Custom peers":
    _peers_df, _n_peers, _peer_note = build_custom_peers(df_latest, label_col, selected_custom_peers, current_row)
    
show_peer_list = False
if comparison != "No comparison":
    show_peer_list = st.sidebar.checkbox("Show peer firm list", value=False)

if show_peer_list:
    if _n_peers == 0 or _peers_df is None or _peers_df.empty:
        st.sidebar.info("No peers to display for the current selection.")
    else:
        _name_col = label_col
        _cols = []
        _ren = {}
        for src, dst in [
            (_name_col, "Name"),
            (country_col, "Country"),
            (sector_col, "Sector"),
            (industry_col, "Industry"),
        ]:
            if src and src in _peers_df.columns:
                _cols.append(src)
                _ren[src] = dst

        _view = _peers_df[_cols].rename(columns=_ren).drop_duplicates().copy()
        st.sidebar.caption(f"Peers shown: {len(_view)}{_peer_note}")
        st.sidebar.dataframe(_view, use_container_width=True, hide_index=True, height=300)

mode_options = ["Charts", "Tables"]
mode_default_index = 0 if mode_qp == "charts" else 1
display_mode = st.sidebar.radio("Display", mode_options, index=mode_default_index)

X_TITLE = "Number of reported Disclosure Requirements"

params = {
    "view": view,
    "firm": str(firm_label),
    "comp": COMP_TO_PARAM.get(comparison, "none"),
    "mode": "charts" if display_mode == "Charts" else "tables",
    "v": VARIANT,
}
if COMP_TO_PARAM.get(comparison) == "custom" and selected_custom_peers:
    params["peers"] = ",".join(selected_custom_peers)
set_query_params(**params)

def link_for(pillar_key: str) -> str:
    qp = {
        "view": pillar_key,
        "firm": str(firm_label),
        "comp": COMP_TO_PARAM.get(comparison, "none"),
        "mode": "charts" if display_mode == "Charts" else "tables",
    }
    if COMP_TO_PARAM.get(comparison) == "custom" and selected_custom_peers:
        qp["peers"] = ",".join(selected_custom_peers)
    return "?" + urlencode(qp)


# ========= UTILITY: build series list including prior year =========

def build_series_rows_for_std(std_code, metrics_in_group, current_row, prior_year_row, 
                               peers, n_peers, firm_series, peers_series,
                               prior_label=None, show_prior=False):
    """
    Return a list of row dicts for a single standard, covering:
    - Firm (current year)
    - Firm prior year (if show_prior and prior_year_row is not None)
    - Peers mean (if n_peers > 0)
    Applies numeric 1/0 comparison (from normalized columns).
    """
    rows = []
    label = SHORT_ESRS_LABELS.get(std_code, std_code)

    # Current year firm
    vals = pd.to_numeric(current_row[metrics_in_group], errors="coerce")
    firm_yes = int((vals == 1).sum())
    rows.append({"StdCode": std_code, "Standard": label, "Series": firm_series, "Value": float(firm_yes)})

    # Prior year firm
    if show_prior and prior_year_row is not None and prior_label:
        pvals = pd.to_numeric(prior_year_row[metrics_in_group], errors="coerce")
        prior_yes = int((pvals == 1).sum())
        rows.append({"StdCode": std_code, "Standard": label, "Series": prior_label, "Value": float(prior_yes)})

    # Peers
    if n_peers > 0 and peers is not None and peers_series:
        present_cols = [m for m in metrics if m in df.columns and "_phase_in" not in m and "fully_phased" not in m]
        if present_cols:
            peer_block = pd.to_numeric(peers[present_cols].stack(), errors="coerce").unstack()
            peer_yes_mean = float((peer_block == 1).sum(axis=1).mean())
        else:
            peer_yes_mean = 0.0
        rows.append({"StdCode": std_code, "Standard": label, "Series": peers_series, "Value": float(peer_yes_mean)})

    return rows, firm_yes

# ========= COMBINED VIEW =========
with tab_dr:
    if view == "Total":
        comp_col = None
        comp_label = None
        peers = None
        n_peers = 0
        peer_note = ""

        if comparison == "Country" and country_col:
            comp_col = country_col
            comp_label = "Country mean"
            peers, n_peers, peer_note = build_peers(df, comp_col, current_row)
        elif comparison == "Index" and "dax40" in df.columns:
            comp_label = "Index mean"
            if selected_peer_index == "DAX40":
                peers = df_latest[df_latest["dax40"].astype(str).isin(["1", "1.0", "True", "true"])].copy()
            elif selected_peer_index == "EuroStoxx50":
                peers = df_latest[df_latest["es50"].astype(str).isin(["1", "1.0", "True", "true"])].copy()
            else:
                peers = pd.DataFrame()
            try:
                peers = peers.drop(current_row.name, errors="ignore")
            except Exception:
                pass
            n_peers = len(peers)
            peer_note = f" (Index = {selected_peer_index}, n={n_peers})"

        elif comparison == "Sector" and sector_col:
            comp_col = sector_col
            comp_label = "Sector mean"
            peers, n_peers, peer_note = build_peers(df_latest, comp_col, current_row)
        elif comparison == "Industry" and industry_col:
            comp_col = industry_col
            comp_label = "industry mean"
            peers, n_peers, peer_note = build_peers(df_latest, comp_col, current_row)
        elif comparison == "Custom peers":
            comp_label = "Custom"
            peers, n_peers, peer_note = build_custom_peers(df_latest, label_col, selected_custom_peers, current_row)
        firm_series = f"Firm ({current_year})" if current_year else "Firm"
        prior_label = f"Firm ({prior_year})" if (show_prior_year and prior_year) else None
        comp_label_short = (comp_label or "").replace(" mean", "") if comp_label else None
        peers_series = f"Mean: {comp_label_short}" if comp_label_short else None


        if display_mode == "Tables":
            summary_rows = []
            for pillar in ["E", "S", "G"]:
                pcols = pillar_columns(pillar, groups, by_pillar)
                total_DR = len(pcols)

                if total_DR:
                    vals = pd.to_numeric(current_row[pcols], errors="coerce")
                    firm_yes = int((vals == 1).sum())

                    prior_yes = None
                    if show_prior_year and prior_year_row is not None:
                        pvals = pd.to_numeric(prior_year_row[pcols], errors="coerce")
                        prior_yes = int((pvals == 1).sum())

                    if n_peers > 0:
                        peer_block = pd.to_numeric(peers[pcols].stack(), errors="coerce").unstack()
                        peer_yes_mean = float((peer_block == 1).sum(axis=1).mean()) if len(peer_block) else None
                    else:
                        peer_yes_mean = None
                else:
                    firm_yes = 0
                    prior_yes = None
                    peer_yes_mean = None

                if VARIANT == "v3":
                    row = {
                        "Pillar": PILLAR_LABEL[pillar],
                        "Reported disclosure requirements": firm_yes,
                        "Not reported disclosure requirements": max(total_DR - firm_yes, 0),
                        "Total disclosure requirements": total_DR,
                    }
                    if prior_yes is not None:
                        row[f"Prior year ({prior_year}) reported"] = prior_yes
                    if peer_yes_mean is not None:
                        row[f"Peers — mean reported ({comp_label})"] = round(peer_yes_mean, 1)
                elif VARIANT == "v2":
                    row = {
                        "Pillar": PILLAR_LABEL[pillar],
                        "Firm — number of reported Disclosure Requirements": firm_yes,
                        "Total disclosure requirements": total_DR,
                    }
                    if prior_yes is not None:
                        row[f"Prior year ({prior_year}) reported"] = prior_yes
                    if peer_yes_mean is not None:
                        row[f"Peers — mean reported ({comp_label})"] = round(peer_yes_mean, 1)
                else:  # v1
                    row = {
                        "Pillar": PILLAR_LABEL[pillar],
                        "Firm — number of reported Disclosure Requirements": firm_yes,
                    }
                    if prior_yes is not None:
                        row[f"Prior year ({prior_year}) reported"] = prior_yes
                    if peer_yes_mean is not None:
                        row[f"Peers — mean number of reported Disclosure Requirements ({comp_label})"] = round(peer_yes_mean, 1)

                summary_rows.append(row)

            tbl = pd.DataFrame(summary_rows)
            st.subheader("Total overview")
            st.dataframe(tbl, use_container_width=True, hide_index=True)

            if VARIANT == "v3":
                note_txt = "Rows show reported, not reported, and total DRs per pillar."
            elif VARIANT == "v2":
                note_txt = "Rows show the firm's reported DRs and the pillar's total."
            else:
                note_txt = "Rows show the number of reported Disclosure Requirements per pillar."
            if n_peers > 0:
                note_txt += peer_note
            st.caption(note_txt)

        else:
            # === Charts mode ===
            perstd_rows = []
            pillar_reported  = {"E": 0, "S": 0, "G": 0}
            pillar_total     = {"E": 0, "S": 0, "G": 0}
            pillar_peers_rep = {"E": 0.0, "S": 0.0, "G": 0.0}
            pillar_prior_rep = {"E": 0, "S": 0, "G": 0}

            for std_code in STD_ORDER:
                if std_code not in groups:
                    continue
                metrics_in_group = groups[std_code]
                label = SHORT_ESRS_LABELS.get(std_code, std_code)
                pillar = std_code[0]

                vals = pd.to_numeric(current_row[metrics_in_group], errors="coerce")
                firm_yes = int((vals == 1).sum())
                pillar_reported[pillar] += firm_yes
                pillar_total[pillar]    += len(metrics_in_group)

                perstd_rows.append({"StdCode": std_code, "Standard": label, "Series": firm_series, "Value": float(firm_yes)})

                # Prior year
                if show_prior_year and prior_year_row is not None and prior_label:
                    pvals = pd.to_numeric(prior_year_row[metrics_in_group], errors="coerce")
                    prior_yes = int((pvals == 1).sum())
                    pillar_prior_rep[pillar] += prior_yes
                    perstd_rows.append({"StdCode": std_code, "Standard": label, "Series": prior_label, "Value": float(prior_yes)})

                if n_peers > 0:
                    present_cols = [m for m in metrics_in_group if m in peers.columns]
                    if present_cols:
                        peer_block = pd.to_numeric(peers[present_cols].stack(), errors="coerce").unstack()
                        if len(peer_block) > 0 and peers_series is not None:
                            peer_yes_mean = float((peer_block == 1).sum(axis=1).mean())
                            perstd_rows.append({
                                "StdCode": std_code, "Standard": label,
                                "Series": peers_series, "Value": float(peer_yes_mean)
                            })
                            pillar_peers_rep[pillar] += float(peer_yes_mean)

            # Missing segments for v2/v3
            if VARIANT in ("v2", "v3"):
                miss_vals_firm = {
                    "E_MISS": max(pillar_total["E"] - pillar_reported["E"], 0),
                    "S_MISS": max(pillar_total["S"] - pillar_reported["S"], 0),
                    "G_MISS": max(pillar_total["G"] - pillar_reported["G"], 0),
                }
                for code, val in miss_vals_firm.items():
                    if val > 0:
                        p = code[0]
                        perstd_rows.append({
                            "StdCode": code,
                            "Standard": missing_label_for_variant(p),
                            "Series": firm_series,
                            "Value": float(val),
                        })

                if show_prior_year and prior_year_row is not None and prior_label:
                    miss_vals_prior = {
                        "E_MISS": max(pillar_total["E"] - pillar_prior_rep["E"], 0),
                        "S_MISS": max(pillar_total["S"] - pillar_prior_rep["S"], 0),
                        "G_MISS": max(pillar_total["G"] - pillar_prior_rep["G"], 0),
                    }
                    for code, val in miss_vals_prior.items():
                        if val > 0:
                            p = code[0]
                            perstd_rows.append({
                                "StdCode": code,
                                "Standard": missing_label_for_variant(p),
                                "Series": prior_label,
                                "Value": float(val),
                            })

                if n_peers > 0 and peers_series:
                    miss_vals_peers = {
                        "E_MISS": max(pillar_total["E"] - pillar_peers_rep["E"], 0.0),
                        "S_MISS": max(pillar_total["S"] - pillar_peers_rep["S"], 0.0),
                        "G_MISS": max(pillar_total["G"] - pillar_peers_rep["G"], 0.0),
                    }
                    for code, val in miss_vals_peers.items():
                        if val > 1e-9:
                            p = code[0]
                            perstd_rows.append({
                                "StdCode": code,
                                "Standard": missing_label_for_variant(p),
                                "Series": peers_series,
                                "Value": float(val),
                            })

            chart_df = pd.DataFrame(perstd_rows) if perstd_rows else pd.DataFrame(columns=["StdCode","Standard","Series","Value","StdRank"])
            custom_order = ["E1","E2","E3","E4","E5","E_MISS","S1","S2","S3","S4","S_MISS","G1","G_MISS"]
            rank_map = {c:i for i,c in enumerate(custom_order)}
            if not chart_df.empty:
                chart_df["StdRank"] = chart_df["StdCode"].map(lambda c: rank_map.get(c, 9999))

            if not chart_df.empty:
                present_codes = [c for c in STD_ORDER if (chart_df["StdCode"] == c).any()]
            else:
                present_codes = STD_ORDER

            render_section_header("Total overview", [])
            if chart_df.empty:
                st.info("No matching ESG columns found in the data for this firm. Check that column names follow the E1-1, S1-1, G1-1 format.")
            else:
                if VARIANT == "v3":
                    render_inline_legend_with_single_missing(present_codes, STD_COLOR)
                else:
                    render_inline_legend(present_codes, STD_COLOR)

            if not chart_df.empty:
                color_domain = present_codes + [c for c in MISSING_CODES if (chart_df["StdCode"] == c).any()]
                color_range = [
                    STD_COLOR[c] if c in STD_COLOR else MISSING_COLOR.get(c, "#cccccc")
                    for c in color_domain
                ]
                # y sort: current firm first, then prior year, then peers
                y_sort = [firm_series]
                if show_prior_year and prior_label:
                    y_sort.append(prior_label)
                if peers_series:
                    y_sort.append(peers_series)

                base = alt.Chart(chart_df)

                sep_rules = (
                    alt.Chart(chart_df)
                    .transform_calculate(
                        pillar="substring(datum.StdCode, 0, 1)",
                        pr="substring(datum.StdCode, 0, 1) == 'E' ? 1 : (substring(datum.StdCode, 0, 1) == 'S' ? 2 : 3)"
                    )
                    .transform_aggregate(
                        pillar_sum="sum(Value)",
                        groupby=["Series", "pillar", "pr"]
                    )
                    .transform_window(
                        cum="sum(pillar_sum)",
                        sort=[alt.SortField(field="pr", order="ascending")],
                        groupby=["Series"]
                    )
                    .mark_rule(stroke="black", strokeWidth=1.5)
                    .encode(
                        x=alt.X("cum:Q"),
                        y=alt.Y("Series:N", sort=y_sort, title="", bandPosition=0),
                        y2=alt.Y2("Series:N", bandPosition=1),
                        tooltip=[alt.Tooltip("Series:N", title="Series")]
                    )
                )

                missing_present = [c for c in MISSING_CODES if (chart_df["StdCode"] == c).any()]

                if missing_present:
                    is_missing = alt.FieldOneOfPredicate(field="StdCode", oneOf=missing_present)
                    bars = (
                        base
                        .mark_bar()
                        .encode(
                            y=alt.Y("Series:N", title="", sort=y_sort,
                                    scale=alt.Scale(paddingInner=0.25, paddingOuter=0.25)),
                            x=alt.X("Value:Q", title=X_TITLE, stack="zero"),
                            color=alt.Color("StdCode:N",
                                            scale=alt.Scale(domain=color_domain, range=color_range),
                                            legend=None),
                            order=alt.Order("StdRank:Q"),
                            opacity=alt.condition(is_missing, alt.value(0.6), alt.value(1.0)),
                            stroke=alt.condition(
                                is_missing,
                                alt.Color("StdCode:N", scale=alt.Scale(domain=color_domain, range=color_range)),
                                alt.value(None)
                            ),
                            strokeDash=alt.condition(is_missing, alt.value([3, 2]), alt.value([0, 0])),
                            strokeWidth=alt.condition(is_missing, alt.value(1.5), alt.value(0)),
                            strokeOpacity=alt.condition(is_missing, alt.value(1.0), alt.value(0.0)),
                            tooltip=[
                                alt.Tooltip("Series:N", title="Series"),
                                alt.Tooltip("Standard:N", title="Segment"),
                                alt.Tooltip("Value:Q", title="# DR", format=".1f"),
                            ],
                        )
                    )
                else:
                    bars = (
                        base
                        .mark_bar()
                        .encode(
                            y=alt.Y("Series:N", title="", sort=y_sort,
                                    scale=alt.Scale(paddingInner=0.25, paddingOuter=0.25)),
                            x=alt.X("Value:Q", title=X_TITLE, stack="zero"),
                            color=alt.Color("StdCode:N",
                                            scale=alt.Scale(domain=color_domain, range=color_range),
                                            legend=None),
                            order=alt.Order("StdRank:Q"),
                            opacity=alt.value(1.0),
                            stroke=alt.value(None),
                            strokeDash=alt.value([0, 0]),
                            strokeWidth=alt.value(0),
                            strokeOpacity=alt.value(0.0),
                            tooltip=[
                                alt.Tooltip("Series:N", title="Series"),
                                alt.Tooltip("Standard:N", title="Segment"),
                                alt.Tooltip("Value:Q", title="# DR", format=".1f"),
                            ],
                        )
                    )

                if VARIANT == "v3" and missing_present:
                    is_missing = alt.FieldOneOfPredicate(field="StdCode", oneOf=missing_present)
                    miss_word = "not reported"

                    def _make_total_labels(source_df, series_val, sort_field="StdRank"):
                        base = (
                            alt.Chart(source_df)
                            .transform_filter(alt.FieldEqualPredicate(field="Series", equal=series_val))
                            .transform_window(
                                cum="sum(Value)",
                                sort=[alt.SortField(field=sort_field, order="ascending")],
                                groupby=["Series"]
                            )
                            .transform_calculate(
                                prev="datum.cum - datum.Value",
                                mid="datum.prev + datum.Value/2",
                                pillar="substring(datum.StdCode, 0, 1)",
                                denom="datum.pillar == 'E' ? 32 : (datum.pillar == 'S' ? 32 : 6)",
                                pct="datum.denom > 0 ? datum.Value / datum.denom : 0",
                                pct_label="format(datum.pct, '.1%')"
                            )
                            .transform_filter(is_missing)
                            .transform_filter("datum.Value > 0 && datum.denom > 0")
                        )
                        t_pct = (
                            base
                            .mark_text(align="center", baseline="middle", fontSize=11, color="#333", dy=-5)
                            .encode(y=alt.Y("Series:N", title="", sort=y_sort,
                                            scale=alt.Scale(paddingInner=0.25, paddingOuter=0.25)),
                                    x=alt.X("mid:Q"),
                                    text="pct_label:N")
                        )
                        t_miss = (
                            base
                            .mark_text(align="center", baseline="middle", fontSize=10, color="#333", dy=6)
                            .encode(y=alt.Y("Series:N", title="", sort=y_sort,
                                            scale=alt.Scale(paddingInner=0.25, paddingOuter=0.25)),
                                    x=alt.X("mid:Q"),
                                    text=alt.value(miss_word))
                        )
                        return t_pct, t_miss

                    text_pct, text_missing = _make_total_labels(chart_df, firm_series)

                    extra_layers = []
                    if show_prior_year and prior_label:
                        prior_text_pct, prior_text_missing = _make_total_labels(chart_df, prior_label)
                        extra_layers = [prior_text_pct, prior_text_missing]

                    fig = alt.layer(bars, sep_rules, text_pct, text_missing, *extra_layers).properties(
                        height=alt.Step(56), width="container",
                        padding={"left": 12, "right": 12, "top": 6, "bottom": 6},
                    ).configure_view(stroke=None)
                else:
                    fig = alt.layer(bars, sep_rules).properties(
                        height=alt.Step(56), width="container",
                        padding={"left": 12, "right": 12, "top": 6, "bottom": 6},
                    ).configure_view(stroke=None)

                st.altair_chart(fig, use_container_width=True)

                note = "Bars show total counts of reported Disclosure Requirements, stacked by standard (E1–E5, S1–S4, G1)."
                if show_prior_year and prior_label:
                    note += f" Prior year ({prior_year}) shown for comparison."
                if n_peers > 0:
                    note += peer_note
                st.caption(note)


    def render_pillar(pillar: str, title: str, comparison: str, display_mode: str):
        pillar_groups = by_pillar.get(pillar, [])
        if not pillar_groups:
            st.info(f"No {pillar} columns found.")
            return

        comp_col = None
        comp_label = None
        peers, n_peers, note = (None, 0, "")
        if comparison == "Country" and country_col:
            comp_col, comp_label = country_col, "country"
            peers, n_peers, note = build_peers(df_latest, comp_col, current_row)
        elif comparison == "Index" and "dax40" in df.columns:
            comp_label = "index"
            if selected_peer_index == "DAX40":
                peers = df_latest[df_latest["dax40"].astype(str).isin(["1", "1.0", "True", "true"])].copy()
            elif selected_peer_index == "EuroStoxx50":
                peers = df_latest[df_latest["es50"].astype(str).isin(["1", "1.0", "True", "true"])].copy()
            else:
                peers = pd.DataFrame()
            try:
                peers = peers.drop(current_row.name, errors="ignore")
            except Exception:
                pass
            n_peers = len(peers)
            note = f" (Index = {selected_peer_index}, n={n_peers})"
        elif comparison == "Sector" and sector_col:
            comp_col, comp_label = sector_col, "sector"
            peers, n_peers, note = build_peers(df_latest, comp_col, current_row)
        elif comparison == "Industry" and industry_col:
            comp_col, comp_label = industry_col, "industry"
            peers, n_peers, note = build_peers(df_latest, comp_col, current_row)
        elif comparison == "Custom peers":
            comp_label = "custom"
            peers, n_peers, note = build_custom_peers(df_latest, (firm_name_col or firm_id_col), selected_custom_peers, current_row)

        if pillar == "E":
            stds_in_pillar = E_STANDARDS
        elif pillar == "S":
            stds_in_pillar = S_STANDARDS
        else:
            stds_in_pillar = G_STANDARDS

        firm_series = f"Firm ({current_year})" if current_year else "Firm"
        prior_label = f"Firm ({prior_year})" if (show_prior_year and prior_year) else None
        peers_series = f"Mean: {comp_label}" if n_peers > 0 else None

        # y sort order
        y_sort = [firm_series]
        if show_prior_year and prior_label:
            y_sort.append(prior_label)
        if peers_series:
            y_sort.append(peers_series)

        # ===== Overview =====
        if display_mode == "Charts":
            st.markdown("### Overview")

            if VARIANT == "v1":
                render_inline_legend(stds_in_pillar, STD_COLOR)

                rows = []
                for std_code in stds_in_pillar:
                    std_metrics = []
                    for gname in pillar_groups:
                        if gname.split("-")[0] == std_code:
                            std_metrics.extend(groups[gname])

                    vals = pd.to_numeric(current_row[std_metrics], errors="coerce")
                    firm_yes = int((vals == 1).sum())
                    rows.append({
                        "StdCode": std_code,
                        "Standard": SHORT_ESRS_LABELS.get(std_code, std_code),
                        "Series": firm_series,
                        "Value": float(firm_yes),
                    })

                    # Prior year
                    if show_prior_year and prior_year_row is not None and prior_label:
                        pvals = pd.to_numeric(prior_year_row[std_metrics], errors="coerce")
                        prior_yes = int((pvals == 1).sum())
                        rows.append({
                            "StdCode": std_code,
                            "Standard": SHORT_ESRS_LABELS.get(std_code, std_code),
                            "Series": prior_label,
                            "Value": float(prior_yes),
                        })

                    if n_peers > 0 and peers is not None and peers_series:
                        present = [c for c in std_metrics if c in peers.columns]
                        if present:
                            pb = pd.to_numeric(peers[present].stack(), errors="coerce").unstack()
                            peer_mean_rep = float((pb == 1).sum(axis=1).mean())
                        else:
                            peer_mean_rep = 0.0
                        rows.append({
                            "StdCode": std_code,
                            "Standard": SHORT_ESRS_LABELS.get(std_code, std_code),
                            "Series": peers_series,
                            "Value": float(peer_mean_rep),
                        })

                if rows:
                    cdf = pd.DataFrame(rows)
                    color_domain = stds_in_pillar
                    color_range  = [STD_COLOR.get(c, "#999") for c in color_domain]

                    base = alt.Chart(cdf)

                    bars = (
                        base
                        .mark_bar(stroke="#000", strokeWidth=1, strokeOpacity=0.9, strokeJoin="miter")
                        .encode(
                            y=alt.Y("Series:N", title="", sort=y_sort,
                                    scale=alt.Scale(paddingInner=0.25, paddingOuter=0.25)),
                            x=alt.X("Value:Q", title=X_TITLE, stack="zero"),
                            color=alt.Color("StdCode:N",
                                            scale=alt.Scale(domain=color_domain, range=color_range),
                                            legend=None),
                            order=alt.Order("StdCode:N"),
                            tooltip=[
                                alt.Tooltip("Series:N"),
                                alt.Tooltip("Standard:N"),
                                alt.Tooltip("Value:Q", title="# DR", format=".1f"),
                            ],
                        )
                    )

                    totals = (
                        base.transform_aggregate(total="sum(Value)", groupby=["Series"])
                        .mark_text(align="left", baseline="middle", dx=4)
                        .encode(
                            y=alt.Y("Series:N", sort=y_sort),
                            x="total:Q",
                            text=alt.Text("total:Q", format=".1f"),
                        )
                    )

                    sep_rules = (
                        alt.Chart(cdf)
                        .transform_aggregate(std_sum="sum(Value)", groupby=["Series", "StdCode"])
                        .transform_calculate(std_rank=f"indexof({stds_in_pillar!r}, datum.StdCode)")
                        .transform_window(
                            cum="sum(std_sum)",
                            sort=[alt.SortField(field="std_rank", order="ascending")],
                            groupby=["Series"]
                        )
                        .mark_rule(stroke="black", strokeWidth=1.5)
                        .encode(
                            x=alt.X("cum:Q"),
                            y=alt.Y("Series:N", sort=y_sort, title="", bandPosition=0),
                            y2=alt.Y2("Series:N", bandPosition=1),
                            tooltip=[alt.Tooltip("Series:N", title="Series")]
                        )
                    )

                    fig = (
                        alt.layer(bars, sep_rules, totals)
                        .properties(height=alt.Step(56), width="container",
                                    padding={"left": 12, "right": 12, "top": 6, "bottom": 6})
                        .configure_view(stroke=None)
                    )
                    st.altair_chart(fig, use_container_width=True)

                cap = "Counts of reported Disclosure Requirements within this pillar, stacked by standard."
                if show_prior_year and prior_label:
                    cap += f" Prior year ({prior_year}) shown for comparison."
                cap += (note if n_peers > 0 else "")
                st.caption(cap)
                st.markdown("---")

            else:
                # v2 / v3
                if VARIANT == "v3":
                    render_pillar_legend_single_missing(stds_in_pillar, STD_COLOR)
                else:
                    render_inline_legend(stds_in_pillar, STD_COLOR)

                rows = []
                for std_code in stds_in_pillar:
                    std_metrics = []
                    for gname in pillar_groups:
                        if gname.split("-")[0] == std_code:
                            std_metrics.extend(groups[gname])

                    total_std = STD_TOTAL_OVERRIDES.get(std_code, len(std_metrics))

                    vals = pd.to_numeric(current_row[std_metrics], errors="coerce")
                    firm_yes = int((vals == 1).sum())
                    firm_miss = max(total_std - firm_yes, 0)

                    rows.append({"Cat": std_code,
                                 "Label": SHORT_ESRS_LABELS.get(std_code, std_code),
                                 "Series": firm_series, "Value": float(firm_yes),
                                 "Denom": float(total_std)})
                    rows.append({"Cat": f"{std_code}_MISS",
                                 "Label": f"{SHORT_ESRS_LABELS.get(std_code, std_code)} — {'Not reported' if VARIANT=='v2' else ''}",
                                 "Series": firm_series, "Value": float(firm_miss),
                                 "Denom": float(total_std)})

                    # Prior year
                    if show_prior_year and prior_year_row is not None and prior_label:
                        pvals = pd.to_numeric(prior_year_row[std_metrics], errors="coerce")
                        prior_yes = int((pvals == 1).sum())
                        prior_miss = max(total_std - prior_yes, 0)
                        rows.append({"Cat": std_code,
                                     "Label": SHORT_ESRS_LABELS.get(std_code, std_code),
                                     "Series": prior_label, "Value": float(prior_yes),
                                     "Denom": float(total_std)})
                        rows.append({"Cat": f"{std_code}_MISS",
                                     "Label": f"{SHORT_ESRS_LABELS.get(std_code, std_code)} — {'Not reported' if VARIANT=='v2' else ''}",
                                     "Series": prior_label, "Value": float(prior_miss),
                                     "Denom": float(total_std)})

                    if n_peers > 0 and peers is not None:
                        present = [c for c in std_metrics if c in peers.columns]
                        if present:
                            pb = pd.to_numeric(peers[present].stack(), errors="coerce").unstack()
                            peer_mean_rep = float((pb == 1).sum(axis=1).mean())
                        else:
                            peer_mean_rep = 0.0
                        peer_mean_miss = max(total_std - peer_mean_rep, 0.0)
                        rows.append({
                            "Cat": std_code,
                            "Label": SHORT_ESRS_LABELS.get(std_code, std_code),
                            "Series": peers_series if peers_series else "Peers",
                            "Value": float(peer_mean_rep), "Denom": float(total_std),
                        })
                        rows.append({
                            "Cat": f"{std_code}_MISS",
                            "Label": f"{SHORT_ESRS_LABELS.get(std_code, std_code)} — {'Not reported' if VARIANT=='v2' else ''}",
                            "Series": peers_series if peers_series else "Peers",
                            "Value": float(peer_mean_miss), "Denom": float(total_std),
                        })

                if rows:
                    cdf = pd.DataFrame(rows)
                    cat_order = []
                    for s in stds_in_pillar:
                        cat_order.extend([s, f"{s}_MISS"])
                    rank_map = {c: i for i, c in enumerate(cat_order)}
                    cdf["CatRank"] = cdf["Cat"].map(rank_map).astype(int)

                    domain = [c for c in cat_order if (cdf["Cat"] == c).any()]
                    rng = [
                        (MISSING_COLOR[f"{pillar}_MISS"] if c.endswith("_MISS")
                         else STD_COLOR.get(c.replace("_MISS", ""), "#999"))
                        for c in domain
                    ]

                    missing_cats = [f"{s}_MISS" for s in stds_in_pillar]
                    is_missing = alt.FieldOneOfPredicate(field="Cat", oneOf=missing_cats)

                    base = alt.Chart(cdf)
                    bars = (
                        base
                        .mark_bar(stroke="#000", strokeWidth=1, strokeOpacity=0.9, strokeJoin="miter")
                        .encode(
                            y=alt.Y("Series:N", title="", sort=y_sort,
                                    scale=alt.Scale(paddingInner=0.25, paddingOuter=0.25)),
                            x=alt.X("Value:Q", title=X_TITLE, stack="zero"),
                            color=alt.Color("Cat:N", scale=alt.Scale(domain=domain, range=rng), legend=None),
                            order=alt.Order("CatRank:Q"),
                            opacity=alt.condition(is_missing, alt.value(0.5), alt.value(1.0)),
                            stroke=alt.condition(
                                is_missing,
                                alt.Color("Cat:N", scale=alt.Scale(domain=domain, range=rng)),
                                alt.value("#000")
                            ),
                            strokeDash=alt.condition(is_missing, alt.value([3, 2]), alt.value([0, 0])),
                            strokeWidth=alt.condition(is_missing, alt.value(1.5), alt.value(1)),
                            tooltip=[
                                alt.Tooltip("Series:N", title="Series"),
                                alt.Tooltip("Label:N", title="Segment"),
                                alt.Tooltip("Value:Q", title="# DR", format=".1f"),
                            ],
                        )
                    )

                    totals = (
                        base.transform_aggregate(total="sum(Value)", groupby=["Series"])
                            .mark_text(align="left", baseline="middle", dx=4)
                            .encode(y=alt.Y("Series:N", sort=y_sort),
                                    x="total:Q", text=alt.Text("total:Q", format=".1f"))
                    )

                    sep_rules = (
                        alt.Chart(cdf)
                        .transform_calculate(baseStd="replace(datum.Cat, /_MISS$/, '')")
                        .transform_aggregate(std_sum="sum(Value)", groupby=["Series", "baseStd"])
                        .transform_calculate(std_rank=f"indexof({stds_in_pillar!r}, datum.baseStd)")
                        .transform_window(
                            cum="sum(std_sum)",
                            sort=[alt.SortField(field="std_rank", order="ascending")],
                            groupby=["Series"]
                        )
                        .mark_rule(stroke="black", strokeWidth=1.5)
                        .encode(
                            x=alt.X("cum:Q"),
                            y=alt.Y("Series:N", sort=y_sort, title="", bandPosition=0),
                            y2=alt.Y2("Series:N", bandPosition=1),
                            tooltip=[alt.Tooltip("Series:N", title="Series")]
                        )
                    )

                    if VARIANT == "v3":
                        miss_word = "not reported"

                        def _make_pillar_labels(source_df, series_val):
                            base = (
                                alt.Chart(source_df)
                                .transform_filter(alt.FieldEqualPredicate(field="Series", equal=series_val))
                                .transform_window(
                                    cum="sum(Value)",
                                    sort=[alt.SortField(field="CatRank", order="ascending")],
                                    groupby=["Series"]
                                )
                                .transform_calculate(
                                    prev="datum.cum - datum.Value",
                                    mid="datum.prev + datum.Value/2",
                                    pct="(datum.Denom && datum.Denom > 0) ? datum.Value / datum.Denom : 0",
                                    pct_label="format(datum.pct, '.1%')"
                                )
                                .transform_filter(is_missing)
                                .transform_filter("datum.Value > 0 && datum.Denom > 0")
                            )
                            t_pct = (
                                base
                                .mark_text(align="center", baseline="middle", fontSize=11, color="#333", dy=-5)
                                .encode(y=alt.Y("Series:N", title="", sort=y_sort,
                                                scale=alt.Scale(paddingInner=0.25, paddingOuter=0.25)),
                                        x=alt.X("mid:Q"), text="pct_label:N")
                            )
                            t_miss = (
                                base
                                .mark_text(align="center", baseline="middle", fontSize=10, color="#333", dy=6)
                                .encode(y=alt.Y("Series:N", title="", sort=y_sort,
                                                scale=alt.Scale(paddingInner=0.25, paddingOuter=0.25)),
                                        x=alt.X("mid:Q"), text=alt.value(miss_word))
                            )
                            return t_pct, t_miss

                        text_pct, text_missing = _make_pillar_labels(cdf, firm_series)

                        extra_layers = []
                        if show_prior_year and prior_label:
                            prior_text_pct, prior_text_missing = _make_pillar_labels(cdf, prior_label)
                            extra_layers = [prior_text_pct, prior_text_missing]

                        fig = alt.layer(bars, sep_rules, text_pct, text_missing, *extra_layers, totals).properties(
                            height=alt.Step(56), width="container",
                            padding={"left": 12, "right": 12, "top": 6, "bottom": 6},
                        ).configure_view(stroke=None)
                    else:
                        fig = alt.layer(bars, sep_rules, totals).properties(
                            height=alt.Step(56), width="container",
                            padding={"left": 12, "right": 12, "top": 6, "bottom": 6},
                        ).configure_view(stroke=None)

                    st.altair_chart(fig, use_container_width=True)

                    fixed_total = sum(STD_TOTAL_OVERRIDES.get(s, 0) for s in stds_in_pillar)
                    cap = (
                        f"Counts of reported Disclosure Requirements (solid) within this pillar, stacked by standard. "
                        f"{'Not reported in grey. ' if VARIANT=='v3' else ''}"
                        f"Total in standard = {fixed_total}."
                    )
                    if show_prior_year and prior_label:
                        cap += f" Prior year ({prior_year}) shown for comparison."
                    cap += (note if n_peers > 0 else "")
                    st.caption(cap)
                st.markdown("---")

        else:
            # ===== Overview (Tables mode) =====
            st.markdown("### Overview")
            summary_rows = []
            for std_code in stds_in_pillar:
                std_metrics = []
                for gname in pillar_groups:
                    if gname.split("-")[0] == std_code:
                        std_metrics.extend(groups[gname])

                total_std = STD_TOTAL_OVERRIDES.get(std_code, len(std_metrics))
                vals = pd.to_numeric(current_row[std_metrics], errors="coerce")
                firm_yes = int((vals == 1).sum())
                missing = max(total_std - firm_yes, 0)

                prior_yes = None
                if show_prior_year and prior_year_row is not None:
                    pvals = pd.to_numeric(prior_year_row[std_metrics], errors="coerce")
                    prior_yes = int((pvals == 1).sum())

                peer_yes_mean = None
                if n_peers > 0 and peers is not None:
                    present_cols = [m for m in std_metrics if m in peers.columns]
                    if present_cols:
                        pb = pd.to_numeric(peers[present_cols].stack(), errors="coerce").unstack()
                        peer_yes_mean = float((pb == 1).sum(axis=1).mean())

                row = {"Standard": SHORT_ESRS_LABELS.get(std_code, std_code)}
                if VARIANT == "v3":
                    row["Reported disclosure requirements"] = firm_yes
                    row["Not reported disclosure requirements"] = missing
                    row["Total disclosure requirements"] = total_std
                elif VARIANT == "v2":
                    row["Firm — number of reported Disclosure Requirements"] = firm_yes
                    row["Total disclosure requirements"] = total_std
                else:
                    row["Firm — number of reported Disclosure Requirements"] = firm_yes

                if prior_yes is not None:
                    row[f"Prior year ({prior_year}) reported"] = prior_yes
                if peer_yes_mean is not None:
                    row[f"Peers — mean number of reported Disclosure Requirements ({comp_label})"] = round(peer_yes_mean, 1)

                summary_rows.append(row)

            if summary_rows:
                tbl = pd.DataFrame(summary_rows)
                st.dataframe(tbl, use_container_width=True, hide_index=True)
                cap = "Rows show the number of reported Disclosure Requirements per ESRS standard in this pillar."
                if VARIANT == "v3":
                    cap += " Includes each standard's Total and Not reported."
                elif VARIANT == "v2":
                    cap += " Includes each standard's Total."
                if show_prior_year and prior_year:
                    cap += f" Prior year ({prior_year}) column shown for comparison."
                if n_peers > 0:
                    cap += note
                st.caption(cap)
                st.markdown("---")

        # ===== Per-standard detail (expanders) =====
        for g in pillar_groups:
            metrics = groups[g]
            base_code = g.split("-")[0]
            fully_phased_col = f"{base_code}-fully_phased_in"
            std_fully_phased = is_yes_val(current_row.get(fully_phased_col, np.nan))
            short_title = SHORT_ESRS_LABELS.get(base_code, base_code)
            n_metrics = len(metrics)

            vals = pd.to_numeric(current_row[metrics], errors="coerce")
            firm_yes_count = int((vals == 1).sum())
            peers_yes_mean = None
            if n_peers > 0 and peers is not None:
                present_cols = [m for m in metrics if m in peers.columns]
                if present_cols:
                    pb = pd.to_numeric(peers[present_cols].stack(), errors="coerce").unstack()
                    if len(pb) > 0:
                        peers_yes_mean = float((pb == 1).sum(axis=1).mean())

            if VARIANT == "v1":
                exp_title = short_title
            elif VARIANT == "v2":
                missing_count = max(n_metrics - int(firm_yes_count), 0)
                if peers_yes_mean is not None:
                    exp_title = (
                        f"{short_title} • Disclosure Requirements "
                        f"reported: {firm_yes_count}/{n_metrics} "
                        f"(Peers {comp_label}: {peers_yes_mean:.1f})"
                    )
                else:
                    exp_title = (
                        f"{short_title} • Disclosure Requirements "
                        f"reported: {firm_yes_count}"
                    )
            else:
                if peers_yes_mean is not None:
                    exp_title = (
                        f"{short_title} •  Disclosure Requirements "
                        f"reported: {firm_yes_count}/{n_metrics} "
                        f"(Peers {comp_label}: {peers_yes_mean:.1f})"
                    )
                else:
                    exp_title = (
                        f"{short_title} • Disclosure Requirements "
                        f"reported: {firm_yes_count}/{n_metrics}"
                    )

            with st.expander(exp_title, expanded=False):
                if display_mode == "Tables":
                    codes = [col_to_dr_code(str(c).strip().split(" ")[0]) for c in metrics]
                    names = [DR_LABELS.get(code, "") for code in codes]
                    firm_vals_list = [pretty_value(current_row.get(c, np.nan)) for c in metrics]

                    table = pd.DataFrame({
                        "Code": codes,
                        "Name": names,
                        "Reported": firm_vals_list,
                    })

                    if show_prior_year and prior_year_row is not None:
                        prior_vals_list = [pretty_value(prior_year_row.get(c, np.nan)) for c in metrics]
                        table[f"Prior year ({prior_year})"] = prior_vals_list

                    if n_peers > 0 and peers is not None:
                        peer_pct = []
                        for m in metrics:
                            if m in peers.columns:
                                s = pd.to_numeric(peers[m], errors="coerce")
                                pct = (s == 1).mean()
                                peer_pct.append(f"{pct*100:.1f}%")
                            else:
                                peer_pct.append("—")
                        table[f"Peers reported % ({comp_label})"] = peer_pct

                    st.dataframe(table, use_container_width=True, hide_index=True)
                    if n_peers > 0:
                        st.caption(f"Peers reported % = share of selected peers answering 'Yes' {note}")

                else:
                    ok_color = TILE_OK
                    no_color = TILE_NO

                    present_cols = [m for m in metrics if m in df.columns and "_phase_in" not in m and "fully_phased" not in m]
                    phase_lookup = {
                        m: m + "_phase_in_disclosed"
                        for m in present_cols
                        if m + "_phase_in_disclosed" in df.columns
                    }
                    phase_cols = {m.replace("_phase_in_disclosed", ""): m for m in metrics if "_phase_in_disclosed" in m}
                    if len(present_cols) == 0:
                        st.info("No Disclosure Requirements found for this group.")
                        continue


                    def short_label(col: str) -> str:
                        s = str(col).strip()
                        return s.split(" ")[0] if " " in s else s

                    def full_name(code: str) -> str:
                        return DR_LABELS.get(code, "")

                    labels = [short_label(c) for c in present_cols]
                    tile_gap = 0.10
                    eff_w = 1.0 - tile_gap

                    rows = []
                    for i, col in enumerate(present_cols):
                        code = short_label(col)
                        xa = i + tile_gap / 2.0
                        xb = i + 1 - tile_gap / 2.0
                        raw_val = current_row.get(col, np.nan)
                        phase_col = phase_lookup.get(col)
                        phase_val = current_row.get(phase_col, np.nan) if phase_col else np.nan
                        
                        try:
                            reported = float(raw_val) == 1.0
                        except (ValueError, TypeError):
                            reported = False
                        try:
                            is_phase = float(phase_val) == 1.0 or std_fully_phased
                        except (ValueError, TypeError):
                            is_phase = std_fully_phased
                        share = 1.0 if reported else (0.5 if is_phase else 0.0)
                        xg = float(xa + eff_w * (1.0 if (reported or is_phase) else 0.0))
                        rows.append({
                            "Series": firm_series,
                            "Label": code, "Full": full_name(code),
                            "i": i, "xa": float(xa), "xb": float(xb),
                            "xg": xg,
                            "share": float(share)
                        })

                    # Prior year tiles

                    if show_prior_year and prior_year_row is not None and prior_label:
                        for i, col in enumerate(present_cols):
                            code = short_label(col)
                            xa = i + tile_gap / 2.0
                            xb = i + 1 - tile_gap / 2.0
                            raw_val = prior_year_row.get(col, np.nan)
                            try:
                                share = 1.0 if float(raw_val) == 1.0 else 0.0
                            except (ValueError, TypeError):
                                share = 0.0
                            rows.append({
                                "Series": prior_label,
                                "Label": code, "Full": full_name(code),
                                "i": i, "xa": float(xa), "xb": float(xb),
                                "xg": float(xa + eff_w * share),
                                "share": float(share)
                            })

                    peers_label = None
                    if n_peers > 0 and peers is not None:
                        peers_label = "Mean:" + (f" {comp_label}" if comp_label else "")
                        for i, col in enumerate(present_cols):
                            code = short_label(col)
                            xa = i + tile_gap / 2.0
                            xb = i + 1 - tile_gap / 2.0
                            if col in peers.columns:
                                s = pd.to_numeric(peers[col], errors="coerce")
                                share = float((s == 1).mean()) if len(s) else 0.0
                            else:
                                share = 0.0
                            rows.append({
                                "Series": peers_label,
                                "Label": code, "Full": full_name(code),
                                "i": i, "xa": float(xa), "xb": float(xb),
                                "xg": float(xa + eff_w * share),
                                "share": float(share)
                            })

                    tile_df = pd.DataFrame(rows)

                    tick_values = [i + 0.5 for i in range(len(present_cols))]
                    labels_js = "[" + ",".join([repr(lbl) for lbl in labels]) + "]"
                    label_expr = f"{labels_js}[floor(datum.value - 0.5)]"

                    tile_sort = [firm_series]
                    if show_prior_year and prior_label:
                        tile_sort.append(prior_label)
                    if peers_label:
                        tile_sort.append(peers_label)

                    xscale = alt.Scale(domain=[0, len(present_cols)], nice=False, zero=True)
                    x_axis = alt.Axis(values=tick_values, tickSize=0, labelAngle=0, labelPadding=6,
                                      labelExpr=label_expr, title=None)

                    y_enc = alt.Y(
                        "Series:N",
                        sort=tile_sort,
                        title="",
                        scale=alt.Scale(paddingInner=0.65, paddingOuter=0.28),
                        axis=alt.Axis(labels=True, ticks=False, domain=False)
                    )

                    tile_tooltip = [
                        alt.Tooltip("Label:N", title="Code"),
                        alt.Tooltip("Full:N",  title="Name"),
                        alt.Tooltip("Series:N", title="Series"),
                    ]

                    base = alt.Chart(tile_df)

                    red = (
                        base.mark_rect(stroke="white", strokeWidth=0.8)
                            .encode(
                                y=y_enc,
                                x=alt.X("xa:Q", scale=xscale, axis=x_axis),
                                x2="xb:Q",
                                color=alt.value(no_color),
                                tooltip=tile_tooltip,
                            )
                    )

                    green = (
                        base.mark_rect(stroke="white", strokeWidth=0.8)
                            .encode(y=y_enc, x="xa:Q", x2="xg:Q", color=alt.value(ok_color), tooltip=tile_tooltip)
                            .transform_filter("datum.share == 1.0")
                    )
                    
                    phase_tiles = (
                        base.mark_rect(stroke="white", strokeWidth=0.8)
                            .encode(y=y_enc, x="xa:Q", x2="xg:Q", color=alt.value(TILE_PHASE), tooltip=tile_tooltip)
                            .transform_filter("datum.share == 0.5")
                    )

                    pct_text = None
                    if peers_label:
                        pct_text = (
                            base
                            .transform_filter(alt.FieldEqualPredicate(field="Series", equal=peers_label))
                            .transform_filter("datum.share >= 0.10")
                            .transform_calculate(xtext="datum.xa + (datum.xb - datum.xa) * datum.share * 0.35")
                            .mark_text(baseline="middle", fontSize=11, color="white")
                            .encode(
                                y=y_enc,
                                x=alt.X("xtext:Q", scale=xscale),
                                text=alt.Text("share:Q", format=".0%"),
                                tooltip=tile_tooltip,
                            )
                        )

                    px_per_tile = 28
                    total_width = max(240, int(px_per_tile * len(present_cols)))
                    fig = alt.layer(red, green, phase_tiles).properties(
                        width=total_width,
                        height=alt.Step(50),
                        padding={"left": 12, "right": 12, "top": 6, "bottom": 8},
                    ).configure_view(stroke=None)

                    st.altair_chart(fig, use_container_width=True)
                    tiles_legend = (
                        "Tiles: dark = reported, medium = phase-in, light = missing. "
                        if VARIANT == "v2"
                        else "Tiles: dark = reported, light = not reported. "
                    )
                    prior_note = f"Prior year ({prior_year}) row shown. " if (show_prior_year and prior_label) else ""
                    st.caption(
                        f"{len(present_cols)} Tiles = Disclosure Requirements within this ESRS standard. "
                        + tiles_legend
                        + prior_note
                        + (f"Peer tiles show % of peers reporting. " if peers_label else "")
                        + (note if peers_label else "")
                    )


    # ========= Render selected pillar =========
    if view == "E":
        render_pillar("E", "E — Environment", comparison, display_mode)
    elif view == "S":
        render_pillar("S", "S — Social", comparison, display_mode)
    elif view == "G":
        render_pillar("G", "G — Governance", comparison, display_mode)
    elif view == "Text characteristics":
        st.subheader("Text characteristics")
        TEXT_METRICS = {
            "Pages": "Pages",
            "total_words": "Total words",
            "mean_fog": "Language Complexity",
            "boilergrams": "Boilergrams",
        }


        present_metrics = [c for c in TEXT_METRICS.keys() if c in df.columns]

        if not present_metrics:
            st.info("No text characteristics columns found (expected: pages, words_total, fog).")
        else:
            firm_vals = {}
            for c in present_metrics:
                v = current_row.get(c, np.nan)
                firm_vals[c] = pd.to_numeric(v, errors="coerce")

            peers, n_peers, peer_note = (None, 0, "")
            if comparison == "Country" and country_col:
                peers, n_peers, peer_note = build_peers(filtered_df, country_col, current_row)
            elif comparison == "Index" and "dax40" in df.columns:
                if selected_peer_index == "DAX40":
                    peers = df_latest[df_latest["dax40"].astype(str).isin(["1", "1.0", "True", "true"])].copy()
                elif selected_peer_index == "EuroStoxx50":
                    peers = df_latest[df_latest["es50"].astype(str).isin(["1", "1.0", "True", "true"])].copy()
                else:
                    peers = pd.DataFrame()
                try:
                    peers = peers.drop(current_row.name, errors="ignore")
                except Exception:
                    pass
                n_peers = len(peers)
                peer_note = f" (Index = {selected_peer_index}, n={n_peers})"
            elif comparison == "Sector" and sector_col:
                peers, n_peers, peer_note = build_peers(df_latest, sector_col, current_row)
            elif comparison == "Industry" and industry_col:
                peers, n_peers, peer_note = build_peers(df_latest, industry_col, current_row)
            elif comparison == "Custom peers":
                peers, n_peers, peer_note = build_custom_peers(
                    df_latest, (firm_name_col or firm_id_col), selected_custom_peers, current_row
                )
            peer_means = {}
            if n_peers > 0 and peers is not None and not peers.empty:
                for c in present_metrics:
                    peer_means[c] = pd.to_numeric(peers[c], errors="coerce").mean()
            else:
                peer_means = {c: np.nan for c in present_metrics}

            prior_text_vals = {}
            if show_prior_year and prior_year_row is not None:
                for c in present_metrics:
                    v = prior_year_row.get(c, np.nan)
                    prior_text_vals[c] = pd.to_numeric(v, errors="coerce")

            kpi_cols = st.columns(len(present_metrics))
            for i, c in enumerate(present_metrics):
                label = TEXT_METRICS[c]
                firm_v = firm_vals[c]
                peer_v = peer_means[c]

                if c in ("pages", "words_total"):
                    firm_fmt = "—" if pd.isna(firm_v) else f"{firm_v:,.0f}"
                    delta = None if pd.isna(peer_v) else (firm_v - peer_v if not pd.isna(firm_v) else None)
                    delta_fmt = None if delta is None else f"{delta:,.0f}"
                else:
                    firm_fmt = "—" if pd.isna(firm_v) else f"{firm_v:.2f}"
                    delta = None if pd.isna(peer_v) else (firm_v - peer_v if not pd.isna(firm_v) else None)
                    delta_fmt = None if delta is None else f"{delta:+.2f}"

                prior_v = prior_text_vals.get(c, np.nan) if prior_text_vals else np.nan
                
                _dp  = float(firm_v) - float(peer_v)  if (not pd.isna(firm_v) and not pd.isna(peer_v))  else None
                _dpr = float(firm_v) - float(prior_v) if (not pd.isna(firm_v) and not pd.isna(prior_v)) else None
                _dfmt = lambda d: (f"{d:+,.0f}" if c in ("pages", "words_total") else f"{d:+.2f}") if d is not None else None
                
                if show_prior_year and _dpr is not None and n_peers > 0 and _dp is not None:
                    kpi_cols[i].metric(label=label, value=firm_fmt, delta=f"{_dfmt(_dp)} vs peers")
                    kpi_cols[i].metric(label="", value="", delta=f"{_dfmt(_dpr)} vs {prior_year}")
                elif show_prior_year and _dpr is not None:
                    kpi_cols[i].metric(label=label, value=firm_fmt,
                        delta=f"{_dfmt(_dpr)} vs {prior_year}")
                elif n_peers > 0 and _dp is not None:
                    kpi_cols[i].metric(label=label, value=firm_fmt,
                        delta=f"{_dfmt(_dp)} vs peers")
                else:
                    kpi_cols[i].metric(label=label, value=firm_fmt)
    

            if display_mode == "Charts":
                st.markdown("### Charts")

                for c in present_metrics:
                    firm_v = firm_vals.get(c, np.nan)
                    peer_v = peer_means.get(c, np.nan)
                    prior_v = prior_text_vals.get(c, np.nan) if prior_text_vals else np.nan

                    chart_rows = []
                    firm_lbl = f"Firm ({current_year})" if current_year else "Firm"
                    if not pd.isna(firm_v):
                        chart_rows.append({"Series": firm_lbl, "Value": float(firm_v)})
                    if show_prior_year and not pd.isna(prior_v):
                        prior_lbl = f"Firm ({prior_year})"
                        chart_rows.append({"Series": prior_lbl, "Value": float(prior_v)})
                    if n_peers > 0 and not pd.isna(peer_v):
                        chart_rows.append({"Series": "Peers mean", "Value": float(peer_v)})

                    chart_df = pd.DataFrame(chart_rows)
                    if chart_df.empty:
                        continue

                    fmt = ",.0f" if c in ("pages", "words_total") else ".2f"
                    vmax = float(chart_df["Value"].max())
                    xscale = alt.Scale(domain=[0, vmax * 1.10] if vmax > 0 else [0, 1])

                    y_order = [firm_lbl]
                    if show_prior_year and prior_year:
                        y_order.append(f"Firm ({prior_year})")
                    y_order.append("Peers mean")

                    bars = (
                        alt.Chart(chart_df)
                        .mark_bar()
                        .encode(
                            y=alt.Y("Series:N", title="", sort=y_order),
                            x=alt.X("Value:Q", title=TEXT_METRICS[c], scale=xscale),
                            tooltip=[
                                alt.Tooltip("Series:N", title="Series"),
                                alt.Tooltip("Value:Q", title=TEXT_METRICS[c], format=fmt),
                            ],
                        )
                        .properties(height=120)
                    )

                    maxv = float(chart_df["Value"].max()) if len(chart_df) else 0.0
                    inside_threshold = 0.18 * maxv

                    labels_outside = (
                        alt.Chart(chart_df)
                        .transform_filter(f"datum.Value < {inside_threshold}")
                        .mark_text(align="left", baseline="middle", dx=6)
                        .encode(
                            y=alt.Y("Series:N", sort=y_order),
                            x=alt.X("Value:Q", scale=xscale),
                            text=alt.Text("Value:Q", format=fmt),
                        )
                    )

                    labels_inside = (
                        alt.Chart(chart_df)
                        .transform_filter(f"datum.Value >= {inside_threshold}")
                        .mark_text(align="right", baseline="middle", dx=-6, color="white")
                        .encode(
                            y=alt.Y("Series:N", sort=y_order),
                            x=alt.X("Value:Q", scale=xscale),
                            text=alt.Text("Value:Q", format=fmt),
                        )
                    )

                    st.altair_chart(
                        alt.layer(bars, labels_outside, labels_inside),
                        use_container_width=True
                    )

            if display_mode == "Tables":
                rows = []
                firm_lbl = f"Firm ({current_year})" if current_year else "Firm"
                rows.append({"Series": firm_lbl, **{TEXT_METRICS[c]: firm_vals[c] for c in present_metrics}})

                if show_prior_year and prior_year_row is not None:
                    rows.append({
                        "Series": f"Firm ({prior_year})",
                        **{TEXT_METRICS[c]: prior_text_vals.get(c, np.nan) for c in present_metrics}
                    })

                if n_peers > 0 and peers is not None and not peers.empty:
                    rows.append({
                        "Series": f"Peers mean{peer_note}",
                        **{TEXT_METRICS[c]: peer_means[c] for c in present_metrics}
                    })

                out = pd.DataFrame(rows)
                for c in present_metrics:
                    nice = TEXT_METRICS[c]
                    if c in ("pages", "words_total"):
                        out[nice] = out[nice].map(lambda x: "—" if pd.isna(x) else f"{x:,.0f}")
                    else:
                        out[nice] = out[nice].map(lambda x: "—" if pd.isna(x) else f"{x:.2f}")

                st.dataframe(out, use_container_width=True, hide_index=True)
            st.markdown("""
            **Metric explanations**
            - **Pages**: Total number of pages in the sustainability report.
            - **Total words**: Total word count extracted from the PDF.
            - **Language Complexity (Fog)**: Gunning Fog Index, Scores above 18 are considered very difficult.
            - **Boilergrams**: Count of generic, templated n-grams (word sequences) found across many reports. Higher = more boilerplate, less firm-specific disclosure.
            """)
            if n_peers > 0:
                st.caption("Peer values are computed as the mean across the current peer set." + peer_note)


   
