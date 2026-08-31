
import asyncio
import io
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

import pandas as pd
import requests
import reflex as rx
import yfinance as yf


# ============================================================
# PIPSGO NSE STOCK SCANNER
# ============================================================

MIN_LTP = 100.0
DMA50_DISTANCE = 15.0
MAX_BELOW_52W_HIGH = 5.0
MIN_TRADING_DAYS = 365

# Faster Yahoo downloads.
BATCH_SIZE = 100
DOWNLOAD_WORKERS = 3
BATCH_RETRIES = 2
DOWNLOAD_TIMEOUT = 25

NSE_URL = "https://archives.nseindia.com/content/equities/EQUITY_L.csv"
NSE_HOME = "https://www.nseindia.com/"


# ============================================================
# DATA
# ============================================================

def get_nse_universe() -> pd.DataFrame:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/131.0 Safari/537.36"
        ),
        "Accept": (
            "text/html,application/xhtml+xml,application/xml;"
            "q=0.9,*/*;q=0.8"
        ),
        "Referer": NSE_HOME,
    }

    session = requests.Session()
    session.get(NSE_HOME, headers=headers, timeout=20)
    response = session.get(NSE_URL, headers=headers, timeout=30)
    response.raise_for_status()

    df = pd.read_csv(io.BytesIO(response.content))
    df.columns = [str(c).strip() for c in df.columns]

    if "SERIES" in df.columns:
        df = df[df["SERIES"].astype(str).str.strip().eq("EQ")].copy()

    if "SYMBOL" not in df.columns:
        raise ValueError("NSE SYMBOL column not found.")

    company_column = next(
        (
            column
            for column in df.columns
            if str(column).strip().upper() in {
                "NAME OF COMPANY",
                "NAME_OF_COMPANY",
                "COMPANY NAME",
                "COMPANY_NAME",
            }
        ),
        None,
    )

    if company_column is None:
        df["Company"] = df["SYMBOL"].astype(str).str.strip()
    else:
        df["Company"] = df[company_column].fillna("").astype(str).str.strip()

    universe = df[["SYMBOL", "Company"]].copy()
    universe["SYMBOL"] = universe["SYMBOL"].astype(str).str.strip()
    universe = universe[
        universe["SYMBOL"].ne("") & universe["SYMBOL"].notna()
    ]
    universe = universe.drop_duplicates("SYMBOL").sort_values("SYMBOL")
    return universe.reset_index(drop=True)


def download_batch(batch: list[str]) -> pd.DataFrame | None:
    tickers = [f"{symbol}.NS" for symbol in batch]

    for attempt in range(BATCH_RETRIES + 1):
        try:
            data = yf.download(
                tickers=tickers,
                period="18mo",
                interval="1d",
                group_by="ticker",
                auto_adjust=False,
                progress=False,
                threads=True,
                timeout=DOWNLOAD_TIMEOUT,
            )
            if data is not None and not data.empty:
                return data
        except Exception:
            pass

        if attempt < BATCH_RETRIES:
            time.sleep(1.0 + attempt)

    return None


def process_stock(
    symbol: str,
    company: str,
    data: pd.DataFrame | None,
    stats: dict[str, int],
) -> dict | None:
    ticker = f"{symbol}.NS"

    try:
        if data is None or data.empty:
            return None
        if not isinstance(data.columns, pd.MultiIndex):
            return None
        if ticker not in data.columns.get_level_values(0):
            return None

        df = data[ticker].copy()
        required = ["Close", "High"]

        if df.empty or any(c not in df.columns for c in required):
            return None

        df = df.dropna(subset=required)
        trading_days = len(df)

        if trading_days < MIN_TRADING_DAYS:
            return None
        stats["365_days"] += 1

        ltp = float(df["Close"].iloc[-1])

        if ltp <= MIN_LTP:
            return None
        stats["ltp"] += 1

        sma50 = (
            df["Close"]
            .rolling(50, min_periods=50)
            .mean()
            .iloc[-1]
        )

        if pd.isna(sma50):
            return None

        sma50 = float(sma50)
        distance = ((ltp - sma50) / sma50) * 100.0

        if abs(distance) > DMA50_DISTANCE:
            return None
        stats["dma50"] += 1

        last_252 = df.tail(252)

        if len(last_252) < 252:
            return None

        high_52w = float(last_252["High"].max())

        if high_52w <= 0:
            return None

        below_high = max(
            0.0,
            ((high_52w - ltp) / high_52w) * 100.0,
        )

        if below_high > MAX_BELOW_52W_HIGH:
            return None

        stats["52w"] += 1

        return {
            "Rank": 0,
            "Symbol": symbol,
            "Company": company,
            "LTP": round(ltp, 2),
            "50 DMA": round(sma50, 2),
            "% From 50 DMA": round(distance, 2),
            "52 Week High": round(high_52w, 2),
            "% Below 52W High": round(below_high, 2),
            "Trading Days": trading_days,
            "Sector": "—",
            "Chart": (
                "https://www.tradingview.com/chart/"
                f"?symbol=NSE%3A{symbol}"
            ),
        }

    except Exception:
        return None


