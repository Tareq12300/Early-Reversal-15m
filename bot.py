"""
🤖 Advanced Self-Learning Crypto Signals Telegram Bot - 1H
"""

import asyncio
import json
import logging
import os
import sqlite3
from datetime import datetime, date

import pytz
import requests
from telegram import Bot
from telegram.constants import ParseMode


SAUDI_TZ = pytz.timezone("Asia/Riyadh")

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHANNEL_ID = os.environ.get("TELEGRAM_CHANNEL_ID")
CMC_API_KEY = os.environ.get("CMC_API_KEY")

CHECK_INTERVAL = int(os.environ.get("CHECK_INTERVAL", "1800"))
CMC_TOP_N = int(os.environ.get("CMC_TOP_N", "800"))
DAILY_SUMMARY_HOUR = int(os.environ.get("DAILY_SUMMARY_HOUR", "0"))

RSI_TIMEFRAME = os.environ.get("RSI_TIMEFRAME", "60")
RSI_PERIOD = int(os.environ.get("RSI_PERIOD", "14"))
MAX_RSI_BUY = float(os.environ.get("MAX_RSI_BUY", "20"))

MIN_CONFIDENCE = int(os.environ.get("MIN_CONFIDENCE", "90"))
MAX_24H_CHANGE = float(os.environ.get("MAX_24H_CHANGE", "15"))
MIN_VOLUME_24H = float(os.environ.get("MIN_VOLUME_24H", "3000000"))
MIN_CURRENT_CANDLE_VOLUME_USD = float(os.environ.get("MIN_CURRENT_CANDLE_VOLUME_USD", "200000"))

HISTORY_FILE = os.environ.get("HISTORY_FILE", "signals_history.json")
DB_FILE = os.environ.get("DB_FILE", "signals_bot.db")

ACCOUNT_BALANCE = float(os.environ.get("ACCOUNT_BALANCE", "1000"))
RISK_PER_TRADE_PCT = float(os.environ.get("RISK_PER_TRADE_PCT", "1"))
BTC_TREND_FILTER_ENABLED = os.environ.get("BTC_TREND_FILTER_ENABLED", "true").lower() == "true"

KUCOIN_KLINE_URL = "https://api.kucoin.com/api/v1/market/candles"
MEXC_KLINE_URL = "https://api.mexc.com/api/v3/klines"
OKX_KLINE_URL = "https://www.okx.com/api/v5/market/candles"


STABLECOINS = {
    "USDT", "USDC", "BUSD", "DAI", "TUSD", "FRAX", "USDP", "GUSD",
    "USDD", "FDUSD", "UST", "PYUSD", "USDE",
    "USD0", "USDX", "USDY", "SUSD", "LUSD", "EUSD",
    "CRVUSD", "MIM", "RLUSD", "EURC", "EURT"
}

MEME = {
    "DOGE", "SHIB", "PEPE", "FLOKI", "BONK", "WIF", "MEME",
    "BABYDOGE", "DOGS", "NEIRO", "POPCAT", "MOG", "TURBO",
    "BRETT", "TOSHI", "LADYS", "SATS", "RATS", "ELON", "KISHU",
    "AKITA", "HOGE", "SAMO", "CAT", "MONKEY", "CORG", "WOOF",
    "PITBULL", "MOON", "SAFEMOON", "TRUMP"
}

GAMING = {
    "AXS", "SLP", "RON", "SAND", "MANA", "ENJ", "CHZ", "GALA",
    "ILV", "YGG", "MBOX", "GMT", "MAGIC", "IMX", "PIXEL",
    "PORTAL", "BEAM", "XAI"
}

GAMBLING = {"DICE", "FUN", "BET", "LOTTO", "JACK", "SPIN", "SLOT"}
PREDICTION = {"POLY", "POLYX", "OMEN", "AUG", "REP", "GNO", "FORE", "OVL", "SX"}
PRIVACY = {"ZEC", "DASH"}

BLACKLIST = STABLECOINS | MEME | GAMING | GAMBLING | PREDICTION | PRIVACY


def init_db():
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT,
            signal_time TEXT,
            entry_price REAL,
            confidence INTEGER,
            ai_score INTEGER,
            macd_strength TEXT,
            volume_spike INTEGER,
            stoch_k REAL,
            stoch_d REAL,
            change_1h REAL,
            change_24h REAL,
            change_7d REAL,
            target1 REAL,
            target2 REAL,
            target3 REAL,
            target4 REAL,
            target5 REAL,
            stop_loss REAL,
            status TEXT DEFAULT 'OPEN',
            result TEXT DEFAULT 'OPEN',
            result_pct REAL DEFAULT 0,
            close_time TEXT
        )
    """)
    conn.commit()
    conn.close()


def db_save_signal(sig: dict):
    try:
        conn = sqlite3.connect(DB_FILE)
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO signals (
                symbol, signal_time, entry_price, confidence, ai_score,
                macd_strength, volume_spike, stoch_k, stoch_d,
                change_1h, change_24h, change_7d,
                target1, target2, target3, target4, target5, stop_loss,
                status, result
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'OPEN', 'OPEN')
        """, (
            sig["symbol"],
            datetime.now(SAUDI_TZ).isoformat(),
            sig["price"],
            sig["confidence"],
            sig.get("ai_score", sig["confidence"]),
            sig.get("macd_strength"),
            1 if sig.get("volume_spike") else 0,
            sig.get("stoch_k"),
            sig.get("stoch_d"),
            sig.get("change_1h"),
            sig.get("change_24h"),
            sig.get("change_7d"),
            sig.get("target1"),
            sig.get("target2"),
            sig.get("target3"),
            sig.get("target4"),
            sig.get("target5"),
            sig.get("stop_loss"),
        ))
        conn.commit()
        conn.close()
    except Exception as e:
        logging.error(f"db_save_signal error: {e}")


