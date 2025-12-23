# reportgen_v1

地質調査報告書の自動生成ツールと、国土地理院/国交省データを併用したレポート補助機能の試作リポジトリです。

## 最近の更新（2025-12-24）
- GUI を整理し、XML/PDF/テンプレ/出力先のドラッグ＆ドロップを追加
- 同梱テンプレの自動探索とユーザー上書きテンプレの優先読み込みに対応
- OpenAI を使った自由記述生成を GUI から ON/OFF・モデル選択できるようにし、自動モデル一覧取得を追加
- 5万図簿冊ダウンロードパネルを追加し、インデックス自動検出・住所フォールバック・保存先/候補数の環境変数をサポート

## GUI の使い方（MVP）
1. 起動: `python -m src.reportgen.gui.app`  
   - 既定出力先: `./output/生成_報告書.docx`（環境変数 `REPORTGEN_OUT_DIR` で変更可）
2. 入力:  
   - XML（必須）をドラッグ＆ドロップまたは「参照」で指定  
   - 液状化判定 PDF（任意）を指定すると報告書に反映  
   - テンプレート未指定なら同梱テンプレを自動セット
3. オプション:  
   - `生成後に出力ファイルを開く` を必要に応じて ON  
   - `AI 文章生成（実験）` を ON にすると自由記述を OpenAI API で生成
4. `報告書を生成` をクリックして DOCX を出力

### AI 文章生成（任意）
- チェックボックスを ON にし、`API キー` に OpenAI キーを入力（未入力時は既定文を使用）
- モデルはプルダウンから選択（`REPORTGEN_AI_MODEL` で既定指定可）。GUI 起動時に gpt-* 系を自動列挙します。

### テンプレートの探索順
1. GUI で明示したパス  
2. 環境変数 `REPORTGEN_TEMPLATE_PATH`  
3. ユーザー領域 `%APPDATA%/ReportGen/templates/報告書_ひな形_v2.docx`（存在すれば、同梱より新しければ優先）  
4. 同梱テンプレ `reportgen/templates/報告書_ひな形_v2.docx`（フォールバックで `bk/` も参照）

### 5万図簿冊ダウンロード（GUI）
- `図幅インデックスファイル` は `data/indices/50k_index.gpkg / .geojson` を自動検出。無い場合は手動指定してください。
- XML に座標があればそれを使用、無ければ `住所（任意）` を手入力すると簡易ジオコーディング（スタブ）にフォールバックします。
- 保存設定（環境変数で上書き可）  
  - `REPORTGEN_BOOKLET_OUTDIR` … 簿冊の保存先（既定: `./booklets`）  
  - `REPORTGEN_BOOKLET_CANDIDATES` … 候補取得数（既定: 2）  
  - `REPORTGEN_BOOKLET_BUFFER` … ポリゴン検索のバッファ距離 m（既定: 200）  
  - `REPORTGEN_BOOKLET_CODE_FIELD` / `REPORTGEN_BOOKLET_NAME_FIELD` … インデックスの属性名
- 取得後の結果と出典情報は右ペインに表示されます。`候補をすべて保存` を ON にすると最優先以外も保存します。

## 5万図インデックス生成フロー

1. **四隅座標の取得**  
   - `tools/scrape_gsi_50k_corners.py` が国土地理院サイト（5万・2.5万 対照表）を巡回し、5万図葉ごとの四隅緯度経度を `tmp/50k_corners.csv` に書き出します。  
   - オフライン環境のため DNS 解決で失敗し、現状は 10 図葉分のダミー座標（`offline-sample`）で `tmp/50k_corners.csv` を作成しています。オンライン環境では次のコマンドで全量取得してください。  
     ```bash
     python tools/scrape_gsi_50k_corners.py --out tmp/50k_corners.csv --log
     ```
2. **ポリゴン化と検証**  
   - `tools/build_50k_index.py` が CSV を読み込み、UL→UR→LR→LL→UL のポリゴンを生成、自己交差補正・面積検査を実施して GeoJSON/GPKG/メタ情報を `data/indices/` に出力します。  
   - 実行例（今回の暫定デモでも実行済み）  
     ```bash
     python tools/build_50k_index.py \
       --src tmp/50k_corners.csv \
       --datum wgs84 \
       --out-dir data/indices \
       --layer-name index_50k \
       --source-text "GSI 5万/2.5万 対照表(索引図)" \
       --source-url "https://www.gsi.go.jp/MAP/NEWOLDBL/25000-50000/index25000-50000.html"
     ```
   - 結果ファイル  
     - `data/indices/50k_index.geojson`  
     - `data/indices/50k_index.gpkg`（レイヤ名 `index_50k`）  
     - `data/indices/50k_index_meta.json`（作成日時/出典URL/件数サマリ等）

> **補足**: 現在の `50k_index.*` は 10 図葉だけのサンプルです。ネットワークに接続できる環境で再度スクレイプ→ビルドを実行し、全国分に更新してください。

## 簿冊PDF（t.pdf）の取得

- 本来は `https://nlftp.mlit.go.jp/kokjo/tochimizu/F3/data/pdf/{code}t.pdf` から直接ダウンロードします。  
- オフライン環境のため、`data/booklets/2806t.pdf` は Pillow で生成したプレースホルダPDFです。  
- `data/booklets/manifest.json` に MD5/サイズ/ステータスを記録してあるので、ネットワーク接続後に本物の t.pdf へ差し替えてください。ダウンロードコマンド例：
  ```bash
  curl -o data/booklets/2806t.pdf \
       https://nlftp.mlit.go.jp/kokjo/tochimizu/F3/data/pdf/2806t.pdf
  ```
  取得後に `manifest.json` を更新し、`status` を `downloaded` に変更してください。

## GUI からの利用

- `src/reportgen/gui/app.py` は `data/indices/50k_index.*` を自動検出し、ボーリングXMLの座標→図幅候補→簿冊ダウンロード（オフライン時はプレースホルダ）を実行します。  
- インデックスを全国版へ差し替えた後は、GUI 側に追加実装済みの「5万図簿冊ダウンロード」パネルからそのまま利用できます。

## 出典

- 5万図 四隅緯度経度: 国土地理院「5万・2.5万 地形図の新旧緯度・経度対照表（索引図）」  
  <https://www.gsi.go.jp/MAP/NEWOLDBL/25000-50000/index25000-50000.html>  
- 土地分類基本調査（簿冊 t.pdf）: 国土数値情報（国土交通省国土政策局国土情報課）  
  <https://nlftp.mlit.go.jp/kokjo/tochimizu/F3/>  

最新更新日: 2025-12-24 （オフラインデモ版）
