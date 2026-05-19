# 4D Scraper (Standalone Version)

This repository contains a standalone 4D scraper for Magnum and Toto results from 4dmoon.com.

> **Note:** This is a standalone scraper version derived from the [RandAI Scraper Bot](https://github.com/lck920/randai-scraper-bot) repository. The code in this repository was created and refactored using ChatGPT.

## Overview
This project contains Python scripts designed to extract 4D lottery results and save them locally. 

- `scrape_magnum.py` - Scrapes Magnum 4D results.
- `scrape_toto.py` - Scrapes Toto 4D results.

## Installation

1. **Clone or Download the Repository:**
   Download the source code to your local machine.

2. **Install Python:**
   Ensure you have Python 3.7 or newer installed. You can download it from [python.org](https://www.python.org/).

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
