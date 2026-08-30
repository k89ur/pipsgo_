import reflex as rx
import pandas as pd
import yfinance as yf
import requests
import io
import time
import asyncio
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache


# ============================================================
# SETTINGS
# ============================================================

MIN_LTP = 100.0
DMA50_DISTANCE = 15.0
MAX_BELOW_52W_HIGH = 5.0
MIN_TRADING_DAYS = 365

BATCH_SIZE = 50
BATCH_DELAY = 0.35


# ============================================================
# DATA MODEL
# ============================================================

@dataclass
class StockRow:
    rank: int
    symbol: str
    ltp: str
    dma50: str
    from_dma50: str
    high_52w: str
    below_52w: str
    trading_days: int
    tradingview: str


# ============================================================
# NSE SYMBOLS
# ============================================================

@lru_cache(maxsize=1)
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
        "Referer": "https://www.nseindia.com/",
    }

    session = requests.Session()

    session.get(
        "https://www.nseindia.com/",
        headers=headers,
        timeout=20,
    )

    response = session.get(
        url,
        headers=headers,
        timeout=30,
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
        ]

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

    return sorted(symbols)


# ============================================================
# DOWNLOAD BATCH
# ============================================================

def download_batch(batch):

    tickers = [
        f"{symbol}.NS"
        for symbol in batch
    ]

    try:

        return yf.download(
            tickers=tickers,
            period="2y",
            interval="1d",
            group_by="ticker",
            auto_adjust=False,
            progress=False,
            threads=True,
        )

    except Exception:
        return None


# ============================================================
# PROCESS STOCK
# ============================================================

def process_stock(symbol, data, stats):

    ticker = f"{symbol}.NS"

    try:

        if data is None or data.empty:
            return None

        if not isinstance(
            data.columns,
            pd.MultiIndex
        ):
            return None

        if ticker not in data.columns.get_level_values(0):
            return None

        df = data[ticker].copy()

        if df.empty:
            return None

        df = df.dropna(
            subset=["Close", "High"]
        )

        if df.empty:
            return None

        # ----------------------------------------------------
        # HISTORY
        # ----------------------------------------------------

        trading_days = len(df)

        if trading_days < MIN_TRADING_DAYS:
            return None

        stats["365_days"] += 1

        # ----------------------------------------------------
        # LTP
        # ----------------------------------------------------

        ltp = float(
            df["Close"].iloc[-1]
        )

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
                min_periods=50,
            )
            .mean()
            .iloc[-1]
        )

        if pd.isna(sma50):
            return None

        sma50 = float(sma50)

        distance = (
            (ltp - sma50)
            / sma50
        ) * 100

        if abs(distance) > DMA50_DISTANCE:
            return None

        stats["dma50"] += 1

        # ----------------------------------------------------
        # 52 WEEK HIGH
        # ----------------------------------------------------

        last_252 = df.tail(252)

        if len(last_252) < 252:
            return None

        high_52w = float(
            last_252["High"].max()
        )

        below_high = (
            (high_52w - ltp)
            / high_52w
        ) * 100

        below_high = max(
            0.0,
            below_high,
        )

        if below_high > MAX_BELOW_52W_HIGH:
            return None

        stats["52w"] += 1

        # ----------------------------------------------------
        # TRADINGVIEW
        # ----------------------------------------------------

        tradingview = (
            "https://www.tradingview.com/chart/"
            "?symbol=NSE%3A"
            + symbol
        )

        return {
            "Symbol": symbol,
            "LTP": ltp,
            "50 DMA": sma50,
            "% From 50 DMA": distance,
            "52 Week High": high_52w,
            "% Below 52W High": below_high,
            "Trading Days": trading_days,
            "TradingView Chart": tradingview,
        }

    except Exception:
        return None


# ============================================================
# REFLEX STATE
# ============================================================

class ScannerState(rx.State):

    scanning: bool = False
    completed: bool = False

    progress: int = 0
    status: str = "Ready to scan."

    total_stocks: int = 0
    elapsed: str = ""

    days_count: int = 0
    ltp_count: int = 0
    dma_count: int = 0
    final_count: int = 0

    results: list[StockRow] = []

    csv_data: str = ""

    error_message: str = ""

    # --------------------------------------------------------
    # START SCAN
    # --------------------------------------------------------

    @rx.event(background=True)
    async def run_scan(self):

        async with self:
            if self.scanning:
                return

            self.scanning = True
            self.completed = False
            self.progress = 0
            self.status = "Loading NSE stock universe..."
            self.results = []
            self.csv_data = ""
            self.error_message = ""

            self.days_count = 0
            self.ltp_count = 0
            self.dma_count = 0
            self.final_count = 0

        start_time = time.time()

        try:

            # ------------------------------------------------
            # NSE UNIVERSE
            # ------------------------------------------------

            symbols = await asyncio.to_thread(
                get_nse_symbols
            )

            async with self:
                self.total_stocks = len(symbols)
                self.status = (
                    f"Found {len(symbols):,} NSE EQ stocks."
                )

            stats = {
                "365_days": 0,
                "ltp": 0,
                "dma50": 0,
                "52w": 0,
            }

            results = []

            total_batches = (
                len(symbols)
                + BATCH_SIZE
                - 1
            ) // BATCH_SIZE

            # ------------------------------------------------
            # BATCH SCAN
            # ------------------------------------------------

