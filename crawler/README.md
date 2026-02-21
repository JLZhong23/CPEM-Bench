# CrawlerData: Literature Crawler (crawler.py + crawlerWWW.py)

This directory contains two synchronous crawler scripts based on **Playwright**, designed to batch retrieve literature entries from the Medlive/Yiigle website by "disease name list" and save **titles/abstracts** as TXT files, while downloading corresponding PDFs when possible.

- `crawler.py`: Primarily crawls `https://cmcr.yiigle.com/index` (referred to as **website1** below)
- `crawlerWWW.py`: Primarily crawls `https://www.yiigle.com/index` (referred to as **website2** below)

> Note: Both scripts have built-in `run()` example entry points that read disease lists from `csv/diseases_part*.csv` by default and output to `paper/part{n}/website1` or `paper/part{n}/website2`.

---

## Requirements

- Windows (this project handles Windows path/illegal character filename sanitization)
- Python 3.10+ (recommended)
- Playwright (scripts use `playwright.sync_api`)

---

## Installation

Execute in this directory:

```bash
pip install -r requirements.txt
```

Playwright requires browser runtime:

```bash
playwright install chromium
```

### About Browser Path (Important)

The `run()` functions in both scripts have a hardcoded browser path by default, for example:

- `D:\playwright_browsers\chromium-1200\chrome-win64\chrome.exe`

You have two options:

1) **Recommended**: Use Playwright's built-in browser
   - Ensure you've executed `playwright install chromium`
   - Then set `browser_path` to `None` or directly remove the parameter (let Playwright automatically use the downloaded Chromium)

2) Use Chrome/Chromium already installed on your machine
   - Change `browser_path` to the actual path of `chrome.exe` on your machine

---

## Input Data (Disease List CSV)

Scripts read CSV through `ExtractDisease()`:

- Reads from `csv/diseases_part1.csv`, `csv/diseases_part2.csv`, `csv/diseases_part4.csv`, etc. by default
- **Column 1 of each row** contains the disease name
- Compatible with inline OMIM information (automatically truncates content within parentheses):
  - `xxx (OMIM:12345)` or `xxx（OMIM:12345）`

---

## Output Directories and Files

### website1 (`crawler.py`)

Default output to:

- `paper/part{n}/website1/{id}_{disease_name}/`

This generates:

- `{disease_name}_{title}.txt`: Title + abstract
- `{disease_name}_{title}.pdf`: Saved if downloadable
- `errors.csv`: Generated only when exceptions occur during runtime (saved in the output root directory for that part)

Additionally:

- Logs written to `crawler_log.log`

### website2 (`crawlerWWW.py`)

Default output to:

- `paper/part{n}/website2/{id}_{disease_name}/`

This generates:

- `{id}_{disease_name}_{title}.txt`: Title + abstract + source link + timestamp
- `{id}_{disease_name}_{title}.pdf`: Saved if downloadable
- `crawler2_results.csv`: Summary results (saved in the output root directory for that part)
- `errors_crawler2.csv`: Error summary (saved in the output root directory for that part)

Additionally:

- Logs written to `crawler2_log.log`

> File/directory names are sanitized through `_sanitize_windows_path_component()` to avoid Windows-prohibited characters (such as `:` `*` `?` etc.).

---

## How to Run

### Method A: Directly run the built-in run() in the script

1) Run `crawler.py` (website1 / cmcr):

```bash
python crawler.py
```

2) Run `crawlerWWW.py` (website2 / www):

```bash
python crawlerWWW.py
```

Both scripts will batch process `part1/part2/part4` according to `parts_to_crawl` by default. If you only want to run a specific part, simply reduce `parts_to_crawl` in the script to a single entry.

### Method B: Customize parameters in code (recommended for debugging)

You typically only need to modify these settings:

- `parts_to_crawl`: Select which CSVs to run
- `browser_path`: Your machine's browser path (or change to `None` to let Playwright manage automatically)
- `headless`: Can be set to `False` during debugging (allows you to see the browser)
- `start` (only in `crawlerWWW.py`): Start from which disease (resume from breakpoint)

---

## Differences Between the Two Scripts (How to Choose)

- `crawler.py` (website1 / cmcr)
  - Main flow: Search → Get first N results → Enter detail page → Extract abstract → Attempt multi-strategy PDF download
  - Output focuses on "one txt/pdf per result"

- `crawlerWWW.py` (website2 / www)
  - Main flow: Search → Extract first N entries → Click popup/new page to enter details → Extract title/abstract → Trigger download with `expect_download`
  - Supports `start` parameter, suitable for resuming long lists from breakpoint

---

## Common Issues

1) **Constant timeouts / element not found**
   - Site page structure may have been updated; related selectors need adjustment (scripts have some error tolerance but aren't guaranteed to be permanently stable)
   - For slow networks, you can appropriately increase:
     - `default_navigation_timeout`
     - `default_action_timeout`

2) **Cannot download PDF**
   - Website may require login/permissions or use dynamic download methods
   - `crawler.py` internally uses multiple strategies: direct `.pdf` link requests, iframe, clicking "Download PDF/Download Full Text" etc., but may still fail

3) **Anti-crawling/CAPTCHA**
   - Recommend setting `headless=False` first to observe page behavior
   - If necessary, reduce frequency (scripts have `time.sleep()`, can be increased appropriately)

4) **Output filename errors**
   - Theoretically won't occur (scripts already sanitize illegal characters). If issues persist, it's likely due to path length; move the output root directory to a shorter path.

---

## Directory Overview

- `csv/`: Disease lists (by part)
- `paper/`: Crawler output (organized by part and website)
- `crawler.py`: cmcr site crawler (website1)
- `crawlerWWW.py`: www site crawler (website2)
- `requirements.txt`: Dependencies
- `MinerU/`, `疾病pdf/`, `ExtractSubtype.py`: Related to subsequent processing/materials (does not affect crawler operation in this README)

---

## Reproduction Suggestions (Minimal Setup)

- First keep 1-3 disease names in a `csv/diseases_part*.csv`
- Run once with `headless=False` to observe the page
- Confirm that txt files are generated in the output directory (PDF depends on site permissions)