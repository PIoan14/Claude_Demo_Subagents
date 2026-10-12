"""Streamlit dashboard for the market briefs in market-brief/<date>/brief.md.

Run with:  streamlit run main.py
"""

import re
from pathlib import Path

import pandas as pd
import streamlit as st

BRIEFS_DIR = Path(__file__).parent / "market-brief"

REGIONS = {
    "United States": {"flag": "🇺🇸", "prices": "United States"},
    "Europe": {"flag": "🇪🇺", "prices": "Europe"},
    "Asia": {"flag": "🌏", "prices": "Asia"},
}

LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
NEWS_RE = re.compile(r"^\*\*(.+?)\*\*\s*(.*)$")


# ---------------------------------------------------------------- parsing


def split_sections(text: str, marker: str) -> dict[str, str]:
    """Split markdown into {heading: body} on lines starting with `marker`."""
    sections, current, lines = {}, None, []
    for line in text.splitlines():
        if line.startswith(marker):
            if current is not None:
                sections[current] = "\n".join(lines).strip()
            current, lines = line[len(marker):].strip(), []
        elif current is not None:
            lines.append(line)
    if current is not None:
        sections[current] = "\n".join(lines).strip()
    return sections


def parse_table(body: str) -> pd.DataFrame:
    rows = [
        [cell.strip() for cell in line.strip().strip("|").split("|")]
        for line in body.splitlines()
        if line.strip().startswith("|")
    ]
    rows = [r for r in rows if not all(set(c) <= set("-: ") for c in r)]
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows[1:], columns=rows[0])


def parse_bullets(body: str) -> list[str]:
    return [line[2:].strip() for line in body.splitlines() if line.startswith("- ")]


def parse_region(body: str) -> tuple[str, list[dict]]:
    summary = "\n".join(
        line for line in body.splitlines() if line.strip() and not line.startswith("- ")
    )
    news = []
    for bullet in parse_bullets(body):
        link = LINK_RE.search(bullet)
        text = LINK_RE.sub("", bullet).strip()
        match = NEWS_RE.match(text)
        title, detail = (match.group(1), match.group(2)) if match else (text, "")
        news.append(
            {
                "title": title.rstrip("."),
                "detail": detail.strip(),
                "url": link.group(2) if link else None,
            }
        )
    return summary, news


def find_section(sections: dict[str, str], name: str) -> str:
    return next((body for title, body in sections.items() if name in title), "")


def to_number(value: str) -> float | None:
    try:
        return float(value.replace(",", "").replace("%", "").replace("+", ""))
    except (AttributeError, ValueError):
        return None


@st.cache_data
def load_brief(path: str, mtime: float) -> dict:
    text = Path(path).read_text(encoding="utf-8")
    title_line = next((l for l in text.splitlines() if l.startswith("# ")), "# Market Brief")
    sections = split_sections(text, "## ")
    prices = {
        name: parse_table(body)
        for name, body in split_sections(find_section(sections, "All prices"), "### ").items()
    }
    return {
        "title": title_line[2:].strip(),
        "glance": parse_bullets(find_section(sections, "At a glance")),
        "snapshot": parse_table(find_section(sections, "Global snapshot")),
        "regions": {name: parse_region(find_section(sections, name)) for name in REGIONS},
        "watch": parse_bullets(find_section(sections, "What to watch")),
        "prices": prices,
        "notes": parse_bullets(find_section(sections, "Sources and notes")),
        "raw": text,
    }


# ---------------------------------------------------------------- styling

CSS = """
<style>
.block-container { padding-top: 2rem; max-width: 1200px; }
.hero {
  padding: 1.6rem 1.8rem; border-radius: 16px; margin-bottom: 1.2rem;
  background: linear-gradient(135deg, #0f2027 0%, #203a43 50%, #2c5364 100%);
  color: #fff;
}
.hero h1 { margin: 0; font-size: 2rem; color: #fff; }
.hero p { margin: .3rem 0 0; opacity: .8; }
.card {
  border: 1px solid rgba(128,128,128,.25); border-radius: 12px;
  padding: 1rem 1.1rem; margin-bottom: .8rem; height: 100%;
}
.card h4 { margin: 0 0 .4rem; font-size: 1rem; }
.card p { margin: 0; opacity: .85; font-size: .92rem; }
.card a { font-size: .85rem; text-decoration: none; }
.glance { padding: .55rem .9rem; border-left: 4px solid #2c5364;
  background: rgba(44,83,100,.08); border-radius: 6px; margin-bottom: .5rem; }
</style>
"""