def fetch_sector(symbol: str) -> str:
    try:
        info = yf.Ticker(f"{symbol}.NS").get_info()
        sector = info.get("sector")
        return str(sector).strip() if sector else "—"
    except Exception:
        return "—"


def fetch_sectors(symbols: list[str]) -> dict[str, str]:
    if not symbols:
        return {}

    sectors: dict[str, str] = {}

    # Only final matches need sector lookups.
    with ThreadPoolExecutor(max_workers=8) as executor:
        future_map = {
            executor.submit(fetch_sector, symbol): symbol
            for symbol in symbols
        }

        for future in as_completed(future_map):
            symbol = future_map[future]
            try:
                sectors[symbol] = future.result()
            except Exception:
                sectors[symbol] = "—"

    return sectors


# ============================================================
# STATE
# ============================================================

class ScannerState(rx.State):
    scanning: bool = False
    stop_requested: bool = False

    # Progress is always 0..100 and must remain an integer for Radix progress bars.
    progress: int = 0

    status: str = "Ready to scan."
    processed: int = 0
    total: int = 0
    elapsed: float = 0.0

    count_365: int = 0
    count_ltp: int = 0
    count_dma50: int = 0
    count_52w: int = 0
    count_final: int = 0
    avg_below_52w: float = 0.0

    rows: list[list[str]] = []
    csv_data: str = ""

    # Trading Days is intentionally kept for scanning/CSV, but hidden
    # from the on-screen result table.
    columns: list[str] = [
        "Rank",
        "Symbol",
        "Company",
        "LTP",
        "50 DMA",
        "% From 50 DMA",
        "52 Week High",
        "% Below 52W High",
        "Trading Days",
        "Sector",
        "Chart",
    ]

    @rx.event
    def stop_scan(self):
        if self.scanning:
            self.stop_requested = True
            self.status = "Stopping scan after the current download batch..."

    @rx.event(background=True)
    async def run_scan(self):
        async with self:
            if self.scanning:
                return

            self.scanning = True
            self.stop_requested = False
            self.progress = 0
            self.status = "Loading NSE equity universe..."
            self.processed = 0
            self.total = 0
            self.elapsed = 0.0
            self.count_365 = 0
            self.count_ltp = 0
            self.count_dma50 = 0
            self.count_52w = 0
            self.count_final = 0
            self.avg_below_52w = 0.0
            self.rows = []
            self.csv_data = ""

        start_time = time.time()

        try:
            universe = await asyncio.to_thread(get_nse_universe)

            symbols = universe["SYMBOL"].tolist()
            company_map = dict(
                zip(universe["SYMBOL"], universe["Company"])
            )

            async with self:
                self.total = len(symbols)
                self.status = f"Found {len(symbols):,} NSE EQ stocks."

            stats = {
                "365_days": 0,
                "ltp": 0,
                "dma50": 0,
                "52w": 0,
            }

            results: list[dict] = []

            batches = [
                symbols[i:i + BATCH_SIZE]
                for i in range(0, len(symbols), BATCH_SIZE)
            ]

            total_batches = len(batches)
            completed_batches = 0

            # Process a small number of batches concurrently. Unlike creating
            # every task at once, this lets Stop Scan take effect between waves.
            for wave_start in range(0, total_batches, DOWNLOAD_WORKERS):
                async with self:
                    if self.stop_requested:
                        break

                wave = batches[
                    wave_start:wave_start + DOWNLOAD_WORKERS
                ]

                tasks = [
                    asyncio.create_task(
                        asyncio.to_thread(download_batch, batch)
                    )
                    for batch in wave
                ]

                wave_data = await asyncio.gather(
                    *tasks,
                    return_exceptions=True,
                )

                for batch, data in zip(wave, wave_data):
                    if isinstance(data, Exception):
                        data = None

                    if data is not None and not data.empty:
                        for symbol in batch:
                            result = process_stock(
                                symbol,
                                company_map.get(symbol, symbol),
                                data,
                                stats,
                            )

                            if result is not None:
                                results.append(result)

                    completed_batches += 1

                    processed = min(
                        completed_batches * BATCH_SIZE,
                        len(symbols),
                    )

                    progress_pct = (
                        processed / len(symbols) * 100.0
                        if symbols
                        else 100.0
                    )
                    progress_value = int(round(progress_pct))

                    async with self:
                        self.processed = processed
                        self.progress = progress_value
                        self.count_365 = stats["365_days"]
                        self.count_ltp = stats["ltp"]
                        self.count_dma50 = stats["dma50"]
                        self.count_52w = stats["52w"]

                        if not self.stop_requested:
                            self.status = (
                                f"Scanning batch "
                                f"{completed_batches}/{total_batches} "
                                f"— {processed:,}/{len(symbols):,}"
                            )

                async with self:
                    if self.stop_requested:
                        break

            async with self:
                stopped = self.stop_requested

            # Sort and rank whatever has been collected.
            results.sort(
                key=lambda x: x["% Below 52W High"]
            )

            for index, result in enumerate(results, start=1):
                result["Rank"] = index

            # Only fetch sectors when the user lets the scan finish.
            if results and not stopped:
                async with self:
                    self.status = (
                        f"Scan complete. Loading sectors for "
                        f"{len(results):,} matches..."
                    )

                sector_map = await asyncio.to_thread(
                    fetch_sectors,
                    [result["Symbol"] for result in results],
                )

                for result in results:
                    result["Sector"] = sector_map.get(
                        result["Symbol"],
                        "—",
                    )

            avg_below = (
                sum(
                    float(result["% Below 52W High"])
                    for result in results
                ) / len(results)
                if results
                else 0.0
            )

            df = pd.DataFrame(
                results,
                columns=self.columns,
            )

            csv_text = (
                df.to_csv(index=False)
                if not df.empty
                else ""
            )

            # Trading Days remains in CSV/data but is hidden from the UI.
            rows = [
                [
                    str(result["Rank"]),
                    result["Symbol"],
                    result["Company"],
                    f"{result['LTP']:,.2f}",
                    f"{result['50 DMA']:,.2f}",
                    f"{result['% From 50 DMA']:.2f}",
                    f"{result['52 Week High']:,.2f}",
                    f"{result['% Below 52W High']:.2f}",
                    str(result["Trading Days"]),
                    result["Sector"],
                    result["Chart"],
                ]
                for result in results
            ]

            elapsed = round(
                time.time() - start_time,
                1,
            )

            async with self:
                self.rows = rows
                self.csv_data = csv_text
                self.elapsed = elapsed
                self.count_final = len(results)
                self.avg_below_52w = round(avg_below, 2)

                if stopped:
                    self.status = (
                        f"Scan stopped: {len(results)} matches "
                        f"collected in {elapsed:.1f} seconds."
                    )
                else:
                    self.progress = 100
                    self.status = (
                        f"Scan completed: {len(results)} matches "
                        f"in {elapsed:.1f} seconds."
                    )

        except Exception as exc:
            async with self:
                self.status = f"Scan failed: {exc}"
                self.elapsed = round(
                    time.time() - start_time,
                    1,
                )

        finally:
            async with self:
                self.scanning = False
                self.stop_requested = False

    @rx.event
    def download_csv(self):
        if not self.csv_data:
            return rx.window_alert(
                "Run the scanner first."
            )

        filename = (
            "PIPSGO_NSE_Scanner_"
            + datetime.now().strftime("%Y%m%d_%H%M")
            + ".csv"
        )

        return rx.download(
            data=self.csv_data,
            filename=filename,
        )


