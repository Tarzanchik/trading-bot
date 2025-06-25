# bot.py — версия с интерактивным меню и графиком
import os, io, html, logging
from datetime import datetime, timedelta

import pandas as pd
import requests, yfinance as yf
import matplotlib.pyplot as plt
from dotenv import load_dotenv
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputFile,
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    CallbackContext,
)

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

POPULAR = ["SBER", "GAZP", "LKOH"]  # расширяй при желании

# ───────── утилиты MOEX/Yahoo ────────

def _moex_history(ticker: str, days=180):
    end, start = datetime.now(), datetime.now() - timedelta(days=days)
    url = f"https://iss.moex.com/iss/history/engines/stock/markets/shares/securities/{ticker}.json"
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
        df = pd.DataFrame(rows, columns=["Date", "Close"])
        df["Date"] = pd.to_datetime(df["Date"])
        return df.set_index("Date")[["Close"]].astype(float)
    except Exception:
        return pd.DataFrame()


def _yahoo_history(ticker: str, period="6mo"):
    try:
        data = yf.download(ticker, period=period, progress=False)
        return data[["Close"]].astype(float)
    except Exception:
        return pd.DataFrame()


def get_history(ticker: str) -> pd.DataFrame:
    df = _moex_history(ticker)
    return df if not df.empty else _yahoo_history(ticker)


def _moex_price(ticker: str):
    url = f"https://iss.moex.com/iss/engines/stock/markets/shares/securities/{ticker}.json"
    try:
        rows = requests.get(url, params={"iss.only": "marketdata", "marketdata.columns": "LAST"}, timeout=10
                            ).json().get("marketdata", {}).get("data", [])
        return float(rows[0][0]) if rows and rows[0][0] is not None else None
    except Exception:
        return None


def _yahoo_price(ticker: str):
    try:
        data = yf.Ticker(ticker).history(period="1d")
        return float(data["Close"].iloc[-1]) if not data.empty else None
    except Exception:
        return None


def get_price(ticker: str):
    price = _moex_price(ticker)
    return price if price else _yahoo_price(ticker)


# ──────── анализ и график ────────

def build_analysis(ticker: str) -> str:
    df = get_history(ticker)
    if df.empty:
        return f"<b>{html.escape(ticker)}</b>\nНет данных."

    df["ma5"] = df.Close.rolling(5).mean()
    df["ma20"] = df.Close.rolling(20).mean()
    delta = df.Close.diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    rs = gain / loss
    df["rsi"] = 100 - 100 / (1 + rs)
    ema12 = df.Close.ewm(span=12, adjust=False).mean()
    ema26 = df.Close.ewm(span=26, adjust=False).mean()
    df["macd"] = ema12 - ema26
    df["signal"] = df.macd.ewm(span=9, adjust=False).mean()

    last = df.iloc[-1]
    lines = [
        f"<b>{html.escape(ticker)}</b>",
        f"Close: {last.Close:.2f}",
        f"MA5 / MA20: {last.ma5:.2f} / {last.ma20:.2f}",
        f"RSI(14): {last.rsi:.1f}",
        f"MACD: {last.macd:.2f} vs {last.signal:.2f}",
    ]
    if last.ma5 > last.ma20 and last.macd > last.signal and last.rsi < 70:
        lines.append("🟢 <b>BUY signal</b>")
    elif last.ma5 < last.ma20 and last.macd < last.signal and last.rsi > 30:
        lines.append("🔴 <b>SELL signal</b>")
    else:
        lines.append("🟡 Сигнал не ясен")
    return "\n".join(lines)


def build_chart(ticker: str) -> io.BytesIO:
    df = get_history(ticker).tail(120)
    plt.figure(figsize=(8, 4))
    plt.plot(df.index, df.Close, label="Close")
    plt.plot(df.Close.rolling(20).mean(), label="MA20")
    plt.tight_layout()
    buf = io.BytesIO()
    plt.savefig(buf, format="png")
    plt.close()
    buf.seek(0)
    return buf


# ──────── Telegram меню ────────

def main_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("💵 Курс", callback_data="menu_price"),
          InlineKeyboardButton("📊 Анализ", callback_data="menu_analysis")]]
    )


def ticker_keyboard(action: str) -> InlineKeyboardMarkup:
    # action = "price" / "analysis"
    rows = [[InlineKeyboardButton(t, callback_data=f"{action}_{t}")] for t in POPULAR]
    return InlineKeyboardMarkup(rows)


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 Бот-инвестор. Выберите действие:",
        reply_markup=main_menu_keyboard(),
    )


async def cmd_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Меню:", reply_markup=main_menu_keyboard())


# ──────── обработка нажатий ────────

async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    data = q.data
    if data == "menu_price":
        await q.edit_message_text("Выберите тикер:", reply_markup=ticker_keyboard("price"))
    elif data == "menu_analysis":
        await q.edit_message_text("Выберите тикер:", reply_markup=ticker_keyboard("analysis"))

    # --- показать цену
    elif data.startswith("price_"):
        tkr = data.split("_")[1]
        price = get_price(tkr)
        if price:
            kb = InlineKeyboardMarkup(
                [[InlineKeyboardButton("📊 Анализ", callback_data=f"analysis_{tkr}")]]
            )
            await q.edit_message_text(
                f"<b>{tkr}</b> = {price:.2f}",
                parse_mode="HTML",
                reply_markup=kb,
            )
        else:
            await q.edit_message_text(f"Цена недоступна для {tkr}")

    # --- анализ
    elif data.startswith("analysis_"):
        tkr = data.split("_")[1]
        text = build_analysis(tkr)
        kb = InlineKeyboardMarkup(
            [[InlineKeyboardButton("📈 График", callback_data=f"chart_{tkr}")]]
        )
        await q.edit_message_text(text, parse_mode="HTML", reply_markup=kb)

    # --- график
    elif data.startswith("chart_"):
        tkr = data.split("_")[1]
        buf = build_chart(tkr)
        await q.message.reply_photo(InputFile(buf), caption=f"График {tkr}")


# ──────── ошибка ────────

async def error_handler(update: object, context: CallbackContext):
    logging.error("Error: %s", context.error)
    if isinstance(update, Update) and update.effective_chat:
        await update.effective_chat.send_message("⚠️ Ошибка, попробуйте позже.")


# ──────── запуск ────────

def main():
    token = os.getenv("TELEGRAM_TOKEN")
    if not token:
        raise RuntimeError("В .env нет TELEGRAM_TOKEN")

    app = ApplicationBuilder().token(token).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("menu", cmd_menu))
    app.add_handler(CallbackQueryHandler(on_callback))
    app.add_error_handler(error_handler)

    logging.info("Bot started")
    app.run_polling()


if __name__ == "__main__":
    main()
