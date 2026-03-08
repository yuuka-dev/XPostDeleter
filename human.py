"""
human.py
人間らしいマウス操作・スクロール・タイミング制御
"""

import math
import os
import random
import time

import pandas as pd
import pyautogui
from selenium import webdriver

# pyautogui側のグローバル設定
pyautogui.FAILSAFE = True  # 画面左上にマウス飛ばすと緊急停止できるように
pyautogui.PAUSE = 0  # 待ち時間は自前で制御する


def human_pause(
    mean_sec: float, jitter_ratio: float = 0.3, min_sec: float = 0.1
) -> None:
    """
    人間ぽい「ため」入り待ち時間。
    平均 mean_sec、揺らぎ mean_sec * jitter_ratio のガウス分布＋下限 min_sec。
    """
    delay = random.gauss(mean_sec, mean_sec * jitter_ratio)
    delay = max(min_sec, delay)
    time.sleep(delay)


def human_scroll(
    driver: webdriver.Chrome,
    direction: str = "down",
    px_mean: int = 280,
    px_jitter: int = 120,
) -> None:
    """
    人間ぽいスクロール。ランダムな量だけ上下にスクロールする。
    """
    px = max(60, int(random.gauss(px_mean, px_jitter)))
    if direction == "up":
        px = -px
    driver.execute_script(
        f"window.scrollBy({{top: {px}, left: 0, behavior: 'smooth'}});"
    )
    human_pause(0.4, 0.5, min_sec=0.15)


def human_browse_page(driver: webdriver.Chrome) -> None:
    """
    ページ読み込み直後の「ながめる」挙動。
    ランダムに数回スクロールして、画像を眺めるフリをする。
    """
    scroll_count = random.randint(0, 3)
    for _ in range(scroll_count):
        human_scroll(driver, direction="down")
    if random.random() < 0.4:
        human_scroll(driver, direction="up", px_mean=120, px_jitter=60)
    human_pause(random.uniform(2.0, 4.5), jitter_ratio=0.3, min_sec=1.5)


def _bezier_point(p0, p1, p2, p3, t: float):
    """キュビックベジェ曲線上の1点を返す。t ∈ [0,1]。"""
    u = 1.0 - t
    tt = t * t
    uu = u * u
    uuu = uu * u
    ttt = tt * t

    x = uuu * p0[0] + 3 * uu * t * p1[0] + 3 * u * tt * p2[0] + ttt * p3[0]
    y = uuu * p0[1] + 3 * uu * t * p1[1] + 3 * u * tt * p2[1] + ttt * p3[1]
    return x, y


def move_mouse_human(
    target_x: float,
    target_y: float,
    min_duration: float = 0.4,
    max_duration: float = 1.2,
    jitter_px: float = 2.0,
) -> None:
    """
    マウスを「ベジェ曲線＋イージング＋微ブレ」でターゲット付近まで移動。
    最後にわずかな"うろうろ"を入れてからクリック位置に落ち着かせる。
    """
    start_x, start_y = pyautogui.position()

    end_x = target_x + random.uniform(-jitter_px, jitter_px)
    end_y = target_y + random.uniform(-jitter_px, jitter_px)

    duration = random.uniform(min_duration, max_duration)

    dist = math.hypot(end_x - start_x, end_y - start_y)
    curve_jitter = max(30.0, min(dist * 0.20, 150.0))

    cp1 = (
        start_x
        + (end_x - start_x) * random.uniform(0.2, 0.4)
        + random.uniform(-curve_jitter, curve_jitter),
        start_y
        + (end_y - start_y) * random.uniform(0.1, 0.3)
        + random.uniform(-curve_jitter, curve_jitter),
    )
    cp2 = (
        start_x
        + (end_x - start_x) * random.uniform(0.6, 0.8)
        + random.uniform(-curve_jitter, curve_jitter),
        start_y
        + (end_y - start_y) * random.uniform(0.7, 0.9)
        + random.uniform(-curve_jitter, curve_jitter),
    )

    steps = max(30, int(duration * 120))

    for i in range(steps + 1):
        linear_t = i / steps
        t = 0.5 - 0.5 * math.cos(math.pi * linear_t)

        x, y = _bezier_point(
            (start_x, start_y),
            cp1,
            cp2,
            (end_x, end_y),
            t,
        )
        pyautogui.moveTo(x, y)

        base_sleep = duration / steps
        jitter = base_sleep * random.uniform(0.7, 1.3)
        time.sleep(jitter)

    wobble_times = random.randint(2, 4)
    wobble_radius = max(0.5, jitter_px * 0.6)
    for _ in range(wobble_times):
        wobble_x = end_x + random.uniform(-wobble_radius, wobble_radius)
        wobble_y = end_y + random.uniform(-wobble_radius, wobble_radius)
        pyautogui.moveTo(wobble_x, wobble_y)
        time.sleep(random.uniform(0.02, 0.08))
    pyautogui.moveTo(end_x, end_y)


_RECT_JS = """
const el = arguments[0];
const r = el.getBoundingClientRect();
const contentX = window.screenX + (window.outerWidth - window.innerWidth) / 2;
const contentY = window.screenY + (window.outerHeight - window.innerHeight);
return {
    left: r.left, top: r.top, width: r.width, height: r.height,
    absOffsetX: contentX, absOffsetY: contentY,
    url: window.location.href
};
"""


def _get_element_rect(driver, element) -> dict:
    return driver.execute_script(_RECT_JS, element)


def human_move_click_element(
    driver, element, label="unknown", scroll: bool = True, jitter_px: float = 2.0
) -> None:
    if scroll:
        driver.execute_script(
            "arguments[0].scrollIntoView({block: 'center', inline: 'center', behavior: 'instant'});",
            element,
        )
        human_pause(0.3, 0.3)

    rect = _get_element_rect(driver, element)

    margin_w = rect["width"] * 0.2
    margin_h = rect["height"] * 0.2
    inner_x = random.uniform(margin_w, rect["width"] - margin_w)
    inner_y = random.uniform(margin_h, rect["height"] - margin_h)

    target_abs_x = rect["left"] + inner_x + rect["absOffsetX"]
    target_abs_y = rect["top"] + inner_y + rect["absOffsetY"]

    log_file = "click_statistics.csv"
    log_data = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "url": rect["url"],
        "label": label,
        "internal_x": round(inner_x, 2),
        "internal_y": round(inner_y, 2),
        "btn_w": round(rect["width"], 1),
        "btn_h": round(rect["height"], 1),
    }

    is_new = not os.path.exists(log_file)
    with open(log_file, "a", encoding="utf-8", newline="") as f:
        pd.DataFrame([log_data]).to_csv(f, header=is_new, index=False)

    print(
        f"[ロックマン.exe] 内部座標でターゲティング完了: {label}"
        f" ({log_data['internal_x']}, {log_data['internal_y']})"
        f" btn=({log_data['btn_w']}x{log_data['btn_h']})"
    )

    move_mouse_human(target_abs_x, target_abs_y, jitter_px=jitter_px)
    human_pause(0.2, 0.2)

    fresh_rect = _get_element_rect(driver, element)
    final_x = fresh_rect["left"] + inner_x + fresh_rect["absOffsetX"]
    final_y = fresh_rect["top"] + inner_y + fresh_rect["absOffsetY"]
    pyautogui.moveTo(final_x, final_y)
    pyautogui.click()
