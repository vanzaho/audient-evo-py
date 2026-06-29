// SPDX-License-Identifier: GPL-2.0+
/*
 * This module binds to Audient EVO USB devices and exposes per-device misc
 * devices (/dev/evo4, /dev/evo8). A single ioctl (EVO_CTRL_TRANSFER) lets
 * userspace send/receive arbitrary USB control transfers via the kernel's
 * usb_control_msg(), which bypasses usbfs interface-ownership checks.
 * snd-usb-audio continues to handle audio streaming undisturbed.
 */

#include "asm-generic/errno-base.h"
#include "asm-generic/int-ll64.h"
#include "linux/array_size.h"
#include "linux/gfp_types.h"
#include "linux/math.h"
#include "sound/asound.h"
#include <linux/fs.h>
#include <linux/kref.h>
#include <linux/miscdevice.h>
#include <linux/module.h>
#include <linux/slab.h>
#include <linux/uaccess.h>
#include <linux/usb.h>

#include <sound/control.h>
#include <sound/core.h>
#include <sound/tlv.h>

// 1. raw USB comm
// 2. ioctl (/dev/evo[4|8])
// 3. alsa bindings

#define AUDIENT_VID 0x2708
#define EVO4_PID 0x0006
#define EVO8_PID 0x0007
#define EVO_MAX_DATA 256

// EVO - USB
#define EVO_REQTYPE_SET 0x21
#define EVO_REQTYPE_GET 0xA1
#define EVO_REQ_CUR 0x01

// CS - Control Selector
#define EVO_CS_VOLUME 2
#define FU10_WINDEX 0x0A00
#define FU11_WINDEX 0x0B00
#define FU_WVALUE(cn) ((EVO_CS_VOLUME << 8) | (cn))

#define EU56_WVALUE 0x0000
#define EU56_WINDEX 0x3800

#define EVO_DB_TO_RAW(db) ((s16)((db) * 256))
#define EVO_RAW_TO_DB(raw) DIV_ROUND_CLOSEST((int)(raw), 256)

static const DECLARE_TLV_DB_SCALE(evo_vol_tlv, -9600, 100, 0);
static const DECLARE_TLV_DB_SCALE(evo_gain_tlv, -800, 100, 0);

// EVO4 Specific

#define EVO4_VOL_DB_MIN (-96)
#define EVO4_VOL_DB_MAX 0
#define EVO4_GAIN_DB_MIN (-8)
#define EVO4_GAIN_DB_MAX 50
#define EVO4_DIRECT_MONITOR_MIN 0
#define EVO4_DIRECT_MONITOR_MAX 100

static const struct evo_model {
    __u16 pid;
    const char *name;
} evo_models[] = {
    {EVO4_PID, "evo4"},
    {EVO8_PID, "evo8"},
};

/* ioctl payload - matches userspace struct */
struct evo_ctrl_xfer {
    __u8 bRequestType;
    __u8 bRequest;
    __u16 wValue;
    __u16 wIndex;
    __u16 wLength;
    __u8 data[EVO_MAX_DATA];
};

/* ioctl number: type='E' (0x45), nr=0, read+write, size of struct */
#define EVO_CTRL_TRANSFER _IOWR('E', 0, struct evo_ctrl_xfer)

struct evo_bool_ctl_config {
    const char *name;
    __u16 wValue;
    __u16 wIndex;
    bool invert; // Alsa Switch means 1="active"; EVO device stores 1="mute"
};

struct evo_int_ctl_config {
    const char *name;
    __u16 wIndex;
    __u8 base_channel_number; // First channel
    __u8 n_channels;          // 1=single, 2=pair
    short db_min, db_max;
    const unsigned int *tlv;
};

static const struct evo_bool_ctl_config evo_bool_ctl_configs[] = {
    {.name = "Master Playback Switch", .wValue = 0x0100, .wIndex = 0x3B00, .invert = true},
    {.name = "Mic 1 Capture Switch", .wValue = 0x0200, .wIndex = 0x3A00, .invert = true},
    {.name = "Mic 2 Capture Switch", .wValue = 0x0201, .wIndex = 0x3A00, .invert = true},
    {.name = "Mic 1 Phantom 48V Capture Switch", .wValue = 0x0000, .wIndex = 0x3A00},
    {.name = "Mic 2 Phantom 48V Capture Switch", .wValue = 0x0001, .wIndex = 0x3A00},
};