for batch_number, start in enumerate(
                range(
                    0,
                    len(symbols),
                    BATCH_SIZE,
                ),
                start=1,
            ):

                batch = symbols[
                    start:
                    start + BATCH_SIZE
                ]

                data = await asyncio.to_thread(
                    download_batch,
                    batch,
                )

                if data is not None and not data.empty:

                    for symbol in batch:

                        result = process_stock(
                            symbol,
                            data,
                            stats,
                        )

                        if result:
                            results.append(result)

                percentage = int(
                    batch_number
                    / total_batches
                    * 100
                )

                processed = min(
                    start + BATCH_SIZE,
                    len(symbols),
                )

                async with self:

                    self.progress = percentage

                    self.status = (
                        f"Scanning {processed:,} / "
                        f"{len(symbols):,} stocks"
                    )

                    self.days_count = stats["365_days"]
                    self.ltp_count = stats["ltp"]
                    self.dma_count = stats["dma50"]
                    self.final_count = stats["52w"]

                await asyncio.sleep(
                    BATCH_DELAY
                )

            # ------------------------------------------------
            # SORT
            # ------------------------------------------------

            results.sort(
                key=lambda x: x["% Below 52W High"]
            )

            rows = []

            for rank, item in enumerate(
                results,
                start=1,
            ):

                rows.append(
                    StockRow(
                        rank=rank,
                        symbol=item["Symbol"],
                        ltp=f"₹{item['LTP']:,.2f}",
                        dma50=f"₹{item['50 DMA']:,.2f}",
                        from_dma50=(
                            f"{item['% From 50 DMA']:.2f}%"
                        ),
                        high_52w=(
                            f"₹{item['52 Week High']:,.2f}"
                        ),
                        below_52w=(
                            f"{item['% Below 52W High']:.2f}%"
                        ),
                        trading_days=item[
                            "Trading Days"
                        ],
                        tradingview=item[
                            "TradingView Chart"
                        ],
                    )
                )

            # ------------------------------------------------
            # CSV
            # ------------------------------------------------

            csv_df = pd.DataFrame(
                results
            )

            csv_data = csv_df.to_csv(
                index=False
            )

            elapsed = round(
                time.time() - start_time,
                1,
            )

            # ------------------------------------------------
            # FINAL STATE
            # ------------------------------------------------

            async with self:

                self.results = rows

                self.csv_data = csv_data

                self.progress = 100

                self.completed = True

                self.scanning = False

                self.final_count = len(rows)

                self.elapsed = (
                    f"{elapsed} seconds"
                )

                self.status = (
                    f"Scan completed — "
                    f"{len(rows)} matches found."
                )

        except Exception as e:

            async with self:

                self.scanning = False

self.completed = False

                self.error_message = str(e)

                self.status = (
                    "Scanner failed."
                )

    # --------------------------------------------------------
    # DOWNLOAD CSV
    # --------------------------------------------------------

    @rx.event
    def download_csv(self):

        if not self.csv_data:
            return

        filename = (
            "NSE_Stock_Scanner_"
            + datetime.now().strftime(
                "%Y%m%d_%H%M"
            )
            + ".csv"
        )

        return rx.download(
            data=self.csv_data,
            filename=filename,
        )


# ============================================================
# CONDITIONS
# ============================================================

def conditions():

    return rx.card(

        rx.vstack(

            rx.heading(
                "📋 Scan Conditions",
                size="4",
            ),

            rx.text(
                "✅ NSE Equity stocks"
            ),

            rx.text(
                f"✅ Minimum {MIN_TRADING_DAYS} trading days"
            ),

            rx.text(
                f"✅ LTP > ₹{MIN_LTP:,.0f}"
            ),

            rx.text(
                f"✅ LTP within ±{DMA50_DISTANCE}% of 50-DMA"
            ),

            rx.text(
                f"✅ Maximum {MAX_BELOW_52W_HIGH}% below 52-week high"
            ),

            spacing="2",
            align="start",
        ),

        width="100%",
    )


# ============================================================
# SUMMARY
# ============================================================

