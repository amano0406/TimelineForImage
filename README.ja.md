# TimelineForImage

`TimelineForImage` は、固定入力ディレクトリ内の画像を読み取り、後段のLLMや検索で扱いやすい `image_record.json` と `timeline.json` を更新するローカル Docker-first CLI 製品です。

この製品は CLI 専用です。Web UI はありません。元画像は編集せず、出力 ZIP にも元画像は含めません。

## できること

- 固定された入力ディレクトリから画像ファイルを読む
- `source hash`、`source file identity`、`generation signature` が変わらないファイルを skip する
- EXIF、寸法、ファイル更新日時、SHA-256 を保存する
- ローカル Tesseract OCR で文字と bbox を抽出する
- 画像ごとに `image_record.json` を作る
- 画像ごとに `timeline.json` と `convert_info.json` を作る
- 色パレット、3x3色グリッド、正規化画像、OCR debug overlay を作る
- 必要に応じて handoff ZIP を作る
- 利用モデルの一覧を出し、ローカル処理範囲を確認する

## しないこと

- Web UI は提供しない
- 元画像は変更しない
- 元画像を export ZIP に含めない
- 人物の本人特定、顔認識、年齢、性別、属性推測はしない
- OCR文字列をプライバシー理由で削除・マスクしない
- 外部APIへ画像を送らない

## Settings

通常の Docker Compose 運用では、repo 直下のローカル設定ファイルを使います。

```text
C:\apps\TimelineForImage\settings.json
```

テンプレート:

```text
C:\apps\TimelineForImage\settings.example.json
```

設定例:

```json
{
  "schemaVersion": 1,
  "inputRoots": [
    "C:\\TimelineData\\input-image\\"
  ],
  "outputRoot": "C:\\TimelineData\\image",
  "appdataRoot": "C:\\TimelineData\\image\\.timeline-for-image-state",
  "ocrMode": "auto"
}
```

`ocrMode` は `auto`、`mock`、`off` のいずれかです。OCR文字列の削除・マスクは行わない固定仕様で、設定項目としては持ちません。

## Output Contract

Master output:

```text
<outputRoot>/
  items/
    <item-id>/
      convert_info.json
      timeline.json
      image_record.json
      raw_outputs/
        ocr.json
      artifacts/
        normalized_image.jpg
        debug_overlay.jpg
  downloads/
    TimelineForImage-<timestamp>.zip
  latest/
    TimelineForImage-export.zip
```

`image_record.json` が画像ごとの主成果物です。
スキーマは `schemas\image_record.schema.json` で固定しています。

```json
{
  "schema_version": "timeline_for_image.image_record.v1",
  "record_id": "image-...",
  "asset": {},
  "timeline": {},
  "image": {},
  "processing": {
    "source_image_modified": false
  },
  "quality": {},
  "classification": {},
  "text": {
    "has_text": true,
    "full_text": "...",
    "blocks": []
  },
  "visual": {},
  "layout": {
    "color_palette": [],
    "grid": [],
    "text_regions": []
  },
  "search": {},
  "review": {}
}
```

## CLI Usage

repo ルートで実行します。

```powershell
cd C:\apps\TimelineForImage
```

Windows では PowerShell が正面玄関です。

```powershell
.\start.ps1
.\cli.ps1 settings init
.\cli.ps1 settings status
.\cli.ps1 files list
.\cli.ps1 items refresh --max-items 4
.\cli.ps1 items list
.\cli.ps1 items list --page 1 --page-size 50
.\cli.ps1 items remove --item-id image-xxxxxxxxxxxxxxxx --dry-run
.\cli.ps1 items remove --item-id image-xxxxxxxxxxxxxxxx
.\cli.ps1 items download --all
.\cli.ps1 runs list
.\cli.ps1 runs list --page 1 --page-size 20
.\cli.ps1 runs show --run-id <RUN_ID>
.\cli.ps1 models list
.\cli.ps1 doctor
```

JSON 出力:

```powershell
.\cli.ps1 --json items refresh --max-items 4
```

テスト用に今回のサンプル画像を使う場合:

```powershell
.\cli.ps1 settings save `
  --input-root C:\apps\image_memory_record_demo\examples\sample_images `
  --output-root C:\TimelineData\image `
  --appdata-root C:\TimelineData\image\.timeline-for-image-state `
  --ocr-mode auto

.\cli.ps1 items refresh --max-items 4
```

## Docker Compose

Compose project name:

```text
timeline-for-image
```

worker service は Python CLI を実行します。browser port は公開しません。

## 運用上の削除

`items remove` は master item の生成物と catalog entry だけを削除します。元画像は削除しません。

削除前確認:

```powershell
.\cli.ps1 items remove --item-id image-xxxxxxxxxxxxxxxx --dry-run
```

実削除:

```powershell
.\cli.ps1 items remove --item-id image-xxxxxxxxxxxxxxxx
```

Docker resources:

- `app-data`: 製品内部の runtime data
- `cache-data`: OCRや後続モデル用 cache
- `C:\` bind mount: 入力と出力のローカルパス解決

## Testing

テストも Docker worker 内で実行します。

```powershell
cd C:\apps\TimelineForImage
docker compose run --rm --entrypoint sh worker -c "pip install --no-cache-dir -r /workspace/worker/requirements-dev.txt >/tmp/pip-test.log && PYTHONPATH=/workspace/worker/src python -m pytest /workspace/worker/tests -q"
```

`cli.ps1` をローカル入口として実際に呼び出し、`items download --all` の ZIP 生成まで確認する統合テスト:

```powershell
cd C:\apps\TimelineForImage
python -m unittest discover -s tests -p test_cli_ps1_download.py
```
