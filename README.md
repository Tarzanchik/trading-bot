Trading Bot
==========

This Telegram bot collects stock data from the Moscow Exchange when possible and falls back to Yahoo Finance. It performs basic technical analysis and can show the latest price. **Use at your own risk. This is not professional financial advice.**

All network requests use a 10 second timeout, and any connection failures are reported to the user.

Setup
-----
1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
   This project uses **python-dotenv** to load environment variables from a
   `.env` file.
2. Set your Telegram bot token in the environment:
   ```bash
   export TELEGRAM_TOKEN="<your token here>"
   ```
3. Run the bot:
   ```bash
   python bot.py
   ```

Commands
--------
- `/price <TICKER>` — show the latest price from MOEX (fallback to Yahoo)
- `/recommend <TICKER>` — moving average, RSI and MACD analysis
