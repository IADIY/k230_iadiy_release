#!/bin/sh
# Documentation/usb/gadget_uvc.rst
CONFIGFS="/sys/kernel/config"
G="$CONFIGFS/usb_gadget/uvc_g1"
FUNCTION="$G/functions/uvc.usb0"
DWC2_DRIVER="/sys/bus/platform/drivers/dwc2"
UDC_NAME="91500000.usb"

create_frame() {
    # Example usage:
    # create_frame <width> <height> <group> <format name>

    WIDTH=$1
    HEIGHT=$2
    FORMAT=$3
    NAME=$4

    wdir=${FUNCTION}/streaming/$FORMAT/$NAME/${HEIGHT}p
    mkdir -p $wdir
    echo $WIDTH > $wdir/wWidth
    echo $HEIGHT > $wdir/wHeight
    # For uncompressed formats (YUYV), 2 bytes per pixel
    # For compressed formats (MJPEG, H.264, H.265), use larger buffer
    case "$FORMAT" in
        uncompressed)
            case "$WIDTH" in
            1920)
                echo "$(( $WIDTH * $HEIGHT * 2 ))"  >  $wdir/dwMaxVideoFrameBufferSize
                echo "29491200" > $wdir/dwMaxBitRate
                echo "29491200" > $wdir/dwMinBitRate
            ;;   # 320KB for 1080p
            1280)
                echo "$(( $WIDTH * $HEIGHT * 2 ))" >  $wdir/dwMaxVideoFrameBufferSize
                echo "29491200" > $wdir/dwMaxBitRate
                echo "29491200" > $wdir/dwMinBitRate
            ;;   # 160KB for 720p
            640)
                echo "$(( $WIDTH * $HEIGHT * 2 ))" >  $wdir/dwMaxVideoFrameBufferSize
                echo "55296000" > $wdir/dwMaxBitRate
                echo "55296000" > $wdir/dwMinBitRate
            ;;    # 80KB for 360p
            *)
                echo "$(( $WIDTH * $HEIGHT * 2 )) " >  $wdir/dwMaxVideoFrameBufferSize
                echo "10240000" > $wdir/dwMaxBitRate
                echo "10240000" > $wdir/dwMinBitRate
            ;;   # default 160KB
            esac
        ;;

        mjpeg)
            # Match the encoded source capacity; reserve space for complete frames.
            frame_bytes=$(( WIDTH * HEIGHT * 2 ))
            echo "$frame_bytes" > "$wdir/dwMaxVideoFrameBufferSize"
            echo "$(( frame_bytes * 8 * 30 ))" > "$wdir/dwMaxBitRate"
            echo "2000000" > "$wdir/dwMinBitRate"
        ;;
        *)
        echo $(( $WIDTH * $HEIGHT * 2 )) > $wdir/dwMaxVideoFrameBufferSize
        ;;
    esac
    echo "333333" > $wdir/dwDefaultFrameInterval
    echo "333333" > $wdir/dwFrameInterval
}

# Configfs owns attributes and default groups; remove only created objects.
cleanup_uvc_gadget() {
    [ -d "$G" ] || return 0
    result=0
    if [ -e "$G/UDC" ]; then
        echo "" > "$G/UDC" || result=1
    fi
    for link in "$G/configs/c.1/f1" \
        "$FUNCTION/streaming/class/fs/h" \
        "$FUNCTION/streaming/class/hs/h" \
        "$FUNCTION/streaming/class/ss/h" \
        "$FUNCTION/streaming/header/h/mjpeg" \
        "$FUNCTION/control/class/fs/h" \
        "$FUNCTION/control/class/ss/h"; do
        if [ -L "$link" ]; then rm "$link" || result=1; fi
    done
    for dir in "$FUNCTION/streaming/header/h" \
        "$FUNCTION/streaming/mjpeg/mjpeg/360p" \
        "$FUNCTION/streaming/mjpeg/mjpeg/720p" \
        "$FUNCTION/streaming/mjpeg/mjpeg/1080p" \
        "$FUNCTION/streaming/mjpeg/mjpeg/1944p" \
        "$FUNCTION/streaming/mjpeg/mjpeg" \
        "$FUNCTION/control/header/h" \
        "$G/configs/c.1/strings/0x409" \
        "$G/configs/c.1" \
        "$G/strings/0x409" \
        "$FUNCTION" \
        "$G"; do
        if [ -d "$dir" ]; then rmdir "$dir" || result=1; fi
    done
    return "$result"
}

