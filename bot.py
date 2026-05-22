import os
import time
import math
import requests
import pandas as pd
from datetime import datetime
from flask import Flask
from threading import Thread

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

CMC_API_KEY = os.getenv("CMC_API_KEY", "")
USE_CMC_FILTER = os.getenv("USE_CMC_FILTER", "true").lower() == "true"
CMC_TOP_N = int(os.getenv("CMC_TOP_N", "1000"))
MIN_MARKET_CAP = float(os.getenv("MIN_MARKET_CAP", "0"))
MAX_MARKET_CAP = float(os.getenv("MAX_MARKET_CAP", "1000000000"))

CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", "900"))
TIMEFRAME = os.getenv("TIMEFRAME", "15m")
MAX_COINS = int(os.getenv("MAX_COINS", "300"))

MAX_RSI_BUY = float(os.getenv("MAX_RSI_BUY", "30"))
MIN_VOLUME_RATIO = float(os.getenv("MIN_VOLUME_RATIO", "1.1"))
MIN_VOLUME_USDT = float(os.getenv("MIN_VOLUME_USDT", "50000"))
MIN_CURRENT_CANDLE_VOLUME = float(os.getenv("MIN_CURRENT_CANDLE_VOLUME", "8000"))
VOLUME_LOOKBACK = int(os.getenv("VOLUME_LOOKBACK", "20"))
MAX_24H_CHANGE = float(os.getenv("MAX_24H_CHANGE", "25"))

RSI_PERIOD = int(os.getenv("RSI_PERIOD", "14"))
STOCH_PERIOD = int(os.getenv("STOCH_PERIOD", "14"))
K_SMOOTH = int(os.getenv("K_SMOOTH", "3"))
D_SMOOTH = int(os.getenv("D_SMOOTH", "3"))

SIGNAL_COOLDOWN_HOURS = int(os.getenv("SIGNAL_COOLDOWN_HOURS", "6"))

ENABLE_GATE = os.getenv("ENABLE_GATE", "true").lower() == "true"
ENABLE_MEXC = os.getenv("ENABLE_MEXC", "true").lower() == "true"
ENABLE_KUCOIN = os.getenv("ENABLE_KUCOIN", "true").lower() == "true"
ENABLE_OKX = os.getenv("ENABLE_OKX", "true").lower() == "true"
ENABLE_BYBIT = os.getenv("ENABLE_BYBIT", "true").lower() == "true"
ENABLE_BITGET = os.getenv("ENABLE_BITGET", "true").lower() == "true"

app = Flask(__name__)

@app.route("/")
def home():
    return "Early Reversal Bot with CMC Filter is running ✅"

EXCLUDED_KEYWORDS = [
    "3L", "3S", "5L", "5S", "BULL", "BEAR",
    "UP", "DOWN", "LONG", "SHORT",
    "USDC", "BUSD", "DAI", "TUSD", "FDUSD", "USDP",
    "PEPE", "DOGE", "SHIB", "FLOKI", "BONK", "WIF",
    "MEME", "CAT", "DOG", "PUMP",
    "GAME", "GAMING", "CASINO", "BET", "PREDICT", "POLYMARKET",
    "BABAON", "NVDAX", "TSLA3S", "TSLA3L", "SBUXON"
]

sent_signals = {}
cmc_allowed_symbols = {}
last_cmc_update = 0

def send_telegram(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print(message)
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }

    try:
        requests.post(url, json=payload, timeout=20)
    except Exception as e:
        print("Telegram Error:", e)

def safe_float(x, default=0):
    try:
        return float(x)
    except Exception:
        return default

def base_symbol(symbol):
    s = symbol.upper()
    s = s.replace("_USDT", "")
    s = s.replace("-USDT", "")
    s = s.replace("USDT", "")
    return s

def normalize_symbol(symbol):
    return symbol.replace("_", "/").replace("-", "/")

def is_excluded(symbol):
    s = base_symbol(symbol)
    return any(x in s for x in EXCLUDED_KEYWORDS)

