# ============================================================
# NSE STOCK SCANNER
# ============================================================
#
# CONDITIONS
#
# 1. NSE EQ stocks
# 2. Minimum 365 trading days
# 3. LTP > ₹100
# 4. LTP within +/-15% of 50 DMA
# 5. LTP maximum 5% below 52-week high
#
# FEATURES
#
# - One-click scan
# - Mobile-friendly UI
# - Progress indicator
# - TradingView links
# - CSV download
# - Scan statistics
# - Optimized batch downloading
#
# ============================================================

import streamlit as st
import pandas as pd
import yfinance as yf
import requests
import io
import time
from datetime import datetime


# ============================================================
# PAGE CONFIGURATION
# ============================================================

st.set_page_config(
    page_title="NSE Stock Scanner",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="collapsed"
)


# ============================================================
# SCANNER SETTINGS
# ============================================================

MIN_LTP = 100.0

DMA50_DISTANCE = 15.0

MAX_BELOW_52W_HIGH = 5.0

MIN_TRADING_DAYS = 365

BATCH_SIZE = 50

BATCH_DELAY = 0.35


# ============================================================
# CUSTOM CSS
# ============================================================

st.markdown(
    """
    <style>

    .main-title {
        font-size: 32px;
        font-weight: 700;
        margin-bottom: 0px;
    }

    .subtitle {
        color: #888888;
        margin-top: 0px;
        margin-bottom: 20px;
    }

    div.stButton > button {
        width: 100%;
        height: 55px;
        font-size: 20px;
        font-weight: 600;
        border-radius: 10px;
    }

    .condition-box {
        padding: 12px;
        border-radius: 10px;
        background-color: rgba(128,128,128,0.08);
        margin-bottom: 8px;
    }

    </style>
    """,
    unsafe_allow_html=True
)


# ============================================================
# HEADER
# ============================================================

st.markdown(
    '<div class="main-title">📈 NSE Stock Scanner</div>',
    unsafe_allow_html=True
)

st.markdown(
    '<div class="subtitle">'
    '50-DMA + 52-Week High scanner'
    '</div>',
    unsafe_allow_html=True
)


# ============================================================
# CONDITIONS DISPLAY
# ============================================================

with st.expander("📋 Scan Conditions", expanded=False):

    st.markdown(
        f"""
        <div class="condition-box">
        ✅ NSE Equity stocks
        </div>

        <div class="condition-box">
        ✅ Minimum {MIN_TRADING_DAYS} trading days
        </div>

        <div class="condition-box">
        ✅ LTP &gt; ₹{MIN_LTP:,.0f}
        </div>

        <div class="condition-box">
        ✅ LTP within ±{DMA50_DISTANCE}% of 50-DMA
        </div>

        <div class="condition-box">
        ✅ Maximum {MAX_BELOW_52W_HIGH}% below 52-week high
        </div>
        """,
        unsafe_allow_html=True
    )


# ============================================================
# NSE SYMBOL LIST
# ============================================================

@st.cache_data(ttl=86400, show_spinner=False)
def get_nse_symbols():

    url = (
        "https://archives.nseindia.com/"
        "content/equities/EQUITY_L.csv"
    )

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 "
            "(KHTML, like Gecko) "
            "Chrome/131.0 Safari/537.36"
        ),
        "Accept": (
            "text/html,application/xhtml+xml,"
            "application/xml;q=0.9,*/*;q=0.8"
        ),
        "Referer": "https://www.nseindia.com/"
    }

    session = requests.Session()

    response = session.get(
        "https://www.nseindia.com/",
        headers=headers,
        timeout=20
    )

    response = session.get(
        url,
        headers=headers,
        timeout=30
    )

    response.raise_for_status()

    df = pd.read_csv(
        io.BytesIO(response.content)
    )

    df.columns = [
        str(c).strip()
        for c in df.columns
    ]

    if "SERIES" in df.columns:

        df = df[
            df["SERIES"]
            .astype(str)
            .str.strip()
            .eq("EQ")
        ].copy()

    if "SYMBOL" not in df.columns:

        raise ValueError(
            "NSE SYMBOL column not found."
        )

    symbols = (
        df["SYMBOL"]
        .astype(str)
        .str.strip()
        .dropna()
        .unique()
        .tolist()
    )

    symbols = sorted(symbols)

    return symbols


