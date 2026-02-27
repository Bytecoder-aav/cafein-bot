import os
import logging
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes, ConversationHandler
)

# ── КОНФІГ ──
BOT_TOKEN   = os.environ.get("BOT_TOKEN", "")
ADMIN_CHAT  = int(os.environ.get("CHAT_ID_ADMIN", "0"))

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ── СТАНИ РОЗМОВИ ──
SELECT_DRINKS, SELECT_QTY, SELECT_TIME, CUSTOM_TIME, CONFIRM = range(5)

# ── МЕНЮ (з сайту Cafe!n) ──
MENU = {
    "☕ Кава": [
        ("Еспресо",       "40"),
        ("Американо",     "45"),
        ("Капучино",      "60"),
        ("Віденська кава","60"),
        ("Допіо",         "70"),
        ("Лате",          "70"),
        ("Флет Уайт",     "80"),
        ("Раф",           "80"),
    ],
    "🌿 На рослинній основі": [
        ("Американо з молоком", "60"),
        ("Капучино",            "100"),
        ("Лате",                "120"),
        ("Дитячий лате",        "80/100"),
        ("Какао",               "90/110"),
        ("Гарячий шоколад",     "100/120"),
    ],
    "🍵 Не кава": [
        ("Чай пакетований", "50"),
        ("Чай фірмовий",    "70"),
        ("Дитячий лате",    "50/60"),
        ("Какао",           "60/70"),
        ("Гарячий шоколад", "70"),
    ],
    "🥪 Перекуси": [
        ("Штолен",         "60"),
        ("Кукіс",          "70"),
        ("Трайфл",         "70"),
        ("Курка в лаваші", "80"),
    ],
}

# Плоский список для зручності
ALL_DRINKS = []
for cat, items in MENU.items():
    for name, price in items:
        ALL_DRINKS.append({"name": name, "price": price, "cat": cat})

# ── КЛАВІАТУРИ ──
def drinks_keyboard(selected: list[int]) -> InlineKeyboardMarkup:
    """Клавіатура вибору напоїв з категоріями."""
    buttons = []
    current_cat = None
    for i, d in enumerate(ALL_DRINKS):
        if d["cat"] != current_cat:
            current_cat = d["cat"]
            # Заголовок категорії (не кнопка, просто текст через кнопку-роздільник)
            buttons.append([InlineKeyboardButton(f"─── {current_cat} ───", callback_data="noop")])
        
        check = "✅ " if i in selected else ""
        label = f"{check}{d['name']} — {d['price']} грн"
        buttons.append([InlineKeyboardButton(label, callback_data=f"drink_{i}")])
    
    # Кнопка підтвердження вибору
    if selected:
        buttons.append([InlineKeyboardButton("✅ Далі →", callback_data="drinks_done")])
    else:
        buttons.append([InlineKeyboardButton("⬆️ Оберіть хоча б один напій", callback_data="noop")])
    
    buttons.append([InlineKeyboardButton("❌ Скасувати", callback_data="cancel")])
    return InlineKeyboardMarkup(buttons)


def qty_keyboard(order: list[dict]) -> InlineKeyboardMarkup:
    """Клавіатура вибору кількості для кожного напою."""
    buttons = []
    for idx, item in enumerate(order):
        name  = item["name"]
        qty   = item["qty"]
        short = name[:20] + "…" if len(name) > 20 else name
        buttons.append([
            InlineKeyboardButton(f"➖", callback_data=f"qty_minus_{idx}"),
            InlineKeyboardButton(f"{short}: {qty} шт", callback_data="noop"),
            InlineKeyboardButton(f"➕", callback_data=f"qty_plus_{idx}"),
        ])
    buttons.append([InlineKeyboardButton("✅ Далі →", callback_data="qty_done")])
    buttons.append([InlineKeyboardButton("◀️ Назад", callback_data="back_to_drinks"),
                    InlineKeyboardButton("❌ Скасувати", callback_data="cancel")])
    return InlineKeyboardMarkup(buttons)


def time_keyboard() -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton("⚡ Через 5 хвилин",  callback_data="time_5")],
        [InlineKeyboardButton("🕐 Через 10 хвилин", callback_data="time_10")],
        [InlineKeyboardButton("🕑 Через 20 хвилин", callback_data="time_20")],
        [InlineKeyboardButton("⏰ Вказати свій час", callback_data="time_custom")],
        [InlineKeyboardButton("◀️ Назад", callback_data="back_to_qty"),
         InlineKeyboardButton("❌ Скасувати", callback_data="cancel")],
    ]
    return InlineKeyboardMarkup(buttons)


