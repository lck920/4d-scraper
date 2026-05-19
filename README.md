# 4D Scraper

## Note
This is a standalone version derived from:

https://github.com/lck920/randai-scraper-bot

Created using ChatGPT.

This repository contains standalone Python scraping scripts to retrieve past 4D results from 4dmoon directly into local CSV files, without the Telegram bot interface.

---

# Included Scripts

`scrape_magnum.py`
Scrapes and updates the Magnum 4D dataset.

`scrape_toto.py`
Scrapes and updates the Sports Toto dataset.

---

# Features

- Historical 4D scraping
- Automatic CSV updating
- Incremental updates
- Parallel scraping
- Local dataset generation
- Standalone usage without Telegram bot

---

# Requirements

- Python 3.9+
- requests
- beautifulsoup4

Install dependencies:

```bash
pip install requests beautifulsoup4
