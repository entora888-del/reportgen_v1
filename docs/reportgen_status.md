# reportgen_v1 現状整理（静的確認ベース）

> 本ドキュメントは、`reportgen_v1` リポジトリ内のソースコード・設定・成果物を静的に読み取った内容のみをまとめたものです。実行やビルドは行っていません。

## 1. プロジェクト概要

- **目的・想定フロー**  
  - ボーリングXMLと液状化判定PDFから主要メタ情報・層情報・液状化指標を解析し、Wordテンプレート（Docx）へマージして地質調査報告書を自動生成するMVP。  
  - GUI（PySide6）でファイル選択・ドラッグ&ドロップ・オプション指定ができ、生成後にログ表示とファイルオープンまで行うワークフローを備える。
- **入出力パイプライン**  
  - 入力: ボーリングXML（必須）、液状化判定PDF（任意）、Docxテンプレート（任意。未指定時は同梱テンプレを自動解決）。  
  - 出力: `generate_docx_from_template`→`docxtpl` による Docx。後続で `liquefaction_post.postprocess_liquefaction_block` が Word XML を直接編集し、液状化ブロックの数値・文字列を差し替える。
- **現状の進捗感**  
  - GUI・XML/PDFパーサ・テンプレ適用ロジック・設定ローダは実装済み。  
  - GUI補助部品(`widgets.py`)、NLFTPモジュール、ポストエディット用ファイルにはまだ中身がなく、将来拡張のプレースホルダと推測。  
  - テンプレ・サンプルDocx/PDF、スクリーンショット、生成済みDocxが揃っており、試行履歴が見える。

## 2. 環境と依存関係

- **開発環境**  
  - Python 3.10 以上 (`pyproject.toml`)。  
  - `.venv/` 以下に PySide6 他多数の依存がインストール済み。
- **主なライブラリ（`pyproject.toml` より）**  
  - GUI: `pyside6`  
  - 解析: `lxml`, `pdfplumber`, `beautifulsoup4`, `requests`（将来用途含む）  
  - 画像/テンプレ: `pillow`, `docxtpl`, `python-docx`  
  - コメントとして `tabula-py`, `pytesseract` を将来追加候補に言及。
- **ビルド/配布**  
  - `scripts/build_win.ps1` は Windows 用の仮想環境再作成・依存導入・GUI起動・テスト実行をまとめた運用スクリプト。PyInstaller ベースの配布は未着手。  
  - `build/` および `dist/` は空。今後のバンドル成果物置き場として確保済み。

## 3. アプリケーション構成（主要ディレクトリと責務）

- **GUI (`src/reportgen/gui/app.py`)**  
  - `MainWindow`（行64〜334）が UI 構成、入力検証、ログUI、ドラッグ＆ドロップ対応、テンプレ解決、PDF解析呼び出し、Docx生成、生成後の自動オープンまでを包含。  
  - `DropLine` ウィジェットがパスの正規化（`normalize_input_path`）を担う。  
  - `widgets.py` は空ファイルで、共通ウィジェットを切り出す予定地。
- **設定 (`src/reportgen/config/loader.py`, `settings.json`)**  
  - `Settings` dataclass 群が会社情報、文章テンプレ、レポート既定値（層文章の上書き含む）をモデル化。  
  - JSON 未設定項目は `_DEFAULT_SETTINGS` で初期化し、空ファイルでも安全にロードできるよう配慮。  
  - 住所や文章テンプレは実データ（兵庫県案件）で埋められており、生成レポートの文面サンプルとして利用。
- **解析 (`src/reportgen/parsers/`)**  
  - `boring_xml.py`: 表紙・報告書メタ・層構成・観察記事・SPT N値の抽出、地層ごとの見出し生成、地下水表示フォーマット化などを実装。  
  - `liquefaction_pdf.py`: `pdfplumber` でページテキストを読み、αmax=150/200/350gal ケースを抽出。Dcy/PL値から危険度を判定し、概要文章を組み立てる。
- **テンプレ適用 (`src/reportgen/wordgen/`)**  
  - `templater.py`: XML/設定値を統合し、Docxテンプレ用コンテキストを構築。層文章の整形や既定テキストの上書き、液状化サマリの初期値設定を担当。  
  - `liquefaction_post.py`: 生成後のDocx(Zip)を直接開き、液状化ブロックの式（αmax 表記、Dcy, PL, 危険度テキスト）を最終調整。  
  - `post_edit.py` は今後の追加処理用の空ファイル。