static const struct evo_int_ctl_config evo_db_ctl_configs[] = {
    {
        .name = "Master Playback Volume",
        .wIndex = FU10_WINDEX,
        .base_channel_number = 1,
        .n_channels = 1,
        .db_min = EVO4_VOL_DB_MIN,
        .db_max = EVO4_VOL_DB_MAX,
        .tlv = evo_vol_tlv,
    },
    {
        .name = "Mic 1 Capture Volume",
        .wIndex = FU11_WINDEX,
        .base_channel_number = 1,
        .n_channels = 1,
        .db_min = EVO4_GAIN_DB_MIN,
        .db_max = EVO4_GAIN_DB_MAX,
        .tlv = evo_gain_tlv,
    },
    {
        .name = "Mic 2 Capture Volume",
        .wIndex = FU11_WINDEX,
        .base_channel_number = 2,
        .n_channels = 1,
        .db_min = EVO4_GAIN_DB_MIN,
        .db_max = EVO4_GAIN_DB_MAX,
        .tlv = evo_gain_tlv,
    },
};

struct evo_device {
    struct usb_device *udev;
    struct miscdevice misc;
    struct mutex lock;
    struct kref kref;
    char name[8]; /* "evo4" or "evo8" */
    // [ALSA]
    struct snd_card *card;
    struct {
        bool bool_switches[ARRAY_SIZE(evo_bool_ctl_configs)];
        int db_ranges[ARRAY_SIZE(evo_db_ctl_configs)];
        int direct_monitor;
    } cache;
};

static void evo_delete(struct kref *kref)
{
    struct evo_device *dev = container_of_const(kref, struct evo_device, kref);
    kfree(dev);
}

static int evo_open(struct inode *inode, struct file *file)
{
    struct evo_device *dev = container_of_const(file->private_data, struct evo_device, misc);
    kref_get(&dev->kref);
    file->private_data = dev;
    return 0;
}

static int evo_release(struct inode *inode, struct file *file)
{
    struct evo_device *dev = file->private_data;
    kref_put(&dev->kref, evo_delete);
    return 0;
}

/* Control-transfer helper, used by: 1. ioctl, 2. ALSA kcontrol.
 * <data> must be a DMA-able buffer.
 *
 * Returns bytes trasferred or -errno.
 */
static int evo_ctrl(struct evo_device *dev, __u8 bRequest, __u8 bRequestType, __u16 wValue,
                    __u16 wIndex, void *data, __u16 wLength)
{
    unsigned int pipe;
    int ret;

    mutex_lock(&dev->lock);

    if (!dev->udev) {
        mutex_unlock(&dev->lock);
        return -ENODEV;
    }

    if (bRequestType & USB_DIR_IN)
        pipe = usb_rcvctrlpipe(dev->udev, 0);
    else
        pipe = usb_sndctrlpipe(dev->udev, 0);

    ret = usb_control_msg(dev->udev, pipe, bRequest, bRequestType, wValue, wIndex, data, wLength,
                          1000);

    mutex_unlock(&dev->lock);
    return ret;
}

static int evo_recv_bool(struct evo_device *dev, __u16 wValue, __u16 wIndex, bool *on)
{
    __le32 *buf;
    int ret;

    buf = kmalloc(sizeof(*buf), GFP_KERNEL);
    if (!buf)
        return -ENOMEM;

    ret = evo_ctrl(dev, EVO_REQ_CUR, EVO_REQTYPE_GET, wValue, wIndex, buf, sizeof(*buf));
    if (ret >= 0)
        *on = (le32_to_cpu(*buf) == 1);

    kfree(buf);
    return ret < 0 ? ret : 0;
}

static int evo_send_bool(struct evo_device *dev, __u16 wValue, __u16 wIndex, bool on)
{
    __le32 *buf;
    int ret;

    buf = kmalloc(sizeof(*buf), GFP_KERNEL);
    if (!buf)
        return -ENOMEM;

    *buf = cpu_to_le32(on ? 1 : 0);
    ret = evo_ctrl(dev, EVO_REQ_CUR, EVO_REQTYPE_SET, wValue, wIndex, buf, sizeof(*buf));

    kfree(buf);
    return ret < 0 ? ret : 0;
}

static int evo_recv_s16(struct evo_device *dev, __u16 wValue, __u16 wIndex, s16 *out)
{
    __le16 *buf;
    int ret;

    buf = kmalloc(sizeof(*buf), GFP_KERNEL);
    if (!buf)
        return -ENOMEM;

    ret = evo_ctrl(dev, EVO_REQ_CUR, EVO_REQTYPE_GET, wValue, wIndex, buf, sizeof(*buf));
    if (ret >= 0)
        *out = le16_to_cpu(*buf);

    kfree(buf);
    return ret < 0 ? ret : 0;
}

