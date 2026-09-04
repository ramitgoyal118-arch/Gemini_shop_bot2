import sqlite3, secrets
from datetime import datetime, timezone, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters

# =========================
# HARD-CODE YOUR CREDENTIALS
# =========================
BOT_TOKEN = 8972099567:AAGwhTKvAuPF5XcyOfE23Fgu0NWFQYRTEJc
OWNER_ID = 7737039539

DB_FILE = "shop.db"
PRODUCT_ID = "gemini_premium"
PRODUCT_NAME = "Gemini Premium"
DEFAULT_PRICE = 100

def now():
    return datetime.now(timezone.utc).isoformat()

def db():
    c = sqlite3.connect(DB_FILE)
    c.row_factory = sqlite3.Row
    c.execute("""CREATE TABLE IF NOT EXISTS settings(
        k TEXT PRIMARY KEY, v TEXT NOT NULL)""")
    c.execute("""CREATE TABLE IF NOT EXISTS admins(
        user_id INTEGER PRIMARY KEY)""")
    c.execute("""CREATE TABLE IF NOT EXISTS stock(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        product_id TEXT NOT NULL,
        link TEXT NOT NULL UNIQUE,
        sold INTEGER NOT NULL DEFAULT 0)""")
    c.execute("""CREATE TABLE IF NOT EXISTS orders(
        id TEXT PRIMARY KEY,
        user_id INTEGER NOT NULL,
        username TEXT,
        product_id TEXT NOT NULL,
        qty INTEGER NOT NULL,
        price REAL NOT NULL,
        status TEXT NOT NULL,
        payment_txid TEXT,
        paid_at TEXT,
        created_at TEXT NOT NULL)""")
    c.execute("""CREATE TABLE IF NOT EXISTS order_links(
        order_id TEXT NOT NULL,
        link TEXT NOT NULL UNIQUE,
        PRIMARY KEY(order_id, link))""")
    c.execute("""CREATE TABLE IF NOT EXISTS warranty_claims(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        order_id TEXT NOT NULL,
        user_id INTEGER NOT NULL,
        warranty_link TEXT NOT NULL UNIQUE,
        proof TEXT,
        status TEXT NOT NULL DEFAULT 'pending',
        reason TEXT,
        replacement_link TEXT,
        created_at TEXT NOT NULL)""")
    c.commit()
    return c

def is_owner(uid): return uid == OWNER_ID
def is_admin(uid):
    if is_owner(uid): return True
    c=db(); x=c.execute("SELECT 1 FROM admins WHERE user_id=?", (uid,)).fetchone(); c.close()
    return bool(x)

def setting(k, default=""):
    c=db(); r=c.execute("SELECT v FROM settings WHERE k=?", (k,)).fetchone(); c.close()
    return r["v"] if r else default

def set_setting(k,v):
    c=db(); c.execute("INSERT OR REPLACE INTO settings(k,v) VALUES(?,?)",(k,str(v))); c.commit(); c.close()

def price_for(username):
    c=db()
    key=f"price:{username.lower()}" if username else ""
    r=c.execute("SELECT v FROM settings WHERE k=?", (key,)).fetchone()
    g=c.execute("SELECT v FROM settings WHERE k=?", ("price:global",)).fetchone()
    c.close()
    return float(r["v"]) if r else (float(g["v"]) if g else DEFAULT_PRICE)

def stock_count():
    c=db(); n=c.execute("SELECT COUNT(*) n FROM stock WHERE product_id=? AND sold=0",(PRODUCT_ID,)).fetchone()["n"]; c.close()
    return n

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid=update.effective_user.id
    if not setting("bot_on","1") == "1" and not is_admin(uid):
        await update.message.reply_text("🔴 Bot is currently OFF.")
        return
    p=price_for(update.effective_user.username or "")
    kb=[[InlineKeyboardButton("🛒 Buy Gemini Premium", callback_data="buy")],
        [InlineKeyboardButton("💳 Payment Info", callback_data="payinfo")],
        [InlineKeyboardButton("🛡 Warranty", callback_data="warranty_help")]]
    await update.message.reply_text(
        f"✨ {PRODUCT_NAME}\n\nPrice: {p:g}\nStock: {stock_count()}\n\nChoose an option:",
        reply_markup=InlineKeyboardMarkup(kb))

async def botstatus(update, context):
    await update.message.reply_text("🟢 Bot is ON" if setting("bot_on","1")=="1" else "🔴 Bot is OFF")