def confirm_keyboard() -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton("✅ Підтвердити замовлення", callback_data="confirm_yes")],
        [InlineKeyboardButton("✏️ Змінити", callback_data="back_to_time"),
         InlineKeyboardButton("❌ Скасувати", callback_data="cancel")],
    ]
    return InlineKeyboardMarkup(buttons)


# ── ФОРМАТУВАННЯ ЗАМОВЛЕННЯ ──
def format_order(data: dict, for_admin=False) -> str:
    order   = data.get("order", [])
    time_str = data.get("time_str", "—")
    user    = data.get("user", {})
    total   = sum(int(item["price"].split("/")[0]) * item["qty"] for item in order)

    lines = []
    if for_admin:
        lines.append("🔔 <b>НОВЕ ЗАМОВЛЕННЯ</b>")
        name = user.get("name", "Невідомо")
        username = f" (@{user['username']})" if user.get("username") else ""
        lines.append(f"👤 {name}{username}")
        lines.append(f"🆔 ID: <code>{user.get('id','')}</code>")
        lines.append("")

    lines.append("☕ <b>Замовлення:</b>")
    for item in order:
        price_per = int(item["price"].split("/")[0])
        subtotal  = price_per * item["qty"]
        lines.append(f"  • {item['name']} × {item['qty']} = <b>{subtotal} грн</b>")

    lines.append("")
    lines.append(f"💰 <b>Сума: {total} грн</b>")
    lines.append(f"⏰ <b>Час готовності: {time_str}</b>")
    return "\n".join(lines)


# ── ХЕНДЛЕРИ ──
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data.clear()
    ctx.user_data["selected"] = []

    await update.message.reply_text(
        "👋 Вітаємо у <b>Cafe!n</b>!\n\n"
        "Оберіть напої зі списку нижче.\n"
        "Можна обрати кілька — натискайте на позиції ✅",
        parse_mode="HTML",
        reply_markup=drinks_keyboard([])
    )
    return SELECT_DRINKS


