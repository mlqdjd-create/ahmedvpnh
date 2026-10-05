import os
import threading
import logging
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from .env
env_path = Path(__file__).resolve().parent / ".env"
load_dotenv(dotenv_path=env_path)

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
OWNER_ID_STR = os.getenv("OWNER_ID", "6803988521").strip()
try:
    OWNER_ID = int(OWNER_ID_STR)
except ValueError:
    OWNER_ID = 6803988521

HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", 8080))
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "").strip().rstrip("/")


def public_base() -> str:
    """رابط الأساس العام لروابط الاشتراك (PUBLIC_BASE_URL أو host:port)."""
    if PUBLIC_BASE_URL:
        return PUBLIC_BASE_URL
    return f"http://{HOST}:{PORT}"

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup
)
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters
)

import database

# Configure logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger("AhmedVpnBot")

# Store conversation state for the owner.
# Schema: {user_id: {"mode": "add|announce|update", "step": "...", "data": {...}}}
SESSIONS = {}


def is_owner(user_id: int) -> bool:
    return user_id == OWNER_ID


def is_admin(user_id: int) -> bool:
    """المالك دائمًا مدير، بالإضافة للمدراء المضافين في قاعدة البيانات."""
    if user_id == OWNER_ID:
        return True
    try:
        return database.is_admin(user_id)
    except Exception:
        return False


