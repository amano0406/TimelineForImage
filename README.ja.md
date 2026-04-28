# TimelineForImage

`TimelineForImage` は、ローカル画像ファイルをタイムライン形式の Markdown / JSON / ZIP に変換する CLI ツールです。ChatGPT などの LLM に渡しやすい成果物を作ることを目的にしています。

ローカルファーストで動作し、元画像は編集しません。

## 現在の範囲

初期版ではホスト側の依存を軽く保ち、モデル依存は Docker Compose の worker に寄せます。現時点で次の情報を抽出します。

- 元画像パス
- SHA-256
- ファイルサイズ
- 画像形式
- 幅と高さ
- EXIF 撮影日時
- EXIF カメラメーカー、カメラ機種、レンズ、焦点距離、GPS 座標
- 撮影日時がない場合のファイル更新日時
- 寸法や日時が取れない場合の警告
- 既定の Docker Compose worker 内 Hugging Face image-to-text
- Docker Compose worker 内 Tesseract によるローカル OCR
- caption / OCR から作る派生 visual observations
- 日付単位の timeline grouping
- JSON ファイルから渡す human annotations
- テスト用の mock caption
- `--caption-mode openai` と `OPENAI_API_KEY` による OpenAI caption

人物の本人特定や顔認識はまだ行いません。

## 基本操作

通常の CLI 実行は Docker Compose worker 内だけ許可しています。ホストの Python で直接 `python -m timeline_for_image_worker ...` を実行すると失敗します。

Windows では PowerShell の `start.ps1` を正面玄関にします。

```powershell
.\start.ps1 discover --directory C:\path\to\images
.\start.ps1 run --directory C:\path\to\images
```

`start.bat` は互換用 shim として `start.ps1` に処理を渡します。WSL/Linux では裏口として `./start.command` を残します。

Docker Compose を直接呼ぶ低レベルな形式も使えます。

```bash
docker compose --profile worker run --rm worker discover --directory /mnt/c/path/to/images
```

```bash
docker compose --profile worker run --rm worker run --directory /mnt/c/path/to/images --format json
```

成果物は `TimelineForImage-export.zip` にまとめられます。元画像は ZIP に含めません。

## ソース管理

複数の入力ディレクトリをマスターソースとして登録できます。

```bash
docker compose --profile worker run --rm worker sources add /mnt/c/path/to/images

docker compose --profile worker run --rm worker sources list
```

登録後は `--directory` なしで `discover` / `create-job` / `run` を実行できます。

`settings.json` の `sources` でも複数入力を指定できます。`recursive` は source ごとに効きます。

```json
{
  "sources": [
    {
      "path": "C:\\Users\\amano\\Pictures\\",
      "recursive": true
    },
    {
      "path": "C:\\Users\\amano\\Desktop\\camera-import\\",
      "recursive": false
    }
  ]
}
```

各 run では master catalog と比較し、`new` / `changed` / `unchanged` を記録します。基本処理プロファイルは `metadata-v2` で、caption / OCR の mode と model も有効プロファイルに含めます。

caption / OCR / visual observations の派生成果物は、設定済み state root の `derived_cache.json` に保存します。画像 SHA-256 と processing profile が一致する場合は再生成せず再利用します。

## Settings

永続的な設定は repo 直下の `settings.json` で管理します。`settings.example.json` はテンプレートとして Git 管理し、`settings.json` はローカル専用として Git 管理しません。

`settings.json` がない場合は生成できます。

```bash
docker compose --profile worker run --rm worker settings init
```

現在の既定設定:

```json
{
  "sources": [
    {
      "path": "C:\\Users\\amano\\Pictures\\",
      "recursive": true
    }
  ],
  "outputs_root": "C:\\Users\\amano\\image\\",
  "appdata_root": "C:\\Users\\amano\\image\\.timeline-for-image-state",
  "caption": {
    "mode": "local",
    "model": "Salesforce/blip-image-captioning-base"
  },
  "ocr": {
    "mode": "auto",
    "model": "tesseract:eng+jpn"
  },
  "watch": {
    "interval_seconds": 30,
    "min_quiet_seconds": 2
  },
  "mock": false
}
```

Docker/Linux 上では `C:\...` のパスを `/mnt/c/...` に自動変換します。Compose worker は `settings.json` を読んで起動します。

