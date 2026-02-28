import os, logging
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes, ConversationHandler
)

BOT_TOKEN  = os.environ.get("BOT_TOKEN", "")
ADMIN_CHAT = int(os.environ.get("CHAT_ID_ADMIN", "-1003316723038"))  # група
ADMIN_IDS  = {8582499564, 7444305927, 782023256}  # адміни (без групи)

logging.basicConfig(format="%(asctime)s [%(levelname)s] %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# ── СТАНИ ──
(SELECT_CAT, SELECT_DRINKS, SELECT_QTY,
 SELECT_TIME, CUSTOM_TIME, CONFIRM) = range(6)

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
CAT_EMOJI = {"Кава": "☕", "На рослинній основі": "🌿", "Не кава": "🍵", "Перекуси": "🥪"}
CATS = list(MENU.keys())

# ── ДАНІ ──
orders: dict = {}
_order_counter: dict = {}

# Відстеження reply від клієнтів: {(client_chat_id, message_id): order_id}
client_msg_map: dict = {}

STATUS = {
    "new":       "🆕 Нове",
    "accepted":  "👨‍🍳 В роботі",
    "ready":     "✅ Готове",
    "done":      "📦 Видано",
    "cancelled": "❌ Скасовано",
}


def new_id() -> str:
    today = datetime.now().strftime("%d%m%y")
    _order_counter[today] = _order_counter.get(today, 0) + 1
    return f"{today}-{_order_counter[today]:03d}"


def is_adm(u) -> bool:
    return getattr(u, "id", 0) in ADMIN_IDS


def has_sizes(price: str) -> bool:
    return "/" in price


# ══════════════════════════════
#  КЛАВІАТУРИ
# ══════════════════════════════
def kb_cats(cart):
    total = sum(v["q"] for v in cart.values())
    rows = []
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
    for i, (name, price) in enumerate(MENU[cat]):
        base_key = f"{ci}_{i}"
        if has_sizes(price):
            p1, p2 = price.split("/")
            q_s = cart.get(f"{base_key}_s", {}).get("q", 0)
            q_l = cart.get(f"{base_key}_l", {}).get("q", 0)
            mk_s = f" ✅×{q_s}" if q_s else ""
            mk_l = f" ✅×{q_l}" if q_l else ""
            # Рядок 1: назва (неактивна кнопка)
            rows.append([InlineKeyboardButton(f"  {name}", callback_data="c|noop|")])
            # Рядок 2: S і L з цінами
            rows.append([
                InlineKeyboardButton(f"S — {p1} грн{mk_s}", callback_data=f"c|drink|{base_key}_s"),
                InlineKeyboardButton(f"L — {p2} грн{mk_l}", callback_data=f"c|drink|{base_key}_l"),
            ])
        else:
            q = cart.get(base_key, {}).get("q", 0)
            mk = f"  ✅×{q}" if q else ""
            rows.append([InlineKeyboardButton(
                f"{name} — {price} грн{mk}", callback_data=f"c|drink|{base_key}")])
    total = sum(v["q"] for v in cart.values())
    if total:
        rows.append([InlineKeyboardButton(f"🛒 Кошик — {total} поз.", callback_data="c|cart|")])
    rows.append([InlineKeyboardButton("◀️ Категорії", callback_data="c|cats|"),
                 InlineKeyboardButton("❌ Скасувати",  callback_data="c|cancel|")])
    return InlineKeyboardMarkup(rows)


def kb_cart(cart):
    rows = []
    for key, item in cart.items():
        sh = (item["n"][:18] + "…") if len(item["n"]) > 18 else item["n"]
        rows.append([
            InlineKeyboardButton("➖", callback_data=f"c|minus|{key}"),
            InlineKeyboardButton(f"{sh} ×{item['q']}", callback_data="c|noop|"),
            InlineKeyboardButton("➕", callback_data=f"c|plus|{key}"),
        ])
    rows.append([InlineKeyboardButton("➕ Додати ще", callback_data="c|cats|"),
                 InlineKeyboardButton("⏩ Оформити",   callback_data="c|checkout|")])
    rows.append([InlineKeyboardButton("❌ Скасувати", callback_data="c|cancel|")])
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


def kb_adm_list(fs=None):
    pool = list(orders.values())
    if fs == "done":  pool = [o for o in pool if o["s"] == "done"]
    elif fs:          pool = [o for o in pool if o["s"] == fs]
    else:             pool = [o for o in pool if o["s"] not in ("done", "cancelled")]
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
    if not o:
        return InlineKeyboardMarkup([])
    s, rows = o["s"], []
    if s == "new":
        rows.append([InlineKeyboardButton("👨‍🍳 Взяти в роботу",             callback_data=f"A|do|accept|{oid}")])
    if s == "accepted":
        rows.append([InlineKeyboardButton("✅ Готове — сповістити клієнта",  callback_data=f"A|do|ready|{oid}")])
    if s == "ready":
        rows.append([InlineKeyboardButton("📦 Видано",                       callback_data=f"A|do|done|{oid}")])
    if s not in ("done", "cancelled"):
        rows.append([InlineKeyboardButton("✉️ Написати клієнту",             callback_data=f"A|do|msg|{oid}")])
        rows.append([InlineKeyboardButton("❌ Скасувати замовлення",         callback_data=f"A|do|cancel|{oid}")])
    rows.append([InlineKeyboardButton("◀️ До списку", callback_data="A|list|")])
    return InlineKeyboardMarkup(rows)


# ══════════════════════════════
#  ФОРМАТУВАННЯ
# ══════════════════════════════
def fmt_order(o, adm=False):
    cart  = o["cart"]
    total = sum(int(v["p"]) * v["q"] for v in cart.values())
    lines = []
    if adm:
        lines += [
            f"🔔 <b>ЗАМОВЛЕННЯ #{o['id']}</b>  {STATUS[o['s']]}",
            f"👤 {o['u']['name']}" + (f" (@{o['u']['un']})" if o["u"].get("un") else ""),
            f"🕐 {o['at']}", "",
        ]
    lines.append("☕ <b>Замовлення:</b>")
    for v in cart.values():
        sub = int(v["p"]) * v["q"]
        lines.append(f"  • {v['n']} ×{v['q']} = <b>{sub} грн</b>")
    lines += ["", f"💰 <b>Разом: {total} грн</b>", f"⏰ <b>Час: {o['t']}</b>"]
    return "\n".join(lines)


def fmt_cart(cart):
    if not cart:
        return "Кошик порожній"
    total = sum(int(v["p"]) * v["q"] for v in cart.values())
    lines = [f"  • {v['n']} ×{v['q']} — {int(v['p']) * v['q']} грн" for v in cart.values()]
    lines.append(f"\n💰 <b>Разом: {total} грн</b>")
    return "\n".join(lines)


# ══════════════════════════════
#  НАДСИЛАННЯ З ВІДСТЕЖЕННЯМ REPLY
# ══════════════════════════════
async def ntf(bot, cid, text, oid=None):
    """Надіслати клієнту. Якщо oid вказано — запам'ятати message_id для перехоплення reply."""
    try:
        msg = await bot.send_message(chat_id=cid, text=text, parse_mode="HTML")
        if oid:
            client_msg_map[(cid, msg.message_id)] = oid
            logger.info(f"ntf: client_msg_map[({cid},{msg.message_id})] = {oid}")
    except Exception as e:
        logger.error(f"ntf error: {e}")


# ══════════════════════════════
#  КЛІЄНТ — хендлери
# ══════════════════════════════
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data.clear()
    ctx.user_data["cart"] = {}
    await update.message.reply_text(
        "👋 Вітаємо у <b>Cafe!n</b>!\n\nОберіть категорію меню 👇",
        parse_mode="HTML", reply_markup=kb_cats({}),
    )
    return SELECT_CAT


async def client_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q      = update.callback_query
    await q.answer()
    parts  = q.data.split("|")
    action = parts[1] if len(parts) > 1 else ""
    param  = parts[2] if len(parts) > 2 else ""
    cart   = ctx.user_data.setdefault("cart", {})
    state  = ctx.user_data.get("state", SELECT_CAT)

    if action == "cancel":
        await q.edit_message_text("❌ Скасовано. /start — почати знову.")
        ctx.user_data.clear()
        return ConversationHandler.END

    if action == "noop":
        return state

    if action == "cat":
        ci  = int(param)
        cat = CATS[ci]
        ctx.user_data["ci"]    = ci
        ctx.user_data["state"] = SELECT_DRINKS
        await q.edit_message_text(
            f"{CAT_EMOJI[cat]} <b>{cat}</b>\n\n"
            f"Оберіть позиції. Де є <b>S / L</b> — виберіть потрібний розмір:",
            parse_mode="HTML", reply_markup=kb_drinks(ci, cart),
        )
        return SELECT_DRINKS

    if action == "cats":
        ctx.user_data["state"] = SELECT_CAT
        await q.edit_message_text("🗂 <b>Оберіть категорію:</b>",
                                  parse_mode="HTML", reply_markup=kb_cats(cart))
        return SELECT_CAT

    if action == "drink":
        key_parts = param.split("_")

        if len(key_parts) == 3:
            # Позиція з розміром: {ci}_{ii}_{s або l}
            ci, ii, size = int(key_parts[0]), int(key_parts[1]), key_parts[2]
            cat   = CATS[ci]
            n, p  = MENU[cat][ii]
            p1, p2 = p.split("/")
            price  = p1 if size == "s" else p2
            label  = "S (малий)" if size == "s" else "L (великий)"
            key    = f"{ci}_{ii}_{size}"
            name   = f"{n} {label}"
            if key in cart:
                cart[key]["q"] += 1
            else:
                cart[key] = {"n": name, "p": price, "cat": cat, "q": 1}
            await q.answer(f"✅ {name} додано!")
            ci_cur = ctx.user_data.get("ci", ci)
            await q.edit_message_reply_markup(reply_markup=kb_drinks(ci_cur, cart))

        else:
            # Звичайна позиція: {ci}_{ii}
            ci, ii = int(key_parts[0]), int(key_parts[1])
            cat    = CATS[ci]
            n, p   = MENU[cat][ii]
            key    = f"{ci}_{ii}"
            if key in cart:
                cart[key]["q"] += 1
            else:
                cart[key] = {"n": n, "p": p, "cat": cat, "q": 1}
            await q.answer(f"✅ {n} додано!")
            await q.edit_message_reply_markup(reply_markup=kb_drinks(ci, cart))

        return SELECT_DRINKS

    if action == "cart":
        ctx.user_data["state"] = SELECT_QTY
        await q.edit_message_text("🛒 <b>Ваш кошик:</b>\n\n" + fmt_cart(cart),
                                  parse_mode="HTML", reply_markup=kb_cart(cart))
        return SELECT_QTY

    if action == "plus":
        if param in cart:
            cart[param]["q"] += 1
        await q.edit_message_text("🛒 <b>Ваш кошик:</b>\n\n" + fmt_cart(cart),
                                  parse_mode="HTML", reply_markup=kb_cart(cart))
        return SELECT_QTY

    if action == "minus":
        if param in cart:
            cart[param]["q"] -= 1
            if cart[param]["q"] <= 0:
                del cart[param]
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

    if action == "t":
        t_map = {"5": "через 5 хвилин", "10": "через 10 хвилин", "20": "через 20 хвилин"}
        if param in t_map:
            ctx.user_data["t"]     = t_map[param]
            ctx.user_data["state"] = CONFIRM
            tmp = {"id": "", "cart": cart, "t": t_map[param], "s": "new", "u": {}, "at": ""}
            await q.edit_message_text("📋 <b>Перевірте замовлення:</b>\n\n" + fmt_order(tmp),
                                      parse_mode="HTML", reply_markup=kb_confirm())
            return CONFIRM
        if param == "custom":
            await q.edit_message_text(
                "✏️ Напишіть час готовності:\n<i>Наприклад: 14:30 або через 40 хвилин</i>",
                parse_mode="HTML")
            return CUSTOM_TIME

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
    tmp = {"id": "", "cart": ctx.user_data["cart"], "t": ctx.user_data["t"],
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
    logger.info(f"Нове замовлення {oid} від {user.full_name} (id={user.id})")
    try:
        sent = await q.get_bot().send_message(
            chat_id=ADMIN_CHAT,
            text=fmt_order(o, adm=True),
            parse_mode="HTML",
            reply_markup=kb_adm_order(oid),
        )
        logger.info(f"Повідомлення адміну надіслано, message_id={sent.message_id}")
    except Exception as e:
        logger.error(f"Помилка надсилання адміну: {e}")
    await q.edit_message_text(
        f"✅ <b>Замовлення прийнято!</b>\n\n{fmt_order(o)}\n\n"
        f"⏳ Очікуйте повідомлення коли буде готово ☕",
        parse_mode="HTML",
    )
    ctx.user_data.clear()
    return ConversationHandler.END


# ══════════════════════════════
#  REPLY ВІД КЛІЄНТА → адміну
# ══════════════════════════════
async def client_reply_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Клієнт відповів на повідомлення від бота — пересилаємо адміну."""
    msg = update.message
    if not msg or not msg.reply_to_message:
        return
    if is_adm(update.effective_user):
        return  # Відповідь від самого адміна — не пересилаємо

    key = (msg.chat_id, msg.reply_to_message.message_id)
    oid = client_msg_map.get(key)
    user = msg.from_user
    text = msg.text or ""

    order_ref = f"замовлення <b>#{oid}</b>" if oid else "невідоме замовлення"
    adm_text = (
        f"💬 <b>Відповідь клієнта</b>\n"
        f"👤 {user.full_name}" + (f" (@{user.username})" if user.username else "") + "\n"
        f"📋 {order_ref}\n\n"
        f"«{text}»"
    )
    try:
        await ctx.bot.send_message(
            chat_id=ADMIN_CHAT,
            text=adm_text,
            parse_mode="HTML",
            reply_markup=kb_adm_order(oid) if oid else None,
        )
    except Exception as e:
        logger.error(f"client_reply_handler: {e}")

    await msg.reply_text("✅ Ваше повідомлення передано до кафе.")


# ══════════════════════════════
#  АДМІН — хендлери
# ══════════════════════════════
async def cmd_admin(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_adm(update.effective_user):
        await update.message.reply_text("⛔ Доступ заборонено.")
        return
    active = [o for o in orders.values() if o["s"] not in ("done", "cancelled")]
    await update.message.reply_text(
        f"👨‍💼 <b>Адмін панель Cafe!n</b>\n\n"
        f"📋 Активних: <b>{len(active)}</b>  /  Всього: <b>{len(orders)}</b>",
        parse_mode="HTML", reply_markup=kb_adm_list(),
    )


async def cmd_orders(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_adm(update.effective_user):
        return
    c = {s: sum(1 for o in orders.values() if o["s"] == s) for s in STATUS}
    await update.message.reply_text(
        f"📊 <b>Статистика Cafe!n</b>\n\n"
        f"🆕 Нові:        <b>{c['new']}</b>\n"
        f"👨‍🍳 В роботі: <b>{c['accepted']}</b>\n"
        f"✅ Готові:      <b>{c['ready']}</b>\n"
        f"📦 Видані:      <b>{c['done']}</b>\n"
        f"❌ Скасовані:   <b>{c['cancelled']}</b>\n\n"
        f"📋 Всього за сесію: <b>{len(orders)}</b>",
        parse_mode="HTML", reply_markup=kb_adm_list(),
    )


async def adm_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    logger.info(f"adm_cb: '{q.data}' від user_id={update.effective_user.id}")
    if not is_adm(update.effective_user):
        await q.answer("⛔ Доступ заборонено", show_alert=True)
        return
    await q.answer()

    parts  = q.data.split("|")
    action = parts[1] if len(parts) > 1 else ""
    param  = parts[2] if len(parts) > 2 else ""
    oid    = parts[3] if len(parts) > 3 else ""

    # ── Список / фільтри ──
    if action in ("f", "list", "back"):
        f_map = {"new": "new", "accepted": "accepted", "ready": "ready",
                 "done": "done", "all": None, "refresh": None}
        fs = f_map.get(param) if action == "f" else None
        active = [o for o in orders.values() if o["s"] not in ("done", "cancelled")]
        try:
            await q.edit_message_text(
                f"📋 Активних: <b>{len(active)}</b>  /  Всього: <b>{len(orders)}</b>",
                parse_mode="HTML", reply_markup=kb_adm_list(fs),
            )
        except Exception:
            pass
        return

    # ── Перегляд замовлення ──
    if action == "view":
        o = orders.get(param)
        if not o:
            await q.answer("Замовлення не знайдено", show_alert=True)
            return
        try:
            await q.edit_message_text(fmt_order(o, adm=True), parse_mode="HTML",
                                      reply_markup=kb_adm_order(param))
        except Exception:
            pass
        return

    # ── Дії ──
    if action == "do":
        o = orders.get(oid)
        if not o:
            await q.answer("Замовлення не знайдено", show_alert=True)
            return

        if param == "accept":
            o["s"] = "accepted"
            await ntf(ctx.bot, o["u"]["cid"],
                      f"👨‍🍳 <b>Ваше замовлення #{oid} взято в роботу!</b>\n\n"
                      f"Час готовності: <b>{o['t']}</b>\n"
                      f"Очікуйте — повідомимо коли буде готово ☕\n\n"
                      f"<i>Якщо є питання — відповідайте на це повідомлення.</i>",
                      oid=oid)

        elif param == "ready":
            o["s"] = "ready"
            await ntf(ctx.bot, o["u"]["cid"],
                      f"✅ <b>Ваше замовлення #{oid} готове!</b>\n\n"
                      f"Можете забирати ☕\n"
                      f"📍 просп. Героїв Дніпра, 67\n\n"
                      f"<i>Якщо є питання — відповідайте на це повідомлення.</i>",
                      oid=oid)

        elif param == "done":
            o["s"] = "done"
            await ntf(ctx.bot, o["u"]["cid"],
                      f"📦 <b>Замовлення #{oid} видано. Дякуємо!</b>\n\n"
                      f"Раді бачити вас у Cafe!n ❤️\n/start — нове замовлення")

        elif param == "cancel":
            o["s"] = "cancelled"
            await ntf(ctx.bot, o["u"]["cid"],
                      f"❌ <b>На жаль, ваше замовлення #{oid} скасовано.</b>\n\n"
                      f"З питань — звертайтесь до нас.\n/start — нове замовлення")

        elif param == "msg":
            ctx.bot_data[f"adm_msg_{update.effective_user.id}"] = oid
            try:
                await q.edit_message_text(
                    f"✉️ Напишіть повідомлення клієнту для замовлення <b>#{oid}</b>:\n"
                    f"(або /skip щоб скасувати)",
                    parse_mode="HTML",
                )
            except Exception:
                pass
            return

        try:
            await q.edit_message_text(fmt_order(o, adm=True), parse_mode="HTML",
                                      reply_markup=kb_adm_order(oid))
        except Exception:
            pass
        return


async def adm_msg_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Текст від адміна: якщо в режимі написання — відправляємо клієнту."""
    if not is_adm(update.effective_user):
        return

    adm_key = f"adm_msg_{update.effective_user.id}"
    oid = ctx.bot_data.get(adm_key)
    if not oid:
        return

    txt = update.message.text
    o   = orders.get(oid)

    if txt == "/skip" or not o:
        ctx.bot_data.pop(adm_key, None)
        active = [x for x in orders.values() if x["s"] not in ("done", "cancelled")]
        await update.message.reply_text(
            f"Скасовано.\n\n📋 Активних: <b>{len(active)}</b>  /  Всього: <b>{len(orders)}</b>",
            parse_mode="HTML", reply_markup=kb_adm_list(),
        )
        return

    # Надсилаємо клієнту із підказкою про reply
    await ntf(ctx.bot, o["u"]["cid"],
              f"💬 <b>Повідомлення від Cafe!n:</b>\n\n{txt}\n\n"
              f"<i>Якщо є питання — відповідайте на це повідомлення.</i>",
              oid=oid)
    ctx.bot_data.pop(adm_key, None)
    await update.message.reply_text(
        f"✅ Повідомлення надіслано клієнту.\n\n{fmt_order(o, adm=True)}",
        parse_mode="HTML", reply_markup=kb_adm_order(oid),
    )


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


async def cmd_test(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid  = update.effective_user.id
    cid  = update.effective_chat.id
    name = update.effective_user.full_name
    adm  = is_adm(update.effective_user)
    await update.message.reply_text(
        f"🔍 <b>Діагностика</b>\n\n"
        f"👤 Ім'я: <b>{name}</b>\n"
        f"🆔 User ID: <code>{uid}</code>\n"
        f"💬 Chat ID: <code>{cid}</code>\n\n"
        f"⚙️ ADMIN_CHAT: <code>{ADMIN_CHAT}</code>\n"
        f"⚙️ ADMIN_IDS: <code>{ADMIN_IDS}</code>\n\n"
        f"{'✅ Маєте адмін-доступ' if adm else '❌ Не маєте адмін-доступу'}",
        parse_mode="HTML",
    )


async def cmd_cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data.clear()
    await update.message.reply_text("❌ Скасовано. /start — почати знову.")
    return ConversationHandler.END


async def unknown_command(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Невідома команда — показуємо довідку."""
    if is_adm(update.effective_user):
        return  # Адміну не заважаємо
    await update.message.reply_text(
        "ℹ️ <b>Cafe!n — Швидке замовлення</b>\n\n"
        "/start  — Зробити замовлення\n"
        "/help   — Довідка\n\n"
        "📍 просп. Героїв Дніпра, 67, Горішні Плавні\n"
        "🕐 Пн–Нд: 09:00 – 18:00",
        parse_mode="HTML")


async def unknown_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Довільний текст поза замовленням — підказуємо що робити."""
    if is_adm(update.effective_user):
        return  # Адміну не заважаємо
    await update.message.reply_text(
        "Щоб зробити замовлення — натисніть /start 👇",
        parse_mode="HTML")


# ══════════════════════════════
#  ЗАПУСК
# ══════════════════════════════
def main():
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN не задано!")
        return

    app = Application.builder().token(BOT_TOKEN).build()

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
    app.add_handler(client)

    # Адмін — глобальні хендлери
    app.add_handler(CommandHandler("admin",  cmd_admin))
    app.add_handler(CommandHandler("orders", cmd_orders))
    app.add_handler(CallbackQueryHandler(adm_cb, pattern=r"^A\|"))

    # Адмін пише клієнту (group=1)
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND,
        adm_msg_handler,
    ), group=1)

    # Клієнт відповідає на повідомлення бота (group=2)
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND & filters.REPLY,
        client_reply_handler,
    ), group=2)

    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("test", cmd_test))

    # Невідомі команди та текст поза розмовою — завжди останніми
    app.add_handler(MessageHandler(filters.COMMAND, unknown_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, unknown_text), group=3)

    logger.info("✅ Cafe!n бот v5 запущено")
    logger.info(f"   ADMIN_CHAT={ADMIN_CHAT}, ADMIN_IDS={ADMIN_IDS}")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