# ============================================================
# UI
# ============================================================

BG = "#F4F7F5"
SURFACE = "#FFFFFF"
TEXT = "#17202A"
MUTED = "#6B7280"
BORDER = "#DFE6E2"
ACCENT = "#18A873"
ACCENT_DARK = "#11875D"
DANGER = "#D64545"


def panel(*children, **props) -> rx.Component:
    return rx.box(
        *children,
        background=SURFACE,
        border=f"1px solid {BORDER}",
        border_radius="14px",
        padding="18px",
        **props,
    )


def stat_card(label: str, value) -> rx.Component:
    return rx.box(
        rx.text(
            label,
            size="1",
            weight="bold",
            color=MUTED,
        ),
        rx.heading(
            value,
            size="5",
            color=TEXT,
            margin_top="4px",
        ),
        padding="13px",
        border=f"1px solid {BORDER}",
        border_radius="10px",
        background=SURFACE,
        width="100%",
    )


def sidebar() -> rx.Component:
    return rx.box(
        rx.vstack(
            rx.text(
                "PIPSGO",
                size="6",
                weight="bold",
                color=TEXT,
            ),

            rx.text(
                "SCANNERS LIBRARY",
                size="1",
                weight="bold",
                color=MUTED,
            ),

            rx.box(
                rx.vstack(
                    rx.hstack(
                        rx.text(
                            "NSE Stock Scanner",
                            size="3",
                            weight="bold",
                            color=TEXT,
                        ),
                        rx.spacer(),
                        rx.cond(
                            ScannerState.scanning,
                            rx.badge(
                                "LIVE",
                                color_scheme="green",
                                variant="soft",
                            ),
                            rx.badge(
                                "IDLE",
                                color_scheme="gray",
                                variant="soft",
                            ),
                        ),
                        width="100%",
                    ),

                    rx.text(
                        "50-DMA + 52-Week High scanner",
                        size="2",
                        color=MUTED,
                    ),

                    align="start",
                    width="100%",
                    spacing="2",
                ),

                border=f"1px solid {BORDER}",
                border_radius="10px",
                padding="14px",
                width="100%",
                background=SURFACE,
            ),

            rx.spacer(),

            rx.text(
                "PIPSGO",
                size="1",
                color=MUTED,
            ),

            width="100%",
            height="100%",
            align="start",
        ),

        width="230px",
        min_width="230px",
        height="100vh",
        padding="24px 14px",
        border_right=f"1px solid {BORDER}",
        background=SURFACE,
    )


