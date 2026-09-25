import os
import sys
import asyncio
import logging
from typing import Dict, Any, Optional
from html import escape as html_escape
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
from telegram.error import BadRequest, TelegramError

import config
import database

# ==================== LOGGING ====================
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("telegram.ext.Application").setLevel(logging.WARNING)
logging.getLogger("telegram.ext.Updater").setLevel(logging.WARNING)
logger = logging.getLogger("AhmedVpnBot")

# ==================== CONSTANTS ====================
PARSE_MODE = "HTML"
SESSIONS: Dict[int, Dict[str, Any]] = {}


# ==================== HELPERS ====================

def esc(text) -> str:
    """Escape آمن لأي نص قبل HTML"""
    if text is None:
        return ""
    return html_escape(str(text), quote=False)


def code(text) -> str:
    """يغلّف النص بـ <code> مع escape"""
    return f"<code>{esc(text)}</code>"


def b(text) -> str:
    """نص عريض"""
    return f"<b>{esc(text)}</b>"


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
    elif "UK" in n or "BRIT" in n or "بريطان" in n:
        return "🇬🇧"
    elif "SINGAPORE" in n:
        return "🇸🇬"
    elif "CANADA" in n:
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
            InlineKeyboardButton("👥 إحصائيات المستخدمين", callback_data="menu_stats")
        ],
        [
            InlineKeyboardButton("➕ إضافة أدمن", callback_data="menu_add_admin"),
            InlineKeyboardButton("➖ حذف أدمن", callback_data="menu_list_admins")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)


async def safe_edit(query, text: str, keyboard=None):
    """يعدّل الرسالة — يتجاهل 'Message is not modified' بهدوء"""
    try:
        await query.edit_message_text(
            text,
            reply_markup=keyboard,
            parse_mode=PARSE_MODE,
            disable_web_page_preview=True,
        )
    except BadRequest as e:
        err = str(e).lower()
        if "message is not modified" in err:
            return  # لا شيء — طبيعي
        if "can't parse entities" in err:
            logger.warning(f"Parse error — fallback to plain text")
            try:
                await query.edit_message_text(
                    text,
                    reply_markup=keyboard,
                    disable_web_page_preview=True,
                )
            except Exception:
                pass
            return
        raise
    except TelegramError as e:
        logger.warning(f"TelegramError in safe_edit: {e}")


async def safe_reply(message, text: str, keyboard=None):
    """يرسل رد — يتعامل مع أخطاء التنسيق"""
    try:
        await message.reply_text(
            text,
            reply_markup=keyboard,
            parse_mode=PARSE_MODE,
            disable_web_page_preview=True,
        )
    except BadRequest as e:
        err = str(e).lower()
        if "can't parse entities" in err:
            try:
                await message.reply_text(
                    text,
                    reply_markup=keyboard,
                    disable_web_page_preview=True,
                )
            except Exception:
                pass
            return
        raise


# ==================== ACCESS CONTROL ====================

async def check_admin_access(update: Update) -> bool:
    user = update.effective_user
    if not user or not database.is_admin(user.id):
        msg = (
            "⛔ <b>عذراً، هذا البوت خاص بإدارة تطبيق AHMED VPN فقط.</b>\n\n"
            f"آيدي المستخدم: {code(user.id if user else 'غير معروف')} غير مصرح له بالدخول."
        )
        try:
            if update.callback_query:
                await update.callback_query.answer(
                    "⛔ غير مصرح لك باستخدام هذا البوت.",
                    show_alert=True
                )
                await safe_edit(update.callback_query, msg)
            elif update.message:
                await update.message.reply_text(msg, parse_mode=PARSE_MODE)
        except Exception as e:
            logger.error(f"check_admin_access error: {e}")
        return False
    return True


