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
# Updated Reflex UI + user-selectable 52W High filter
# + optional 50 DMA filter
# ============================================================

MIN_LTP = 100.0
DMA50_DISTANCE = 15.0
MIN_TRADING_DAYS = 365

# User can select either 5% or 7% below 52-week high.
DEFAULT_52W_HIGH_FILTER = 5.0

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
            if str(column).strip().upper()
            in {
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
    use_dma50_filter: bool,
    max_below_52w_high: float,
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

        # Condition 1: stock must have at least 365 trading days.
        if trading_days < MIN_TRADING_DAYS:
            return None
        stats["365_days"] += 1

        # Condition 2: LTP must be above ₹100.
        ltp = float(df["Close"].iloc[-1])
        if ltp <= MIN_LTP:
            return None
        stats["ltp"] += 1

        # Optional Condition 3: current price must remain within ±15%
        # of the 50 DMA. If the user turns this filter OFF, this
        # condition is skipped completely.
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

        if use_dma50_filter:
            if abs(distance) > DMA50_DISTANCE:
                return None
            stats["dma50"] += 1

        # Condition 4: 52-week high distance selected by the user.
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

        if below_high > max_below_52w_high:
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

    progress: float = 0.0
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

    # ---------------- USER SCAN SETTINGS ----------------
    # 5% or 7% below 52-week high.
    max_below_52w_high: str = "5"

    # Keep the existing ±15% 50-DMA condition, but let the user
    # switch it ON/OFF before running the scan.
    use_dma50_filter: bool = True

    rows: list[list[str]] = []
    csv_data: str = ""

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

    @rx.var
    def progress_ring(self) -> str:
        return (
            f"conic-gradient({ACCENT} {self.progress}%, "
            f"#E9EEF1 {self.progress}% 100%)"
        )

    @rx.event
    def set_52w_filter(self, value: str):
        if value in {"5", "7"}:
            self.max_below_52w_high = value

    @rx.event
    def set_dma50_filter(self, value: bool):
        self.use_dma50_filter = value

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
            self.progress = 0.0
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

            # Take a snapshot of the settings at the moment RUN SCAN
            # is pressed. This keeps one scan consistent even if the UI
            # changes while the download is running.
            selected_high_filter = float(self.max_below_52w_high)
            selected_dma_filter = self.use_dma50_filter

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
                                selected_dma_filter,
                                selected_high_filter,
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

                    async with self:
                        self.processed = processed
                        self.progress = round(progress_pct, 1)
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
                    self.progress = 100.0
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
# UI DESIGN
# ============================================================

BG = "#F5F7F9"
SURFACE = "#FFFFFF"
TEXT = "#17202A"
MUTED = "#6B7280"
BORDER = "#E3E8EC"
ACCENT = "#10A37F"
ACCENT_DARK = "#078564"
DANGER = "#D64545"
SOFT_GREEN = "#E8F7F1"
SOFT_BLUE = "#EEF5FF"
SOFT_PURPLE = "#F4F0FF"
SOFT_ORANGE = "#FFF5E8"


# ---------------- BASIC COMPONENTS ----------------


def panel(*children, **props) -> rx.Component:
    return rx.box(
        *children,
        background=SURFACE,
        border=f"1px solid {BORDER}",
        border_radius="14px",
        **props,
    )


def stat_card(label: str, value) -> rx.Component:
    return rx.box(
        rx.text(
            label,
            size="1",
            weight="bold",
            color=MUTED,
            letter_spacing="0.04em",
        ),
        rx.heading(
            value,
            size="5",
            color=TEXT,
            margin_top="4px",
        ),
        padding="14px 16px",
        border=f"1px solid {BORDER}",
        border_radius="11px",
        background=SURFACE,
        width="100%",
    )


def filter_badge(
    text: str,
    color_scheme: str = "gray",
) -> rx.Component:
    return rx.badge(
        text,
        color_scheme=color_scheme,
        variant="soft",
        size="2",
        padding="6px 10px",
    )


# ---------------- TOP NAVIGATION ----------------


def top_bar() -> rx.Component:
    return rx.box(
        rx.hstack(
            rx.hstack(
                rx.box(
                    width="8px",
                    height="8px",
                    border_radius="50%",
                    background=ACCENT,
                ),
                rx.text(
                    "SF-LIVE.01",
                    size="1",
                    weight="bold",
                    color=TEXT,
                    letter_spacing="0.08em",
                ),
                spacing="2",
            ),

            rx.spacer(),

            rx.hstack(
                rx.text(
                    "⌁",
                    size="6",
                    weight="bold",
                    color=TEXT,
                ),
                rx.text(
                    "PIPSGO",
                    size="4",
                    weight="bold",
                    color=TEXT,
                    letter_spacing="0.02em",
                ),
                spacing="2",
            ),

            rx.spacer(),

            rx.hstack(
                rx.box(
                    width="7px",
                    height="7px",
                    border_radius="50%",
                    background=ACCENT,
                ),
                rx.text(
                    "SYNCED: 100MS AGO",
                    size="1",
                    color=MUTED,
                    weight="bold",
                ),
                rx.box(
                    "K",
                    width="28px",
                    height="28px",
                    border_radius="50%",
                    background="#E8ECEF",
                    color=TEXT,
                    display="flex",
                    align_items="center",
                    justify_content="center",
                 
