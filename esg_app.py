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

st.set_page_config(page_title="DR Viewer", page_icon="🌱", layout="wide")
st.markdown(
    """
<style>
.firm-meta{
  font-size: 1.05rem;
  line-height: 1.45;
  margin-top: -0.25rem;
}
@media (prefers-color-scheme: dark){
  .firm-meta{}
}
</style>
""",
    unsafe_allow_html=True,
)

# ========= CONFIG =========
# Hard-wired GitHub file (blob URL is fine; we convert to RAW internally)
DEFAULT_DATA_URL = "https://github.com/akgrossk/srn_dr_list/blob/main/DR_extract.xlsx"

# Columns used for firm selection (auto-detected)
FIRM_NAME_COL_CANDIDATES = ["name", "company", "firm"]
FIRM_ID_COL_CANDIDATES   = ["isin", "ticker"]
COUNTRY_COL_CANDIDATES   = ["country", "Country"]
INDUSTRY_COL_CANDIDATES  = ["industry", "Industry", "sector", "Sector"]

YES_SET = {"yes", "ja", "true", "1"}
NO_SET  = {"no", "nein", "false", "0"}
PILLAR_LABEL = {"E": "Environment", "S": "Social", "G": "Governance"}

# ESRS group display names (for expander headers)
ESRS_LABELS = {
    "E1": "ESRS E1 — Climate change",
    "E2": "ESRS E2 — Pollution",
    "E3": "ESRS E3 — Water and marine resources",
    "E4": "ESRS E4 — Biodiversity and ecosystems",
    "E5": "ESRS E5 — Resource use and circular economy",
    "S1": "ESRS S1 — Own workforce",
    "S2": "ESRS S2 — Workers in the value chain",
    "S3": "ESRS S3 — Affected communities",
    "S4": "ESRS S4 — Consumers and end‑users",
    "G1": "ESRS G1 — Governance and business conduct",
}

# Short labels for expander titles (no "ESRS" prefix, ASCII hyphen)
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

