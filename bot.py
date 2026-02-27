import os, logging
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes, ConversationHandler
)

BOT_TOKEN  = os.environ.get("BOT_TOKEN", "")
ADMIN_CHAT = int(os.environ.get("CHAT_ID_ADMIN", "0"))

logging.basicConfig(format="%(asctime)s [%(levelname)s] %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# ── СТАНИ ──
(SELECT_CAT, SELECT_DRINKS, SELECT_QTY,
 SELECT_TIME, CUSTOM_TIME, CONFIRM,
 ADM_PANEL, ADM_ORDER, ADM_MSG) = range(9)

# ── МЕНЮ ──
MENU = {
    "Кава": [
        ("Еспресо","40"),("Американо","45"),("Капучино","60"),
        ("Віденська кава","60"),("Допіо","70"),("Лате","70"),
        ("Флет Уайт","80"),("Раф","80"),
    ],
    "На рослинній основі": [
        ("Американо з молоком","60"),("Капучино","100"),("Лате","120"),
        ("Дитячий лате","80/100"),("Какао","90/110"),("Гарячий шоколад","100/120"),
    ],
    "Не кава": [
        ("Чай пакетований","50"),("Чай фірмовий","70"),
        ("Дитячий лате","50/60"),("Какао","60/70"),("Гарячий шоколад","70"),
    ],
    "Перекуси": [
        ("Штолен","60"),("Кукіс","70"),("Трайфл","70"),("Курка в лаваші","80"),
    ],
}
CAT_EMOJI = {"Кава":"☕","На рослинній основі":"🌿","Не кава":"🍵","Перекуси":"🥪"}
CATS = list(MENU.keys())

# ── ЗАМОВЛЕННЯ (без номерів) ──
orders: dict[str, dict] = {}

import random, string
def new_id() -> str:
    """Короткий читабельний ID: CAF-X7K2"""
    chars = string.ascii_uppercase + string.digits
    suffix = "".join(random.choices(chars, k=4))
    return f"CAF-{suffix}"

STATUS = {
    "new":       "🆕 Нове",
    "accepted":  "👨‍🍳 В роботі",
    "ready":     "✅ Готове",
    "done":      "📦 Видано",
    "cancelled": "❌ Скасовано",
}

# ══════════════════════════════
#  КЛАВІАТУРИ  (префікси: клієнт=c/d/p/m/t/y; адмін=A)
# ══════════════════════════════
def kb_cats(cart):
    total = sum(v["q"] for v in cart.values())
    rows  = []
    for i, cat in enumerate(CATS):
        n = sum(v["q"] for v in cart.values() if v["cat"] == cat)
        badge = f"  ({n})" if n else ""
        rows.append([InlineKeyboardButton(
            f"{CAT_EMOJI[cat]} {cat}{badge}", callback_data=f"c|cat|{i}")])
    if total:
        rows.append([InlineKeyboardButton(f"🛒 Кошик — {total} поз.", callback_data="c|cart|")])
    else:
        rows.append([InlineKeyboardButton("🛒 Кошик порожній", callback_data="c|noop|")])
    rows.append([InlineKeyboardButton("❌ Скасувати", callback_data="c|cancel|")])
    return InlineKeyboardMarkup(rows)

def kb_drinks(ci, cart):
    cat, rows = CATS[ci], []
    for i,(name,price) in enumerate(MENU[cat]):
        key = f"{ci}_{i}"
        q   = cart.get(key, {}).get("q", 0)
        mk  = f"  ✅×{q}" if q else ""
        rows.append([InlineKeyboardButton(
            f"{name} — {price} грн{mk}", callback_data=f"c|drink|{ci}_{i}")])
    total = sum(v["q"] for v in cart.values())
    if total:
        rows.append([InlineKeyboardButton(f"🛒 Кошик — {total} поз.", callback_data="c|cart|")])
    rows.append([InlineKeyboardButton("◀️ Категорії", callback_data="c|cats|"),
                 InlineKeyboardButton("❌ Скасувати",  callback_data="c|cancel|")])
    return InlineKeyboardMarkup(rows)

def kb_cart(cart):
    rows = []
    for key, item in cart.items():
        sh = (item["n"][:16]+"…") if len(item["n"]) > 16 else item["n"]
        rows.append([
            InlineKeyboardButton("➖", callback_data=f"c|minus|{key}"),
            InlineKeyboardButton(f"{sh} ×{item['q']}", callback_data="c|noop|"),
            InlineKeyboardButton("➕", callback_data=f"c|plus|{key}"),
        ])
    rows.append([InlineKeyboardButton("➕ Додати ще", callback_data="c|cats|"),
                 InlineKeyboardButton("⏩ Оформити",   callback_data="c|checkout|")])
    rows.append([InlineKeyboardButton("❌ Скасувати",  callback_data="c|cancel|")])
    return InlineKeyboardMarkup(rows)

def kb_time():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⚡ Через 5 хв",  callback_data="c|t|5")],
        [InlineKeyboardButton("🕐 Через 10 хв", callback_data="c|t|10")],
        [InlineKeyboardButton("🕑 Через 20 хв", callback_data="c|t|20")],
        [InlineKeyboardButton("✏️ Свій час",    callback_data="c|t|custom")],
        [InlineKeyboardButton("◀️ Кошик",       callback_data="c|cart|"),
         InlineKeyboardButton("❌ Скасувати",   callback_data="c|cancel|")],
    ])

