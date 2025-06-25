import os
import logging
import yfinance as yf
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from dotenv import load_dotenv
load_dotenv()


logging.basicConfig(level=logging.INFO)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send a welcome message."""
    await update.message.reply_text(
        "Welcome to the trading bot. Use /recommend <TICKER> to get a suggestion."
    )


def analyze_ticker(ticker: str) -> str:
    """Fetch data for *ticker* and return a recommendation."""
    data = yf.download(ticker, period="6mo", progress=False)
    if data.empty:
        return "No data available for %s" % ticker

    data["ma_short"] = data["Close"].rolling(window=5).mean()
    data["ma_long"] = data["Close"].rolling(window=20).mean()
    latest = data.iloc[-1]

    message = [
        f"{ticker} close: {latest['Close']:.2f}",
        f"Short MA: {latest['ma_short']:.2f}",
        f"Long MA: {latest['ma_long']:.2f}",
    ]

    if latest["ma_short"] > latest["ma_long"]:
        message.append("Potential uptrend. Consider buying.")
    elif latest["ma_short"] < latest["ma_long"]:
        message.append("Potential downtrend. Consider selling.")
    else:
        message.append("No clear signal.")

    return "\n".join(message)


async def recommend(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the /recommend command."""
    if not context.args:
        await update.message.reply_text("Usage: /recommend <TICKER>")
        return

    ticker = context.args[0].upper()
    await update.message.reply_text("Fetching data...")
    message = analyze_ticker(ticker)
    await update.message.reply_text(message)


def main() -> None:
    token = os.getenv("TELEGRAM_TOKEN")
    if not token:
        raise RuntimeError("TELEGRAM_TOKEN environment variable not set")

    app = ApplicationBuilder().token(token).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("recommend", recommend))

    logging.info("Bot started")
    app.run_polling()


if __name__ == "__main__":
    main()
