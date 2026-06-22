// SPDX-License-Identifier: GPL-2.0+
/*
 * evo_raw - raw USB control transfer access for Audient EVO series
 *
 * This module binds to Audient EVO USB devices and exposes per-device misc
 * devices (/dev/evo4, /dev/evo8). A single ioctl (EVO_CTRL_TRANSFER) lets
 * userspace send/receive arbitrary USB control transfers via the kernel's
 * usb_control_msg(), which bypasses usbfs interface-ownership checks.
 * snd-usb-audio continues to handle audio streaming undisturbed.
 */

#include <linux/fs.h>
#include <linux/kref.h>
#include <linux/miscdevice.h>
#include <linux/module.h>
#include <linux/slab.h>
#include <linux/uaccess.h>
#include <linux/usb.h>

#define AUDIENT_VID 0x2708
#define EVO4_PID 0x0006
#define EVO8_PID 0x0007

#define EVO_MAX_DATA 256

/* Model table - maps PID to device name */
static const struct evo_model {
    __u16 pid;
    const char *name;
} evo_models[] = {
    {EVO4_PID, "evo4"},
    {EVO8_PID, "evo8"},
};

/* ioctl payload - matches the struct userspace packs */
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

struct evo_device {
    struct usb_device *udev;
    struct miscdevice misc;
    struct mutex lock;
    struct kref kref;
    char name[8]; /* "evo4" or "evo8" */
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

    /*
     * snd-usb-audio claims interfaces 0-2 (audio control + streaming).
     * Interface 3 (DFU) is left unbound - we grab it just to get the
     * usb_device handle. We don't actually use interface 3 for anything;
     * all our work goes through endpoint 0 (control pipe).
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
        usb_put_dev(dev->udev);
        kfree(dev);
        return -ENODEV;
    }

    dev_info(&intf->dev, "Audient %s raw control registered at /dev/%s\n", dev->name, dev->name);
    usb_set_intfdata(intf, dev);
    return 0;
}

static void evo_disconnect(struct usb_interface *intf)
{
    struct evo_device *dev = usb_get_intfdata(intf);

    if (!dev)
        return;

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
