# Repository guidance

## Project and source layout

This release turns the CM-K230 eMMC board with an IMX335 on CSI2 into a USB
UVC camera, with optional LCD preview. The runtime image is Debian 13; the
SDK uses Buildroot 2025.02.1 and the Xuantie RISC-V toolchain to build artifacts.
The code is primarily C/C++, shell scripts, Buildroot Make recipes/configs,
and Python host tests. There is no application-level package manager.

- `README.md`: release profile, build sequence, and camera operation.
- `docs/project-guide.md`: detailed incremental builds and hardware validation.
  Its generic board examples also cover the GC2093 baseline; use the IMX335
  profile below for this release.
- `buildroot-overlay/configs/`: board defconfigs.
- `buildroot-overlay/package/k230_camera/`: camera launcher and package recipe.
- `buildroot-overlay/package/uvc-gadget/`: USB gadget scripts and C patches.
- `buildroot-overlay/board/canaan/k230-soc/`: rootfs overlay, image generation,
  board hooks, and boot artwork.
- `buildroot-overlay/linux/` and `buildroot-overlay/boot/`: kernel patches
  and bootloader overlays.
- `tools/sync.mk`: downloads Buildroot and synchronizes source overlays.
- `tools/tests/`: Python unittest tests using mocked device interfaces.
- `output/` and `dl/`: generated trees, images, and download caches.

Edit `buildroot-overlay/`, not generated copies under `output/`. Preserve
tracked firmware, models, artwork, and third-party source unless the task
requires changing them. Match the style of the surrounding package; use tabs
for Make recipes and preserve each script's shell/interpreter requirements.

## Setup and build

Run commands from the repository root. The SDK documents Ubuntu 22.04/24.04.
Host dependency installation and image packaging need root; compilation uses
the normal user. Setup installs packages and a toolchain under `/opt/toolchain`:

```sh
sudo make toolchain_and_depend
make CONF=k230_canmv_iadiy_emmc_imx335_uvc_defconfig
make buildroot
sudo make debian
```

`make CONF=...` selects the profile **and builds it**, saving `.last_conf`.
Without explicit selection the fallback is `k230_canmv_defconfig`, which is
not this release's profile. Even Makefile parsing writes `.last_conf` and may
probe download sites; `make help` also depends on synchronization. Do not use
these commands as side-effect-free inspection.

`sudo make debian` packages existing artifacts; it does not compile changes.
Rebuild affected components first, then run `make buildroot` and package again.
See the incremental build guide for package source refresh requirements.
Kernel/bootloader rebuild targets include `make linux-rebuild` and
`make uboot-rebuild`. Configuration is saved with `make savedefconfig` or
`make linux-savedefconfig`; inspect their resulting source changes.

The flashable image is
`output/k230_canmv_iadiy_emmc_imx335_uvc_defconfig/images/debian.img.gz`.
Builds download dependencies and may take substantial time and disk space.

## Validation

Host camera regression tests require Python 3, Bash, standard Unix tools,
and a host `cc` compiler for the encoded-frame capacity test:

```sh
python3 -m unittest discover -s tools/tests -p 'test_*.py'
bash -n buildroot-overlay/package/k230_camera/files/k230-camera
sh -n buildroot-overlay/package/uvc-gadget/uvc-gadget.sh
```

No repository-wide lint command was found. Choose checks appropriate to the
changed component. Host tests do not validate sensor capture, UVC throughput,
or LCD output; those need the board and a USB host as described in the guide.
The on-device `k230-camera` command runs as root with `vvcam.service` active;
it changes USB gadget mode and may disconnect a USB shell. Logs are under
`/run/k230-camera/`.

## Git and local state

Git commands may only be used for read-only inspection, such as `git diff`,
`git status`, and `git log`. Do not use git commands that modify repository
state.
Preserve unrelated working-tree changes.

Recent commits use short, imperative subjects, for example
`Add audio output device setup guide` and
`Fix audio playing issue: pass class id to playForDetections, not array index`.
Keep commits focused on one change. This message guidance does not authorize
creating commits.

Keep local credentials and generated artifacts out of source changes. The
checked-in `.clangd` contains machine-specific paths; adapt local tooling
deliberately rather than treating those paths as portable setup.
