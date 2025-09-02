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

DEFAULT_DATA_PATH = r"C:\Users\agrosko\Dropbox\Coding\srn\DR_extract.xlsx"  # ← your local dev path
# Auto-load this on deploy (converted to RAW under the hood)
DEFAULT_DATA_URL = "https://github.com/akgrossk/srn_dr_list/blob/main/DR_extract.xlsx"
