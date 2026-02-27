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

# ── ЗАМОВЛЕННЯ ──
orders: dict[int, dict] = {}
_counter = 0
def new_id():
    global _counter; _counter += 1; return _counter

S = {"new":"🆕 Нове","accepted":"👨‍🍳 В роботі","ready":"✅ Готове","done":"📦 Видано","cancelled":"❌ Скасовано"}

# ══════════════════════════════
#  КЛАВІАТУРИ
# ══════════════════════════════
def kb_cats(cart):
    total = sum(v["q"] for v in cart.values())
    rows  = []
    for i, cat in enumerate(CATS):
        n = sum(v["q"] for v in cart.values() if v["cat"]==cat)
        badge = f"  ({n})" if n else ""
        rows.append([InlineKeyboardButton(f"{CAT_EMOJI[cat]} {cat}{badge}", callback_data=f"c{i}")])
    if total:
        rows.append([InlineKeyboardButton(f"🛒 Кошик — {total} поз.", callback_data="cart")])
    else:
        rows.append([InlineKeyboardButton("🛒 Кошик порожній", callback_data="noop")])
    rows.append([InlineKeyboardButton("❌ Скасувати", callback_data="cancel")])
    return InlineKeyboardMarkup(rows)

def kb_drinks(ci, cart):
    cat  = CATS[ci]
    rows = []
    for i,(name,price) in enumerate(MENU[cat]):
        key = f"{ci}_{i}"
        q   = cart.get(key,{}).get("q",0)
        mk  = f"  ✅×{q}" if q else ""
        rows.append([InlineKeyboardButton(f"{name} — {price} грн{mk}", callback_data=f"d{ci}_{i}")])
    total = sum(v["q"] for v in cart.values())
    if total:
        rows.append([InlineKeyboardButton(f"🛒 Кошик — {total} поз.", callback_data="cart")])
    rows.append([InlineKeyboardButton("◀️ Категорії", callback_data="cats"),
                 InlineKeyboardButton("❌ Скасувати",  callback_data="cancel")])
    return InlineKeyboardMarkup(rows)

def kb_cart(cart):
    rows = []
    for key,item in cart.items():
        sh = (item["n"][:16]+"…") if len(item["n"])>16 else item["n"]
        rows.append([
            InlineKeyboardButton("➖", callback_data=f"m{key}"),
            InlineKeyboardButton(f"{sh} ×{item['q']}", callback_data="noop"),
            InlineKeyboardButton("➕", callback_data=f"p{key}"),
        ])
    rows.append([InlineKeyboardButton("➕ Додати ще",   callback_data="cats"),
                 InlineKeyboardButton("⏩ Оформити",    callback_data="checkout")])
    rows.append([InlineKeyboardButton("❌ Скасувати", callback_data="cancel")])
    return InlineKeyboardMarkup(rows)

def kb_time():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⚡ Через 5 хв",  callback_data="t5")],
        [InlineKeyboardButton("🕐 Через 10 хв", callback_data="t10")],
        [InlineKeyboardButton("🕑 Через 20 хв", callback_data="t20")],
        [InlineKeyboardButton("✏️ Свій час",    callback_data="tcustom")],
        [InlineKeyboardButton("◀️ Кошик",       callback_data="cart"),
         InlineKeyboardButton("❌ Скасувати",   callback_data="cancel")],
    ])

def kb_confirm():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Підтвердити замовлення", callback_data="yes")],
        [InlineKeyboardButton("⏰ Змінити час", callback_data="chtime"),
         InlineKeyboardButton("❌ Скасувати",   callback_data="cancel")],
    ])

def kb_adm_list(fs=None):
    pool = list(orders.values())
    if fs=="done":   pool=[o for o in pool if o["s"]=="done"]
    elif fs:         pool=[o for o in pool if o["s"]==fs]
    else:            pool=[o for o in pool if o["s"] not in ("done","cancelled")]
    rows = []
    for o in sorted(pool, key=lambda x:x["id"]):
        lbl = f"#{o['id']} {S[o['s']]} · {o['u']['name'][:12]} · {o['t']}"
        rows.append([InlineKeyboardButton(lbl, callback_data=f"av{o['id']}")])
    rows.append([
        InlineKeyboardButton("🆕", callback_data="af_new"),
        InlineKeyboardButton("👨‍🍳", callback_data="af_accepted"),
        InlineKeyboardButton("✅", callback_data="af_ready"),
        InlineKeyboardButton("📋", callback_data="af_all"),
        InlineKeyboardButton("📦", callback_data="af_done"),
        InlineKeyboardButton("🔄", callback_data="af_refresh"),
    ])
    return InlineKeyboardMarkup(rows)

