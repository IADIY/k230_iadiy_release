################################################################################
#
# k230_camera
#
################################################################################

K230_CAMERA_VERSION = 1.0
K230_CAMERA_SITE = $(K230_CAMERA_PKGDIR)/files
K230_CAMERA_SITE_METHOD = local
K230_CAMERA_DEPENDENCIES = vvcam uvc-gadget bash coreutils util-linux ffmpeg

define K230_CAMERA_INSTALL_TARGET_CMDS
	$(INSTALL) -D -m 0755 $(@D)/k230-camera $(TARGET_DIR)/usr/bin/k230-camera
endef

define K230_CAMERA_BUILD_DEB
	rm -rf $(@D)/deb
	$(INSTALL) -d -m 0755 $(@D)/deb/DEBIAN
	$(INSTALL) -D -m 0755 $(@D)/k230-camera $(@D)/deb/usr/bin/k230-camera
	printf '%s\n' \
		'Package: k230-camera' \
		'Version: $(K230_CAMERA_VERSION)' \
		'Section: utils' \
		'Priority: optional' \
		'Architecture: all' \
		'Depends: bash, coreutils, util-linux, k230-vvcam, k230-uvc-gadtet' \
		'Maintainer: K230 Dev <dev@example.com>' \
		'Description: Manual IMX335 USB camera and optional LCD preview' \
		> $(@D)/deb/DEBIAN/control
	$(INSTALL) -d -m 0755 $(BINARIES_DIR)/deb
	dpkg-deb --build --root-owner-group $(@D)/deb $(BINARIES_DIR)/deb/k230-camera.deb
endef

# Match the existing UVC package's Debian name (k230-uvc-gadtet).
K230_CAMERA_POST_INSTALL_TARGET_HOOKS += K230_CAMERA_BUILD_DEB

$(eval $(generic-package))