- **テンプレ/リソース**  
  - テンプレ探索 (`src/reportgen/utils/template_locator.py`) は「ユーザー指定→ユーザー領域→同梱テンプレ」の優先順で解決し、初回はユーザー領域に自動展開。  
  - アイコン画像は `src/reportgen/assets/reportgen_icon.png`。スクリーンショット（`キャプチャ*.png`）がルートにあり、UI状態の共有に利用可能。
- **その他**  
  - `src/reportgen/nlftp/fetcher.py`、`src/reportgen/logs/` はまだ未整備。  
  - `tests/test_pdf.py` のみが実装され、同梱PDFを使う液状化解析の正規化を担保。`tests/test_xml.py` は未実装。

## 4. 成果物・サンプル

- **生成済みレポート**  
  - ルート、および `src/` 直下に `生成_報告書*.docx`、`aaa.docx` など多数のサンプル出力が残っており、テンプレ改稿・品質検証の履歴を把握できる。  
  - `生成_報告書.docx` を GUI の既定保存先としても利用。
- **テンプレ・参照データ**  
  - `src/reportgen/templates/` に `報告書_ひな形_v2.docx`、`報告書_正解.docx`、`液状化判定プリントアウト.pdf`、`DATA.XML`、`液状化.DAT` などが揃い、単体テストや手動検証に利用可能。  
  - `~$報告書_ひな形_v2.docx` や `.tmp` も含まれているため、テンプレ編集時の一時ファイルが残存している点に注意。
- **スクリーンショット・補助資料**  
  - `キャプチャ.png`, `キャプチャ2.png` が UI の状態共有用に配置。  
  - `data/cache/`, `data/samples/` はまだ空で、実案件データは未投入。

## 付録: ディレクトリ構成

- 開発用の仮想環境やキャッシュ（`.venv`, `__pycache__`, `.pytest_cache`, `.codex`, `.git`, `.mypy_cache`）を除外し、主要ディレクトリとファイルをツリー表示で整理しました。  
- 同じ内容を `docs/directory_tree.txt` にも保存しています。

```
.
├── .vscode/
│   └── settings.json
├── build/
├── data/
│   ├── cache/
│   └── samples/
├── dist/
├── docs/
│   ├── directory_tree.txt
│   └── reportgen_status.md
├── scripts/
│   └── build_win.ps1
├── src/
│   ├── reportgen/
│   │   ├── assets/
│   │   │   └── reportgen_icon.png
│   │   ├── config/
│   │   │   ├── loader.py
│   │   │   └── settings.json
│   │   ├── gui/
│   │   │   ├── app.py
│   │   │   └── widgets.py
│   │   ├── logs/
│   │   ├── nlftp/
│   │   │   └── fetcher.py
│   │   ├── parsers/
│   │   │   ├── boring_xml.py
│   │   │   └── liquefaction_pdf.py
│   │   ├── templates/
│   │   │   ├── bk/
│   │   │   │   ├── 報告書_ひな形.docx
│   │   │   │   ├── 報告書_ひな形_v2.docx
│   │   │   │   └── 報告書_ひな形_v2_fixed.docx
│   │   │   ├── DATA.XML
│   │   │   ├── ~$書_ひな形_v2.docx
│   │   │   ├── 報告書_ひな形_v2.docx
│   │   │   ├── 報告書_ひな形_v2_working.tmp
│   │   │   ├── 報告書_正解.docx
│   │   │   ├── 液状化.DAT
│   │   │   └── 液状化判定プリントアウト.pdf
│   │   ├── utils/
│   │   │   ├── pathnorm.py
│   │   │   └── template_locator.py
│   │   ├── wordgen/
│   │   │   ├── liquefaction_post.py
│   │   │   ├── post_edit.py
│   │   │   └── templater.py
│   │   └── __init__.py
│   ├── reportgen.egg-info/
│   │   ├── dependency_links.txt
│   │   ├── PKG-INFO
│   │   ├── requires.txt
│   │   ├── SOURCES.txt
│   │   └── top_level.txt
│   ├── aaaa
│   ├── 生成_報告書_5.docx
│   ├── 生成_報告書_6.docx
│   ├── 生成_報告書_7.docx
│   └── 生成_報告書_8.docx
├── tests/
│   ├── test_pdf.py
│   └── test_xml.py
├── aaa.docx
├── pyproject.toml
├── ~$生成_報告書.docx
├── キャプチャ.png
├── キャプチャ2.png
├── 生成_報告書.docx
├── 生成_報告書_10.docx
├── 生成_報告書_11.docx
├── 生成_報告書_12.docx
├── 生成_報告書_13.docx
├── 生成_報告書_8.docx
└── 生成_報告書_9.docx
```