# ==================== ERROR HANDLER ====================

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """معالج أخطاء شامل — يمنع البوت من الكف"""
    error = context.error
    if error is None:
        return

    err_str = str(error)
    err_low = err_str.lower()

    # 1) أخطاء سطحية — نتجاهلها بهدوء
    IGNORE = [
        "message is not modified",
        "query is too old",
        "message to delete not found",
        "message can't be deleted",
    ]
    for ig in IGNORE:
        if ig in err_low:
            return

    # 2) أخطاء تنسيق — نسجّلها فقط
    if "can't parse entities" in err_low:
        logger.warning(f"⚠️ Parse error (تنسيق): {err_str[:150]}")
        return

    # 3) أخطاء شبكة مؤقتة
    if any(x in err_low for x in [
        "timeout", "bad gateway", "network", "connection",
        "temporary failure", "getaddrinfo"
    ]):
        logger.warning(f"⚠️ شبكة مؤقتة: {err_str[:120]}")
        return

    # 4) Conflict — نسخة أخرى
    if "conflict" in err_low or "terminated by other" in err_low:
        logger.warning("⚠️ Conflict — نسخة أخرى تعمل")
        return

    # 5) خطأ فعلي
    logger.error(f"❌ خطأ: {type(error).__name__}: {err_str[:200]}")


# ==================== COMMANDS ====================

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if not await check_admin_access(update):
            return

        user = update.effective_user
        SESSIONS.pop(user.id, None)

        stats = database.get_system_stats()
        is_super = (user.id == config.OWNER_ID)

        rank = "المالك الأساسي 👑" if is_super else "مشرف معتمد 👮‍♂️"

        text = (
            f"🚀 <b>{esc(config.APP_NAME)} — لوحة تحكم الإدارة</b> 🛡️\n\n"
            f"أهلاً بك يا <b>{esc(user.first_name)}</b>\n"
            f"رتبتك: <b>{rank}</b>\n\n"
            f"👥 مستخدمي التطبيق: {code(stats['total_users'])}\n"
            f"🖥️ السيرفرات النشطة: {code(stats['total_servers'])}\n"
            f"👮‍♂️ المشرفين: {code(stats['total_admins'])}\n\n"
            "اختر إجراءً من الأزرار:"
        )
        await update.message.reply_text(
            text,
            reply_markup=get_main_menu_keyboard(is_super),
            parse_mode=PARSE_MODE,
        )
    except Exception as e:
        logger.error(f"start_command error: {e}", exc_info=True)


