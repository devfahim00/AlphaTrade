# AlphaTrade

Signal "brain" (Python) + browser extension for **demo** trading tests.

- `brain/` – FastAPI server: builds candles from ticks, backtests 3 strategies (S/R price action,
  trend pullback, RSI+Stoch reversal), picks one on train data, verifies on out-of-sample data,
  emits CALL / PUT / WAIT and journals live demo results to `journal.csv`.
- `extension/` – Chrome (MV3) extension: reads price ticks from the page WebSocket, sends them to the
  brain on `127.0.0.1:8765`, shows the signal overlay.

## Use (from the pre-release)
1. Run `AlphaTradeBrain.exe`.
2. Unzip `AlphaTrade-extension.zip` → `chrome://extensions` → Developer mode → *Load unpacked*.
3. Open the demo page. After warm-up (~150 candles) the overlay shows the signal.

## Run from source
```
cd brain && pip install -r requirements.txt && python main.py
```
Config (env): `QX_TF`, `QX_EXPIRY_BARS`, `QX_PAYOUT`, `QX_WINDOW`, `QX_MIN_CANDLES`.

## Notes
- The tick parser in `extension/inject.js` (`walk()`) is a guess at the frame layout; check the
  `[qx-brain] frame:` console logs and adjust if no ticks arrive.
- Signal only; no auto-trading. Backtested win rate is not a guarantee. Demo only.