def cooldown_ok(key):
    now = time.time()
    last = sent_signals.get(key)
    if not last:
        return True
    return now - last >= SIGNAL_COOLDOWN_HOURS * 3600

def convert_timeframe(exchange):
    tf = TIMEFRAME

    mapping = {
        "Gate": tf,
        "MEXC": tf,
        "KuCoin": {
            "1m": "1min",
            "5m": "5min",
            "15m": "15min",
            "30m": "30min",
            "1h": "1hour",
            "4h": "4hour",
            "1d": "1day"
        }.get(tf, "15min"),
        "OKX": {
            "1m": "1m",
            "5m": "5m",
            "15m": "15m",
            "30m": "30m",
            "1h": "1H",
            "4h": "4H",
            "1d": "1D"
        }.get(tf, "15m"),
        "Bybit": {
            "1m": "1",
            "5m": "5",
            "15m": "15",
            "30m": "30",
            "1h": "60",
            "4h": "240",
            "1d": "D"
        }.get(tf, "15"),
        "Bitget": {
            "1m": "1min",
            "5m": "5min",
            "15m": "15min",
            "30m": "30min",
            "1h": "1h",
            "4h": "4h",
            "1d": "1day"
        }.get(tf, "15min")
    }

    return mapping.get(exchange, tf)

def update_cmc_filter():
    global cmc_allowed_symbols, last_cmc_update

    if not USE_CMC_FILTER:
        cmc_allowed_symbols = {}
        return

    if not CMC_API_KEY:
        print("CMC_API_KEY missing. CMC filter disabled temporarily.")
        cmc_allowed_symbols = {}
        return

    now = time.time()

    if now - last_cmc_update < 3600 and cmc_allowed_symbols:
        return

    print("Updating CoinMarketCap filter...")

    url = "https://pro-api.coinmarketcap.com/v1/cryptocurrency/listings/latest"
    headers = {"X-CMC_PRO_API_KEY": CMC_API_KEY}
    params = {
        "start": "1",
        "limit": str(CMC_TOP_N),
        "convert": "USD",
        "sort": "market_cap",
        "sort_dir": "desc"
    }

    try:
        data = requests.get(url, headers=headers, params=params, timeout=30).json()

        if "data" not in data:
            print("CMC error:", data)
            return

        allowed = {}

        for coin in data["data"]:
            symbol = str(coin.get("symbol", "")).upper()
            name = str(coin.get("name", "")).upper()
            quote = coin.get("quote", {}).get("USD", {})

            market_cap = safe_float(quote.get("market_cap"))
            volume_24h = safe_float(quote.get("volume_24h"))
            change_24h = safe_float(quote.get("percent_change_24h"))

            if not symbol:
                continue

            if market_cap < MIN_MARKET_CAP:
                continue

            if market_cap > MAX_MARKET_CAP:
                continue

            if volume_24h < MIN_VOLUME_USDT:
                continue

            if abs(change_24h) > MAX_24H_CHANGE:
                continue

            combined = symbol + " " + name
            if any(x in combined for x in EXCLUDED_KEYWORDS):
                continue

            allowed[symbol] = {
                "name": coin.get("name", symbol),
                "market_cap": market_cap,
                "volume_24h": volume_24h,
                "change_24h": change_24h,
                "rank": coin.get("cmc_rank")
            }

        cmc_allowed_symbols = allowed
        last_cmc_update = now

        print(f"CMC allowed symbols: {len(cmc_allowed_symbols)}")

    except Exception as e:
        print("CMC update error:", e)

def cmc_is_allowed(symbol):
    if not USE_CMC_FILTER:
        return True

    if not CMC_API_KEY:
        return True

    if not cmc_allowed_symbols:
        return True

    return base_symbol(symbol) in cmc_allowed_symbols

def get_cmc_info(symbol):
    return cmc_allowed_symbols.get(base_symbol(symbol), {})

def ema(series, length):
    return series.ewm(span=length, adjust=False).mean()

