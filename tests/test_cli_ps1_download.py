from __future__ import annotations

import os
import shutil
import struct
import subprocess
import unittest
import zipfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
TEST_ROOT = REPO_ROOT / "output" / "cli-ps1-download-test"
INPUT_ROOT = TEST_ROOT / "input"
RECORDS_ROOT = TEST_ROOT / "records"
STATE_ROOT = TEST_ROOT / "state"
SETTINGS_PATH = TEST_ROOT / "settings.json"
RUNNER_PATH = TEST_ROOT / "invoke-cli.ps1"
REPO_SETTINGS_PATH = REPO_ROOT / "settings.json"
TEST_INSTANCE_NAME = "cli-ps1-test"
TEST_API_PORT = "19493"


class CliPs1DownloadTest(unittest.TestCase):
    def test_cli_ps1_download_all_from_local_host(self) -> None:
        powershell = find_powershell_command()
        if powershell is None:
            self.skipTest("PowerShell is not available on this host.")
        docker = find_docker_command()
        if docker is None:
            self.skipTest("Docker CLI is not available on this host.")

        original_settings = REPO_SETTINGS_PATH.read_bytes() if REPO_SETTINGS_PATH.exists() else None
        worker_was_running = compose_worker_running(docker, TEST_INSTANCE_NAME)
        worker_run_containers_before = worker_run_containers(docker)
        try:
            shutil.rmtree(TEST_ROOT, ignore_errors=True)
            INPUT_ROOT.mkdir(parents=True)
            (INPUT_ROOT / "sample.png").write_bytes(minimal_png(8, 6))

            run_cli_ps1(
                powershell,
                "settings",
                "save",
                "--input-root",
                to_windows_path(INPUT_ROOT),
                "--output-root",
                to_windows_path(RECORDS_ROOT),
            )
            self.assertTrue(compose_worker_running(docker, TEST_INSTANCE_NAME))
            self.assertTrue(SETTINGS_PATH.exists())
            if original_settings is None:
                self.assertFalse(REPO_SETTINGS_PATH.exists())
            else:
                self.assertEqual(REPO_SETTINGS_PATH.read_bytes(), original_settings)
            self.assertFalse((RECORDS_ROOT / "items").exists())
            run_cli_ps1(powershell, "--json", "items", "refresh", "--max-items", "1")
            image_records = sorted((RECORDS_ROOT / "items").glob("*/image_record.json"))
            self.assertEqual(len(image_records), 1)

            run_cli_ps1(powershell, "--json", "items", "download")
            archive_path = RECORDS_ROOT / "downloads" / "TimelineForImage-selected.zip"

            self.assertTrue(archive_path.exists())
            self.assertEqual(archive_path.name, "TimelineForImage-selected.zip")
            with zipfile.ZipFile(archive_path) as archive:
                names = set(archive.namelist())
            self.assertIn("README.md", names)
            self.assertTrue(any(name.endswith("/convert_info.json") for name in names))
            self.assertTrue(any(name.endswith("/timeline.json") for name in names))
            self.assertTrue(any(name.endswith("/image_record.json") for name in names))
            self.assertFalse(any(name.endswith("sample.png") for name in names))
            self.assertEqual(worker_run_containers(docker), worker_run_containers_before)
        finally:
            if not worker_was_running:
                run_docker_compose(docker, TEST_INSTANCE_NAME, "down", check=False)
            shutil.rmtree(TEST_ROOT, ignore_errors=True)
            if original_settings is None:
                REPO_SETTINGS_PATH.unlink(missing_ok=True)
            else:
                REPO_SETTINGS_PATH.write_bytes(original_settings)


def run_cli_ps1(powershell: list[str], *args: str) -> subprocess.CompletedProcess[str]:
    TEST_ROOT.mkdir(parents=True, exist_ok=True)
    write_cli_runner()
    completed = subprocess.run(
        [
            *powershell,
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            to_windows_path(RUNNER_PATH),
            *args,
        ],
        cwd=REPO_ROOT,
        env=os.environ.copy(),
        text=True,
        capture_output=True,
        timeout=180,
        check=False,
    )
    assert completed.returncode == 0, f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
    return completed