async def buy_cb(update, context):
    q=update.callback_query; await q.answer()
    uid=q.from_user.id
    if not setting("bot_on","1")=="1" and not is_admin(uid):
        await q.message.reply_text("🔴 Bot is currently OFF."); return
    await q.message.reply_text("Send quantity, e.g. `1`", parse_mode="Markdown")
    context.user_data["buy_qty"]=True

async def text_msg(update, context):
    if not update.message: return
    if context.user_data.pop("buy_qty", False):
        try: qty=int(update.message.text.strip())
        except: qty=0
        if qty<1: await update.message.reply_text("❌ Enter a valid quantity."); return
        available=stock_count()
        if qty>available: await update.message.reply_text(f"❌ Only {available} item(s) available."); return
        price=price_for(update.effective_user.username or "")
        oid=secrets.token_hex(4).upper()
        c=db(); c.execute("""INSERT INTO orders
            (id,user_id,username,product_id,qty,price,status,created_at)
            VALUES(?,?,?,?,?,?,?,?)""",
            (oid,update.effective_user.id,update.effective_user.username or "",
             PRODUCT_ID,qty,price*qty,"awaiting_payment",now()))
        c.commit(); c.close()
        pay=setting("payment_info","Payment instructions are not configured. Contact the owner.")
        await update.message.reply_text(
            f"🧾 Order: {oid}\nProduct: {PRODUCT_NAME}\nQuantity: {qty}\nTotal: {price*qty:g}\n\n"
            f"💳 Payment instructions:\n{pay}\n\nAfter payment send:\n/paid {oid} YOUR_TRANSACTION_ID")
        return
    if context.user_data.get("warranty_order"):
        await warranty_proof(update, context)

async def payinfo(update, context):
    q=update.callback_query; await q.answer()
    await q.message.reply_text("💳 Payment Info\n\n"+setting("payment_info","Not configured."))

async def warranty_help(update, context):
    q=update.callback_query; await q.answer()
    await q.message.reply_text("🛡 Warranty\nUse:\n/warranty ORDER_ID DELIVERED_LINK\nThen send your proof.")

async def paid(update, context):
    if len(context.args)!=2: await update.message.reply_text("Usage: /paid <order_id> <transaction_id>"); return
    oid,tx=context.args
    c=db(); r=c.execute("SELECT * FROM orders WHERE id=? AND user_id=?",(oid,update.effective_user.id)).fetchone()
    if not r: c.close(); await update.message.reply_text("❌ Order not found."); return
    c.execute("UPDATE orders SET status='payment_submitted',payment_txid=? WHERE id=?",(tx,oid)); c.commit(); c.close()
    await update.message.reply_text("✅ Payment proof submitted. Please wait for approval.")

async def approve(update, context):
    if not is_owner(update.effective_user.id): return
    if len(context.args)!=1: await update.message.reply_text("Usage: /approve <order_id>"); return
    oid=context.args[0].upper(); c=db()
    order=c.execute("SELECT * FROM orders WHERE id=?",(oid,)).fetchone()
    if not order or order["status"]!="payment_submitted":
        c.close(); await update.message.reply_text("❌ Invalid order/payment."); return
    rows=c.execute("""SELECT id,link FROM stock WHERE product_id=? AND sold=0
                      GROUP BY link ORDER BY id LIMIT ?""",(PRODUCT_ID,order["qty"])).fetchall()
    if len(rows)<order["qty"]:
        c.close(); await update.message.reply_text("❌ Not enough unique stock."); return
    links=[r["link"] for r in rows]
    for r in rows:
        c.execute("UPDATE stock SET sold=1 WHERE id=?",(r["id"],))
        c.execute("INSERT INTO order_links(order_id,link) VALUES(?,?)",(oid,r["link"]))
    paid_at=now()
    c.execute("UPDATE orders SET status='paid',paid_at=? WHERE id=?",(paid_at,oid)); c.commit(); c.close()
    await update.message.reply_text("✅ Order approved and fulfilled.")
    await context.bot.send_message(order["user_id"],
        f"🎉 Payment approved!\nOrder: {oid}\n\nYour links:\n"+"\n".join(links)+
        "\n\n🛡 Warranty: valid for 24 hours.\nUse /warranty "+oid+" YOUR_LINK")