# For query-param encoding/decoding of comparison mode
COMP_TO_PARAM = {
    "No comparison": "none",
    "Country": "country",
    "Industry": "industry",
    "Custom": "custom",
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
    # Fetch from GitHub (public or private with token)
    u = normalize_github_raw_url(url)
    headers = {}
    try:
        token = st.secrets.get("GITHUB_TOKEN")  # optional for private repos
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

# ========= LOAD DATA (GitHub only) =========
st.sidebar.title("🌱 DR Viewer")
df = load_table(DEFAULT_DATA_URL)
if df.empty:
    st.stop()  # error shown already

# ========= DETECT COLUMNS & PRE-READ URL STATE =========
firm_name_col = first_present(df.columns, FIRM_NAME_COL_CANDIDATES)
firm_id_col   = first_present(df.columns, FIRM_ID_COL_CANDIDATES)
country_col   = first_present(df.columns, COUNTRY_COL_CANDIDATES)
industry_col  = first_present(df.columns, INDUSTRY_COL_CANDIDATES)

# Read selections from URL so they persist when clicking chart links
firm_qp  = read_query_param("firm", None)
comp_qp  = (read_query_param("comp", "none") or "none").lower()
peers_qp = read_query_param("peers", "")
preselected_peers = [p for p in peers_qp.split(",") if p] if peers_qp else []

# ========= FIRM PICKER (no preselected firm unless in URL) =========
if firm_name_col:
    firms = df[firm_name_col].dropna().astype(str).unique().tolist()
    default_index = firms.index(firm_qp) if (firm_qp in firms) else None
    try:
        firm_label = st.sidebar.selectbox("Firm", firms, index=default_index, placeholder="Select a firm…")
    except TypeError:
        # Older Streamlit fallback
        options = ["— Select firm —"] + firms
        idx = 0 if firm_qp is None else (options.index(firm_qp) if firm_qp in options else 0)
        firm_label = st.sidebar.selectbox("Firm", options, index=idx)
        if firm_label == "— Select firm —":
            st.stop()
    if not firm_label:
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
            st.stop()
    if not firm_label:
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
isin_txt    = f"ISIN: <strong>{current_row.get(firm_id_col, 'n/a')}</strong>" if firm_id_col else ""
country_txt = f"Country: <strong>{current_row.get(country_col, 'n/a')}</strong>" if country_col else ""
industry_txt= f"Industry: <strong>{current_row.get(industry_col, 'n/a')}</strong>" if industry_col else ""
sub = " · ".join([t for t in [isin_txt, country_txt, industry_txt] if t])
if sub:
    st.markdown(f"<div class='firm-meta'>{sub}</div>", unsafe_allow_html=True)

link_ar = str(current_row.get("Link_AR", "")).strip()
if link_ar and link_ar.lower().startswith(("http://", "https://")):
    try:
        st.link_button("Open firm report", link_ar)
    except Exception:
        st.markdown(
            f'<a href="{link_ar}" target="_blank" rel="noopener noreferrer">Open firm report ↗</a>',
            unsafe_allow_html=True,
        )

# ========= NAV & COMPARISON =========
valid_views = ["Combined", "E", "S", "G"]
current_view = read_query_param("view", "Combined")
if current_view not in valid_views:
    current_view = "Combined"

view = st.sidebar.radio("Section", valid_views, index=valid_views.index(current_view))
comp_options = ["No comparison", "Country", "Industry", "Custom"]
comp_default_label = PARAM_TO_COMP.get(comp_qp, "No comparison")
if comp_default_label not in comp_options:
    comp_default_label = "No comparison"
comparison = st.sidebar.selectbox("Comparison", comp_options, index=comp_options.index(comp_default_label))

if comparison == "Country" and not country_col:
    st.sidebar.info("No country column found; comparison will be disabled.")
if comparison == "Industry" and not industry_col:
    st.sidebar.info("No industry column found; comparison will be disabled.")

# Custom peers (up to 4), default from URL
selected_custom_peers = []
label_col = firm_name_col if firm_name_col else firm_id_col
if comparison == "Custom" and label_col:
    all_firms = df[label_col].dropna().astype(str).unique().tolist()
    # Exclude current firm from options
    try:
        all_firms = [f for f in all_firms if str(f) != str(current_row.get(label_col, ""))]
    except Exception:
        pass
    default_peers = [p for p in preselected_peers if p in all_firms]
    selected_custom_peers = st.sidebar.multiselect("Custom peers (max 4)", all_firms, default=default_peers)
    if len(selected_custom_peers) > 4:
        st.sidebar.warning("Using only the first 4 selected peers.")
        selected_custom_peers = selected_custom_peers[:4]

# Keep URL in sync with current selections
params = {
    "view": view,
    "firm": str(firm_label),
    "comp": COMP_TO_PARAM.get(comparison, "none"),
}
if COMP_TO_PARAM.get(comparison) == "custom" and selected_custom_peers:
    params["peers"] = ",".join(selected_custom_peers)
set_query_params(**params)

# Helper to build internal links that preserve selections
def link_for(pillar_key: str) -> str:
    qp = {
        "view": pillar_key,
        "firm": str(firm_label),
        "comp": COMP_TO_PARAM.get(comparison, "none"),
    }
    if COMP_TO_PARAM.get(comparison) == "custom" and selected_custom_peers:
        qp["peers"] = ",".join(selected_custom_peers)
    return "?" + urlencode(qp)

# ========= COMBINED (chart with counts) =========
if view == "Combined":
    st.subheader("Combined overview")

    # Choose peer set
    comp_col = None
    comp_label = None
    peers = None
    n_peers = 0
    peer_note = ""

    if comparison == "Country" and country_col:
        comp_col = country_col
        comp_label = "country mean"
        peers, n_peers, peer_note = build_peers(df, comp_col, current_row)
    elif comparison == "Industry" and industry_col:
        comp_col = industry_col
        comp_label = "industry mean"
        peers, n_peers, peer_note = build_peers(df, comp_col, current_row)
    elif comparison == "Custom":
        comp_label = "custom"
        peers, n_peers, peer_note = build_custom_peers(df, label_col, selected_custom_peers, current_row)

    chart_rows = []
    for pillar in ["E", "S", "G"]:
        pcols = pillar_columns(pillar, groups, by_pillar)
        total_metrics = len(pcols)
        if total_metrics:
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

        chart_rows.append({
            "Pillar": PILLAR_LABEL[pillar],
            "Series": "Firm — # DR",
            "Value": firm_yes,
            "Link": link_for(pillar),
        })
        if peer_yes_mean is not None:
            chart_rows.append({
                "Pillar": PILLAR_LABEL[pillar],
                "Series": f"Peers — mean # DR ({comp_label})",
                "Value": round(peer_yes_mean, 1),
                "Link": link_for(pillar),
            })

    chart_df = pd.DataFrame(chart_rows)

    if not chart_df.empty:
        base_colors = {"Environment": "#008000", "Social": "#ff0000", "Governance": "#ffa500"}  # E/S/G
        series_domain = chart_df["Series"].unique().tolist()
        # Peers series label for styling (if present)
        peers_label = f"Peers — mean # DR ({comp_label})" if comp_label else ""

        chart = (
            alt.Chart(chart_df)
            .mark_bar()
            .encode(
                y=alt.Y("Pillar:N", title="", sort=["Environment", "Social", "Governance"]),
                yOffset=alt.YOffset("Series:N"),  # two bars under each other
                x=alt.X("Value:Q", title="# of DR reported"),
                color=alt.Color(
                    "Pillar:N",
                    scale=alt.Scale(domain=list(base_colors.keys()), range=list(base_colors.values())),
                    legend=None,
                ),
                opacity=alt.Opacity(
                    "Series:N",
                    scale=alt.Scale(domain=series_domain, range=[1.0] if len(series_domain) == 1 else [1.0, 0.55]),
                    legend=alt.Legend(title=""),
                ),
                stroke=alt.condition(
                    alt.FieldEqualPredicate(field="Series", equal=peers_label),
                    alt.value("#4200ff"),
                    alt.value(None),
                ),
                strokeWidth=alt.condition(
                    alt.FieldEqualPredicate(field="Series", equal=peers_label),
                    alt.value(1),
                    alt.value(0),
                ),
                tooltip=["Pillar", "Series", alt.Tooltip("Value:Q", title="# DR", format=".1f"), "Link"],
                href="Link:N",
            )
            .properties(height=420, width="container")
        )

        text = (
            alt.Chart(chart_df)
            .mark_text(align="left", baseline="middle", dx=3, color="white")
            .encode(
                y=alt.Y("Pillar:N", sort=["Environment", "Social", "Governance"]),
                yOffset=alt.YOffset("Series:N"),
                x=alt.X("Value:Q"),
                text=alt.Text("Value:Q", format=".1f"),
                href="Link:N",
            )
        )
        st.altair_chart(chart + text, use_container_width=True)

    note = "Bars show absolute counts of DR per pillar."
    if n_peers > 0:
        note += peer_note
    st.caption(note)

# ========= PILLAR DETAIL TABLES =========
def render_pillar(pillar: str, title: str, comparison: str):
    
    pillar_groups = by_pillar.get(pillar, [])
    if not pillar_groups:
        st.info(f"No {pillar} columns found.")
        return

    comp_col = None
    comp_label = None
    peers, n_peers, note = (None, 0, "")
    if comparison == "Country" and country_col:
        comp_col, comp_label = country_col, "country"
        peers, n_peers, note = build_peers(df, comp_col, current_row)
    elif comparison == "Industry" and industry_col:
        comp_col, comp_label = industry_col, "industry"
        peers, n_peers, note = build_peers(df, comp_col, current_row)
    elif comparison == "Custom":
        comp_label = "custom"
        peers, n_peers, note = build_custom_peers(df, label_col, selected_custom_peers, current_row)

    for g in pillar_groups:
        metrics = groups[g]

        # ==== Aggregate counts for expander header ====
        # Firm: how many "Yes" in this group
        firm_yes_count = 0
        for m in metrics:
            v = str(current_row.get(m, "")).strip().lower()
            if v in YES_SET:
                firm_yes_count += 1

        # Peers: mean # of "Yes" across chosen peers (if any)
        peers_yes_mean = None
        if n_peers > 0:
            present_cols = [m for m in metrics if m in peers.columns]
            if present_cols:
                peer_block = peers[present_cols].astype(str).applymap(lambda x: x.strip().lower() in YES_SET)
                if len(peer_block) > 0:
                    peers_yes_mean = float(peer_block.sum(axis=1).mean())

        # Build expander title with aggregates, using short ESRS title
        base_code = g.split("-")[0]
        short_title = SHORT_ESRS_LABELS.get(base_code, base_code)
        n_metrics = len(metrics)
        if peers_yes_mean is not None:
            exp_title = f"{short_title} • {n_metrics} metrics — reported: {firm_yes_count}/{n_metrics} (peers {comp_label}: {peers_yes_mean:.1f}/{n_metrics})"
        else:
            exp_title = f"{short_title} • {n_metrics} metrics — reported: {firm_yes_count}/{n_metrics}"

        # ==== Row table ====
        firm_vals = [pretty_value(current_row.get(c, np.nan)) for c in metrics]
        table = pd.DataFrame({"DR": metrics, "Reported": firm_vals})

        if n_peers > 0:
            peer_pct = []
            for m in metrics:
                if m in peers.columns:
                    s = peers[m].astype(str).str.strip().str.lower()
                    pct = (s.isin(YES_SET)).mean()
                    peer_pct.append(f"{pct*100:.1f}%")
                else:
                    peer_pct.append("—")
            table[f"Peers reported % ({comp_label})"] = peer_pct

        with st.expander(exp_title, expanded=False):
            st.dataframe(table, use_container_width=True, hide_index=True)
            if n_peers > 0:
                st.caption(f"Peers reported % = share of selected peers reporting DR {note}")

if view == "E":
    render_pillar("E", "E — Environment", comparison)
elif view == "S":
    render_pillar("S", "S — Social", comparison)
elif view == "G":
    render_pillar("G", "G — Governance", comparison)

