import streamlit as st
import pandas as pd
import numpy as np
from collections import defaultdict
import altair as alt
from io import BytesIO
import requests
from urllib.parse import urlencode

# ========= VARIANT / TREATMENT ARMS =========
VARIANT_KEYS = ["v1", "v2", "v3"]
DEFAULT_VARIANT = None  # None => randomize when URL lacks ?v=

# Early, local URL helpers so we don't depend on later helper defs
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
    # 1) respect ?v= in URL if present (case-insensitive)
    v = (_qp_get("v", "") or "").lower()
    if v in VARIANT_KEYS:
        st.session_state["variant"] = v
        return v

    # 2) respect previously chosen session variant
    v = st.session_state.get("variant")
    if v not in VARIANT_KEYS:
        # 3) default: random assignment (unless DEFAULT_VARIANT is set)
        v = DEFAULT_VARIANT or np.random.choice(VARIANT_KEYS)
        st.session_state["variant"] = v

    # persist to URL
    _qp_update(v=v)
    return v

# Optional: dev mode via ?dev=1 or secrets
DEV_MODE = str(_qp_get("dev", "") or "").lower() in ("1", "true", "yes")
try:
    if st.secrets.get("DEV_MODE"):
        DEV_MODE = True
except Exception:
    pass

VARIANT = _get_variant()


# ========= CONFIG =========
DEFAULT_DATA_URL = "https://github.com/akgrossk/srn_dr_list/blob/main/DR_upload.xlsx"

FIRM_NAME_COL_CANDIDATES = ["name", "company", "firm"]
FIRM_ID_COL_CANDIDATES   = ["isin", "ticker"]
COUNTRY_COL_CANDIDATES   = ["country", "Country"]

# IMPORTANT: use your SICS columns first, with sensible fallbacks
INDUSTRY_COL_CANDIDATES  = ["primary_sics_industry", "industry", "Industry"]
SECTOR_COL_CANDIDATES    = ["primary_sics_sector", "sector", "Sector"]

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
        # Expect "CODE<TAB>Label"
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
S1-2	Processes for engaging with own workers and workers’ representatives about impacts
S1-3	Processes to remediate negative impacts and channels for own workers to raise concerns
S1-4	Taking action on material impacts on own workforce, and approaches to mitigating material risks and pursuing material opportunities related to own workforce, and effectiveness of those actions
S1-5	Targets related to managing material negative impacts, advancing positive impacts, and managing material risks and opportunities
S1-6	Characteristics of the undertaking’s employees
S1-7	Characteristics of non-employee workers in the undertaking’s own workforce
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


# === Overview palettes (used ONLY in the overview charts) ===
E_STANDARDS = ["E1", "E2", "E3", "E4", "E5"]
S_STANDARDS = ["S1", "S2", "S3", "S4"]
G_STANDARDS = ["G1"]  # extend if you add more
PALETTE_E = ["#0b7a28", "#188f31", "#20a73c", "#27be46", "#2fd551"]  # E1..E5 greens
PALETTE_S = ["#8f1414", "#b51d1d", "#d23030", "#ea4b4b"]             # S1..S4 reds
PALETTE_G = ["#f2c744"]                                             # G1 yellow
STD_ORDER = E_STANDARDS + S_STANDARDS + G_STANDARDS
STD_COLOR = {
    **{s: c for s, c in zip(E_STANDARDS, PALETTE_E)},
    **{s: c for s, c in zip(S_STANDARDS, PALETTE_S)},
    **{s: c for s, c in zip(G_STANDARDS, PALETTE_G)},
}
# === Fixed totals per standard used in pillar Overviews ===
STD_TOTAL_OVERRIDES = {
    # Environment (sum = 32)
    "E1": 9, "E2": 6, "E3": 5, "E4": 6, "E5": 6,
    # Social (sum = 32)
    "S1": 17, "S2": 5, "S3": 5, "S4": 5,
    # Governance (sum = 6)
    "G1": 6,
}

# ========= VARIANT-SPECIFIC LOOKS =========
# You can make each arm feel different: colors, chart marks, table options, etc.

# Color themes for standards by variant:
STD_COLOR_V1 = STD_COLOR  # your current palette

STD_COLOR_V2 = STD_COLOR 

STD_COLOR_V3 = STD_COLOR 

if VARIANT == "v2":
    STD_COLOR = STD_COLOR_V2
elif VARIANT == "v3":
    STD_COLOR = STD_COLOR_V3
# else keep v1 defaults

# Tile colors (for the per-DR “green/red” tiles)
TILE_OK = "#4200ff"
TILE_NO = "#d6ccff"

# Force stack order to follow legend order E1..E5, S1..S4, G1
STD_RANK = {code: i for i, code in enumerate(STD_ORDER)}


# add Sector as a first-class comparison
COMP_TO_PARAM = {
    "No comparison": "none",
    "Country": "country",
    "Sector": "sector",
    "Industry": "industry",
    "Custom peers": "custom",
}
PARAM_TO_COMP = {v: k for k, v in COMP_TO_PARAM.items()}

# ========= HELPERS =========
def pretty_value(v):
    if pd.isna(v):
        return "—"
    s = str(v).strip().lower()
    if s in YES_SET:
        return "✅ Yes"
    if s in NO_SET:
        return "❌ No"
    return str(v)

def group_key(col: str):
    if not isinstance(col, str) or not col or col[0] not in "ESG":
        return None
    parts = col.split("-")
    if len(parts) >= 2 and not parts[1].isdigit():  # IRO / GOV / SBM etc.
        return f"{parts[0]}-{parts[1]}"
    return parts[0]

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
            return pd.read_excel(data)
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
    note = f" ({comp_col} = {current_val}, n={len(peers)})"
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
    # spacer so the chart starts on a full-width new row
    st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)