async def reject(update, context):
    if not is_owner(update.effective_user.id): return
    if len(context.args)!=1: await update.message.reply_text("Usage: /reject <order_id>"); return
    oid=context.args[0].upper(); c=db()
    r=c.execute("SELECT * FROM orders WHERE id=?",(oid,)).fetchone()
    if not r or r["status"]!="payment_submitted":
        c.close(); await update.message.reply_text("❌ Invalid order."); return
    c.execute("UPDATE orders SET status='rejected' WHERE id=?",(oid,)); c.commit(); c.close()
    await update.message.reply_text("❌ Payment rejected.")
    await context.bot.send_message(r["user_id"],"❌ Payment rejected. Contact the owner.")

async def warranty(update, context):
    if len(context.args)!=2: await update.message.reply_text("Usage: /warranty <order_id> <link>"); return
    oid=context.args[0].upper(); link=context.args[1]
    c=db(); o=c.execute("SELECT * FROM orders WHERE id=? AND user_id=? AND status='paid'",(oid,update.effective_user.id)).fetchone()
    if not o: c.close(); await update.message.reply_text("❌ Order not eligible."); return
    paid=datetime.fromisoformat(o["paid_at"])
    if datetime.now(timezone.utc)>paid+timedelta(hours=24):
        c.close(); await update.message.reply_text("❌ 24-hour warranty expired."); return
    ok=c.execute("SELECT 1 FROM order_links WHERE order_id=? AND link=?",(oid,link)).fetchone()
    claimed=c.execute("SELECT 1 FROM warranty_claims WHERE warranty_link=?",(link,)).fetchone()
    c.close()
    if not ok: await update.message.reply_text("❌ Link was not delivered in this order."); return
    if claimed: await update.message.reply_text("❌ This link already has a warranty claim."); return
    context.user_data["warranty_order"]=oid; context.user_data["warranty_link"]=link
    await update.message.reply_text("🛡 Claim started. Send your proof now (text/photo/document).")

async def warranty_proof(update, context):
    oid=context.user_data.get("warranty_order"); link=context.user_data.get("warranty_link")
    if not oid or not link: return
    proof=update.message.text or ""
    if update.message.photo: proof="[PHOTO] "+str(update.message.photo[-1].file_id)
    if update.message.document: proof="[DOCUMENT] "+update.message.document.file_id
    c=db()
    try:
        c.execute("""INSERT INTO warranty_claims(order_id,user_id,warranty_link,proof,created_at)
                     VALUES(?,?,?,?,?)""",(oid,update.effective_user.id,link,proof,now()))
        cid=c.execute("SELECT last_insert_rowid() x").fetchone()["x"]; c.commit()
    except sqlite3.IntegrityError:
        c.close(); await update.message.reply_text("❌ This link already has a claim."); return
    c.close(); context.user_data.clear()
    await update.message.reply_text("✅ Warranty claim submitted.")
    await context.bot.send_message(OWNER_ID,f"🛡 Warranty Claim #{cid}\nOrder: {oid}\nLink: {link}\nProof: {proof[:300]}")

async def addlink(update, context):
    if not is_admin(update.effective_user.id): return
    if len(context.args)<1: await update.message.reply_text("Usage: /addlink <link>"); return
    link=" ".join(context.args).strip(); c=db()
    try:
        c.execute("INSERT INTO stock(product_id,link) VALUES(?,?)",(PRODUCT_ID,link)); c.commit()
        msg="✅ Stock link added."
    except sqlite3.IntegrityError: msg="❌ Duplicate link. Already exists."
    c.close(); await update.message.reply_text(msg)

async def checkduplicates(update, context):
    if not is_owner(update.effective_user.id): return
    c=db(); rows=c.execute("""SELECT link,COUNT(*) n FROM stock GROUP BY link HAVING n>1""").fetchall(); c.close()
    await update.message.reply_text("✅ No duplicates." if not rows else "⚠️ Duplicates:\n"+"\n".join(f"{r['n']}× {r['link']}" for r in rows))

async def setpaymentinfo(update, context):
    if not is_owner(update.effective_user.id): return
    info=" ".join(context.args).strip()
    if not info: await update.message.reply_text("Usage: /setpaymentinfo <instructions>"); return
    set_setting("payment_info",info); await update.message.reply_text("✅ Payment info updated.")

async def setprice(update, context):
    if not is_owner(update.effective_user.id) or len(context.args)!=2: return
    try: v=float(context.args[1])
    except: await update.message.reply_text("❌ Invalid price."); return
    set_setting("price:global",v); await update.message.reply_text(f"✅ Global price: {v:g}")

async def setuserprice(update, context):
    if not is_owner(update.effective_user.id) or len(context.args)!=3: return
    try: v=float(context.args[2])
    except: await update.message.reply_text("❌ Invalid price."); return
    set_setting(f"price:{context.args[0].lstrip('@').lower()}",v); await update.message.reply_text("✅ User price updated.")

