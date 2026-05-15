# Testing

[Back to README](../README.md)

Use these checks after changing code, CLI contracts, output contracts, Docker behavior, or documentation that affects commands.

## Worker Unit Tests

```powershell
cd C:\apps\TimelineForImage
docker compose run --rm --entrypoint sh worker -c "pip install --no-cache-dir -r /workspace/worker/requirements-dev.txt >/tmp/pip-test.log && PYTHONPATH=/workspace/worker/src python -m pytest /workspace/worker/tests -q"
```

This command intentionally uses an isolated test container. Product CLI commands should go through the resident worker started by `cli.ps1` or `start.ps1`.

## Local CLI Download Test

```powershell
cd C:\apps\TimelineForImage
python -m unittest discover -s tests -p test_cli_ps1_download.py
```

This test calls `cli.ps1` from the local host and confirms download ZIP generation.

## Health Endpoint Build

```powershell
cd C:\apps\TimelineForImage
dotnet build health\TimelineForImage.Health\TimelineForImage.Health.csproj
```

The health endpoint is the only C# HTTP surface. It serves `GET /health` and
returns a JSON boolean.

## Operational Test

```powershell
cd C:\apps\TimelineForImage
.\scripts\test-operational.ps1
```

The operational test creates temporary settings, input, output, and state paths. It does not use the root `settings.json`.

Keep output for inspection:

```powershell
.\scripts\test-operational.ps1 -KeepOutput
```

## Lightweight Static Checks

```powershell
python -m json.tool schemas\settings.schema.json > $null
python -m json.tool schemas\image_record.schema.json > $null
python -m json.tool settings.example.json > $null
python -m json.tool timeline-product.json > $null
git diff --check
```
