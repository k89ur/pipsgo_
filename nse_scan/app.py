File Sync ☁️:
import reflex as rx

from scanner import ScannerState


# ============================================================
# PIPSGO / SCANFLOW UI
# ============================================================

BG = "#F4F7F5"
SURFACE = "#FFFFFF"
TEXT = "#17202A"
MUTED = "#6B7280"
BORDER = "#DFE6E2"

ACCENT = "#18A873"
ACCENT_DARK = "#11875D"

DANGER = "#D64545"
DANGER_DARK = "#B93636"


# ============================================================
# COMMON COMPONENTS
# ============================================================

def panel(
    *children,
    props,
) -> rx.Component:

    return rx.box(
        *children,

        background=SURFACE,

        border=f"1px solid {BORDER}",

        border_radius="14px",

        padding="18px",

        props,
    )


def stat_card(
    label: str,
    value,
) -> rx.Component:

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


# ============================================================
# FILTER BADGES
# ============================================================

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


# ============================================================
# SIDEBAR
# ============================================================

def sidebar() -> rx.Component:

    return rx.box(

        rx.vstack(

            rx.hstack(

                rx.text(
                    "PIPSGO",
                    size="6",
                    weight="bold",
                    color=TEXT,
                ),

                rx.spacer(),

                rx.badge(
                    "LIVE",
                    color_scheme="green",
                    variant="soft",
                ),

                width="100%",
            ),

            rx.text(
                "SCANNERS LIBRARY",
                size="1",
                weight="bold",
                color=MUTED,
            ),

            # ------------------------------------------------
            # Current scanner
            # ------------------------------------------------

            rx.box(

                rx.vstack(

                    rx.hstack(

                        rx.text(
                            "52W High Scanner",
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
                        "Configurable 52W High + optional 50 DMA",
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

# ------------------------------------------------
            # Future scanner placeholders
            # ------------------------------------------------

            rx.box(

                rx.vstack(

                    rx.hstack(

                        rx.text(
                            "Scanner Library",
                            size="2",
                            weight="bold",
                            color=TEXT,
                        ),

                        rx.spacer(),

                        rx.text(
                            "+",
                            size="4",
                            weight="bold",
                            color=MUTED,
                        ),

                        width="100%",
                    ),

                    rx.text(
                        "More scanners can be added here.",
                        size="1",
                        color=MUTED,
                    ),

                    align="start",
                    width="100%",
                ),

                border=f"1px solid {BORDER}",

                border_radius="10px",

                padding="14px",

                width="100%",
            ),

            rx.spacer(),

            rx.text(
                "PIPSGO NSE Scanner",
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


# ============================================================
# SCANNER CONTROLS
# ============================================================

def scanner_controls() -> rx.Component:

    return rx.vstack(

        rx.text(
            "SCAN CONTROLS",
            size="1",
            weight="bold",
            color=MUTED,
        ),

        # ----------------------------------------------------
        # 52W HIGH SLIDER
        # ----------------------------------------------------

        rx.box(

            rx.vstack(

                rx.hstack(

                    rx.text(
                        "Maximum distance below 52W High",
                        size="2",
                        weight="bold",
                        color=TEXT,
                    ),

                    rx.spacer(),

                    rx.badge(
                        ScannerState.max_below_52w_high.to_string()
                        + "%",
                        color_scheme="green",
                        variant="soft",
                        size="2",
                    ),

                    width="100%",
                ),

                rx.slider(
                    min=0,
                    max=7,
                    step=1,

                    value=ScannerState.max_below_52w_high,

                    on_change=(
                        ScannerState
                        .set_max_below_52w_high
                    ),

                    width="100%",

                    color_scheme="green",
                ),

                rx.hstack(

                    rx.text(
                        "0%",
                        size="1",
                        color=MUTED,
                    ),

                    rx.spacer(),

                    rx.text(
                        "7%",
                        size="1",
                        color=MUTED,
                    ),

                    width="100%",
                ),

                width="100%",
                spacing="2",
            ),

            padding="12px",

            border=f"1px solid {BORDER}",

            border_radius="10px",

            background=BG,

            width="100%",
        ),

        # ----------------------------------------------------
        # 50 DMA CHECKBOX
        # ----------------------------------------------------

        rx.box(

            rx.hstack(

rx.checkbox(
                    checked=ScannerState.use_dma50,
                    on_change=(
                        ScannerState
                        .set_use_dma50
                    ),
                    color_scheme="green",
                ),

                rx.vstack(

                    rx.text(
                        "Use 50 DMA filter",
                        size="2",
                        weight="bold",
                        color=TEXT,
                    ),

                    rx.text(
                        "LTP must be within ±15% of 50 DMA",
                        size="1",
                        color=MUTED,
                    ),

                    align="start",
                    spacing="1",
                ),

                width="100%",
            ),

            padding="12px",

            border=f"1px solid {BORDER}",

            border_radius="10px",

            background=BG,

            width="100%",
        ),

        width="100%",
        spacing="2",
        align="start",
    )


# ============================================================
# SCANNER HEADER
# ============================================================

def scanner_header() -> rx.Component:

    return panel(

        rx.hstack(

            rx.vstack(

                rx.heading(
                    "52W HIGH SCANNER",
                    size="6",
                    color=TEXT,
                ),

                rx.text(
                    "Scans NSE equities using configurable "
                    "52-week high conditions and optional 50-DMA.",
                    size="2",
                    color=MUTED,
                    max_width="650px",
                ),

                align="start",
                spacing="1",
            ),

            rx.spacer(),

            # ------------------------------------------------
            # RUN / STOP
            # ------------------------------------------------

            rx.cond(

                ScannerState.scanning,

                rx.button(

                    "■  STOP SCAN",

                    on_click=(
                        ScannerState.stop_scan
                    ),

                    background=DANGER,

                    color="white",

                    size="3",

                    _hover={
                        "background": DANGER_DARK
                    },
                ),

                rx.button(

                    "▶  RUN SCAN",

                    on_click=(
                        ScannerState.run_scan
                    ),

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

        # ----------------------------------------------------
        # CONTROLS
        # ----------------------------------------------------

        scanner_controls(),

        rx.divider(
            margin_y="14px"
        ),

        # ----------------------------------------------------
        # ACTIVE FILTERS
        # ----------------------------------------------------

        rx.vstack(

            rx.text(
                "ACTIVE FILTERS",
                size="1",
                weight="bold",
                color=MUTED,
            ),

            rx.hstack(

                filter_badge(
                    "LTP > ₹100",
                    "blue",
                ),

                filter_badge(
                    "≥365 Trading Days",
                    "orange",
                ),

                rx.cond(

                    ScannerState.use_dma50,

                    filter_badge(
                        "50 DMA ±15%",
                        "purple",
                    ),

filter_badge(
                        "50 DMA OFF",
                        "gray",
                    ),
                ),

                filter_badge(
                    "52W High ≤ "
                    + ScannerState
                    .max_below_52w_high
                    .to_string()
                    + "%",
                    "green",
                ),

                wrap="wrap",
                width="100%",
            ),

            align="start",
            spacing="2",
        ),

        width="100%",
    )


# ============================================================
# TABLE ROW
# ============================================================

def table_row(
    row: list[str],
) -> rx.Component:

    return rx.table.row(

        # ----------------------------------------------------
        # Rank
        # ----------------------------------------------------

        rx.table.cell(

            rx.text(
                row[0],
                size="1",
                color=MUTED,
            )
        ),

        # ----------------------------------------------------
        # Symbol
        # ----------------------------------------------------

        rx.table.cell(

            rx.text(
                row[1],
                weight="bold",
                size="2",
                color=TEXT,
            )
        ),

        # ----------------------------------------------------
        # Company
        # ----------------------------------------------------

        rx.table.cell(

            rx.text(
                row[2],
                size="1",
                color=TEXT,

                max_width="140px",

                overflow="hidden",

                text_overflow="ellipsis",

                white_space="nowrap",
            )
        ),

        # ----------------------------------------------------
        # LTP
        # ----------------------------------------------------

        rx.table.cell(

            rx.text(
                f"₹{row[3]}",
                size="1",
                color=TEXT,
            )
        ),

        # ----------------------------------------------------
        # 50 DMA
        # ----------------------------------------------------

        rx.table.cell(

            rx.text(
                (
                    f"₹{row[4]}"
                    if row[4] != "—"
                    else "—"
                ),
                size="1",
                color=TEXT,
            )
        ),

        # ----------------------------------------------------
        # % 50 DMA
        # ----------------------------------------------------

        rx.table.cell(

            rx.text(
                (
                    f"{row[5]}%"
                    if row[5] != "—"
                    else "—"
                ),
                size="1",
                color=TEXT,
            )
        ),

        # ----------------------------------------------------
        # 52W HIGH
        # ----------------------------------------------------

        rx.table.cell(

            rx.text(
                f"₹{row[6]}",
                size="1",
                color=TEXT,
            )
        ),

        # ----------------------------------------------------
        # % BELOW 52W HIGH
        # ----------------------------------------------------

        rx.table.cell(

            rx.badge(

                f"{row[7]}%",

                color_scheme="green",

                variant="soft",

                size="1",
            )
        ),

        # ----------------------------------------------------
        # SECTOR
        # ----------------------------------------------------

        rx.table.cell(

            rx.text(
                row[9],

                size="1",

                color=MUTED,

                max_width="110px",

                overflow="hidden",

                text_overflow="ellipsis",

                white_space="nowrap",
            )
        ),

# ----------------------------------------------------
        # CHART
        # ----------------------------------------------------

        rx.table.cell(

            rx.link(

                "Open ↗",

                href=row[10],

                is_external=True,

                color=ACCENT_DARK,

                weight="bold",

                underline="none",

                size="1",
            )
        ),

        white_space="nowrap",
    )


# ============================================================
# RESULTS TABLE
# ============================================================

def results_table() -> rx.Component:

    return rx.box(

        rx.table.root(

            rx.table.header(

                rx.table.row(

                    rx.table.column_header_cell(
                        "#"
                    ),

                    rx.table.column_header_cell(
                        "SYMBOL"
                    ),

                    rx.table.column_header_cell(
                        "COMPANY"
                    ),

                    rx.table.column_header_cell(
                        "LTP"
                    ),

                    rx.table.column_header_cell(
                        "50 DMA"
                    ),

                    rx.table.column_header_cell(
                        "% 50 DMA"
                    ),

                    rx.table.column_header_cell(
                        "52W HIGH"
                    ),

                    rx.table.column_header_cell(
                        "% BELOW"
                    ),

                    rx.table.column_header_cell(
                        "SECTOR"
                    ),

                    rx.table.column_header_cell(
                        "CHART"
                    ),
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


# ============================================================
# RESULTS PANEL
# ============================================================

def results_panel() -> rx.Component:

    return panel(

        # ----------------------------------------------------
        # TABLE HEADER
        # Export CSV stays top-right.
        # ----------------------------------------------------

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

                    on_click=(
                        ScannerState
                        .download_csv
                    ),

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

        # ----------------------------------------------------
        # STATUS
        # ----------------------------------------------------

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

                    ScannerState
                    .count_final
                    .to_string()
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

        # ----------------------------------------------------
        # PROGRESS
        # ----------------------------------------------------

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

                        ScannerState
                        .processed
                        .to_string()

                        + " / "

                        + ScannerState
                        .total
                        .to_string()

                        + " stocks",

                        size="1",

                        color=MUTED,
                    ),

                    rx.spacer(),

                    rx.text(

                        ScannerState
                        .progress
                        .to_string()

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

        # ----------------------------------------------------
        # RESULTS
        # ----------------------------------------------------

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


# ============================================================
# RIGHT PANEL
# ============================================================

def right_panel() -> rx.Component:

    return rx.vstack(

        # ----------------------------------------------------
        # COMPLETION
        # ----------------------------------------------------

        panel(

            rx.vstack(

                rx.text(
                    "SCAN COMPLETION",
                    size="2",
                    weight="bold",
                    color=TEXT,
                ),

                rx.cond(

                    ScannerState.scanning,

                    rx.text(
                        "● SCANNING...",
                        size="1",
                        weight="bold",
                        color=ACCENT,
                    ),

                    rx.text(
                        "● READY",
                        size="1",
                        weight="bold",
                        color=MUTED,
                    ),
                ),

                rx.progress(

                    value=ScannerState.progress,

                    width="100%",

                    color_scheme="green",
                ),

                rx.heading(

                    ScannerState
                    .progress
                    .to_string()
                    + "%",

                    size="7",

                    color=TEXT,
                ),

                rx.text(

                    ScannerState
                    .processed
                    .to_string()

                    + " / "

                    + ScannerState
                    .total
                    .to_string()

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

# ----------------------------------------------------
        # SESSION STATISTICS
        # ----------------------------------------------------

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

        rx.cond(

            ScannerState.use_dma50,

            stat_card(
                "WITHIN 50 DMA",
                ScannerState.count_dma50,
            ),

            stat_card(
                "50 DMA",
                "OFF",
            ),
        ),

        stat_card(
            "≤ "
            + ScannerState
            .max_below_52w_high
            .to_string()
            + "% BELOW 52W HIGH",
            ScannerState.count_52w,
        ),

        stat_card(
            "AVG. BELOW 52W HIGH",

            ScannerState
            .avg_below_52w
            .to_string()

            + "%",
        ),

        stat_card(
            "SCAN DURATION",

            ScannerState
            .elapsed
            .to_string()

            + " sec",
        ),

        width="100%",

        spacing="3",
    )


# ============================================================
# MAIN PAGE
# ============================================================

def index() -> rx.Component:

    return rx.box(

        rx.hstack(

            # ------------------------------------------------
            # LEFT SIDEBAR
            # ------------------------------------------------

            sidebar(),

            # ------------------------------------------------
            # CENTER
            # ------------------------------------------------

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

            # ------------------------------------------------
            # RIGHT SIDEBAR
            # ------------------------------------------------

            rx.box(

                right_panel(),

                width="270px",

                min_width="270px",

                padding="24px 18px",

                border_left=(
                    f"1px solid {BORDER}"
                ),

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


# ============================================================
# APP
# ============================================================

app = rx.App(

    theme=rx.theme(

        appearance="light",

        radius="medium",

        accent_color="green",
    )
)

app.add_page(index)