# ==================== CALLBACKS ====================

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    try:
        await query.answer()
    except Exception:
        pass

    try:
        user = update.effective_user
        if not await check_admin_access(update):
            return

        data = query.data
        is_super = (user.id == config.OWNER_ID)

        # ---------- Main / Refresh ----------
        if data in ("menu_refresh", "menu_main"):
            SESSIONS.pop(user.id, None)
            stats = database.get_system_stats()
            text = (
                f"🚀 <b>{esc(config.APP_NAME)} — لوحة التحكم</b> 🛡️\n\n"
                f"👥 المستخدمين: {code(stats['total_users'])}\n"
                f"🖥️ السيرفرات: {code(stats['total_servers'])}\n"
                f"👮‍♂️ المشرفين: {code(stats['total_admins'])}\n"
                f"🕒 آخر تحديث: {code(stats['last_updated'])}\n"
                f"🌐 API: {code(stats['api_status'])}\n\n"
                "اختر إجراءً:"
            )
            await safe_edit(query, text, get_main_menu_keyboard(is_super))

        # ---------- Stats ----------
        elif data == "menu_stats":
            stats = database.get_system_stats()
            text = (
                "📊 <b>إحصائيات تطبيق AHMED VPN:</b>\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n"
                f"👥 المستخدمين: {code(stats['total_users'])}\n"
                f"🖥️ السيرفرات: {code(stats['total_servers'])}\n"
                f"👮‍♂️ المشرفين: {code(stats['total_admins'])}\n"
                f"🕒 آخر تحديث: {code(stats['last_updated'])}\n"
                f"🟢 الحالة: {code(stats['api_status'])}\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n"
                "💡 يُحدّث تلقائياً عند فتح التطبيق."
            )
            keyboard = [
                [InlineKeyboardButton("🔄 تحديث", callback_data="menu_stats")],
                [InlineKeyboardButton("🔙 القائمة", callback_data="menu_main")]
            ]
            await safe_edit(query, text, InlineKeyboardMarkup(keyboard))

        # ---------- Add Server ----------
        elif data == "menu_add_server":
            SESSIONS[user.id] = {"action": "add_server", "step": "name", "data": {}}
            text = (
                "➕ <b>إضافة سيرفر جديد (1/3)</b>\n\n"
                "أرسل الآن <b>اسم السيرفر</b>:\n"
                "<i>(مثال: Germany 01)</i>\n\n"
                "💡 أو أرسل رابط مباشر (<code>vless://...</code>, "
                "<code>vmess://...</code>, <code>trojan://...</code>)"
            )
            keyboard = [[InlineKeyboardButton("🔙 إلغاء", callback_data="menu_main")]]
            await safe_edit(query, text, InlineKeyboardMarkup(keyboard))

        elif data.startswith("set_proto_"):
            proto = data.split("_")[-1]
            session = SESSIONS.get(user.id)
            if session and session.get("action") == "add_server":
                session["data"]["protocol"] = proto
                session["step"] = "config"
                text = (
                    f"✅ البروتوكول: {code(proto)}\n\n"
                    f"🔗 <b>الخطوة 3 من 3</b>\n"
                    f"أرسل الآن <b>رابط السيرفر</b> (يبدأ بـ {code(proto.lower() + '://')}):"
                )
                keyboard = [[InlineKeyboardButton("🔙 إلغاء", callback_data="menu_main")]]
                await safe_edit(query, text, InlineKeyboardMarkup(keyboard))
            else:
                await safe_edit(query, "⚠️ انتهت الجلسة. أعد من البداية.", get_main_menu_keyboard(is_super))

        # ---------- List Servers ----------
        elif data == "menu_list_servers":
            servers = database.get_all_servers()
            if not servers:
                text = "📋 <b>لا توجد سيرفرات مضافة حالياً.</b>"
                keyboard = [
                    [InlineKeyboardButton("➕ إضافة سيرفر", callback_data="menu_add_server")],
                    [InlineKeyboardButton("🔙 رجوع", callback_data="menu_main")]
                ]
                await safe_edit(query, text, InlineKeyboardMarkup(keyboard))
                return

            # نعرض 10 سيرفرات فقط لتجنب تجاوز حد الرسالة
            text = f"📋 <b>السيرفرات المتاحة ({len(servers)} سيرفر):</b>\n\n"
            for s in servers[:10]:
                flag = get_flag_for_name(s["name"])
                text += (
                    f"━━━━━━━━━━━━━━━━━━━\n"
                    f"🔹 ID: {code(s['id'])}\n"
                    f"🏷️ {flag} <b>{esc(s['name'])}</b>\n"
                    f"⚡ {code(s['protocol'])}\n"
                )
            if len(servers) > 10:
                text += f"\n<i>... و {len(servers) - 10} سيرفر إضافي</i>"
            text += "\n━━━━━━━━━━━━━━━━━━━"

            keyboard = [
                [InlineKeyboardButton("➕ إضافة سيرفر", callback_data="menu_add_server")],
                [InlineKeyboardButton("🗑️ مسح سيرفر", callback_data="menu_delete_server_0")],
                [InlineKeyboardButton("🔙 القائمة", callback_data="menu_main")]
            ]
            await safe_edit(query, text, InlineKeyboardMarkup(keyboard))

        # ---------- Delete Server ----------
        elif data.startswith("menu_delete_server_"):
            page = int(data.split("_")[-1])
            servers = database.get_all_servers()
            if not servers:
                text = "🗑️ <b>لا توجد سيرفرات لحذفها.</b>"
                keyboard = [[InlineKeyboardButton("🔙 القائمة", callback_data="menu_main")]]
                await safe_edit(query, text, InlineKeyboardMarkup(keyboard))
                return

            per_page = 5
            start_idx = page * per_page
            end_idx = min(start_idx + per_page, len(servers))
            current_page = servers[start_idx:end_idx]

            keyboard = []
            for s in current_page:
                flag = get_flag_for_name(s["name"])
                label = f"🗑️ {flag} {s['name'][:25]} ({s['protocol']})"
                keyboard.append([
                    InlineKeyboardButton(
                        label,
                        callback_data=f"confirm_del_srv_{s['id']}"
                    )
                ])

            nav = []
            if page > 0:
                nav.append(InlineKeyboardButton("⬅️", callback_data=f"menu_delete_server_{page - 1}"))
            if end_idx < len(servers):
                nav.append(InlineKeyboardButton("➡️", callback_data=f"menu_delete_server_{page + 1}"))
            if nav:
                keyboard.append(nav)

            keyboard.append([InlineKeyboardButton("🔙 القائمة", callback_data="menu_main")])

            text = f"🗑️ <b>اختر سيرفر للحذف</b>\n(صفحة {page + 1})"
            await safe_edit(query, text, InlineKeyboardMarkup(keyboard))

        elif data.startswith("confirm_del_srv_"):
            server_id = int(data.split("_")[-1])
            server = database.get_server_by_id(server_id)
            if not server:
                await query.answer("السيرفر غير موجود!", show_alert=True)
                await safe_edit(query, "السيرفر غير موجود.", get_main_menu_keyboard(is_super))
                return

            flag = get_flag_for_name(server["name"])
            text = (
                f"⚠️ <b>تأكيد الحذف</b>\n\n"
                f"هل تريد حذف السيرفر:\n"
                f"{flag} <b>{esc(server['name'])}</b> ({code(server['protocol'])})؟\n\n"
                f"<i>سيُحذف نهائياً من قاعدة البيانات.</i>"
            )
            keyboard = [
                [
                    InlineKeyboardButton("✅ حذف", callback_data=f"execute_del_srv_{server_id}"),
                    InlineKeyboardButton("❌ إلغاء", callback_data="menu_delete_server_0")
                ]
            ]
            await safe_edit(query, text, InlineKeyboardMarkup(keyboard))

        elif data.startswith("execute_del_srv_"):
            server_id = int(data.split("_")[-1])
            server = database.get_server_by_id(server_id)
            name = server["name"] if server else f"#{server_id}"
            deleted = database.delete_server(server_id)

            if deleted:
                try:
                    await query.answer("✅ تم الحذف!", show_alert=False)
                except Exception:
                    pass
                text = f"✅ <b>تم حذف السيرفر:</b> {esc(name)}"
            else:
                try:
                    await query.answer("⚠️ تعذر الحذف", show_alert=True)
                except Exception:
                    pass
                text = f"⚠️ تعذر حذف: {esc(name)}"

            keyboard = [
                [InlineKeyboardButton("🗑️ حذف آخر", callback_data="menu_delete_server_0")],
                [InlineKeyboardButton("🔙 القائمة", callback_data="menu_main")]
            ]
            await safe_edit(query, text, InlineKeyboardMarkup(keyboard))

        # ---------- Admins ----------
        elif data == "menu_add_admin":
            SESSIONS[user.id] = {"action": "add_admin", "step": "id"}
            text = (
                "➕ <b>إضافة أدمن جديد</b>\n\n"
                "أرسل <b>معرّف Telegram</b> للشخص:\n"
                "<i>(مثال: 123456789)</i>"
            )
            keyboard = [[InlineKeyboardButton("🔙 إلغاء", callback_data="menu_main")]]
            await safe_edit(query, text, InlineKeyboardMarkup(keyboard))

        elif data == "menu_list_admins":
            admins = database.get_all_admins()
            text = (
                "👮‍♂️ <b>المشرفين المعتمدين</b>\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n"
                f"👑 المالك: {code(config.OWNER_ID)}\n"
            )
            keyboard = []
            for adm in admins:
                aid = adm["telegram_id"]
                if aid == config.OWNER_ID:
                    continue
                uname = adm.get("username") or "بدون اسم"
                text += f"🔹 {code(aid)} — {esc(uname)}\n"
                keyboard.append([
                    InlineKeyboardButton(
                        f"➖ حذف ({aid})",
                        callback_data=f"confirm_del_adm_{aid}"
                    )
                ])

            text += "━━━━━━━━━━━━━━━━━━━━━━\nاختر أدمن للحذف:"
            keyboard.append([InlineKeyboardButton("➕ إضافة أدمن", callback_data="menu_add_admin")])
            keyboard.append([InlineKeyboardButton("🔙 القائمة", callback_data="menu_main")])
            await safe_edit(query, text, InlineKeyboardMarkup(keyboard))

        elif data.startswith("confirm_del_adm_"):
            target_id = int(data.split("_")[-1])
            if target_id == config.OWNER_ID:
                await query.answer("⛔ لا يمكن حذف المالك!", show_alert=True)
                return

            text = (
                f"⚠️ <b>تأكيد الحذف</b>\n\n"
                f"هل تريد سحب صلاحيات الأدمن من:\n{code(target_id)}؟"
            )
            keyboard = [
                [
                    InlineKeyboardButton("✅ حذف", callback_data=f"execute_del_adm_{target_id}"),
                    InlineKeyboardButton("❌ إلغاء", callback_data="menu_list_admins")
                ]
            ]
            await safe_edit(query, text, InlineKeyboardMarkup(keyboard))

        elif data.startswith("execute_del_adm_"):
            target_id = int(data.split("_")[-1])
            if target_id == config.OWNER_ID:
                await query.answer("⛔ غير مسموح!", show_alert=True)
                return

            success = database.remove_admin(target_id)
            if success:
                try:
                    await query.answer("✅ تم الحذف", show_alert=False)
                except Exception:
                    pass
                text = f"✅ تم حذف الأدمن {code(target_id)}"
            else:
                try:
                    await query.answer("⚠️ غير موجود", show_alert=True)
                except Exception:
                    pass
                text = f"⚠️ تعذر حذف {code(target_id)}"

            keyboard = [
                [InlineKeyboardButton("📋 المشرفين", callback_data="menu_list_admins")],
                [InlineKeyboardButton("🔙 القائمة", callback_data="menu_main")]
            ]
            await safe_edit(query, text, InlineKeyboardMarkup(keyboard))

    except Exception as e:
        logger.error(f"callback_handler error: {e}", exc_info=True)
        try:
            await query.answer("⚠️ حدث خطأ.", show_alert=True)
        except Exception:
            pass


