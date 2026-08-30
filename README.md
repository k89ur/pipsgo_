# NSE Stock Scanner - Reflex

This is the Reflex conversion of the original Streamlit NSE scanner.

## Files

- `nse_scan/nse_scan.py` - Reflex application
- `rxconfig.py` - Reflex configuration
- `requirements.txt` - Python dependencies

## Run

```bash
python3 -m pip install -r requirements.txt
python3 -m reflex run
```

The app will normally be available on port 3000.

## Important

Do not keep the old Streamlit `st.*` code in the Reflex app file. This version uses Reflex state/events/components instead.

The scanner preserves the original filters:

- NSE EQ stocks
- At least 365 trading days
- LTP > ₹100
- LTP within ±15% of 50-DMA
- At most 5% below the 52-week high
- Batch Yahoo Finance downloads
- Progress
- Scan statistics
- TradingView URLs
- CSV download
