import os
import time
import json
import threading

import requests
import ccxt
import pytz
from flask import Flask


# =========================================
# ENV HELPERS
# =========================================

def env_str(name, default=""):
    return os.getenv(name, default).strip()


def env_int(name, default):
    try:
        return int(os.getenv(name, default))
    except:
        return default


def env_float(name, default):
    try:
        return float(os.getenv(name, default))
    except:
        return default


def env_bool(name, default=False):
    value = os.getenv(name, str(default)).lower()
    return value in ["true", "1", "yes"]


# =========================================
# VARIABLES
# =========================================

TELEGRAM_BOT_TOKEN = env_str("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHANNEL_ID = env_str("TELEGRAM_CHANNEL_ID")
CMC_API_KEY = env_str("CMC_API_KEY")

CMC_TOP_N = env_int("CMC_TOP_N", 2000)
CHECK_INTERVAL = env_int("CHECK_INTERVAL", 900)

TREND_TIMEFRAME = env_str("TREND_TIMEFRAME", "1d")
ENTRY_TIMEFRAME = env_str("ENTRY_TIMEFRAME", "1h")

EMA_PERIOD = env_int("EMA_PERIOD", 20)
RSI_PERIOD = env_int("RSI_PERIOD", 14)
STOCH_RSI_PERIOD = env_int("STOCH_RSI_PERIOD", 14)

MAX_STOCH_RSI = env_float("MAX_STOCH_RSI", 60)

MIN_VOLUME_RATIO = env_float("MIN_VOLUME_RATIO", 0.3)
MIN_CANDLE_VOLUME_USD = env_float("MIN_CANDLE_VOLUME_USD", 15000)
MIN_24H_VOLUME_USD = env_float("MIN_24H_VOLUME_USD", 100000)

REQUIRE_TREND_CLOSE_ABOVE_EMA = env_bool("REQUIRE_TREND_CLOSE_ABOVE_EMA", False)
REQUIRE_TREND_MACD_POSITIVE = env_bool("REQUIRE_TREND_MACD_POSITIVE", True)

REQUIRE_ENTRY_CLOSE_ABOVE_EMA = env_bool("REQUIRE_ENTRY_CLOSE_ABOVE_EMA", False)
REQUIRE_ENTRY_STOCH_K_ABOVE_D = env_bool("REQUIRE_ENTRY_STOCH_K_ABOVE_D", True)
REQUIRE_ENTRY_MACD_POSITIVE = env_bool("REQUIRE_ENTRY_MACD_POSITIVE", False)
REQUIRE_ENTRY_MACD_RISING = env_bool("REQUIRE_ENTRY_MACD_RISING", True)

ENABLE_GATE = env_bool("ENABLE_GATE", True)
ENABLE_KUCOIN = env_bool("ENABLE_KUCOIN", True)
ENABLE_OKX = env_bool("ENABLE_OKX", True)
ENABLE_BYBIT = env_bool("ENABLE_BYBIT", True)
ENABLE_BITGET = env_bool("ENABLE_BITGET", True)

COOLDOWN_HOURS = env_int("COOLDOWN_HOURS", 12)

TP1_PERCENT = env_float("TP1_PERCENT", 3)
TP2_PERCENT = env_float("TP2_PERCENT", 6)
TP3_PERCENT = env_float("TP3_PERCENT", 10)
SL_PERCENT = env_float("SL_PERCENT", 6)

TIMEZONE = pytz.timezone("Asia/Riyadh")

SENT_FILE = "sent_signals.json"

app = Flask(__name__)


@app.route("/")
def home():
    return "Bot Running ✅"


# =========================================
# TELEGRAM
# =========================================

def send_telegram(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHANNEL_ID:
        print("Telegram not configured")
        return

    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"

        payload = {
            "chat_id": TELEGRAM_CHANNEL_ID,
            "text": message,
            "parse_mode": "Markdown",
            "disable_web_page_preview": True
        }

        r = requests.post(url, json=payload, timeout=20)

        if r.status_code != 200:
            print(f"Telegram Error: {r.text}")

    except Exception as e:
        print(f"Telegram Error: {e}")


# =========================================
# JSON
# =========================================

def load_json(path, default):
    try:
        if os.path.exists(path):
            with open(path, "r") as f:
                return json.load(f)
    except:
        pass

    return default


def save_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


sent_signals = load_json(SENT_FILE, {})


# =========================================
# EXCHANGES
# =========================================

EXCHANGES = []

if ENABLE_GATE:
    EXCHANGES.append(("Gate", ccxt.gateio()))

if ENABLE_KUCOIN:
    EXCHANGES.append(("KuCoin", ccxt.kucoin()))

if ENABLE_OKX:
    EXCHANGES.append(("OKX", ccxt.okx()))

if ENABLE_BYBIT:
    EXCHANGES.append(("Bybit", ccxt.bybit()))

if ENABLE_BITGET:
    EXCHANGES.append(("Bitget", ccxt.bitget()))


# =========================================
# CMC
# =========================================

def get_cmc_symbols():
    if not CMC_API_KEY:
        print("CMC_API_KEY missing")
        return []

    url = "https://pro-api.coinmarketcap.com/v1/cryptocurrency/listings/latest"

    headers = {
        "X-CMC_PRO_API_KEY": CMC_API_KEY
    }

    params = {
        "start": 1,
        "limit": CMC_TOP_N,
        "convert": "USD"
    }

    try:
        r = requests.get(url, headers=headers, params=params, timeout=30)
        data = r.json().get("data", [])

        symbols = []

        for coin in data:
            symbol = coin["symbol"].upper()
            volume_24h = coin["quote"]["USD"]["volume_24h"]

            if volume_24h >= MIN_24H_VOLUME_USD:
                symbols.append(symbol)

        return symbols

    except Exception as e:
        print(f"CMC Error: {e}")
        return []


# =========================================
# INDICATORS
# =========================================

def ema(values, period):
    if len(values) < period:
        return [None] * len(values)

    result = []
    multiplier = 2 / (period + 1)

    sma_value = sum(values[:period]) / period
    result.append(sma_value)

    for price in values[period:]:
        value = ((price - result[-1]) * multiplier) + result[-1]
        result.append(value)

    return [None] * (period - 1) + result


def rsi(values, period=14):
    if len(values) <= period:
        return [None] * len(values)

    gains = []
    losses = []

    for i in range(1, len(values)):
        diff = values[i] - values[i - 1]
        gains.append(max(diff, 0))
        losses.append(abs(min(diff, 0)))

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    rsis = [None] * period

    for i in range(period, len(gains)):
        avg_gain = ((avg_gain * (period - 1)) + gains[i]) / period
        avg_loss = ((avg_loss * (period - 1)) + losses[i]) / period

        if avg_loss == 0:
            rsis.append(100)
        else:
            rs = avg_gain / avg_loss
            rsis.append(100 - (100 / (1 + rs)))

    while len(rsis) < len(values):
        rsis.append(None)

    return rsis[:len(values)]


def sma(values, period):
    result = []

    for i in range(len(values)):
        if i + 1 < period:
            result.append(None)
        else:
            window = values[i + 1 - period:i + 1]

            if any(x is None for x in window):
                result.append(None)
            else:
                result.append(sum(window) / period)

    return result


def stoch_rsi(closes):
    rsi_values = rsi(closes, RSI_PERIOD)

    stoch = []

    for i in range(len(rsi_values)):
        if i < STOCH_RSI_PERIOD or rsi_values[i] is None:
            stoch.append(None)
            continue

        window = [
            x for x in rsi_values[i - STOCH_RSI_PERIOD:i]
            if x is not None
        ]

        if len(window) < STOCH_RSI_PERIOD:
            stoch.append(None)
            continue

        low = min(window)
        high = max(window)

        if high - low == 0:
            stoch.append(0)
        else:
            value = ((rsi_values[i] - low) / (high - low)) * 100
            stoch.append(value)

    k = sma(stoch, 3)
    d = sma(k, 3)

    return k, d


def macd(closes, fast=12, slow=26, signal=9):
    ema_fast = ema(closes, fast)
    ema_slow = ema(closes, slow)

    macd_line = []

    for f, s in zip(ema_fast, ema_slow):
        if f is None or s is None:
            macd_line.append(None)
        else:
            macd_line.append(f - s)

    valid = [x for x in macd_line if x is not None]

    if len(valid) < signal:
        return [None] * len(closes)

    signal_valid = ema(valid, signal)

    signal_line = []
    idx = 0

    for x in macd_line:
        if x is None:
            signal_line.append(None)
        else:
            signal_line.append(signal_valid[idx])
            idx += 1

    histogram = []

    for m, s in zip(macd_line, signal_line):
        if m is None or s is None:
            histogram.append(None)
        else:
            histogram.append(m - s)

    return histogram


# =========================================
# ANALYZE
# =========================================

def analyze(exchange, symbol):
    try:
        trend_data = exchange.fetch_ohlcv(symbol, TREND_TIMEFRAME, limit=150)
        entry_data = exchange.fetch_ohlcv(symbol, ENTRY_TIMEFRAME, limit=150)

        if not trend_data or not entry_data:
            return None

        trend_closes = [x[4] for x in trend_data]
        entry_closes = [x[4] for x in entry_data]

        trend_ema = ema(trend_closes, EMA_PERIOD)
        entry_ema = ema(entry_closes, EMA_PERIOD)

        trend_macd = macd(trend_closes)
        entry_macd = macd(entry_closes)

        k, d = stoch_rsi(entry_closes)

        if (
            trend_ema[-1] is None or
            entry_ema[-1] is None or
            trend_macd[-1] is None or
            entry_macd[-1] is None or
            entry_macd[-2] is None or
            k[-1] is None or
            d[-1] is None
        ):
            return None

        trend_close = trend_closes[-1]
        entry_close = entry_closes[-1]

        current_volume = entry_data[-1][4] * entry_data[-1][5]

        avg_volume = 0
        for c in entry_data[-21:-1]:
            avg_volume += c[4] * c[5]

        avg_volume = avg_volume / 20 if avg_volume > 0 else 0

        volume_ratio = current_volume / avg_volume if avg_volume > 0 else 0

        trend_ok = True
        entry_ok = True

        if REQUIRE_TREND_CLOSE_ABOVE_EMA:
            trend_ok = trend_ok and trend_close > trend_ema[-1]

        if REQUIRE_TREND_MACD_POSITIVE:
            trend_ok = trend_ok and trend_macd[-1] > 0

        if REQUIRE_ENTRY_CLOSE_ABOVE_EMA:
            entry_ok = entry_ok and entry_close > entry_ema[-1]

        if REQUIRE_ENTRY_STOCH_K_ABOVE_D:
            entry_ok = entry_ok and k[-1] > d[-1]

        if REQUIRE_ENTRY_MACD_POSITIVE:
            entry_ok = entry_ok and entry_macd[-1] > 0

        if REQUIRE_ENTRY_MACD_RISING:
            entry_ok = entry_ok and entry_macd[-1] > entry_macd[-2]

        entry_ok = (
            entry_ok and
            k[-1] < MAX_STOCH_RSI and
            volume_ratio >= MIN_VOLUME_RATIO and
            current_volume >= MIN_CANDLE_VOLUME_USD
        )

        if trend_ok and entry_ok:
            return {
                "price": entry_close,
                "k": k[-1],
                "d": d[-1],
                "macd": entry_macd[-1],
                "macd_prev": entry_macd[-2],
                "volume_ratio": volume_ratio,
                "current_volume": current_volume,
                "avg_volume": avg_volume,
                "trend_close": trend_close,
                "trend_ema": trend_ema[-1],
                "entry_ema": entry_ema[-1],
            }

    except Exception as e:
        print(f"{symbol} Error: {e}")

    return None


# =========================================
# MESSAGE
# =========================================

def signal_message(exchange_name, symbol, data):
    price = data["price"]

    tp1 = price * (1 + TP1_PERCENT / 100)
    tp2 = price * (1 + TP2_PERCENT / 100)
    tp3 = price * (1 + TP3_PERCENT / 100)
    sl = price * (1 - SL_PERCENT / 100)

    if data["macd"] > 0:
        macd_status = "موجب ✅"
    elif data["macd"] > data["macd_prev"]:
        macd_status = "انعكاس مبكر ويتحسن 🔄"
    else:
        macd_status = "ضعيف ⚠️"

    if data["volume_ratio"] >= 5:
        volume_strength = "قوي جدًا 🔥"
    elif data["volume_ratio"] >= 2:
        volume_strength = "قوي ✅"
    elif data["volume_ratio"] >= 1:
        volume_strength = "متوسط ⚠️"
    else:
        volume_strength = "بداية حركة / منخفض"

    return f"""
🟢 MULTI-TIMEFRAME SIGNAL
━━━━━━━━━━━━━━

🏦 المنصة: {exchange_name}
🪙 العملة: {symbol}

💰 سعر الدخول:
{price:.8f}

📈 الاتجاه:
• Trend Frame: {TREND_TIMEFRAME}
• Entry Frame: {ENTRY_TIMEFRAME}

📊 Stoch RSI
K: {data['k']:.2f}
D: {data['d']:.2f}

📈 MACD Histogram
الحالي: {data['macd']:.8f}
السابق: {data['macd_prev']:.8f}
الحالة: {macd_status}

💧 Volume
الحالي: ${data['current_volume']:,.0f}
المتوسط: ${data['avg_volume']:,.0f}
Volume Ratio: {data['volume_ratio']:.2f}x
القوة: {volume_strength}

🎯 Targets
TP1: {tp1:.8f} (+{TP1_PERCENT}%)
TP2: {tp2:.8f} (+{TP2_PERCENT}%)
TP3: {tp3:.8f} (+{TP3_PERCENT}%)

🛑 Stop Loss
{sl:.8f} (-{SL_PERCENT}%)

⏰ Cooldown:
{COOLDOWN_HOURS} ساعة

⚠️ تحليل آلي وليس توصية مالية
"""


def startup_message():
    enabled = [name for name, _ in EXCHANGES]

    return f"""
🤖 بوت الإشارات اشتغل بنجاح ✅
━━━━━━━━━━━━━━

📈 Trend Timeframe: {TREND_TIMEFRAME}
📈 Entry Timeframe: {ENTRY_TIMEFRAME}
⏱️ الفحص كل: {CHECK_INTERVAL} ثانية

🏦 المنصات:
{", ".join(enabled)}

🌐 CoinMarketCap:
Top N: {CMC_TOP_N}
Min 24H Volume: ${MIN_24H_VOLUME_USD:,.0f}

🎯 شروط الدخول:
• MAX Stoch RSI: أقل من {MAX_STOCH_RSI}
• Volume Ratio: أعلى من {MIN_VOLUME_RATIO}x
• Candle Volume: أعلى من ${MIN_CANDLE_VOLUME_USD:,.0f}

⚙️ الشروط المفعلة:
• Trend Close Above EMA: {REQUIRE_TREND_CLOSE_ABOVE_EMA}
• Trend MACD Positive: {REQUIRE_TREND_MACD_POSITIVE}
• Entry Close Above EMA: {REQUIRE_ENTRY_CLOSE_ABOVE_EMA}
• K Above D: {REQUIRE_ENTRY_STOCH_K_ABOVE_D}
• Entry MACD Positive: {REQUIRE_ENTRY_MACD_POSITIVE}
• Entry MACD Rising: {REQUIRE_ENTRY_MACD_RISING}

🧊 Cooldown:
{COOLDOWN_HOURS} ساعة

✅ البوت بدأ الفحص الآن.
"""


# =========================================
# COOLDOWN
# =========================================

def can_send_signal(signal_key):
    if signal_key not in sent_signals:
        return True

    try:
        last_sent = float(sent_signals[signal_key])
    except:
        return True

    hours_passed = (time.time() - last_sent) / 3600

    return hours_passed >= COOLDOWN_HOURS


# =========================================
# LOOP
# =========================================

def scanner_loop():
    send_telegram(startup_message())

    while True:
        try:
            print("Scanning CoinMarketCap...")

            symbols = get_cmc_symbols()
            print(f"Symbols Loaded: {len(symbols)}")

            signals_found = 0

            for exchange_name, exchange in EXCHANGES:
                try:
                    exchange.load_markets()

                    for base in symbols:
                        symbol = f"{base}/USDT"

                        if symbol not in exchange.markets:
                            continue

                        signal_key = f"{exchange_name}:{symbol}"

                        if not can_send_signal(signal_key):
                            continue

                        data = analyze(exchange, symbol)

                        if data:
                            send_telegram(signal_message(exchange_name, symbol, data))

                            sent_signals[signal_key] = time.time()
                            save_json(SENT_FILE, sent_signals)

                            signals_found += 1
                            time.sleep(1)

                except Exception as e:
                    print(f"{exchange_name} Error: {e}")

            print(f"Signals Found: {signals_found}")

        except Exception as e:
            print(f"Scanner Error: {e}")

        time.sleep(CHECK_INTERVAL)


# =========================================
# MAIN
# =========================================

if __name__ == "__main__":
    threading.Thread(target=scanner_loop, daemon=True).start()

    port = int(os.getenv("PORT", 8080))

    app.run(
        host="0.0.0.0",
        port=port
    )