def write_cli_runner() -> None:
    cli_path = escape_powershell_single_quoted(to_windows_path(REPO_ROOT / "cli.ps1"))
    RUNNER_PATH.write_text(
        "\n".join(
            [
                "[CmdletBinding()]",
                "param(",
                "    [Parameter(ValueFromRemainingArguments = $true)]",
                "    [string[]]$CliArgs",
                ")",
                "$ErrorActionPreference = \"Stop\"",
                "$env:TIMELINE_FOR_IMAGE_C_DRIVE_MOUNT = \"C:\\\"",
                "$env:TIMELINE_FOR_IMAGE_SETTINGS_PATH = \"/workspace/output/cli-ps1-download-test/settings.json\"",
                "$env:TIMELINE_FOR_IMAGE_INTERNAL_STATE_ROOT = \"/workspace/output/cli-ps1-download-test/state\"",
                f"$env:TIMELINE_FOR_IMAGE_INSTANCE_NAME = \"{TEST_INSTANCE_NAME}\"",
                f"$env:TIMELINE_FOR_IMAGE_API_PORT = \"{TEST_API_PORT}\"",
                f"& '{cli_path}' @CliArgs",
                "exit $LASTEXITCODE",
                "",
            ]
        ),
        encoding="utf-8",
    )


def escape_powershell_single_quoted(value: str) -> str:
    return value.replace("'", "''")


def find_powershell_command() -> list[str] | None:
    if shutil.which("cmd.exe") and shutil.which("powershell.exe"):
        return ["cmd.exe", "/c", "powershell.exe"]
    powershell = shutil.which("powershell.exe") or shutil.which("pwsh")
    return [powershell] if powershell else None


def find_docker_command() -> str | None:
    return shutil.which("docker.exe") or shutil.which("docker")


def run_docker(docker: str, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        [docker, *args],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        timeout=180,
        check=False,
    )
    if check and completed.returncode != 0:
        raise AssertionError(f"docker {' '.join(args)} failed\nstdout:\n{completed.stdout}\nstderr:\n{completed.stderr}")
    return completed


def run_docker_compose(docker: str, project: str, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return run_docker(docker, "compose", "--project-directory", to_windows_path(REPO_ROOT), "-p", f"timeline-for-image-{project}", *args, check=check)


def compose_worker_running(docker: str, project: str) -> bool:
    completed = run_docker_compose(docker, project, "ps", "--status", "running", "--services", check=False)
    if completed.returncode != 0:
        return False
    services = {line.strip() for line in completed.stdout.splitlines() if line.strip()}
    return "worker" in services


def worker_run_containers(docker: str) -> set[str]:
    completed = run_docker(docker, "ps", "--format", "{{.Names}}", check=False)
    if completed.returncode != 0:
        return set()
    return {line.strip() for line in completed.stdout.splitlines() if line.strip().startswith("timeline-for-image-worker-run-")}


def to_windows_path(path: Path) -> str:
    resolved = path.resolve()
    parts = resolved.parts
    if len(parts) >= 4 and parts[0] == "/" and parts[1] == "mnt" and len(parts[2]) == 1:
        drive = parts[2].upper()
        rest = "\\".join(parts[3:])
        return f"{drive}:\\{rest}"
    return str(resolved)


def minimal_png(width: int, height: int) -> bytes:
    def chunk(kind: bytes, data: bytes) -> bytes:
        import zlib

        payload = kind + data
        return struct.pack(">I", len(data)) + payload + struct.pack(">I", zlib.crc32(payload) & 0xFFFFFFFF)

    import zlib

    raw = b"".join(b"\x00" + b"\xff\xff\xff" * width for _ in range(height))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )
