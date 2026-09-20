// SPDX-License-Identifier: GPL-2.0-only
/*
 * ocp8178_bl.c - Orient-Chip OCP8178 one-wire backlight driver
 *
 * The OCP8178 LED driver on the ClockworkPi uConsole mainboard is controlled
 * through its EN pin alone. A steady high level gives full brightness, which
 * is what gpio-backlight does. The same pin also speaks a one-wire protocol
 * (EasyScale style): a shutdown-plus-detect sequence enters the mode, then an
 * address byte (0x72) followed by a data byte selects one of 32 levels.
 *
 * Protocol and timings are taken from ClockworkPi's downstream driver
 * (drivers/video/backlight/ocp8178_bl.c in their kernels), which has driven
 * this hardware for years. Differences to that driver:
 *  - the one-wire mode is entered only when the chip is off (first use,
 *    after brightness 0, after suspend), not on every change. Re-entering
 *    costs a 3 ms blank and a stretch with interrupts disabled;
 *  - all 32 levels are exposed (max_brightness = 31) instead of a 10-step table;
 *  - the 3 ms shutdown hold sleeps instead of spinning with interrupts off.
 * Set the module parameter always_reenter=1 to get the downstream behaviour
 * back if a level change ever fails to take effect.
 *
 * The entry sequence begins with EN held low for 3 ms, which also clears the
 * latched-off state that a crashed warm boot can leave the chip in.
 */

#include <linux/backlight.h>
#include <linux/delay.h>
#include <linux/gpio/consumer.h>
#include <linux/interrupt.h>
#include <linux/module.h>
#include <linux/of.h>
#include <linux/platform_device.h>
#include <linux/property.h>

#define OCP8178_MAX_LEVEL	31	/* 5-bit data byte */
#define OCP8178_ADDRESS		0x72

/* Timings in microseconds, from the downstream driver */
#define T_SHUTDOWN_US		3000	/* EN low: chip off, one-wire mode left */
#define T_DETECT_DELAY_US	200	/* EN high before the detect pulse */
#define T_DETECT_LOW_US		500	/* detect pulse */
#define T_DETECT_WINDOW_US	1000	/* EN high before the first byte */
#define T_START_US		10	/* EN high before a byte */
#define T_END_US		10	/* EN low after a byte */
#define T_BIT1_LOW_US		10	/* a 1 bit: short low, long high */
#define T_BIT1_HIGH_US		50
#define T_BIT0_LOW_US		50	/* a 0 bit: long low, short high */
#define T_BIT0_HIGH_US		10

static bool always_reenter;
module_param(always_reenter, bool, 0644);
MODULE_PARM_DESC(always_reenter,
		 "Run the shutdown+detect sequence before every level change (downstream behaviour)");

struct ocp8178 {
	struct gpio_desc *gpiod;
	bool on;		/* EN high and chip in one-wire mode */
};

static void ocp8178_write_byte(struct ocp8178 *ctx, u8 byte)
{
	unsigned long flags;
	int i;

	/* Bit timing is in the tens of microseconds: keep interrupts out. */
	local_irq_save(flags);
	gpiod_set_value(ctx->gpiod, 1);
	udelay(T_START_US);
	for (i = 7; i >= 0; i--) {
		bool bit = byte & BIT(i);

		gpiod_set_value(ctx->gpiod, 0);
		udelay(bit ? T_BIT1_LOW_US : T_BIT0_LOW_US);
		gpiod_set_value(ctx->gpiod, 1);
		udelay(bit ? T_BIT1_HIGH_US : T_BIT0_HIGH_US);
	}
	gpiod_set_value(ctx->gpiod, 0);
	udelay(T_END_US);
	gpiod_set_value(ctx->gpiod, 1);
	local_irq_restore(flags);
}

static void ocp8178_enter(struct ocp8178 *ctx)
{
	unsigned long flags;

	/* Shutdown: also resets a latched-off chip. Nothing time-critical here. */
	gpiod_set_value(ctx->gpiod, 0);
	usleep_range(T_SHUTDOWN_US, T_SHUTDOWN_US + 500);

	local_irq_save(flags);
	gpiod_set_value(ctx->gpiod, 1);
	udelay(T_DETECT_DELAY_US);
	gpiod_set_value(ctx->gpiod, 0);
	udelay(T_DETECT_LOW_US);
	gpiod_set_value(ctx->gpiod, 1);
	local_irq_restore(flags);
	udelay(T_DETECT_WINDOW_US);
	ctx->on = true;
}

