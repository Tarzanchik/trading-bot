Trading Bot
==========

This Telegram bot collects stock data, performs simple trend analysis, and provides buy or sell suggestions. The logic relies on moving-average comparison to guess potential market direction. **Use at your own risk. This is not professional financial advice.**

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