def filter_badge(
    text: str,
    color_scheme: str,
) -> rx.Component:
    return rx.badge(
        text,
        color_scheme=color_scheme,
        variant="soft",
        size="2",
        padding="6px 10px",
    )


def scanner_header() -> rx.Component:
    return panel(
        rx.hstack(
            rx.vstack(
                rx.heading(
                    "52W HIGH + 50MA",
                    size="6",
                    color=TEXT,
                ),

                rx.text(
                    "Scans NSE equities using 50-DMA + 52-Week High conditions.",
                    size="2",
                    color=MUTED,
                ),

                align="start",
                spacing="1",
            ),

            rx.spacer(),

            # RUN / STOP button
            rx.cond(
                ScannerState.scanning,

                rx.button(
                    "■  STOP SCAN",
                    on_click=ScannerState.stop_scan,
                    background=DANGER,
                    color="white",
                    size="3",
                    _hover={
                        "background": "#B93636"
                    },
                ),

                rx.button(
                    "▶  RUN SCAN",
                    on_click=ScannerState.run_scan,
                    background=ACCENT,
                    color="white",
                    size="3",
                    _hover={
                        "background": ACCENT_DARK
                    },
                ),
            ),

            width="100%",
            align="center",
        ),

        rx.divider(
            margin_y="14px"
        ),

        rx.vstack(
            rx.text(
                "ACTIVE FILTERS",
                size="1",
                weight="bold",
                color=MUTED,
            ),

            rx.hstack(
                filter_badge(
                    f"LTP > ₹{MIN_LTP:,.0f}",
                    "blue",
                ),

                filter_badge(
                    f"50 DMA ±{DMA50_DISTANCE}%",
                    "purple",
                ),

                filter_badge(
                    f"52W High ≤{MAX_BELOW_52W_HIGH}%",
                    "green",
                ),

                filter_badge(
                    f"≥{MIN_TRADING_DAYS} Trading Days",
                    "orange",
                ),

                wrap="wrap",
                width="100%",
            ),

            align="start",
            spacing="2",
        ),

        width="100%",
    )


