import streamlit as st
import pandas as pd
import numpy as np
from pathlib import Path
from collections import defaultdict
import altair as alt  # charts
from io import BytesIO
import requests

st.set_page_config(page_title="DR Viewer", page_icon="🌱", layout="wide")
st.markdown("""
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
""", unsafe_allow_html=True)

DEFAULT_DATA_URL = "https://github.com/akgrossk/srn_dr_list/blob/main/DR_extract.xlsx"

FIRM_NAME_COL_CANDIDATES = ["name", "company", "firm"]
FIRM_ID_COL_CANDIDATES   = ["isin", "ticker"]
COUNTRY_COL_CANDIDATES   = ["country", "Country"]
INDUSTRY_COL_CANDIDATES  = ["industry", "Industry", "sector", "Sector"]

YES_SET = {"yes", "ja", "true", "1"}
NO_SET  = {"no", "nein", "false", "0"}

PILLAR_LABEL = {"E": "Environment", "S": "Social", "G": "Governance"}

def pretty_value(v):
    if pd.isna(v):
        return "—"
    s = str(v).strip()
    low = s.lower()
    if low in YES_SET:
        return "✅ Yes"
    if low in NO_SET:
        return "❌ No"
    return s

def group_key(col: str):
    if not isinstance(col, str) or not col or col[0] not in "ESG":
        return None
    parts = col.split("-")
    if len(parts) >= 2 and not parts[1].isdigit():
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
            out.append(c); seen.add(c)
    return out

def normalize_github_raw_url(url: str) -> str:
    u = url.strip()
    if "github.com" in u and "/blob/" in u:
        u = u.replace("https://github.com/", "https://raw.githubusercontent.com/").replace("/blob/", "/")
    if "dropbox.com" in u and "dl=0" in u:
        u = u.replace("dl=0", "dl=1")
    return u

@st.cache_data(show_spinner=False)
def load_table(path: str) -> pd.DataFrame:
    # Handle URLs
    if isinstance(path, str) and path.lower().startswith(("http://", "https://")):
        url = normalize_github_raw_url(path)
        headers = {}
        try:
            token = st.secrets.get("GITHUB_TOKEN")  # optional, for private repos
        except Exception:
            token = None
        if token and ("githubusercontent" in url or "github.com" in url):
            headers["Authorization"] = f"token {token}"
        try:
            r = requests.get(url, headers=headers, timeout=30)
            r.raise_for_status()
            data = BytesIO(r.content)
            if url.lower().endswith((".xlsx", ".xls")):
                return pd.read_excel(data)
            return pd.read_csv(data)
        except Exception as e:
            st.error(f"Failed to fetch data from URL: {e}")
            return pd.DataFrame()

    # Handle local filesystem paths
    p = Path(path)
    if not p.exists():
        return pd.DataFrame()
    if p.suffix.lower() in {".xlsx", ".xls"}:
        return pd.read_excel(p)
    if p.suffix.lower() == ".csv":
        return pd.read_csv(p)
    return pd.DataFrame()


def first_present(cols, candidates):
    for c in candidates:
        if c in cols:
            return c
    return None

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

# NEW: custom peer builder from explicit firm names/IDs
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

st.sidebar.title("🌱 DR Viewer")

# -------- DATA SOURCE (deploy-friendly) --------
source_mode = st.sidebar.radio("Data source", ["URL", "Upload", "Local path (dev)"], index=0, horizontal=False)

df = pd.DataFrame()
if source_mode == "URL":
    data_url = st.sidebar.text_input("Data URL (.xlsx or .csv)", placeholder="Paste RAW GitHub/Dropbox/HTTPS link…")
    if data_url:
        df = load_table(data_url)
        if df.empty:
            st.sidebar.warning("Could not load from URL. For GitHub, click 'Raw' and use that URL; for Dropbox, ensure 'dl=1'.")