static int evo_send_s16(struct evo_device *dev, __u16 wValue, __u16 wIndex, s16 val)
{
    __le16 *buf;
    int ret;

    buf = kmalloc(sizeof(*buf), GFP_KERNEL);
    if (!buf)
        return -ENOMEM;

    *buf = cpu_to_le16(val);
    ret = evo_ctrl(dev, EVO_REQ_CUR, EVO_REQTYPE_SET, wValue, wIndex, buf, sizeof(*buf));

    kfree(buf);
    return ret < 0 ? ret : 0;
}

static int evo_bool_get(struct snd_kcontrol *k, struct snd_ctl_elem_value *v)
{
    struct evo_device *dev = snd_kcontrol_chip(k);
    v->value.integer.value[0] = dev->cache.bool_switches[k->private_value];
    return 0;
}

static int evo_bool_put(struct snd_kcontrol *k, struct snd_ctl_elem_value *v)
{
    struct evo_device *dev = snd_kcontrol_chip(k);
    const unsigned int idx = k->private_value;
    const struct evo_bool_ctl_config *c = &evo_bool_ctl_configs[idx];
    bool on = !!v->value.integer.value[0];
    int ret;

    if (on == dev->cache.bool_switches[idx])
        return 0;

    bool evo_on = c->invert ? !on : on;
    ret = evo_send_bool(dev, c->wValue, c->wIndex, evo_on);
    if (ret < 0)
        return ret;

    dev->cache.bool_switches[idx] = on;
    return 1;
}

static int evo_db_info(struct snd_kcontrol *k, struct snd_ctl_elem_info *u)
{
    const struct evo_int_ctl_config *c = &evo_db_ctl_configs[k->private_value];
    u->type = SNDRV_CTL_ELEM_TYPE_INTEGER;
    u->count = 1;
    u->value.integer.min = c->db_min;
    u->value.integer.max = c->db_max;
    u->value.integer.step = 1;
    return 0;
}

static int evo_db_get(struct snd_kcontrol *k, struct snd_ctl_elem_value *v)
{
    struct evo_device *dev = snd_kcontrol_chip(k);
    v->value.integer.value[0] = dev->cache.db_ranges[k->private_value];
    return 0;
}

static int evo_db_put(struct snd_kcontrol *k, struct snd_ctl_elem_value *v)
{
    struct evo_device *dev = snd_kcontrol_chip(k);
    const unsigned int idx = k->private_value;
    const struct evo_int_ctl_config *c = &evo_db_ctl_configs[idx];
    int db = clamp_t(int, v->value.integer.value[0], c->db_min, c->db_max);
    s16 raw = EVO_DB_TO_RAW(db);
    int ret;

    if (db == dev->cache.db_ranges[idx])
        return 0;

    // TODO: On EVO4, setting 1 channel from a pair also sets the other one, on EVO8
    // they can be separated - try if it works and place argument for channel
    for (int cn = c->base_channel_number; cn < c->base_channel_number + c->n_channels; cn++) {
        ret = evo_send_s16(dev, FU_WVALUE(cn), c->wIndex, raw);
        if (ret < 0)
            return ret;
    }
    dev->cache.db_ranges[idx] = db;
    return 1;
}

static int evo4_direct_monitor_info(struct snd_kcontrol *k, struct snd_ctl_elem_info *u)
{
    u->type = SNDRV_CTL_ELEM_TYPE_INTEGER;
    u->count = 1;
    u->value.integer.min = EVO4_DIRECT_MONITOR_MIN;
    u->value.integer.max = EVO4_DIRECT_MONITOR_MAX;
    u->value.integer.step = 1;
    return 0;
}

static int evo4_direct_monitor_get(struct snd_kcontrol *k, struct snd_ctl_elem_value *v)
{
    struct evo_device *dev = snd_kcontrol_chip(k);
    v->value.integer.value[0] = dev->cache.direct_monitor;
    return 0;
}