def table_row(row: list[str]) -> rx.Component:
    return rx.table.row(
        rx.table.cell(
            rx.text(
                row[0],
                size="1",
                color=MUTED,
            )
        ),

        rx.table.cell(
            rx.text(
                row[1],
                weight="bold",
                size="2",
                color=TEXT,
            )
        ),

        rx.table.cell(
            rx.text(
                row[2],
                size="1",
                color=TEXT,
                max_width="125px",
                overflow="hidden",
                text_overflow="ellipsis",
                white_space="nowrap",
            )
        ),

        rx.table.cell(
            rx.text(
                f"₹{row[3]}",
                size="1",
                color=TEXT,
            )
        ),

        rx.table.cell(
            rx.text(
                f"₹{row[4]}",
                size="1",
                color=TEXT,
            )
        ),

        rx.table.cell(
            rx.text(
                f"{row[5]}%",
                size="1",
                color=TEXT,
            )
        ),

        rx.table.cell(
            rx.text(
                f"₹{row[6]}",
                size="1",
                color=TEXT,
            )
        ),

        rx.table.cell(
            rx.badge(
                f"{row[7]}%",
                color_scheme="green",
                variant="soft",
                size="1",
            )
        ),

        # Trading Days intentionally hidden from the result table.

        rx.table.cell(
            rx.text(
                row[9],
                size="1",
                color=MUTED,
                max_width="95px",
                overflow="hidden",
                text_overflow="ellipsis",
                white_space="nowrap",
            )
        ),

        rx.table.cell(
            rx.link(
                "Open ↗",
                href=row[10],
                is_external=True,
                color_scheme="green",
                weight="bold",
                underline="none",
                size="1",
            )
        ),

        white_space="nowrap",
    )


def results_table() -> rx.Component:
    return rx.box(
        rx.table.root(
            rx.table.header(
                rx.table.row(
                    rx.table.column_header_cell("#"),
                    rx.table.column_header_cell("SYMBOL"),
                    rx.table.column_header_cell("COMPANY"),
                    rx.table.column_header_cell("LTP"),
                    rx.table.column_header_cell("50 DMA"),
                    rx.table.column_header_cell("% 50 DMA"),
                    rx.table.column_header_cell("52W HIGH"),
                    rx.table.column_header_cell("% BELOW"),
                    rx.table.column_header_cell("SECTOR"),
                    rx.table.column_header_cell("CHART"),
                )
            ),

            rx.table.body(
                rx.foreach(
                    ScannerState.rows,
                    table_row,
                )
            ),

            width="100%",
            size="1",
            variant="surface",
        ),

        width="100%",
        overflow_x="auto",
    )