elif source_mode == "Upload":
    up = st.sidebar.file_uploader("Upload .xlsx/.xls/.csv", type=["xlsx", "xls", "csv"])
    if up is not None:
        try:
            if up.name.lower().endswith((".xlsx", ".xls")):
                df = pd.read_excel(up)
            else:
                df = pd.read_csv(up)
        except Exception as e:
            st.sidebar.error(f"Failed to read uploaded file: {e}")
else:  # Local path (dev)
    data_path = DEFAULT_DATA_PATH
    df = load_table(data_path)

if df.empty:
    st.info("Load a dataset from the sidebar (URL or Upload) to begin.")
    st.stop()

firm_name_col = first_present(df.columns, FIRM_NAME_COL_CANDIDATES)
firm_id_col   = first_present(df.columns, FIRM_ID_COL_CANDIDATES)
country_col   = first_present(df.columns, COUNTRY_COL_CANDIDATES)
industry_col  = first_present(df.columns, INDUSTRY_COL_CANDIDATES)

# Firm selector (no pre-selected firm)
if firm_name_col:
    firms = df[firm_name_col].dropna().astype(str).unique().tolist()
    try:
        firm_label = st.sidebar.selectbox("Firm", firms, index=None, placeholder="Select a firm…")
    except TypeError:
        # Fallback for older Streamlit: add a dummy first option
        firms = ["— Select firm —"] + firms
        firm_label = st.sidebar.selectbox("Firm", firms, index=0)
        if firm_label == "— Select firm —":
            st.stop()
    if not firm_label:
        st.info("Select a firm from the sidebar to view details.")
        st.stop()
    current_row = df[df[firm_name_col].astype(str) == str(firm_label)].iloc[0]
elif firm_id_col:
    firms = df[firm_id_col].dropna().astype(str).unique().tolist()
    try:
        firm_label = st.sidebar.selectbox("Firm (ID)", firms, index=None, placeholder="Select a firm…")
    except TypeError:
        firms = ["— Select firm —"] + firms
        firm_label = st.sidebar.selectbox("Firm (ID)", firms, index=0)
        if firm_label == "— Select firm —":
            st.stop()
    if not firm_label:
        st.info("Select a firm from the sidebar to view details.")
        st.stop()
    current_row = df[df[firm_id_col].astype(str) == str(firm_label)].iloc[0]
else:
    st.error("No firm identifier column found (looked for: name / company / firm / isin / ticker).")
    st.stop()

esg_columns = [c for c in df.columns if isinstance(c, str) and c[:1] in ("E", "S", "G")]
groups, by_pillar = build_hierarchy(esg_columns)

st.title(str(firm_label))

isin_txt = f"ISIN: <strong>{current_row.get(firm_id_col, 'n/a')}</strong>" if firm_id_col else ""
country_txt = f"Country: <strong>{current_row.get(country_col, 'n/a')}</strong>" if country_col else ""
industry_txt = f"Industry: <strong>{current_row.get(industry_col, 'n/a')}</strong>" if industry_col else ""
sub = " · ".join([t for t in [isin_txt, country_txt, industry_txt] if t])

if sub:
    st.markdown(f"<div class='firm-meta'>{sub}</div>", unsafe_allow_html=True)

link_ar = str(current_row.get("Link_AR", "")).strip()
if link_ar and link_ar.lower().startswith(("http://", "https://")):
    try:
        st.link_button("Open firm report", link_ar)
    except Exception:
        st.markdown(f'<a href="{link_ar}" target="_blank" rel="noopener noreferrer">Open firm report ↗</a>', unsafe_allow_html=True)

valid_views = ["Combined", "E", "S", "G"]
current_view = st.query_params.get("view", "Combined")
if current_view not in valid_views:
    current_view = "Combined"

view = st.sidebar.radio("Section", valid_views, index=valid_views.index(current_view))
comp_options = ["No comparison", "Country", "Industry", "Custom"]
comparison = st.sidebar.selectbox("Comparison", comp_options, index=0)
if comparison == "Country" and not country_col:
    st.sidebar.info("No country column found; comparison will be disabled.")
