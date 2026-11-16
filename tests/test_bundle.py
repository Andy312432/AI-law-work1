"""Opt-in checks against a real PyInstaller release, without source imports."""

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import unittest


BUNDLE_DIR = os.environ.get("LEXIARBITER_BUNDLE_DIR")


@unittest.skipUnless(BUNDLE_DIR, "Set LEXIARBITER_BUNDLE_DIR to test a built release")
class BundleTests(unittest.TestCase):
    def test_release_includes_editable_modes_preferences_and_icons(self):
        bundle = Path(BUNDLE_DIR).resolve()
        for name in ("configs/annotation_modes/term_definition.json",
                     "configs/user_preferences.json",
                     "assets/LexiArbiter_icon.png", "assets/LexiArbiter_icon.ico"):
            with self.subTest(file=name):
                self.assertTrue((bundle / name).is_file(), f"Missing bundled file: {name}")

    def test_copied_release_starts_from_an_unrelated_working_directory(self):
        with tempfile.TemporaryDirectory(prefix="lexiarbiter-release-") as folder:
            bundle = Path(folder) / "發佈測試"
            shutil.copytree(Path(BUNDLE_DIR).resolve(), bundle,
                            ignore=shutil.ignore_patterns("logs"))
            executable = next(bundle.glob("*.exe"))
            env = {**os.environ, "QT_QPA_PLATFORM": "offscreen"}
            process = subprocess.Popen(
                [str(executable)], cwd=folder, env=env,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            startup_log = bundle / "logs" / "lexiarbiter.log"
            try:
                deadline = time.monotonic() + 20
                while time.monotonic() < deadline:
                    self.assertIsNone(process.poll(), "Bundled app exited during startup")
                    contents = startup_log.read_text(encoding="utf-8") if startup_log.exists() else ""
                    if "Main window ready" in contents:
                        self.assertFalse((bundle / "logs" / "last_crash.txt").exists())
                        return
                    time.sleep(0.1)
                self.fail(f"Bundled app did not finish startup. Log:\n{contents}")
            finally:
                if process.poll() is None:
                    process.terminate()
                process.wait(timeout=10)


if __name__ == "__main__":
    unittest.main()