# ============================================================
# DOWNLOAD ONE BATCH
# ============================================================

def download_batch(batch):

    tickers = [
        f"{symbol}.NS"
        for symbol in batch
    ]

    try:

        data = yf.download(
            tickers=tickers,
            period="2y",
            interval="1d",
            group_by="ticker",
            auto_adjust=False,
            progress=False,
            threads=True
        )

        return data

    except Exception:

        return None


# ============================================================
# PROCESS ONE STOCK
# ============================================================

def process_stock(
    symbol,
    data,
    stats
):

    ticker = f"{symbol}.NS"

    try:

        # ----------------------------------------------------
        # Extract ticker data
        # ----------------------------------------------------

        if ticker in data.columns.get_level_values(0):

            df = data[ticker].copy()

        else:

            return None

        if df.empty:

            return None

        # ----------------------------------------------------
        # Clean data
        # ----------------------------------------------------

        required_columns = [
            "Close",
            "High"
        ]

        df = df.dropna(
            subset=required_columns
        )

        if df.empty:

            return None

        # ----------------------------------------------------
        # CONDITION 1
        # Minimum trading history
        # ----------------------------------------------------

        trading_days = len(df)

        if trading_days < MIN_TRADING_DAYS:

            return None

        stats["365_days"] += 1

        # ----------------------------------------------------
        # Current LTP
        # ----------------------------------------------------

        ltp = float(
            df["Close"].iloc[-1]
        )

        # ----------------------------------------------------
        # CONDITION 2
        # LTP > ₹100
        # ----------------------------------------------------

        if ltp <= MIN_LTP:

            return None

        stats["ltp"] += 1

        # ----------------------------------------------------
        # 50 DMA
        # ----------------------------------------------------

        sma50 = (
            df["Close"]
            .rolling(
                window=50,
                min_periods=50
            )
            .mean()
            .iloc[-1]
        )

        if pd.isna(sma50):

            return None

        sma50 = float(sma50)

        # ----------------------------------------------------
        # Distance from 50 DMA
        # ----------------------------------------------------

        distance_from_50dma = (
            (ltp - sma50)
            / sma50
        ) * 100

        # ----------------------------------------------------
        # CONDITION 3
        # Within +/-15% of 50 DMA
        # ----------------------------------------------------

        if abs(distance_from_50dma) > DMA50_DISTANCE:

            return None

        stats["dma50"] += 1

        # ----------------------------------------------------
        # 52 WEEK HIGH
        #
        # Last 252 trading sessions
        # ----------------------------------------------------

        last_252 = df.tail(252)

        if len(last_252) < 252:

            return None

        high_52w = float(
            last_252["High"].max()
        )

        # ----------------------------------------------------
        # % below 52 week high
        # ----------------------------------------------------

        below_52w_high = (
            (high_52w - ltp)
            / high_52w
        ) * 100

        # Protect against tiny floating point negatives
        below_52w_high = max(
            0.0,
            below_52w_high
        )

        # ----------------------------------------------------
        # CONDITION 4
        # Within 5% below 52W high
        # ----------------------------------------------------

        if below_52w_high > MAX_BELOW_52W_HIGH:

            return None

        stats["52w"] += 1

        # ----------------------------------------------------
        # TRADINGVIEW LINK
        # ----------------------------------------------------

        tradingview_url = (
            "https://www.tradingview.com/chart/"
            "?symbol=NSE%3A"
            + symbol
        )

        # ----------------------------------------------------
        # RESULT
        # ----------------------------------------------------

        return {

            "Symbol": symbol,

            "LTP": round(
                ltp,
                2
            ),

            "50 DMA": round(
                sma50,
                2
            ),

            "% From 50 DMA": round(
                distance_from_50dma,
                2
            ),

            "52 Week High": round(
                high_52w,
                2
            ),

            "% Below 52W High": round(
                below_52w_high,
                2
            ),

            "Trading Days": trading_days,

            "TradingView Chart":
                tradingview_url
        }

    except Exception:

        return None


