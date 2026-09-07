# 4D Scraper (Standalone Version)

This repository contains a standalone 4D scraper for Magnum and Toto results from 4dmoon.com.

> **Note:** This is a standalone scraper version derived from the [RandAI Scraper Bot](https://github.com/lck920/randai-scraper-bot) repository. The code in this repository was created and refactored using ChatGPT.

## Overview
This project contains Python scripts designed to extract 4D lottery results and save them locally.

- `scrape_magnum.py` - Scrapes Magnum 4D results.
- `scrape_toto.py` - Scrapes Toto 4D results.
- `scraper_common.py` - Shared scraping/parsing/CSV logic used by both scripts above. Not meant to be run directly.

## Features
- **Historical Data Scraping**: Pulls all past results up to the current date and automatically repairs suspicious or corrupted data blocks.
- **Live Draw Support**: Intelligently switches to the live JSON data feed for today's date so you can scrape results even while the draw is happening.
- **Automated CSV Management**: Automatically names the output files based on the latest valid draw date and removes older output files to keep your directory clean. If a run would produce *fewer* rows than the existing file, cleanup is skipped and a warning is printed instead, so a bad run can't destroy good data.
- **Fetch Failure Handling**: A page that fails to load (blocked, rate-limited, network error) is retried automatically and reported separately from a confirmed "no draw that day" — so a temporary outage isn't mistaken for missing data.

## Installation

1. **Clone or Download the Repository:**
   Download the source code to your local machine.

2. **Install Python:**
   Ensure you have Python 3.10 or newer installed (the scripts use modern type-hint syntax that requires it). You can download it from [python.org](https://www.python.org/).

3. **Install Dependencies:**
   Open a terminal or command prompt in the project directory and install the required third-party libraries:
   ```bash
   pip install requests beautifulsoup4
   ```

## Usage Guide

You can run the scrapers individually from the command line. When executed, the scripts will connect to the target website, parse the latest 4D results, and save the data locally in your directory.

**To scrape Magnum results:**
```bash
python scrape_magnum.py
```

**To scrape Toto results:**
```bash
python scrape_toto.py
```

*Note: Depending on how your Python environment is set up, you may need to use `python3` instead of `python`.*

*`scraper_common.py` holds the shared logic for both scripts above — don't run it directly, it has no output of its own.*
