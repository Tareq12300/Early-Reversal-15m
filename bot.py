import os
import time
import json
import threading
from datetime import datetime

import requests
import ccxt
import pytz
from flask import Flask


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


TELEGRAM_BOT_TOKEN = env_str("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHANNEL_ID = env_str("TELEGRAM_CHANNEL_ID")
CMC_API_KEY = env_str("CMC_API_KEY")

CMC_TOP_N = env_int("CMC_TOP_N", 1000)
CHECK_INTERVAL = env_int("CHECK_INTERVAL", 3600)

TREND_TIMEFRAME = env_str("TREND_TIMEFRAME", "1d")
ENTRY_TIMEFRAME = env_str("ENTRY_TIMEFRAME", "4h")

EMA_PERIOD = env_int("EMA_PERIOD", 50)
RSI_PERIOD = env_int("RSI_PERIOD", 14)
STOCH_RSI_PERIOD = env_int("STOCH_RSI_PERIOD", 14)

MAX_STOCH_RSI = env_float("MAX_STOCH_RSI", 40)

MIN_VOLUME_RATIO = env_float("MIN_VOLUME_RATIO", 1.0)
MIN_CANDLE_VOLUME_USD = env_float("MIN_CANDLE_VOLUME_USD", 8000)
MIN_24H_VOLUME_USD = env_float("MIN_24H_VOLUME_USD", 500000)

TP1_PERCENT = env_float("TP1_PERCENT", 3)
TP2_PERCENT = env_float("TP2_PERCENT", 6)
TP3_PERCENT = env_float("TP3_PERCENT", 10)
SL_PERCENT = env_float("SL_PERCENT", 6)

TIMEZONE = pytz.timezone("Asia/Riyadh")

SIGNALS_FILE = "active_signals.json"
SENT_FILE = "sent_signals.json"


app = Flask(__name__)


@app.route("/")
def home():
    return "Bot Running ✅"


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


active_signals = load_json(SIGNALS_FILE, {})
sent_signals = load_json(SENT_FILE, {})


EXCHANGES = [
    ("Gate", ccxt.gateio()),
    ("KuCoin", ccxt.kucoin()),
    ("OKX", ccxt.okx()),
    ("Bybit", ccxt.bybit()),
    ("Bitget", ccxt.bitget())
]


def get_cmc_symbols():
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
        data = r.json()["data"]

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


def ema(values, period):
    if len(values) < period:
        return [None] * len(values)

    result = []
    multiplier = 2 / (period + 1)

    sma_value = sum(values[:period]) / period
    result.append(sma_value)

    for price in values[period:]:
        value = (price - result[-1]) * multiplier + result[-1]
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
            window = [x for x in values[i + 1 - period:i + 1] if x is not None]

            if len(window) < period:
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

        window = [x for x in rsi_values[i - STOCH_RSI_PERIOD:i] if x is not None]

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

    signal_line_valid = ema(valid, signal)

    signal_line = []
    idx = 0

    for x in macd_line:
        if x is None:
            signal_line.append(None)
        else:
            signal_line.append(signal_line_valid[idx])
            idx += 1

    histogram = []

    for m, s in zip(macd_line, signal_line):
        if m is None or s is None:
            histogram.append(None)
        else:
            histogram.append(m - s)

    return histogram


def calculate_potential_score(
    entry_close,
    entry_ema,
    k_value,
    d_value,
    macd_now,
    macd_prev,
    volume_ratio,
    current_volume
):
    score = 0

    if entry_close > entry_ema:
        score += 15

    if k_value > d_value:
        score += 15

    if k_value < 20:
        score += 20
    elif k_value < 40:
        score += 15
    elif k_value < 60:
        score += 5

    if macd_now > 0:
        score += 20

    if macd_now > macd_prev:
        score += 15

    if volume_ratio >= 5:
        score += 25
    elif volume_ratio >= 3:
        score += 20
    elif volume_ratio >= 1.5:
        score += 15
    elif volume_ratio >= 1:
        score += 10

    if current_volume >= 100000:
        score += 10
    elif current_volume >= 50000:
        score += 7
    elif current_volume >= 10000:
        score += 5

    if score > 100:
        score = 100

    if score >= 85:
        potential = "انفجارية جدًا 🚀"
        potential_range = "50% - 150%"
    elif score >= 70:
        potential = "قوية 🔥"
        potential_range = "20% - 50%"
    elif score >= 55:
        potential = "متوسطة 📈"
        potential_range = "10% - 20%"
    else:
        potential = "ضعيفة / محدودة ⚠️"
        potential_range = "3% - 8%"

    return score, potential, potential_range


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

        trend_ok = (
            trend_close > trend_ema[-1]
            and trend_macd[-1] > 0
        )

        current_volume = entry_data[-1][4] * entry_data[-1][5]

        avg_volume = 0

        for c in entry_data[-21:-1]:
            avg_volume += c[4] * c[5]

        avg_volume /= 20

        volume_ratio = current_volume / avg_volume if avg_volume > 0 else 0

        entry_ok = (
            entry_close > entry_ema[-1]
            and k[-1] > d[-1]
            and k[-1] < MAX_STOCH_RSI
            and entry_macd[-1] > 0
            and entry_macd[-1] > entry_macd[-2]
            and volume_ratio >= MIN_VOLUME_RATIO
            and current_volume >= MIN_CANDLE_VOLUME_USD
        )

        score, potential, potential_range = calculate_potential_score(
            entry_close=entry_close,
            entry_ema=entry_ema[-1],
            k_value=k[-1],
            d_value=d[-1],
            macd_now=entry_macd[-1],
            macd_prev=entry_macd[-2],
            volume_ratio=volume_ratio,
            current_volume=current_volume
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
                "score": score,
                "potential": potential,
                "potential_range": potential_range
            }

    except Exception as e:
        print(f"{symbol} Error: {e}")

    return None


def signal_message(exchange_name, symbol, data):
    price = data["price"]

    tp1 = price * (1 + TP1_PERCENT / 100)
    tp2 = price * (1 + TP2_PERCENT / 100)
    tp3 = price * (1 + TP3_PERCENT / 100)
    sl = price * (1 - SL_PERCENT / 100)

    return f"""
🟢 MULTI-TIMEFRAME TREND ALERT
━━━━━━━━━━━━━━

🏦 المنصة: {exchange_name}
🪙 العملة: {symbol}
💰 سعر الدخول: {price:.8f}

📈 الاتجاه العام:
• {TREND_TIMEFRAME} صاعد ✅
• {ENTRY_TIMEFRAME} صاعد ✅

📊 Stoch RSI
K: {data["k"]:.2f}
D: {data["d"]:.2f}

📈 MACD Histogram
الحالي: {data["macd"]:.8f}
السابق: {data["macd_prev"]:.8f}

💧 Volume
الحالي: ${data["current_volume"]:,.0f}
المتوسط: ${data["avg_volume"]:,.0f}
Volume Ratio: {data["volume_ratio"]:.2f}x

🔥 قوة الحركة المتوقعة
التقييم: {data["potential"]}
النطاق المحتمل: {data["potential_range"]}
Score: {data["score"]}/100

🎯 Targets
TP1: {tp1:.8f} (+{TP1_PERCENT}%)
TP2: {tp2:.8f} (+{TP2_PERCENT}%)
TP3: {tp3:.8f} (+{TP3_PERCENT}%)

🛑 Stop Loss
{sl:.8f} (-{SL_PERCENT}%)

✅ سيتم إرسال تنبيه عند تحقق كل هدف.
"""


def startup_message():
    return f"""
🤖 بوت توافق الاتجاه اشتغل بنجاح ✅
━━━━━━━━━━━━━━

📈 فريم الاتجاه: {TREND_TIMEFRAME}
📈 فريم الدخول: {ENTRY_TIMEFRAME}

⏱️ الفحص كل: {CHECK_INTERVAL} ثانية

🌐 CoinMarketCap:
Top {CMC_TOP_N} عملة

🎯 شروط الدخول:
• الاتجاه العام صاعد
• الاتجاه الحالي صاعد
• Stoch RSI أقل من {MAX_STOCH_RSI}
• K أعلى من D
• MACD موجب ويتحسن
• Volume Ratio أعلى من {MIN_VOLUME_RATIO}x

🔥 تقييم قوة الحركة:
• Score من 100
• تقدير نطاق الصعود المحتمل
• يعتمد على MACD + Stoch RSI + Volume + EMA

🎯 الأهداف:
• TP1 +{TP1_PERCENT}%
• TP2 +{TP2_PERCENT}%
• TP3 +{TP3_PERCENT}%

🛑 Stop Loss:
-{SL_PERCENT}%

✅ تنبيه عند كل هدف.
"""


def register_signal(exchange_name, symbol, price):
    key = f"{exchange_name}:{symbol}"

    active_signals[key] = {
        "exchange": exchange_name,
        "symbol": symbol,
        "entry": price,
        "tp1": price * (1 + TP1_PERCENT / 100),
        "tp2": price * (1 + TP2_PERCENT / 100),
        "tp3": price * (1 + TP3_PERCENT / 100),
        "sl": price * (1 - SL_PERCENT / 100),
        "tp1_hit": False,
        "tp2_hit": False,
        "tp3_hit": False,
        "sl_hit": False
    }

    save_json(SIGNALS_FILE, active_signals)


def monitor_targets():
    while True:
        try:
            for key, signal in list(active_signals.items()):
                exchange_name = signal["exchange"]
                symbol = signal["symbol"]

                exchange = None

                for name, ex in EXCHANGES:
                    if name == exchange_name:
                        exchange = ex
                        break

                if exchange is None:
                    continue

                ticker = exchange.fetch_ticker(symbol)
                price = ticker["last"]

                if not signal["tp1_hit"] and price >= signal["tp1"]:
                    signal["tp1_hit"] = True
                    send_telegram(
                        f"🎯 TP1 تحقق ✅\n\n🪙 {symbol}\n💰 السعر الحالي: {price:.8f}\n📈 +{TP1_PERCENT}%"
                    )

                if not signal["tp2_hit"] and price >= signal["tp2"]:
                    signal["tp2_hit"] = True
                    send_telegram(
                        f"🎯 TP2 تحقق ✅\n\n🪙 {symbol}\n💰 السعر الحالي: {price:.8f}\n📈 +{TP2_PERCENT}%"
                    )

                if not signal["tp3_hit"] and price >= signal["tp3"]:
                    signal["tp3_hit"] = True
                    send_telegram(
                        f"🎯 TP3 تحقق ✅\n\n🪙 {symbol}\n💰 السعر الحالي: {price:.8f}\n📈 +{TP3_PERCENT}%"
                    )

                if not signal["sl_hit"] and price <= signal["sl"]:
                    signal["sl_hit"] = True
                    send_telegram(
                        f"🛑 STOP LOSS\n\n🪙 {symbol}\n💰 السعر الحالي: {price:.8f}\n📉 -{SL_PERCENT}%"
                    )

                if signal["tp3_hit"] or signal["sl_hit"]:
                    active_signals.pop(key, None)

            save_json(SIGNALS_FILE, active_signals)

        except Exception as e:
            print(f"Monitor Error: {e}")

        time.sleep(60)


def scanner_loop():
    send_telegram(startup_message())

    while True:
        print("Scanning CoinMarketCap...")

        symbols = get_cmc_symbols()
        signals_found = 0

        for exchange_name, exchange in EXCHANGES:
            try:
                exchange.load_markets()

                for base in symbols:
                    symbol = f"{base}/USDT"

                    if symbol not in exchange.markets:
                        continue

                    signal_key = f"{exchange_name}:{symbol}"

                    if signal_key in sent_signals:
                        continue

                    data = analyze(exchange, symbol)

                    if data:
                        send_telegram(signal_message(exchange_name, symbol, data))

                        register_signal(exchange_name, symbol, data["price"])

                        sent_signals[signal_key] = True
                        save_json(SENT_FILE, sent_signals)

                        signals_found += 1
                        time.sleep(2)

            except Exception as e:
                print(f"{exchange_name} Error: {e}")

        print(f"Signals Found: {signals_found}")
        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    threading.Thread(target=scanner_loop, daemon=True).start()
    threading.Thread(target=monitor_targets, daemon=True).start()

    port = int(os.getenv("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