# ============================================================
# SCAN FUNCTION
# ============================================================

def run_scan():

    start_time = time.time()

    # --------------------------------------------------------
    # GET NSE UNIVERSE
    # --------------------------------------------------------

    with st.status(
        "Preparing NSE stock universe...",
        expanded=True
    ) as status:

        try:

            symbols = get_nse_symbols()

        except Exception as e:

            status.update(
                label="❌ Unable to load NSE stock list",
                state="error"
            )

            st.error(
                f"NSE data error: {e}"
            )

            return None

        st.write(
            f"Found {len(symbols):,} NSE EQ stocks."
        )

        status.update(
            label="NSE stock universe loaded",
            state="complete"
        )

    # --------------------------------------------------------
    # STATISTICS
    # --------------------------------------------------------

    stats = {

        "365_days": 0,

        "ltp": 0,

        "dma50": 0,

        "52w": 0
    }

    results = []

    total_batches = (
        len(symbols)
        + BATCH_SIZE
        - 1
    ) // BATCH_SIZE

    # --------------------------------------------------------
    # PROGRESS
    # --------------------------------------------------------

    st.subheader(
        "🔎 Scanning..."
    )

    progress = st.progress(
        0,
        text="Starting scan..."
    )

    progress_text = st.empty()

    # --------------------------------------------------------
    # BATCH PROCESSING
    # --------------------------------------------------------

    for batch_number, start in enumerate(
        range(
            0,
            len(symbols),
            BATCH_SIZE
        ),
        start=1
    ):

        batch = symbols[
            start:
            start + BATCH_SIZE
        ]

        data = download_batch(
            batch
        )

        if data is not None and not data.empty:

            for symbol in batch:

                result = process_stock(
                    symbol,
                    data,
                    stats
                )

                if result is not None:

                    results.append(
                        result
                    )

        percentage = (
            batch_number
            / total_batches
        )

        progress.progress(
            percentage,
            text=(
                f"Scanning batch "
                f"{batch_number}/{total_batches}"
            )
        )

        progress_text.write(
            f"Processed "
            f"{min(start + BATCH_SIZE, len(symbols)):,}"
            f" / {len(symbols):,} stocks"
        )

        time.sleep(
            BATCH_DELAY
        )

    progress.progress(
        1.0,
        text="Scan completed"
    )

    # --------------------------------------------------------
    # DATAFRAME
    # --------------------------------------------------------

    result_df = pd.DataFrame(
        results
    )

    elapsed = round(
        time.time() - start_time,
        1
    )

    if result_df.empty:

        return {
            "data": None,
            "stats": stats,
            "total": len(symbols),
            "elapsed": elapsed
        }

    # --------------------------------------------------------
    # SORT
    # --------------------------------------------------------

    result_df = result_df.sort_values(
        by="% Below 52W High",
        ascending=True
    ).reset_index(
        drop=True
    )

    # Rank
    result_df.insert(
        0,
        "Rank",
        range(
            1,
            len(result_df) + 1
        )
    )

    return {
        "data": result_df,
        "stats": stats,
        "total": len(symbols),
        "elapsed": elapsed
    }


# ============================================================
# RUN BUTTON
# ============================================================

st.markdown("### 🚀 Run Scanner")

run_button = st.button(
    "🔎 RUN SCAN",
    type="primary",
    use_container_width=True
)


