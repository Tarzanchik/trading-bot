# bot.py
import os
import html
import logging
from datetime import datetime, timedelta

import pandas as pd
import requests
import yfinance as yf
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    CallbackContext,
)

load_dotenv()
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)

# ────────────────── 1.  Источники данных ──────────────────
# ---------- MOEX ----------
def fetch_moex_history(ticker: str, days: int = 180) -> pd.DataFrame:
    end = datetime.now()
    start = end - timedelta(days=days)
    url = (
        "https://iss.moex.com/iss/history/engines/stock/markets/shares/"
        f"securities/{ticker}.json"
    )
    params = {
        "from": start.strftime("%Y-%m-%d"),
        "till": end.strftime("%Y-%m-%d"),
        "iss.only": "history",
        "history.columns": "TRADEDATE,CLOSE",
    }
    try:
        r = requests.get(url, params=params, timeout=10)
        r.raise_for_status()
        rows = r.json().get("history", {}).get("data", [])
        if not rows:
            return pd.DataFrame()
        df = pd.DataFrame(rows, columns=["TRADEDATE", "Close"])
        df["TRADEDATE"] = pd.to_datetime(df["TRADEDATE"])
        return df.set_index("TRADEDATE")[["Close"]].astype(float)
    except Exception as exc:
        logging.warning("MOEX history error: %s", exc)
        return pd.DataFrame()


def fetch_price_moex(ticker: str) -> float | None:
    url = (
        "https://iss.moex.com/iss/engines/stock/markets/shares/"
        f"securities/{ticker}.json"
    )
    params = {"iss.only": "marketdata", "marketdata.columns": "LAST"}
    try:
        r = requests.get(url, params=params, timeout=10)
        r.raise_for_status()
        rows = r.json().get("marketdata", {}).get("data", [])
        return float(rows[0][0]) if rows and rows[0][0] is not None else None
    except Exception as exc:
        logging.warning("MOEX price error: %s", exc)
        return None


# ---------- Yahoo ----------
def fetch_yahoo_history(ticker: str, period: str = "6mo") -> pd.DataFrame:
    try:
        data = yf.download(ticker, period=period, progress=False)
        return data[["Close"]].astype(float)
    except Exception as exc:
        logging.warning("Yahoo history error: %s", exc)
        return pd.DataFrame()


def fetch_price_yahoo(ticker: str) -> float | None:
    try:
        data = yf.Ticker(ticker).history(period="1d")
        return float(data["Close"].iloc[-1]) if not data.empty else None
    except Exception as exc:
        logging.warning("Yahoo price error: %s", exc)
        return None


# ────────────────── 2.  Агрегация ──────────────────
def get_history(ticker: str) -> pd.DataFrame:
    df = fetch_moex_history(ticker)
    return df if not df.empty else fetch_yahoo_history(ticker)


def get_price(ticker: str) -> float | None:
    price = fetch_price_moex(ticker)
    return price if price is not None else fetch_price_yahoo(ticker)


# ────────────────── 3.  Аналитика ──────────────────
def analyze_ticker(ticker: str) -> str:
    df = get_history(ticker)
    if df.empty:
        return f"<b>{html.escape(ticker)}</b>\nNo data available."

    # скользящие средние
    df["ma5"] = df["Close"].rolling(5).mean()
    df["ma20"] = df["Close"].rolling(20).mean()

    # RSI
    delta = df["Close"].diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    rs = gain / loss
    df["rsi"] = 100 - (100 / (1 + rs))

    # MACD
    ema12 = df["Close"].ewm(span=12, adjust=False).mean()
    ema26 = df["Close"].ewm(span=26, adjust=False).mean()
    df["macd"] = ema12 - ema26
    df["signal"] = df["macd"].ewm(span=9, adjust=False).mean()

    last = df.iloc[-1]

    msg = [
        f"<b>{html.escape(ticker)}</b>",
        f"Close: {last['Close']:.2f}",
        f"MA5 / MA20: {last['ma5']:.2f} / {last['ma20']:.2f}",
        f"RSI(14): {last['rsi']:.1f}",
        f"MACD: {last['macd']:.2f} (sig {last['signal']:.2f})",
    ]

    # простая логика рекомендаций
    if last["ma5"] > last["ma20"] and last["macd"] > last["signal"] and last["rsi"] < 70:
        msg.append("🟢 <b>BUY signal</b> (uptrend)")
    elif last["ma5"] < last["ma20"] and last["macd"] < last["signal"] and last["rsi"] > 30:
        msg.append("🔴 <b>SELL signal</b> (downtrend)")
    else:
        msg.append("🟡 <i>No clear signal</i>")

    return "\n".join(msg)


# ────────────────── 4.  Обработчики Telegram ──────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 <b>Trading Bot</b>\n"
        "/price TICKER — текущая цена\n"
        "/recommend TICKER — анализ и совет",
        parse_mode="HTML",
    )


async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /price TICKER")
        return
    ticker = context.args[0].upper()
    await update.message.reply_text("Fetching price...")
    price_value = get_price(ticker)
    if price_value is None:
        text = f"<b>{html.escape(ticker)}</b>: price not available."
    else:
        text = f"<b>{html.escape(ticker)}</b> price: {price_value:.2f}"
    await update.message.reply_text(text, parse_mode="HTML")


async def recommend(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /recommend TICKER")
        return
    ticker = context.args[0].upper()
    await update.message.reply_text("Fetching analysis...")
    message = analyze_ticker(ticker)
    await update.message.reply_text(message, parse_mode="HTML")


# ────────────────── 5.  Error-handler ──────────────────
async def error_handler(update: object, context: CallbackContext):
    logging.error("Telegram error: %s", context.error)
    if isinstance(update, Update) and update.effective_chat:
        await update.effective_chat.send_message(
            "⚠️ An internal error occurred.", parse_mode="HTML"
        )


# ────────────────── 6.  Запуск ──────────────────
def main():
    token = os.getenv("TELEGRAM_TOKEN")
    if not token:
        raise RuntimeError("Add TELEGRAM_TOKEN to .env")

    app = (
        ApplicationBuilder()
        .token(token)
        .build()
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("price", price))
    app.add_handler(CommandHandler("recommend", recommend))
    app.add_error_handler(error_handler)

    logging.info("Bot started")
    app.run_polling()


if __name__ == "__main__":
    main()
