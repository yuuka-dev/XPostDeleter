"""
browser.py
ChromeDriver の生成・タブ管理・ページ遷移ユーティリティ
"""

import os

from dotenv import load_dotenv
from selenium import webdriver
from selenium.common.exceptions import TimeoutException, WebDriverException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait

load_dotenv()

# --- ブラウザ設定定数 ---
CHROME_DRIVER_DEFAULT = "chromedriver.exe"  # 環境変数が無いときのデフォルトパス
USER_DATA_DIR = os.getenv(
    "USER_DATA_DIR",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "ChromeUserData"),
)  # .env の USER_DATA_DIR 優先、未設定ならスクリプトと同階層の ChromeUserData/
PROFILE_DIRECTORY = "Default"  # 使いたいプロファイル名
DEBUGGER_ADDRESS = "127.0.0.1:9222"  # 既存Chromeへのアタッチ先


def ensure_x_tab(driver: webdriver.Chrome) -> None:
    """
    attach-existing 時に「操作対象のタブがどれか分からん」問題が起きやすいので、
    x.com / twitter.com のタブがあればそこへスイッチする。
    見つからなければ新規タブで x.com を開く。
    """
    try:
        handles = driver.window_handles
    except Exception:
        return

    for h in handles:
        try:
            driver.switch_to.window(h)
            cur = (driver.current_url or "").lower()
            if "x.com" in cur or "twitter.com" in cur:
                return
        except Exception:
            continue

    try:
        driver.switch_to.new_window("tab")
        driver.get("https://x.com/home")
    except Exception:
        pass


def navigate_to(
    driver: webdriver.Chrome,
    url: str,
    status_id: str | None = None,
    timeout_sec: int = 15,
) -> None:
    """
    driver.get が効かない/見えない時があるので、遷移が完了したかを検証しつつ遷移する。
    - まず driver.get(url)
    - timeout したら JS で window.location を直接更新
    """
    before = ""
    try:
        before = driver.current_url or ""
    except Exception:
        pass

    def _is_arrived(_driver: webdriver.Chrome) -> bool:
        try:
            cur = _driver.current_url or ""
        except Exception:
            return False
        if status_id:
            return status_id in cur
        return cur != before

    # 1) 通常遷移
    driver.get(url)
    try:
        WebDriverWait(driver, timeout_sec).until(_is_arrived)
        return
    except TimeoutException:
        pass
    except WebDriverException:
        pass

    # 2) JS で強制遷移（SPAが get を飲み込む/タブが違う時の保険）
    try:
        driver.execute_script("window.location.href = arguments[0];", url)
        WebDriverWait(driver, timeout_sec).until(_is_arrived)
        return
    except Exception:
        try:
            cur = driver.current_url
        except Exception:
            cur = "<unknown>"
        try:
            title = driver.title
        except Exception:
            title = "<unknown>"
        print(f"[NAV-ERROR] before={before} now={cur} title={title}")
        try:
            print(f"[NAV-ERROR] window_handles={len(driver.window_handles)}")
        except Exception:
            pass
        raise


def create_driver(
    chrome_driver_path: str | None = None,
    attach_existing: bool = False,
    debugger_address: str = DEBUGGER_ADDRESS,
    user_data_dir: str = USER_DATA_DIR,
    profile_directory: str = PROFILE_DIRECTORY,
    debug_driver: bool = False,
) -> webdriver.Chrome:
    """
    ChromeDriver の生成方法を2パターンから選べるようにしたファクトリ。

    - attach_existing=False（デフォルト）:
        Selenium が専用の Chrome を起動する方式。
        user_data_dir / profile_directory を使ってプロファイルを指定。
    - attach_existing=True:
        既に起動済みの Chrome に remote debugging でアタッチする方式。
        debugger_address に接続する。

    依存性解決の優先順位: 引数 > 環境変数 CHROME_DRIVER_PATH > CHROME_DRIVER_DEFAULT。

    debug_driver=True のときは ChromeDriver のログを ./webdriver_debug.log に吐く。
    """
    resolved_path = chrome_driver_path or os.getenv(
        "CHROME_DRIVER_PATH", CHROME_DRIVER_DEFAULT
    )
    if os.path.isdir(resolved_path):
        resolved_path = os.path.join(resolved_path, "chromedriver.exe")

    options = Options()
    options.add_argument("--disable-blink-features=AutomationControlled")
    if not debug_driver:
        options.add_argument("--log-level=3")

    if attach_existing:
        options.add_experimental_option("debuggerAddress", debugger_address)
    else:
        options.add_argument(f"--user-data-dir={user_data_dir}")
        options.add_argument(f"--profile-directory={profile_directory}")
        options.add_argument("--disable-notifications")
        options.add_argument("--disable-gcm")
        options.add_argument("--disable-geofencing")

    if debug_driver:
        log_path = os.path.join(os.getcwd(), "webdriver_debug.log")
    else:
        log_path = os.devnull

    service = Service(executable_path=resolved_path, log_path=log_path)
    return webdriver.Chrome(service=service, options=options)
