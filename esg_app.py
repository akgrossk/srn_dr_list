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

st.set_page_config(page_title="Disclosure Requirements Viewer", page_icon="🌱", layout="wide")
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

# ========= LOAD DATA (GitHub only) =========
st.sidebar.title("🌱 Disclosure Requirements Viewer")
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
isin_txt     = f"ISIN: <strong>{current_row.get(firm_id_col, 'n/a')}</strong>" if firm_id_col else ""
country_txt  = f"Country: <strong>{current_row.get(country_col, 'n/a')}</strong>" if country_col else ""
sector_txt   = f"Sector: <strong>{current_row.get(sector_col, 'n/a')}</strong>" if sector_col else ""
industry_txt = f"Industry: <strong>{current_row.get(industry_col, 'n/a')}</strong>" if industry_col else ""
sub = " · ".join([t for t in [isin_txt, country_txt, sector_txt, industry_txt] if t])
if sub:
    st.markdown(f"<div class='firm-meta'>{sub}</div>", unsafe_allow_html=True)

link_sr = str(current_row.get("Link_SR", "")).strip()
link_ar = str(current_row.get("Link_AR", "")).strip()

def _valid_url(u: str) -> bool:
    return u.lower().startswith(("http://", "https://"))

link_url = link_sr if _valid_url(link_sr) else (link_ar if _valid_url(link_ar) else "")

if link_url:
    try:
        # Keep the same label; it will open SR if present, else AR
        st.link_button("Open firm report", link_url)
    except Exception:
        st.markdown(
            f'<a href="{link_url}" target="_blank" rel="noopener noreferrer">Open firm report ↗</a>',
            unsafe_allow_html=True,
        )

# ========= NAV & COMPARISON =========
valid_views = ["Total", "E", "S", "G"]
current_view = read_query_param("view", "Total")
# backwards-compat for old URLs using view=Combined
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
    st.subheader("Total overview")
    
    comp_col = None
    comp_label = None
    peers = None
    n_peers = 0
    peer_note = ""

    if comparison == "Country" and country_col:
        comp_col = country_col
        comp_label = "country mean"
        peers, n_peers, peer_note = build_peers(df, comp_col, current_row)
    elif comparison == "Sector" and sector_col:
        comp_col = sector_col
        comp_label = "sector mean"
        peers, n_peers, peer_note = build_peers(df, comp_col, current_row)
    elif comparison == "Industry" and industry_col:
        comp_col = industry_col
        comp_label = "industry mean"
        peers, n_peers, peer_note = build_peers(df, comp_col, current_row)
    elif comparison == "Custom peers":
        comp_label = "custom"
        peers, n_peers, peer_note = build_custom_peers(df, label_col, selected_custom_peers, current_row)
    
    # --- short legend labels (for Combined chart) ---
    firm_series = "Firm"
    comp_label_short = (comp_label or "").replace(" mean", "") if comp_label else None  # country/sector/industry/custom
    peers_series = f"Peers avg ({comp_label_short})" if comp_label_short else None

    chart_rows = []
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

        # chart rows
        chart_rows.append({
            "Pillar": PILLAR_LABEL[pillar],
            "Series": firm_series,
            "Value": firm_yes,
            "Link": link_for(pillar),
        })
        if peer_yes_mean is not None:
            chart_rows.append({
                "Pillar": PILLAR_LABEL[pillar],
                "Series": peers_series,
                "Value": round(peer_yes_mean, 1),
                "Link": link_for(pillar),
            })

        # summary table rows
        summary_rows.append({
            "Pillar": PILLAR_LABEL[pillar],
            "Firm — number of Disclosure Requirements": firm_yes,
            "Peers — mean number of Disclosure Requirements": (round(peer_yes_mean, 1) if peer_yes_mean is not None else None),
            "Total Disclosure Requirements": total_DR,
        })

    # ===== Global Tables or Charts =====
    if display_mode == "Tables":
        tbl = pd.DataFrame(summary_rows)
        if n_peers > 0:
            tbl = tbl.rename(columns={
                "Peers — mean number of Disclosure Requirements":
                f"Peers — mean number of Disclosure Requirements ({comp_label})"
            })
        else:
            if "Peers — mean number of Disclosure Requirements" in tbl.columns:
                tbl = tbl.drop(columns=["Peers — mean number of Disclosure Requirements"])
                
        st.dataframe(tbl, use_container_width=True, hide_index=True)

        note = "Rows show the number of Disclosure Requirements per pillar."
        if n_peers > 0:
            note += peer_note
        st.caption(note)

    else:
        chart_df = pd.DataFrame(chart_rows)
        if not chart_df.empty:
            base_colors = {"Environment": "#008000", "Social": "#ff0000", "Governance": "#ffa500"}  # E/S/G

            # legend should show just our two short labels
            series_domain = [firm_series] + ([peers_series] if peers_series else [])
            peers_label = peers_series or ""

            # We now stack E/S/G within each Series (Firm vs Peers)
            stacked = (
                alt.Chart(chart_df)
                .transform_calculate(
                    # Explicit stack order: E=0, S=1, G=2
                    PillarOrder="{'Environment': 0, 'Social': 1, 'Governance': 2}[datum.Pillar]"
                )
                .mark_bar()
                .encode(
                    y=alt.Y("Series:N", title="", sort=[firm_series] + ([peers_series] if peers_series else [])),
                    x=alt.X("Value:Q", title="Number of Disclosure Requirements reported"),
                    color=alt.Color(
                        "Pillar:N",
                        # Controls legend order & color mapping
                        scale=alt.Scale(domain=["Environment", "Social", "Governance"],
                                        range=[base_colors["Environment"], base_colors["Social"], base_colors["Governance"]]),
                        legend=alt.Legend(title="Pillar")
                    ),
                    tooltip=[
                        alt.Tooltip("Series:N", title="Series"),
                        alt.Tooltip("Pillar:N", title="Pillar"),
                        alt.Tooltip("Value:Q", title="# DR", format=".1f"),
                    ],
                    href="Link:N",
                    # Controls stack order (left-to-right for horizontal bars)
                    order=alt.Order("PillarOrder:Q", sort="ascending"),
                )
                .properties(height=120, width="container")
            )
        
            totals = (
                stacked
                .transform_aggregate(total="sum(Value)", groupby=["Series"])
                .mark_text(align="left", baseline="middle", dx=4)
                .encode(
                    y="Series:N",
                    x="total:Q",
                    text=alt.Text("total:Q", format=".1f"),
                )
            )
        
            st.altair_chart(stacked + totals, use_container_width=True)
        
        note = "Bars show total counts of reported Disclosure Requirements, stacked by pillar."
        if n_peers > 0:
            note += peer_note
        st.caption(note)