def kb_adm_order(oid):
    o = orders.get(oid)
    if not o: return InlineKeyboardMarkup([])
    s    = o["s"]
    rows = []
    if s=="new":      rows.append([InlineKeyboardButton("👨‍🍳 Взяти в роботу",           callback_data=f"aa{oid}")])
    if s=="accepted": rows.append([InlineKeyboardButton("✅ Готове — сповістити клієнта", callback_data=f"ar{oid}")])
    if s=="ready":    rows.append([InlineKeyboardButton("📦 Видано",                      callback_data=f"ad{oid}")])
    if s not in ("done","cancelled"):
        rows.append([InlineKeyboardButton("✉️ Написати клієнту",    callback_data=f"am{oid}")])
        rows.append([InlineKeyboardButton("❌ Скасувати замовлення", callback_data=f"ac{oid}")])
    rows.append([InlineKeyboardButton("◀️ До списку", callback_data="aback")])
    return InlineKeyboardMarkup(rows)

# ══════════════════════════════
#  ФОРМАТУВАННЯ
# ══════════════════════════════
def fmt(o, adm=False):
    cart  = o["cart"]
    total = sum(int(v["p"].split("/")[0])*v["q"] for v in cart.values())
    lines = []
    if adm:
        lines += [f"🔔 <b>ЗАМОВЛЕННЯ #{o['id']}</b>  {S[o['s']]}",
                  f"👤 {o['u']['name']}" + (f" (@{o['u']['un']})" if o['u'].get('un') else ""),
                  f"🕐 {o['at']}", ""]
    lines.append(f"☕ <b>Замовлення #{o['id']}:</b>")
    for v in cart.values():
        sub = int(v["p"].split("/")[0])*v["q"]
        lines.append(f"  • {v['n']} ×{v['q']} = <b>{sub} грн</b>")
    lines += ["", f"💰 <b>Разом: {total} грн</b>", f"⏰ <b>Час: {o['t']}</b>"]
    return "\n".join(lines)

def fmt_cart(cart):
    if not cart: return "Кошик порожній"
    total = sum(int(v["p"].split("/")[0])*v["q"] for v in cart.values())
    lines = [f"  • {v['n']} ×{v['q']} — {int(v['p'].split('/')[0])*v['q']} грн" for v in cart.values()]
    lines.append(f"\n💰 <b>Разом: {total} грн</b>")
    return "\n".join(lines)

# ══════════════════════════════
#  КЛІЄНТ
# ══════════════════════════════
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data.clear()
    ctx.user_data["cart"] = {}
    await update.message.reply_text(
        "👋 Вітаємо у <b>Cafe!n</b>!\n\nОберіть категорію меню 👇",
        parse_mode="HTML", reply_markup=kb_cats({})
    )
    return SELECT_CAT

