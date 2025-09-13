# esg_app.py — DR Viewer (GitHub auto-load; Country/Industry/Custom comparison)
# Requirements: streamlit, pandas, numpy, altair, requests, openpyxl

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

# ========= LOAD DATA (GitHub only) =========
st.sidebar.title("🌱 Disclosure Requirements Viewer")

# Dev/testing: force a variant from the sidebar when DEV_MODE is on
if DEV_MODE:
    forced = st.sidebar.selectbox("Dev: force variant", VARIANT_KEYS, index=VARIANT_KEYS.index(VARIANT))
    if forced != VARIANT:
        VARIANT = forced
        st.session_state["variant"] = forced
        # persist in URL
        try:
            st.query_params.update({"v": forced})
        except Exception:
            cur = st.experimental_get_query_params()
            cur["v"] = forced
            st.experimental_set_query_params(**cur)

st.sidebar.caption(f"Variant: **{VARIANT.upper()}**")

df = load_table(DEFAULT_DATA_URL)
if df.empty:
    st.stop()

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

# Buttons row: Open report + Show auditor side-by-side
btn_col1, btn_col2, _sp = st.columns([1, 1, 6])

with btn_col1:
    if link_url:
        try:
            st.link_button("Open firm report", link_url)
        except Exception:
            st.markdown(
                f'<a href="{link_url}" target="_blank" rel="noopener noreferrer">Open firm report ↗</a>',
                unsafe_allow_html=True,
            )
    else:
        st.caption("No report link available")