def kb_confirm():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Підтвердити замовлення", callback_data="c|confirm|yes")],
        [InlineKeyboardButton("⏰ Змінити час", callback_data="c|confirm|time"),
         InlineKeyboardButton("❌ Скасувати",   callback_data="c|cancel|")],
    ])

# Адмін клавіатури (всі починаються з "A|")
def kb_adm_list(fs=None):
    pool = list(orders.values())
    if fs == "done":  pool = [o for o in pool if o["s"] == "done"]
    elif fs:          pool = [o for o in pool if o["s"] == fs]
    else:             pool = [o for o in pool if o["s"] not in ("done","cancelled")]

    rows = []
    for o in sorted(pool, key=lambda x: x["at"]):
        lbl = f"{STATUS[o['s']]} · {o['u']['name'][:14]} · {o['t']}"
        rows.append([InlineKeyboardButton(lbl, callback_data=f"A|view|{o['id']}")])

    rows.append([
        InlineKeyboardButton("🆕",  callback_data="A|f|new"),
        InlineKeyboardButton("👨‍🍳", callback_data="A|f|accepted"),
        InlineKeyboardButton("✅",  callback_data="A|f|ready"),
        InlineKeyboardButton("📋",  callback_data="A|f|all"),
        InlineKeyboardButton("📦",  callback_data="A|f|done"),
        InlineKeyboardButton("🔄",  callback_data="A|f|refresh"),
    ])
    return InlineKeyboardMarkup(rows)

def kb_adm_order(oid):
    o = orders.get(oid)
    if not o: return InlineKeyboardMarkup([])
    s, rows = o["s"], []
    if s == "new":
        rows.append([InlineKeyboardButton("👨‍🍳 Взяти в роботу",            callback_data=f"A|do|accept|{oid}")])
    if s == "accepted":
        rows.append([InlineKeyboardButton("✅ Готове — сповістити клієнта", callback_data=f"A|do|ready|{oid}")])
    if s == "ready":
        rows.append([InlineKeyboardButton("📦 Видано",                      callback_data=f"A|do|done|{oid}")])
    if s not in ("done","cancelled"):
        rows.append([InlineKeyboardButton("✉️ Написати клієнту",            callback_data=f"A|do|msg|{oid}")])
        rows.append([InlineKeyboardButton("❌ Скасувати замовлення",        callback_data=f"A|do|cancel|{oid}")])
    rows.append([InlineKeyboardButton("◀️ До списку", callback_data="A|back|")])
    return InlineKeyboardMarkup(rows)