async def select_drink(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data  = query.data

    if data == "noop":
        return SELECT_DRINKS

    if data == "cancel":
        await query.edit_message_text("❌ Замовлення скасовано. Напишіть /start щоб почати знову.")
        ctx.user_data.clear()
        return ConversationHandler.END

    if data == "drinks_done":
        selected = ctx.user_data.get("selected", [])
        if not selected:
            await query.answer("Оберіть хоча б один напій!", show_alert=True)
            return SELECT_DRINKS
        # Ініціалізуємо кількість = 1 для кожного
        ctx.user_data["order"] = [
            {**ALL_DRINKS[i], "qty": 1} for i in selected
        ]
        await query.edit_message_text(
            "🔢 <b>Вкажіть кількість для кожного напою:</b>",
            parse_mode="HTML",
            reply_markup=qty_keyboard(ctx.user_data["order"])
        )
        return SELECT_QTY

    if data.startswith("drink_"):
        idx = int(data.split("_")[1])
        sel = ctx.user_data.setdefault("selected", [])
        if idx in sel:
            sel.remove(idx)
        else:
            sel.append(idx)
        await query.edit_message_reply_markup(reply_markup=drinks_keyboard(sel))
        return SELECT_DRINKS

    return SELECT_DRINKS


async def select_qty(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data  = query.data
    order = ctx.user_data.get("order", [])

    if data == "cancel":
        await query.edit_message_text("❌ Замовлення скасовано. Напишіть /start щоб почати знову.")
        ctx.user_data.clear()
        return ConversationHandler.END

    if data == "back_to_drinks":
        ctx.user_data["order"] = []
        await query.edit_message_text(
            "⬆️ Оберіть напої:",
            parse_mode="HTML",
            reply_markup=drinks_keyboard(ctx.user_data.get("selected", []))
        )
        return SELECT_DRINKS

    if data.startswith("qty_plus_"):
        idx = int(data.split("_")[2])
        if order[idx]["qty"] < 10:
            order[idx]["qty"] += 1
        await query.edit_message_reply_markup(reply_markup=qty_keyboard(order))
        return SELECT_QTY

    if data.startswith("qty_minus_"):
        idx = int(data.split("_")[2])
        if order[idx]["qty"] > 1:
            order[idx]["qty"] -= 1
        await query.edit_message_reply_markup(reply_markup=qty_keyboard(order))
        return SELECT_QTY

    if data == "qty_done":
        await query.edit_message_text(
            "⏰ <b>Коли вам підготувати замовлення?</b>",
            parse_mode="HTML",
            reply_markup=time_keyboard()
        )
        return SELECT_TIME

    return SELECT_QTY


async def select_time(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data  = query.data

    if data == "cancel":
        await query.edit_message_text("❌ Замовлення скасовано. Напишіть /start щоб почати знову.")
        ctx.user_data.clear()
        return ConversationHandler.END

    if data == "back_to_qty":
        await query.edit_message_text(
            "🔢 <b>Вкажіть кількість:</b>",
            parse_mode="HTML",
            reply_markup=qty_keyboard(ctx.user_data.get("order", []))
        )
        return SELECT_QTY

    time_map = {"time_5": "через 5 хвилин", "time_10": "через 10 хвилин", "time_20": "через 20 хвилин"}
    if data in time_map:
        ctx.user_data["time_str"] = time_map[data]
        await show_confirm(query, ctx)
        return CONFIRM

    if data == "time_custom":
        await query.edit_message_text(
            "✏️ Напишіть бажаний час готовності\n"
            "Наприклад: <i>14:30</i> або <i>через 40 хвилин</i>",
            parse_mode="HTML"
        )
        return CUSTOM_TIME

    return SELECT_TIME


async def custom_time(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["time_str"] = update.message.text.strip()
    await update.message.reply_text(
        "📋 Перевірте ваше замовлення:",
        parse_mode="HTML"
    )
    await update.message.reply_text(
        format_order(ctx.user_data),
        parse_mode="HTML",
        reply_markup=confirm_keyboard()
    )
    return CONFIRM


async def show_confirm(query, ctx: ContextTypes.DEFAULT_TYPE):
    await query.edit_message_text(
        "📋 Перевірте ваше замовлення:\n\n" + format_order(ctx.user_data),
        parse_mode="HTML",
        reply_markup=confirm_keyboard()
    )


async def confirm(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data  = query.data

    if data == "cancel":
        await query.edit_message_text("❌ Замовлення скасовано. Напишіть /start щоб почати знову.")
        ctx.user_data.clear()
        return ConversationHandler.END

    if data == "back_to_time":
        await query.edit_message_text(
            "⏰ <b>Коли вам підготувати замовлення?</b>",
            parse_mode="HTML",
            reply_markup=time_keyboard()
        )
        return SELECT_TIME

    if data == "confirm_yes":
        user = update.effective_user
        ctx.user_data["user"] = {
            "id":       user.id,
            "name":     user.full_name,
            "username": user.username,
        }

        # Надіслати замовлення адміну
        try:
            await ctx.bot.send_message(
                chat_id=ADMIN_CHAT,
                text=format_order(ctx.user_data, for_admin=True),
                parse_mode="HTML"
            )
        except Exception as e:
            logger.error(f"Не вдалось надіслати адміну: {e}")

        # Підтвердження клієнту
        now = datetime.now().strftime("%H:%M")
        await query.edit_message_text(
            f"✅ <b>Замовлення прийнято!</b>\n\n"
            f"{format_order(ctx.user_data)}\n\n"
            f"🕐 Замовлення надіслано о {now}\n"
            f"Чекайте на ваш напій ☕",
            parse_mode="HTML"
        )
        ctx.user_data.clear()
        return ConversationHandler.END

    return CONFIRM


async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "ℹ️ <b>Cafe!n — Швидке замовлення</b>\n\n"
        "/start — Зробити замовлення\n"
        "/help — Ця довідка\n\n"
        "📍 просп. Героїв Дніпра, 67, Горішні Плавні\n"
        "🕐 Пн–Нд: 09:00 – 18:00",
        parse_mode="HTML"
    )


async def cancel_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data.clear()
    await update.message.reply_text("❌ Замовлення скасовано. Напишіть /start щоб почати знову.")
    return ConversationHandler.END


# ── ЗАПУСК ──
def main():
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN не задано!")
        return

    app = Application.builder().token(BOT_TOKEN).build()

    conv = ConversationHandler(
        entry_points=[CommandHandler("start", cmd_start)],
        states={
            SELECT_DRINKS: [CallbackQueryHandler(select_drink)],
            SELECT_QTY:    [CallbackQueryHandler(select_qty)],
            SELECT_TIME:   [CallbackQueryHandler(select_time)],
            CUSTOM_TIME:   [MessageHandler(filters.TEXT & ~filters.COMMAND, custom_time)],
            CONFIRM:       [CallbackQueryHandler(confirm)],
        },
        fallbacks=[
            CommandHandler("cancel", cancel_cmd),
            CommandHandler("start", cmd_start),
        ],
        allow_reentry=True,
    )

    app.add_handler(conv)
    app.add_handler(CommandHandler("help", cmd_help))

    logger.info("Бот Cafe!n запущено ✅")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
