from scraper_common import run_scraper

TARGET_NAME = "Magnum 4D"
FILE_PREFIX = "magnum_pastresult"
LOGO_SRC_KEYS = ['logo_magnum.gif']
LIVE_JSON_KEY = "M"


if __name__ == "__main__":
    run_scraper(
        target_name=TARGET_NAME,
        file_prefix=FILE_PREFIX,
        logo_src_keys=LOGO_SRC_KEYS,
        live_json_key=LIVE_JSON_KEY,
    )