def color_change(value: str) -> str:
    number = to_number(value)
    if number is None or number == 0:
        return ""
    return "color: #16a34a; font-weight: 600" if number > 0 else "color: #dc2626; font-weight: 600"


def show_price_table(df: pd.DataFrame) -> None:
    if df.empty:
        st.info("No prices available.")
        return
    change_cols = [c for c in ("Chg", "Chg %") if c in df.columns]
    st.dataframe(
        df.style.map(color_change, subset=change_cols),
        hide_index=True,
        width="stretch",
    )


def show_metrics(df: pd.DataFrame, per_row: int = 4) -> None:
    if df.empty or "Value" not in df.columns:
        return
    records = df.to_dict("records")
    for start in range(0, len(records), per_row):
        cols = st.columns(per_row)
        for col, row in zip(cols, records[start:start + per_row]):
            col.metric(
                label=row.get("Asset", ""),
                value=row["Value"],
                delta=f"{row.get('Chg', '')} ({row.get('Chg %', '')})",
                border=True,
            )


def show_news(news: list[dict]) -> None:
    if not news:
        st.caption("No news items.")
        return
    cols = st.columns(len(news))
    for col, item in zip(cols, news):
        link = f'<a href="{item["url"]}" target="_blank">Read on Yahoo Finance →</a>' if item["url"] else ""
        col.markdown(
            f'<div class="card"><h4>{item["title"]}</h4><p>{item["detail"]}</p><br>{link}</div>',
            unsafe_allow_html=True,
        )


# ---------------------------------------------------------------- app


def main() -> None:
    st.set_page_config(page_title="Market Brief", page_icon="📈", layout="wide")
    st.markdown(CSS, unsafe_allow_html=True)

    briefs = sorted(BRIEFS_DIR.glob("*/brief.md"), reverse=True)
    if not briefs:
        st.error(f"No briefs found in `{BRIEFS_DIR}`. Run `/market-brief` first.")
        return

    with st.sidebar:
        st.header("📅 Briefs")
        chosen = st.selectbox("Date", briefs, format_func=lambda p: p.parent.name)
        st.caption(f"{len(briefs)} brief(s) available")
        st.divider()
        st.caption("Source: Yahoo Finance. For information only, not investment advice.")

    brief = load_brief(str(chosen), chosen.stat().st_mtime)

    st.markdown(
        f'<div class="hero"><h1>📈 {brief["title"]}</h1>'
        "<p>US · Europe · Asia — prices, news and what to watch</p></div>",
        unsafe_allow_html=True,
    )

    # Global snapshot
    snapshot = brief["snapshot"]
    if not snapshot.empty:
        st.subheader("🌐 Global snapshot")
        cols = st.columns(len(snapshot))
        for col, row in zip(cols, snapshot.to_dict("records")):
            col.metric(
                label=f'{row.get("Region", "")} · {row.get("Main index", "")}',
                value=row.get("Value", ""),
                delta=row.get("Chg %", ""),
                border=True,
            )

    # At a glance + what to watch
    left, right = st.columns([3, 2], gap="large")
    with left:
        st.subheader("⚡ At a glance")
        for item in brief["glance"]:
            st.markdown(f'<div class="glance">{item}</div>', unsafe_allow_html=True)
    with right:
        st.subheader("👀 What to watch")
        for item in brief["watch"]:
            st.markdown(f"- {item}")

    st.divider()

    # Regions
    tabs = st.tabs([f'{meta["flag"]} {name}' for name, meta in REGIONS.items()])
    for tab, (name, meta) in zip(tabs, REGIONS.items()):
        summary, news = brief["regions"][name]
        prices = brief["prices"].get(meta["prices"], pd.DataFrame())
        with tab:
            if summary:
                st.markdown(summary)
            else:
                st.warning(f"No data available for {name}.")
            show_metrics(prices)
            st.markdown("#### 📰 News")
            show_news(news)
            with st.expander("Full price table"):
                show_price_table(prices)

    st.divider()

    with st.expander("ℹ️ Sources and notes"):
        for note in brief["notes"]:
            st.markdown(f"- {note}")
    with st.expander("📄 Raw brief.md"):
        st.markdown(brief["raw"])

    st.caption("*For information only, not investment advice.*")


if __name__ == "__main__":
    main()