static void ocp8178_set_level(struct ocp8178 *ctx, unsigned int level)
{
	int passes = 1;

	if (!ctx->on || always_reenter) {
		ocp8178_enter(ctx);
		passes = 2;	/* downstream writes twice after entering; cheap */
	}
	while (passes--) {
		ocp8178_write_byte(ctx, OCP8178_ADDRESS);
		ocp8178_write_byte(ctx, level & OCP8178_MAX_LEVEL);
	}
}

static int ocp8178_update_status(struct backlight_device *bl)
{
	struct ocp8178 *ctx = bl_get_data(bl);
	int brightness = backlight_get_brightness(bl);	/* 0 when blanked/off */

	if (brightness <= 0) {
		gpiod_set_value(ctx->gpiod, 0);	/* shutdown; next use re-enters */
		ctx->on = false;
		return 0;
	}
	ocp8178_set_level(ctx, brightness);
	return 0;
}

static bool ocp8178_controls_device(struct backlight_device *bl,
				    struct device *display_dev)
{
	return true;	/* one panel on this board */
}

static const struct backlight_ops ocp8178_ops = {
	.options	 = BL_CORE_SUSPENDRESUME,
	.update_status	 = ocp8178_update_status,
	.controls_device = ocp8178_controls_device,
};

static int ocp8178_probe(struct platform_device *pdev)
{
	struct device *dev = &pdev->dev;
	struct backlight_properties props;
	struct backlight_device *bl;
	struct ocp8178 *ctx;
	u32 def = OCP8178_MAX_LEVEL;

	ctx = devm_kzalloc(dev, sizeof(*ctx), GFP_KERNEL);
	if (!ctx)
		return -ENOMEM;

	/*
	 * Output from the start. The first update below begins with the 3 ms
	 * shutdown hold anyway, so starting low costs nothing; leaving the line
	 * as-is (an input after reset) would make every set_value a no-op.
	 */
	ctx->gpiod = devm_gpiod_get(dev, NULL, GPIOD_OUT_LOW);
	if (IS_ERR(ctx->gpiod))
		return dev_err_probe(dev, PTR_ERR(ctx->gpiod),
				     "gpios property missing or invalid\n");
	if (gpiod_cansleep(ctx->gpiod))
		return dev_err_probe(dev, -EINVAL,
				     "the one-wire timing needs a non-sleeping GPIO\n");

	device_property_read_u32(dev, "default-brightness-level", &def);
	if (def > OCP8178_MAX_LEVEL)
		def = OCP8178_MAX_LEVEL;

	memset(&props, 0, sizeof(props));
	props.type = BACKLIGHT_RAW;
	props.max_brightness = OCP8178_MAX_LEVEL;
	props.brightness = def;
	props.power = BACKLIGHT_POWER_ON;

	bl = devm_backlight_device_register(dev, dev_name(dev), dev, ctx,
					    &ocp8178_ops, &props);
	if (IS_ERR(bl))
		return dev_err_probe(dev, PTR_ERR(bl), "failed to register backlight\n");

	/*
	 * The chip may be on (steady high from the bootloader or from a
	 * previous kernel) or latched off. Either way we do not know its mode,
	 * so the first update enters one-wire mode from a clean shutdown.
	 */
	ctx->on = false;
	backlight_update_status(bl);

	platform_set_drvdata(pdev, bl);
	dev_info(dev, "OCP8178 one-wire backlight, %u levels, default %u\n",
		 OCP8178_MAX_LEVEL, def);
	return 0;
}

static const struct of_device_id ocp8178_of_match[] = {
	{ .compatible = "orientchip,ocp8178" },
	{ .compatible = "ocp8178-backlight" },	/* ClockworkPi downstream name */
	{ /* sentinel */ }
};
MODULE_DEVICE_TABLE(of, ocp8178_of_match);

static struct platform_driver ocp8178_driver = {
	.driver = {
		.name		= "ocp8178-backlight",
		.of_match_table	= ocp8178_of_match,
	},
	.probe = ocp8178_probe,
};
module_platform_driver(ocp8178_driver);

MODULE_DESCRIPTION("Orient-Chip OCP8178 one-wire backlight driver");
MODULE_LICENSE("GPL");
MODULE_ALIAS("platform:ocp8178-backlight");