def rsi(series, period=14):
    delta = series.diff()
    gain = delta.where(delta > 0, 0).rolling(period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(period).mean()
    rs = gain / loss.replace(0, math.nan)
    return 100 - (100 / (1 + rs))

def stoch_rsi(close):
    r = rsi(close, RSI_PERIOD)
    min_rsi = r.rolling(STOCH_PERIOD).min()
    max_rsi = r.rolling(STOCH_PERIOD).max()
    stoch = 100 * (r - min_rsi) / (max_rsi - min_rsi)
    k = stoch.rolling(K_SMOOTH).mean()
    d = k.rolling(D_SMOOTH).mean()
    return k, d

def macd_hist(close):
    macd_line = ema(close, 12) - ema(close, 26)
    signal = ema(macd_line, 9)
    return macd_line - signal

def gate_symbols():
    try:
        url = "https://api.gateio.ws/api/v4/spot/currency_pairs"
        data = requests.get(url, timeout=20).json()
        symbols = []
        for x in data:
            pair = x.get("id", "")
            if pair.endswith("_USDT") and x.get("trade_status") == "tradable":
                if cmc_is_allowed(pair):
                    symbols.append(pair)
        return symbols[:MAX_COINS]
    except Exception as e:
        print("Gate symbols error:", e)
        return []

def gate_ticker(symbol):
    try:
        url = f"https://api.gateio.ws/api/v4/spot/tickers?currency_pair={symbol}"
        data = requests.get(url, timeout=15).json()
        if not data:
            return None
        x = data[0]
        return {
            "price": safe_float(x.get("last")),
            "quote_volume": safe_float(x.get("quote_volume")),
            "change_24h": safe_float(x.get("change_percentage"))
        }
    except Exception:
        return None

def gate_candles(symbol):
    try:
        url = "https://api.gateio.ws/api/v4/spot/candlesticks"
        params = {
            "currency_pair": symbol,
            "interval": convert_timeframe("Gate"),
            "limit": 120
        }
        data = requests.get(url, params=params, timeout=20).json()
        rows = []
        for c in data:
            rows.append({
                "time": int(c[0]),
                "volume_quote": safe_float(c[1]),
                "close": safe_float(c[2]),
                "high": safe_float(c[3]),
                "low": safe_float(c[4]),
                "open": safe_float(c[5])
            })
        df = pd.DataFrame(rows).sort_values("time").reset_index(drop=True)
        return df if len(df) >= 60 else None
    except Exception:
        return None

def mexc_symbols():
    try:
        url = "https://api.mexc.com/api/v3/exchangeInfo"
        data = requests.get(url, timeout=20).json()
        symbols = []
        for x in data.get("symbols", []):
            s = x.get("symbol", "")
            if s.endswith("USDT") and x.get("status") == "ENABLED":
                if cmc_is_allowed(s):
                    symbols.append(s)
        return symbols[:MAX_COINS]
    except Exception as e:
        print("MEXC symbols error:", e)
        return []

def mexc_ticker(symbol):
    try:
        url = f"https://api.mexc.com/api/v3/ticker/24hr?symbol={symbol}"
        x = requests.get(url, timeout=15).json()
        return {
            "price": safe_float(x.get("lastPrice")),
            "quote_volume": safe_float(x.get("quoteVolume")),
            "change_24h": safe_float(x.get("priceChangePercent"))
        }
    except Exception:
        return None

def mexc_candles(symbol):
    try:
        url = "https://api.mexc.com/api/v3/klines"
        params = {
            "symbol": symbol,
            "interval": convert_timeframe("MEXC"),
            "limit": 120
        }
        data = requests.get(url, params=params, timeout=20).json()
        rows = []
        for c in data:
            rows.append({
                "time": int(c[0]),
                "open": safe_float(c[1]),
                "high": safe_float(c[2]),
                "low": safe_float(c[3]),
                "close": safe_float(c[4]),
                "volume_quote": safe_float(c[7])
            })
        df = pd.DataFrame(rows).sort_values("time").reset_index(drop=True)
        return df if len(df) >= 60 else None
    except Exception:
        return None

def kucoin_symbols():
    try:
        url = "https://api.kucoin.com/api/v1/symbols"
        data = requests.get(url, timeout=20).json()
        symbols = []
        for x in data.get("data", []):
            s = x.get("symbol", "")
            if s.endswith("-USDT") and x.get("enableTrading"):
                if cmc_is_allowed(s):
                    symbols.append(s)
        return symbols[:MAX_COINS]
    except Exception as e:
        print("KuCoin symbols error:", e)
        return []

def kucoin_ticker(symbol):
    try:
        url = f"https://api.kucoin.com/api/v1/market/stats?symbol={symbol}"
        x = requests.get(url, timeout=15).json().get("data", {})
        return {
            "price": safe_float(x.get("last")),
            "quote_volume": safe_float(x.get("volValue")),
            "change_24h": safe_float(x.get("changeRate")) * 100
        }
    except Exception:
        return None

def kucoin_candles(symbol):
    try:
        url = "https://api.kucoin.com/api/v1/market/candles"
        params = {
            "symbol": symbol,
            "type": convert_timeframe("KuCoin")
        }
        data = requests.get(url, params=params, timeout=20).json().get("data", [])
        rows = []
        for c in data[:120]:
            rows.append({
                "time": int(c[0]),
                "open": safe_float(c[1]),
                "close": safe_float(c[2]),
                "high": safe_float(c[3]),
                "low": safe_float(c[4]),
                "volume_quote": safe_float(c[6])
            })
        df = pd.DataFrame(rows).sort_values("time").reset_index(drop=True)
        return df if len(df) >= 60 else None
    except Exception:
        return None

def okx_symbols():
    try:
        url = "https://www.okx.com/api/v5/public/instruments?instType=SPOT"
        data = requests.get(url, timeout=20).json()
        symbols = []
        for x in data.get("data", []):
            s = x.get("instId", "")
            if s.endswith("-USDT") and x.get("state") == "live":
                if cmc_is_allowed(s):
                    symbols.append(s)
        return symbols[:MAX_COINS]
    except Exception as e:
        print("OKX symbols error:", e)
        return []

def okx_ticker(symbol):
    try:
        url = f"https://www.okx.com/api/v5/market/ticker?instId={symbol}"
        x = requests.get(url, timeout=15).json().get("data", [])[0]
        open24h = safe_float(x.get("open24h"))
        last = safe_float(x.get("last"))
        change = ((last - open24h) / open24h * 100) if open24h > 0 else 0
        return {
            "price": last,
            "quote_volume": safe_float(x.get("volCcy24h")),
            "change_24h": change
        }
    except Exception:
        return None

def okx_candles(symbol):
    try:
        url = "https://www.okx.com/api/v5/market/candles"
        params = {
            "instId": symbol,
            "bar": convert_timeframe("OKX"),
            "limit": 120
        }
        data = requests.get(url, params=params, timeout=20).json().get("data", [])
        rows = []
        for c in data:
            rows.append({
                "time": int(c[0]),
                "open": safe_float(c[1]),
                "high": safe_float(c[2]),
                "low": safe_float(c[3]),
                "close": safe_float(c[4]),
                "volume_quote": safe_float(c[7])
            })
        df = pd.DataFrame(rows).sort_values("time").reset_index(drop=True)
        return df if len(df) >= 60 else None
    except Exception:
        return None

def bybit_symbols():
    try:
        url = "https://api.bybit.com/v5/market/instruments-info"
        params = {"category": "spot"}
        data = requests.get(url, params=params, timeout=20).json()
        symbols = []
        for x in data.get("result", {}).get("list", []):
            s = x.get("symbol", "")
            if s.endswith("USDT") and x.get("status") == "Trading":
                if cmc_is_allowed(s):
                    symbols.append(s)
        return symbols[:MAX_COINS]
    except Exception as e:
        print("Bybit symbols error:", e)
        return []

def bybit_ticker(symbol):
    try:
        url = "https://api.bybit.com/v5/market/tickers"
        params = {"category": "spot", "symbol": symbol}
        x = requests.get(url, params=params, timeout=15).json().get("result", {}).get("list", [])[0]
        return {
            "price": safe_float(x.get("lastPrice")),
            "quote_volume": safe_float(x.get("turnover24h")),
            "change_24h": safe_float(x.get("price24hPcnt")) * 100
        }
    except Exception:
        return None

def bybit_candles(symbol):
    try:
        url = "https://api.bybit.com/v5/market/kline"
        params = {
            "category": "spot",
            "symbol": symbol,
            "interval": convert_timeframe("Bybit"),
            "limit": 120
        }
        data = requests.get(url, params=params, timeout=20).json().get("result", {}).get("list", [])
        rows = []
        for c in data:
            rows.append({
                "time": int(c[0]),
                "open": safe_float(c[1]),
                "high": safe_float(c[2]),
                "low": safe_float(c[3]),
                "close": safe_float(c[4]),
                "volume_quote": safe_float(c[6])
            })
        df = pd.DataFrame(rows).sort_values("time").reset_index(drop=True)
        return df if len(df) >= 60 else None
    except Exception:
        return None

def bitget_symbols():
    try:
        url = "https://api.bitget.com/api/v2/spot/public/symbols"
        data = requests.get(url, timeout=20).json()
        symbols = []
        for x in data.get("data", []):
            s = x.get("symbol", "")
            if s.endswith("USDT") and x.get("status") == "online":
                if cmc_is_allowed(s):
                    symbols.append(s)
        return symbols[:MAX_COINS]
    except Exception as e:
        print("Bitget symbols error:", e)
        return []

def bitget_ticker(symbol):
    try:
        url = "https://api.bitget.com/api/v2/spot/market/tickers"
        params = {"symbol": symbol}
        x = requests.get(url, params=params, timeout=15).json().get("data", [])[0]
        return {
            "price": safe_float(x.get("lastPr")),
            "quote_volume": safe_float(x.get("quoteVolume")),
            "change_24h": safe_float(x.get("change24h")) * 100
        }
    except Exception:
        return None

def bitget_candles(symbol):
    try:
        url = "https://api.bitget.com/api/v2/spot/market/candles"
        params = {
            "symbol": symbol,
            "granularity": convert_timeframe("Bitget"),
            "limit": 120
        }
        data = requests.get(url, params=params, timeout=20).json().get("data", [])
        rows = []
        for c in data:
            rows.append({
                "time": int(c[0]),
                "open": safe_float(c[1]),
                "high": safe_float(c[2]),
                "low": safe_float(c[3]),
                "close": safe_float(c[4]),
                "volume_quote": safe_float(c[6])
            })
        df = pd.DataFrame(rows).sort_values("time").reset_index(drop=True)
        return df if len(df) >= 60 else None
    except Exception:
        return None

def analyze_symbol(exchange, symbol, ticker_func, candle_func):
    if is_excluded(symbol):
        return None

    ticker = ticker_func(symbol)
    if not ticker:
        return None

    price = ticker["price"]
    quote_volume = ticker["quote_volume"]
    change_24h = ticker["change_24h"]

    if price <= 0:
        return None

    if quote_volume < MIN_VOLUME_USDT:
        return None

    if abs(change_24h) > MAX_24H_CHANGE:
        return None

    df = candle_func(symbol)
    if df is None or len(df) < 60:
        return None

    close = df["close"]
    volume = df["volume_quote"]

    k, d = stoch_rsi(close)
    hist = macd_hist(close)
    ema20 = ema(close, 20)

    k_now = k.iloc[-1]
    d_now = d.iloc[-1]
    k_prev = k.iloc[-2]
    d_prev = d.iloc[-2]

    hist_now = hist.iloc[-1]
    hist_prev = hist.iloc[-2]

    current_price = close.iloc[-1]
    current_volume = volume.iloc[-1]

    if current_volume < MIN_CURRENT_CANDLE_VOLUME:
        return None

    avg_volume = volume.iloc[-(VOLUME_LOOKBACK + 1):-1].mean()

    if pd.isna(k_now) or pd.isna(d_now) or pd.isna(hist_now) or avg_volume <= 0:
        return None

    volume_ratio = current_volume / avg_volume

    stoch_cross = k_prev <= d_prev and k_now > d_now
    stoch_low = k_now < MAX_RSI_BUY
    macd_rising = hist_now > hist_prev
    volume_ok = volume_ratio >= MIN_VOLUME_RATIO
    price_above_ema20 = current_price > ema20.iloc[-1]

    if not (stoch_cross and stoch_low and macd_rising and volume_ok):
        return None

    key = f"{exchange}:{symbol}"
    if not cooldown_ok(key):
        return None

    score = 0
    reasons = []

    if stoch_cross:
        score += 30
        reasons.append("✅ Stoch RSI K اخترق D")
    if stoch_low:
        score += 20
        reasons.append(f"✅ Stoch RSI تحت {MAX_RSI_BUY}")
    if macd_rising:
        score += 20
        reasons.append("✅ MACD Histogram يتحسن")
    if volume_ok:
        score += 20
        reasons.append(f"✅ Volume Ratio أعلى من {MIN_VOLUME_RATIO}x")
    if price_above_ema20:
        score += 10
        reasons.append("✅ السعر فوق EMA20")

    sent_signals[key] = time.time()

    cmc = get_cmc_info(symbol)

    return {
        "exchange": exchange,
        "symbol": normalize_symbol(symbol),
        "price": current_price,
        "k": k_now,
        "d": d_now,
        "macd": hist_now,
        "macd_prev": hist_prev,
        "volume": current_volume,
        "avg_volume": avg_volume,
        "volume_ratio": volume_ratio,
        "quote_volume": quote_volume,
        "change_24h": change_24h,
        "score": score,
        "reasons": reasons,
        "tp1": current_price * 1.03,
        "tp2": current_price * 1.06,
        "tp3": current_price * 1.10,
        "sl": current_price * 0.94,
        "cmc_name": cmc.get("name", ""),
        "cmc_rank": cmc.get("rank", ""),
        "market_cap": cmc.get("market_cap", 0),
        "cmc_volume_24h": cmc.get("volume_24h", 0)
    }

def format_signal(s):
    reasons = "\n".join(s["reasons"])
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    cmc_text = ""
    if s["market_cap"]:
        cmc_text = f"""
🌐 <b>CoinMarketCap</b>
الاسم: {s['cmc_name']}
الترتيب: {s['cmc_rank']}
Market Cap: ${s['market_cap']:,.0f}
CMC 24H Volume: ${s['cmc_volume_24h']:,.0f}
"""

    return f"""
🟢 <b>EARLY REVERSAL ALERT</b>
━━━━━━━━━━━━━━
⏰ الوقت: {now}
🏦 المنصة: <b>{s['exchange']}</b>
🪙 العملة: <b>{s['symbol']}</b>
💰 سعر الدخول: <b>{s['price']:.8f}</b>

📊 <b>Stoch RSI</b>
K: {s['k']:.2f}
D: {s['d']:.2f}

📈 <b>MACD Histogram</b>
الحالي: {s['macd']:.8f}
السابق: {s['macd_prev']:.8f}
الحالة: يتحسن ✅

💧 <b>Volume</b>
حجم الشمعة الحالية: ${s['volume']:,.0f}
متوسط آخر {VOLUME_LOOKBACK} شمعة: ${s['avg_volume']:,.0f}
Volume Ratio: <b>{s['volume_ratio']:.2f}x</b>

📊 Exchange 24H Volume: ${s['quote_volume']:,.0f}
📈 تغير 24H: {s['change_24h']:.2f}%
{cmc_text}
🎯 <b>الأهداف</b>
TP1: {s['tp1']:.8f} (+3%)
TP2: {s['tp2']:.8f} (+6%)
TP3: {s['tp3']:.8f} (+10%)
SL: {s['sl']:.8f} (-6%)

⭐ قوة الإشارة: <b>{s['score']}%</b>

🔥 <b>أسباب التنبيه</b>
{reasons}

⚠️ تحليل آلي فقط وليس نصيحة مالية.
"""

def startup_message():
    exchanges = []
    if ENABLE_GATE:
        exchanges.append("Gate")
    if ENABLE_MEXC:
        exchanges.append("MEXC")
    if ENABLE_KUCOIN:
        exchanges.append("KuCoin")
    if ENABLE_OKX:
        exchanges.append("OKX")
    if ENABLE_BYBIT:
        exchanges.append("Bybit")
    if ENABLE_BITGET:
        exchanges.append("Bitget")

    exchange_text = "\n".join([f"• {x}" for x in exchanges])

    msg = f"""
🤖 <b>بوت Early Reversal اشتغل بنجاح ✅</b>

━━━━━━━━━━━━━━
📊 الفريم: <b>{TIMEFRAME}</b>
⏱️ الفحص كل: <b>{CHECK_INTERVAL} ثانية</b>

🏦 <b>المنصات المفعلة:</b>
{exchange_text}

🌐 <b>CoinMarketCap Filter:</b>
الحالة: {'مفعل ✅' if USE_CMC_FILTER else 'غير مفعل ❌'}
Top N: {CMC_TOP_N}
Min Market Cap: ${MIN_MARKET_CAP:,.0f}
Max Market Cap: ${MAX_MARKET_CAP:,.0f}

🎯 <b>شروط الدخول الحالية:</b>
• Stoch RSI K يخترق D
• Stoch RSI أقل من {MAX_RSI_BUY}
• MACD Histogram يتحسن
• Volume Ratio أعلى من {MIN_VOLUME_RATIO}x
• حجم الشمعة الحالية أعلى من ${MIN_CURRENT_CANDLE_VOLUME:,.0f}
• 24H Change أقل من {MAX_24H_CHANGE}%

💧 <b>فلتر الفوليوم:</b>
• أقل حجم تداول 24H: ${MIN_VOLUME_USDT:,.0f}
• مقارنة الفوليوم مع آخر {VOLUME_LOOKBACK} شمعة

⚡ الوضع:
صيد الانعكاسات المبكرة قبل الانطلاقة 🚀

✅ البوت يعمل الآن...
"""
    send_telegram(msg)

def scan_exchange(name, symbols_func, ticker_func, candle_func):
    try:
        symbols = symbols_func()
        print(f"Scanning {name}: {len(symbols)} symbols")

        found = 0
        for symbol in symbols:
            signal = analyze_symbol(name, symbol, ticker_func, candle_func)
            if signal:
                found += 1
                send_telegram(format_signal(signal))
                print(f"Signal Found: {name} {symbol}")

            time.sleep(0.15)

        print(f"{name} scan finished. Signals: {found}")

    except Exception as e:
        print(f"{name} scan error:", e)

def scanner_loop():
    startup_message()

    while True:
        try:
            update_cmc_filter()

            if ENABLE_GATE:
                scan_exchange("Gate", gate_symbols, gate_ticker, gate_candles)

            if ENABLE_MEXC:
                scan_exchange("MEXC", mexc_symbols, mexc_ticker, mexc_candles)

            if ENABLE_KUCOIN:
                scan_exchange("KuCoin", kucoin_symbols, kucoin_ticker, kucoin_candles)

            if ENABLE_OKX:
                scan_exchange("OKX", okx_symbols, okx_ticker, okx_candles)

            if ENABLE_BYBIT:
                scan_exchange("Bybit", bybit_symbols, bybit_ticker, bybit_candles)

            if ENABLE_BITGET:
                scan_exchange("Bitget", bitget_symbols, bitget_ticker, bitget_candles)

            print("Full scan finished.")

        except Exception as e:
            print("Main scanner error:", e)

        time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    Thread(target=scanner_loop, daemon=True).start()
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "8080")))
