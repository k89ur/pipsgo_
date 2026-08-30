import asyncio
import io
import time
from datetime import datetime

import pandas as pd
import requests
import reflex as rx
import yfinance as yf


# ============================================================
# NSE STOCK SCANNER - REFLEX VERSION
# ============================================================

MIN_LTP = 100.0
DMA50_DISTANCE = 15.0
MAX_BELOW_52W_HIGH = 5.0
MIN_TRADING_DAYS = 365
BATCH_SIZE = 50
BATCH_DELAY = 0.35


NSE_URL = "https://archives.nseindia.com/content/equities/EQUITY_L.csv"
NSE_HOME = "https://www.nseindia.com/"


def get_nse_symbols() -> list[str]:
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

    return sorted(
        df["SYMBOL"]
        .astype(str)
        .str.strip()
        .dropna()
        .unique()
        .tolist()
    )


def download_batch(batch: list[str]):
    tickers = [f"{symbol}.NS" for symbol in batch]
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


def process_stock(symbol: str, data, stats: dict):
    ticker = f"{symbol}.NS"

    try:
        if data is None or data.empty:
            return None

        if not isinstance(data.columns, pd.MultiIndex):
            return None

        level0 = data.columns.get_level_values(0)
        if ticker not in level0:
            return None

        df = data[ticker].copy()
        if df.empty:
            return None

        required = ["Close", "High"]
        df = df.dropna(subset=required)
        if df.empty:
            return None

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
            .rolling(window=50, min_periods=50)
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
        below_high = ((high_52w - ltp) / high_52w) * 100.0
        below_high = max(0.0, below_high)

        if below_high > MAX_BELOW_52W_HIGH:
            return None
        stats["52w"] += 1

        return {
            "Rank": 0,
            "Symbol": symbol,
            "LTP": round(ltp, 2),
            "50 DMA": round(sma50, 2),
            "% From 50 DMA": round(distance, 2),
            "52 Week High": round(high_52w, 2),
            "% Below 52W High": round(below_high, 2),
            "Trading Days": trading_days,
            "TradingView Chart": (
                "https://www.tradingview.com/chart/"
                f"?symbol=NSE%3A{symbol}"
            ),
        }

    except Exception:
        return None


class ScannerState(rx.State):
    scanning: bool = False
    progress: float = 0.0
    status: str = "Ready to scan."
    processed: int = 0
    total: int = 0
    elapsed: float = 0.0

    count_365: int = 0
    count_ltp: int = 0
    count_dma50: int = 0
    count_final: int = 0

    rows: list[list] = []
    csv_data: str = ""

    columns: list[str] = [
        "Rank",
        "Symbol",
        "LTP",
        "50 DMA",
        "% From 50 DMA",
        "52 Week High",
        "% Below 52W High",
        "Trading Days",
        "TradingView Chart",
    ]

    @rx.event(background=True)
    async def run_scan(self):
        async with self:
            if self.scanning:
                return

            self.scanning = True
            self.progress = 0.0
            self.status = "Loading NSE equity universe..."
            self.processed = 0
            self.total = 0
            self.elapsed = 0.0
            self.count_365 = 0
            self.count_ltp = 0
            self.count_dma50 = 0
            self.count_final = 0
            self.rows = []
            self.csv_data = ""

        start_time = time.time()

        try:
            symbols = await asyncio.to_thread(get_nse_symbols)

            async with self:
                self.total = len(symbols)
                self.status = f"Found {len(symbols):,} NSE EQ stocks."

            stats = {
                "365_days": 0,
                "ltp": 0,
                "dma50": 0,
                "52w": 0,
            }

            results = []
            total_batches = (len(symbols) + BATCH_SIZE - 1) // BATCH_SIZE

            for batch_number, start in enumerate(
                range(0, len(symbols), BATCH_SIZE), start=1
            ):
                batch = symbols[start:start + BATCH_SIZE]
                data = await asyncio.to_thread(download_batch, batch)

                if data is not None and not data.empty:
                    for symbol in batch:
                        result = process_stock(symbol, data, stats)
                        if result is not None:
                            results.append(result)

                processed = min(start + BATCH_SIZE, len(symbols))
                progress = processed / len(symbols) if symbols else 1.0

                async with self:
                    self.processed = processed
                    self.progress = progress
                    self.count_365 = stats["365_days"]
                    self.count_ltp = stats["ltp"]
                    self.count_dma50 = stats["dma50"]
                    self.count_final = stats["52w"]
                    self.status = (
                        f"Scanning batch {batch_number}/{total_batches} "
                        f"— {processed:,}/{len(symbols):,}"
                    )

                await asyncio.sleep(BATCH_DELAY)

            results.sort(key=lambda x: x["% Below 52W High"])
            for index, result in enumerate(results, start=1):
                result["Rank"] = index

            df = pd.DataFrame(results, columns=self.columns)
            csv_text = df.to_csv(index=False) if not df.empty else ""

            rows = [
                [row.get(column, "") for column in self.columns]
                for row in results
            ]

            elapsed = round(time.time() - start_time, 1)

            async with self:
                self.rows = rows
                self.csv_data = csv_text
                self.elapsed = elapsed
                self.progress = 1.0
                self.count_final = len(results)
                self.status = (
                    f"Scan completed: {len(results)} matches "
                    f"in {elapsed:.1f} seconds."
                )

        except Exception as exc:
            async with self:
                self.status = f"Scan failed: {exc}"
                self.elapsed = round(time.time() - start_time, 1)

        finally:
            async with self:
                self.scanning = False

    @rx.event
    def download_csv(self):
        if not self.csv_data:
            return rx.window_alert("Run the scanner first.")
        filename = (
            "NSE_Stock_Scanner_"
            + datetime.now().strftime("%Y%m%d_%H%M")
            + ".csv"
        )
        return rx.download(
            data=self.csv_data,
            filename=filename,
        )


