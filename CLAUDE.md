# CLAUDE.md

このファイルは、本リポジトリで作業する Claude Code 向けのガイドです。

## プロジェクト概要

- **プロジェクト名**: python-automation
- **目的**: Python による各種作業の自動化スクリプト群
- **言語**: Python 3

## コミュニケーション

- 返答・説明・コードコメントは**必ず日本語**で行うこと。

## 開発環境

- OS: Windows 11
- 仮想環境の利用を推奨:
  ```bash
  python -m venv .venv
  .venv\Scripts\activate        # PowerShell / cmd
  source .venv/Scripts/activate # Git Bash
  ```
- 依存パッケージは `requirements.txt` で管理し、追加したら必ず更新する:
  ```bash
  pip install -r requirements.txt
  pip freeze > requirements.txt
  ```

## コーディング規約

- PEP 8 に準拠する。
- 関数・クラスには日本語の docstring を付ける。
- パスワードや API キーなどの機密情報はコードに直接書かず、`.env` ファイルや環境変数で管理する（`.env` は `.gitignore` に含める）。
- ファイルパスはプロジェクト外の絶対パスをハードコードせず、`pathlib` を使って扱う。

## Git 運用ルール

- **コードを変更するたびに、コミットして GitHub にプッシュすること。**
  ```bash
  git add <変更したファイル>
  git commit -m "変更内容の要約"
  git push
  ```
- コミットメッセージは日本語で、何を・なぜ変更したかを簡潔に書く。
- 1 コミットにつき 1 つのまとまった変更にする。
- `.env`、`.venv/`、`__pycache__/`、ログファイルなど機密情報や生成物はコミットしない。
- プッシュ前に、スクリプトがエラーなく動作することを確認する。
