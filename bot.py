import os
import logging
from datetime import datetime, timedelta

import pandas as pd
import requests
import yfinance as yf
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from dotenv import load_dotenv

load_dotenv()


logging.basicConfig(level=logging.INFO)

def fetch_moex_history(ticker: str, days: int = 180) -> pd.DataFrame:
    """Return historical close prices from MOEX ISS API."""
    end = datetime.now()
    start = end - timedelta(days=days)
    url = (
        f"https://iss.moex.com/iss/history/engines/stock/markets/shares/"
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
        payload = r.json()
        rows = payload.get("history", {}).get("data", [])
        if not rows:
            return pd.DataFrame()
        df = pd.DataFrame(rows, columns=payload["history"]["columns"])
        df["TRADEDATE"] = pd.to_datetime(df["TRADEDATE"])
        df = df.set_index("TRADEDATE")
        df = df.rename(columns={"CLOSE": "Close"})
        return df[["Close"]].dropna()
    except Exception as e:
        logging.exception("Failed to fetch MOEX history for %s", ticker)
        return pd.DataFrame()


def fetch_price_moex(ticker: str) -> float | None:
    """Return the latest price from MOEX ISS API."""
    url = (
        f"https://iss.moex.com/iss/engines/stock/markets/shares/"
        f"securities/{ticker}.json"
    )
    params = {"iss.only": "marketdata", "marketdata.columns": "LAST"}
    try:
        r = requests.get(url, params=params, timeout=10)
        r.raise_for_status()
        payload = r.json()
        rows = payload.get("marketdata", {}).get("data", [])
        if rows and rows[0][0] is not None:
            return float(rows[0][0])
    except Exception:
        logging.exception("Failed to fetch MOEX price for %s", ticker)
    return None


def fetch_yahoo_history(ticker: str, period: str = "6mo") -> pd.DataFrame:
    """Return historical data using Yahoo Finance."""
    try:
        data = yf.download(ticker, period=period, progress=False)
        return data[["Close"]]
    except Exception:
        logging.exception("Failed to fetch Yahoo history for %s", ticker)
        return pd.DataFrame()


def fetch_price_yahoo(ticker: str) -> float | None:
    """Get current price from Yahoo Finance."""
    try:
        info = yf.Ticker(ticker)
        data = info.history(period="1d")
        if not data.empty:
            return float(data["Close"].iloc[-1])
    except Exception:
        logging.exception("Failed to fetch Yahoo price for %s", ticker)
    return None


def get_history(ticker: str) -> pd.DataFrame:
    """Fetch history from MOEX with fallback to Yahoo."""
    data = fetch_moex_history(ticker)
    if data.empty:
        data = fetch_yahoo_history(ticker)
    return data


def get_price(ticker: str) -> float | None:
    """Fetch latest price from MOEX with fallback to Yahoo."""
    price = fetch_price_moex(ticker)
    if price is None:
        price = fetch_price_yahoo(ticker)
    return price

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send a welcome message."""
    await update.message.reply_text(
        "Welcome to the trading bot.\n"
        "Use /price <TICKER> to get the latest price or /recommend <TICKER> for analysis."
    )


def analyze_ticker(ticker: str) -> str:
    """Fetch data for *ticker* and return a recommendation."""
    data = get_history(ticker)
    if data.empty:
        return f"No data available for {ticker}"

    # indicators
    data["ma_short"] = data["Close"].rolling(window=5).mean()
    data["ma_long"] = data["Close"].rolling(window=20).mean()

    delta = data["Close"].diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.rolling(14).mean()
    avg_loss = loss.rolling(14).mean()
    rs = avg_gain / avg_loss
    data["rsi"] = 100 - (100 / (1 + rs))

    exp1 = data["Close"].ewm(span=12, adjust=False).mean()
    exp2 = data["Close"].ewm(span=26, adjust=False).mean()
    data["macd"] = exp1 - exp2
    data["signal"] = data["macd"].ewm(span=9, adjust=False).mean()

    latest = data.iloc[-1]

    msg = [
        f"*{ticker}*",
        f"Close: {latest['Close']:.2f}",
        f"MA5: {latest['ma_short']:.2f}",
        f"MA20: {latest['ma_long']:.2f}",
        f"RSI(14): {latest['rsi']:.2f}",
        f"MACD: {latest['macd']:.2f}",
        f"Signal: {latest['signal']:.2f}",
    ]

    # Simple signals
    if latest["ma_short"] > latest["ma_long"] and latest["macd"] > latest["signal"] and latest["rsi"] < 70:
        msg.append("Potential uptrend. Consider buying.")
    elif latest["ma_short"] < latest["ma_long"] and latest["macd"] < latest["signal"] and latest["rsi"] > 30:
        msg.append("Potential downtrend. Consider selling.")
    else:
        msg.append("No clear signal.")

    return "\n".join(msg)


async def recommend(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the /recommend command."""
    if not context.args:
        await update.message.reply_text("Usage: /recommend <TICKER>")
        return

    ticker = context.args[0].upper()
    await update.message.reply_text("Fetching data...")
    message = analyze_ticker(ticker)
    await update.message.reply_text(message, parse_mode="Markdown")


async def price(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the /price command."""
    if not context.args:
        await update.message.reply_text("Usage: /price <TICKER>")
        return

    ticker = context.args[0].upper()
    await update.message.reply_text("Fetching price...")
    price_value = get_price(ticker)
    if price_value is None:
        await update.message.reply_text(f"Could not fetch price for {ticker}")
    else:
        await update.message.reply_text(f"*{ticker}* current price: {price_value:.2f}", parse_mode="Markdown")


def main() -> None:
    token = os.getenv("TELEGRAM_TOKEN")
    if not token:
        raise RuntimeError("TELEGRAM_TOKEN environment variable not set")

    app = ApplicationBuilder().token(token).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("price", price))
    app.add_handler(CommandHandler("recommend", recommend))

    logging.info("Bot started")
    app.run_polling()


if __name__ == "__main__":
    main()
