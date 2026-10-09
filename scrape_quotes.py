"""quotes.toscrape.com/js から名言のテキストと著者名を Playwright で収集し、Markdown とスクリーンショットに保存するスクリプト。

- JavaScript で描画されるページのため、ブラウザ(画面表示あり)で描画後の DOM から取得する
- robots.txt を読み込み、禁止されたパスにはアクセスしない
- リクエスト間に 1〜3 秒のランダムな待機時間を設ける
- 接続エラー時はログにエラーメッセージを出力して終了する
"""

import argparse
import logging
import random
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin
from urllib.robotparser import RobotFileParser

import requests
import truststore
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Page, sync_playwright

# OS の証明書ストアで SSL 検証する(セキュリティソフトの HTTPS 検査環境でも検証を有効なまま接続できる)
truststore.inject_into_ssl()

START_URL = "https://quotes.toscrape.com/js/"
USER_AGENT = "python-automation-scraper/1.0"
TIMEOUT_SECONDS = 10
WAIT_RANGE_SECONDS = (1.0, 3.0)

PROJECT_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = PROJECT_DIR / "output"
LOG_DIR = PROJECT_DIR / "logs"

logger = logging.getLogger("scrape_quotes")


def setup_logging() -> None:
    """コンソールとログファイルの両方に出力するようロガーを設定する。"""
    LOG_DIR.mkdir(exist_ok=True)
    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")

    file_handler = logging.FileHandler(LOG_DIR / "scrape_quotes.log", encoding="utf-8")
    file_handler.setFormatter(formatter)
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    logger.setLevel(logging.INFO)
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)


def random_wait() -> None:
    """リクエスト間で 1〜3 秒ランダムに待機する。"""
    seconds = random.uniform(*WAIT_RANGE_SECONDS)
    logger.info("%.1f 秒待機します", seconds)
    time.sleep(seconds)


def load_robots(url: str) -> RobotFileParser:
    """robots.txt を取得して解析する。存在しない(4xx)場合は全パス許可として扱う。"""
    robots_url = urljoin(url, "/robots.txt")
    robots = RobotFileParser()
    logger.info("robots.txt を取得します: %s", robots_url)
    try:
        response = requests.get(robots_url, headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT_SECONDS)
    except requests.exceptions.RequestException as e:
        logger.error("接続エラーが発生しました: %s (%s)", robots_url, e)
        sys.exit(1)

    if response.status_code == 200:
        robots.parse(response.text.splitlines())
        logger.info("robots.txt を読み込みました")
    elif 400 <= response.status_code < 500:
        # robots.txt が存在しない場合は制限なし(一般的な慣例に従う)
        robots.allow_all = True
        logger.info("robots.txt が見つかりません(HTTP %d)。全パス許可として扱います", response.status_code)
    else:
        # サーバーエラー時は安全側に倒して全パス禁止とする
        robots.disallow_all = True
        logger.warning("robots.txt を取得できません(HTTP %d)。全パス禁止として扱います", response.status_code)
    return robots


def open_page(page: Page, url: str) -> None:
    """ページを開き、名言が描画されるまで待つ。接続エラー時はログを出力して終了する。"""
    logger.info("取得中: %s", url)
    try:
        response = page.goto(url, timeout=TIMEOUT_SECONDS * 1000)
        if response is not None and not response.ok:
            logger.error("HTTP エラーが発生しました: %s (HTTP %d)", url, response.status)
            sys.exit(1)
        page.wait_for_selector("div.quote", timeout=TIMEOUT_SECONDS * 1000)
    except PlaywrightError as e:
        logger.error("接続エラーが発生しました: %s (%s)", url, e.message.splitlines()[0])
        sys.exit(1)


def parse_quotes(page: Page) -> list[dict[str, str]]:
    """描画済みのページから名言のテキストと著者名を抽出する。"""
    quotes = []
    for quote in page.locator("div.quote").all():
        quotes.append({
            "text": quote.locator("span.text").inner_text().strip(),
            "author": quote.locator("small.author").inner_text().strip(),
        })
    return quotes


def find_next_page(page: Page) -> str | None:
    """「Next」リンクがあれば次ページの絶対 URL を返す。"""
    next_link = page.locator("li.next a")
    if next_link.count() == 0:
        return None
    return urljoin(page.url, next_link.get_attribute("href"))


def scrape(max_pages: int | None, screenshot_path: Path) -> list[dict[str, str]]:
    """ブラウザを画面表示で起動し、ページを順にたどって名言を収集する。1 ページ目のスクリーンショットも保存する。"""
    robots = load_robots(START_URL)
    quotes: list[dict[str, str]] = []
    url: str | None = START_URL
    page_count = 0

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        try:
            page = browser.new_page(user_agent=USER_AGENT)
            while url and (max_pages is None or page_count < max_pages):
                if not robots.can_fetch(USER_AGENT, url):
                    logger.warning("robots.txt で禁止されているためスキップします: %s", url)
                    break
                # robots.txt 取得後の 1 ページ目も含め、すべてのリクエストの前に待機する
                random_wait()
                open_page(page, url)
                page_count += 1

                if page_count == 1:
                    page.screenshot(path=screenshot_path, full_page=True)
                    logger.info("スクリーンショットを保存しました: %s", screenshot_path)

                page_quotes = parse_quotes(page)
                quotes.extend(page_quotes)
                logger.info("%d ページ目: %d 件取得(累計 %d 件)", page_count, len(page_quotes), len(quotes))
                url = find_next_page(page)
        finally:
            browser.close()

    return quotes


def escape_markdown_cell(text: str) -> str:
    """Markdown の表を崩さないよう、セル内の | をエスケープし改行を空白にする。"""
    return text.replace("|", "\\|").replace("\n", " ")


def save_markdown(quotes: list[dict[str, str]], date: datetime, path: Path) -> None:
    """収集結果を Markdown の表として保存する。"""
    lines = [
        f"# 名言一覧({date:%Y-%m-%d})",
        "",
        f"- 取得元: {START_URL}",
        f"- 取得日時: {date:%Y-%m-%d %H:%M:%S}",
        f"- 件数: {len(quotes)} 件",
        "",
        "| No. | 名言 | 著者 |",
        "| ---: | --- | --- |",
    ]
    for i, quote in enumerate(quotes, start=1):
        lines.append(f"| {i} | {escape_markdown_cell(quote['text'])} | {escape_markdown_cell(quote['author'])} |")

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="quotes.toscrape.com/js の名言を収集します")
    parser.add_argument("--max-pages", type=int, default=None, help="取得する最大ページ数(省略時は全ページ)")
    args = parser.parse_args()

    setup_logging()
    started_at = datetime.now()
    OUTPUT_DIR.mkdir(exist_ok=True)
    markdown_path = OUTPUT_DIR / f"quotes_{started_at:%Y%m%d}.md"
    screenshot_path = OUTPUT_DIR / f"quotes_{started_at:%Y%m%d}.png"
    logger.info("スクレイピングを開始します")

    quotes = scrape(args.max_pages, screenshot_path)
    save_markdown(quotes, started_at, markdown_path)
    logger.info("%d 件を保存しました: %s", len(quotes), markdown_path)


if __name__ == "__main__":
    main()