static int evo4_direct_monitor_put(struct snd_kcontrol *k, struct snd_ctl_elem_value *v)
{
    struct evo_device *dev = snd_kcontrol_chip(k);
    int ratio =
        clamp_t(int, v->value.integer.value[0], EVO4_DIRECT_MONITOR_MIN, EVO4_DIRECT_MONITOR_MAX);
    s16 raw;
    int ret;

    if (ratio == dev->cache.direct_monitor)
        return 0;

    raw = DIV_ROUND_CLOSEST(ratio * 127, EVO4_DIRECT_MONITOR_MAX);
    ret = evo_send_s16(dev, EU56_WVALUE, EU56_WINDEX, raw);
    if (ret < 0)
        return ret;

    dev->cache.direct_monitor = ratio;
    return 1;
}

static long evo_ioctl(struct file *file, unsigned int cmd, unsigned long arg)
{
    struct evo_device *dev = file->private_data;
    struct evo_ctrl_xfer xfer;
    void *dmabuf;
    int ret;

    if (cmd != EVO_CTRL_TRANSFER)
        return -ENOTTY;

    if (copy_from_user(&xfer, (void __user *)arg, sizeof(xfer)))
        return -EFAULT;

    if (xfer.wLength > EVO_MAX_DATA)
        return -EINVAL;

    /* usb_control_msg requires a DMA-able buffer, not stack memory */
    dmabuf = kmalloc(xfer.wLength ?: 1, GFP_KERNEL);
    if (!dmabuf)
        return -ENOMEM;

    /* For OUT transfers, copy data into the DMA buffer */
    if (!(xfer.bRequestType & USB_DIR_IN))
        memcpy(dmabuf, xfer.data, xfer.wLength);

    ret = evo_ctrl(dev, xfer.bRequest, xfer.bRequestType, xfer.wValue, xfer.wIndex, dmabuf,
                   xfer.wLength);

    if (ret < 0) {
        kfree(dmabuf);
        return ret;
    }

    /* For IN transfers, copy the response data back to userspace */
    if (xfer.bRequestType & USB_DIR_IN) {
        memcpy(xfer.data, dmabuf, ret);
        xfer.wLength = ret;
        if (copy_to_user((void __user *)arg, &xfer, sizeof(xfer))) {
            kfree(dmabuf);
            return -EFAULT;
        }
    }

    kfree(dmabuf);
    return ret;
}

static const struct file_operations evo_fops = {
    .owner = THIS_MODULE,
    .open = evo_open,
    .release = evo_release,
    .unlocked_ioctl = evo_ioctl,
};

static const char *evo_find_name(__u16 pid)
{
    int i;
    for (i = 0; i < ARRAY_SIZE(evo_models); i++) {
        if (evo_models[i].pid == pid)
            return evo_models[i].name;
    }
    return NULL;
}