start_uvc_gadget() (
    if [ -e "$G" ]; then
        echo "Gadget already exists: $G" >&2
        exit 75
    fi
    set -e
    modprobe libcomposite
    modprobe usb_f_uvc
    if [ ! -d "$CONFIGFS/usb_gadget" ]; then
        mount -t configfs none "$CONFIGFS"
    fi
    # 2. 创建 Gadget 根目录
    if ! mkdir "$G"; then
        echo "Could not acquire gadget: $G" >&2
        exit 75
    fi
    # Retain the setup failure status even if partial cleanup fails.
    trap 'status=$?; trap - 0; if [ "${dwc2_unbound:-0}" -eq 1 ]; then echo "Restoring DWC2 controller binding" >&2; echo "$UDC_NAME" > "$DWC2_DRIVER/bind" || echo "Failed to restore DWC2 controller binding; controller may be unbound" >&2; fi; if [ "$status" -ne 0 ]; then cleanup_uvc_gadget || :; fi; exit "$status"' 0
    trap 'exit 130' INT
    trap 'exit 143' TERM
    # Reset before creating the UVC function, which initializes its queue.
    for udc in "$CONFIGFS"/usb_gadget/*/UDC; do
        [ -f "$udc" ] || continue
        if [ "$(cat "$udc")" = "$UDC_NAME" ]; then
            echo "Controller $UDC_NAME is already bound to a gadget: $udc" >&2
            exit 1
        fi
    done
    if [ ! -w "$DWC2_DRIVER/unbind" ] || [ ! -w "$DWC2_DRIVER/bind" ]; then
        echo "DWC2 reset controls unavailable: $DWC2_DRIVER" >&2
        exit 1
    fi
    echo "$UDC_NAME" > "$DWC2_DRIVER/unbind" || { echo "Failed to unbind DWC2 controller" >&2; exit 1; }
    dwc2_unbound=1
    sleep 1
    echo "$UDC_NAME" > "$DWC2_DRIVER/bind" || { echo "Failed to bind DWC2 controller" >&2; exit 1; }
    dwc2_unbound=0
    sleep 1
    cd "$G"

    # pid.codes VID/PID for testing only; replace before production use.
    echo 0x1209 > idVendor
    echo 0x0001 > idProduct
    echo 0x0200 > bcdUSB
    echo 0xEF > bDeviceClass
    echo 0x02 > bDeviceSubClass
    echo 0x01 > bDeviceProtocol

    mkdir -p strings/0x409
    echo "12345678" > strings/0x409/serialnumber
    echo "Canaan" > strings/0x409/manufacturer
    echo "UVC Gadget" > strings/0x409/product

    # 3. 创建 UVC 功能实例
    mkdir -p $FUNCTION

    # 设置传输参数
    echo 1 > $FUNCTION/streaming_interval
    # 1024 produced clean full-resolution video at reported 30 fps.
    # 2048 and 3072 showed corruption on this board/host setup.
    echo 1024 > $FUNCTION/streaming_maxpacket
    echo 4 > $FUNCTION/streaming_maxburst
    echo "k230 linux uvc" > $FUNCTION/function_name

    # 4. 创建帧描述符 (MJPEG format)
    create_frame 640 360 mjpeg mjpeg
    create_frame 1280 720 mjpeg mjpeg
    create_frame 1920 1080 mjpeg mjpeg
    create_frame 2592 1944 mjpeg mjpeg
    echo 4 > "$FUNCTION/streaming/mjpeg/mjpeg/bDefaultFrameIndex"

    # 5. Header linking
    mkdir $FUNCTION/streaming/header/h
    cd $FUNCTION/streaming/header/h
    ln -s ../../mjpeg/mjpeg

    cd ../../class/fs
    ln -s ../../header/h
    cd ../../class/hs
    ln -s ../../header/h
    cd ../../class/ss
    ln -s ../../header/h
    cd ../../../control
    mkdir header/h
    ln -s header/h class/fs
    ln -s header/h class/ss

    cd "$G"

    # 6. 绑定到配置项
    mkdir -p configs/c.1/strings/0x409
    echo "Config 1" > configs/c.1/strings/0x409/configuration
    echo 500 > configs/c.1/MaxPower
    ln -s ${FUNCTION} configs/c.1/f1

    # 7. 启动！
    echo "$UDC_NAME" > UDC

    echo "UVC gadget started"

    # 8. 启动 uvc-gadget 应用
    #/usr/bin/uvc-gadget -v /dev/video1 &
)

stop_uvc_gadget() {
    # 1. 停止 uvc-gadget 应用
    killall uvc-gadget 2>/dev/null || true

    cleanup_uvc_gadget || return $?

    # 7. 等待 USB 连接完全断开
    sleep 1

    # 8. 卸载模块（先卸载功能模块，再卸载 composite）
    rmmod usb_f_uvc 2>/dev/null || true
    rmmod libcomposite 2>/dev/null || true

    # 9. 卸载 configfs
    umount /sys/kernel/config 2>/dev/null || true

    echo "UVC gadget stopped"
}

case "$1" in
    start)
        [ -f /etc/init.d/S41adb_mtp ] && /etc/init.d/S41adb_mtp stop
        [ -f /etc/vvcam/S41adb_mtp ] && /etc/vvcam/S41adb_mtp stop
        start_uvc_gadget
        ;;
    start-managed)
        start_uvc_gadget
        ;;
    cleanup)
        cleanup_uvc_gadget
        ;;
    stop)
        stop_uvc_gadget
        ;;
    restart)
        stop_uvc_gadget
        sleep 1
        start_uvc_gadget
        ;;
    *)
        echo "Usage: $0 {start|stop|restart|start-managed|cleanup}" >&2
        exit 3
        ;;
esac
