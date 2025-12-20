# reportgen_v1

地質調査報告書の自動生成ツールと、国土地理院/国交省データを併用したレポート補助機能の試作リポジトリです。

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

最新更新日: 2025-11-11 （オフラインデモ版）