# ==================== TEXT MESSAGES ====================

async def text_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if not await check_admin_access(update):
            return

        user = update.effective_user
        text = update.message.text.strip()
        session = SESSIONS.get(user.id)

        # 1) روابط مباشرة
        if text.startswith(("vless://", "vmess://", "trojan://")):
            lines = text.splitlines()
            added = 0
            last_name = "Server"
            proto = "VLESS"

            for line in lines:
                line = line.strip()
                if not line:
                    continue
                proto = "VLESS" if line.startswith("vless://") else (
                    "VMESS" if line.startswith("vmess://") else "TROJAN"
                )
                name = f"Server {database.get_servers_count() + 1}"
                if "#" in line:
                    try:
                        remark = unquote(line.split("#")[-1]).strip()
                        if remark:
                            name = remark[:60]
                    except Exception:
                        pass

                database.add_server(name=name, protocol=proto, config=line)
                added += 1
                last_name = name

            SESSIONS.pop(user.id, None)
            flag = get_flag_for_name(last_name)

            reply = (
                f"✅ <b>تمت إضافة {added} سيرفر</b> 🚀\n\n"
                f"• آخر سيرفر: {flag} <b>{esc(last_name)}</b>\n"
                f"• البروتوكول: {code(proto)}"
            )
            keyboard = [
                [InlineKeyboardButton("📋 عرض", callback_data="menu_list_servers")],
                [InlineKeyboardButton("🔙 القائمة", callback_data="menu_main")]
            ]
            await safe_reply(update.message, reply, InlineKeyboardMarkup(keyboard))
            return

        # 2) إضافة أدمن
        if session and session.get("action") == "add_admin":
            try:
                target_id = int(text.replace(" ", "").replace("@", ""))
                if target_id <= 0:
                    raise ValueError()
            except ValueError:
                await safe_reply(update.message, "❌ <b>آيدي غير صالح!</b>\nأرسل أرقاماً فقط.")
                return

            added = database.add_admin(telegram_id=target_id, username="", added_by=user.id)
            SESSIONS.pop(user.id, None)

            if added:
                reply = f"✅ <b>تمت إضافة الأدمن</b>\n• ID: {code(target_id)}"
            else:
                reply = "⚠️ فشل إضافة الأدمن."

            keyboard = [
                [InlineKeyboardButton("👮‍♂️ المشرفين", callback_data="menu_list_admins")],
                [InlineKeyboardButton("🔙 القائمة", callback_data="menu_main")]
            ]
            await safe_reply(update.message, reply, InlineKeyboardMarkup(keyboard))
            return

        # 3) إضافة سيرفر — wizard
        if session and session.get("action") == "add_server":
            step = session.get("step")

            if step == "name":
                session["data"]["name"] = text[:60]
                session["step"] = "protocol"
                prompt = (
                    f"🏷️ الاسم: <b>{esc(text[:60])}</b>\n\n"
                    f"⚡ <b>الخطوة 2 من 3</b>\nاختر البروتوكول:"
                )
                keyboard = [
                    [
                        InlineKeyboardButton("VLESS", callback_data="set_proto_VLESS"),
                        InlineKeyboardButton("VMESS", callback_data="set_proto_VMESS"),
                        InlineKeyboardButton("TROJAN", callback_data="set_proto_TROJAN")
                    ],
                    [InlineKeyboardButton("🔙 إلغاء", callback_data="menu_main")]
                ]
                await safe_reply(update.message, prompt, InlineKeyboardMarkup(keyboard))
                return

            elif step == "config":
                proto = session["data"].get("protocol", "VLESS")
                name = session["data"].get("name", "Server")
                config_link = text

                try:
                    sid = database.add_server(name=name, protocol=proto, config=config_link)
                    SESSIONS.pop(user.id, None)

                    flag = get_flag_for_name(name)
                    reply = (
                        f"✅ <b>تم حفظ السيرفر</b>\n\n"
                        f"• ID: {code(sid)}\n"
                        f"• الاسم: {flag} <b>{esc(name)}</b>\n"
                        f"• البروتوكول: {code(proto)}"
                    )
                    keyboard = [
                        [InlineKeyboardButton("➕ إضافة آخر", callback_data="menu_add_server")],
                        [InlineKeyboardButton("📋 عرض", callback_data="menu_list_servers")],
                        [InlineKeyboardButton("🔙 القائمة", callback_data="menu_main")]
                    ]
                    await safe_reply(update.message, reply, InlineKeyboardMarkup(keyboard))
                except Exception as e:
                    logger.error(f"add_server error: {e}")
                    SESSIONS.pop(user.id, None)
                    await safe_reply(update.message, "⚠️ فشل حفظ السيرفر.")
                return

        # fallback
        await safe_reply(
            update.message,
            "💡 أرسل /start لفتح اللوحة، أو أرسل رابط <code>vless://...</code> مباشرة."
        )

    except Exception as e:
        logger.error(f"text_message_handler error: {e}", exc_info=True)
        try:
            await update.message.reply_text("⚠️ حدث خطأ.")
        except Exception:
            pass


# ==================== MAIN ====================

async def post_init(app: Application) -> None:
    """يحذف webhook قبل polling"""
    try:
        await app.bot.delete_webhook(drop_pending_updates=True)
        logger.info("✅ Webhook deleted — polling mode activated")
    except Exception as e:
        logger.warning(f"⚠️ فشل حذف webhook: {e}")


def main():
    print("=" * 60)
    print(f"  🚀 {config.APP_NAME} - Telegram Admin Bot")
    print(f"  Owner ID: {config.OWNER_ID}")
    print("=" * 60)

    if not config.BOT_TOKEN or config.BOT_TOKEN == "ضع_توكن_البوت_هنا":
        print(" [!] BOT_TOKEN غير مضبوط!")
        return

    app = (
        Application.builder()
        .token(config.BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_message_handler))
    app.add_error_handler(error_handler)

    logger.info("🤖 Bot is starting polling...")
    app.run_polling(
        drop_pending_updates=True,
        allowed_updates=Update.ALL_TYPES,
        poll_interval=1.0,
        timeout=30,
    )


if __name__ == "__main__":
    main()
