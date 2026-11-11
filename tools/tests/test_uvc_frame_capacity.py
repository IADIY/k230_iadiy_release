"""Exercise the production encoded-frame capacity guard without camera hardware."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

PATCH = (Path(__file__).resolve().parents[2] / 'buildroot-overlay/package/uvc-gadget/'
         '0003-vpu-validate-full-resolution-formats-and-buffer-sizes.patch')


class CapacityTest(unittest.TestCase):
    @unittest.skipUnless(shutil.which('cc'), 'host C compiler is required')
    def test_full_resolution_and_invalid_dimensions(self):
        added = '\n'.join(line[1:] for line in PATCH.read_text().splitlines()
                          if line.startswith('+') and not line.startswith('+++'))
        start = added.index('static int mjpeg_frame_capacity(')
        end = added.index('\n}', start) + 2
        function = added[start:end]
        harness = r'''
#include <assert.h>
#include <errno.h>
#include <stdint.h>
#include <limits.h>
FUNCTION
int main(void) {
    uint32_t capacity = 0;
    assert(mjpeg_frame_capacity(2592, 1944, &capacity) == 0);
    assert(capacity == 10077696);
    assert(mjpeg_frame_capacity(1920, 1080, &capacity) == 0);
    assert(capacity == 4147200);
    assert(mjpeg_frame_capacity(640, 360, &capacity) == 0);
    assert(capacity == 460800);
    capacity = 123;
    assert(mjpeg_frame_capacity(0, 1944, &capacity) == -EINVAL);
    assert(mjpeg_frame_capacity(2592, 0, &capacity) == -EINVAL);
    assert(mjpeg_frame_capacity(2591, 1944, &capacity) == -EINVAL);
    assert(mjpeg_frame_capacity(2592, 1943, &capacity) == -EINVAL);
    assert(mjpeg_frame_capacity(UINT32_MAX - 1, 2, &capacity) == -EINVAL);
    assert(mjpeg_frame_capacity(65536, 65536, &capacity) == -EINVAL);
    assert(capacity == 123);
    return 0;
}
'''.replace('FUNCTION', function)
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / 'capacity.c'
            binary = Path(tmp) / 'capacity'
            source.write_text(harness)
            subprocess.run(['cc', '-std=c99', '-Wall', '-Wextra', '-Werror',
                            str(source), '-o', str(binary)], check=True)
            subprocess.run([str(binary)], check=True)


if __name__ == '__main__':
    unittest.main()
