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
# PIPSGO NSE STOCK SCANNER - SCANNER ENGINE
# ============================================================

MIN_LTP = 100.0
MIN_TRADING_DAYS = 365

DEFAULT_DMA50_DISTANCE = 15.0
DEFAULT_MAX_BELOW_52W_HIGH = 5

MIN_52W_SLIDER = 0
MAX_52W_SLIDER = 7

BATCH_SIZE = 100
DOWNLOAD_WORKERS = 3
BATCH_RETRIES = 2
DOWNLOAD_TIMEOUT = 25

NSE_URL = (
    "https://archives.nseindia.com/content/equities/EQUITY_L.csv"
)
NSE_HOME = "https://www.nseindia.com/"


# ============================================================
# NSE UNIVERSE
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

    session.get(
        NSE_HOME,
        headers=headers,
        timeout=20,
    )

    response = session.get(
        NSE_URL,
        headers=headers,
        timeout=30,
    )

    response.raise_for_status()

    df = pd.read_csv(io.BytesIO(response.content))

    df.columns = [
        str(column).strip()
        for column in df.columns
    ]

    # Only NSE EQ stocks.
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

    # Find company-name column.
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
        df["Company"] = (
            df["SYMBOL"]
            .astype(str)
            .str.strip()
        )
    else:
        df["Company"] = (
            df[company_column]
            .fillna("")
            .astype(str)
            .str.strip()
        )

    universe = df[
        ["SYMBOL", "Company"]
    ].copy()

    universe["SYMBOL"] = (
        universe["SYMBOL"]
        .astype(str)
        .str.strip()
    )

    universe = universe[
        universe["SYMBOL"].ne("")
        & universe["SYMBOL"].notna()
    ]

    universe = (
        universe
        .drop_duplicates("SYMBOL")
        .sort_values("SYMBOL")
    )

    return universe.reset_index(drop=True)


# ============================================================
# YAHOO DOWNLOAD
# ============================================================

def download_batch(
    batch: list[str],
) -> pd.DataFrame | None:

    tickers = [
        f"{symbol}.NS"
        for symbol in batch
    ]

    for attempt in range(
        BATCH_RETRIES + 1
    ):
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

            if (
                data is not None
                and not data.empty
            ):
                return data

        except Exception:
            pass

        if attempt < BATCH_RETRIES:
            time.sleep(1.0 + attempt)

    return None

# ============================================================
# STOCK PROCESSING
# ============================================================