# ============================================================
# EXECUTE
# ============================================================

if run_button:

    scan_result = run_scan()

    if scan_result is None:

        st.stop()

    result_df = scan_result["data"]

    stats = scan_result["stats"]

    total_stocks = scan_result["total"]

    elapsed = scan_result["elapsed"]

    # --------------------------------------------------------
    # SUMMARY
    # --------------------------------------------------------

    st.success(
        f"Scan completed in {elapsed} seconds"
    )

    st.markdown(
        "### 📊 Scan Summary"
    )

    c1, c2, c3, c4, c5 = st.columns(5)

    c1.metric(
        "NSE Stocks",
        f"{total_stocks:,}"
    )

    c2.metric(
        "365+ Days",
        f"{stats['365_days']:,}"
    )

    c3.metric(
        "LTP > ₹100",
        f"{stats['ltp']:,}"
    )

    c4.metric(
        "Within 50 DMA",
        f"{stats['dma50']:,}"
    )

    c5.metric(
        "Final Matches",
        f"{stats['52w']:,}"
    )

    # --------------------------------------------------------
    # NO RESULTS
    # --------------------------------------------------------

    if result_df is None:

        st.warning(
            "No stocks matched all conditions."
        )

        st.stop()

    # --------------------------------------------------------
    # RESULTS
    # --------------------------------------------------------

    st.markdown(
        f"### 📈 Results — {len(result_df)} stocks"
    )

    # --------------------------------------------------------
    # DOWNLOAD CSV
    # --------------------------------------------------------

    csv_data = result_df.to_csv(
        index=False
    ).encode(
        "utf-8-sig"
    )

    st.download_button(
        label="⬇️ Download CSV",
        data=csv_data,
        file_name=(
            "NSE_Stock_Scanner_"
            + datetime.now().strftime(
                "%Y%m%d_%H%M"
            )
            + ".csv"
        ),
        mime="text/csv",
        use_container_width=True
    )

    # --------------------------------------------------------
    # TABLE
    # --------------------------------------------------------

    display_df = result_df.copy()

    st.dataframe(
        display_df,
        use_container_width=True,
        hide_index=True,
        column_config={

            "TradingView Chart":
                st.column_config.LinkColumn(
                    "📈 Open Chart",
                    help=(
                        "Open stock chart "
                        "in TradingView"
                    ),
                    display_text="Open Chart"
                ),

            "LTP":
                st.column_config.NumberColumn(
                    "LTP",
                    format="₹%.2f"
                ),

            "50 DMA":
                st.column_config.NumberColumn(
                    "50 DMA",
                    format="₹%.2f"
                ),

            "% From 50 DMA":
                st.column_config.NumberColumn(
                    "% From 50 DMA",
                    format="%.2f%%"
                ),

            "52 Week High":
                st.column_config.NumberColumn(
                    "52 Week High",
                    format="₹%.2f"
                ),

            "% Below 52W High":
                st.column_config.NumberColumn(
                    "% Below 52W High",
                    format="%.2f%%"
                ),

            "Trading Days":
                st.column_config.NumberColumn(
                    "Trading Days",
                    format="%d"
                )
        }
    )

    # --------------------------------------------------------
    # LAST SCAN
    # --------------------------------------------------------

    st.caption(
        "Last scan: "
        + datetime.now().strftime(
            "%d-%m-%Y %H:%M:%S"
        )
    )

else:

    # --------------------------------------------------------
    # INITIAL SCREEN
    # --------------------------------------------------------

    st.info(
        "Tap **🔎 RUN SCAN** to scan the NSE."
    )

    st.markdown(
        """
        ### Current filters

        | Condition | Requirement |
        |---|---|
        | Market | NSE Equity |
        | History | ≥ 365 trading days |
        | LTP | > ₹100 |
        | 50 DMA | Within ±15% |
        | 52 Week High | ≤5% below |
        """
  )
