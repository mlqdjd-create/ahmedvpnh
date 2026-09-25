import os
import sys
import logging
from typing import Dict, Any
from urllib.parse import unquote

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

import config
import database

# Configure logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger("AhmedVpnBot")

# Conversation state tracking
# Schema: {user_id: {"action": "add_server|add_admin|remove_admin", "step": "...", "data": {...}}}
SESSIONS: Dict[int, Dict[str, Any]] = {}

def get_flag_for_name(name: str) -> str:
    n = name.upper()
    if "GERMAN" in n or "DE" in n or "ألمان" in n:
        return "🇩🇪"
    elif "NETHER" in n or "NL" in n or "هولند" in n:
        return "🇳🇱"
    elif "FRANCE" in n or "FR" in n or "فرنس" in n:
        return "🇫🇷"
    elif "USA" in n or "US" in n or "AMERICA" in n or "أمريك" in n:
        return "🇺🇸"
    elif "TURK" in n or "TR" in n or "ترك" in n:
        return "🇹🇷"
    elif "UK" in n or "GB" in n or "BRIT" in n or "بريطان" in n:
        return "🇬🇧"
    elif "SINGAPORE" in n or "SG" in n:
        return "🇸🇬"
    elif "CANADA" in n or "CA" in n:
        return "🇨🇦"
    return "🌐"