static int evo_probe(struct usb_interface *intf, const struct usb_device_id *id)
{
    struct usb_device *udev = interface_to_usbdev(intf);
    struct evo_device *dev;
    const char *name;
    int err;

    /*
     * snd-usb-audio claims interfaces 0-2 (audio control + streaming).
     * Interface 3 (DFU) is unclaimed - we use it just to get the usb_device handle.
     * All communication goes via endpoint 0 (control pipe).
     */
    if (intf->cur_altsetting->desc.bInterfaceNumber != 3)
        return -ENODEV;

    name = evo_find_name(le16_to_cpu(udev->descriptor.idProduct));
    if (!name)
        return -ENODEV;

    dev = kzalloc(sizeof(*dev), GFP_KERNEL);
    if (!dev)
        return -ENOMEM;

    mutex_init(&dev->lock);
    kref_init(&dev->kref);
    strscpy(dev->name, name, sizeof(dev->name));
    dev->udev = usb_get_dev(udev);
    dev->misc.minor = MISC_DYNAMIC_MINOR;
    dev->misc.name = dev->name;
    dev->misc.fops = &evo_fops;

    if (misc_register(&dev->misc)) {
        dev_err(&intf->dev, "failed to register /dev/%s\n", dev->name);
        err = -ENODEV;
        goto err_put;
    }

    // [ALSA] Create logical Sound Card
    // TODO: -1 means "first free slot"; pass string instead NULL for stable hw:<NAME>
    err = snd_card_new(&intf->dev, -1, NULL, THIS_MODULE, 0, &dev->card);
    if (err < 0)
        goto err_misc;

    strscpy(dev->card->driver, "evo_raw", sizeof(dev->card->driver));
    strscpy(dev->card->shortname, "EVO4 Mixer", sizeof(dev->card->shortname));
    snprintf(dev->card->longname, sizeof(dev->card->longname), "Audient %s control mixer",
             dev->name);

    // [ALSA] Register boolean-switch EVO controls
    struct snd_kcontrol_new bool_ctl = {
        .iface = SNDRV_CTL_ELEM_IFACE_MIXER,
        .info = snd_ctl_boolean_mono_info,
        .get = evo_bool_get,
        .put = evo_bool_put,
    };

    for (int i = 0; i < ARRAY_SIZE(evo_bool_ctl_configs); i++) {
        const struct evo_bool_ctl_config *c = &evo_bool_ctl_configs[i];
        bool_ctl.name = c->name;
        bool_ctl.private_value = i;
        err = snd_ctl_add(dev->card, snd_ctl_new1(&bool_ctl, dev));
        if (err < 0)
            goto err_snd;

        bool value;
        if (evo_recv_bool(dev, c->wValue, c->wIndex, &value) == 0)
            dev->cache.bool_switches[i] = c->invert ? !value : value;
    }

    // [ALSA] Register decibel-range-based EVO controls
    struct snd_kcontrol_new db_ctl = {
        .iface = SNDRV_CTL_ELEM_IFACE_MIXER,
        .access = SNDRV_CTL_ELEM_ACCESS_READWRITE | SNDRV_CTL_ELEM_ACCESS_TLV_READ,
        .info = evo_db_info,
        .get = evo_db_get,
        .put = evo_db_put,
        .tlv.p = evo_vol_tlv,
    };

    for (int i = 0; i < ARRAY_SIZE(evo_db_ctl_configs); i++) {
        const struct evo_int_ctl_config *c = &evo_db_ctl_configs[i];
        db_ctl.name = c->name;
        db_ctl.private_value = i;
        db_ctl.tlv.p = c->tlv;
        err = snd_ctl_add(dev->card, snd_ctl_new1(&db_ctl, dev));
        if (err < 0)
            goto err_snd;

        s16 value;
        if (evo_recv_s16(dev, FU_WVALUE(c->base_channel_number), c->wIndex, &value) == 0)
            dev->cache.db_ranges[i] = EVO_RAW_TO_DB(value);
    }

    // [ALSA] Register Direct Monitor EVO control
    static const struct snd_kcontrol_new evo4_direct_monitor_ctl = {
        .iface = SNDRV_CTL_ELEM_IFACE_MIXER,
        .name = "Direct Monitor Playback Volume",
        .info = evo4_direct_monitor_info,
        .get = evo4_direct_monitor_get,
        .put = evo4_direct_monitor_put
    };

    err = snd_ctl_add(dev->card, snd_ctl_new1(&evo4_direct_monitor_ctl, dev));
    if (err < 0)
        goto err_snd;
    s16 raw;
    if (evo_recv_s16(dev, EU56_WVALUE, EU56_WINDEX, &raw) == 0)
        dev->cache.direct_monitor = DIV_ROUND_CLOSEST(raw * 100, 127);


    err = snd_card_register(dev->card);
    if (err < 0)
        goto err_snd;

    dev_info(&intf->dev, "Audient %s raw control registered at /dev/%s\n", dev->name, dev->name);
    usb_set_intfdata(intf, dev);
    return 0;

err_snd:
    snd_card_free(dev->card);
err_misc:
    misc_deregister(&dev->misc);
err_put:
    usb_put_dev(dev->udev);
    kfree(dev);
    return err;
}

static void evo_disconnect(struct usb_interface *intf)
{
    struct evo_device *dev = usb_get_intfdata(intf);

    if (!dev)
        return;

    snd_card_free(dev->card);

    mutex_lock(&dev->lock);
    misc_deregister(&dev->misc);
    usb_put_dev(dev->udev);
    dev->udev = NULL;
    mutex_unlock(&dev->lock);

    dev_info(&intf->dev, "Audient %s raw control disconnected\n", dev->name);
    kref_put(&dev->kref, evo_delete);
}

static const struct usb_device_id evo_id_table[] = {
    {USB_DEVICE(AUDIENT_VID, EVO4_PID)}, {USB_DEVICE(AUDIENT_VID, EVO8_PID)}, {}};
MODULE_DEVICE_TABLE(usb, evo_id_table);

static struct usb_driver evo_driver = {
    .name = "evo_raw",
    .id_table = evo_id_table,
    .probe = evo_probe,
    .disconnect = evo_disconnect,
};
module_usb_driver(evo_driver);

MODULE_LICENSE("GPL");
MODULE_AUTHOR("audient-evo-py contributors");
MODULE_DESCRIPTION("Raw USB control transfer access for Audient EVO series");