worker コンテナ内では C ドライブを常に `/mnt/c` として見せます。Windows PowerShell の正面玄関では Docker bind source を `C:\` に設定し、WSL/Linux の裏口では `/mnt/c` を既定にします。出力 bind source は Windows では `C:\Users\amano\image\`、WSL/Linux では `/mnt/c/Users/amano/image` が既定です。C ドライブ以外を入力または出力にする場合は、`TIMELINE_FOR_IMAGE_C_DRIVE_MOUNT` / `TIMELINE_FOR_IMAGE_OUTPUT_MOUNT` を設定するか、`docker-compose.yml` に追加 mount が必要です。

```bash
docker compose --profile worker up worker
```

運用前チェック:

```bash
docker compose --profile worker run --rm worker doctor --format json
```

`doctor` は settings の存在、入力 source の可視性、出力/state の書込可否、Docker 実行ガード、Hugging Face local backend、Tesseract OCR 言語を確認します。

## Watch と latest 出力

`watch` は sources をスキャンし、現在の processing profile に対して新規または変更された画像がある場合だけ run を作成します。

```bash
docker compose --profile worker run --rm worker watch \
  --directory /mnt/c/path/to/images \
  --once \
  --min-quiet-seconds 0
```

`settings.json` を使う場合:

```bash
docker compose --profile worker run --rm worker watch \
  --once
```

`--once` を外すと `--interval-seconds` ごとに繰り返します。`--min-quiet-seconds` は書き込み中のファイルを処理しないための待機時間です。

完了した `run` / `watch` は `<outputs-root>/latest/` を更新します。

- `latest/timeline.md`
- `latest/result.json`
- `latest/TimelineForImage-export.zip`

## 画像説明

初期段階では、外部 API ではなく Docker Compose の worker コンテナ内で Hugging Face の `image-to-text` モデルを動かす構成を既定にしています。

```bash
docker compose --profile worker run --rm worker run --directory /mnt/c/path/to/images
```

既定値:

- 画像説明 model: `Salesforce/blip-image-captioning-base`
- OCR engine: `tesseract:eng+jpn`

Docker Compose の worker から実行する例:

```bash
docker compose --profile worker run --rm worker doctor
docker compose --profile worker run --rm worker run --directory /mnt/c/path/to/images
```

Windows の正面玄関は `start.ps1` です。`start.bat` は互換用 shim、`start.command` は WSL/Linux 用の裏口として Compose worker を呼び出します。

上書き:

```bash
TIMELINE_FOR_IMAGE_LOCAL_MODEL=Salesforce/blip-image-captioning-base \
TIMELINE_FOR_IMAGE_OCR_MODEL=tesseract:eng+jpn \
docker compose --profile worker run --rm worker run --directory /mnt/c/path/to/images
```

日本語説明や OCR 精度は、今後のモデル比較・評価対象にします。

テスト用には mock caption を使えます。

```bash
docker compose --profile worker run --rm worker run \
  --directory /mnt/c/path/to/images \
  --caption-mode mock
```

API キーがある場合は OpenAI で画像説明を生成できます。

```bash
OPENAI_API_KEY=... \
docker compose --profile worker run --rm worker run \
  --directory /mnt/c/path/to/images \
  --caption-mode openai
```

caption は `captions.json` と `timeline.md` に入ります。EXIF のような観測事実ではなく、AI 由来の推定情報として扱います。

## OCR

OCR は画像説明とは別レイヤーです。

既定は `--ocr-mode auto` です。

1. worker コンテナ内のローカル OCR を実行する
2. 現在の auto mode では、OCR 結果が空でない場合を true として扱う
3. `ocr.json` に保存する
4. `timeline.md` に OCR 判定と抽出結果を載せる

モード:

- `--ocr-mode off`
- `--ocr-mode auto`
- `--ocr-mode always`
- `--ocr-mode mock`

OCR 判定と OCR 結果は AI 由来の推定情報です。誤りうるため、レビュー対象として扱います。

## Visual Observations / Grouping / Annotations

`visual_observations.json` は caption と OCR から作る派生情報です。現時点では次のような粗い構造化情報を出します。

- 人物が写っていそうか
- 文字があるか
- 場所のヒント
- 物体キーワード
- 活動キーワード

`timeline_groups.json` は現時点では day / sequence / event / location グループを出します。sequence は隣接する timeline timestamp が 10 分以内の場合に作ります。event は手動注釈の `event` が一致する画像をまとめます。location は GPS 座標が 250m 以内の画像をまとめます。より高度なイベント推定は今後の拡張対象です。

手動注釈は `--annotations-file` で指定できます。

```json
{
  "annotations": [
    {
      "relative_path": "sample.png",
      "tags": ["receipt"],
      "people": ["person name"],
      "event": "trip",
      "note": "manual note"
    }
  ]
}
```

注釈は `annotations.json` にコピーし、`timeline.md` にも表示します。

## テスト

テストは worker コンテナ内で実行します。ホスト直実行は、テスト時に `TIMELINE_FOR_IMAGE_ALLOW_HOST_CLI=1` を明示した場合だけ例外として許可します。

```bash
docker compose --profile worker run --rm --entrypoint sh worker -c \
  "pip install --no-cache-dir pytest >/tmp/pip-test.log && PYTHONPATH=/app/worker/src python -m pytest /app-config/worker/tests"
```
