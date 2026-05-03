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
REPO_SETTINGS_PATH = REPO_ROOT / "settings.json"


class CliPs1DownloadTest(unittest.TestCase):
    def test_cli_ps1_download_all_from_local_host(self) -> None:
        powershell = find_powershell_command()
        if powershell is None:
            self.skipTest("PowerShell is not available on this host.")
        if shutil.which("docker.exe") is None and shutil.which("docker") is None:
            self.skipTest("Docker CLI is not available on this host.")

        original_settings = REPO_SETTINGS_PATH.read_bytes() if REPO_SETTINGS_PATH.exists() else None
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
            self.assertTrue(REPO_SETTINGS_PATH.exists())
            run_cli_ps1(powershell, "--json", "items", "refresh", "--max-items", "1")
            image_records = sorted((RECORDS_ROOT / "items").glob("*/image_record.json"))
            self.assertEqual(len(image_records), 1)

            run_cli_ps1(powershell, "--json", "items", "download", "--all")
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
        finally:
            if original_settings is None:
                REPO_SETTINGS_PATH.unlink(missing_ok=True)
            else:
                REPO_SETTINGS_PATH.write_bytes(original_settings)


def run_cli_ps1(powershell: list[str], *args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.setdefault("TIMELINE_FOR_IMAGE_C_DRIVE_MOUNT", "C:\\")
    env["TIMELINE_FOR_IMAGE_INTERNAL_STATE_ROOT"] = "/workspace/output/cli-ps1-download-test/state"
    completed = subprocess.run(
        [
            *powershell,
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            to_windows_path(REPO_ROOT / "cli.ps1"),
            *args,
        ],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
        timeout=180,
        check=False,
    )
    assert completed.returncode == 0, f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
    return completed


def find_powershell_command() -> list[str] | None:
    if shutil.which("cmd.exe") and shutil.which("powershell.exe"):
        return ["cmd.exe", "/c", "powershell.exe"]
    powershell = shutil.which("powershell.exe") or shutil.which("pwsh")
    return [powershell] if powershell else None


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