# ══════════════════════════════
#  ФОРМАТУВАННЯ
# ══════════════════════════════
def fmt_order(o, adm=False):
    cart  = o["cart"]
    total = sum(int(v["p"].split("/")[0]) * v["q"] for v in cart.values())
    lines = []
    if adm:
        lines += [
            f"🔔 <b>НОВЕ ЗАМОВЛЕННЯ</b>  {STATUS[o['s']]}",
            f"👤 {o['u']['name']}" + (f" (@{o['u']['un']})" if o["u"].get("un") else ""),
            f"🕐 {o['at']}", ""
        ]
    lines.append("☕ <b>Замовлення:</b>")
    for v in cart.values():
        sub = int(v["p"].split("/")[0]) * v["q"]
        lines.append(f"  • {v['n']} ×{v['q']} = <b>{sub} грн</b>")
    lines += ["", f"💰 <b>Разом: {total} грн</b>", f"⏰ <b>Час: {o['t']}</b>"]
    return "\n".join(lines)

def fmt_cart(cart):
    if not cart: return "Кошик порожній"
    total = sum(int(v["p"].split("/")[0]) * v["q"] for v in cart.values())
    lines = [f"  • {v['n']} ×{v['q']} — {int(v['p'].split('/')[0])*v['q']} грн"
             for v in cart.values()]
    lines.append(f"\n💰 <b>Разом: {total} грн</b>")
    return "\n".join(lines)

# ══════════════════════════════
#  КЛІЄНТ — хендлери (callback pattern: ^c\|)
# ══════════════════════════════
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data.clear()
    ctx.user_data["cart"] = {}
    await update.message.reply_text(
        "👋 Вітаємо у <b>Cafe!n</b>!\n\nОберіть категорію меню 👇",
        parse_mode="HTML", reply_markup=kb_cats({})
    )
    return SELECT_CAT

async def client_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    parts = q.data.split("|")          # ["c", action, param]
    action = parts[1] if len(parts) > 1 else ""
    param  = parts[2] if len(parts) > 2 else ""
    cart   = ctx.user_data.setdefault("cart", {})
    state  = ctx.user_data.get("state", SELECT_CAT)

    # ── Скасування ──
    if action == "cancel":
        await q.edit_message_text("❌ Скасовано. /start — почати знову.")
        ctx.user_data.clear()
        return ConversationHandler.END

    # ── noop ──
    if action == "noop":
        return state

    # ── Категорії ──
    if action == "cat":
        ci  = int(param)
        cat = CATS[ci]
        ctx.user_data["ci"]    = ci
        ctx.user_data["state"] = SELECT_DRINKS
        await q.edit_message_text(
            f"{CAT_EMOJI[cat]} <b>{cat}</b>\n\nОберіть позиції (кожне натискання +1):",
            parse_mode="HTML", reply_markup=kb_drinks(ci, cart)
        )
        return SELECT_DRINKS

    if action == "cats":
        ctx.user_data["state"] = SELECT_CAT
        await q.edit_message_text("🗂 <b>Оберіть категорію:</b>",
                                  parse_mode="HTML", reply_markup=kb_cats(cart))
        return SELECT_CAT

    # ── Напій ──
    if action == "drink":
        ci, ii = map(int, param.split("_"))
        cat    = CATS[ci]
        n, p   = MENU[cat][ii]
        key    = f"{ci}_{ii}"
        if key in cart: cart[key]["q"] += 1
        else:           cart[key] = {"n": n, "p": p, "cat": cat, "q": 1}
        await q.answer(f"✅ {n} додано!")
        await q.edit_message_reply_markup(reply_markup=kb_drinks(ci, cart))
        return SELECT_DRINKS

    # ── Кошик ──
    if action == "cart":
        ctx.user_data["state"] = SELECT_QTY
        await q.edit_message_text("🛒 <b>Ваш кошик:</b>\n\n" + fmt_cart(cart),
                                  parse_mode="HTML", reply_markup=kb_cart(cart))
        return SELECT_QTY

    if action == "plus":
        if param in cart: cart[param]["q"] += 1
        await q.edit_message_text("🛒 <b>Ваш кошик:</b>\n\n" + fmt_cart(cart),
                                  parse_mode="HTML", reply_markup=kb_cart(cart))
        return SELECT_QTY

    if action == "minus":
        if param in cart:
            cart[param]["q"] -= 1
            if cart[param]["q"] <= 0: del cart[param]
        if not cart:
            ctx.user_data["state"] = SELECT_CAT
            await q.edit_message_text("🗂 Кошик порожній. Оберіть категорію:",
                                      reply_markup=kb_cats(cart))
            return SELECT_CAT
        await q.edit_message_text("🛒 <b>Ваш кошик:</b>\n\n" + fmt_cart(cart),
                                  parse_mode="HTML", reply_markup=kb_cart(cart))
        return SELECT_QTY

    if action == "checkout":
        ctx.user_data["state"] = SELECT_TIME
        await q.edit_message_text("⏰ <b>Коли підготувати замовлення?</b>",
                                  parse_mode="HTML", reply_markup=kb_time())
        return SELECT_TIME

    # ── Час ──
    if action == "t":
        t_map = {"5": "через 5 хвилин", "10": "через 10 хвилин", "20": "через 20 хвилин"}
        if param in t_map:
            ctx.user_data["t"]     = t_map[param]
            ctx.user_data["state"] = CONFIRM
            tmp = {"id":"", "cart": cart, "t": t_map[param], "s": "new", "u": {}, "at": ""}
            await q.edit_message_text("📋 <b>Перевірте замовлення:</b>\n\n" + fmt_order(tmp),
                                      parse_mode="HTML", reply_markup=kb_confirm())
            return CONFIRM
        if param == "custom":
            await q.edit_message_text(
                "✏️ Напишіть час готовності:\n<i>Наприклад: 14:30 або через 40 хвилин</i>",
                parse_mode="HTML")
            return CUSTOM_TIME

    # ── Підтвердження ──
    if action == "confirm":
        if param == "time":
            ctx.user_data["state"] = SELECT_TIME
            await q.edit_message_text("⏰ <b>Коли підготувати замовлення?</b>",
                                      parse_mode="HTML", reply_markup=kb_time())
            return SELECT_TIME
        if param == "yes":
            return await _place_order(q, ctx)

    return ctx.user_data.get("state", SELECT_CAT)

