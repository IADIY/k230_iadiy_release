import os
from pathlib import Path
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[2] / "buildroot-overlay/package/uvc-gadget/uvc-gadget.sh"

# Simulate configfs default groups and attributes, which cannot be removed
# directly and vanish when their owning object is removed.
MOCK = r'''#!/usr/bin/env python3
import os, pathlib, shutil, sys
name = pathlib.Path(sys.argv[0]).name
args = sys.argv[1:]
with open(os.environ["LOG"], "a") as f: f.write(name + " " + " ".join(args) + "\n")
if name == "mkdir":
    paths = [x for x in args if x != "-p"]
    for x in paths:
        p = pathlib.Path(x)
        if os.environ.get("FAIL_AT") and os.environ["FAIL_AT"] in str(p):
            sys.exit(42)
        p.mkdir(parents="-p" in args, exist_ok="-p" in args)
        if p.name == "uvc_g1":
            for d in ("functions", "configs", "strings"): (p/d).mkdir()
            (p/"UDC").touch()
        if p.name == "uvc.usb0":
            for d in ("streaming/mjpeg", "streaming/header", "streaming/class/fs", "streaming/class/hs", "streaming/class/ss", "control/header", "control/class/fs", "control/class/ss"):
                (p/d).mkdir(parents=True, exist_ok=True)
        if p.name == "c.1": (p/"strings").mkdir(exist_ok=True)
elif name == "rmdir":
    p = pathlib.Path(args[0])
    if not p.exists(): sys.exit(1)
    # Refuse to remove a configfs object with user-created children or links.
    for child in p.rglob("*"):
        if child.is_symlink(): sys.exit(1)
        if child.is_dir() and child.name not in ("functions", "configs", "strings", "streaming", "mjpeg", "header", "class", "fs", "hs", "ss", "control"):
            sys.exit(1)
    shutil.rmtree(p)
elif name == "sleep":
    driver = pathlib.Path(os.environ["DRIVER"])
    with open(os.environ["LOG"], "a") as f:
        for control in ("unbind", "bind"):
            p = driver / control
            if p.is_file(): f.write(control + "=" + p.read_text().strip() + "\n")
elif name in ("modprobe", "mount", "rmmod", "umount", "killall"):
    pass
'''

class LifecycleTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.config = self.root / "config"
        (self.config / "usb_gadget").mkdir(parents=True)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        for name in ("mkdir", "rmdir", "modprobe", "mount", "rmmod", "umount", "killall", "sleep"):
            p = self.bin / name
            p.write_text(MOCK)
            p.chmod(0o755)
        self.driver = self.root / "dwc2"
        self.driver.mkdir()
        for name in ("unbind", "bind"):
            (self.driver / name).touch()
        self.script = self.root / "gadget.sh"
        self.script.write_text(SCRIPT.read_text()
            .replace('CONFIGFS="/sys/kernel/config"', f'CONFIGFS="{self.config}"')
            .replace('DWC2_DRIVER="/sys/bus/platform/drivers/dwc2"', f'DWC2_DRIVER="{self.driver}"'))
        self.env = dict(os.environ, PATH=f'{self.bin}:' + os.environ["PATH"], LOG=str(self.root / "log"), DRIVER=str(self.driver))
        self.gadget = self.config / "usb_gadget/uvc_g1"

    def run_action(self, action, **env):
        return subprocess.run(["sh", str(self.script), action], env=dict(self.env, **env), capture_output=True, text=True)

    def test_cycles_and_existing_gadget(self):
        for _ in range(2):
            result = self.run_action("start-managed")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue((self.gadget / "configs/c.1/f1").is_symlink())
            marker = self.gadget / "owned-by-other"
            marker.write_text("untouched")
            self.assertEqual(self.run_action("start-managed").returncode, 75)
            self.assertEqual(marker.read_text(), "untouched")
            marker.unlink()
            result = self.run_action("cleanup")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(self.gadget.exists())
            self.assertEqual(self.run_action("cleanup").returncode, 0)
        log = (self.root / "log").read_text()
        for forbidden in ("killall ", "umount ", "rmmod "):
            self.assertNotIn(forbidden, log)

    def test_full_resolution_and_legacy_descriptors(self):
        result = self.run_action("start-managed")
        self.assertEqual(result.returncode, 0, result.stderr)
        function = self.gadget / "functions/uvc.usb0"
        fmt = function / "streaming/mjpeg/mjpeg"
        self.assertEqual((function / "streaming_interval").read_text().strip(), "1")
        # 1024 passed live full-resolution board testing at reported 30 fps.
        self.assertEqual((function / "streaming_maxpacket").read_text().strip(), "1024")
        self.assertEqual((fmt / "bDefaultFrameIndex").read_text().strip(), "4")
        for width, height in ((640, 360), (1280, 720), (1920, 1080), (2592, 1944)):
            frame = fmt / f"{height}p"
            self.assertEqual(int((frame / "wWidth").read_text()), width)
            self.assertEqual(int((frame / "wHeight").read_text()), height)
            self.assertEqual(int((frame / "dwMaxVideoFrameBufferSize").read_text()), width * height * 2)
            self.assertEqual(int((frame / "dwFrameInterval").read_text()), 333333)
        self.assertEqual((self.gadget / "idVendor").read_text().strip(), "0x1209")
        self.assertEqual((self.gadget / "idProduct").read_text().strip(), "0x0001")
        result = self.run_action("cleanup")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.gadget.exists())

    def test_reset_precedes_function_creation(self):
        result = self.run_action("start-managed")
        self.assertEqual(result.returncode, 0, result.stderr)
        log = (self.root / "log").read_text()
        self.assertLess(log.index("unbind=91500000.usb"), log.index("bind=91500000.usb\nmkdir"))
        self.assertLess(log.index("bind=91500000.usb\nmkdir"), log.index("uvc.usb0"))

    def test_bound_controller_is_not_reset(self):
        other = self.config / "usb_gadget/other"
        other.mkdir()
        (other / "UDC").write_text("91500000.usb\n")
        result = self.run_action("start-managed")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("already bound", result.stderr)
        self.assertFalse(self.gadget.exists())
        self.assertEqual((self.driver / "unbind").read_text(), "")
        self.assertEqual((self.driver / "bind").read_text(), "")
        self.assertEqual((other / "UDC").read_text(), "91500000.usb\n")

    def test_missing_reset_control_cleans_up(self):
        (self.driver / "bind").unlink()
        result = self.run_action("start-managed")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("reset controls unavailable", result.stderr)
        self.assertFalse(self.gadget.exists())
        self.assertEqual((self.driver / "unbind").read_text(), "")

    def test_bind_failure_attempts_restoration_and_cleans_up(self):
        (self.driver / "bind").unlink()
        (self.driver / "bind").mkdir()
        result = self.run_action("start-managed")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Failed to bind DWC2 controller", result.stderr)
        self.assertIn("controller may be unbound", result.stderr)
        self.assertFalse(self.gadget.exists())
        self.assertEqual((self.driver / "unbind").read_text().strip(), "91500000.usb")

    def test_failed_acquisition_does_not_cleanup(self):
        result = self.run_action("start-managed", FAIL_AT="uvc_g1")
        self.assertEqual(result.returncode, 75, result.stderr)
        self.assertNotIn("rmdir ", (self.root / "log").read_text())

    def test_partial_failure_is_cleaned(self):
        result = self.run_action("start-managed", FAIL_AT="720p")
        self.assertEqual(result.returncode, 42, result.stderr)
        self.assertFalse(self.gadget.exists(), result.stderr)

if __name__ == "__main__":
    unittest.main()