# --- Missing segments (v2/v3 Total only) ---
MISSING_CODES = ["E_MISS", "S_MISS", "G_MISS"]
# exact colors for the added "missing" bars
MISSING_COLOR = {
    "E_MISS": "#8BE8A0",  # light green
    "S_MISS": "#F5A3A3",  # light red
    "G_MISS": "#F8E690",  # light yellow
}


def pillar_color(p: str) -> str:
    # use the *existing* pillar base color (unchanged palette)
    if p == "E":
        return STD_COLOR.get("E1", "#0b7a28")
    if p == "S":
        return STD_COLOR.get("S1", "#8f1414")
    return STD_COLOR.get("G1", "#f2c744")

def missing_label_for_variant(pillar: str) -> str:
    base = {"E":"E — ", "S":"S — ", "G":"G — "}[pillar]
    return base + ("Not reported" if VARIANT == "v2" else "Missing")

def render_inline_legend_with_missing(codes, colors):
    """Show normal per-standard chips + 3 extra 'missing' legend entries with exact bar colors."""
    # normal items (standards E1.., S1.., G1..)
    items = "".join(
        f'<span class="swatch" style="background:{colors[c]}"></span>'
        f'<span class="lab">{c}</span>'
        for c in codes
    )

    # exact tint swatches for the 3 missing entries
    miss_bits = []
    for p, code in zip(["E", "S", "G"], MISSING_CODES):
        tint = MISSING_COLOR.get(code, pillar_color(p))  # fallback to pillar base if key missing
        miss_bits.append(
            f'<span class="swatch" style="background:{tint}"></span>'
            f'<span class="lab">{missing_label_for_variant(p)}</span>'
        )
    items += "".join(miss_bits)

    st.markdown(
        """
        <style>
        .legend-inline{display:flex;flex-wrap:wrap;gap:.5rem 1rem;align-items:center;margin-top:.35rem;}
        .legend-inline .swatch{display:inline-block;width:12px;height:12px;border-radius:2px;margin-right:.35rem;}
        .legend-inline .lab{font-size:0.9rem;}
        </style>
        """,
        unsafe_allow_html=True,
    )
    st.markdown(f'<div class="legend-inline">{items}</div>', unsafe_allow_html=True)

def std_missing_label(std_code: str) -> str:
    return f"{std_code} — {'Not reported' if VARIANT=='v2' else 'Missing'}"