def db_update_signal_result(symbol: str, result: str, result_pct: float):
    try:
        conn = sqlite3.connect(DB_FILE)
        cur = conn.cursor()
        cur.execute("""
            SELECT id FROM signals
            WHERE symbol = ? AND status = 'OPEN'
            ORDER BY id DESC
            LIMIT 1
        """, (symbol,))
        row = cur.fetchone()

        if row:
            signal_id = row[0]
            status = "CLOSED" if result in ("TP5", "SL") else "OPEN"
            cur.execute("""
                UPDATE signals
                SET result = ?, result_pct = ?, close_time = ?, status = ?
                WHERE id = ?
            """, (
                result,
                round(result_pct, 2),
                datetime.now(SAUDI_TZ).isoformat(),
                status,
                signal_id,
            ))

        conn.commit()
        conn.close()
    except Exception as e:
        logging.error(f"db_update_signal_result error: {e}")


def db_get_today_winrate() -> dict:
    try:
        today_start = datetime.now(SAUDI_TZ).replace(
            hour=0, minute=0, second=0, microsecond=0
        ).isoformat()

        conn = sqlite3.connect(DB_FILE)
        cur = conn.cursor()
        cur.execute("""
            SELECT result, result_pct
            FROM signals
            WHERE result IN ('TP1','TP2','TP3','TP4','TP5','SL')
            AND signal_time >= ?
        """, (today_start,))
        rows = cur.fetchall()
        conn.close()

        if not rows:
            return {"total": 0, "wins": 0, "losses": 0, "win_rate": 0.0, "avg_result": 0.0}

        wins = [r for r in rows if r[0] != "SL"]
        losses = [r for r in rows if r[0] == "SL"]
        avg_result = sum(float(r[1] or 0) for r in rows) / len(rows)

        return {
            "total": len(rows),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": (len(wins) / len(rows)) * 100,
            "avg_result": avg_result,
        }
    except Exception as e:
        logging.error(f"db_get_today_winrate error: {e}")
        return {"total": 0, "wins": 0, "losses": 0, "win_rate": 0.0, "avg_result": 0.0}


def calculate_position_size(entry_price: float, stop_loss: float) -> dict:
    risk_amount = ACCOUNT_BALANCE * (RISK_PER_TRADE_PCT / 100)
    risk_per_unit = abs(entry_price - stop_loss)

    if risk_per_unit <= 0:
        return {"risk_amount": risk_amount, "position_usd": 0, "quantity": 0}

    quantity = risk_amount / risk_per_unit
    position_usd = quantity * entry_price
    position_pct = (position_usd / ACCOUNT_BALANCE) * 100 if ACCOUNT_BALANCE > 0 else 0

    return {
        "risk_amount": round(risk_amount, 2),
        "position_usd": round(position_usd, 2),
        "position_pct": round(position_pct, 1),
        "quantity": round(quantity, 6),
    }


def calculate_ai_ranking_score(score, macd_strength, volume_spike, btc_filter, learning_adjustment, change_1h, change_24h) -> int:
    ai_score = 50 + score * 4

    if macd_strength in ["قوي", "قوي جدًا"]:
        ai_score += 8
    elif macd_strength == "متوسط":
        ai_score += 4
    elif macd_strength in ["ضعيف", "ضعيف متراجع"]:
        ai_score -= 8

    if volume_spike:
        ai_score += 8

    ai_score += learning_adjustment

    if btc_filter.get("status") == "bullish":
        ai_score += 6
    elif btc_filter.get("status") == "weak":
        ai_score -= 8
    elif btc_filter.get("status") == "bearish":
        ai_score -= 15

    if change_1h > 4:
        ai_score -= 5
    if change_24h > 10:
        ai_score -= 8

    return int(max(0, min(ai_score, 100)))


class DailyTracker:
    def __init__(self):
        self.reset()

    def reset(self):
        self.date = date.today()
        self.buy_signals = []
        self.scans = 0
        self.coins_scanned = 0
        self.summary_sent = False
        self.daily_profit_pct = 0.0

    def add_signal(self, sig: dict):
        self.buy_signals.append({
            "symbol": sig["symbol"],
            "price": sig["price"],
            "confidence": sig["confidence"],
            "change_24h": sig["change_24h"],
            "stoch_k": sig.get("stoch_k"),
            "stoch_d": sig.get("stoch_d"),
            "macd_strength": sig.get("macd_strength"),
            "time": datetime.now(SAUDI_TZ).strftime("%H:%M"),
            "target1": sig["target1"],
            "stop_loss": sig["stop_loss"],
            "result_pct": 0,
        })

    def new_day(self) -> bool:
        return date.today() > self.date

    @property
    def total_signals(self):
        return len(self.buy_signals)

    @property
    def top_buy(self):
        return sorted(self.buy_signals, key=lambda x: x["confidence"], reverse=True)[:5]


tracker = DailyTracker()
active_signals: dict = {}


def add_daily_profit(result_pct: float):
    tracker.daily_profit_pct += result_pct


def load_history() -> list:
    try:
        if not os.path.exists(HISTORY_FILE):
            return []
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logging.error(f"load_history error: {e}")
        return []