async def on_cat(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q    = update.callback_query; await q.answer()
    d    = q.data
    cart = ctx.user_data.setdefault("cart", {})

    if d=="noop": return SELECT_CAT
    if d=="cancel":
        await q.edit_message_text("❌ Скасовано. /start — почати знову.")
        ctx.user_data.clear(); return ConversationHandler.END
    if d=="cart":
        await q.edit_message_text("🛒 <b>Ваш кошик:</b>\n\n"+fmt_cart(cart),
                                  parse_mode="HTML", reply_markup=kb_cart(cart))
        return SELECT_QTY
    if d.startswith("c") and d[1:].isdigit():
        ci  = int(d[1:])
        cat = CATS[ci]
        ctx.user_data["ci"] = ci
        await q.edit_message_text(
            f"{CAT_EMOJI[cat]} <b>{cat}</b>\n\nОберіть позиції (кожне натискання +1):",
            parse_mode="HTML", reply_markup=kb_drinks(ci, cart)
        )
        return SELECT_DRINKS
    return SELECT_CAT

async def on_drink(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q    = update.callback_query; await q.answer()
    d    = q.data
    cart = ctx.user_data.setdefault("cart", {})

    if d=="cancel":
        await q.edit_message_text("❌ Скасовано. /start — почати знову.")
        ctx.user_data.clear(); return ConversationHandler.END
    if d=="cats":
        await q.edit_message_text("🗂 <b>Оберіть категорію:</b>",
                                  parse_mode="HTML", reply_markup=kb_cats(cart))
        return SELECT_CAT
    if d=="cart":
        await q.edit_message_text("🛒 <b>Ваш кошик:</b>\n\n"+fmt_cart(cart),
                                  parse_mode="HTML", reply_markup=kb_cart(cart))
        return SELECT_QTY
    if d.startswith("d"):
        rest   = d[1:]
        ci,ii  = map(int, rest.split("_"))
        cat    = CATS[ci]
        n, p   = MENU[cat][ii]
        key    = f"{ci}_{ii}"
        if key in cart: cart[key]["q"] += 1
        else:           cart[key] = {"n":n,"p":p,"cat":cat,"q":1}
        await q.answer(f"✅ {n} додано!")
        await q.edit_message_reply_markup(reply_markup=kb_drinks(ci, cart))
        return SELECT_DRINKS
    return SELECT_DRINKS

async def on_cart(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q    = update.callback_query; await q.answer()
    d    = q.data
    cart = ctx.user_data.setdefault("cart", {})

    if d=="cancel":
        await q.edit_message_text("❌ Скасовано. /start — почати знову.")
        ctx.user_data.clear(); return ConversationHandler.END
    if d=="cats":
        await q.edit_message_text("🗂 <b>Оберіть категорію:</b>",
                                  parse_mode="HTML", reply_markup=kb_cats(cart))
        return SELECT_CAT
    if d.startswith("p"):
        key = d[1:];
        if key in cart: cart[key]["q"] += 1
        await q.edit_message_text("🛒 <b>Ваш кошик:</b>\n\n"+fmt_cart(cart),
                                  parse_mode="HTML", reply_markup=kb_cart(cart))
        return SELECT_QTY
    if d.startswith("m"):
        key = d[1:]
        if key in cart:
            cart[key]["q"] -= 1
            if cart[key]["q"] <= 0: del cart[key]
        if not cart:
            await q.edit_message_text("🗂 Кошик порожній. Оберіть категорію:",
                                      reply_markup=kb_cats(cart))
            return SELECT_CAT
        await q.edit_message_text("🛒 <b>Ваш кошик:</b>\n\n"+fmt_cart(cart),
                                  parse_mode="HTML", reply_markup=kb_cart(cart))
        return SELECT_QTY
    if d=="checkout":
        await q.edit_message_text("⏰ <b>Коли підготувати замовлення?</b>",
                                  parse_mode="HTML", reply_markup=kb_time())
        return SELECT_TIME
    return SELECT_QTY

async def on_time(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q    = update.callback_query; await q.answer()
    d    = q.data
    cart = ctx.user_data.get("cart", {})

    if d=="cancel":
        await q.edit_message_text("❌ Скасовано. /start — почати знову.")
        ctx.user_data.clear(); return ConversationHandler.END
    if d=="cart":
        await q.edit_message_text("🛒 <b>Ваш кошик:</b>\n\n"+fmt_cart(cart),
                                  parse_mode="HTML", reply_markup=kb_cart(cart))
        return SELECT_QTY
    t_map = {"t5":"через 5 хвилин","t10":"через 10 хвилин","t20":"через 20 хвилин"}
    if d in t_map:
        ctx.user_data["t"] = t_map[d]
        tmp = {"id":"—","cart":cart,"t":t_map[d],"s":"new","u":{},"at":""}
        await q.edit_message_text("📋 <b>Перевірте замовлення:</b>\n\n"+fmt(tmp),
                                  parse_mode="HTML", reply_markup=kb_confirm())
        return CONFIRM
    if d=="tcustom":
        await q.edit_message_text(
            "✏️ Напишіть час готовності:\n<i>Наприклад: 14:30 або через 40 хвилин</i>",
            parse_mode="HTML")
        return CUSTOM_TIME
    return SELECT_TIME

async def on_custom_time(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["t"] = update.message.text.strip()
    tmp = {"id":"—","cart":ctx.user_data["cart"],"t":ctx.user_data["t"],"s":"new","u":{},"at":""}
    await update.message.reply_text("📋 <b>Перевірте замовлення:</b>\n\n"+fmt(tmp),
                                    parse_mode="HTML", reply_markup=kb_confirm())
    return CONFIRM

async def on_confirm(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    d = q.data

    if d=="cancel":
        await q.edit_message_text("❌ Скасовано. /start — почати знову.")
        ctx.user_data.clear(); return ConversationHandler.END
    if d=="chtime":
        await q.edit_message_text("⏰ <b>Коли підготувати замовлення?</b>",
                                  parse_mode="HTML", reply_markup=kb_time())
        return SELECT_TIME
    if d=="yes":
        user = update.effective_user
        oid  = new_id()
        now  = datetime.now().strftime("%H:%M  %d.%m.%Y")
        o    = {
            "id": oid,
            "u":  {"id":user.id,"name":user.full_name,"un":user.username,"cid":user.id},
            "cart": ctx.user_data["cart"],
            "t":   ctx.user_data["t"],
            "s":   "new",
            "at":  now,
        }
        orders[oid] = o
        # → Адмін
        try:
            await ctx.bot.send_message(
                chat_id=ADMIN_CHAT, text=fmt(o, adm=True),
                parse_mode="HTML", reply_markup=kb_adm_order(oid)
            )
        except Exception as e:
            logger.error(f"adm send: {e}")
        # → Клієнт
        await q.edit_message_text(
            f"✅ <b>Замовлення #{oid} прийнято!</b>\n\n"
            f"{fmt(o)}\n\n"
            f"⏳ <b>Взято в роботу — очікуйте повідомлення коли буде готово ☕</b>",
            parse_mode="HTML"
        )
        ctx.user_data.clear()
        return ConversationHandler.END
    return CONFIRM

# ══════════════════════════════
#  АДМІН
# ══════════════════════════════
def is_adm(u): return getattr(u,"id",0)==ADMIN_CHAT

async def cmd_admin(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_adm(update.effective_user):
        await update.message.reply_text("⛔ Доступ заборонено."); return ConversationHandler.END
    active = [o for o in orders.values() if o["s"] not in ("done","cancelled")]
    await update.message.reply_text(
        f"👨‍💼 <b>Адмін панель Cafe!n</b>\n\n"
        f"📋 Активних: <b>{len(active)}</b>  /  Всього: <b>{len(orders)}</b>",
        parse_mode="HTML", reply_markup=kb_adm_list()
    )
    return ADM_PANEL

async def cmd_orders(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_adm(update.effective_user): return
    c = {s: sum(1 for o in orders.values() if o["s"]==s) for s in S}
    await update.message.reply_text(
        f"📊 <b>Статистика Cafe!n</b>\n\n"
        f"🆕 Нові:        <b>{c['new']}</b>\n"
        f"👨‍🍳 В роботі: <b>{c['accepted']}</b>\n"
        f"✅ Готові:      <b>{c['ready']}</b>\n"
        f"📦 Видані:      <b>{c['done']}</b>\n"
        f"❌ Скасовані:   <b>{c['cancelled']}</b>\n\n"
        f"📋 Всього: <b>{len(orders)}</b>",
        parse_mode="HTML", reply_markup=kb_adm_list()
    )
    return ADM_PANEL

async def on_adm_panel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not is_adm(update.effective_user):
        await q.answer("⛔ Доступ заборонено", show_alert=True); return ADM_PANEL
    await q.answer(); d = q.data

    f_map = {"af_new":"new","af_accepted":"accepted","af_ready":"ready","af_done":"done"}
    if d in ("af_refresh","af_all"):
        active = [o for o in orders.values() if o["s"] not in ("done","cancelled")]
        await q.edit_message_text(
            f"📋 Активних: <b>{len(active)}</b>  /  Всього: <b>{len(orders)}</b>",
            parse_mode="HTML", reply_markup=kb_adm_list()
        )
        return ADM_PANEL
    if d in f_map:
        fs = f_map[d]
        n  = sum(1 for o in orders.values() if o["s"]==fs)
        await q.edit_message_text(f"{S[fs]}: <b>{n}</b>",
                                  parse_mode="HTML", reply_markup=kb_adm_list(fs))
        return ADM_PANEL
    if d.startswith("av"):
        oid = int(d[2:])
        o   = orders.get(oid)
        if not o: await q.answer("Не знайдено", show_alert=True); return ADM_PANEL
        ctx.user_data["co"] = oid
        await q.edit_message_text(fmt(o, adm=True), parse_mode="HTML",
                                  reply_markup=kb_adm_order(oid))
        return ADM_ORDER
    return ADM_PANEL

async def ntf(ctx, cid, text):
    try: await ctx.bot.send_message(chat_id=cid, text=text, parse_mode="HTML")
    except Exception as e: logger.error(f"ntf: {e}")

async def on_adm_order(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not is_adm(update.effective_user):
        await q.answer("⛔ Доступ заборонено", show_alert=True); return ADM_ORDER
    await q.answer(); d = q.data

    if d=="aback":
        active = [o for o in orders.values() if o["s"] not in ("done","cancelled")]
        await q.edit_message_text(
            f"📋 Активних: <b>{len(active)}</b>  /  Всього: <b>{len(orders)}</b>",
            parse_mode="HTML", reply_markup=kb_adm_list()
        )
        return ADM_PANEL

    ACTIONS = {
        "aa": ("accepted",
               lambda oid: f"👨‍🍳 <b>Замовлення #{oid} взято в роботу!</b>\n\nЧас: <b>{orders[oid]['t']}</b>\nОчікуйте — повідомимо коли буде готово ☕"),
        "ar": ("ready",
               lambda oid: f"✅ <b>Замовлення #{oid} готове!</b>\n\nМожете забирати ☕\n📍 просп. Героїв Дніпра, 67"),
        "ad": ("done",
               lambda oid: f"📦 <b>Замовлення #{oid} видано. Дякуємо!</b>\n\nРаді бачити вас у Cafe!n ❤️\n/start — нове замовлення"),
        "ac": ("cancelled",
               lambda oid: f"❌ <b>Замовлення #{oid} скасовано.</b>\n\n/start — нове замовлення"),
    }
    for pref,(ns,msg_fn) in ACTIONS.items():
        if d.startswith(pref) and d[len(pref):].isdigit():
            oid = int(d[len(pref):])
            o   = orders.get(oid)
            if o:
                o["s"] = ns
                await ntf(ctx, o["u"]["cid"], msg_fn(oid))
                await q.edit_message_text(fmt(o, adm=True), parse_mode="HTML",
                                          reply_markup=kb_adm_order(oid))
            return ADM_ORDER

    if d.startswith("am") and d[2:].isdigit():
        oid = int(d[2:])
        ctx.user_data["mo"] = oid
        await q.edit_message_text(
            f"✉️ Напишіть повідомлення клієнту замовлення #{oid}:\n(/skip — скасувати)"
        )
        return ADM_MSG
    return ADM_ORDER

async def on_adm_msg(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    txt = update.message.text
    oid = ctx.user_data.get("mo")
    o   = orders.get(oid)
    if txt=="/skip" or not o:
        await update.message.reply_text("Скасовано.", reply_markup=kb_adm_list())
        return ADM_PANEL
    await ntf(ctx, o["u"]["cid"],
              f"💬 <b>Повідомлення від Cafe!n (замовлення #{oid}):</b>\n\n{txt}")
    await update.message.reply_text("✅ Надіслано.", reply_markup=kb_adm_order(oid))
    return ADM_ORDER

async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "ℹ️ <b>Cafe!n — Швидке замовлення</b>\n\n"
        "/start  — Зробити замовлення\n"
        "/help   — Довідка\n\n"
        "📍 просп. Героїв Дніпра, 67, Горішні Плавні\n"
        "🕐 Пн–Нд: 09:00 – 18:00", parse_mode="HTML")

async def cmd_cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data.clear()
    await update.message.reply_text("❌ Скасовано. /start — почати знову.")
    return ConversationHandler.END

# ══════════════════════════════
#  ЗАПУСК
# ══════════════════════════════
def main():
    if not BOT_TOKEN: logger.error("BOT_TOKEN не задано!"); return
    app = Application.builder().token(BOT_TOKEN).build()

    client = ConversationHandler(
        entry_points=[CommandHandler("start", cmd_start)],
        states={
            SELECT_CAT:    [CallbackQueryHandler(on_cat)],
            SELECT_DRINKS: [CallbackQueryHandler(on_drink)],
            SELECT_QTY:    [CallbackQueryHandler(on_cart)],
            SELECT_TIME:   [CallbackQueryHandler(on_time)],
            CUSTOM_TIME:   [MessageHandler(filters.TEXT & ~filters.COMMAND, on_custom_time)],
            CONFIRM:       [CallbackQueryHandler(on_confirm)],
        },
        fallbacks=[CommandHandler("cancel", cmd_cancel), CommandHandler("start", cmd_start)],
        allow_reentry=True,
    )
    admin = ConversationHandler(
        entry_points=[CommandHandler("admin", cmd_admin), CommandHandler("orders", cmd_orders)],
        states={
            ADM_PANEL: [CallbackQueryHandler(on_adm_panel)],
            ADM_ORDER: [CallbackQueryHandler(on_adm_order)],
            ADM_MSG:   [MessageHandler(filters.TEXT & ~filters.COMMAND, on_adm_msg),
                        CommandHandler("skip", on_adm_msg)],
        },
        fallbacks=[CommandHandler("cancel", cmd_cancel)],
        allow_reentry=True,
    )
    app.add_handler(client)
    app.add_handler(admin)
    app.add_handler(CommandHandler("help", cmd_help))
    logger.info("✅ Cafe!n бот запущено")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