# ========= PILLAR DETAIL (Tables or compact Charts) =========
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
        peers, n_peers, note = build_peers(df, comp_col, current_row)
    elif comparison == "Sector" and sector_col:
        comp_col, comp_label = sector_col, "sector"
        peers, n_peers, note = build_peers(df, comp_col, current_row)
    elif comparison == "Industry" and industry_col:
        comp_col, comp_label = industry_col, "industry"
        peers, n_peers, note = build_peers(df, comp_col, current_row)
    elif comparison == "Custom peers":
        comp_label = "custom"
        peers, n_peers, note = build_custom_peers(df, label_col, selected_custom_peers, current_row)

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
        if peers_yes_mean is not None:
            exp_title = (
                f"{short_title} • {n_metrics} Disclosure Requirements — reported: "
                f"{firm_yes_count}/{n_metrics} (peers {comp_label}: {peers_yes_mean:.1f}/{n_metrics})"
            )
        else:
            exp_title = f"{short_title} • {n_metrics} Disclosure Requirements — reported: {firm_yes_count}/{n_metrics}"

        with st.expander(exp_title, expanded=False):
            if display_mode == "Tables":
                firm_vals = [pretty_value(current_row.get(c, np.nan)) for c in metrics]
                table = pd.DataFrame({"Disclosure Requirements": metrics, "Reported": firm_vals})

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

                st.dataframe(table, use_container_width=True, hide_index=True)
                if n_peers > 0:
                    st.caption(f"Peers reported % = share of selected peers answering 'Yes'{note}")

            else:
                # ====== CHART MODE: per-standard stacked bars (sum to total DRs in the group) ======
                # Categories: Yes / No / Blank (Blank = missing/NA/anything not in YES/NO sets)
                cat_colors = {"Yes": "#16a34a", "No": "#ef4444", "Blank": "#9ca3af"}  # green/red/gray
                present_cols = [m for m in metrics if m in df.columns]  # safety

                # --- Firm counts ---
                firm_vals = current_row[present_cols].astype(str).str.strip().str.lower()
                firm_yes = int(firm_vals.isin(YES_SET).sum())
                firm_no  = int(firm_vals.isin(NO_SET).sum())
                firm_blank = len(present_cols) - firm_yes - firm_no

                # --- Peers mean counts (expected counts across DRs for the avg peer) ---
                peers_yes_mean = peers_no_mean = peers_blank_mean = None
                if n_peers > 0 and present_cols:
                    pv = peers[present_cols].astype(str).applymap(lambda x: x.strip().lower())
                    # per-metric proportions across peers
                    yes_p = pv.apply(lambda s: s.isin(YES_SET).mean(), axis=0)
                    no_p  = pv.apply(lambda s: s.isin(NO_SET).mean(), axis=0)
                    blank_p = 1 - yes_p - no_p
                    peers_yes_mean   = float(yes_p.sum())   # expected # of "Yes" across metrics
                    peers_no_mean    = float(no_p.sum())
                    peers_blank_mean = float(blank_p.sum())

                # Build stacked rows
                rows = [
                    {"Series": "Firm (this company)", "Category": "Yes",   "Value": float(firm_yes),   "Total": len(present_cols)},
                    {"Series": "Firm (this company)", "Category": "No",    "Value": float(firm_no),    "Total": len(present_cols)},
                    {"Series": "Firm (this company)", "Category": "Blank", "Value": float(firm_blank), "Total": len(present_cols)},
                ]
                if peers_yes_mean is not None:
                    rows += [
                        {"Series": "Peers mean" + (f" ({comp_label})" if comp_label else ""), "Category": "Yes",   "Value": peers_yes_mean,   "Total": len(present_cols)},
                        {"Series": "Peers mean" + (f" ({comp_label})" if comp_label else ""), "Category": "No",    "Value": peers_no_mean,    "Total": len(present_cols)},
                        {"Series": "Peers mean" + (f" ({comp_label})" if comp_label else ""), "Category": "Blank", "Value": peers_blank_mean, "Total": len(present_cols)},
                    ]

                chart_df = pd.DataFrame(rows)

                # explicit stack order: Yes -> No -> Blank
                chart = (
                    alt.Chart(chart_df)
                    .transform_calculate(
                        CatOrder="{'Yes':0,'No':1,'Blank':2}[datum.Category]"
                    )
                    .mark_bar()
                    .encode(
                        y=alt.Y(
                            "Series:N",
                            title="",
                            sort=["Firm (this company)"] + ([f"Peers mean ({comp_label})"] if (n_peers > 0 and comp_label) else (["Peers mean"] if n_peers > 0 else [])),
                            axis=None,
                        ),
                        x=alt.X(
                            "Value:Q",
                            title=f"Disclosure Requirements in group (0–{len(present_cols)})",
                            scale=alt.Scale(domain=[0, len(present_cols)], nice=False, zero=True),
                            axis=alt.Axis(values=list(range(0, len(present_cols)+1)), tickCount=len(present_cols)+1, format="d"),
                        ),
                        color=alt.Color(
                            "Category:N",
                            scale=alt.Scale(
                                domain=["Yes", "No", "Blank"],
                                range=[cat_colors["Yes"], cat_colors["No"], cat_colors["Blank"]],
                            ),
                            legend=alt.Legend(title="", orient="bottom", direction="horizontal"),
                        ),
                        order=alt.Order("CatOrder:Q", sort="ascending"),
                        tooltip=[
                            alt.Tooltip("Series:N", title="Series"),
                            alt.Tooltip("Category:N", title="Response"),
                            alt.Tooltip("Value:Q", title="# DR", format=".1f"),
                            alt.Tooltip("Total:Q", title="Total DR in group"),
                        ],
                    )
                    .properties(
                        height=alt.Step(42),
                        width="container",
                        padding={"left": 12, "right": 40, "top": 6, "bottom": 24},
                    )
                )

                # totals at bar end
                totals = (
                    alt.Chart(chart_df)
                    .transform_aggregate(total="sum(Value)", groupby=["Series"])
                    .mark_text(align="left", baseline="middle", dx=4)
                    .encode(
                        y="Series:N",
                        x="total:Q",
                        text=alt.Text("total:Q", format=".1f"),
                    )
                )

                st.altair_chart(chart + totals, use_container_width=True)
                st.caption(
                    "Stacked bars sum to the number of Disclosure Requirements in this ESRS group; "
                    "segments show Yes / No / Blank. Peers use expected counts (mean across selected peers)."
                    + (note if n_peers > 0 else "")
                )

# ========= Which pillar to render =========
if view == "E":
    render_pillar("E", "E — Environment", comparison, display_mode)
elif view == "S":
    render_pillar("S", "S — Social", comparison, display_mode)
elif view == "G":
    render_pillar("G", "G — Governance", comparison, display_mode)
