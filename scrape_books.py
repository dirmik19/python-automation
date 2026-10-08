"""books.toscrape.com から書籍のタイトル・価格・在庫状況を収集し、Markdown に保存するスクリプト。

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
from bs4 import BeautifulSoup

# OS の証明書ストアで SSL 検証する(セキュリティソフトの HTTPS 検査環境でも検証を有効なまま接続できる)
truststore.inject_into_ssl()

BASE_URL = "https://books.toscrape.com/"
USER_AGENT = "python-automation-scraper/1.0"
TIMEOUT_SECONDS = 10
WAIT_RANGE_SECONDS = (1.0, 3.0)

PROJECT_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = PROJECT_DIR / "output"
LOG_DIR = PROJECT_DIR / "logs"

logger = logging.getLogger("scrape_books")


def setup_logging() -> None:
    """コンソールとログファイルの両方に出力するようロガーを設定する。"""
    LOG_DIR.mkdir(exist_ok=True)
    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")

    file_handler = logging.FileHandler(LOG_DIR / "scrape_books.log", encoding="utf-8")
    file_handler.setFormatter(formatter)
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    logger.setLevel(logging.INFO)
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)


class PoliteSession:
    """robots.txt の遵守とリクエスト間のランダム待機を行う HTTP セッション。"""

    def __init__(self, base_url: str) -> None:
        self.session = requests.Session()
        self.session.headers["User-Agent"] = USER_AGENT
        self.robots = RobotFileParser()
        self.has_requested = False
        self._load_robots(urljoin(base_url, "/robots.txt"))

    def _wait(self) -> None:
        """2 回目以降のリクエストの前に 1〜3 秒ランダムに待機する。"""
        if self.has_requested:
            seconds = random.uniform(*WAIT_RANGE_SECONDS)
            logger.info("%.1f 秒待機します", seconds)
            time.sleep(seconds)
        self.has_requested = True

    def _load_robots(self, robots_url: str) -> None:
        """robots.txt を取得して解析する。存在しない(4xx)場合は全パス許可として扱う。"""
        logger.info("robots.txt を取得します: %s", robots_url)
        response = self._request(robots_url, check_robots=False)

        if response.status_code == 200:
            self.robots.parse(response.text.splitlines())
            logger.info("robots.txt を読み込みました")
        elif 400 <= response.status_code < 500:
            # robots.txt が存在しない場合は制限なし(一般的な慣例に従う)
            self.robots.allow_all = True
            logger.info("robots.txt が見つかりません(HTTP %d)。全パス許可として扱います", response.status_code)
        else:
            # サーバーエラー時は安全側に倒して全パス禁止とする
            self.robots.disallow_all = True
            logger.warning("robots.txt を取得できません(HTTP %d)。全パス禁止として扱います", response.status_code)

    def _request(self, url: str, check_robots: bool = True) -> requests.Response:
        """待機後に GET リクエストを送る。接続エラー時はログを出力して終了する。"""
        self._wait()
        try:
            response = self.session.get(url, timeout=TIMEOUT_SECONDS)
        except requests.exceptions.RequestException as e:
            logger.error("接続エラーが発生しました: %s (%s)", url, e)
            sys.exit(1)
        if check_robots:
            response.raise_for_status()
        return response

    def can_fetch(self, url: str) -> bool:
        """robots.txt で URL へのアクセスが許可されているか判定する。"""
        return self.robots.can_fetch(USER_AGENT, url)

    def get(self, url: str) -> requests.Response | None:
        """robots.txt で許可されている場合のみ取得する。禁止されていれば None を返す。"""
        if not self.can_fetch(url):
            logger.warning("robots.txt で禁止されているためスキップします: %s", url)
            return None
        logger.info("取得中: %s", url)
        try:
            return self._request(url)
        except requests.exceptions.HTTPError as e:
            logger.error("HTTP エラーが発生しました: %s (%s)", url, e)
            sys.exit(1)


def parse_books(html: str) -> list[dict[str, str]]:
    """一覧ページの HTML から書籍のタイトル・価格・在庫状況を抽出する。"""
    soup = BeautifulSoup(html, "html.parser")
    books = []
    for article in soup.select("article.product_pod"):
        books.append({
            "title": article.select_one("h3 a")["title"],
            "price": article.select_one("p.price_color").get_text(strip=True),
            "availability": article.select_one("p.availability").get_text(strip=True),
        })
    return books


def find_next_page(html: str, current_url: str) -> str | None:
    """「next」リンクがあれば次ページの絶対 URL を返す。"""
    soup = BeautifulSoup(html, "html.parser")
    next_link = soup.select_one("li.next a")
    return urljoin(current_url, next_link["href"]) if next_link else None


def scrape(max_pages: int | None) -> list[dict[str, str]]:
    """一覧ページを順にたどって全書籍の情報を収集する。"""
    client = PoliteSession(BASE_URL)
    books: list[dict[str, str]] = []
    url: str | None = BASE_URL
    page = 0

    while url and (max_pages is None or page < max_pages):
        response = client.get(url)
        if response is None:
            break
        response.encoding = "utf-8"
        page += 1
        page_books = parse_books(response.text)
        books.extend(page_books)
        logger.info("%d ページ目: %d 件取得(累計 %d 件)", page, len(page_books), len(books))
        url = find_next_page(response.text, url)

    return books


def escape_markdown_cell(text: str) -> str:
    """Markdown の表を崩さないよう、セル内の | をエスケープする。"""
    return text.replace("|", "\\|")


def save_markdown(books: list[dict[str, str]], date: datetime) -> Path:
    """収集結果を Markdown の表として books_YYYYMMDD.md に保存する。"""
    OUTPUT_DIR.mkdir(exist_ok=True)
    path = OUTPUT_DIR / f"books_{date:%Y%m%d}.md"

    lines = [
        f"# 書籍一覧({date:%Y-%m-%d})",
        "",
        f"- 取得元: {BASE_URL}",
        f"- 取得日時: {date:%Y-%m-%d %H:%M:%S}",
        f"- 件数: {len(books)} 件",
        "",
        "| No. | タイトル | 価格 | 在庫状況 |",
        "| ---: | --- | ---: | --- |",
    ]
    for i, book in enumerate(books, start=1):
        lines.append(
            f"| {i} | {escape_markdown_cell(book['title'])} "
            f"| {book['price']} | {book['availability']} |"
        )

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description="books.toscrape.com の書籍情報を収集します")
    parser.add_argument("--max-pages", type=int, default=None, help="取得する最大ページ数(省略時は全ページ)")
    args = parser.parse_args()

    setup_logging()
    started_at = datetime.now()
    logger.info("スクレイピングを開始します")

    books = scrape(args.max_pages)
    path = save_markdown(books, started_at)
    logger.info("%d 件を保存しました: %s", len(books), path)


if __name__ == "__main__":
    main()