def get_main_menu_keyboard(is_super_owner: bool = False):
    keyboard = [
        [
            InlineKeyboardButton("➕ إضافة سيرفر", callback_data="menu_add_server"),
            InlineKeyboardButton("🗑️ مسح سيرفر", callback_data="menu_delete_server_0")
        ],
        [
            InlineKeyboardButton("📋 عرض السيرفرات", callback_data="menu_list_servers"),
            InlineKeyboardButton("🔄 تحديث السيرفرات", callback_data="menu_refresh")
        ],
        [
            InlineKeyboardButton("👥 عدد مستخدمي التطبيق والإحصائيات", callback_data="menu_stats")
        ],
        [
            InlineKeyboardButton("➕ إضافة أدمن", callback_data="menu_add_admin"),
            InlineKeyboardButton("➖ حذف أدمن", callback_data="menu_list_admins")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

async def check_admin_access(update: Update) -> bool:
    user = update.effective_user
    if not user or not database.is_admin(user.id):
        msg = (
            "⛔ **عذراً، هذا البوت خاص بإدارة تطبيق AHMED VPN فقط.**\n\n"
            f"آيدي المستخدم الخاص بك: `{user.id if user else 'غير معروف'}` غير مصرح له بالدخول."
        )
        if update.callback_query:
            await update.callback_query.answer("⛔ غير مصرح لك باستخدام هذا البوت.", show_alert=True)
            await update.callback_query.edit_message_text(msg, parse_mode="Markdown")
        elif update.message:
            await update.message.reply_text(msg, parse_mode="Markdown")
        return False
    return True

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_admin_access(update):
        return

    user = update.effective_user
    SESSIONS.pop(user.id, None)

    stats = database.get_system_stats()
    is_super = (user.id == config.OWNER_ID)

    text = (
        f"🚀 **{config.APP_NAME} — لوحة تحكم الإدارة** 🛡️\n\n"
        f"أهلاً بك يا {user.first_name} في لوحة التحكم الكاملة.\n"
        f"رتبتك: **{'المالك الأساسي 👑' if is_super else 'مشرف معتمد 👮‍♂️'}**\n\n"
        f"👥 مستخدمي التطبيق: `{stats['total_users']}`\n"
        f"🖥️ عدد السيرفرات النشطة: `{stats['total_servers']}`\n"
        f"👮‍♂️ المشرفين: `{stats['total_admins']}`\n"
        f"🌐 رابط الـ API:\n`http://{config.HOST}:{config.PORT}/api/servers`\n\n"
        "اختر أحد الإجراءات من الأزرار أدناه:"
    )
    await update.message.reply_text(
        text,
        reply_markup=get_main_menu_keyboard(is_super),
        parse_mode="Markdown"
    )

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = update.effective_user

    if not await check_admin_access(update):
        return

    data = query.data
    is_super = (user.id == config.OWNER_ID)

    if data in ("menu_refresh", "menu_main"):
        SESSIONS.pop(user.id, None)
        stats = database.get_system_stats()
        text = (
            f"🚀 **{config.APP_NAME} — لوحة تحكم الإدارة** 🛡️\n\n"
            f"👥 مستخدمي التطبيق: `{stats['total_users']}`\n"
            f"🖥️ عدد السيرفرات النشطة: `{stats['total_servers']}`\n"
            f"👮‍♂️ المشرفين: `{stats['total_admins']}`\n"
            f"🕒 آخر تحديث: `{stats['last_updated']}`\n"
            f"🌐 حالة الـ API: `{stats['api_status']}`\n\n"
            "اختر أحد الإجراءات للبدء:"
        )
        await query.edit_message_text(text, reply_markup=get_main_menu_keyboard(is_super), parse_mode="Markdown")

    elif data == "menu_stats":
        stats = database.get_system_stats()
        text = (
            "📊 **إحصائيات تطبيق AHMED VPN الشاملة:**\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            f"👥 **عدد مستخدمي التطبيق الفعلي:** `{stats['total_users']}` مستخدم\n"
            f"🖥️ **عدد السيرفرات المتاحة:** `{stats['total_servers']}` سيرفر\n"
            f"👮‍♂️ **عدد مدراء النظام (Admins):** `{stats['total_admins']}` أدمن\n"
            f"🕒 **آخر وقت تحديث:** `{stats['last_updated']}`\n"
            f"🟢 **حالة الـ API:** `{stats['api_status']}`\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "💡 يتم تسجيل وتحديث مستخدمي التطبيق الفعليين تلقائياً عند فتح التطبيق وتحديث قائمة السيرفرات."
        )
        keyboard = [
            [InlineKeyboardButton("🔄 تحديث الإحصائيات", callback_data="menu_stats")],
            [InlineKeyboardButton("🔙 القائمة الرئيسية", callback_data="menu_main")]
        ]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    elif data == "menu_add_server":
        SESSIONS[user.id] = {"action": "add_server", "step": "name", "data": {}}
        text = (
            "➕ **إضافة سيرفر جديد (الخطوة 1 من 3):**\n\n"
            "أرسل الآن **اسم السيرفر**:\n"
            "*(مثال: Germany 01)*\n\n"
            "💡 أو يمكنك إرسال رابط السيرفر مباشرة (`vless://...`, `vmess://...`, `trojan://...`) ليتم حفظه فورياً."
        )
        keyboard = [[InlineKeyboardButton("🔙 إلغاء", callback_data="menu_main")]]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    elif data.startswith("set_proto_"):
        proto = data.split("_")[-1]
        session = SESSIONS.get(user.id)
        if session and session.get("action") == "add_server":
            session["data"]["protocol"] = proto
            session["step"] = "config"
            text = (
                f"✅ تم اختيار البروتوكول: `{proto}`\n\n"
                "🔗 **الخطوة 3 من 3:**\n"
                f"أرسل الآن **رابط السيرفر** (يبدأ بـ `{proto.lower()}://`):"
            )
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
            text += (
                f"━━━━━━━━━━━━━━━━━━━\n"
                f"🔹 **ID:** `{s['id']}`\n"
                f"🏷️ **الاسم:** {flag} {s['name']}\n"
                f"⚡ **البروتوكول:** `{s['protocol']}`\n"
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
            keyboard.append([
                InlineKeyboardButton(
                    f"🗑️ {flag} {s['name']} ({s['protocol']})",
                    callback_data=f"confirm_del_srv_{s['id']}"
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

        text = "🗑️ **اختر السيرفر الذي ترغب بحذفه نهائياً من قاعدة البيانات:**"
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    elif data.startswith("confirm_del_srv_"):
        server_id = int(data.split("_")[-1])
        server = database.get_server_by_id(server_id)
        if not server:
            await query.answer("السيرفر غير موجود أو تم حذفه مسبقاً!", show_alert=True)
            await query.edit_message_text("السيرفر غير موجود.", reply_markup=get_main_menu_keyboard(is_super))
            return

        flag = get_flag_for_name(server["name"])
        text = (
            f"⚠️ **تأكيد حذف السيرفر نهائياً:**\n\n"
            f"هل أنت متأكد من حذف السيرفر:\n"
            f"**{flag} {server['name']}** (`{server['protocol']}`)\n\n"
            "⚠️ سيتم حذفه فعلياً من قاعدة البيانات ولن يظهر بعد الآن للمستخدمين في التطبيق."
        )
        keyboard = [
            [
                InlineKeyboardButton("✅ نعم، حذف نهائي", callback_data=f"execute_del_srv_{server_id}"),
                InlineKeyboardButton("❌ إلغاء", callback_data="menu_delete_server_0")
            ]
        ]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    elif data.startswith("execute_del_srv_"):
        server_id = int(data.split("_")[-1])
        server = database.get_server_by_id(server_id)
        name = server["name"] if server else f"#{server_id}"
        deleted = database.delete_server(server_id)

        if deleted:
            await query.answer("تم حذف السيرفر بنجاح!", show_alert=True)
            text = f"✅ **تم حذف السيرفر بنجاح من قاعدة البيانات:**\n`{name}`"
        else:
            await query.answer("تعذر الحذف أو لم يتم العثور على السيرفر!", show_alert=True)
            text = f"⚠️ تعذر حذف السيرفر `{name}`"

        keyboard = [
            [InlineKeyboardButton("🗑️ مسح سيرفر آخر", callback_data="menu_delete_server_0")],
            [InlineKeyboardButton("🔙 القائمة الرئيسية", callback_data="menu_main")]
        ]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    # ==================== ADMINS WORKFLOW ====================
    elif data == "menu_add_admin":
        SESSIONS[user.id] = {"action": "add_admin", "step": "id"}
        text = (
            "➕ **إضافة أدمن جديد:**\n\n"
            "أرسل الآن **معرّف التليجرام (Telegram ID)** الخاص بالشخص المراد ترقيته كأدمن:\n"
            "*(مثال: `123456789`)*\n\n"
            "💡 يستطيع الأدمن الجديد الوصول إلى لوحة تحكم البوت وإدارة السيرفرات والاطلاع على الإحصائيات."
        )
        keyboard = [[InlineKeyboardButton("🔙 إلغاء", callback_data="menu_main")]]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    elif data == "menu_list_admins":
        admins = database.get_all_admins()
        text = (
            "👮‍♂️ **قائمة المشرفين المعتمدين:**\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            f"👑 **المالك الأساسي:** `{config.OWNER_ID}`\n"
        )
        keyboard = []
        for adm in admins:
            aid = adm["telegram_id"]
            if aid == config.OWNER_ID:
                continue
            text += f"🔹 أدمن: `{aid}` | {adm.get('username') or 'بدون اسم'} | أضيف في: `{adm['added_at']}`\n"
            keyboard.append([
                InlineKeyboardButton(f"➖ حذف أدمن ({aid})", callback_data=f"confirm_del_adm_{aid}")
            ])
            
        text += "━━━━━━━━━━━━━━━━━━━━━━\nاختر أدمن لحذفه أو اضغط رجوع:"
        keyboard.append([InlineKeyboardButton("➕ إضافة أدمن جديد", callback_data="menu_add_admin")])
        keyboard.append([InlineKeyboardButton("🔙 القائمة الرئيسية", callback_data="menu_main")])
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    elif data.startswith("confirm_del_adm_"):
        target_id = int(data.split("_")[-1])
        if target_id == config.OWNER_ID:
            await query.answer("⛔ لا يمكن حذف المالك الأساسي للنظام أبداً!", show_alert=True)
            return

        text = (
            f"⚠️ **تأكيد حذف المشرف:**\n\n"
            f"هل أنت متأكد من سحب صلاحيات الأدمن من الحساب ذي الـ ID:\n"
            f"`{target_id}`؟\n\n"
            "لن يتمكن هذا المستخدم من الدخول إلى لوحة التحكم بعد الحذف."
        )
        keyboard = [
            [
                InlineKeyboardButton("✅ نعم، حذف الأدمن", callback_data=f"execute_del_adm_{target_id}"),
                InlineKeyboardButton("❌ إلغاء", callback_data="menu_list_admins")
            ]
        ]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    elif data.startswith("execute_del_adm_"):
        target_id = int(data.split("_")[-1])
        if target_id == config.OWNER_ID:
            await query.answer("⛔ غير مسموح بحذف المالك الأساسي!", show_alert=True)
            return

        success = database.remove_admin(target_id)
        if success:
            await query.answer("تم حذف الأدمن بنجاح!", show_alert=True)
            text = f"✅ **تم حذف الأدمن `{target_id}` وسحب صلاحياته بنجاح.**"
        else:
            await query.answer("الأدمن غير موجود أو حدث خطأ.", show_alert=True)
            text = f"⚠️ تعذر حذف الأدمن `{target_id}`."

        keyboard = [
            [InlineKeyboardButton("📋 عرض قائمة المشرفين", callback_data="menu_list_admins")],
            [InlineKeyboardButton("🔙 القائمة الرئيسية", callback_data="menu_main")]
        ]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def text_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_admin_access(update):
        return

    user = update.effective_user
    text = update.message.text.strip()
    session = SESSIONS.get(user.id)
    is_super = (user.id == config.OWNER_ID)

    # 1. Quick Direct Link detection (vless://, vmess://, trojan://)
    if text.startswith("vless://") or text.startswith("vmess://") or text.startswith("trojan://"):
        lines = text.splitlines()
        added = 0
        last_name = "Server"
        proto = "VLESS"
        for line in lines:
            line = line.strip()
            if not line:
                continue
            proto = "VLESS" if line.startswith("vless://") else ("VMESS" if line.startswith("vmess://") else "TROJAN")
            name = f"Server {database.get_servers_count() + 1}"
            if "#" in line:
                remark = unquote(line.split("#")[-1]).strip()
                if remark:
                    name = remark
            
            database.add_server(name=name, protocol=proto, config=line)
            added += 1
            last_name = name

        SESSIONS.pop(user.id, None)
        flag = get_flag_for_name(last_name)
        reply = (
            f"✅ **تمت إضافة {added} سيرفر بنجاح إلى قاعدة البيانات!** 🚀\n\n"
            f"• **آخر سيرفر:** {flag} {last_name}\n"
            f"• **البروتوكول:** `{proto}`\n"
        )
        keyboard = [
            [InlineKeyboardButton("📋 عرض السيرفرات", callback_data="menu_list_servers")],
            [InlineKeyboardButton("🔙 القائمة الرئيسية", callback_data="menu_main")]
        ]
        await update.message.reply_text(reply, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
        return

    # 2. Add Admin Session
    if session and session.get("action") == "add_admin":
        try:
            target_id = int(text.replace(" ", "").replace("@", ""))
            if target_id <= 0:
                raise ValueError()
        except ValueError:
            await update.message.reply_text(
                "❌ **آيدي التليجرام غير صالح!**\nيرجى إرسال رقم الـ ID بشكل صحيح (أرقام فقط).\n\n"
                "أرسل الرقم مجدداً أو اضغط /start للإلغاء:"
            )
            return

        added = database.add_admin(telegram_id=target_id, username="", added_by=user.id)
        SESSIONS.pop(user.id, None)
        if added:
            reply = (
                "🎉 **تمت إضافة الأدمن بنجاح!** 👮‍♂️\n\n"
                f"• **Telegram ID:** `{target_id}`\n"
                "• الصلاحية: يستطيع الآن إرسال /start واستخدام لوحة التحكم بالكامل."
            )
        else:
            reply = "⚠️ حدث خطأ أثناء إضافة الأدمن في قاعدة البيانات."

        keyboard = [
            [InlineKeyboardButton("👮‍♂️ قائمة المشرفين", callback_data="menu_list_admins")],
            [InlineKeyboardButton("🔙 القائمة الرئيسية", callback_data="menu_main")]
        ]
        await update.message.reply_text(reply, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
        return

    # 3. Add Server Wizard Session
    if session and session.get("action") == "add_server":
        step = session.get("step")
        if step == "name":
            session["data"]["name"] = text
            session["step"] = "protocol"
            prompt = (
                f"🏷️ اسم السيرفر: **{text}**\n\n"
                "⚡ **الخطوة 2 من 3:**\n"
                "اختر **البروتوكول** من الأزرار أدناه:"
            )
            keyboard = [
                [
                    InlineKeyboardButton("VLESS", callback_data="set_proto_VLESS"),
                    InlineKeyboardButton("VMESS", callback_data="set_proto_VMESS"),
                    InlineKeyboardButton("TROJAN", callback_data="set_proto_TROJAN")
                ],
                [InlineKeyboardButton("🔙 إلغاء", callback_data="menu_main")]
            ]
            await update.message.reply_text(prompt, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
            return

        elif step == "config":
            proto = session["data"].get("protocol", "VLESS")
            name = session["data"].get("name", "Server")
            config_link = text

            sid = database.add_server(name=name, protocol=proto, config=config_link)
            SESSIONS.pop(user.id, None)

            flag = get_flag_for_name(name)
            reply = (
                "🎉 **تم حفظ السيرفر بنجاح في قاعدة البيانات!**\n\n"
                f"• **ID:** `{sid}`\n"
                f"• **الاسم:** {flag} {name}\n"
                f"• **البروتوكول:** `{proto}`\n"
                f"• **الرابط:** `{config_link[:35]}...`\n"
            )
            keyboard = [
                [InlineKeyboardButton("➕ إضافة سيرفر آخر", callback_data="menu_add_server")],
                [InlineKeyboardButton("📋 عرض السيرفرات", callback_data="menu_list_servers")],
                [InlineKeyboardButton("🔙 القائمة الرئيسية", callback_data="menu_main")]
            ]
            await update.message.reply_text(reply, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
            return

    # Default fallback
    await update.message.reply_text(
        "💡 أرسل /start لفتح لوحة التحكم، أو أرسل رابط سيرفر (`vless://...`) لإضافته فورياً."
    )

def main():
    print("=" * 60)
    print(f"  🚀 {config.APP_NAME} - Telegram Administration Bot")
    print(f"  Owner ID: {config.OWNER_ID}")
    print(f"  API Endpoint: http://{config.HOST}:{config.PORT}/api/servers")
    print("=" * 60)

    # Initialize Database
    database.init_db()

    if not config.BOT_TOKEN or config.BOT_TOKEN == "ضع_توكن_البوت_هنا":
        print("\n" + "!" * 60)
        print(" [!] تحذير: لم تقم بوضع BOT_TOKEN داخل ملف .env بعد!")
        print(f" [!] افتح الملف: {config.ENV_PATH}")
        print(" [!] وضع التوكن الخاص بك من @BotFather ثم أعد التشغيل.")
        print("!" * 60 + "\n")
        return

    app = Application.builder().token(config.BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_message_handler))

    logger.info("Bot is starting polling...")
    app.run_polling()

if __name__ == "__main__":
    main()