async def addadmin(update, context):
    if not is_owner(update.effective_user.id) or len(context.args)!=1: return
    c=db(); c.execute("INSERT OR IGNORE INTO admins(user_id) VALUES(?)",(int(context.args[0]),)); c.commit(); c.close()
    await update.message.reply_text("✅ Admin added.")

async def removeadmin(update, context):
    if not is_owner(update.effective_user.id) or len(context.args)!=1: return
    c=db(); c.execute("DELETE FROM admins WHERE user_id=?",(int(context.args[0]),)); c.commit(); c.close()
    await update.message.reply_text("✅ Admin removed.")

async def bot_on(update, context):
    if is_owner(update.effective_user.id): set_setting("bot_on","1"); await update.message.reply_text("🟢 Bot ON")

async def bot_off(update, context):
    if is_owner(update.effective_user.id): set_setting("bot_on","0"); await update.message.reply_text("🔴 Bot OFF")

async def warranty_approve(update, context):
    if not is_owner(update.effective_user.id) or len(context.args)!=1: return
    cid=int(context.args[0]); c=db(); r=c.execute("SELECT * FROM warranty_claims WHERE id=?",(cid,)).fetchone()
    if not r: c.close(); await update.message.reply_text("❌ Claim not found."); return
    c.execute("UPDATE warranty_claims SET status='approved' WHERE id=?",(cid,)); c.commit(); c.close()
    await update.message.reply_text("✅ Warranty approved.")

async def warranty_reject(update, context):
    if not is_owner(update.effective_user.id) or len(context.args)<1: return
    cid=int(context.args[0]); reason=" ".join(context.args[1:]) or "Rejected"
    c=db(); r=c.execute("SELECT * FROM warranty_claims WHERE id=?",(cid,)).fetchone()
    if not r: c.close(); await update.message.reply_text("❌ Claim not found."); return
    c.execute("UPDATE warranty_claims SET status='rejected',reason=? WHERE id=?",(reason,cid)); c.commit(); c.close()
    await update.message.reply_text("❌ Warranty rejected.")

async def warranty_resolve(update, context):
    if not is_owner(update.effective_user.id) or len(context.args)!=2: return
    cid=int(context.args[0]); link=context.args[1]; c=db()
    r=c.execute("SELECT * FROM warranty_claims WHERE id=?",(cid,)).fetchone()
    if not r: c.close(); await update.message.reply_text("❌ Claim not found."); return
    c.execute("UPDATE warranty_claims SET status='resolved',replacement_link=? WHERE id=?",(link,cid)); c.commit(); c.close()
    await update.message.reply_text("✅ Warranty resolved with replacement link.")

def main():
    if not BOT_TOKEN or BOT_TOKEN=="PASTE_NEW_BOT_TOKEN_HERE" or OWNER_ID==0:
        raise RuntimeError("Set BOT_TOKEN and OWNER_ID at the top of bot.py.")
    db().close()
    app=Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start",start))
    app.add_handler(CommandHandler("botstatus",botstatus))
    app.add_handler(CommandHandler("paid",paid))
    app.add_handler(CommandHandler("approve",approve))
    app.add_handler(CommandHandler("reject",reject))
    app.add_handler(CommandHandler("warranty",warranty))
    app.add_handler(CommandHandler("addlink",addlink))
    app.add_handler(CommandHandler("checkduplicates",checkduplicates))
    app.add_handler(CommandHandler("setpaymentinfo",setpaymentinfo))
    app.add_handler(CommandHandler("setprice",setprice))
    app.add_handler(CommandHandler("setuserprice",setuserprice))
    app.add_handler(CommandHandler("addadmin",addadmin))
    app.add_handler(CommandHandler("removeadmin",removeadmin))
    app.add_handler(CommandHandler("bot_on",bot_on))
    app.add_handler(CommandHandler("bot_off",bot_off))
    app.add_handler(CommandHandler("warranty_approve",warranty_approve))
    app.add_handler(CommandHandler("warranty_reject",warranty_reject))
    app.add_handler(CommandHandler("warranty_resolve",warranty_resolve))
    app.add_handler(CallbackQueryHandler(buy_cb,pattern="^buy$"))
    app.add_handler(CallbackQueryHandler(payinfo,pattern="^payinfo$"))
    app.add_handler(CallbackQueryHandler(warranty_help,pattern="^warranty_help$"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND,text_msg))
    print("Bot running...")
    app.run_polling()

if __name__=="__main__":
    main()