if comparison == "Industry" and not industry_col:
    st.sidebar.info("No industry column found; comparison will be disabled.")

# Custom peers picker (up to 4)
selected_custom_peers = []
label_col = firm_name_col if firm_name_col else firm_id_col
if comparison == "Custom" and label_col:
    all_firms = df[label_col].dropna().astype(str).unique().tolist()
    try:
        all_firms = [f for f in all_firms if str(f) != str(current_row.get(label_col, ""))]
    except Exception:
        pass
    selected_custom_peers = st.sidebar.multiselect("Custom peers (max 4)", all_firms, default=[])
    if len(selected_custom_peers) > 4:
        st.sidebar.warning("Using only the first 4 selected peers.")
        selected_custom_peers = selected_custom_peers[:4]

st.query_params["view"] = view

# ---------- Combined ----------
if view == "Combined":
    st.subheader("Combined overview (reported = Yes)")

    # We will chart absolute counts (# of metrics answered "Yes"), not percentages.

    # Peer-set selection
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

        # Rows for chart (long format). Keep link to pillar pages.
        chart_rows.append({
            "Pillar": PILLAR_LABEL[pillar],
            "Series": "Firm — # Yes",
            "Value": firm_yes,
            "Total": total_metrics,
            "Link": f"?view={pillar}",
        })
        if peer_yes_mean is not None:
            chart_rows.append({
                "Pillar": PILLAR_LABEL[pillar],
                "Series": f"Peers — mean # Yes ({comp_label})",
                "Value": round(peer_yes_mean, 1),
                "Total": total_metrics,
                "Link": f"?view={pillar}",
            })

    chart_df = pd.DataFrame(chart_rows)

    if not chart_df.empty:
        base_colors = {
            "Environment": "#008000",
            "Social": "#ff0000",
            "Governance": "#ffa500",
        }
        chart = (
            alt.Chart(chart_df)
            .mark_bar()
            .encode(
                y=alt.Y("Pillar:N", title="", sort=["Environment", "Social", "Governance"]),
                yOffset=alt.YOffset("Series:N"),
                x=alt.X("Value:Q", title="# of metrics reported 'Yes'"),
                color=alt.Color("Pillar:N", scale=alt.Scale(domain=list(base_colors.keys()), range=list(base_colors.values())), legend=None),
                opacity=alt.Opacity("Series:N", scale=alt.Scale(domain=chart_df["Series"].unique().tolist(), range=[1.0, 0.5]), legend=alt.Legend(title="")),
                tooltip=["Pillar", "Series", alt.Tooltip("Value:Q", title="# Yes", format=".1f"),"Link"],
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

    note = "Bars show absolute counts of 'Yes' per pillar (not %)."
    if comp_col and n_peers > 0:
        note += peer_note
    st.caption(note)

#---
def render_pillar(pillar: str, title: str, comparison: str):
    st.header(title)
    pillar_groups = by_pillar.get(pillar, [])
    if not pillar_groups:
        st.info(f"No {pillar} columns found.")
        return
    comp_col = None
    comp_label = None
    if comparison == "Country" and country_col:
        comp_col, comp_label = country_col, "country"
    elif comparison == "Industry" and industry_col:
        comp_col, comp_label = industry_col, "industry"
    peers, n_peers, note = build_peers(df, comp_col, current_row) if comp_col else (None, 0, "")
    if comparison == "Custom":
        comp_label = "custom"
        peers, n_peers, note = build_custom_peers(df, label_col, selected_custom_peers, current_row)
    for g in pillar_groups:
        metrics = groups[g]
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
        with st.expander(f"{g} • {len(metrics)} metrics", expanded=False):
            st.dataframe(table, use_container_width=True, hide_index=True)
            if n_peers > 0:
                st.caption(f"Peers reported % = share of peer firms answering 'Yes'{note}")

if view == "E":
    render_pillar("E", "E — Environment", comparison)
elif view == "S":
    render_pillar("S", "S — Social", comparison)
elif view == "G":
    render_pillar("G", "G — Governance", comparison)

