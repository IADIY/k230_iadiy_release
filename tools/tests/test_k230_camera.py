import os
from pathlib import Path
import signal
import subprocess
import tempfile
import time
import unittest

SCRIPT = Path(__file__).resolve().parents[2] / 'buildroot-overlay/package/k230_camera/files/k230-camera'


class CameraTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        self.events = self.root / 'events'
        self.env = dict(os.environ, PATH=f'{self.bin}:' + os.environ['PATH'], EVENTS=str(self.events), GADGETS=str(self.root / 'gadgets'))
        self.make('helper', '''echo "helper $1" >> "$EVENTS"
[ "$1" != start-managed ] || exit "${FAIL_SETUP:-0}"''')
        self.make('adb', 'echo "adb $1" >> "$EVENTS"; if [ "$1" = start ]; then mkdir -p "$GADGETS/g1"; echo 91500000.usb > "$GADGETS/g1/UDC"; fi')
        self.make('uvc-gadget', '''echo uvc >> "$EVENTS"
if [ "${UVC_EXIT:-0}" = 1 ]; then exit 1; fi
exec sleep 60''')
        self.make('v4l2-drm', 'echo lcd >> "$EVENTS"; exit 1')
        self.harness = self.root / 'harness'
        self.harness.write_text(f'''#!/bin/bash
source "{SCRIPT}"
RUN_DIR="{self.root}/run"
GADGET_ROOT="{self.root}/gadgets"
VIDEO_UVC=/dev/null
VIDEO_LCD=/dev/null
HELPER="{self.bin}/helper"
ADB_SCRIPT="{self.bin}/adb"
prerequisites() {{ [ "${{FAIL_PREREQ:-0}}" = 0 ]; }}
check_usb() {{ restore_adb=${{ADB_ACTIVE:-0}}; }}
main "$@"
''')
        self.harness.chmod(0o755)

    def tearDown(self):
        self.tmp.cleanup()

    def make(self, name, body):
        p = self.bin / name
        p.write_text('#!/bin/sh\n' + body + '\n')
        p.chmod(0o755)

    def start(self, **env):
        return subprocess.Popen([str(self.harness)], env=dict(self.env, **env), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def wait_for(self, text, count=1, timeout=6):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if self.events.exists() and self.events.read_text().splitlines().count(text) >= count:
                return
            time.sleep(.05)
        self.fail(f'missing {text}: {self.events.read_text() if self.events.exists() else ""}')

    def test_retry_lcd_exit_and_signal_cleanup(self):
        p = self.start(UVC_EXIT='1', ADB_ACTIVE='1')
        try:
            self.wait_for('uvc', 2)
            self.assertEqual(self.events.read_text().splitlines().count('lcd'), 1)
        finally:
            p.send_signal(signal.SIGTERM)
            p.wait(timeout=8)
        events = self.events.read_text().splitlines()
        self.assertIn('helper cleanup', events)
        self.assertLess(events.index('adb stop'), events.index('helper start-managed'))
        self.assertLess(events.index('helper cleanup'), events.index('adb start'))

    def test_duplicate_and_signal(self):
        p = self.start()
        try:
            self.wait_for('uvc')
            duplicate = self.start()
            self.assertNotEqual(duplicate.wait(timeout=3), 0)
        finally:
            p.send_signal(signal.SIGTERM)
            p.wait(timeout=8)
        self.assertEqual(self.events.read_text().splitlines().count('helper cleanup'), 1)

    def test_partial_setup_and_prerequisite(self):
        p = self.start(FAIL_PREREQ='1')
        self.assertNotEqual(p.wait(timeout=3), 0)
        self.assertFalse(self.events.exists())
        p = self.start(FAIL_SETUP='1', ADB_ACTIVE='1')
        self.assertNotEqual(p.wait(timeout=8), 0)
        self.assertEqual(self.events.read_text().splitlines(), ['adb stop', 'helper start-managed', 'helper cleanup', 'adb start'])

    def test_setup_ownership_race_does_not_cleanup(self):
        p = self.start(FAIL_SETUP='75', ADB_ACTIVE='1')
        self.assertNotEqual(p.wait(timeout=8), 0)
        self.assertEqual(self.events.read_text().splitlines(),
                         ['adb stop', 'helper start-managed', 'adb start'])

    def test_prerequisites_check_uvc_help_and_service(self):
        self.make('id', 'echo 0')
        self.make('systemctl', '[ "${SERVICE_ACTIVE:-1}" = 1 ]')
        self.make('uvc-gadget', 'echo "usage: uvc-gadget ${UVC_OPTION:--v} DEVICE"')
        check = (f'source "{SCRIPT}"; VIDEO_UVC=/dev/null; '
                 f'HELPER="{self.bin}/helper"; prerequisites')
        def run(**extra):
            return subprocess.run(['bash', '-c', check], env=dict(self.env, **extra),
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.assertEqual(run().returncode, 0)
        self.assertNotEqual(run(SERVICE_ACTIVE='0').returncode, 0)
        self.assertNotEqual(run(UVC_OPTION='--other').returncode, 0)

    def test_usb_rejects_unrelated_bound_and_existing_uvc(self):
        gadgets = self.root / 'gadgets'
        (gadgets / 'other').mkdir(parents=True)
        (gadgets / 'other' / 'UDC').write_text('91500000.usb')
        check = f'source "{SCRIPT}"; GADGET_ROOT="{gadgets}"; VIDEO_UVC=/dev/null; check_usb'
        result = subprocess.run(['bash', '-c', check], env=self.env, capture_output=True)
        self.assertNotEqual(result.returncode, 0)
        (gadgets / 'other' / 'UDC').write_text('')
        (gadgets / 'uvc_g1').mkdir()
        result = subprocess.run(['bash', '-c', check], env=self.env, capture_output=True)
        self.assertNotEqual(result.returncode, 0)

    def test_no_lcd(self):
        p = subprocess.Popen([str(self.harness), '--no-lcd'], env=self.env,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            self.wait_for('uvc')
            self.assertNotIn('lcd', self.events.read_text().splitlines())
        finally:
            p.send_signal(signal.SIGTERM)
            p.wait(timeout=8)

    def test_cli(self):
        self.assertEqual(subprocess.run([str(SCRIPT), '--help'], capture_output=True).returncode, 0)
        self.assertEqual(subprocess.run([str(SCRIPT), '--bad'], capture_output=True).returncode, 2)


if __name__ == '__main__':
    unittest.main()
