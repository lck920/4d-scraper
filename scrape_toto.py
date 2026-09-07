from scraper_common import run_scraper

TARGET_NAME = "SportsToto 4D"
FILE_PREFIX = "toto_pastresult"
LOGO_SRC_KEYS = ['logo_toto4d']
LIVE_JSON_KEY = "T"


if __name__ == "__main__":
    run_scraper(
        target_name=TARGET_NAME,
        file_prefix=FILE_PREFIX,
        logo_src_keys=LOGO_SRC_KEYS,
        live_json_key=LIVE_JSON_KEY,
    )