def render_pillar_legend_with_missing(stds_in_pillar, colors, pillar):
    """Legend for a single pillar tab:
       - colored chips for the pillar's standards (E1.. or S1.. or G1)
       - ONE extra hatched chip for the pillar's 'Not reported/Missing'
    """
    # normal standard chips
    items = "".join(
        f'<span class="swatch" style="background:{colors[c]}"></span>'
        f'<span class="lab">{c}</span>'
        for c in stds_in_pillar
    )

    # hatched chip for this pillar
    base = pillar_color(pillar)  # uses your existing function
    swatch_css = (
        f"background: {base}; "
        f"mask-image: repeating-linear-gradient(135deg, #000 0 6px, transparent 6px 12px); "
        f"-webkit-mask-image: repeating-linear-gradient(135deg, #000 0 6px, transparent 6px 12px); "
        f"border: 1px solid {base};"
    )
    items += (
        f'<span class="swatch" style="{swatch_css}"></span>'
        f'<span class="lab">{missing_label_for_variant(pillar)}</span>'
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


# ========= LOAD DATA (GitHub only) =========
df = load_table(DEFAULT_DATA_URL)
if df.empty:
    st.stop()


# --- Variant switcher (always visible) ---
st.sidebar.caption(f"Variant: **{VARIANT.upper()}**")

try:
    # Streamlit >= 1.31
    new_variant = st.sidebar.segmented_control(
        "View style",
        options=VARIANT_KEYS,
        default=VARIANT,
        format_func=lambda x: x.upper(),
    )
except Exception:
    # Fallback for older Streamlit
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
    # persist to URL so the link is shareable
    try:
        st.query_params.update({"v": VARIANT})
    except Exception:
        cur = st.experimental_get_query_params()
        cur["v"] = VARIANT
        st.experimental_set_query_params(**cur)
    st.rerun()


# ========= DETECT COLUMNS & PRE-READ URL STATE =========
firm_name_col = first_present(df.columns, FIRM_NAME_COL_CANDIDATES)
firm_id_col   = first_present(df.columns, FIRM_ID_COL_CANDIDATES)
country_col   = first_present(df.columns, COUNTRY_COL_CANDIDATES)
industry_col  = first_present(df.columns, INDUSTRY_COL_CANDIDATES)
sector_col    = first_present(df.columns, SECTOR_COL_CANDIDATES)

# Read selections from URL
firm_qp  = read_query_param("firm", None)
comp_qp  = (read_query_param("comp", "none") or "none").lower()
peers_qp = read_query_param("peers", "")
mode_qp  = (read_query_param("mode", "charts") or "charts").lower()
preselected_peers = [p for p in peers_qp.split(",") if p] if peers_qp else []

# --- Landing page content (shown before a firm is selected) ---
LANDING_MD = """
### Welcome

This dashboard shows the Disclosure Requirements, which firms report in their ESRS reports. Each **ESRS** is organized into **Disclosure Requirements (DR)** — for example, **DR E1-6** on GHG emissions — which specify the datapoints to be disclosed (e.g., **ESRS 1.44 (a): Gross Scope 1 GHG emissions**).

"""

# ========= FIRM PICKER =========
if firm_name_col:
    firms = df[firm_name_col].dropna().astype(str).unique().tolist()
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
        st.info("Select a firm from the sidebar to view details.")
        st.stop()
    current_row = df[df[firm_name_col].astype(str) == str(firm_label)].iloc[0]
elif firm_id_col:
    firms = df[firm_id_col].dropna().astype(str).unique().tolist()
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
    current_row = df[df[firm_id_col].astype(str) == str(firm_label)].iloc[0]
else:
    st.error("No firm identifier column found (looked for: name/company/firm or isin/ticker).")
    st.stop()

# ========= ESG STRUCTURE =========
esg_columns = [c for c in df.columns if isinstance(c, str) and c[:1] in ("E", "S", "G")]
groups, by_pillar = build_hierarchy(esg_columns)

# ========= HEADER =========
st.title(str(firm_label))
isin_txt     = f"ISIN: <strong>{current_row.get(firm_id_col, 'n/a')}</strong>" if firm_id_col else ""
country_txt  = f"Country: <strong>{current_row.get(country_col, 'n/a')}</strong>" if country_col else ""
sector_txt   = f"Sector: <strong>{current_row.get(sector_col, 'n/a')}</strong>" if sector_col else ""
industry_txt = f"Industry: <strong>{current_row.get(industry_col, 'n/a')}</strong>" if industry_col else ""
sub = " · ".join([t for t in [isin_txt, country_txt, sector_txt, industry_txt] if t])
if sub:
    st.markdown(f"<div class='firm-meta'>{sub}</div>", unsafe_allow_html=True)

# ====== REPORT BUTTON + AUDITOR POPOVER ======
# Prefer Sustainability Report (Link_SR); fall back to Annual Report (Link_AR)
link_sr = str(current_row.get("Link_SR", "")).strip()
link_ar = str(current_row.get("Link_AR", "")).strip()

def _valid_url(u: str) -> bool:
    try:
        return u.lower().startswith(("http://", "https://"))
    except Exception:
        return False

link_url = link_sr if _valid_url(link_sr) else (link_ar if _valid_url(link_ar) else "")

# Read auditor value from the current row (column is exactly 'auditor')
aud_col = "auditor"
auditor_val = ""
if aud_col in df.columns:
    v = current_row.get(aud_col, "")
    auditor_val = "" if (pd.isna(v)) else str(v).strip()

# === ACTION ROW (exactly 3 single-line buttons) ===
btn_col1, btn_col2, btn_col3 = st.columns([1.2, 1, 1.6])

# Force all buttons onto one line with ellipsis if needed
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

# 1) Open firm report
with btn_col1:
    if _valid_url(link_url):
        st.link_button("Open firm report", link_url, help="Open the firm's report in a new tab")
    else:
        if st.button("Open firm report"):
            try:
                st.toast("No report link available yet.", icon="ℹ️")
            except Exception:
                st.info("No report link available yet.")

# 2) Show auditor
with btn_col2:
    try:
        with st.popover("Show auditor"):
            st.markdown(f"**Auditor:** {auditor_val or '—'}")
    except Exception:
        if st.button("Show auditor"):
            st.info(f"Auditor: {auditor_val or '—'}")

# 3) Show text characteristics (URL optional — placeholder for now)
# Try a few likely column names; adjust to match your data later
esg_link = ""
for col in ["ESG_text_link", "Link_ESG_text", "Link_ESG", "ESG_Text_URL"]:
    if col in df.columns:
        candidate = str(current_row.get(col, "")).strip()
        if _valid_url(candidate):
            esg_link = candidate
            break

with btn_col3:
    if _valid_url(esg_link):
        st.link_button("Show text characteristics", esg_link, help="Opens in a new tab")
    else:
        if st.button("Show text characteristics"):
            try:
                st.toast("No info yet — add an ESG text URL when ready.", icon="📝")
            except Exception:
                st.info("No info yet — add an ESG text URL when ready.")


# ========= NAV & COMPARISON =========
valid_views = ["Total", "E", "S", "G"]
current_view = read_query_param("view", "Total")
if current_view == "Combined":
    current_view = "Total"
if current_view not in valid_views:
    current_view = "Total"

view = st.sidebar.radio("Section", valid_views, index=valid_views.index(current_view))
comp_options = ["No comparison", "Country", "Sector", "Industry", "Custom peers"]
comp_default_label = PARAM_TO_COMP.get(comp_qp, "No comparison")
if comp_default_label not in comp_options:
    comp_default_label = "No comparison"
comparison = st.sidebar.selectbox("Comparison", comp_options, index=comp_options.index(comp_default_label))

if comparison == "Country" and not country_col:
    st.sidebar.info("No country column found; comparison will be disabled.")
if comparison == "Sector" and not sector_col:
    st.sidebar.info("No sector column found; comparison will be disabled.")
if comparison == "Industry" and not industry_col:
    st.sidebar.info("No industry column found; comparison will be disabled.")

# Custom peers (up to 4)
selected_custom_peers = []
label_col = firm_name_col if firm_name_col else firm_id_col
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

# --- SIDEBAR: peer firm list toggle -----------------------------------------
# Build the same peer set the charts use, based on current comparison mode
_peers_df, _n_peers, _peer_note = (None, 0, "")

if comparison == "Country" and country_col:
    _peers_df, _n_peers, _peer_note = build_peers(df, country_col, current_row)
elif comparison == "Sector" and sector_col:
    _peers_df, _n_peers, _peer_note = build_peers(df, sector_col, current_row)
elif comparison == "Industry" and industry_col:
    _peers_df, _n_peers, _peer_note = build_peers(df, industry_col, current_row)
elif comparison == "Custom peers":
    _peers_df, _n_peers, _peer_note = build_custom_peers(
        df, label_col, selected_custom_peers, current_row
    )

show_peer_list = st.sidebar.checkbox("Show peer firm list", value=False)

if show_peer_list:
    if _n_peers == 0 or _peers_df is None or _peers_df.empty:
        st.sidebar.info("No peers to display for the current selection.")
    else:
        # Decide which columns to show and give them clear headers
        _name_col = label_col  # prefer firm name if available; else ID
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

        _view = _peers_df[_cols].rename(columns=_ren).copy()

        st.sidebar.caption(
            f"Peers shown: {len(_view)}{_peer_note}"
        )
        st.sidebar.dataframe(
            _view,
            use_container_width=True,
            hide_index=True,
            height=300,
        )


# === ONE GLOBAL DISPLAY MODE TOGGLE (applies to Combined + Pillars) ===
mode_options = ["Charts", "Tables"]
mode_default_index = 0 if mode_qp == "charts" else 1
display_mode = st.sidebar.radio(
    "Display",
    mode_options,
    index=mode_default_index
)

# Keep URL in sync
params = {
    "view": view,
    "firm": str(firm_label),
    "comp": COMP_TO_PARAM.get(comparison, "none"),
    "mode": "charts" if display_mode == "Charts" else "tables",
    "v": VARIANT,  # keep variant shareable
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

# ========= COMBINED (chart/table with counts) =========
if view == "Total":
    # --- figure out peers ---
    comp_col = None
    comp_label = None
    peers = None
    n_peers = 0
    peer_note = ""

    if comparison == "Country" and country_col:
        comp_col = country_col
        comp_label = "Country mean"
        peers, n_peers, peer_note = build_peers(df, comp_col, current_row)
    elif comparison == "Sector" and sector_col:
        comp_col = sector_col
        comp_label = "Sector mean"
        peers, n_peers, peer_note = build_peers(df, comp_col, current_row)
    elif comparison == "Industry" and industry_col:
        comp_col = industry_col
        comp_label = "industry mean"
        peers, n_peers, peer_note = build_peers(df, comp_col, current_row)
    elif comparison == "Custom peers":
        comp_label = "Custom"
        peers, n_peers, peer_note = build_custom_peers(df, label_col, selected_custom_peers, current_row)
    
    firm_series = "Firm"
    comp_label_short = (comp_label or "").replace(" mean", "") if comp_label else None
    peers_series = f"Mean: {comp_label_short}" if comp_label_short else None


    if display_mode == "Tables":
        # === table summary per pillar ===
        summary_rows = []
        for pillar in ["E", "S", "G"]:
            pcols = pillar_columns(pillar, groups, by_pillar)
            total_DR = len(pcols)
    
            if total_DR:
                vals = current_row[pcols].astype(str).str.strip().str.lower()
                firm_yes = int(vals.isin(YES_SET).sum())
                if n_peers > 0:
                    peer_block = peers[pcols].astype(str).applymap(lambda x: x.strip().lower() in YES_SET)
                    peer_yes_mean = float(peer_block.sum(axis=1).mean()) if len(peer_block) else None
                else:
                    peer_yes_mean = None
            else:
                firm_yes = 0
                peer_yes_mean = None
    
            if VARIANT == "v2":
                row = {
                    "Pillar": PILLAR_LABEL[pillar],
                    "Reported disclosure requirements": firm_yes,
                    "Missing disclosure requirements": max(total_DR - firm_yes, 0),
                    "Total disclosure requirements": total_DR,
                }
                if peer_yes_mean is not None:
                    row[f"Peers — mean reported ({comp_label})"] = round(peer_yes_mean, 1)
    
            elif VARIANT == "v3":
                row = {
                    "Pillar": PILLAR_LABEL[pillar],
                    "Firm — number of reported Disclosure Requirements": firm_yes,
                    "Missing disclosure requirements": max(total_DR - firm_yes, 0),
                    "Total disclosure requirements": total_DR,
                }
                # (no peers column in v3 unless you want it)
    
            else:  # v1
                row = {
                    "Pillar": PILLAR_LABEL[pillar],
                    "Firm — number of Disclosure Requirements": firm_yes,
                }
                if peer_yes_mean is not None:
                    row[f"Peers — mean number of Disclosure Requirements ({comp_label})"] = round(peer_yes_mean, 1)
    
            summary_rows.append(row)
    
        tbl = pd.DataFrame(summary_rows)
    
        st.subheader("Total overview")
        st.dataframe(tbl, use_container_width=True, hide_index=True)
    
        # Variant-specific caption
        if VARIANT == "v2":
            note = ("Rows show how many Disclosure Requirements the firm reported "
                    "(**Reported disclosure requirements**), how many are unreported "
                    "(**Missing disclosure requirements**), and the pillar’s **Total**.")
        elif VARIANT == "v3":
            note = ("Rows show the firm’s reported DRs (**Firm — number of reported Disclosure Requirements**), "
                    "**Missing disclosure requirements** (= Total − Reported), and the pillar’s **Total**.")
        else:
            note = "Rows show the number of reported Disclosure Requirements per pillar."
        if n_peers > 0:
            note += peer_note
        st.caption(note)



    

      

    else:   
        # === stacked bars (counts by standard) ===
        perstd_rows = []
        pillar_reported  = {"E": 0, "S": 0, "G": 0}
        pillar_total     = {"E": 0, "S": 0, "G": 0}
        pillar_peers_rep = {"E": 0.0, "S": 0.0, "G": 0.0}  # NEW

        
        for std_code in STD_ORDER:
            if std_code not in groups:
                continue
            metrics_in_group = groups[std_code]
            label = SHORT_ESRS_LABELS.get(std_code, std_code)
            pillar = std_code[0]  # "E" | "S" | "G"
        
            vals = current_row[metrics_in_group].astype(str).str.strip().str.lower()
            firm_yes = int(vals.isin(YES_SET).sum())
        
            # accumulate pillar totals
            pillar_reported[pillar] += firm_yes
            pillar_total[pillar]    += len(metrics_in_group)
        
            perstd_rows.append({"StdCode": std_code, "Standard": label, "Series": firm_series, "Value": float(firm_yes)})
        
            if n_peers > 0:
                present_cols = [m for m in metrics_in_group if m in peers.columns]
                if present_cols:
                    peer_block = peers[present_cols].astype(str).applymap(lambda x: x.strip().lower() in YES_SET)
                    if len(peer_block) > 0 and peers_series is not None:
                        peer_yes_mean = float(peer_block.sum(axis=1).mean())
                        perstd_rows.append({
                            "StdCode": std_code, "Standard": label,
                            "Series": peers_series, "Value": float(peer_yes_mean)
                        })
                        pillar_peers_rep[pillar] += float(peer_yes_mean)  # NEW

        
        # --- append exactly three extra segments (only in v2/v3), one per pillar
        if VARIANT in ("v2", "v3"):
            # Firm missing segments
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
        
            # Peers missing segments (so Firm and Peers both stack to the same totals)
            if n_peers > 0 and peers_series:
                miss_vals_peers = {
                    "E_MISS": max(pillar_total["E"] - pillar_peers_rep["E"], 0.0),
                    "S_MISS": max(pillar_total["S"] - pillar_peers_rep["S"], 0.0),
                    "G_MISS": max(pillar_total["G"] - pillar_peers_rep["G"], 0.0),
                }
                for code, val in miss_vals_peers.items():
                    # allow zero; add only if there is any missing
                    if val > 1e-9:
                        p = code[0]
                        perstd_rows.append({
                            "StdCode": code,
                            "Standard": missing_label_for_variant(p),
                            "Series": peers_series,
                            "Value": float(val),
                        })

        
       
        chart_df = pd.DataFrame(perstd_rows)
        
        custom_order = ["E1","E2","E3","E4","E5","E_MISS","S1","S2","S3","S4","S_MISS","G1","G_MISS"]
        rank_map = {c:i for i,c in enumerate(custom_order)}
        chart_df["StdRank"] = chart_df["StdCode"].map(lambda c: rank_map.get(c, 9999))
        
        if not chart_df.empty:
            present_codes = [c for c in STD_ORDER if (chart_df["StdCode"] == c).any()]
        else:
            present_codes = STD_ORDER
        
        render_section_header("Total overview", [])
        if VARIANT in ("v2","v3"):
            render_inline_legend_with_missing(present_codes, STD_COLOR)
        else:
            render_inline_legend(present_codes, STD_COLOR)
        
        if not chart_df.empty:
            color_domain = present_codes + [c for c in MISSING_CODES if (chart_df["StdCode"] == c).any()]
            color_range = [
                STD_COLOR[c] if c in STD_COLOR else MISSING_COLOR.get(c, "#cccccc")
                for c in color_domain
            ]
        
            y_sort = [firm_series] + ([peers_series] if peers_series else [])
        
            # compute stacked x0/x1
            seg = chart_df.sort_values(["Series", "StdRank"]).copy()
            seg["x1"] = seg.groupby("Series")["Value"].cumsum()
            seg["x0"] = seg["x1"] - seg["Value"]
        
            # OPAQUE base rectangles (no transparency)
            rects = (
                alt.Chart(seg)
                  .mark_rect(stroke="#000", strokeWidth=1, strokeJoin="miter")
                  .encode(
                      y=alt.Y("Series:N", title="", sort=y_sort),
                      x=alt.X("x0:Q", title="Number of Disclosure Requirements reported", axis=alt.Axis(grid=True)),
                      x2="x1:Q",
                      color=alt.Color("StdCode:N", scale=alt.Scale(domain=color_domain, range=color_range), legend=None),
                      order=alt.Order("StdRank:Q"),
                      tooltip=[
                          alt.Tooltip("Series:N",   title="Series"),
                          alt.Tooltip("Standard:N", title="Segment"),
                          alt.Tooltip("Value:Q",    title="# DR", format=".1f"),
                      ],
                  )
            )
        
            # HATCH overlay only for missing (v2/v3); v1 stays solid
            layers = [rects]
            if VARIANT in ("v2","v3"):
                miss_only = seg[seg["StdCode"].isin(MISSING_CODES)].copy()
        
                def _make_stripes_df(d, step=1.0, stripe_width=0.35):
                    rows = []
                    for _, r in d.iterrows():
                        x0, x1 = float(r["x0"]), float(r["x1"])
                        x = x0
                        while x < x1:
                            xa = x
                            xb = min(x + stripe_width, x1)
                            rows.append({"Series": r["Series"], "xa": xa, "xb": xb})
                            x += step
                    return pd.DataFrame(rows)
        
                stripes_df = _make_stripes_df(miss_only)
                if not stripes_df.empty:
                    stripes = (
                        alt.Chart(stripes_df)
                          .mark_rect()
                          .encode(
                              y=alt.Y("Series:N", title="", sort=y_sort),
                              x=alt.X("xa:Q"),
                              x2="xb:Q",
                              color=alt.value("#ffffff")
                          )
                    )
                    layers.append(stripes)
        
            fig = alt.layer(*layers).properties(
                height=120, width="container",
                padding={"left": 12, "right": 12, "top": 6, "bottom": 6},
            ).configure_view(stroke=None)
        
            st.altair_chart(fig, use_container_width=True)
        
            note = "Bars show total counts of reported Disclosure Requirements, stacked by standard (E1–E5, S1–S4, G1)."
            if n_peers > 0:
                note += peer_note
            st.caption(note)
            

def render_pillar(pillar: str, title: str, comparison: str, display_mode: str):
    # which groups belong to this pillar
    pillar_groups = by_pillar.get(pillar, [])
    if not pillar_groups:
        st.info(f"No {pillar} columns found.")
        return

    # figure peers
    comp_col = None
    comp_label = None
    peers, n_peers, note = (None, 0, "")
    if comparison == "Country" and country_col:
        comp_col, comp_label = country_col, "country"
        peers, n_peers, note = build_peers(df, comp_col, current_row)
    elif comparison == "Sector" and sector_col:
        comp_col, comp_label = sector_col, "sector"
        peers, n_peers, note = build_peers(df, comp_col, current_row)
    elif comparison == "Industry" and industry_col:
        comp_col, comp_label = industry_col, "industry"
        peers, n_peers, note = build_peers(df, comp_col, current_row)
    elif comparison == "Custom peers":
        comp_label = "custom"
        peers, n_peers, note = build_custom_peers(df, (firm_name_col or firm_id_col), selected_custom_peers, current_row)

    # Which standards are in this pillar?
    if pillar == "E":
        stds_in_pillar = E_STANDARDS
    elif pillar == "S":
        stds_in_pillar = S_STANDARDS
    else:
        stds_in_pillar = G_STANDARDS

    # ===== Overview =====
    if display_mode == "Charts":
        st.markdown("### Overview")

        if VARIANT == "v1":
            # v1: reported-only bars per standard (no missing)
            render_inline_legend(stds_in_pillar, STD_COLOR)

            rows = []
            firm_series = "Firm"
            peers_series = f"Mean: {comp_label}" if n_peers > 0 else None

            for std_code in stds_in_pillar:
                # collect columns for this standard
                std_metrics = []
                for gname in pillar_groups:
                    if gname.split("-")[0] == std_code:
                        std_metrics.extend(groups[gname])

                vals = current_row[std_metrics].astype(str).str.strip().str.lower()
                firm_yes = int(vals.isin(YES_SET).sum())
                rows.append({"StdCode": std_code, "Standard": SHORT_ESRS_LABELS.get(std_code, std_code),
                             "Series": firm_series, "Value": float(firm_yes)})

                if n_peers > 0 and peers is not None:
                    present = [c for c in std_metrics if c in peers.columns]
                    if present:
                        pb = peers[present].astype(str).applymap(lambda x: x.strip().lower() in YES_SET)
                        rows.append({"StdCode": std_code,
                                     "Standard": SHORT_ESRS_LABELS.get(std_code, std_code),
                                     "Series": peers_series,
                                     "Value": float(pb.sum(axis=1).mean())})

            if rows:
               
                cdf = pd.DataFrame(rows)
                
                
                            st.caption("Counts of reported Disclosure Requirements within this pillar." + (note if n_peers > 0 else ""))
                            st.markdown("---")
                
                        else:
                            # v2 / v3: reported + hatched missing per standard; rows sum to fixed totals
                            render_pillar_legend_with_missing(stds_in_pillar, STD_COLOR, pillar)
                
                            rows = []
                            firm_series = "Firm"
                            peers_series = f"Mean: {comp_label}" if n_peers > 0 else None
                
                            for std_code in stds_in_pillar:
                                # Collect columns of this standard
                                std_metrics = []
                                for gname in pillar_groups:
                                    if gname.split("-")[0] == std_code:
                                        std_metrics.extend(groups[gname])
                
                                total_std = STD_TOTAL_OVERRIDES.get(std_code, len(std_metrics))
                
                                # Firm counts
                                vals = current_row[std_metrics].astype(str).str.strip().str.lower()
                                firm_yes = int(vals.isin(YES_SET).sum())
                                firm_miss = max(total_std - firm_yes, 0)
                
                                rows.append({"Cat": std_code,
                                             "Label": SHORT_ESRS_LABELS.get(std_code, std_code),
                                             "Series": firm_series, "Value": float(firm_yes)})
                                rows.append({"Cat": f"{std_code}_MISS",
                                             "Label": f"{SHORT_ESRS_LABELS.get(std_code, std_code)} — "
                                                      f"{'Not reported' if VARIANT=='v2' else 'Missing'}",
                                             "Series": firm_series, "Value": float(firm_miss)})
                
                                # Peers mean (reported + missing)
                                if n_peers > 0 and peers is not None:
                                    present = [c for c in std_metrics if c in peers.columns]
                                    if present:
                                        pb = peers[present].astype(str).applymap(lambda x: x.strip().lower() in YES_SET)
                                        peer_mean_rep = float(pb.sum(axis=1).mean())
                                    else:
                                        peer_mean_rep = 0.0
                                    peer_mean_miss = max(total_std - peer_mean_rep, 0.0)
                                    rows.append({"Cat": std_code,
                                                 "Label": SHORT_ESRS_LABELS.get(std_code, std_code),
                                                 "Series": peers_series, "Value": float(peer_mean_rep)})
                                    rows.append({"Cat": f"{std_code}_MISS",
                                                 "Label": f"{SHORT_ESRS_LABELS.get(std_code, std_code)} — "
                                                          f"{'Not reported' if VARIANT=='v2' else 'Missing'}",
                                                 "Series": peers_series, "Value": float(peer_mean_miss)})
                
                            if rows:
                                cdf = pd.DataFrame(rows)
                                # Order: E1, E1_MISS, E2, E2_MISS, ...
                                cat_order = []
                                for s in stds_in_pillar:
                                    cat_order.extend([s, f"{s}_MISS"])
                                rank_map = {c: i for i, c in enumerate(cat_order)}
                                cdf["CatRank"] = cdf["Cat"].map(rank_map).astype(int)
                
                                # Colors = base standard color (missing gets hatched styling via opacity/stroke)
                                domain = [c for c in cat_order if (cdf["Cat"] == c).any()]
                                rng    = [STD_COLOR.get(c.replace("_MISS", ""), "#999") for c in domain]
                
                                missing_cats = [f"{s}_MISS" for s in stds_in_pillar]
                                is_missing = alt.FieldOneOfPredicate(field="Cat", oneOf=missing_cats)
                                y_sort = [firm_series] + ([peers_series] if peers_series else [])
                
                                base = alt.Chart(cdf)
                                bars = (
                                    base
                                    .mark_bar(stroke="#000", strokeWidth=1, strokeOpacity=0.9, strokeJoin="miter")  # default outline
                                    .encode(
                                        y=alt.Y("Series:N", title="", sort=y_sort),
                                        x=alt.X("Value:Q", title="Number of Disclosure Requirements"),
                                        color=alt.Color("Cat:N", scale=alt.Scale(domain=domain, range=rng), legend=None),
                                        order=alt.Order("CatRank:Q"),
                                        opacity=alt.condition(is_missing, alt.value(0.35), alt.value(1.0)),
                                        # For *_MISS, override the stroke color (keeps your hatched look distinct)
                                        stroke=alt.condition(
                                            is_missing,
                                            alt.Color("Cat:N", scale=alt.Scale(domain=domain, range=rng)),
                                            alt.value("#000")
                                        ),
                                        strokeDash=alt.condition(is_missing, alt.value([5, 3]), alt.value([0, 0])),
                                        strokeWidth=alt.condition(is_missing, alt.value(2), alt.value(1)),
                                        tooltip=[
                                            alt.Tooltip("Series:N", title="Series"),
                                            alt.Tooltip("Label:N",  title="Segment"),
                                            alt.Tooltip("Value:Q",  title="# DR", format=".1f"),
                                        ],
                                    )
                                )
                
                
                                totals = (
                                    base.transform_aggregate(total="sum(Value)", groupby=["Series"])
                                        .mark_text(align="left", baseline="middle", dx=4)
                                        .encode(y=alt.Y("Series:N", sort=y_sort),
                                                x="total:Q", text=alt.Text("total:Q", format=".1f"))
                                )
                
                                fig = alt.layer(bars, totals).properties(
                                    height=120, width="container",
                                    padding={"left": 12, "right": 12, "top": 6, "bottom": 6},
                                ).configure_view(stroke=None)
                
                                st.altair_chart(fig, use_container_width=True)

                fixed_total = sum(STD_TOTAL_OVERRIDES.get(s, 0) for s in stds_in_pillar)
                st.caption(
                    f"Each standard shows reported (solid) and "
                    f"{'Not reported' if VARIANT=='v2' else 'Missing'} (hatched). "
                    f"Totals per row = {fixed_total}."
                    + (note if n_peers > 0 else "")
                )
            st.markdown("---")


    else:
        # ===== Overview (Tables mode) =====
        st.markdown("### Overview")

        summary_rows = []
        for std_code in stds_in_pillar:
            # collect columns for this standard
            std_metrics = []
            for gname in pillar_groups:
                if gname.split("-")[0] == std_code:
                    std_metrics.extend(groups[gname])

            total_std = STD_TOTAL_OVERRIDES.get(std_code, len(std_metrics))

            vals = current_row[std_metrics].astype(str).str.strip().str.lower()
            firm_yes = int(vals.isin(YES_SET).sum())
            missing = max(total_std - firm_yes, 0)

            # Peers mean (reported)
            peer_yes_mean = None
            if n_peers > 0 and peers is not None:
                present_cols = [m for m in std_metrics if m in peers.columns]
                if present_cols:
                    pb = peers[present_cols].astype(str).applymap(lambda x: x.strip().lower() in YES_SET)
                    peer_yes_mean = float(pb.sum(axis=1).mean())

            # Variant-specific columns
            row = {"Standard": SHORT_ESRS_LABELS.get(std_code, std_code)}
            if VARIANT == "v2":
                row["Reported disclosure requirements"] = firm_yes
                row["Missing disclosure requirements"] = missing
                row["Total disclosure requirements"] = total_std
            elif VARIANT == "v3":
                row["Firm — number of reported Disclosure Requirements"] = firm_yes
                row["Missing disclosure requirements"] = missing
                row["Total disclosure requirements"] = total_std
            else:
                row["Firm — number of Disclosure Requirements"] = firm_yes

            if peer_yes_mean is not None:
                row[f"Peers — mean number of Disclosure Requirements ({comp_label})"] = round(peer_yes_mean, 1)

            summary_rows.append(row)

        if summary_rows:
            tbl = pd.DataFrame(summary_rows)
            st.dataframe(tbl, use_container_width=True, hide_index=True)
            cap = "Rows show the number of reported Disclosure Requirements per ESRS standard in this pillar."
            if VARIANT in ("v2", "v3"):
                cap += " Includes each standard’s Total and Missing."
            if n_peers > 0:
                cap += note
            st.caption(cap)
            st.markdown("---")


    # ===== Per-standard detail (expanders) =====
    for g in pillar_groups:
        metrics = groups[g]
        base_code = g.split("-")[0]
        short_title = SHORT_ESRS_LABELS.get(base_code, base_code)
        n_metrics = len(metrics)

        # Firm & peers counts for header
        firm_yes_count = (current_row[metrics].astype(str).str.strip().str.lower().isin(YES_SET)).sum()
        peers_yes_mean = None
        if n_peers > 0 and peers is not None:
            present_cols = [m for m in metrics if m in peers.columns]
            if present_cols:
                pb = peers[present_cols].astype(str).applymap(lambda x: x.strip().lower() in YES_SET)
                if len(pb) > 0:
                    peers_yes_mean = float(pb.sum(axis=1).mean())

       
        if VARIANT == "v1":
            # v1: show only the short name like "E1 - Climate change"
            exp_title = short_title
        else:
            # v2/v3: keep the detailed title you had
            if peers_yes_mean is not None:
                exp_title = (
                    f"{short_title} • {n_metrics} Disclosure Requirements — "
                    f"reported: {firm_yes_count}/{n_metrics} "
                    f"(Peers {comp_label}: {peers_yes_mean:.1f}/{n_metrics})"
                )
            else:
                exp_title = (
                    f"{short_title} • {n_metrics} Disclosure Requirements — "
                    f"reported: {firm_yes_count}/{n_metrics}"
                )

        with st.expander(exp_title, expanded=False):
            if display_mode == "Tables":
                # Per-DR table with Code + Name + Reported (+ peers %)
                codes = [str(c).strip().split(" ")[0] for c in metrics]
                names = [DR_LABELS.get(code, "") for code in codes]
                firm_vals = [pretty_value(current_row.get(c, np.nan)) for c in metrics]

                table = pd.DataFrame({
                    "Code": codes,
                    "Name": names,
                    "Reported": firm_vals,
                })

                if n_peers > 0 and peers is not None:
                    peer_pct = []
                    for m in metrics:
                        if m in peers.columns:
                            s = peers[m].astype(str).str.strip().str.lower()
                            pct = (s.isin(YES_SET)).mean()
                            peer_pct.append(f"{pct*100:.1f}%")
                        else:
                            peer_pct.append("—")
                    table[f"Peers reported % ({comp_label})"] = peer_pct

                st.dataframe(table, use_container_width=True, hide_index=True)
                if n_peers > 0:
                    st.caption(f"Peers reported % = share of selected peers answering 'Yes' {note}")

            else:
                # Tile chart (Firm + optional peers %)
                ok_color = TILE_OK
                no_color = TILE_NO

                present_cols = [m for m in metrics if m in df.columns]
                if len(present_cols) == 0:
                    st.info("No Disclosure Requirements found for this group.")
                    continue

                def short_label(col: str) -> str:
                    s = str(col).strip()
                    return s.split(" ")[0] if " " in s else s

                def full_name(code: str) -> str:
                    return DR_LABELS.get(code, "")

                def is_yes(v) -> bool:
                    try:
                        return str(v).strip().lower() in YES_SET
                    except Exception:
                        return False

                labels = [short_label(c) for c in present_cols]
                tile_gap = 0.10
                eff_w = 1.0 - tile_gap

                rows = []
                for i, col in enumerate(present_cols):
                    code = short_label(col)
                    xa = i + tile_gap / 2.0
                    xb = i + 1 - tile_gap / 2.0
                    share = 1.0 if is_yes(current_row.get(col, "")) else 0.0
                    rows.append({
                        "Series": "Firm",
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
                        s = peers[col].astype(str).str.strip().str.lower() if col in peers.columns else pd.Series([])
                        share = float((s.isin(YES_SET)).mean()) if len(s) else 0.0
                        rows.append({
                            "Series": peers_label,
                            "Label": code, "Full": full_name(code),
                            "i": i, "xa": float(xa), "xb": float(xb),
                            "xg": float(xa + eff_w * share),
                            "share": float(share)
                        })

                tile_df = pd.DataFrame(rows)

                # Build chart
                tick_values = [i + 0.5 for i in range(len(present_cols))]
                labels_js = "[" + ",".join([repr(lbl) for lbl in labels]) + "]"
                label_expr = f"{labels_js}[floor(datum.value - 0.5)]"

                xscale = alt.Scale(domain=[0, len(present_cols)], nice=False, zero=True)
                x_axis = alt.Axis(values=tick_values, tickSize=0, labelAngle=0, labelPadding=6,
                                  labelExpr=label_expr, title=None)

                y_enc = alt.Y(
                    "Series:N",
                    sort=["Firm"] + ([peers_label] if peers_label else []),
                    title="",
                    scale=alt.Scale(paddingInner=0.65, paddingOuter=0.28),
                    axis=alt.Axis(labels=True, ticks=False, domain=False)
                )

                tile_tooltip = [
                    alt.Tooltip("Label:N", title="Code"),
                    alt.Tooltip("Full:N",  title="Name"),
                    alt.Tooltip("Series:N", title="Series"),
                    alt.Tooltip("share:Q",  title="% reported", format=".0%"),
                ]

                base = alt.Chart(tile_df)

                # background cells
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

                # filled portion = reported share
                green = (
                    base.mark_rect(stroke="white", strokeWidth=0.8)
                        .encode(
                            y=y_enc,
                            x="xa:Q",
                            x2="xg:Q",
                            color=alt.value(ok_color),
                            tooltip=tile_tooltip,
                        )
                        .transform_filter("datum.share > 0")
                )

                # percent labels on peers bars (only when >=10%)
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

                fig = alt.layer(*([red, green] + ([pct_text] if pct_text is not None else []))).properties(
                    width=total_width,
                    height=alt.Step(50),
                    padding={"left": 12, "right": 12, "top": 6, "bottom": 8},
                ).configure_view(stroke=None)

                st.altair_chart(fig, use_container_width=True)
                st.caption(
                    f"{len(present_cols)} Tiles = Disclosure Requirements within this ESRS standard. "
                    "Tiles: filled = reported, light = not reported. "
                    + (f"Peer tiles: fill equals % of peers that reported (shown as %). " if peers_label else "")
                    + (note if peers_label else "")
                )


# ========= Which pillar to render =========
if view == "E":
    render_pillar("E", "E — Environment", comparison, display_mode)
elif view == "S":
    render_pillar("S", "S — Social", comparison, display_mode)
elif view == "G":
    render_pillar("G", "G — Governance", comparison, display_mode)
