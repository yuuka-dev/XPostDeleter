"""
delete_agent.py
エントリーポイント。引数パース・ドライバ起動・ルーチン呼び出しのみ。
"""

import argparse

from actions import LIMIT_PER_DAY, human_like_delete, human_like_unretweet
from browser import (
    DEBUGGER_ADDRESS,
    PROFILE_DIRECTORY,
    USER_DATA_DIR,
    create_driver,
    ensure_x_tab,
)
from utils import setup_stdout_tee

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--driver-path",
        help="Path to chromedriver executable (overrides CHROME_DRIVER_PATH env and default).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=LIMIT_PER_DAY,
        help="Max number of tweets to delete in one run.",
    )
    parser.add_argument(
        "--allow-low-severity",
        action="store_true",
        help="Also delete tweets with severity < 3 when capacity remains.",
    )
    parser.add_argument(
        "--attach-existing",
        action="store_true",
        help=(
            "Attach to already running Chrome via remote debugging "
            f"({DEBUGGER_ADDRESS}). If not set, a new Chrome instance is launched "
            "with the configured USER_DATA_DIR and PROFILE_DIRECTORY."
        ),
    )
    parser.add_argument(
        "--debug-driver-log",
        action="store_true",
        help="Enable verbose ChromeDriver logging to ./webdriver_debug.log.",
    )
    parser.add_argument(
        "--log-file",
        default="xpostdeleter.log",
        help="Path to append textual run logs (all print output).",
    )
    parser.add_argument(
        "--debugger-address",
        default=DEBUGGER_ADDRESS,
        help="Debugger address for --attach-existing mode (default: 127.0.0.1:9222).",
    )
    parser.add_argument(
        "--debug-rt",
        action="store_true",
        help="RT/リポスト検出まわりで XPath と要素数をログ出力（デバッグ用）。",
    )
    parser.add_argument(
        "--rt",
        action="store_true",
        help=(
            "RT取り消し専用モード。rt_hit_list.csv を読んで unretweet 処理を行う。"
            "指定しない場合は通常の削除モード（delete_hit_list.csv）。"
        ),
    )
    args = parser.parse_args()

    setup_stdout_tee(args.log_file)

    mode = "attach-existing" if args.attach_existing else "standalone"
    print(
        f"[CONFIG] mode={mode}, driver_path={args.driver_path or '<AUTO/ENV>'}, "
        f"debugger={args.debugger_address if args.attach_existing else '-'}, "
        f"user_data_dir={USER_DATA_DIR}, profile={PROFILE_DIRECTORY}"
    )

    driver = create_driver(
        chrome_driver_path=args.driver_path,
        attach_existing=args.attach_existing,
        debugger_address=args.debugger_address,
        debug_driver=args.debug_driver_log,
    )
    try:
        if args.attach_existing:
            ensure_x_tab(driver)
        if args.rt:
            human_like_unretweet(
                driver,
                limit_per_run=args.limit,
                debug_rt=args.debug_rt,
            )
        else:
            human_like_delete(
                driver,
                limit_per_run=args.limit,
                allow_low_severity=args.allow_low_severity,
                debug_rt=args.debug_rt,
            )
    finally:
        print("本日のデバッグ作業終了！プラグアウト！")
        driver.quit()