def get_main_menu_keyboard():
    keyboard = [
        [
            InlineKeyboardButton("➕ إضافة سيرفر", callback_data="menu_add_server"),
            InlineKeyboardButton("🗑️ مسح سيرفر", callback_data="menu_delete_server_0")
        ],
        [
            InlineKeyboardButton("📋 عرض السيرفرات", callback_data="menu_list_servers"),
            InlineKeyboardButton("🔄 تحديث", callback_data="menu_refresh")
        ],
        [
            InlineKeyboardButton("📢 إعلان للتطبيق", callback_data="menu_announce"),
            InlineKeyboardButton("⬆️ تحديث إجباري", callback_data="menu_update")
        ],
        [
            InlineKeyboardButton("🧩 بروكسي/بايلود لسيرفر", callback_data="menu_advanced_0")
        ],
        [
            InlineKeyboardButton("🔗 روابط الاشتراك المدفوعة", callback_data="menu_subs")
        ],
        [
            InlineKeyboardButton("👥 المدراء", callback_data="menu_admins")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)


def get_flag_for_name(name: str) -> str:
    n = (name or "").upper()
    if "GERMAN" in n or "ألمان" in n:
        return "🇩🇪"
    elif "NETHER" in n or "هولند" in n:
        return "🇳🇱"
    elif "FRANCE" in n or "فرنس" in n:
        return "🇫🇷"
    elif "USA" in n or "AMERICA" in n or "أمريك" in n:
        return "🇺🇸"
    elif "TURK" in n or "ترك" in n:
        return "🇹🇷"
    elif "BRIT" in n or "UK" in n or "بريطان" in n:
        return "🇬🇧"
    elif "SINGAPORE" in n:
        return "🇸🇬"
    elif "CANADA" in n:
        return "🇨🇦"
    return "🌐"


def main_menu_text() -> str:
    count = database.get_servers_count(category="main")
    subcount = database.get_servers_count(category="sub")
    users = database.get_users_count()
    return (
        "🚀 **AHMED VPN — لوحة التحكم بالخوادم** 🛡️\n\n"
        "مرحباً بك في لوحة الإدارة.\n\n"
        f"📱 سيرفرات التطبيق: `{count}`\n"
        f"🔗 سيرفرات الاشتراك: `{subcount}`\n"
        f"👥 عدد الأجهزة المسجّلة: `{users}`\n"
        f"🌐 رابط الـ API للتطبيق:\n`http://{HOST}:{PORT}/api/servers`\n\n"
        "اختر أحد الخيارات للبدء:"
    )


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if not is_admin(user_id):
        await update.message.reply_text(
            "⛔ **عذرًا، هذا البوت خاص بالمدراء فقط.**\n"
            f"آيدي المستخدم الخاص بك: `{user_id}` غير مصرح له.\n\n"
            "💡 أرسل هذا الآيدي للمالك ليضيفك كمدير.",
            parse_mode="Markdown"
        )
        return

    SESSIONS.pop(user_id, None)
    await update.message.reply_text(
        main_menu_text(),
        reply_markup=get_main_menu_keyboard(),
        parse_mode="Markdown"
    )


def sub_picker_view(session, page=0):
    """يبني (النص، الكيبورد) لاختيار السيرفرات بالضغط داخل رابط الاشتراك."""
    servers = database.get_all_servers(category="sub")
    if not servers:
        text = ("⚠️ **لا توجد سيرفرات اشتراك بعد.**\n\n"
                "أضف سيرفرات من نوع **🔗 اشتراك** أولًا (زر «➕ إضافة سيرفر» → اختر «🔗 اشتراك»)،\n"
                "وبعدها سوِّ رابط الاشتراك.")
        keyboard = [[InlineKeyboardButton("🔙 القائمة الرئيسية", callback_data="menu_main")]]
        return text, InlineKeyboardMarkup(keyboard)
    selected = set(session["data"].get("selected", []))
    per_page = 8
    total = len(servers)
    page = max(0, min(page, (total - 1) // per_page))
    start = page * per_page
    end = min(start + per_page, total)
    keyboard = []
    for s in servers[start:end]:
        mark = "☑️" if s["id"] in selected else "☐"
        keyboard.append([InlineKeyboardButton(
            f"{mark} {get_flag_for_name(s['name'])} {s['name']}",
            callback_data=f"sub_tog_{s['id']}_{page}")])
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("⬅️", callback_data=f"sub_sel_{page - 1}"))
    if end < total:
        nav.append(InlineKeyboardButton("➡️", callback_data=f"sub_sel_{page + 1}"))
    if nav:
        keyboard.append(nav)
    keyboard.append([
        InlineKeyboardButton("☑️ تحديد الكل", callback_data=f"sub_all_{page}"),
        InlineKeyboardButton("⬜ مسح", callback_data=f"sub_none_{page}"),
    ])
    keyboard.append([InlineKeyboardButton("✅ إنشاء الرابط", callback_data="sub_confirm")])
    keyboard.append([InlineKeyboardButton("🔙 إلغاء", callback_data="menu_main")])
    text = (
        "🌐 **اختر السيرفرات** التي تريد إضافتها لهذا المستخدم:\n"
        f"(المحدد: **{len(selected)}** من {total})\n\n"
        "اضغط على السيرفر لتحديده/إلغائه، ثم «✅ إنشاء الرابط»."
    )
    return text, InlineKeyboardMarkup(keyboard)


async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = update.effective_user.id

    if not is_admin(user_id):
        await query.edit_message_text("⛔ عذرًا، لست من المدراء.")
        return

    if data == "menu_refresh" or data == "menu_main":
        SESSIONS.pop(user_id, None)
        await query.edit_message_text(
            main_menu_text(),
            reply_markup=get_main_menu_keyboard(),
            parse_mode="Markdown"
        )

    elif data == "menu_add_server":
        SESSIONS[user_id] = {"mode": "add", "step": "name", "data": {}}
        text = (
            "➕ **إضافة سيرفر جديد (الخطوة 1 من 3):**\n\n"
            "أرسل الآن **اسم السيرفر**:\n"
            "*(مثال: Germany 01)*\n\n"
            "💡 أو أرسل رابط السيرفر مباشرة (`vless://...`) ليُحفظ فورًا كسيرفر **رئيسي** للتطبيق."
        )
        keyboard = [[InlineKeyboardButton("🔙 إلغاء", callback_data="menu_main")]]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    elif data == "set_cat_main" or data == "set_cat_sub":
        session = SESSIONS.get(user_id)
        if not session or session.get("mode") != "add":
            await query.answer("انتهت الجلسة، ابدأ من جديد.", show_alert=True)
            return
        cat = "main" if data == "set_cat_main" else "sub"
        session["data"]["category"] = cat
        session["step"] = "protocol"
        label = "📱 رئيسي (للتطبيق)" if cat == "main" else "🔗 اشتراك (معزول)"
        text = (
            f"✅ النوع: **{label}**\n\n"
            "⚡ **الخطوة 2 من 3:** اختر **البروتوكول** من الأزرار أدناه:"
        )
        keyboard = [
            [
                InlineKeyboardButton("VLESS", callback_data="set_proto_VLESS"),
                InlineKeyboardButton("VMESS", callback_data="set_proto_VMESS"),
                InlineKeyboardButton("TROJAN", callback_data="set_proto_TROJAN")
            ],
            [
                InlineKeyboardButton("SSH", callback_data="set_proto_SSH"),
                InlineKeyboardButton("Shadowsocks", callback_data="set_proto_SHADOWSOCKS"),
                InlineKeyboardButton("WireGuard", callback_data="set_proto_WIREGUARD")
            ],
            [InlineKeyboardButton("🔙 إلغاء", callback_data="menu_main")]
        ]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    elif data.startswith("set_proto_"):
        proto = data.split("_")[-1]
        session = SESSIONS.get(user_id)
        if session:
            session["data"]["protocol"] = proto
            session["step"] = "config"
            if proto == "WIREGUARD":
                hint = ("أرسل الآن **إعداد WireGuard** (لازم يبدأ بـ `[Interface]`):\n\n"
                        "`[Interface]` ثم `PrivateKey` و`Address`، ثم `[Peer]` ثم `PublicKey` "
                        "و`Endpoint` و`AllowedIPs`.\n\n"
                        "أو رابط `wg://<base64>`.")
            elif proto == "SSH":
                hint = "أرسل الآن **رابط SSH** (يبدأ بـ `ssh://`)."
            elif proto == "SHADOWSOCKS":
                hint = "أرسل الآن **رابط Shadowsocks** (يبدأ بـ `ss://`)."
            else:
                hint = f"أرسل الآن **رابط السيرفر** (يبدأ بـ `{proto.lower()}://`)."
            text = f"✅ تم اختيار البروتوكول: `{proto}`\n\n🔗 **الخطوة 3 من 3:**\n{hint}"
            keyboard = [[InlineKeyboardButton("🔙 إلغاء", callback_data="menu_main")]]
            await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    elif data == "menu_list_servers":
        servers = database.get_all_servers()
        if not servers:
            text = "📋 **لا توجد سيرفرات مضافة حالياً في قاعدة البيانات.**"
            keyboard = [
                [InlineKeyboardButton("➕ إضافة سيرفر", callback_data="menu_add_server")],
                [InlineKeyboardButton("🔙 رجوع", callback_data="menu_main")]
            ]
            await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
            return

        text = f"📋 **عرض السيرفرات المتاحة ({len(servers)} سيرفر):**\n\n"
        for s in servers:
            flag = get_flag_for_name(s["name"])
            cat_tag = "📱 رئيسي" if (s.get("category") or "main") == "main" else "🔗 اشتراك"
            text += (
                f"━━━━━━━━━━━━━━━━━━━\n"
                f"🔹 **ID:** `{s['id']}`\n"
                f"🏷️ **الاسم:** {flag} {s['name']}\n"
                f"⚡ **البروتوكول:** `{s['protocol']}`\n"
                f"🧩 **النوع:** {cat_tag}\n"
                f"📅 **تاريخ الإضافة:** `{s['created_at']}`\n"
                f"🔗 **الرابط:**\n`{s['config']}`\n"
            )
        text += "━━━━━━━━━━━━━━━━━━━"
        keyboard = [
            [InlineKeyboardButton("➕ إضافة سيرفر", callback_data="menu_add_server")],
            [InlineKeyboardButton("🗑️ مسح سيرفر", callback_data="menu_delete_server_0")],
            [InlineKeyboardButton("🔙 القائمة الرئيسية", callback_data="menu_main")]
        ]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    elif data.startswith("menu_delete_server_"):
        page = int(data.split("_")[-1])
        servers = database.get_all_servers()
        if not servers:
            text = "🗑️ **لا توجد سيرفرات لحذفها حالياً.**"
            keyboard = [[InlineKeyboardButton("🔙 القائمة الرئيسية", callback_data="menu_main")]]
            await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
            return

        per_page = 5
        start_idx = page * per_page
        end_idx = min(start_idx + per_page, len(servers))
        current_page = servers[start_idx:end_idx]

        keyboard = []
        for s in current_page:
            flag = get_flag_for_name(s["name"])
            cat_tag = "📱" if (s.get("category") or "main") == "main" else "🔗"
            keyboard.append([
                InlineKeyboardButton(
                    f"🗑️ {cat_tag} {flag} {s['name']} ({s['protocol']})",
                    callback_data=f"confirm_del_{s['id']}"
                )
            ])

        nav = []
        if page > 0:
            nav.append(InlineKeyboardButton("⬅️ السابق", callback_data=f"menu_delete_server_{page - 1}"))
        if end_idx < len(servers):
            nav.append(InlineKeyboardButton("التالي ➡️", callback_data=f"menu_delete_server_{page + 1}"))
        if nav:
            keyboard.append(nav)

        keyboard.append([InlineKeyboardButton("🔙 القائمة الرئيسية", callback_data="menu_main")])

        text = "🗑️ **اختر السيرفر الذي ترغب بحذفه نهائياً:**"
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    elif data.startswith("confirm_del_"):
        server_id = int(data.split("_")[-1])
        server = database.get_server_by_id(server_id)
        if not server:
            await query.answer("السيرفر غير موجود أو تم حذفه مسبقاً!", show_alert=True)
            await query.edit_message_text("السيرفر غير موجود.", reply_markup=get_main_menu_keyboard())
            return

        flag = get_flag_for_name(server["name"])
        text = (
            f"⚠️ **تأكيد الحذف:**\n\n"
            f"هل أنت متأكد من حذف السيرفر:\n"
            f"**{flag} {server['name']}** (`{server['protocol']}`)\n\n"
            "⚠️ هذه العملية لا يمكن التراجع عنها وسيتم حذفه من قاعدة البيانات وتطبيق المستخدمين."
        )
        keyboard = [
            [
                InlineKeyboardButton("✅ نعم، حذف", callback_data=f"execute_del_{server_id}"),
                InlineKeyboardButton("❌ إلغاء", callback_data="menu_delete_server_0")
            ]
        ]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    elif data.startswith("execute_del_"):
        server_id = int(data.split("_")[-1])
        server = database.get_server_by_id(server_id)
        name = server["name"] if server else f"#{server_id}"
        database.delete_server(server_id)

        await query.answer("تم حذف السيرفر بنجاح!", show_alert=True)
        text = f"✅ **تم حذف السيرفر بنجاح:**\n`{name}`"
        keyboard = [
            [InlineKeyboardButton("🗑️ مسح سيرفر آخر", callback_data="menu_delete_server_0")],
            [InlineKeyboardButton("🔙 القائمة الرئيسية", callback_data="menu_main")]
        ]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    # ---------- Per-server proxy/payload ----------
    elif data.startswith("menu_advanced_"):
        page = int(data.split("_")[-1])
        servers = database.get_all_servers()
        if not servers:
            keyboard = [[InlineKeyboardButton("🔙 القائمة الرئيسية", callback_data="menu_main")]]
            await query.edit_message_text("🧩 لا توجد سيرفرات بعد.", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
            return
        per_page = 5
        start_idx = page * per_page
        end_idx = min(start_idx + per_page, len(servers))
        keyboard = []
        for s in servers[start_idx:end_idx]:
            flag = get_flag_for_name(s["name"])
            has = []
            if s.get("proxy_host") and s.get("proxy_port"):
                has.append("بروكسي")
            if s.get("payload"):
                has.append("بايلود")
            tag = (" — " + " + ".join(has)) if has else ""
            cat_tag = "📱" if (s.get("category") or "main") == "main" else "🔗"
            keyboard.append([InlineKeyboardButton(f"🧩 {cat_tag} {flag} {s['name']}{tag}", callback_data=f"adv_pick_{s['id']}")])
        nav = []
        if page > 0:
            nav.append(InlineKeyboardButton("⬅️ السابق", callback_data=f"menu_advanced_{page - 1}"))
        if end_idx < len(servers):
            nav.append(InlineKeyboardButton("التالي ➡️", callback_data=f"menu_advanced_{page + 1}"))
        if nav:
            keyboard.append(nav)
        keyboard.append([InlineKeyboardButton("🔙 القائمة الرئيسية", callback_data="menu_main")])
        await query.edit_message_text("🧩 **اختر سيرفراً لضبط البروكسي/البايلود الخاص به:**", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    elif data.startswith("adv_pick_"):
        sid = int(data.split("_")[-1])
        server = database.get_server_by_id(sid)
        if not server:
            await query.answer("السيرفر غير موجود", show_alert=True)
            return
        SESSIONS[user_id] = {"mode": "adv", "step": "proxy", "data": {"id": sid, "name": server["name"]}}
        keyboard = [[InlineKeyboardButton("🔙 إلغاء", callback_data="menu_main")]]
        await query.edit_message_text(
            f"🧩 **{server['name']}**\n\nأرسل **البروكسي** بصيغة `host:port`\n(أو أرسل `-` لتخطي البروكسي ومسحه):",
            reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    # ---------- Subscriptions ----------
    elif data == "menu_subs":
        SESSIONS.pop(user_id, None)
        text = (
            "🔗 **روابط الاشتراك المدفوعة**\n\n"
            "كل رابط = مستخدم محدد، وله تاريخ انتهاء. الرابط يشتغل في أي\n"
            "تطبيق v2ray و يتحدّث تلقائيًا مع سيرفراتك.\n\n"
            "اختر:"
        )
        keyboard = [
            [InlineKeyboardButton("➕ إنشاء رابط اشتراك", callback_data="sub_create")],
            [InlineKeyboardButton("📋 عرض الروابط", callback_data="sub_list")],
            [InlineKeyboardButton("🔙 القائمة الرئيسية", callback_data="menu_main")],
        ]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    elif data == "sub_create":
        SESSIONS[user_id] = {"mode": "sub", "step": "label", "data": {}}
        text = (
            "➕ **إنشاء رابط اشتراك (الخطوة 1 من 3):**\n\n"
            "أرسل **اسم/ملاحظة للمستخدم** (مثال: أحمد — شهر 10):"
        )
        keyboard = [[InlineKeyboardButton("🔙 إلغاء", callback_data="menu_main")]]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    elif data == "sub_list":
        subs = database.list_subscriptions()
        if not subs:
            text = "📋 **لا توجد روابط اشتراك بعد.**"
            keyboard = [
                [InlineKeyboardButton("➕ إنشاء رابط", callback_data="sub_create")],
                [InlineKeyboardButton("🔙 القائمة الرئيسية", callback_data="menu_main")],
            ]
            await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
            return
        import time as _t
        now = int(_t.time())
        text = f"📋 **روابط الاشتراك ({len(subs)}):**\n\n"
        for s in subs:
            exp = s.get("expires_at")
            state = "🟢 نشط" if s.get("active") else "🔴 موقوف"
            if exp:
                try:
                    from datetime import datetime as _dt
                    ep = int(_dt.strptime(str(exp), "%Y-%m-%d %H:%M:%S").timestamp())
                    state += " — ⛔ منتهي" if ep < now else f" — ⏳ حتى `{exp}`"
                except Exception:
                    state += f" — ⏳ حتى `{exp}`"
            else:
                state += " — ∞ بلا انتهاء"
            text += (
                f"━━━━━━━━━━━━━━━━━━━\n"
                f"🏷️ **{s.get('label') or '—'}**\n"
                f"• الحالة: {state}\n"
                f"• السيرفرات: `{s.get('server_ids') or 'الكل'}`\n"
                f"🔗 `{public_base()}/sub/{s['token']}`\n"
            )
        text += "━━━━━━━━━━━━━━━━━━━"
        keyboard = [
            [InlineKeyboardButton("➕ إنشاء رابط", callback_data="sub_create")],
            [InlineKeyboardButton("🗑️ إلغاء رابط", callback_data="sub_del_0")],
            [InlineKeyboardButton("🔙 القائمة الرئيسية", callback_data="menu_main")],
        ]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    elif data.startswith("sub_del_"):
        page = int(data.split("_")[-1])
        subs = database.list_subscriptions()
        if not subs:
            keyboard = [[InlineKeyboardButton("🔙 القائمة الرئيسية", callback_data="menu_main")]]
            await query.edit_message_text("لا توجد روابط.", reply_markup=InlineKeyboardMarkup(keyboard))
            return
        per_page = 5
        start_idx = page * per_page
        end_idx = min(start_idx + per_page, len(subs))
        keyboard = []
        for s in subs[start_idx:end_idx]:
            keyboard.append([InlineKeyboardButton(
                f"🗑️ {s.get('label') or s['token'][:8]}",
                callback_data=f"sub_confirm_del_{s['token']}")])
        nav = []
        if page > 0:
            nav.append(InlineKeyboardButton("⬅️ السابق", callback_data=f"sub_del_{page - 1}"))
        if end_idx < len(subs):
            nav.append(InlineKeyboardButton("التالي ➡️", callback_data=f"sub_del_{page + 1}"))
        if nav:
            keyboard.append(nav)
        keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data="menu_subs")])
        await query.edit_message_text("🗑️ **اختر الرابط الذي تريد إلغاءه:**",
                                      reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    elif data.startswith("sub_confirm_del_"):
        token = data[len("sub_confirm_del_"):]
        sub = database.get_subscription(token)
        label = (sub.get("label") if sub else "") or token[:8]
        text = f"⚠️ **تأكيد الإلغاء:**\n\nحذف رابط الاشتراك الخاص بـ **{label}** نهائيًا؟"
        keyboard = [
            [InlineKeyboardButton("✅ نعم، احذف", callback_data=f"sub_exec_del_{token}")],
            [InlineKeyboardButton("❌ إلغاء", callback_data="sub_del_0")],
        ]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    elif data.startswith("sub_exec_del_"):
        token = data[len("sub_exec_del_"):]
        database.delete_subscription(token)
        await query.answer("تم حذف الرابط.", show_alert=True)
        text = "✅ **تم حذف رابط الاشتراك.**"
        keyboard = [[InlineKeyboardButton("🔙 روابط الاشتراك", callback_data="menu_subs")]]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    elif data.startswith("sub_sel_"):
        page = int(data.split("_")[-1])
        session = SESSIONS.get(user_id)
        if not session or session.get("mode") != "sub":
            await query.answer("انتهت الجلسة، ابدأ من جديد.", show_alert=True)
            return
        txt, kb = sub_picker_view(session, page)
        await query.edit_message_text(txt, reply_markup=kb, parse_mode="Markdown")

    elif data.startswith("sub_tog_"):
        parts = data.split("_")
        sid = int(parts[2])
        page = int(parts[3])
        session = SESSIONS.get(user_id)
        if not session or session.get("mode") != "sub":
            await query.answer("انتهت الجلسة، ابدأ من جديد.", show_alert=True)
            return
        sel = session["data"].setdefault("selected", [])
        if sid in sel:
            sel.remove(sid)
        else:
            sel.append(sid)
        txt, kb = sub_picker_view(session, page)
        await query.edit_message_text(txt, reply_markup=kb, parse_mode="Markdown")

    elif data.startswith("sub_all_"):
        page = int(data.split("_")[-1])
        session = SESSIONS.get(user_id)
        if not session or session.get("mode") != "sub":
            await query.answer("انتهت الجلسة، ابدأ من جديد.", show_alert=True)
            return
        session["data"]["selected"] = [s["id"] for s in database.get_all_servers(category="sub")]
        txt, kb = sub_picker_view(session, page)
        await query.edit_message_text(txt, reply_markup=kb, parse_mode="Markdown")

    elif data.startswith("sub_none_"):
        page = int(data.split("_")[-1])
        session = SESSIONS.get(user_id)
        if not session or session.get("mode") != "sub":
            await query.answer("انتهت الجلسة، ابدأ من جديد.", show_alert=True)
            return
        session["data"]["selected"] = []
        txt, kb = sub_picker_view(session, page)
        await query.edit_message_text(txt, reply_markup=kb, parse_mode="Markdown")

    elif data == "sub_confirm":
        session = SESSIONS.get(user_id)
        if not session or session.get("mode") != "sub":
            await query.answer("انتهت الجلسة، ابدأ من جديد.", show_alert=True)
            return
        sel = session["data"].get("selected", [])
        if not sel:
            await query.answer("اختر سيرفر واحد على الأقل (أو «تحديد الكل»).", show_alert=True)
            return
        server_ids = ",".join(str(x) for x in sel)
        info = database.create_subscription(
            label=session["data"].get("label", ""),
            days=session["data"].get("days", 0),
            server_ids=server_ids,
        )
        SESSIONS.pop(user_id, None)
        url = f"{public_base()}/sub/{info['token']}"
        exp = info.get("expires_at")
        text = (
            "🎉 **تم إنشاء رابط الاشتراك!**\n\n"
            f"• المستخدم: **{info.get('label') or '—'}**\n"
            f"• الانتهاء: `{exp or 'بلا انتهاء'}`\n"
            f"• عدد السيرفرات: `{len(sel)}`\n\n"
            f"🔗 **الرابط:**\n`{url}`\n\n"
            "أرسله للمستخدم: يلصقه في «استيراد اشتراك» وتنضاف له كل السيرفرات المحددة دفعة وحدة."
        )
        keyboard = [
            [InlineKeyboardButton("➕ رابط آخر", callback_data="sub_create")],
            [InlineKeyboardButton("📋 عرض الروابط", callback_data="sub_list")],
            [InlineKeyboardButton("🔙 القائمة الرئيسية", callback_data="menu_main")],
        ]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    # ---------- Admins (owner only) ----------
    elif data == "menu_admins":
        if not is_owner(user_id):
            await query.answer("هذا الخيار للمالك فقط.", show_alert=True)
            return
        admins = database.list_admins()
        text = f"👥 **إدارة المدراء** ({len(admins)})\n\nالمالك: `{OWNER_ID}`\n\n"
        if admins:
            for a in admins:
                text += f"• **{a.get('name') or '—'}** — `{a['user_id']}`\n"
        else:
            text += "_لا يوجد مدراء مضافون بعد._\n"
        keyboard = [
            [InlineKeyboardButton("➕ إضافة مدير", callback_data="admin_add")],
            [InlineKeyboardButton("🗑️ إزالة مدير", callback_data="admin_del_0")],
            [InlineKeyboardButton("🔙 القائمة الرئيسية", callback_data="menu_main")],
        ]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    elif data == "admin_add":
        if not is_owner(user_id):
            await query.answer("هذا الخيار للمالك فقط.", show_alert=True)
            return
        SESSIONS[user_id] = {"mode": "admin", "step": "add_id", "data": {}}
        text = (
            "➕ **إضافة مدير**\n\n"
            "أرسل **آيدي التليجرام** (رقم) للمستخدم الذي تريد إضافته كمدير،\n"
            "أو **اعمل فوروارد** لرسالة منه هنا.\n\n"
            "💡 المستخدم يشوف آيديه لما يرسل /start للبوت."
        )
        keyboard = [[InlineKeyboardButton("🔙 إلغاء", callback_data="menu_admins")]]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    elif data.startswith("admin_del_"):
        if not is_owner(user_id):
            await query.answer("هذا الخيار للمالك فقط.", show_alert=True)
            return
        page = int(data.split("_")[-1])
        admins = database.list_admins()
        if not admins:
            await query.answer("لا يوجد مدراء.", show_alert=True)
            return
        per_page = 5
        start_idx = page * per_page
        end_idx = min(start_idx + per_page, len(admins))
        keyboard = []
        for a in admins[start_idx:end_idx]:
            keyboard.append([InlineKeyboardButton(
                f"🗑️ {a.get('name') or a['user_id']}",
                callback_data=f"admin_confirm_del_{a['user_id']}")])
        nav = []
        if page > 0:
            nav.append(InlineKeyboardButton("⬅️", callback_data=f"admin_del_{page - 1}"))
        if end_idx < len(admins):
            nav.append(InlineKeyboardButton("➡️", callback_data=f"admin_del_{page + 1}"))
        if nav:
            keyboard.append(nav)
        keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data="menu_admins")])
        await query.edit_message_text("🗑️ **اختر المدير لإزالته:**",
                                      reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    elif data.startswith("admin_confirm_del_"):
        if not is_owner(user_id):
            await query.answer("هذا الخيار للمالك فقط.", show_alert=True)
            return
        aid = data[len("admin_confirm_del_"):]
        text = f"⚠️ **تأكيد الإزالة:**\n\nإزالة المدير `{aid}`؟"
        keyboard = [
            [InlineKeyboardButton("✅ نعم، أزل", callback_data=f"admin_exec_del_{aid}")],
            [InlineKeyboardButton("❌ إلغاء", callback_data="admin_del_0")],
        ]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    elif data.startswith("admin_exec_del_"):
        if not is_owner(user_id):
            await query.answer("هذا الخيار للمالك فقط.", show_alert=True)
            return
        aid = data[len("admin_exec_del_"):]
        database.remove_admin(aid)
        await query.answer("تمت الإزالة.", show_alert=True)
        keyboard = [[InlineKeyboardButton("🔙 المدراء", callback_data="menu_admins")]]
        await query.edit_message_text("✅ **تم إزالة المدير.**",
                                      reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    # ---------- Announcement ----------
    elif data == "menu_announce":
        SESSIONS[user_id] = {"mode": "announce", "step": "text", "data": {}}
        text = (
            "📢 **إعلان للتطبيق**\n\n"
            "أرسل الآن **نص الإعلان** الذي سيصل لكل المستخدمين كإشعار داخل التطبيق:"
        )
        keyboard = [[InlineKeyboardButton("🔙 إلغاء", callback_data="menu_main")]]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    # ---------- Forced update ----------
    elif data == "menu_update":
        SESSIONS[user_id] = {"mode": "update", "step": "version", "data": {}}
        text = (
            "⬆️ **تحديث إجباري للتطبيق (الخطوة 1 من 3):**\n\n"
            "أرسل **رقم الإصدار الجديد** (versionCode) — رقم صحيح أكبر من الحالي:"
        )
        keyboard = [[InlineKeyboardButton("🔙 إلغاء", callback_data="menu_main")]]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")


async def text_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        return

    text = (update.message.text or "").strip()
    session = SESSIONS.get(user_id)

    # 1. Quick direct-link detection (vless/vmess/trojan/ssh/ss) + WireGuard config
    _low = text.strip().lower()
    _is_wg = _low.startswith("[interface]") or _low.startswith("wg://") or _low.startswith("wireguard://")
    _is_link = _low.startswith(("vless://", "vmess://", "trojan://", "ssh://", "ss://"))
    if _is_wg or _is_link:
        if _is_wg:
            # إعداد WireGuard كامل (multi-line) → سيرفر واحد
            database.add_server(name="WireGuard Server", protocol="WIREGUARD", config=text.strip())
            SESSIONS.pop(user_id, None)
            keyboard = [
                [InlineKeyboardButton("📋 عرض السيرفرات", callback_data="menu_list_servers")],
                [InlineKeyboardButton("🔙 القائمة الرئيسية", callback_data="menu_main")]
            ]
            await update.message.reply_text(
                "✅ **تمت إضافة سيرفر WireGuard بنجاح!** 🚀\n\n"
                "• **الاسم:** WireGuard Server\n• **البروتوكول:** `WIREGUARD`",
                reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
            return
        lines = text.splitlines()
        added = 0
        name = ""
        proto = ""
        for line in lines:
            line = line.strip()
            if not line:
                continue
            ll = line.lower()
            if ll.startswith("vless://"):
                proto = "VLESS"
            elif ll.startswith("vmess://"):
                proto = "VMESS"
            elif ll.startswith("trojan://"):
                proto = "TROJAN"
            elif ll.startswith("ssh://"):
                proto = "SSH"
            elif ll.startswith("ss://"):
                proto = "SHADOWSOCKS"
            else:
                continue
            name = f"Server {database.get_servers_count() + 1}"
            if "#" in line:
                from urllib.parse import unquote
                remark = unquote(line.split("#")[-1]).strip()
                if remark:
                    name = remark

            database.add_server(name=name, protocol=proto, config=line)
            added += 1

        SESSIONS.pop(user_id, None)
        flag = get_flag_for_name(name)
        reply = (
            f"✅ **تمت إضافة {added} سيرفر بنجاح!** 🚀\n\n"
            f"• **الاسم:** {flag} {name}\n"
            f"• **البروتوكول:** `{proto}`\n"
        )
        keyboard = [
            [InlineKeyboardButton("📋 عرض السيرفرات", callback_data="menu_list_servers")],
            [InlineKeyboardButton("🔙 القائمة الرئيسية", callback_data="menu_main")]
        ]
        await update.message.reply_text(reply, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
        return

    # 2. Wizard sessions
    if session:
        mode = session.get("mode", "add")

        if mode == "announce":
            if not text:
                await update.message.reply_text("⚠️ أرسل نصاً غير فارغ.")
                return
            database.add_announcement(text)
            SESSIONS.pop(user_id, None)
            reply = f"✅ **تم إرسال الإعلان للتطبيق:**\n\n{text}"
            keyboard = [[InlineKeyboardButton("🔙 القائمة الرئيسية", callback_data="menu_main")]]
            await update.message.reply_text(reply, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
            return

        if mode == "update":
            step = session.get("step")
            if step == "version":
                if not text.isdigit():
                    await update.message.reply_text("⚠️ أرسل رقم إصدار صحيح (أرقام فقط).")
                    return
                session["data"]["version_code"] = int(text)
                session["step"] = "url"
                await update.message.reply_text(
                    f"✅ رقم الإصدار: `{text}`\n\n🔗 **الخطوة 2 من 3:** أرسل **رابط تحميل الـAPK** (يبدأ بـ http):",
                    parse_mode="Markdown"
                )
                return
            elif step == "url":
                if not text.startswith("http"):
                    await update.message.reply_text("⚠️ الرابط يجب أن يبدأ بـ http.")
                    return
                session["data"]["url"] = text
                session["step"] = "message"
                await update.message.reply_text(
                    "✅ تم حفظ الرابط.\n\n📝 **الخطوة 3 من 3:** أرسل **نص رسالة التحديث** (أو أرسل `-` لاستخدام النص الافتراضي):",
                    parse_mode="Markdown"
                )
                return
            elif step == "message":
                import json
                msg = "" if text == "-" else text
                database.set_setting("app_update", json.dumps({
                    "enabled": True,
                    "version_code": session["data"].get("version_code", 0),
                    "url": session["data"].get("url", ""),
                    "message": msg,
                }))
                SESSIONS.pop(user_id, None)
                reply = (
                    "✅ **تم تفعيل التحديث الإجباري!**\n\n"
                    f"• versionCode: `{session['data'].get('version_code')}`\n"
                    f"• الرابط: `{session['data'].get('url')}`"
                )
                keyboard = [[InlineKeyboardButton("🔙 القائمة الرئيسية", callback_data="menu_main")]]
                await update.message.reply_text(reply, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
                return

        if mode == "sub":
            step = session.get("step")
            if step == "label":
                session["data"]["label"] = text or "مستخدم"
                session["step"] = "days"
                await update.message.reply_text(
                    f"🏷️ الاسم: **{session['data']['label']}**\n\n"
                    "⏳ **الخطوة 2 من 3:** أرسل **عدد أيام الاشتراك** (مثال: 30)\n"
                    "أو أرسل `0` أو `-` لرابط **بلا انتهاء**:",
                    parse_mode="Markdown")
                return
            elif step == "days":
                days = 0
                if text.strip() not in ("-", "0"):
                    if not text.strip().isdigit():
                        await update.message.reply_text(
                            "⚠️ أرسل رقمًا صحيحًا (أيام) أو `0` لبلا انتهاء.", parse_mode="Markdown")
                        return
                    days = int(text.strip())
                session["data"]["days"] = days
                session["data"]["selected"] = []
                session["step"] = "pick"
                txt, kb = sub_picker_view(session, 0)
                await update.message.reply_text(txt, reply_markup=kb, parse_mode="Markdown")
                return
            elif step == "pick":
                # المستخدم أرسل نصًا بدل الاختيار — نعيد عرض القائمة
                txt, kb = sub_picker_view(session, 0)
                await update.message.reply_text("👇 اختر السيرفرات من الأزرار:", reply_markup=kb, parse_mode="Markdown")
                return

        if mode == "admin":
            step = session.get("step")
            if step == "add_id":
                if not is_owner(user_id):
                    SESSIONS.pop(user_id, None)
                    return
                target_id = ""
                fwd = getattr(update.message, "forward_from", None)
                fwd_chat = getattr(update.message, "forward_from_chat", None)
                if fwd is not None and getattr(fwd, "id", None):
                    target_id = str(fwd.id)
                elif fwd_chat is not None and getattr(fwd_chat, "id", None):
                    target_id = str(fwd_chat.id)
                elif text.strip().lstrip("-").isdigit():
                    target_id = text.strip()
                if not target_id:
                    await update.message.reply_text(
                        "⚠️ أرسل آيدي رقمي أو اعمل فوروارد لرسالة من المستخدم.",
                        parse_mode="Markdown")
                    return
                name = ""
                if fwd is not None:
                    parts = [getattr(fwd, "first_name", "") or "", getattr(fwd, "last_name", "") or ""]
                    name = " ".join(p for p in parts if p).strip()
                database.add_admin(target_id, name)
                SESSIONS.pop(user_id, None)
                reply = f"✅ **تم إضافة المدير:**\n`{target_id}`" + (f"\n({name})" if name else "")
                keyboard = [
                    [InlineKeyboardButton("👥 المدراء", callback_data="menu_admins")],
                    [InlineKeyboardButton("🔙 القائمة الرئيسية", callback_data="menu_main")],
                ]
                await update.message.reply_text(reply, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
                return

        if mode == "adv":
            step = session.get("step")
            sid = session["data"].get("id")
            if step == "proxy":
                host = ""
                port = 0
                if text != "-":
                    if ":" in text:
                        h, p = text.rsplit(":", 1)
                        if p.strip().isdigit():
                            host = h.strip()
                            port = int(p.strip())
                    if not host or port <= 0:
                        await update.message.reply_text("⚠️ صيغة غير صحيحة. أرسل `host:port` أو `-`.", parse_mode="Markdown")
                        return
                session["data"]["proxy_host"] = host
                session["data"]["proxy_port"] = port
                session["step"] = "payload"
                await update.message.reply_text("🔗 أرسل الآن **البايلود** (أو `-` لتخطيه):", parse_mode="Markdown")
                return
            elif step == "payload":
                payload = "" if text == "-" else text
                srv = database.get_server_by_id(sid) or {}
                database.update_server_advanced(
                    sid,
                    country=srv.get("country", "") or "",
                    proxy_host=session["data"].get("proxy_host", ""),
                    proxy_port=session["data"].get("proxy_port", 0),
                    proxy_user=srv.get("proxy_user", "") or "",
                    proxy_pass=srv.get("proxy_pass", "") or "",
                    payload=payload,
                )
                SESSIONS.pop(user_id, None)
                reply = (
                    "✅ **تم حفظ إعدادات السيرفر**\n\n"
                    f"• بروكسي: `{session['data'].get('proxy_host') or '—'}`\n"
                    f"• بايلود: `{'نعم' if payload else '—'}`"
                )
                keyboard = [[InlineKeyboardButton("🔙 القائمة الرئيسية", callback_data="menu_main")]]
                await update.message.reply_text(reply, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
                return

        if mode == "add":
            step = session.get("step")
            if step == "name":
                session["data"]["name"] = text
                session["step"] = "category"
                prompt = (
                    f"🏷️ اسم السيرفر: **{text}**\n\n"
                    "🧩 **أين يروح هذا السيرفر؟**\n"
                    "• 📱 **رئيسي** = يظهر لكل مستخدمي التطبيق (القائمة العامة)\n"
                    "• 🔗 **اشتراك** = فقط داخل روابط الاشتراك (معزول تمامًا)"
                )
                keyboard = [
                    [InlineKeyboardButton("📱 رئيسي (للتطبيق)", callback_data="set_cat_main")],
                    [InlineKeyboardButton("🔗 اشتراك (للروابط)", callback_data="set_cat_sub")],
                    [InlineKeyboardButton("🔙 إلغاء", callback_data="menu_main")]
                ]
                await update.message.reply_text(prompt, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
                return

            elif step == "config":
                proto = session["data"].get("protocol", "VLESS")
                name = session["data"].get("name", "Server")
                category = session["data"].get("category", "main")
                config = text

                sid = database.add_server(name=name, protocol=proto, config=config, category=category)
                SESSIONS.pop(user_id, None)

                flag = get_flag_for_name(name)
                type_label = "📱 رئيسي (للتطبيق)" if category == "main" else "🔗 اشتراك (معزول)"
                reply = (
                    "🎉 **تم حفظ السيرفر بنجاح في قاعدة البيانات!**\n\n"
                    f"• **ID:** `{sid}`\n"
                    f"• **الاسم:** {flag} {name}\n"
                    f"• **البروتوكول:** `{proto}`\n"
                    f"• **النوع:** {type_label}\n"
                    f"• **الرابط:** `{config[:35]}...`\n"
                )
                keyboard = [
                    [InlineKeyboardButton("➕ إضافة سيرفر آخر", callback_data="menu_add_server")],
                    [InlineKeyboardButton("📋 عرض السيرفرات", callback_data="menu_list_servers")],
                    [InlineKeyboardButton("🔙 القائمة الرئيسية", callback_data="menu_main")]
                ]
                await update.message.reply_text(reply, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
                return

    # If no session and text sent, remind owner of /start
    await update.message.reply_text(
        "💡 أرسل /start لفتح لوحة التحكم، أو أرسل رابط سيرفر (`vless://...`) لإضافته فورياً."
    )


async def sub_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Quick: /sub <days> <label...>  (days=0 لبلا انتهاء)"""
    user_id = update.effective_user.id
    if not is_admin(user_id):
        return
    args = context.args or []
    if len(args) < 2:
        await update.message.reply_text(
            "الاستخدام: `/sub الأيام الاسم`\nمثال: `/sub 30 أحمد`\n(0 = بلا انتهاء)",
            parse_mode="Markdown")
        return
    if not args[0].isdigit():
        await update.message.reply_text("⚠️ أول قيمة يجب أن تكون عدد الأيام (رقم).", parse_mode="Markdown")
        return
    days = int(args[0])
    label = " ".join(args[1:])
    info = database.create_subscription(label=label, days=days)
    url = f"{public_base()}/sub/{info['token']}"
    await update.message.reply_text(
        f"✅ تم إنشاء رابط اشتراك لـ **{label}**\n\n🔗 `{url}`",
        parse_mode="Markdown")


async def announce_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Quick: /announce <text>"""
    user_id = update.effective_user.id
    if not is_admin(user_id):
        return
    text = " ".join(context.args).strip()
    if not text:
        await update.message.reply_text("الاستخدام: `/announce نص الإعلان`", parse_mode="Markdown")
        return
    database.add_announcement(text)
    await update.message.reply_text("✅ تم إرسال الإعلان للتطبيق.")


async def update_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Quick: /update <versionCode> <apk_url> [message]"""
    import json
    user_id = update.effective_user.id
    if not is_admin(user_id):
        return
    args = context.args or []
    if len(args) < 2:
        await update.message.reply_text(
            "الاستخدام: `/update versionCode apk_url [message]`", parse_mode="Markdown"
        )
        return
    if not args[0].isdigit() or not args[1].startswith("http"):
        await update.message.reply_text("⚠️ تأكد من رقم الإصدار والرابط (يبدأ بـ http).")
        return
    message = " ".join(args[2:]) if len(args) > 2 else ""
    database.set_setting("app_update", json.dumps({
        "enabled": True,
        "version_code": int(args[0]),
        "url": args[1],
        "message": message,
    }))
    await update.message.reply_text("✅ تم تفعيل التحديث الإجباري.")


def start_api_server():
    """Runs uvicorn in a daemon thread so 'python bot.py' runs both."""
    import uvicorn
    logger.info(f"Starting FastAPI on http://{HOST}:{PORT}")
    uvicorn.run("api:app", host=HOST, port=PORT, log_level="warning")


def main():
    print("=" * 60)
    print("  🚀 AHMED VPN - Telegram Bot & FastAPI Server")
    print(f"  Owner ID: {OWNER_ID}")
    print(f"  API Endpoint: http://{HOST}:{PORT}/api/servers")
    print("=" * 60)

    # 1. Initialize SQLite Database
    database.init_db()

    # 2. Check token
    if not BOT_TOKEN or BOT_TOKEN == "ضع_توكن_البوت_هنا":
        print("\n" + "!" * 60)
        print(" [!] تحذير: لم تقم بوضع BOT_TOKEN داخل ملف .env بعد!")
        print(f" [!] افتح الملف: {env_path}")
        print(" [!] ضع التوكن الخاص بك ثم أعد التشغيل.")
        print(" [!] سيعمل سيرفر الـ API فقط الآن على المنفذ " + str(PORT))
        print("!" * 60 + "\n")
        # Run API directly in main thread
        import uvicorn
        uvicorn.run("api:app", host=HOST, port=PORT, log_level="info")
        return

    # 3. Start FastAPI server in background thread
    api_thread = threading.Thread(target=start_api_server, daemon=True)
    api_thread.start()

    # 4. Start Telegram Bot on main thread
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("announce", announce_command))
    app.add_handler(CommandHandler("update", update_command))
    app.add_handler(CommandHandler("sub", sub_command))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_message_handler))

    logger.info("Bot is starting polling...")
    app.run_polling()


if __name__ == "__main__":
    main()