with btn_col2:
    try:
        with st.popover("Show auditor"):
            st.markdown(f"**Auditor:** {auditor_val}")
    except Exception:
        if st.button("Show auditor"):
            st.info(f"Auditor: {auditor_val}")
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
                # v2: Reported + Total
                row = {
                    "Pillar": PILLAR_LABEL[pillar],
                    "Reported disclosure requirements": firm_yes,
                    "Total disclosure requirements": total_DR,
                }
                # (optional) keep peers mean if available, renamed for clarity
                if peer_yes_mean is not None:
                    row[f"Peers — mean reported ({comp_label})"] = round(peer_yes_mean, 1)
    
            elif VARIANT == "v3":
                # v3: three columns — Firm reported, Missing, Total
                missing = max(total_DR - firm_yes, 0)
                row = {
                    "Pillar": PILLAR_LABEL[pillar],
                    "Firm — number of reported Disclosure Requirements": firm_yes,
                    "Missing disclosure requirements": missing,
                    "Total disclosure requirements": total_DR,
                }
                # (intentionally no peers column here to match your spec)
    
            else:
                # v1: original naming
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
            note = (
                "Rows show how many Disclosure Requirements the firm reported "
                "(**Reported disclosure requirements**) and the pillar’s total possible "
                "(**Total disclosure requirements**)."
            )
        elif VARIANT == "v3":
            note = (
                "Rows show the firm’s reported DRs (**Firm — number of reported Disclosure Requirements**), "
                "how many are unreported (**Missing disclosure requirements** = Total − Reported), and "
                "the pillar’s **Total disclosure requirements**."
            )
        else:
            note = "Rows show the number of reported Disclosure Requirements per pillar."
    
        if n_peers > 0:
            note += peer_note
        st.caption(note)



    else:
        # === CHARTS MODE ===
        if VARIANT in ("v2", "v3"):
            # ===== Aggregated E / S / G with patterned "not reported / missing" =====
            NOTREPORTED_LABEL = "Not reported" if VARIANT == "v2" else "Missing"
    
            agg_rows = []
            for pillar in ["E", "S", "G"]:
                pcols = pillar_columns(pillar, groups, by_pillar)
                total_DR = len(pcols)
    
                if total_DR == 0:
                    continue
    
                vals = current_row[pcols].astype(str).str.strip().str.lower()
                firm_yes = int(vals.isin(YES_SET).sum())
                missing = max(total_DR - firm_yes, 0)
    
                pill_name = PILLAR_LABEL[pillar]
                agg_rows.append({"Pillar": pillar, "PillarName": pill_name, "Status": "Reported",         "Value": float(firm_yes)})
                agg_rows.append({"Pillar": pillar, "PillarName": pill_name, "Status": NOTREPORTED_LABEL, "Value": float(missing)})
    
            agg_df = pd.DataFrame(agg_rows)
            if agg_df.empty:
                st.info("No Disclosure Requirements detected for E, S, or G.")
            else:
                # Color by pillar (E green, S red, G yellow)
                color_domain = ["E", "S", "G"]
                color_range  = [PALETTE_E[0], PALETTE_S[0], PALETTE_G[0]]
                # Try to use Vega-Lite fill pattern (diagonal stripes) for the not-reported/missing part.
                # If the runtime Altair/Vega-Lite doesn't support patterns, it will gracefully fall back to solid fill.
                base = alt.Chart(agg_df)
    
                bars = (
                    base
                    .mark_bar()
                    .encode(
                        y=alt.Y("PillarName:N", title="", sort=[PILLAR_LABEL[p] for p in ["E","S","G"]]),
                        x=alt.X("Value:Q", stack="zero", title="Number of Disclosure Requirements"),
                        color=alt.Color("Pillar:N",
                                        scale=alt.Scale(domain=color_domain, range=color_range),
                                        legend=alt.Legend(title="Pillar")),
                        tooltip=[
                            alt.Tooltip("PillarName:N", title="Pillar"),
                            alt.Tooltip("Status:N",     title="Status"),
                            alt.Tooltip("Value:Q",      title="# DR", format=".0f"),
                        ],
                    )
                )
    
                # Patterned fill for the "not reported / missing" segment (diagonal stripes)
                # Vega-Lite 5 pattern channel: fillPattern. Altair >=5 exposes it via FillPattern.
                try:
                    bars = bars.encode(
                        fillPattern=alt.FillPattern(
                            "Status:N",
                            legend=alt.Legend(title=""),
                            scale=alt.Scale(
                                domain=["Reported", NOTREPORTED_LABEL],
                                range=[None, "diagonal-right-left"]  # reported = solid, missing = ///
                            ),
                        )
                    )
                except Exception:
                    # If fillPattern isn't supported in the runtime, fall back to lower opacity
                    bars = bars.encode(
                        opacity=alt.condition(
                            alt.datum.Status == NOTREPORTED_LABEL,
                            alt.value(0.45),
                            alt.value(1.0),
                        )
                    )
    
                # Totals annotation at the end of each bar
                totals = (
                    base
                    .transform_aggregate(Total="sum(Value)", groupby=["PillarName"])
                    .mark_text(align="left", baseline="middle", dx=4)
                    .encode(
                        y=alt.Y("PillarName:N", sort=[PILLAR_LABEL[p] for p in ["E","S","G"]]),
                        x="Total:Q",
                        text=alt.Text("Total:Q", format=".0f"),
                    )
                )
    
                # Inline legend to show the patterned status label explicitly
                # (Only needed when pattern is not rendered; harmless otherwise)
                st.markdown(
                    f"""
                    <style>
                      .status-legend {{ display:flex; gap:1rem; align-items:center; margin:.25rem 0 .5rem 0; }}
                      .swatch {{
                        width:14px; height:14px; border-radius:2px; display:inline-block; position:relative; overflow:hidden;
                      }}
                      .swatch.e {{ background:{PALETTE_E[0]}; }}
                      .swatch.s {{ background:{PALETTE_S[0]}; }}
                      .swatch.g {{ background:{PALETTE_G[0]}; }}
                      .swatch.stripe:before {{
                        content:""; position:absolute; inset:0;
                        background: repeating-linear-gradient(135deg, rgba(255,255,255,.0) 0 6px, rgba(255,255,255,.45) 6px 10px);
                        mix-blend-mode: screen;
                      }}
                    </style>
                    <div class="status-legend">
                      <div><span class="swatch e"></span> Reported (E)</div>
                      <div><span class="swatch s"></span> Reported (S)</div>
                      <div><span class="swatch g"></span> Reported (G)</div>
                      <div><span class="swatch e stripe"></span> {NOTREPORTED_LABEL} (E)</div>
                      <div><span class="swatch s stripe"></span> {NOTREPORTED_LABEL} (S)</div>
                      <div><span class="swatch g stripe"></span> {NOTREPORTED_LABEL} (G)</div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
    
                render_section_header("Total overview", ["E","S","G"])
                fig = alt.layer(bars, totals).properties(
                    height=150,
                    width="container",
                    padding={"left": 12, "right": 12, "top": 6, "bottom": 6},
                ).configure_view(stroke=None)
    
                st.altair_chart(fig, use_container_width=True)
    
            note = (
                f"Bars show **reported** vs **{NOTREPORTED_LABEL.lower()}** Disclosure Requirements aggregated by pillar."
            )
            if n_peers > 0:
                note += peer_note
            st.caption(note)
    
        else:
        # === CHARTS MODE on Total ===
    
        # Build per-standard rows (unchanged v1 behaviour preserved)
        perstd_rows = []
        for std_code in STD_ORDER:
            if std_code not in groups:
                continue
            metrics_in_group = groups[std_code]
            label = SHORT_ESRS_LABELS.get(std_code, std_code)
    
            vals = current_row[metrics_in_group].astype(str).str.strip().str.lower()
            firm_yes = int(vals.isin(YES_SET).sum())
            perstd_rows.append({"StdCode": std_code, "Standard": label, "Series": firm_series, "Value": float(firm_yes)})
    
            if n_peers > 0:
                present_cols = [m for m in metrics_in_group if m in peers.columns]
                if present_cols:
                    peer_block = peers[present_cols].astype(str).applymap(lambda x: x.strip().lower() in YES_SET)
                    if len(peer_block) > 0 and peers_series is not None:
                        peer_yes_mean = float(peer_block.sum(axis=1).mean())
                        perstd_rows.append({"StdCode": std_code, "Standard": label, "Series": peers_series, "Value": float(peer_yes_mean)})
    
        chart_df = pd.DataFrame(perstd_rows)
        chart_df["StdRank"] = chart_df["StdCode"].map(STD_RANK).fillna(9999)
        chart_df["Status"]  = "Reported"  # tag standards as reported
        chart_df["Pillar"]  = chart_df["StdCode"].str[0]
    
        # ---- ADD: three extra synthetic segments for aggregated missing per pillar (v2/v3 only)
        NOT_LABEL = "Not reported" if VARIANT == "v2" else "Missing"
        extra_rows = []
        if VARIANT in ("v2", "v3"):
            for pillar in ["E", "S", "G"]:
                pcols = pillar_columns(pillar, groups, by_pillar)
                if not pcols:
                    continue
                vals = current_row[pcols].astype(str).str.strip().str.lower()
                firm_yes = int(vals.isin(YES_SET).sum())
                missing = max(len(pcols) - firm_yes, 0)
                if missing > 0:
                    syn_code = f"{pillar}_MISSING"  # won't collide with standards
                    pillar_hex = PALETTE_E[0] if pillar == "E" else (PALETTE_S[0] if pillar == "S" else PALETTE_G[0])
                    extra_rows.append({
                        "StdCode": syn_code,
                        "Standard": f"{pillar} {NOT_LABEL.lower()}",
                        "Series": firm_series,
                        "Value": float(missing),
                        "StdRank": 99999,          # put after real standards
                        "Status": NOT_LABEL,       # for hatching
                        "Pillar": pillar,
                        "ColorHex": pillar_hex,    # direct pillar color
                    })
    
        extra_df   = pd.DataFrame(extra_rows)
        combined_df = pd.concat([chart_df, extra_df], ignore_index=True)
    
        # === Legend header: use ONLY actual standards to avoid KeyError
        if not chart_df.empty:
            present_codes = [c for c in STD_ORDER if (chart_df["StdCode"] == c).any()]
        else:
            present_codes = STD_ORDER  # fallback
        render_section_header("Total overview", present_codes)  
    
        if not combined_df.empty:
            # Color: use hex per row (standards via STD_COLOR, synthetic already set)
            def _std_hex(code):
                return STD_COLOR.get(code, "#999999")
            if "ColorHex" not in combined_df.columns:
                combined_df["ColorHex"] = None
            mask_nohex = combined_df["ColorHex"].isna()
            combined_df.loc[mask_nohex, "ColorHex"] = combined_df.loc[mask_nohex, "StdCode"].map(_std_hex)
    
            color_enc = alt.Color("ColorHex:N", scale=None, legend=None)
            y_sort    = [firm_series] + ([peers_series] if peers_series else [])
            base      = alt.Chart(combined_df)
    
            bars = (
                base
                .mark_bar()
                .encode(
                    y=alt.Y("Series:N", title="", sort=y_sort),
                    x=alt.X("Value:Q", title="Number of Disclosure Requirements", stack="zero"),
                    color=color_enc,
                    order=alt.Order("StdRank:Q"),
                    tooltip=[
                        alt.Tooltip("Series:N",   title="Series"),
                        alt.Tooltip("StdCode:N",  title="Segment"),
                        alt.Tooltip("Value:Q",    title="# DR", format=".0f"),
                    ],
                )
            )
    
            # Hatching only on the synthetic NOT_LABEL rows
            try:
                bars = bars.encode(
                    fillPattern=alt.FillPattern(
                        "Status:N",
                        legend=None,
                        scale=alt.Scale(domain=["Reported", NOT_LABEL], range=[None, "diagonal-right-left"]),
                    )
                )
            except Exception:
                # Fallback if pattern not supported
                bars = bars.encode(
                    opacity=alt.condition(alt.datum.Status == NOT_LABEL, alt.value(0.45), alt.value(1.0))
                )
    
            totals = (
                base
                .transform_aggregate(total="sum(Value)", groupby=["Series"])
                .mark_text(align="left", baseline="middle", dx=4)
                .encode(y=alt.Y("Series:N", sort=y_sort), x="total:Q", text=alt.Text("total:Q", format=".1f"))
            )
    
            fig = alt.layer(bars, totals).properties(
                height=120, width="container",
                padding={"left": 12, "right": 12, "top": 6, "bottom": 6},
            ).configure_view(stroke=None)
            st.altair_chart(fig, use_container_width=True)
    
            # === Add a small hatched legend for the synthetic segments (under the standards legend)
            #     v2 -> "not reported", v3 -> "missing"
            lab_suffix = "not reported" if VARIANT == "v2" else "missing"
            st.markdown(
                f"""
                <style>
                  .status-legend {{ display:flex; flex-wrap:wrap; gap:0.75rem 1.25rem; align-items:center; margin-top:.25rem; }}
                  .swatch {{ width:14px; height:14px; border-radius:2px; display:inline-block; position:relative; overflow:hidden; }}
                  .e {{ background:{PALETTE_E[0]}; }} .s {{ background:{PALETTE_S[0]}; }} .g {{ background:{PALETTE_G[0]}; }}
                  .stripe:before {{
                    content:""; position:absolute; inset:0;
                    background: repeating-linear-gradient(135deg,
                                                         rgba(255,255,255,.0) 0 6px,
                                                         rgba(255,255,255,.45) 6px 10px);
                    mix-blend-mode: screen;
                  }}
                  .status-legend .lab {{ font-size:0.9rem; margin-left:.35rem; }}
                </style>
                <div class="status-legend">
                  <div><span class="swatch e stripe"></span><span class="lab">E {lab_suffix}</span></div>
                  <div><span class="swatch s stripe"></span><span class="lab">S {lab_suffix}</span></div>
                  <div><span class="swatch g stripe"></span><span class="lab">G {lab_suffix}</span></div>
                </div>
                """,
                unsafe_allow_html=True,
            )
    
        note = (
            "Bars show total counts of **reported Disclosure Requirements per standard** (E1–E5, S1–S4, G1). "
            f"The hatched segments add **pillar-level {NOT_LABEL.lower()}** DRs (E/S/G)."
        )
        if n_peers > 0:
            note += peer_note
        st.caption(note)

    
    # ===== standards detail (E1/E2/...) as before =====
    for g in pillar_groups:
        metrics = groups[g]

        # ==== Aggregate counts for expander header ====
        firm_yes_count = 0
        for m in metrics:
            v = str(current_row.get(m, "")).strip().lower()
            if v in YES_SET:
                firm_yes_count += 1

        peers_yes_mean = None
        if n_peers > 0:
            present_cols = [m for m in metrics if m in peers.columns]
            if present_cols:
                peer_block = peers[present_cols].astype(str).applymap(lambda x: x.strip().lower() in YES_SET)
                if len(peer_block) > 0:
                    peers_yes_mean = float(peer_block.sum(axis=1).mean())

        base_code = g.split("-")[0]
        short_title = SHORT_ESRS_LABELS.get(base_code, base_code)
        n_metrics = len(metrics)
        if VARIANT == "v1":
            # v1: title only, no counts
            exp_title = f"{short_title}"
        else:
            # v2 & v3: include counts (and peers if available)
            if peers_yes_mean is not None:
                exp_title = (
                    f"{short_title} • {n_metrics} Disclosure Requirements — reported: "
                    f"{firm_yes_count}/{n_metrics} (Peers {comp_label}: {peers_yes_mean:.1f}/{n_metrics})"
                )
            else:
                exp_title = (
                    f"{short_title} • {n_metrics} Disclosure Requirements — reported: "
                    f"{firm_yes_count}/{n_metrics}"
                )


        with st.expander(exp_title, expanded=False):
            if display_mode == "Tables":
                # Build a row per Disclosure Requirement in this standard
                rows = []
                for m in metrics:
                    code = str(m).strip().split(" ")[0]  # e.g., "E1-1"
                    name = DR_LABELS.get(code, "")       # long label from your mapping
                    reported = pretty_value(current_row.get(m, np.nan))
        
                    row = {
                        "Code": code,
                        "Name": name,
                        "Reported": reported,
                    }
        
                    if n_peers > 0:
                        if m in peers.columns:
                            s = peers[m].astype(str).str.strip().str.lower()
                            pct = (s.isin(YES_SET)).mean()
                            row[f"Peers reported % ({comp_label})"] = f"{pct*100:.1f}%"
                        else:
                            row[f"Peers reported % ({comp_label})"] = "—"
        
                    rows.append(row)
        
                table = pd.DataFrame(rows)
                st.dataframe(table, use_container_width=True, hide_index=True)
        
                if n_peers > 0:
                    st.caption(f"Peers reported % = share of selected peers answering 'Yes'{note}")

            else:
                # === CHART MODE: labeled tile bar per ESRS group (schema-safe, single layered chart) ===
                # new (primary blue + light blue)
                ok_color = TILE_OK
                no_color = TILE_NO



                present_cols = [m for m in metrics if m in df.columns]
                n_tiles = len(present_cols)
                if n_tiles == 0:
                    st.info("No Disclosure Requirements found for this group.")
                    continue

                def short_label(col: str) -> str:
                    s = str(col).strip()
                    return s.split(" ")[0] if " " in s else s  # e.g., "E1-1"

                def full_name(code: str) -> str:
                    return DR_LABELS.get(code, "")


                def is_yes(v) -> bool:
                    try:
                        return str(v).strip().lower() in YES_SET
                    except Exception:
                        return False

                labels = [short_label(c) for c in present_cols]

                def full_name(code: str) -> str:
                    return DR_LABELS.get(code, "")

                # tile geometry: we draw quantitative x with [0..n_tiles], each tile ~1 wide minus a gutter
                tile_gap = 0.10
                eff_w = 1.0 - tile_gap

                rows = []
                # Firm tiles
                for i, col in enumerate(present_cols):
                    code = short_label(col) 
                    xa = i + tile_gap / 2.0
                    xb = i + 1 - tile_gap / 2.0
                    xmid = (xa + xb) / 2.0
                    share = 1.0 if is_yes(current_row.get(col, "")) else 0.0
                    rows.append({
                        "Series": "Firm",
                        "Label": code,              # short (e.g., E1-1)
                        "Full": full_name(code),    # long hover label
                        "i": i, "xa": float(xa), "xb": float(xb),
                        "xmid": float(xmid), "share": float(share)
                    })

                # Peers tiles (if available)
                peers_label = None
                if n_peers > 0:
                    peers_label = "Mean:" + f" {comp_label}" if comp_label else ""
                    for i, col in enumerate(present_cols):
                        code = short_label(col) 
                        xa = i + tile_gap / 2.0
                        xb = i + 1 - tile_gap / 2.0
                        xmid = (xa + xb) / 2.0
                        s = peers[col].astype(str).str.strip().str.lower()
                        share = float((s.isin(YES_SET)).mean())
                        rows.append({
                            "Series": peers_label,
                            "Label": code,               # short
                            "Full": full_name(code),     # long
                            "i": i, "xa": float(xa), "xb": float(xb),
                            "xmid": float(xmid), "share": float(share)
                        })

                tile_df = pd.DataFrame(rows)
                tile_df["xg"] = tile_df["xa"] + eff_w * tile_df["share"]  # end of green overlay per tile

                series_order = ["Firm"] + ([peers_label] if peers_label else [])
                tile_tooltip = [
                    alt.Tooltip("Label:N", title="Code"),
                    alt.Tooltip("Full:N",  title="Name"),
                    alt.Tooltip("Series:N", title="Series"),
                    alt.Tooltip("share:Q",  title="% reported", format=".0%"),
                ]

                # Build an x-axis that shows sub-standard labels at tile centers via labelExpr
                tick_values = [i + 0.5 for i in range(n_tiles)]
                # JS array of labels for the labelExpr
                labels_js = "[" + ",".join([repr(lbl) for lbl in labels]) + "]"
                label_expr = f"{labels_js}[floor(datum.value - 0.5)]"

                xscale = alt.Scale(domain=[0, n_tiles], nice=False, zero=True)
                x_axis = alt.Axis(values=tick_values, tickSize=0, labelAngle=0, labelPadding=6,
                                  labelExpr=label_expr, title=None)

                y_enc = alt.Y(
                    "Series:N",
                    sort=series_order,
                    title="",
                    scale=alt.Scale(paddingInner=0.65, paddingOuter=0.28),
                    axis=alt.Axis(labels=True, ticks=False, domain=False)
                )

                base = alt.Chart(tile_df)

                # Red base (full tile width)
                red = (
                    base
                    .mark_rect(stroke="white", strokeWidth=0.8)
                    .encode(
                        y=y_enc,
                        x=alt.X("xa:Q", scale=xscale, axis=x_axis),
                        x2="xb:Q",
                        color=alt.value(no_color),
                        tooltip=[
                            alt.Tooltip("Label:N", title="Code"),
                            alt.Tooltip("Full:N",  title="Name"),
                            alt.Tooltip("Series:N", title="Series"),
                            alt.Tooltip("share:Q",  title="% reported", format=".0%"),
                        ],
                    )
                )

                # Green overlay (partial width = share)
                green = (
                    base
                    .mark_rect(stroke="white", strokeWidth=0.8)
                    .encode(
                        y=y_enc,
                        x="xa:Q",
                        x2="xg:Q",
                        color=alt.value(ok_color),
                        tooltip=tile_tooltip,     # ✅ add this line
                    )
                    .transform_filter("datum.share > 0")
                )


                # Peer % text centered in peer tiles (hide when tiny)
                pct_text = None
                if peers_label:
                    pct_text = (
                        base
                        .transform_filter(alt.FieldEqualPredicate(field="Series", equal=peers_label))
                        .transform_filter("datum.share >= 0.10")
                        .transform_calculate(
                            xtext="datum.xa + (datum.xb - datum.xa) * datum.share * 0.35"
                        )
                        .mark_text(baseline="middle", fontSize=11, color="white")
                        .encode(
                            y=y_enc,
                            x=alt.X("xtext:Q", scale=xscale),
                            text=alt.Text("share:Q", format=".0%"),
                            tooltip=tile_tooltip,   # ✅ add this line
                        )
                    )
                

                px_per_tile = 28  # adjust density
                total_width = max(240, int(px_per_tile * n_tiles))

                fig = alt.layer(*( [red, green] + ([pct_text] if pct_text is not None else []) )).properties(
                    width=total_width,
                    height=alt.Step(50),
                    padding={"left": 12, "right": 12, "top": 6, "bottom": 8},
                ).configure_view(
                    stroke=None
                )

                st.altair_chart(fig, use_container_width=True)
                st.caption(
                    f"{n_tiles} Tiles = Disclosure Requirements within this ESRS standard. "
                    "Tiles: green = reported, red = not reported. "
                    + (f"Peer tiles: green fill equals % of peers that reported (shown as %). " if peers_label else "")
                    + (note if peers_label else "")
                )


# ========= Which pillar to render =========
if view == "E":
    render_pillar("E", "E — Environment", comparison, display_mode)
elif view == "S":
    render_pillar("S", "S — Social", comparison, display_mode)
elif view == "G":
    render_pillar("G", "G — Governance", comparison, display_mode)