def results_panel() -> rx.Component:
    return panel(
        # Table title + Export CSV on the top-right
        rx.hstack(
            rx.heading(
                "SCAN RESULTS",
                size="3",
                color=TEXT,
            ),

            rx.spacer(),

            rx.cond(
                ScannerState.csv_data != "",
                rx.button(
                    "⇩  EXPORT CSV",
                    on_click=ScannerState.download_csv,
                    background=ACCENT,
                    color="white",
                    size="2",
                    _hover={
                        "background": ACCENT_DARK
                    },
                ),
                rx.fragment(),
            ),

            width="100%",
            align="center",
        ),

        rx.hstack(
            rx.text(
                ScannerState.status,
                size="1",
                color=MUTED,
            ),
            rx.spacer(),
            rx.cond(
                ScannerState.rows.length() > 0,
                rx.text(
                    ScannerState.count_final.to_string()
                    + " matches",
                    size="1",
                    weight="bold",
                    color=ACCENT_DARK,
                ),
                rx.fragment(),
            ),
            width="100%",
            margin_top="4px",
        ),

        rx.cond(
            ScannerState.scanning,

            rx.vstack(
                rx.progress(
                    value=ScannerState.progress,
                    width="100%",
                    color_scheme="green",
                ),

                rx.hstack(
                    rx.text(
                        ScannerState.processed.to_string()
                        + " / "
                        + ScannerState.total.to_string()
                        + " stocks",
                        size="1",
                        color=MUTED,
                    ),

                    rx.spacer(),

                    rx.text(
                        ScannerState.progress.to_string()
                        + "%",
                        size="1",
                        weight="bold",
                        color=ACCENT_DARK,
                    ),

                    width="100%",
                ),

                width="100%",
                spacing="2",
                margin_top="8px",
            ),

            rx.fragment(),
        ),

        rx.cond(
            ScannerState.rows.length() > 0,

            results_table(),

            rx.box(
                rx.text(
                    "Run the scanner to see matching stocks.",
                    size="2",
                    color=MUTED,
                ),
                padding="40px",
                text_align="center",
                width="100%",
            ),
        ),

        width="100%",
    )


def right_panel() -> rx.Component:
    return rx.vstack(
        panel(
            rx.vstack(
                rx.text(
                    "SCAN COMPLETION",
                    size="2",
                    weight="bold",
                    color=TEXT,
                ),

                rx.progress(
                    value=ScannerState.progress,
                    width="100%",
                    color_scheme="green",
                ),

                rx.heading(
                    ScannerState.progress.to_string()
                    + "%",
                    size="7",
                    color=TEXT,
                ),

                rx.text(
                    ScannerState.processed.to_string()
                    + " / "
                    + ScannerState.total.to_string()
                    + " stocks scanned",
                    size="1",
                    color=MUTED,
                ),

                width="100%",
                align="center",
                spacing="3",
            ),

            width="100%",
        ),

        rx.text(
            "SESSION STATISTICS",
            size="1",
            weight="bold",
            color=MUTED,
        ),

        stat_card(
            "STOCKS SCANNED",
            ScannerState.processed,
        ),

        stat_card(
            "MATCHES FOUND",
            ScannerState.count_final,
        ),

        stat_card(
            "LTP > ₹100",
            ScannerState.count_ltp,
        ),

        stat_card(
            "WITHIN 50 DMA",
            ScannerState.count_dma50,
        ),

        stat_card(
            "≤ 5% BELOW 52W HIGH",
            ScannerState.count_52w,
        ),

        stat_card(
            "AVG. BELOW 52W HIGH",
            ScannerState.avg_below_52w.to_string()
            + "%",
        ),

        stat_card(
            "SCAN DURATION",
            ScannerState.elapsed.to_string()
            + " sec",
        ),

        width="100%",
        spacing="3",
    )


def index() -> rx.Component:
    return rx.box(
        rx.hstack(
            sidebar(),

            rx.box(
                rx.vstack(
                    scanner_header(),
                    results_panel(),
                    width="100%",
                    spacing="4",
                ),

                flex="1",
                padding="24px",
                overflow="auto",
                height="100vh",
                min_width="0",
            ),

            rx.box(
                right_panel(),
                width="270px",
                min_width="270px",
                padding="24px 18px",
                border_left=f"1px solid {BORDER}",
                height="100vh",
                overflow="auto",
                background=BG,
            ),

            width="100%",
            height="100vh",
            spacing="0",
            align="stretch",
        ),

        background=BG,
        color=TEXT,
        width="100%",
        min_height="100vh",
    )


app = rx.App(
    theme=rx.theme(
        appearance="light",
        radius="medium",
        accent_color="green",
    )
)

app.add_page(index)