def condition_box(text: str) -> rx.Component:
    return rx.box(
        rx.text(text, size="3"),
        padding="12px",
        border_radius="10px",
        background="var(--gray-a3)",
        width="100%",
    )


def metric_card(label: str, value) -> rx.Component:
    return rx.card(
        rx.vstack(
            rx.text(label, size="2", color="gray"),
            rx.heading(value, size="5"),
            spacing="1",
            align="start",
        ),
        width="100%",
    )


def results_section() -> rx.Component:
    return rx.vstack(
        rx.cond(
            ScannerState.scanning,
            rx.progress(
                value=ScannerState.progress * 100,
                width="100%",
            ),
            rx.fragment(),
        ),
        rx.text(ScannerState.status, size="2", color="gray"),
        rx.grid(
            metric_card("NSE Stocks", ScannerState.total),
            metric_card("365+ Days", ScannerState.count_365),
            metric_card("LTP > ₹100", ScannerState.count_ltp),
            metric_card("Within 50 DMA", ScannerState.count_dma50),
            metric_card("Final Matches", ScannerState.count_final),
            columns=rx.breakpoints(initial="2", sm="3", md="5"),
            spacing="3",
            width="100%",
        ),
        rx.cond(
            ScannerState.csv_data != "",
            rx.button(
                "⬇️ Download CSV",
                on_click=ScannerState.download_csv,
                width="100%",
            ),
            rx.fragment(),
        ),
        rx.cond(
            ScannerState.rows.length() > 0,
            rx.data_table(
                data=ScannerState.rows,
                columns=ScannerState.columns,
                search=True,
                sort=True,
                pagination={"pageSize": 20},
                resizable=True,
                width="100%",
            ),
            rx.callout(
                "Run the scanner to see matching stocks.",
                icon="info",
                width="100%",
            ),
        ),
        width="100%",
        spacing="4",
    )


def index() -> rx.Component:
    return rx.container(
        rx.vstack(
            rx.heading("📈 NSE Stock Scanner", size="8"),
            rx.text(
                "50-DMA + 52-Week High scanner",
                color="gray",
                size="4",
            ),

            rx.accordion.root(
                rx.accordion.item(
                    header="📋 Scan Conditions",
                    content=rx.vstack(
                        condition_box("✅ NSE Equity stocks"),
                        condition_box(
                            f"✅ Minimum {MIN_TRADING_DAYS} trading days"
                        ),
                        condition_box(f"✅ LTP > ₹{MIN_LTP:,.0f}"),
                        condition_box(
                            f"✅ LTP within ±{DMA50_DISTANCE}% of 50-DMA"
                        ),
                        condition_box(
                            f"✅ Maximum {MAX_BELOW_52W_HIGH}% below 52-week high"
                        ),
                        spacing="2",
                        width="100%",
                    ),
                ),
                collapsible=True,
                width="100%",
            ),

            rx.button(
                rx.cond(
                    ScannerState.scanning,
                    "🔄 SCANNING...",
                    "🔎 RUN SCAN",
                ),
                on_click=ScannerState.run_scan,
                disabled=ScannerState.scanning,
                size="4",
                width="100%",
            ),

            results_section(),

            rx.text(
                "Data source: NSE equity list + Yahoo Finance historical data. "
                "TradingView links open NSE charts.",
                size="1",
                color="gray",
            ),

            width="100%",
            spacing="5",
            align="stretch",
        ),
        size="4",
        padding_y="32px",
    )


app = rx.App(
    theme=rx.theme(
        appearance="dark",
        radius="large",
        accent_color="blue",
    )
)
app.add_page(index)