def summary():

    return rx.grid(

        rx.card(
            rx.text("NSE Stocks"),
            rx.heading(
                ScannerState.total_stocks
            ),
        ),

        rx.card(
            rx.text("365+ Days"),
            rx.heading(
                ScannerState.days_count
            ),
        ),

        rx.card(
            rx.text("LTP > ₹100"),
            rx.heading(
                ScannerState.ltp_count
            ),
        ),

        rx.card(
            rx.text("Within 50 DMA"),
            rx.heading(
                ScannerState.dma_count
            ),
        ),

        rx.card(
            rx.text("Final Matches"),
            rx.heading(
                ScannerState.final_count
            ),
        ),

        columns=rx.breakpoints(
            initial="2",
            sm="3",
            md="5",
        ),

        spacing="3",

        width="100%",
    )


# ============================================================
# RESULT ROW
# ============================================================

def result_row(row: StockRow):

    return rx.table.row(

        rx.table.cell(
            row.rank
        ),

        rx.table.cell(
            row.symbol
        ),

        rx.table.cell(
            row.ltp
        ),

        rx.table.cell(
            row.dma50
        ),

        rx.table.cell(
            row.from_dma50
        ),

        rx.table.cell(
            row.high_52w
        ),

        rx.table.cell(
            row.below_52w
        ),

        rx.table.cell(
            row.trading_days
        ),

        rx.table.cell(

            rx.link(
                "Open Chart",
                href=row.tradingview,
                is_external=True,
            )

        ),
    )


# ============================================================
# RESULTS TABLE
# ============================================================

def results_table():

    return rx.box(

        rx.heading(
            "📈 Scan Results",
            size="5",
            margin_bottom="1em",
        ),

        rx.box(

            rx.table.root(

                rx.table.header(

                    rx.table.row(

                        rx.table.column_header_cell(
                            "#"
                        ),

rx.table.column_header_cell(
                            "Symbol"
                        ),

                        rx.table.column_header_cell(
                            "LTP"
                        ),

                        rx.table.column_header_cell(
                            "50 DMA"
                        ),

                        rx.table.column_header_cell(
                            "% From 50 DMA"
                        ),

                        rx.table.column_header_cell(
                            "52W High"
                        ),

                        rx.table.column_header_cell(
                            "% Below 52W"
                        ),

                        rx.table.column_header_cell(
                            "Trading Days"
                        ),

                        rx.table.column_header_cell(
                            "TradingView"
                        ),
                    )
                ),

                rx.table.body(

                    rx.foreach(
                        ScannerState.results,
                        result_row,
                    )
                ),

                width="100%",
            ),

            overflow_x="auto",
            width="100%",
        ),

        width="100%",
    )


# ============================================================
# MAIN PAGE
# ============================================================

def index():

    return rx.container(

        rx.vstack(

            # HEADER
            rx.vstack(

                rx.heading(
                    "📈 NSE Stock Scanner",
                    size="8",
                ),

                rx.text(
                    "50-DMA + 52-Week High scanner",
                    color="gray",
                ),

                align="start",
                width="100%",
            ),

            conditions(),

            # RUN BUTTON
            rx.button(

                "🔎 RUN SCAN",

                on_click=ScannerState.run_scan,

                loading=ScannerState.scanning,

                disabled=ScannerState.scanning,

                size="4",

                width="100%",
            ),

            # PROGRESS
            rx.cond(

                ScannerState.scanning,

                rx.card(

                    rx.vstack(

                        rx.text(
                            ScannerState.status
                        ),

                        rx.progress(
                            value=ScannerState.progress,
                            max=100,
                            width="100%",
                            size="3",
                        ),

                        rx.text(
                            f"{ScannerState.progress}%"
                        ),

                        spacing="3",
                        width="100%",
                    ),

                    width="100%",
                ),

                rx.cond(

                    ScannerState.completed,

                    rx.card(

                        rx.vstack(

                            rx.text(
                                "✅ "
                                + ScannerState.status
                            ),

                            rx.text(
                                "Scan time: "
                                + ScannerState.elapsed
                            ),

                            spacing="2",
                        ),

                        width="100%",
                    ),

                    rx.text(
                        "Tap RUN SCAN to start."
                    ),
                ),
            ),

            # ERROR
            rx.cond(

                ScannerState.error_message != "",

                rx.callout(
                    ScannerState.error_message,
                    icon="triangle_alert",
                    color_scheme="red",
                    width="100%",
                ),
            ),

# SUMMARY
            rx.cond(

                ScannerState.completed,

                summary(),
            ),

            # DOWNLOAD
            rx.cond(

                ScannerState.final_count > 0,

                rx.button(

                    "⬇️ Download CSV",

                    on_click=ScannerState.download_csv,

                    size="3",

                    width="100%",
                ),
            ),

            # RESULTS
            rx.cond(

                ScannerState.final_count > 0,

                results_table(),
            ),

            spacing="5",

            width="100%",
        ),

        max_width="1400px",

        padding="20px",

        width="100%",
    )


# ============================================================
# APP
# ============================================================

app = rx.App()

app.add_page(
    index,
    title="NSE Stock Scanner",
)