async def on_custom_time(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["t"] = update.message.text.strip()
    tmp = {"id":"", "cart": ctx.user_data["cart"], "t": ctx.user_data["t"],
           "s": "new", "u": {}, "at": ""}
    await update.message.reply_text("📋 <b>Перевірте замовлення:</b>\n\n" + fmt_order(tmp),
                                    parse_mode="HTML", reply_markup=kb_confirm())
    return CONFIRM

async def _place_order(q, ctx):
    user = q.from_user
    oid  = new_id()
    now  = datetime.now().strftime("%H:%M  %d.%m.%Y")
    o = {
        "id":   oid,
        "u":    {"id": user.id, "name": user.full_name, "un": user.username, "cid": user.id},
        "cart": ctx.user_data["cart"],
        "t":    ctx.user_data["t"],
        "s":    "new",
        "at":   now,
    }
    orders[oid] = o
    try:
        await q.get_bot().send_message(
            chat_id=ADMIN_CHAT,
            text=fmt_order(o, adm=True),
            parse_mode="HTML",
            reply_markup=kb_adm_order(oid)
        )
    except Exception as e:
        logger.error(f"adm send: {e}")
    await q.edit_message_text(
        f"✅ <b>Замовлення прийнято!</b>\n\n"
        f"{fmt_order(o)}\n\n"
        f"⏳ <b>Взято в роботу — очікуйте повідомлення коли буде готово ☕</b>",
        parse_mode="HTML"
    )
    ctx.user_data.clear()
    return ConversationHandler.END

# ══════════════════════════════
#  АДМІН — хендлери (callback pattern: ^A\|)
# ══════════════════════════════
def is_adm(u): return getattr(u, "id", 0) == ADMIN_CHAT

async def cmd_admin(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_adm(update.effective_user):
        await update.message.reply_text("⛔ Доступ заборонено.")
        return ConversationHandler.END
    active = [o for o in orders.values() if o["s"] not in ("done","cancelled")]
    await update.message.reply_text(
        f"👨‍💼 <b>Адмін панель Cafe!n</b>\n\n"
        f"📋 Активних: <b>{len(active)}</b>  /  Всього: <b>{len(orders)}</b>",
        parse_mode="HTML", reply_markup=kb_adm_list()
    )
    return ADM_PANEL

async def cmd_orders(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_adm(update.effective_user): return
    c = {s: sum(1 for o in orders.values() if o["s"] == s) for s in STATUS}
    await update.message.reply_text(
        f"📊 <b>Статистика Cafe!n</b>\n\n"
        f"🆕 Нові:        <b>{c['new']}</b>\n"
        f"👨‍🍳 В роботі: <b>{c['accepted']}</b>\n"
        f"✅ Готові:      <b>{c['ready']}</b>\n"
        f"📦 Видані:      <b>{c['done']}</b>\n"
        f"❌ Скасовані:   <b>{c['cancelled']}</b>\n\n"
        f"📋 Всього за сесію: <b>{len(orders)}</b>",
        parse_mode="HTML", reply_markup=kb_adm_list()
    )
    return ADM_PANEL

async def adm_panel_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not is_adm(update.effective_user):
        await q.answer("⛔ Доступ заборонено", show_alert=True)
        return ADM_PANEL
    await q.answer()
    parts  = q.data.split("|")   # ["A", action, param]
    action = parts[1] if len(parts) > 1 else ""
    param  = parts[2] if len(parts) > 2 else ""

    if action in ("f", "back") or action == "f":
        f_map = {"new":"new","accepted":"accepted","ready":"ready","done":"done","all":None,"refresh":None}
        fs = f_map.get(param)
        active = [o for o in orders.values() if o["s"] not in ("done","cancelled")]
        await q.edit_message_text(
            f"📋 Активних: <b>{len(active)}</b>  /  Всього: <b>{len(orders)}</b>",
            parse_mode="HTML", reply_markup=kb_adm_list(fs)
        )
        return ADM_PANEL

    if action == "view":
        oid = param
        o   = orders.get(oid)
        if not o:
            await q.answer("Замовлення не знайдено", show_alert=True)
            return ADM_PANEL
        ctx.user_data["co"] = oid
        await q.edit_message_text(fmt_order(o, adm=True), parse_mode="HTML",
                                  reply_markup=kb_adm_order(oid))
        return ADM_ORDER

    return ADM_PANEL

async def ntf(ctx, cid, text):
    try:
        await ctx.bot.send_message(chat_id=cid, text=text, parse_mode="HTML")
    except Exception as e:
        logger.error(f"ntf: {e}")

async def adm_order_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not is_adm(update.effective_user):
        await q.answer("⛔ Доступ заборонено", show_alert=True)
        return ADM_ORDER
    await q.answer()
    parts  = q.data.split("|")   # ["A", "do", action, oid]  OR ["A", "back", ""]
    action = parts[1] if len(parts) > 1 else ""
    sub    = parts[2] if len(parts) > 2 else ""
    oid    = parts[3] if len(parts) > 3 else ""

    if action == "back":
        active = [o for o in orders.values() if o["s"] not in ("done","cancelled")]
        await q.edit_message_text(
            f"📋 Активних: <b>{len(active)}</b>  /  Всього: <b>{len(orders)}</b>",
            parse_mode="HTML", reply_markup=kb_adm_list()
        )
        return ADM_PANEL

    if action == "do":
        o = orders.get(oid)
        if not o:
            await q.answer("Не знайдено", show_alert=True)
            return ADM_ORDER

        if sub == "accept":
            o["s"] = "accepted"
            await ntf(ctx, o["u"]["cid"],
                f"👨‍🍳 <b>Ваше замовлення взято в роботу!</b>\n\n"
                f"Час готовності: <b>{o['t']}</b>\nОчікуйте — повідомимо коли буде готово ☕")

        elif sub == "ready":
            o["s"] = "ready"
            await ntf(ctx, o["u"]["cid"],
                f"✅ <b>Ваше замовлення готове!</b>\n\n"
                f"Можете забирати ☕\n📍 просп. Героїв Дніпра, 67")

        elif sub == "done":
            o["s"] = "done"
            await ntf(ctx, o["u"]["cid"],
                f"📦 <b>Замовлення видано. Дякуємо!</b>\n\n"
                f"Раді бачити вас у Cafe!n ❤️\n/start — нове замовлення")

        elif sub == "cancel":
            o["s"] = "cancelled"
            await ntf(ctx, o["u"]["cid"],
                f"❌ <b>На жаль, ваше замовлення скасовано.</b>\n\n"
                f"З питань — звертайтесь до нас.\n/start — нове замовлення")

        elif sub == "msg":
            ctx.user_data["mo"] = oid
            await q.edit_message_text(
                f"✉️ Напишіть повідомлення клієнту:\n(/skip — скасувати)")
            return ADM_MSG

        await q.edit_message_text(fmt_order(o, adm=True), parse_mode="HTML",
                                  reply_markup=kb_adm_order(oid))
        return ADM_ORDER

    return ADM_ORDER

async def adm_msg_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    txt = update.message.text
    oid = ctx.user_data.get("mo")
    o   = orders.get(oid)
    if txt == "/skip" or not o:
        await update.message.reply_text("Скасовано.", reply_markup=kb_adm_list())
        return ADM_PANEL
    await ntf(ctx, o["u"]["cid"],
              f"💬 <b>Повідомлення від Cafe!n:</b>\n\n{txt}")
    await update.message.reply_text("✅ Надіслано.", reply_markup=kb_adm_order(oid))
    return ADM_ORDER

# ══════════════════════════════
#  ЗАГАЛЬНІ КОМАНДИ
# ══════════════════════════════
async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "ℹ️ <b>Cafe!n — Швидке замовлення</b>\n\n"
        "/start  — Зробити замовлення\n"
        "/help   — Довідка\n\n"
        "📍 просп. Героїв Дніпра, 67, Горішні Плавні\n"
        "🕐 Пн–Нд: 09:00 – 18:00",
        parse_mode="HTML")

async def cmd_cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data.clear()
    await update.message.reply_text("❌ Скасовано. /start — почати знову.")
    return ConversationHandler.END

# ══════════════════════════════
#  ЗАПУСК
# ══════════════════════════════
def main():
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN не задано!")
        return

    app = Application.builder().token(BOT_TOKEN).build()

    # Клієнтський ConversationHandler — всі callback мають префікс "c|"
    client = ConversationHandler(
        entry_points=[CommandHandler("start", cmd_start)],
        states={
            SELECT_CAT:    [CallbackQueryHandler(client_cb, pattern=r"^c\|")],
            SELECT_DRINKS: [CallbackQueryHandler(client_cb, pattern=r"^c\|")],
            SELECT_QTY:    [CallbackQueryHandler(client_cb, pattern=r"^c\|")],
            SELECT_TIME:   [CallbackQueryHandler(client_cb, pattern=r"^c\|")],
            CUSTOM_TIME:   [MessageHandler(filters.TEXT & ~filters.COMMAND, on_custom_time)],
            CONFIRM:       [CallbackQueryHandler(client_cb, pattern=r"^c\|")],
        },
        fallbacks=[
            CommandHandler("cancel", cmd_cancel),
            CommandHandler("start",  cmd_start),
        ],
        allow_reentry=True,
    )

    # Адмін ConversationHandler — всі callback мають префікс "A|"
    admin = ConversationHandler(
        entry_points=[
            CommandHandler("admin",  cmd_admin),
            CommandHandler("orders", cmd_orders),
        ],
        states={
            ADM_PANEL: [CallbackQueryHandler(adm_panel_cb, pattern=r"^A\|")],
            ADM_ORDER: [CallbackQueryHandler(adm_order_cb, pattern=r"^A\|")],
            ADM_MSG:   [
                MessageHandler(filters.TEXT & ~filters.COMMAND, adm_msg_handler),
                CommandHandler("skip", adm_msg_handler),
            ],
        },
        fallbacks=[CommandHandler("cancel", cmd_cancel)],
        allow_reentry=True,
    )

    app.add_handler(client)
    app.add_handler(admin)
    app.add_handler(CommandHandler("help", cmd_help))

    logger.info("✅ Cafe!n бот v3 запущено")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