def save_history(history: list):
    try:
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(history, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logging.error(f"save_history error: {e}")


def save_new_signal_to_history(sig: dict):
    history = load_history()

    history.append({
        "symbol": sig["symbol"],
        "time": datetime.now(SAUDI_TZ).isoformat(),
        "price": sig["price"],
        "confidence": sig["confidence"],
        "macd_strength": sig.get("macd_strength"),
        "volume_spike": sig.get("volume_spike"),
        "stoch_k": sig.get("stoch_k"),
        "stoch_d": sig.get("stoch_d"),
        "change_1h": sig.get("change_1h"),
        "change_24h": sig.get("change_24h"),
        "change_7d": sig.get("change_7d"),
        "current_volume_usd": sig.get("current_volume_usd"),
        "volume_ratio": sig.get("volume_ratio"),
        "result": "OPEN",
        "result_pct": 0,
    })

    history = history[-500:]
    save_history(history)


def update_signal_result_in_history(symbol: str, result: str, result_pct: float):
    history = load_history()

    for item in reversed(history):
        if item.get("symbol") == symbol and item.get("result") == "OPEN":
            item["result"] = result
            item["result_pct"] = round(result_pct, 2)
            item["closed_time"] = datetime.now(SAUDI_TZ).isoformat()
            break

    save_history(history)
    db_update_signal_result(symbol, result, result_pct)


def get_learning_adjustment(sig: dict) -> dict:
    history = load_history()

    closed = [
        h for h in history
        if h.get("result") in ["TP1", "TP2", "TP3", "TP4", "TP5", "SL"]
    ]

    if len(closed) < 10:
        return {"adjustment": 0, "note": "لا توجد بيانات تعلم كافية بعد"}

    macd_strength = sig.get("macd_strength")
    volume_spike = sig.get("volume_spike")

    similar = [
        h for h in closed
        if h.get("macd_strength") == macd_strength
        and h.get("volume_spike") == volume_spike
    ]

    if len(similar) < 5:
        return {"adjustment": 0, "note": "بيانات التعلم للحالة المشابهة غير كافية"}

    recent = similar[-30:]
    wins = [h for h in recent if h.get("result") in ["TP1", "TP2", "TP3", "TP4", "TP5"]]
    win_rate = len(wins) / len(recent)

    if win_rate >= 0.70:
        return {"adjustment": 8, "note": f"هذا النمط ناجح سابقًا بنسبة {win_rate * 100:.0f}% 🔥"}
    if win_rate >= 0.60:
        return {"adjustment": 5, "note": f"هذا النمط جيد سابقًا بنسبة {win_rate * 100:.0f}% ✅"}
    if win_rate <= 0.35:
        return {"adjustment": -10, "note": f"هذا النمط ضعيف سابقًا بنسبة نجاح {win_rate * 100:.0f}% ⚠️"}
    if win_rate <= 0.45:
        return {"adjustment": -5, "note": f"هذا النمط متوسط/ضعيف سابقًا بنسبة نجاح {win_rate * 100:.0f}%"}

    return {"adjustment": 0, "note": f"أداء هذا النمط متوازن بنسبة نجاح {win_rate * 100:.0f}%"}


def register_active_signal(sig: dict):
    active_signals[sig["symbol"]] = {
        **sig,
        "signal_time": datetime.now(SAUDI_TZ).isoformat(),
        "tp1_hit": False,
        "tp2_hit": False,
        "tp3_hit": False,
        "tp4_hit": False,
        "tp5_hit": False,
        "sl_hit": False,
    }


def check_tp_updates(symbol: str, current_price: float) -> list:
    if symbol not in active_signals:
        return []

    sig = active_signals[symbol]

    if sig.get("sl_hit"):
        return []

    updates = []

    if not sig["tp1_hit"] and current_price >= sig["target1"]:
        sig["tp1_hit"] = True
        pct = ((sig["target1"] - sig["price"]) / sig["price"]) * 100
        updates.append(("TP1", sig["target1"], pct))
        update_signal_result_in_history(symbol, "TP1", pct)
        add_daily_profit(pct / 5)

    if not sig["tp2_hit"] and current_price >= sig["target2"]:
        sig["tp2_hit"] = True
        pct = ((sig["target2"] - sig["price"]) / sig["price"]) * 100
        updates.append(("TP2", sig["target2"], pct))
        update_signal_result_in_history(symbol, "TP2", pct)
        add_daily_profit(pct / 5)

    if not sig["tp3_hit"] and current_price >= sig["target3"]:
        sig["tp3_hit"] = True
        pct = ((sig["target3"] - sig["price"]) / sig["price"]) * 100
        updates.append(("TP3", sig["target3"], pct))
        update_signal_result_in_history(symbol, "TP3", pct)
        add_daily_profit(pct / 5)

    if not sig["tp4_hit"] and current_price >= sig["target4"]:
        sig["tp4_hit"] = True
        pct = ((sig["target4"] - sig["price"]) / sig["price"]) * 100
        updates.append(("TP4", sig["target4"], pct))
        update_signal_result_in_history(symbol, "TP4", pct)
        add_daily_profit(pct / 5)

    if not sig["tp5_hit"] and current_price >= sig["target5"]:
        sig["tp5_hit"] = True
        pct = ((sig["target5"] - sig["price"]) / sig["price"]) * 100
        updates.append(("TP5", sig["target5"], pct))
        update_signal_result_in_history(symbol, "TP5", pct)
        add_daily_profit(pct / 5)

    if current_price <= sig["stop_loss"]:
        sig["sl_hit"] = True
        pct = ((sig["stop_loss"] - sig["price"]) / sig["price"]) * 100
        updates.append(("SL", sig["stop_loss"], pct))
        update_signal_result_in_history(symbol, "SL", pct)
        add_daily_profit(pct)
        del active_signals[symbol]
        return updates

    if (
        sig.get("tp1_hit")
        and sig.get("tp2_hit")
        and sig.get("tp3_hit")
        and sig.get("tp4_hit")
        and sig.get("tp5_hit")
    ):
        del active_signals[symbol]

    return updates


def get_top_coins_from_cmc() -> list:
    url = "https://pro-api.coinmarketcap.com/v1/cryptocurrency/listings/latest"
    headers = {
        "Accepts": "application/json",
        "X-CMC_PRO_API_KEY": CMC_API_KEY,
    }
    params = {
        "start": 1,
        "limit": CMC_TOP_N,
        "convert": "USD",
        "sort": "market_cap",
    }

    try:
        response = requests.get(url, headers=headers, params=params, timeout=20)
        response.raise_for_status()
        data = response.json().get("data", [])
        coins = []

        for c in data:
            symbol = c.get("symbol", "").upper()
            quote = c.get("quote", {}).get("USD", {})

            if not symbol or symbol in BLACKLIST:
                continue

            price = quote.get("price")
            change_1h = quote.get("percent_change_1h")
            change_24h = quote.get("percent_change_24h")
            change_7d = quote.get("percent_change_7d")
            volume_24h = quote.get("volume_24h")
            market_cap = quote.get("market_cap")

            if price is None or change_24h is None or volume_24h is None:
                continue

            coins.append({
                "symbol": symbol,
                "name": c.get("name", symbol),
                "price": float(price),
                "change_1h": float(change_1h or 0),
                "change_24h": float(change_24h or 0),
                "change_7d": float(change_7d or 0),
                "volume_24h": float(volume_24h or 0),
                "market_cap": float(market_cap or 0),
            })

        print(f"📥 CMC: {len(data)} عملة | بعد الفلترة: {len(coins)} عملة")
        return coins

    except Exception as e:
        logging.error(f"CMC Error: {e}")
        return []


def get_kucoin_market_data(symbol: str):
    params = {
        "symbol": f"{symbol}-USDT",
        "type": "1hour",  # ✅ تم التغيير من 4hour إلى 1hour
    }

    try:
        response = requests.get(KUCOIN_KLINE_URL, params=params, timeout=15)
        response.raise_for_status()
        payload = response.json()

        if payload.get("code") != "200000":
            return None

        rows = payload.get("data", [])
        if not rows:
            return None

        rows = list(reversed(rows))
        closes = [float(row[2]) for row in rows]
        volumes = [float(row[5]) for row in rows]

        return {"closes": closes, "volumes": volumes}

    except Exception as e:
        logging.warning(f"KuCoin failed for {symbol}: {e}")
        return None


def get_mexc_market_data(symbol: str):
    params = {
        "symbol": f"{symbol}USDT",
        "interval": "1h",  # ✅ تم التغيير من 4h إلى 1h
        "limit": 200,
    }

    try:
        response = requests.get(MEXC_KLINE_URL, params=params, timeout=15)
        response.raise_for_status()
        rows = response.json()

        if not rows or not isinstance(rows, list):
            return None

        closes = []
        volumes = []

        for row in rows:
            closes.append(float(row[4]))
            volumes.append(float(row[5]))

        return {"closes": closes, "volumes": volumes}

    except Exception as e:
        logging.info(f"MEXC unavailable for {symbol}: {e}")
        return None


def get_okx_market_data(symbol: str):
    params = {
        "instId": f"{symbol}-USDT",
        "bar": "1H",  # ✅ تم التغيير من 4H إلى 1H
        "limit": "200",
    }

    try:
        response = requests.get(OKX_KLINE_URL, params=params, timeout=15)
        response.raise_for_status()
        payload = response.json()

        if payload.get("code") != "0":
            return None

        rows = payload.get("data", [])
        if not rows or not isinstance(rows, list):
            return None

        rows = list(reversed(rows))
        closes = [float(row[4]) for row in rows]
        volumes = [float(row[5]) for row in rows]

        return {"closes": closes, "volumes": volumes}

    except Exception as e:
        logging.info(f"OKX unavailable for {symbol}: {e}")
        return None


def calculate_stoch_rsi(closes, rsi_period=14, stoch_period=14, smooth_k=3, smooth_d=3):
    min_len = rsi_period + stoch_period + smooth_k + smooth_d + 10

    if len(closes) < min_len:
        return None

    gains = []
    losses = []

    for i in range(1, len(closes)):
        diff = closes[i] - closes[i - 1]
        gains.append(max(diff, 0))
        losses.append(max(-diff, 0))

    avg_gain = sum(gains[:rsi_period]) / rsi_period
    avg_loss = sum(losses[:rsi_period]) / rsi_period

    rsi_values = []

    for i in range(rsi_period, len(gains)):
        avg_gain = (avg_gain * (rsi_period - 1) + gains[i]) / rsi_period
        avg_loss = (avg_loss * (rsi_period - 1) + losses[i]) / rsi_period

        if avg_loss == 0:
            rsi_values.append(100.0)
        else:
            rs = avg_gain / avg_loss
            rsi_values.append(100 - (100 / (1 + rs)))

    raw_k = []

    for i in range(stoch_period - 1, len(rsi_values)):
        window = rsi_values[i - stoch_period + 1: i + 1]
        low = min(window)
        high = max(window)

        if high == low:
            raw_k.append(50.0)
        else:
            raw_k.append((rsi_values[i] - low) / (high - low) * 100)

    if len(raw_k) < smooth_k:
        return None

    k_values = []

    for i in range(smooth_k - 1, len(raw_k)):
        k_values.append(sum(raw_k[i - smooth_k + 1: i + 1]) / smooth_k)

    if len(k_values) < smooth_d:
        return None

    d_values = []

    for i in range(smooth_d - 1, len(k_values)):
        d_values.append(sum(k_values[i - smooth_d + 1: i + 1]) / smooth_d)

    return {
        "k": round(k_values[-1], 2),
        "d": round(d_values[-1], 2),
    }


def _ema_series(data: list, period: int) -> list:
    if len(data) < period:
        return []
    k = 2 / (period + 1)
    val = sum(data[:period]) / period
    series = [val]
    for p in data[period:]:
        val = p * k + val * (1 - k)
        series.append(val)
    return series


def calculate_macd(prices: list):
    if len(prices) < 40:
        return None

    ema12_s = _ema_series(prices, 12)
    ema26_s = _ema_series(prices, 26)

    if not ema12_s or not ema26_s:
        return None

    offset = len(ema12_s) - len(ema26_s)
    macd_series = [
        ema12_s[i + offset] - ema26_s[i]
        for i in range(len(ema26_s))
    ]

    if len(macd_series) < 9:
        return None

    signal_series = _ema_series(macd_series, 9)

    if len(signal_series) < 2:
        return None

    macd_now = macd_series[-1]
    macd_prev = macd_series[-2]
    sig_now = signal_series[-1]
    sig_prev = signal_series[-2]

    hist_now = macd_now - sig_now
    hist_prev = macd_prev - sig_prev

    if hist_now >= 0:
        color = "rising_green" if hist_now > hist_prev else "falling_green"
    else:
        color = "rising_red" if hist_now > hist_prev else "falling_red"

    direction = "rising" if hist_now > hist_prev else "falling"

    switched_to_falling = hist_prev >= 0 and hist_now < 0
    switched_to_rising = hist_prev <= 0 and hist_now > 0

    return {
        "macd": round(macd_now, 10),
        "signal": round(sig_now, 10),
        "histogram": round(hist_now, 10),
        "histogram_prev": round(hist_prev, 10),
        "direction": direction,
        "color": color,
        "switched_to_falling": switched_to_falling,
        "switched_to_rising": switched_to_rising,
    }


def detect_volume_spike(volumes: list, price: float) -> dict:
    if len(volumes) < 12:
        return {
            "spike": False,
            "ratio": 1.0,
            "current_volume_usd": 0,
        }

    recent = volumes[-1]
    avg = sum(volumes[-11:-1]) / 10

    current_volume_usd = recent * price

    if avg == 0:
        return {
            "spike": False,
            "ratio": 1.0,
            "current_volume_usd": current_volume_usd,
        }

    ratio = recent / avg

    return {
        "spike": ratio > 1.8,
        "ratio": round(ratio, 2),
        "current_volume_usd": current_volume_usd,
    }


def classify_macd_histogram(hist, price, direction="rising", color="") -> dict:
    if hist is None or price <= 0:
        return {"label": "غير متوفر", "emoji": "⚪", "score": 0, "ratio": 0}

    ratio = hist / price

    if hist <= 0:
        return {"label": "سلبي", "emoji": "🔴", "score": -2, "ratio": ratio}

    if direction == "falling":
        return {"label": "ضعيف متراجع", "emoji": "⚠️", "score": 0, "ratio": ratio}

    if ratio >= 0.001:
        return {"label": "قوي جدًا", "emoji": "🔥", "score": 4, "ratio": ratio}
    if ratio >= 0.0005:
        return {"label": "قوي", "emoji": "🟢", "score": 3, "ratio": ratio}
    if ratio >= 0.00015:
        return {"label": "متوسط", "emoji": "🟡", "score": 2, "ratio": ratio}

    return {"label": "ضعيف", "emoji": "⚠️", "score": 1, "ratio": ratio}


def calculate_sma(values: list, period: int):
    if len(values) < period:
        return None
    return sum(values[-period:]) / period


def get_btc_trend_filter() -> dict:
    if not BTC_TREND_FILTER_ENABLED:
        return {
            "allow": True,
            "status": "disabled",
            "note": "فلتر BTC غير مفعّل",
            "btc_price": 0,
        }

    try:
        market_data = get_kucoin_market_data("BTC")
        if not market_data:
            market_data = get_mexc_market_data("BTC")
        if not market_data:
            market_data = get_okx_market_data("BTC")

        if not market_data:
            return {
                "allow": True,
                "status": "unknown",
                "note": "تعذر قراءة اتجاه BTC",
                "btc_price": 0,
            }

        closes = market_data["closes"]
        btc_price = closes[-1]
        change_1h = ((closes[-1] - closes[-2]) / closes[-2]) * 100 if len(closes) >= 2 else 0

        sma50 = calculate_sma(closes, 50)
        sma200 = calculate_sma(closes, 200)

        if sma50 is not None and sma200 is not None:
            if btc_price > sma50 > sma200 and change_1h > -2:
                return {
                    "allow": True,
                    "status": "bullish",
                    "note": "BTC داعم للسوق ✅ (SMA50+200)",
                    "btc_price": btc_price,
                }
            if btc_price < sma50 and sma50 < sma200:
                return {
                    "allow": False,
                    "status": "bearish",
                    "note": "BTC هابط بقوة — تم منع الإشارة ❌",
                    "btc_price": btc_price,
                }

        elif sma50 is not None:
            if btc_price > sma50 and change_1h > -2:
                return {
                    "allow": True,
                    "status": "bullish",
                    "note": "BTC فوق SMA50 ✅ (وضع مختصر)",
                    "btc_price": btc_price,
                }
            if btc_price < sma50 and change_1h < -1:
                return {
                    "allow": False,
                    "status": "bearish",
                    "note": "BTC تحت SMA50 وهابط ❌",
                    "btc_price": btc_price,
                }

        else:
            if change_1h <= -3:
                return {
                    "allow": False,
                    "status": "weak",
                    "note": f"BTC يهبط {change_1h:.1f}% على 1H ⚠️",
                    "btc_price": btc_price,
                }
            return {
                "allow": True,
                "status": "neutral",
                "note": f"BTC محايد (بيانات محدودة) 1H: {change_1h:+.1f}%",
                "btc_price": btc_price,
            }

        if change_1h <= -3:
            return {
                "allow": False,
                "status": "weak",
                "note": f"BTC يهبط بقوة على 1H ({change_1h:.1f}%) ⚠️",
                "btc_price": btc_price,
            }

        return {
            "allow": True,
            "status": "neutral",
            "note": f"BTC محايد | 1H: {change_1h:+.1f}%",
            "btc_price": btc_price,
        }

    except Exception as e:
        logging.warning(f"BTC filter error: {e}")
        return {
            "allow": True,
            "status": "unknown",
            "note": "تعذر قراءة اتجاه BTC",
            "btc_price": 0,
        }


def analyze_signal(data: dict, btc_filter: dict | None = None):
    price = data["price"]
    change_1h = data["change_1h"]
    change_24h = data["change_24h"]
    change_7d = data["change_7d"]
    volume_24h = data["volume_24h"]

    rsi_value = data.get("rsi")
    macd_data = data.get("macd_data")
    volume_spike = data.get("volume_spike")
    current_volume_usd = float(data.get("current_volume_usd", 0))
    btc_filter = btc_filter or {
        "allow": True,
        "status": "unknown",
        "note": "BTC غير متوفر",
        "btc_price": 0,
    }

    if not btc_filter.get("allow", True):
        return None

    if rsi_value is None or macd_data is None:
        return None

    stoch_k = rsi_value.get("k")
    stoch_d = rsi_value.get("d")

    if stoch_k is None or stoch_d is None:
        return None

    if stoch_k >= MAX_RSI_BUY or stoch_d >= MAX_RSI_BUY:
        return None

    if change_24h > MAX_24H_CHANGE:
        return None

    if volume_24h < MIN_VOLUME_24H:
        return None

    if current_volume_usd < MIN_CURRENT_CANDLE_VOLUME_USD:
        return None

    score = 0
    reasons = []

    if stoch_k < 10 and stoch_d < 10:
        score += 4
        reasons.append(f"Stoch RSI K=`{stoch_k}` D=`{stoch_d}` — تشبع بيع قوي جدًا 🔥")
    elif stoch_k < 15:
        score += 3
        reasons.append(f"Stoch RSI K=`{stoch_k}` D=`{stoch_d}` — تشبع بيع قوي 🔥")
    else:
        score += 2
        reasons.append(f"Stoch RSI K=`{stoch_k}` D=`{stoch_d}` — منطقة تشبع بيع")

    if stoch_k <= stoch_d:
        return None

    score += 2
    reasons.append("Stoch RSI: K تجاوز D — إشارة ارتداد 📈")

    macd_hist = macd_data["histogram"]
    macd_direction = macd_data.get("direction", "rising")
    macd_color = macd_data.get("color", "")
    macd_strength = classify_macd_histogram(macd_hist, price, macd_direction, macd_color)

    if macd_hist <= 0:
        return None

    if macd_direction != "rising":
        return None

    if macd_strength["label"] != "قوي جدًا":
        return None

    if not macd_data.get("switched_to_rising"):
        return None

    score += macd_strength["score"]
    reasons.append(f"MACD Histogram إيجابي متصاعد — {macd_strength['label']} {macd_strength['emoji']}")

    score += 1
    reasons.append("MACD تحول للإيجابية للتو 🚀")

    if volume_spike:
        score += 2
        reasons.append("Volume Spike قوي 🔥")

    if -1.5 <= change_1h <= 2:
        score += 1
        reasons.append("الحركة الساعية غير متضخمة")
    elif change_1h < -2:
        score += 1
        reasons.append("هبوط قصير قد يعطي ارتداد")

    if -10 <= change_24h <= 4:
        score += 2
        reasons.append("الحركة اليومية مناسبة للدخول المبكر")
    elif 4 < change_24h <= 8:
        score += 1
        reasons.append("ارتفاع يومي متوسط")
    elif change_24h < -15:
        score -= 1
        reasons.append("هبوط يومي قوي يحتاج حذر")

    if -25 <= change_7d <= 18:
        score += 1
        reasons.append("الاتجاه الأسبوعي غير متضخم")
    elif change_7d > 30:
        score -= 2
        reasons.append("صعود أسبوعي متضخم")

    if score < 3:
        return None

    confidence = min(55 + score * 5, 90)

    if not volume_spike:
        confidence = min(confidence, 78)

    if volume_spike and macd_strength["label"] == "قوي جدًا":
        confidence = min(confidence + 5, 95)

    learning = get_learning_adjustment({
        "macd_strength": macd_strength["label"],
        "volume_spike": volume_spike,
    })

    confidence = confidence + learning["adjustment"]
    confidence = max(50, min(confidence, 95))

    ai_score = calculate_ai_ranking_score(
        score=score,
        macd_strength=macd_strength["label"],
        volume_spike=volume_spike,
        btc_filter=btc_filter,
        learning_adjustment=learning["adjustment"],
        change_1h=change_1h,
        change_24h=change_24h,
    )

    confidence = int(round((confidence * 0.65) + (ai_score * 0.35)))

    if confidence < MIN_CONFIDENCE:
        return None

    target1 = price * 1.02
    target2 = price * 1.04
    target3 = price * 1.07
    target4 = price * 1.10
    target5 = price * 1.15
    stop_loss = price * 0.965
    position = calculate_position_size(price, stop_loss)

    return {
        "symbol": data["symbol"],
        "name": data["name"],
        "type": "BUY",
        "price": price,
        "target1": round(target1, 8),
        "target2": round(target2, 8),
        "target3": round(target3, 8),
        "target4": round(target4, 8),
        "target5": round(target5, 8),
        "stop_loss": round(stop_loss, 8),
        "confidence": int(confidence),
        "ai_score": ai_score,
        "position_usd": position["position_usd"],
        "position_pct": position["position_pct"],
        "position_qty": position["quantity"],
        "risk_amount": position["risk_amount"],
        "btc_trend_note": btc_filter.get("note", "-"),
        "stoch_k": stoch_k,
        "stoch_d": stoch_d,
        "macd_histogram": macd_hist,
        "macd_histogram_prev": macd_data.get("histogram_prev"),
        "macd_direction": macd_direction,
        "macd_color": macd_color,
        "macd_strength": macd_strength["label"],
        "macd_emoji": macd_strength["emoji"],
        "macd_ratio": macd_strength["ratio"],
        "macd_switched_rising": macd_data.get("switched_to_rising", False),
        "volume_spike": volume_spike,
        "change_1h": change_1h,
        "change_24h": change_24h,
        "change_7d": change_7d,
        "volume_24h": volume_24h,
        "volume_ratio": data.get("volume_ratio", 1.0),
        "current_volume_usd": data.get("current_volume_usd", 0),
        "learning_note": learning["note"],
        "learning_adjustment": learning["adjustment"],
        "reasons": reasons[:8],
    }


def fp(price: float) -> str:
    if price is None:
        return "-"
    if price < 0.0001:
        return f"{price:.8f}"
    if price < 0.01:
        return f"{price:.6f}"
    if price < 1:
        return f"{price:.4f}"
    if price < 100:
        return f"{price:.3f}"
    return f"{price:,.2f}"


def format_big_number(num: float) -> str:
    if num is None:
        return "0"
    if num >= 1_000_000_000:
        return f"{num / 1_000_000_000:.2f}B"
    if num >= 1_000_000:
        return f"{num / 1_000_000:.2f}M"
    if num >= 1_000:
        return f"{num / 1_000:.2f}K"
    return f"{num:.0f}"


def format_signal_message(sig: dict) -> str:
    reasons = "\n".join(f"   • {r}" for r in sig["reasons"])
    ts = datetime.now(SAUDI_TZ).strftime("%H:%M | %d/%m/%Y")
    spike_text = "نعم 🔥" if sig.get("volume_spike") else "لا"
    dir_text = "⬆️ متصاعد" if sig.get("macd_direction") == "rising" else "⬇️ متراجع"

    return (
        f"🟢 *إشارة شراء 1H | {sig['symbol']}/USDT*\n"  # ✅ تم التغيير من 4H إلى 1H
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"⏰ *الوقت:* `{ts}`\n"
        f"💰 *سعر الدخول:* `{fp(sig['price'])} $`\n\n"
        f"📉 *Stoch RSI K:* `{sig.get('stoch_k')}`\n"
        f"📉 *Stoch RSI D:* `{sig.get('stoch_d')}`\n"
        f"📈 *MACD Hist:* `{sig.get('macd_histogram')}` — *{sig.get('macd_strength')}* {sig.get('macd_emoji')} {dir_text}\n"
        f"🔥 *Volume Spike:* `{spike_text}`\n\n"
        f"📈 *التغيير 1h:* `{sig['change_1h']:+.2f}%`\n"
        f"📊 *التغيير 24h:* `{sig['change_24h']:+.2f}%`\n"
        f"📆 *التغيير 7d:* `{sig['change_7d']:+.2f}%`\n"
        f"💧 *حجم التداول:* `{format_big_number(sig['volume_24h'])} $`\n"
        f"📊 *معدل الفوليوم:* `{sig.get('volume_ratio', 1.0):.2f}x | {format_big_number(sig.get('current_volume_usd', 0))} $`\n"
        f"₿ *فلتر BTC:* `{sig.get('btc_trend_note', '-')}`\n\n"
        f"🎯 *الأهداف:*\n"
        f"   ├ TP1: `{fp(sig['target1'])} $` `(+2%)`\n"
        f"   ├ TP2: `{fp(sig['target2'])} $` `(+4%)`\n"
        f"   ├ TP3: `{fp(sig['target3'])} $` `(+7%)`\n"
        f"   ├ TP4: `{fp(sig['target4'])} $` `(+10%)`\n"
        f"   └ TP5: `{fp(sig['target5'])} $` `(+15%)`\n\n"
        f"🛑 *وقف الخسارة:* `{fp(sig['stop_loss'])} $`\n\n"
        f"📌 *أسباب الإشارة:*\n{reasons}\n\n"
        f"🧠 *الثقة:* `{sig['confidence']}%`\n"
        f"🤖 *AI Ranking:* `{sig.get('ai_score', sig['confidence'])}/100`\n"
        f"🤖 *التعلم الذاتي:* `{sig.get('learning_note', '-')}`\n"
        f"━━━━━━━━━━━━━━━━━━━━"
    )


def format_duration(start_iso: str | None) -> str:
    if not start_iso:
        return "-"
    try:
        now = datetime.now(SAUDI_TZ)
        start_dt = datetime.fromisoformat(start_iso)
        diff = now - start_dt
        total_minutes = int(diff.total_seconds() // 60)
        days = total_minutes // 1440
        hours = (total_minutes % 1440) // 60
        minutes = total_minutes % 60
        parts = []
        if days > 0:
            parts.append(f"{days} يوم")
        if hours > 0:
            parts.append(f"{hours} ساعة")
        if minutes > 0:
            parts.append(f"{minutes} دقيقة")
        return " و ".join(parts) if parts else "أقل من دقيقة"
    except Exception:
        return "-"


def format_tp_update_message(sig: dict, updates: list) -> str:
    ts = datetime.now(SAUDI_TZ)
    duration_text = format_duration(sig.get("signal_time"))
    lines = []

    for tp_name, tp_price, pct in updates:
        if tp_name == "SL":
            lines.append(
                f"🔴 *وقف الخسارة | {sig['symbol']}/USDT*\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"⏰ *الوقت:* `{ts.strftime('%H:%M | %d/%m/%Y')}`\n"
                f"💰 *سعر الدخول:* `{fp(sig['price'])} $`\n"
                f"⏳ *مدة الصفقة:* `{duration_text}`\n"
                f"🛑 *وقف الخسارة تحقق عند:* `{fp(tp_price)} $` `({pct:+.2f}%)`\n"
                f"━━━━━━━━━━━━━━━━━━━━"
            )
        else:
            tp_num = tp_name[-1]
            lines.append(
                f"✅ *تحقق {tp_name} | {sig['symbol']}/USDT*\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"⏰ *الوقت:* `{ts.strftime('%H:%M | %d/%m/%Y')}`\n"
                f"💰 *سعر الدخول:* `{fp(sig['price'])} $`\n"
                f"⏳ *مدة تحقيق الهدف:* `{duration_text}`\n"
                f"🎯 *الهدف {tp_num} تحقق عند:* `{fp(tp_price)} $` ✅\n"
                f"📈 *نسبة الربح:* `{pct:+.2f}%`\n"
                f"━━━━━━━━━━━━━━━━━━━━"
            )

    return "\n\n".join(lines)


def format_daily_summary() -> str:
    today = tracker.date.strftime("%d/%m/%Y")
    total = tracker.total_signals
    avg_conf = 0

    if total:
        avg_conf = round(sum(s["confidence"] for s in tracker.buy_signals) / total, 1)

    stats = db_get_today_winrate()

    lines = [
        f"📋 *ملخص يوم {today}*",
        "━━━━━━━━━━━━━━━━━━━━",
        f"🔍 عمليات فحص: `{tracker.scans}`",
        f"💹 عملات محللة: `{tracker.coins_scanned}`",
        f"📨 إجمالي الإشارات: `{total}`",
        f"🧠 متوسط الثقة: `{avg_conf}%`",
        f"💰 مجموع الربح/الخسارة اليومي: `{tracker.daily_profit_pct:+.2f}%`",
        f"📊 Win Rate اليوم: `{stats['win_rate']:.1f}%`",
        f"✅ رابحة: `{stats['wins']}` | 🔴 خاسرة: `{stats['losses']}` | إجمالي مُغلقة: `{stats['total']}`",
        f"📈 متوسط النتيجة اليوم: `{stats['avg_result']:+.2f}%`",
        "",
    ]

    if tracker.top_buy:
        lines.append("🟢 *أقوى إشارات الشراء:*")
        for i, s in enumerate(tracker.top_buy, 1):
            lines.append(
                f"{i}. `{s['symbol']}` — MACD `{s.get('macd_strength')}` | "
                f"StochK `{s.get('stoch_k')}` | دخول `{fp(s['price'])}$` | "
                f"هدف `{fp(s['target1'])}$` | ثقة `{s['confidence']}%`"
            )
        lines.append("")

    if total == 0:
        lines.append("😴 لا توجد إشارات قوية اليوم")

    lines.append("━━━━━━━━━━━━━━━━━━━━")
    return "\n".join(lines)


async def send_signal(bot: Bot, sig: dict):
    try:
        await bot.send_message(
            chat_id=TELEGRAM_CHANNEL_ID,
            text=format_signal_message(sig),
            parse_mode=ParseMode.MARKDOWN,
        )
        tracker.add_signal(sig)
        register_active_signal(sig)
        save_new_signal_to_history(sig)
        db_save_signal(sig)
        print(
            f"✅ {sig['symbol']} BUY | MACD {sig.get('macd_strength')} {sig.get('macd_direction')} | "
            f"StochK {sig.get('stoch_k')} | Volume {format_big_number(sig.get('current_volume_usd', 0))}$ | "
            f"ثقة {sig['confidence']}%"
        )
    except Exception as e:
        logging.error(f"send_signal {sig['symbol']}: {e}")


async def send_daily_summary(bot: Bot):
    try:
        await bot.send_message(
            chat_id=TELEGRAM_CHANNEL_ID,
            text=format_daily_summary(),
            parse_mode=ParseMode.MARKDOWN,
        )
        tracker.summary_sent = True
        print(f"📋 تم إرسال الملخص اليومي ({tracker.total_signals} إشارة)")
    except Exception as e:
        logging.error(f"send_daily_summary: {e}")


async def run_bot():
    init_db()

    if not TELEGRAM_BOT_TOKEN:
        raise ValueError("TELEGRAM_BOT_TOKEN غير موجود")
    if not TELEGRAM_CHANNEL_ID:
        raise ValueError("TELEGRAM_CHANNEL_ID غير موجود")
    if not CMC_API_KEY:
        raise ValueError("CMC_API_KEY غير موجود")

    bot = Bot(token=TELEGRAM_BOT_TOKEN)

    try:
        me = await bot.get_me()
        print(f"🤖 البوت متصل: @{me.username}")
    except Exception as e:
        print(f"❌ فشل الاتصال بتليغرام: {e}")
        return

    try:
        await bot.send_message(
            chat_id=TELEGRAM_CHANNEL_ID,
            text=(
                "🤖 *بوت إشارات 1H شغّال الآن!*\n\n"  # ✅ تم التغيير من 4H إلى 1H
                f"📊 يراقب أفضل *{CMC_TOP_N} عملة* من CoinMarketCap\n"
                f"📉 Stochastic RSI على فريم *1H* — K و D أقل من *{MAX_RSI_BUY}*\n"  # ✅
                "📊 MACD Hist — *قوي جدًا ومتصاعد فقط* 🔥\n"
                "🔥 Volume Spike + قيمة فوليوم الشمعة الحالية بالدولار\n"
                f"💧 أقل فوليوم للشمعة الحالية: *{format_big_number(MIN_CURRENT_CANDLE_VOLUME_USD)}$*\n"
                "🤖 تعلم ذاتي من نتائج الإشارات السابقة\n"
                "🏆 AI Ranking + BTC Trend Filter\n"
                "🗄️ SQLite Database + Win Rate اليوم\n"
                "📌 Auto Position Sizing\n"
                f"🧠 أقل ثقة للإرسال: *{MIN_CONFIDENCE}%*\n"
                f"🚫 يتجنب ارتفاع 24h أعلى من *{MAX_24H_CHANGE}%*\n"
                f"⏱️ فحص كل *{CHECK_INTERVAL // 60} دقيقة*\n\n"
                "🚀 _سيبدأ التحليل خلال لحظات..._"
            ),
            parse_mode=ParseMode.MARKDOWN,
        )
    except Exception as e:
        print(f"⚠️ رسالة الترحيب لم ترسل: {e}")

    while True:
        now = datetime.now(SAUDI_TZ)

        if now.hour == DAILY_SUMMARY_HOUR and not tracker.summary_sent:
            await send_daily_summary(bot)

        if tracker.new_day():
            tracker.reset()

        print("=" * 55)
        print(f"🔍 [{now.strftime('%H:%M:%S')}] جلب أفضل {CMC_TOP_N} عملة")

        btc_filter = get_btc_trend_filter()
        print(f"₿ BTC Filter: {btc_filter.get('note')}")

        coins = get_top_coins_from_cmc()
        tracker.scans += 1
        tracker.coins_scanned += len(coins)

        signals_this_round = 0

        for i, coin in enumerate(coins, 1):
            print(f"[{i}/{len(coins)}] تحليل 1H {coin['symbol']}", end="\r")  # ✅

            market_data = get_kucoin_market_data(coin["symbol"])
            if not market_data:
                market_data = get_mexc_market_data(coin["symbol"])
            if not market_data:
                market_data = get_okx_market_data(coin["symbol"])

            if not market_data:
                await asyncio.sleep(0.1)
                continue

            closes = market_data["closes"]
            volumes = market_data["volumes"]
            current_price = closes[-1]

            if coin["symbol"] in active_signals:
                sig_before_update = active_signals.get(coin["symbol"])
                updates = check_tp_updates(coin["symbol"], current_price)

                if updates and sig_before_update:
                    try:
                        msg = format_tp_update_message(sig_before_update, updates)
                        await bot.send_message(
                            chat_id=TELEGRAM_CHANNEL_ID,
                            text=msg,
                            parse_mode=ParseMode.MARKDOWN,
                        )
                        for tp_name, tp_price, pct in updates:
                            print(
                                f"🎯 {coin['symbol']} {tp_name} "
                                f"تحقق عند {fp(tp_price)} ({pct:+.2f}%)"
                            )
                        await asyncio.sleep(1.5)
                    except Exception as e:
                        logging.error(f"send_tp_update {coin['symbol']}: {e}")

            rsi_value = calculate_stoch_rsi(closes, RSI_PERIOD)
            macd_data = calculate_macd(closes)
            volume_data = detect_volume_spike(volumes, current_price)
            volume_spike = volume_data["spike"]

            if rsi_value is None:
                await asyncio.sleep(0.1)
                continue

            coin["rsi"] = rsi_value
            coin["macd_data"] = macd_data
            coin["volume_spike"] = volume_spike
            coin["volume_ratio"] = volume_data["ratio"]
            coin["current_volume_usd"] = volume_data.get("current_volume_usd", 0)

            if coin["symbol"] in active_signals:
                await asyncio.sleep(0.2)
                continue

            sig = analyze_signal(coin, btc_filter)

            if sig:
                await send_signal(bot, sig)
                signals_this_round += 1
                await asyncio.sleep(1.5)

            await asyncio.sleep(0.2)

        print()
        print(f"📬 إشارات هذه الجولة: {signals_this_round} | إجمالي اليوم: {tracker.total_signals}")
        print(f"⏳ الفحص القادم بعد {CHECK_INTERVAL // 60} دقيقة")
        await asyncio.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s — %(levelname)s — %(message)s",
    )
    asyncio.run(run_bot())