def process_stock(
    symbol: str,
    company: str,
    data: pd.DataFrame | None,
    stats: dict[str, int],
    use_dma50: bool,
    dma50_distance: float,
    max_below_52w_high: float,
) -> dict | None:

    ticker = f"{symbol}.NS"

    try:
        if data is None or data.empty:
            return None

        if not isinstance(
            data.columns,
            pd.MultiIndex,
        ):
            return None

        if ticker not in data.columns.get_level_values(0):
            return None

        df = data[ticker].copy()

        required = [
            "Close",
            "High",
        ]

        if (
            df.empty
            or any(
                column not in df.columns
                for column in required
            )
        ):
            return None

        df = df.dropna(
            subset=required
        )

        trading_days = len(df)

        # ----------------------------------------------------
        # CONDITION 1
        # Minimum trading history
        # ----------------------------------------------------

        if trading_days < MIN_TRADING_DAYS:
            return None

        stats["365_days"] += 1

        # ----------------------------------------------------
        # CONDITION 2
        # LTP > ₹100
        # ----------------------------------------------------

        ltp = float(
            df["Close"].iloc[-1]
        )

        if ltp <= MIN_LTP:
            return None

        stats["ltp"] += 1

        # ----------------------------------------------------
        # CONDITION 3
        # Optional 50 DMA
        #
        # IMPORTANT:
        # If checkbox is OFF, this calculation is completely
        # skipped.
        # ----------------------------------------------------

        sma50 = None
        distance = None

        if use_dma50:

            sma50 = (
                df["Close"]
                .rolling(
                    50,
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
            ) * 100.0

            if abs(distance) > dma50_distance:
                return None

            stats["dma50"] += 1

        # ----------------------------------------------------
        # CONDITION 4
        # 52 Week High
        # ----------------------------------------------------

        last_252 = df.tail(252)

        if len(last_252) < 252:
            return None

        high_52w = float(
            last_252["High"].max()
        )

        if high_52w <= 0:
            return None

        below_high = max(
            0.0,
            (
                (high_52w - ltp)
                / high_52w
            ) * 100.0,
        )

        if below_high > max_below_52w_high:
            return None

        stats["52w"] += 1

        return {
            "Rank": 0,
            "Symbol": symbol,
            "Company": company,
            "LTP": round(ltp, 2),
            "50 DMA": (
                round(sma50, 2)
                if sma50 is not None
                else ""
            ),
            "% From 50 DMA": (
                round(distance, 2)
                if distance is not None
                else ""
            ),
            "52 Week High": round(
                high_52w,
                2,
            ),
            "% Below 52W High": round(
                below_high,
                2,
            ),
            "Trading Days": trading_days,
            "Sector": "—",
            "Chart": (
                "https://www.tradingview.com/chart/"
                f"?symbol=NSE%3A{symbol}"
            ),
        }

    except Exception:
        return None

# ============================================================
# SECTOR
# ============================================================

def fetch_sector(symbol: str) -> str:

    try:
        info = yf.Ticker(
            f"{symbol}.NS"
        ).get_info()

        sector = info.get("sector")

        return (
            str(sector).strip()
            if sector
            else "—"
        )

    except Exception:
        return "—"


def fetch_sectors(
    symbols: list[str],
) -> dict[str, str]:

    if not symbols:
        return {}

    sectors: dict[str, str] = {}

    with ThreadPoolExecutor(
        max_workers=8
    ) as executor:

        future_map = {
            executor.submit(
                fetch_sector,
                symbol,
            ): symbol
            for symbol in symbols
        }

        for future in as_completed(
            future_map
        ):

            symbol = future_map[future]

            try:
                sectors[symbol] = (
                    future.result()
                )
            except Exception:
                sectors[symbol] = "—"

    return sectors


# ============================================================
# STATE
# ============================================================

class ScannerState(rx.State):

    # --------------------------------------------------------
    # Scanner controls
    # --------------------------------------------------------

    scanning: bool = False
    stop_requested: bool = False

    # User controls
    use_dma50: bool = True

    # 52W High slider: 0% - 7%
    max_below_52w_high: int = (
        DEFAULT_MAX_BELOW_52W_HIGH
    )

    # 50 DMA limit
    dma50_distance: float = (
        DEFAULT_DMA50_DISTANCE
    )

    # --------------------------------------------------------
    # Progress
    # --------------------------------------------------------

    progress: int = 0
    status: str = "Ready to scan."

    processed: int = 0
    total: int = 0
    elapsed: float = 0.0

    # --------------------------------------------------------
    # Statistics
    # --------------------------------------------------------

    count_365: int = 0
    count_ltp: int = 0
    count_dma50: int = 0
    count_52w: int = 0
    count_final: int = 0

    avg_below_52w: float = 0.0

    # --------------------------------------------------------
    # Results
    # --------------------------------------------------------

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

    # ========================================================
    # STOP
    # ========================================================

    @rx.event
    def stop_scan(self):

        if self.scanning:
            self.stop_requested = True

            self.status = (
                "Stopping scan after the "
                "current download batch..."
            )

    # ========================================================
    # RUN SCAN
    # ========================================================

    @rx.event(background=True)
    async def run_scan(self):

        async with self:

            if self.scanning:
                return

            self.scanning = True
            self.stop_requested = False

            self.progress = 0

            self.status = (
                "Loading NSE equity universe..."
            )

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

# Capture user settings for this scan.
            async with self:
                use_dma50 = self.use_dma50
                max_below_52w_high = (
                    self.max_below_52w_high
                )
                dma50_distance = (
                    self.dma50_distance
                )

            # ------------------------------------------------
            # NSE universe
            # ------------------------------------------------

            universe = await asyncio.to_thread(
                get_nse_universe
            )

            symbols = universe[
                "SYMBOL"
            ].tolist()

            company_map = dict(
                zip(
                    universe["SYMBOL"],
                    universe["Company"],
                )
            )

            async with self:

                self.total = len(symbols)

                self.status = (
                    f"Found {len(symbols):,} "
                    "NSE EQ stocks."
                )

            # ------------------------------------------------
            # Statistics
            # ------------------------------------------------

            stats = {
                "365_days": 0,
                "ltp": 0,
                "dma50": 0,
                "52w": 0,
            }

            results: list[dict] = []

            # ------------------------------------------------
            # Batches
            # ------------------------------------------------

            batches = [
                symbols[i:i + BATCH_SIZE]
                for i in range(
                    0,
                    len(symbols),
                    BATCH_SIZE,
                )
            ]

            total_batches = len(batches)
            completed_batches = 0

            # ------------------------------------------------
            # Concurrent download waves
            # ------------------------------------------------

            for wave_start in range(
                0,
                total_batches,
                DOWNLOAD_WORKERS,
            ):

                async with self:

                    if self.stop_requested:
                        break

                wave = batches[
                    wave_start:
                    wave_start + DOWNLOAD_WORKERS
                ]

                tasks = [
                    asyncio.create_task(
                        asyncio.to_thread(
                            download_batch,
                            batch,
                        )
                    )
                    for batch in wave
                ]

                wave_data = await asyncio.gather(
                    *tasks,
                    return_exceptions=True,
                )

                for batch, data in zip(
                    wave,
                    wave_data,
                ):

                    if isinstance(
                        data,
                        Exception,
                    ):
                        data = None

                    if (
                        data is not None
                        and not data.empty
                    ):

                        for symbol in batch:

                            result = process_stock(
                                symbol,
                                company_map.get(
                                    symbol,
                                    symbol,
                                ),
                                data,
                                stats,
                                use_dma50,
                                dma50_distance,
                                max_below_52w_high,
                            )

                            if result is not None:
                                results.append(
                                    result
                                )

                    completed_batches += 1

processed = min(
                        completed_batches
                        * BATCH_SIZE,
                        len(symbols),
                    )

                    progress_pct = (
                        processed
                        / len(symbols)
                        * 100.0
                        if symbols
                        else 100.0
                    )

                    progress_value = int(
                        round(progress_pct)
                    )

                    async with self:

                        self.processed = processed
                        self.progress = (
                            progress_value
                        )

                        self.count_365 = (
                            stats["365_days"]
                        )

                        self.count_ltp = (
                            stats["ltp"]
                        )

                        self.count_dma50 = (
                            stats["dma50"]
                        )

                        self.count_52w = (
                            stats["52w"]
                        )

                        if not self.stop_requested:

                            self.status = (
                                f"Scanning batch "
                                f"{completed_batches}/"
                                f"{total_batches} "
                                f"— {processed:,}/"
                                f"{len(symbols):,}"
                            )

                async with self:

                    if self.stop_requested:
                        break

            # ------------------------------------------------
            # Was scan stopped?
            # ------------------------------------------------

            async with self:
                stopped = self.stop_requested

            # ------------------------------------------------
            # Sort
            # ------------------------------------------------

            results.sort(
                key=lambda x:
                x["% Below 52W High"]
            )

            # ------------------------------------------------
            # Rank
            # ------------------------------------------------

            for index, result in enumerate(
                results,
                start=1,
            ):
                result["Rank"] = index

            # ------------------------------------------------
            # Sector lookup
            # Only when scan finishes normally.
            # ------------------------------------------------

            if results and not stopped:

                async with self:

                    self.status = (
                        f"Scan complete. "
                        f"Loading sectors for "
                        f"{len(results):,} matches..."
                    )

                sector_map = (
                    await asyncio.to_thread(
                        fetch_sectors,
                        [
                            result["Symbol"]
                            for result in results
                        ],
                    )
                )

                for result in results:

                    result["Sector"] = (
                        sector_map.get(
                            result["Symbol"],
                            "—",
                        )
                    )

            # ------------------------------------------------
            # Average distance from 52W high
            # ------------------------------------------------

            avg_below = (
                sum(
                    float(
                        result[
                            "% Below 52W High"
                        ]
                    )
                    for result in results
                )
                / len(results)
                if results
                else 0.0
            )

# ------------------------------------------------
            # CSV
            # ------------------------------------------------

            df = pd.DataFrame(
                results,
                columns=self.columns,
            )

            csv_text = (
                df.to_csv(index=False)
                if not df.empty
                else ""
            )

            # ------------------------------------------------
            # UI rows
            #
            # Trading Days stays in CSV but is NOT displayed.
            # ------------------------------------------------

            rows = []

            for result in results:

                rows.append(
                    [
                        str(result["Rank"]),
                        result["Symbol"],
                        result["Company"],
                        f"{result['LTP']:,.2f}",
                        (
                            f"{result['50 DMA']:,.2f}"
                            if result["50 DMA"] != ""
                            else "—"
                        ),
                        (
                            f"{result['% From 50 DMA']:.2f}"
                            if result[
                                "% From 50 DMA"
                            ] != ""
                            else "—"
                        ),
                        f"{result['52 Week High']:,.2f}",
                        (
                            f"{result['% Below 52W High']:.2f}"
                        ),
                        # Trading Days remains here
                        # for internal/CSV data.
                        str(result["Trading Days"]),
                        result["Sector"],
                        result["Chart"],
                    ]
                )

            # ------------------------------------------------
            # Finish
            # ------------------------------------------------

            elapsed = round(
                time.time()
                - start_time,
                1,
            )

            async with self:

                self.rows = rows

                self.csv_data = csv_text

                self.elapsed = elapsed

                self.count_final = len(
                    results
                )

                self.avg_below_52w = round(
                    avg_below,
                    2,
                )

                if stopped:

                    self.status = (
                        f"Scan stopped: "
                        f"{len(results)} matches "
                        f"collected in "
                        f"{elapsed:.1f} seconds."
                    )

                else:

                    self.progress = 100

                    self.status = (
                        f"Scan completed: "
                        f"{len(results)} matches "
                        f"in {elapsed:.1f} seconds."
                    )

        except Exception as exc:

            async with self:

                self.status = (
                    f"Scan failed: {exc}"
                )

                self.elapsed = round(
                    time.time()
                    - start_time,
                    1,
                )

        finally:

            async with self:

                self.scanning = False
                self.stop_requested = False

    # ========================================================
    # CSV DOWNLOAD
    # ========================================================

    @rx.event
    def download_csv(self):

        if not self.csv_data:

            return rx.window_alert(
                "Run the scanner first."
            )

        filename = (
            "PIPSGO_NSE_Scanner_"
            + datetime.now().strftime(
                "%Y%m%d_%H%M"
            )
            + ".csv"
        )

        return rx.download(
            data=self.csv_data,
            filename=filename,
        )
