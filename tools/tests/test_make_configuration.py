"""Exercise configuration persistence without installing or building anything."""

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


REPO_ROOT = Path(__file__).resolve().parents[2]
PROFILE = "k230_canmv_iadiy_emmc_imx335_uvc_defconfig"


class MakeConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.workspace = tempfile.TemporaryDirectory()
        self.addCleanup(self.workspace.cleanup)
        self.root = Path(self.workspace.name)
        shutil.copyfile(REPO_ROOT / "Makefile", self.root / "Makefile")
        tools = self.root / "tools"
        tools.mkdir()
        installer = tools / "install_toolchain_and_depend.sh"
        installer.write_text('#!/bin/sh\nexit "${INSTALLER_EXIT:-0}"\n')
        installer.chmod(0o755)
        self.config = self.root / ".last_conf"

    def run_make(self, *args, installer_exit=0):
        env = os.environ.copy()
        for name in ("MAKEFLAGS", "MFLAGS", "MAKEOVERRIDES", "CONF"):
            env.pop(name, None)
        env["INSTALLER_EXIT"] = str(installer_exit)
        return subprocess.run(
            ["make", "--no-print-directory", "BR2_PRIMARY_SITE=unused", *args],
            cwd=self.root,
            env=env,
            capture_output=True,
            text=True,
            timeout=10,
        )

    def test_setup_does_not_create_configuration(self):
        for status in (0, 1):
            with self.subTest(installer_exit=status):
                result = self.run_make(
                    "toolchain_and_depend", f"CONF={PROFILE}", installer_exit=status
                )
                self.assertEqual(result.returncode == 0, status == 0, result.stderr)
                self.assertFalse(self.config.exists())

    def test_setup_does_not_read_or_modify_existing_configuration(self):
        # A parse error would stop Make if the setup invocation included this file.
        content = "$(error setup must not include .last_conf)\n"
        self.config.write_text(content)
        self.config.chmod(0o444)
        before = self.config.stat()
        for status in (0, 1):
            with self.subTest(installer_exit=status):
                result = self.run_make("toolchain_and_depend", installer_exit=status)
                self.assertEqual(result.returncode == 0, status == 0, result.stderr)
                self.assertEqual(self.config.read_text(), content)
                after = self.config.stat()
                for field in ("st_uid", "st_gid", "st_mode", "st_mtime_ns"):
                    self.assertEqual(getattr(after, field), getattr(before, field))

    def test_normal_invocation_saves_explicit_configuration(self):
        result = self.run_make(f"CONF={PROFILE}", "list_def")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.config.read_text(), f"CONF={PROFILE}\n")

    def test_multiple_targets_still_save_configuration(self):
        result = self.run_make(
            f"CONF={PROFILE}", "toolchain_and_depend", "list_def"
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.config.read_text(), f"CONF={PROFILE}\n")


if __name__ == "__main__":
    unittest.main()
