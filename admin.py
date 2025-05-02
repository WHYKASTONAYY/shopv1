import sqlite3
import os
import logging
import json
import tempfile
import shutil
import time
import secrets # For generating random codes
import asyncio
from datetime import datetime, timedelta, timezone # <<< Added timezone import
from collections import defaultdict
import math # Add math for pagination calculation
from decimal import Decimal # Ensure Decimal is imported

# Need emoji library for validation (or implement a simpler check)
# Let's try a simpler check first to avoid adding a dependency
# import emoji # Optional, for more robust emoji validation

# --- Telegram Imports ---
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    InputMediaPhoto, InputMediaVideo, InputMediaAnimation
)
from telegram.constants import ParseMode # Keep for reference
from telegram.ext import ContextTypes, JobQueue # Import JobQueue
from telegram import helpers
import telegram.error as telegram_error

# --- Local Imports ---
from utils import (
    CITIES, DISTRICTS, PRODUCT_TYPES, ADMIN_ID, LANGUAGES, THEMES,
    BOT_MEDIA, SIZES, fetch_reviews, format_currency, send_message_with_retry,
    get_date_range, TOKEN, load_all_data, format_discount_value,
    SECONDARY_ADMIN_IDS,
    get_db_connection, MEDIA_DIR, BOT_MEDIA_JSON_PATH, # Import helpers/paths
    DEFAULT_PRODUCT_EMOJI, # Import default emoji
    fetch_user_ids_for_broadcast, # <-- Import broadcast user fetch function
    # <<< Welcome Message Helpers >>>
    get_welcome_message_templates, get_welcome_message_template_count, # <-- Added count helper
    add_welcome_message_template,
    update_welcome_message_template,
    delete_welcome_message_template,
    set_active_welcome_message,
    DEFAULT_WELCOME_MESSAGE, # Fallback if needed
    # User status helpers
    get_user_status, get_progress_bar,
    _get_lang_data,  # <<<===== IMPORT THE HELPER =====>>>
    # <<< Admin Logging >>>
    log_admin_action, ACTION_RESELLER_DISCOUNT_DELETE # Import logging helper and action constant
)
# --- Import viewer admin handlers ---
# These now include the user management handlers
try:
    from viewer_admin import (
        handle_viewer_admin_menu,
        handle_manage_users_start, # <-- Needed for the new button
        # Import other viewer handlers if needed elsewhere in admin.py
        handle_viewer_added_products, # <<< NEED THIS
        handle_viewer_view_product_media # <<< NEED THIS
    )
except ImportError:
    logger_dummy_viewer = logging.getLogger(__name__ + "_dummy_viewer")
    logger_dummy_viewer.error("Could not import handlers from viewer_admin.py.")
    # Define dummy handlers for viewer admin menu and user management if import fails
    async def handle_viewer_admin_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, params=None):
        query = update.callback_query
        msg = "Secondary admin menu handler not found."
        if query: await query.edit_message_text(msg, parse_mode=None)
        else: await send_message_with_retry(context.bot, update.effective_chat.id, msg, parse_mode=None)
    async def handle_manage_users_start(update: Update, context: ContextTypes.DEFAULT_TYPE, params=None):
        query = update.callback_query
        msg = "Manage Users handler not found."
        if query: await query.edit_message_text(msg, parse_mode=None)
        else: await send_message_with_retry(context.bot, update.effective_chat.id, msg, parse_mode=None)
    # Add dummies for other viewer handlers if they were used directly in admin.py
    async def handle_viewer_added_products(update: Update, context: ContextTypes.DEFAULT_TYPE, params=None):
        query = update.callback_query
        msg = "Added Products Log handler not found."
        if query: await query.edit_message_text(msg, parse_mode=None)
        else: await send_message_with_retry(context.bot, update.effective_chat.id, msg, parse_mode=None)
    async def handle_viewer_view_product_media(update: Update, context: ContextTypes.DEFAULT_TYPE, params=None):
        query = update.callback_query
        msg = "View Product Media handler not found."
        if query: await query.edit_message_text(msg, parse_mode=None)
        else: await send_message_with_retry(context.bot, update.effective_chat.id, msg, parse_mode=None)
# ------------------------------------

# --- Import Reseller Management Handlers ---
try:
    from reseller_management import (
        handle_manage_resellers_menu,
        handle_reseller_manage_id_message,
        handle_reseller_toggle_status,
        handle_manage_reseller_discounts_select_reseller,
        handle_manage_specific_reseller_discounts,
        handle_reseller_add_discount_select_type,
        handle_reseller_add_discount_enter_percent,
        handle_reseller_edit_discount,
        handle_reseller_percent_message,
        handle_reseller_delete_discount_confirm,
    )
except ImportError:
    logger_dummy_reseller = logging.getLogger(__name__ + "_dummy_reseller")
    logger_dummy_reseller.error("Could not import handlers from reseller_management.py.")
    async def handle_manage_resellers_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, params=None):
        query = update.callback_query; msg = "Reseller Status Mgmt handler not found."
        if query: await query.edit_message_text(msg)
        else: await send_message_with_retry(context.bot, update.effective_chat.id, msg)
    async def handle_manage_reseller_discounts_select_reseller(update: Update, context: ContextTypes.DEFAULT_TYPE, params=None):
        query = update.callback_query; msg = "Reseller Discount Mgmt handler not found."
        if query: await query.edit_message_text(msg)
        else: await send_message_with_retry(context.bot, update.effective_chat.id, msg)
    # Add dummies for other reseller handlers if needed (less critical for basic menu)
    async def handle_reseller_manage_id_message(update: Update, context: ContextTypes.DEFAULT_TYPE): pass
    async def handle_reseller_toggle_status(update: Update, context: ContextTypes.DEFAULT_TYPE, params=None): pass
    async def handle_manage_specific_reseller_discounts(update: Update, context: ContextTypes.DEFAULT_TYPE, params=None): pass
    async def handle_reseller_add_discount_select_type(update: Update, context: ContextTypes.DEFAULT_TYPE, params=None): pass
    async def handle_reseller_add_discount_enter_percent(update: Update, context: ContextTypes.DEFAULT_TYPE, params=None): pass
    async def handle_reseller_edit_discount(update: Update, context: ContextTypes.DEFAULT_TYPE, params=None): pass
    async def handle_reseller_percent_message(update: Update, context: ContextTypes.DEFAULT_TYPE): pass
    async def handle_reseller_delete_discount_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE, params=None): pass
# ------------------------------------------


# Import stock handler
try: from stock import handle_view_stock
except ImportError:
    logger_dummy_stock = logging.getLogger(__name__ + "_dummy_stock")
    logger_dummy_stock.error("Could not import handle_view_stock from stock.py.")
    async def handle_view_stock(update: Update, context: ContextTypes.DEFAULT_TYPE, params=None):
        query = update.callback_query # Corrected variable name
        msg = "Stock viewing handler not found."
        if query: await query.edit_message_text(msg, parse_mode=None)
        else: await send_message_with_retry(context.bot, update.effective_chat.id, msg, parse_mode=None)

# Logging setup
logger = logging.getLogger(__name__)

# --- Constants for Media Group Handling ---
MEDIA_GROUP_COLLECTION_DELAY = 2.0 # Seconds to wait for more media in a group
TEMPLATES_PER_PAGE = 5 # Pagination for welcome templates

# --- Helper Function to Remove Existing Job ---
def remove_job_if_exists(name: str, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Removes a job by name if it exists."""
    if not hasattr(context, 'job_queue') or not context.job_queue:
        logger.warning("Job queue not available in context for remove_job_if_exists.")
        return False
    current_jobs = context.job_queue.get_jobs_by_name(name)
    if not current_jobs:
        return False
    for job in current_jobs:
        job.schedule_removal()
        logger.debug(f"Removed existing job: {name}")
    return True

# --- Helper to Prepare and Confirm Drop (Handles Download) ---
async def _prepare_and_confirm_drop(
    context: ContextTypes.DEFAULT_TYPE,
    user_data: dict,
    chat_id: int,
    user_id: int,
    text: str,
    collected_media_info: list
    ):
    """Downloads media (if any) and presents the confirmation message."""
    required_context = ["admin_city", "admin_district", "admin_product_type", "pending_drop_size", "pending_drop_price"]
    if not all(k in user_data for k in required_context):
        logger.error(f"_prepare_and_confirm_drop: Context lost for user {user_id}.")
        await send_message_with_retry(context.bot, chat_id, "❌ Error: Context lost. Please start adding product again.", parse_mode=None)
        keys_to_clear = ["state", "pending_drop", "pending_drop_size", "pending_drop_price", "collecting_media_group_id", "collected_media"]
        for key in keys_to_clear: user_data.pop(key, None)
        return

    temp_dir = None
    media_list_for_db = []
    download_errors = 0

    if collected_media_info:
        try:
            temp_dir = await asyncio.to_thread(tempfile.mkdtemp)
            logger.info(f"Created temp dir for media download: {temp_dir} (User: {user_id})")
            for i, media_info in enumerate(collected_media_info):
                media_type = media_info['type']
                file_id = media_info['file_id']
                file_extension = ".jpg" if media_type == "photo" else ".mp4" if media_type in ["video", "gif"] else ".dat"
                temp_file_path = os.path.join(temp_dir, f"{file_id}{file_extension}")
                try:
                    logger.info(f"Downloading media {i+1}/{len(collected_media_info)} ({file_id}) to {temp_file_path}")
                    file_obj = await context.bot.get_file(file_id)
                    await file_obj.download_to_drive(custom_path=temp_file_path)
                    if not await asyncio.to_thread(os.path.exists, temp_file_path) or await asyncio.to_thread(os.path.getsize, temp_file_path) == 0:
                        raise IOError(f"Downloaded file {temp_file_path} is missing or empty.")
                    media_list_for_db.append({"type": media_type, "path": temp_file_path, "file_id": file_id})
                    logger.info(f"Media download {i+1} successful.")
                except (telegram_error.TelegramError, IOError, OSError) as e:
                    logger.error(f"Error downloading/verifying media {i+1} ({file_id}): {e}")
                    download_errors += 1
                except Exception as e:
                    logger.error(f"Unexpected error downloading media {i+1} ({file_id}): {e}", exc_info=True)
                    download_errors += 1
            if download_errors > 0:
                await send_message_with_retry(context.bot, chat_id, f"⚠️ Warning: {download_errors} media file(s) failed to download. Adding drop with successfully downloaded media only.", parse_mode=None)
        except Exception as e:
             logger.error(f"Error setting up/during media download loop user {user_id}: {e}", exc_info=True)
             await send_message_with_retry(context.bot, chat_id, "⚠️ Warning: Error during media processing. Drop will be added without media.", parse_mode=None)
             media_list_for_db = []
             if temp_dir and await asyncio.to_thread(os.path.exists, temp_dir): await asyncio.to_thread(shutil.rmtree, temp_dir, ignore_errors=True); temp_dir = None

    user_data["pending_drop"] = {
        "city": user_data["admin_city"], "district": user_data["admin_district"],
        "product_type": user_data["admin_product_type"], "size": user_data["pending_drop_size"],
        "price": user_data["pending_drop_price"], "original_text": text,
        "media": media_list_for_db,
        "temp_dir": temp_dir
    }
    user_data.pop("state", None)

    city_name = user_data['admin_city']
    dist_name = user_data['admin_district']
    type_name = user_data['admin_product_type']
    type_emoji = PRODUCT_TYPES.get(type_name, DEFAULT_PRODUCT_EMOJI)
    size_name = user_data['pending_drop_size']
    price_str = format_currency(user_data['pending_drop_price'])
    text_preview = text[:200] + ("..." if len(text) > 200 else "")
    text_display = text_preview if text_preview else "No details text provided"
    media_count = len(user_data["pending_drop"]["media"])
    total_submitted_media = len(collected_media_info)
    media_status = f"{media_count}/{total_submitted_media} Downloaded" if total_submitted_media > 0 else "No"
    if download_errors > 0: media_status += " (Errors)"

    msg = (f"📦 Confirm New Drop\n\n🏙️ City: {city_name}\n🏘️ District: {dist_name}\n{type_emoji} Type: {type_name}\n"
           f"📏 Size: {size_name}\n💰 Price: {price_str} EUR\n📝 Details: {text_display}\n"
           f"📸 Media Attached: {media_status}\n\nAdd this drop?")
    keyboard = [[InlineKeyboardButton("✅ Yes, Add Drop", callback_data="confirm_add_drop"),
                InlineKeyboardButton("❌ No, Cancel", callback_data="cancel_add")]]
    await send_message_with_retry(context.bot, chat_id, msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=None)

# --- Job Function to Process Collected Media Group ---
async def _process_collected_media(context: ContextTypes.DEFAULT_TYPE):
    """Job callback to process a collected media group."""
    job_data = context.job.data
    user_id = job_data.get("user_id")
    chat_id = job_data.get("chat_id")
    media_group_id = job_data.get("media_group_id")

    if not user_id or not chat_id or not media_group_id:
        logger.error(f"Job _process_collected_media missing user_id, chat_id, or media_group_id in data: {job_data}")
        return

    logger.info(f"Job executing: Process media group {media_group_id} for user {user_id}")
    user_data = context.application.user_data.get(user_id, {})
    if not user_data:
         logger.error(f"Job {media_group_id}: Could not find user_data for user {user_id}.")
         return

    collected_info = user_data.get('collected_media', {}).get(media_group_id)
    if not collected_info or 'media' not in collected_info:
        logger.warning(f"Job {media_group_id}: No collected media info found in user_data for user {user_id}. Might be already processed or cancelled.")
        user_data.pop('collecting_media_group_id', None)
        if 'collected_media' in user_data:
            user_data['collected_media'].pop(media_group_id, None)
            if not user_data['collected_media']:
                user_data.pop('collected_media', None)
        return

    collected_media = collected_info.get('media', [])
    caption = collected_info.get('caption', '')

    user_data.pop('collecting_media_group_id', None)
    if 'collected_media' in user_data and media_group_id in user_data['collected_media']:
        del user_data['collected_media'][media_group_id]
        if not user_data['collected_media']:
            user_data.pop('collected_media', None)

    await _prepare_and_confirm_drop(context, user_data, chat_id, user_id, caption, collected_media)


# --- Modified Handler for Drop Details Message ---
async def handle_adm_drop_details_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the message containing drop text and optional media (single or group)."""
    if not update.message or not update.effective_user:
        logger.warning("handle_adm_drop_details_message received invalid update.")
        return

    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    user_specific_data = context.user_data

    if user_id != ADMIN_ID: return

    if user_specific_data.get("state") != "awaiting_drop_details":
        logger.debug(f"Ignoring drop details message from user {user_id}, state is not 'awaiting_drop_details' (state: {user_specific_data.get('state')})")
        return

    required_context = ["admin_city", "admin_district", "admin_product_type", "pending_drop_size", "pending_drop_price"]
    if not all(k in user_specific_data for k in required_context):
        logger.warning(f"Context lost for user {user_id} before processing drop details.")
        await send_message_with_retry(context.bot, chat_id, "❌ Error: Context lost. Please start adding product again.", parse_mode=None)
        keys_to_clear = ["state", "pending_drop", "pending_drop_size", "pending_drop_price", "collecting_media_group_id", "collected_media"]
        for key in keys_to_clear: user_specific_data.pop(key, None)
        return

    media_group_id = update.message.media_group_id
    job_name = f"process_media_group_{user_id}_{media_group_id}" if media_group_id else None

    media_type, file_id = None, None
    if update.message.photo: media_type, file_id = "photo", update.message.photo[-1].file_id
    elif update.message.video: media_type, file_id = "video", update.message.video.file_id
    elif update.message.animation: media_type, file_id = "gif", update.message.animation.file_id

    text = (update.message.caption or update.message.text or "").strip()

    if media_group_id:
        logger.debug(f"Received message part of media group {media_group_id} from user {user_id}")
        if 'collected_media' not in user_specific_data:
            user_specific_data['collected_media'] = {}

        if media_group_id not in user_specific_data['collected_media']:
            user_specific_data['collected_media'][media_group_id] = {'media': [], 'caption': None}
            logger.info(f"Started collecting media for group {media_group_id} user {user_id}")
            user_specific_data['collecting_media_group_id'] = media_group_id

        if media_type and file_id:
            if not any(m['file_id'] == file_id for m in user_specific_data['collected_media'][media_group_id]['media']):
                user_specific_data['collected_media'][media_group_id]['media'].append(
                    {'type': media_type, 'file_id': file_id}
                )
                logger.debug(f"Added media {file_id} ({media_type}) to group {media_group_id}")

        if text:
             user_specific_data['collected_media'][media_group_id]['caption'] = text
             logger.debug(f"Stored/updated caption for group {media_group_id}")

        remove_job_if_exists(job_name, context)
        if hasattr(context, 'job_queue') and context.job_queue:
            context.job_queue.run_once(
                _process_collected_media,
                when=timedelta(seconds=MEDIA_GROUP_COLLECTION_DELAY),
                data={'media_group_id': media_group_id, 'chat_id': chat_id, 'user_id': user_id},
                name=job_name,
                job_kwargs={'misfire_grace_time': 15}
            )
            logger.debug(f"Scheduled/Rescheduled job {job_name} for media group {media_group_id}")
        else:
            logger.error("JobQueue not found in context. Cannot schedule media group processing.")
            await send_message_with_retry(context.bot, chat_id, "❌ Error: Internal components missing. Cannot process media group.", parse_mode=None)

    else:
        if user_specific_data.get('collecting_media_group_id'):
            logger.warning(f"Received single message from user {user_id} while potentially collecting media group {user_specific_data['collecting_media_group_id']}. Ignoring for drop.")
            return

        logger.debug(f"Received single message (or text only) for drop details from user {user_id}")
        user_specific_data.pop('collecting_media_group_id', None)
        user_specific_data.pop('collected_media', None)

        single_media_info = []
        if media_type and file_id:
            single_media_info.append({'type': media_type, 'file_id': file_id})

        await _prepare_and_confirm_drop(context, user_specific_data, chat_id, user_id, text, single_media_info)


# --- Admin Callback Handlers ---
async def handle_admin_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, params=None):
    """Displays the main admin dashboard, handling both command and callback."""
    user = update.effective_user
    query = update.callback_query
    if not user:
        logger.warning("handle_admin_menu triggered without effective_user.")
        if query: await query.answer("Error: Could not identify user.", show_alert=True)
        return

    user_id = user.id
    chat_id = update.effective_chat.id
    is_primary_admin = (user_id == ADMIN_ID)
    is_secondary_admin = (user_id in SECONDARY_ADMIN_IDS)

    if not is_primary_admin and not is_secondary_admin:
        logger.warning(f"Non-admin user {user_id} attempted to access admin menu via {'command' if not query else 'callback'}.")
        msg = "Access denied."
        if query: await query.answer(msg, show_alert=True)
        else: await send_message_with_retry(context.bot, chat_id, msg, parse_mode=None)
        return

    if is_secondary_admin and not is_primary_admin:
        logger.info(f"Redirecting secondary admin {user_id} to viewer admin menu.")
        # Ensure the viewer_admin handler is correctly imported and called
        try:
            # Assuming handle_viewer_admin_menu is imported correctly above
            return await handle_viewer_admin_menu(update, context)
        except NameError:
            logger.error("handle_viewer_admin_menu not found, check imports.")
            fallback_msg = "Viewer admin menu handler is missing."
            if query: await query.edit_message_text(fallback_msg)
            else: await send_message_with_retry(context.bot, chat_id, fallback_msg)
            return


    # --- Primary Admin Dashboard ---
    total_users, total_user_balance, active_products, total_sales_value = 0, Decimal('0.0'), 0, Decimal('0.0')
    conn = None
    try:
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("SELECT COUNT(*) as count FROM users")
        res_users = c.fetchone(); total_users = res_users['count'] if res_users else 0

        c.execute("SELECT COALESCE(SUM(balance), 0.0) as total_bal FROM users")
        res_balance = c.fetchone(); total_user_balance = Decimal(str(res_balance['total_bal'])) if res_balance else Decimal('0.0')

        c.execute("SELECT COUNT(*) as count FROM products WHERE available > reserved")
        res_products = c.fetchone(); active_products = res_products['count'] if res_products else 0

        c.execute("SELECT COALESCE(SUM(price_paid), 0.0) as total_sales FROM purchases")
        res_sales = c.fetchone(); total_sales_value = Decimal(str(res_sales['total_sales'])) if res_sales else Decimal('0.0')

    except sqlite3.Error as e:
        logger.error(f"DB error fetching admin dashboard data: {e}", exc_info=True)
        error_message = "❌ Error loading admin data."
        if query:
            try: await query.edit_message_text(error_message, parse_mode=None)
            except Exception: pass
        else: await send_message_with_retry(context.bot, chat_id, error_message, parse_mode=None)
        return
    finally:
        if conn: conn.close()

    total_user_balance_str = format_currency(total_user_balance)
    total_sales_value_str = format_currency(total_sales_value)
    msg = (
       f"🔧 Admin Dashboard (Primary)\n\n"
       f"👥 Total Users: {total_users}\n"
       f"💰 Sum of User Balances: {total_user_balance_str} EUR\n"
       f"📈 Total Sales Value: {total_sales_value_str} EUR\n"
       f"📦 Active Products: {active_products}\n\n"
       "Select an action:"
    )

    # <<< ADDED Clear Reservations Button >>>
    keyboard = [
        [InlineKeyboardButton("📊 Sales Analytics", callback_data="sales_analytics_menu")],
        [InlineKeyboardButton("➕ Add Products", callback_data="adm_city")],
        [InlineKeyboardButton("🗑️ Manage Products", callback_data="adm_manage_products")],
        [InlineKeyboardButton("👥 Manage Users", callback_data="adm_manage_users|0")],
        [InlineKeyboardButton("👑 Manage Resellers", callback_data="manage_resellers_menu")],
        [InlineKeyboardButton("🏷️ Manage Reseller Discounts", callback_data="manage_reseller_discounts_select_reseller|0")],
        [InlineKeyboardButton("🏷️ Manage Discount Codes", callback_data="adm_manage_discounts")],
        [InlineKeyboardButton("👋 Manage Welcome Msg", callback_data="adm_manage_welcome|0")],
        [InlineKeyboardButton("📦 View Bot Stock", callback_data="view_stock")],
        [InlineKeyboardButton("📜 View Added Products Log", callback_data="viewer_added_products|0")],
        [InlineKeyboardButton("🗺️ Manage Districts", callback_data="adm_manage_districts")],
        [InlineKeyboardButton("🏙️ Manage Cities", callback_data="adm_manage_cities")],
        [InlineKeyboardButton("🧩 Manage Product Types", callback_data="adm_manage_types")],
        [InlineKeyboardButton("🚫 Manage Reviews", callback_data="adm_manage_reviews|0")],
        [InlineKeyboardButton("🧹 Clear ALL Reservations", callback_data="adm_clear_reservations_confirm")], # <<< ADDED
        [InlineKeyboardButton("📢 Broadcast Message", callback_data="adm_broadcast_start")],
        [InlineKeyboardButton("➕ Add New City", callback_data="adm_add_city")],
        [InlineKeyboardButton("📸 Set Bot Media", callback_data="adm_set_media")],
        [InlineKeyboardButton("🏠 User Home Menu", callback_data="back_start")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    if query:
        try:
            await query.edit_message_text(msg, reply_markup=reply_markup, parse_mode=None)
        except telegram_error.BadRequest as e:
            if "message is not modified" not in str(e).lower():
                logger.error(f"Error editing admin menu message: {e}")
                # Attempt to send as new message if edit fails catastrophically
                await send_message_with_retry(context.bot, chat_id, msg, reply_markup=reply_markup, parse_mode=None)
            else: # Message not modified is fine, just answer the query
                await query.answer()
        except Exception as e:
            logger.error(f"Unexpected error editing admin menu: {e}", exc_info=True)
            # Attempt to send as new message on unexpected error
            await send_message_with_retry(context.bot, chat_id, msg, reply_markup=reply_markup, parse_mode=None)
    else: # Called by /admin command
        await send_message_with_retry(context.bot, chat_id, msg, reply_markup=reply_markup, parse_mode=None)


# --- Sales Analytics Handlers ---
async def handle_sales_analytics_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, params=None):
    """Displays the sales analytics submenu."""
    query = update.callback_query
    if query.from_user.id != ADMIN_ID: return await query.answer("Access denied.", show_alert=True)
    msg = "📊 Sales Analytics\n\nSelect a report or view:"
    keyboard = [
        [InlineKeyboardButton("📈 View Dashboard", callback_data="sales_dashboard")],
        [InlineKeyboardButton("📅 Generate Report", callback_data="sales_select_period|main")],
        [InlineKeyboardButton("🏙️ Sales by City", callback_data="sales_select_period|by_city")],
        [InlineKeyboardButton("💎 Sales by Type", callback_data="sales_select_period|by_type")],
        [InlineKeyboardButton("🏆 Top Products", callback_data="sales_select_period|top_prod")],
        [InlineKeyboardButton("⬅️ Back", callback_data="admin_menu")]
    ]
    await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=None)

async def handle_sales_dashboard(update: Update, context: ContextTypes.DEFAULT_TYPE, params=None):
    """Displays a quick sales dashboard for today, this week, this month."""
    query = update.callback_query
    if query.from_user.id != ADMIN_ID: return await query.answer("Access denied.", show_alert=True)
    periods = {
        "today": ("☀️ Today ({})", datetime.now(timezone.utc).strftime("%Y-%m-%d")), # Use UTC
        "week": ("🗓️ This Week (Mon-Sun)", None),
        "month": ("📆 This Month", None)
    }
    msg = "📊 Sales Dashboard\n\n"
    conn = None # Initialize conn
    try:
        conn = get_db_connection() # Use helper
        c = conn.cursor()
        for period_key, (label_template, date_str) in periods.items():
            start, end = get_date_range(period_key)
            if not start or not end:
                msg += f"Could not calculate range for {period_key}.\n\n"
                continue
            # Use column names
            c.execute("SELECT COALESCE(SUM(price_paid), 0.0) as total_revenue, COUNT(*) as total_units FROM purchases WHERE purchase_date BETWEEN ? AND ?", (start, end))
            result = c.fetchone()
            revenue = result['total_revenue'] if result else 0.0
            units = result['total_units'] if result else 0
            aov = revenue / units if units > 0 else 0.0
            revenue_str = format_currency(revenue)
            aov_str = format_currency(aov)
            label_formatted = label_template.format(date_str) if date_str else label_template
            msg += f"{label_formatted}\n"
            msg += f"    Revenue: {revenue_str} EUR\n"
            msg += f"    Units Sold: {units}\n"
            msg += f"    Avg Order Value: {aov_str} EUR\n\n"
    except sqlite3.Error as e:
        logger.error(f"DB error generating sales dashboard: {e}", exc_info=True)
        msg += "\n❌ Error fetching dashboard data."
    except Exception as e:
        logger.error(f"Unexpected error in sales dashboard: {e}", exc_info=True)
        msg += "\n❌ An unexpected error occurred."
    finally:
         if conn: conn.close() # Close connection if opened
    keyboard = [[InlineKeyboardButton("⬅️ Back", callback_data="sales_analytics_menu")]]
    try:
        await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=None)
    except telegram_error.BadRequest as e:
        if "message is not modified" not in str(e).lower(): logger.error(f"Error editing sales dashboard: {e}")
        else: await query.answer()

async def handle_sales_select_period(update: Update, context: ContextTypes.DEFAULT_TYPE, params=None):
    """Shows options for selecting a reporting period."""
    query = update.callback_query
    if query.from_user.id != ADMIN_ID: return await query.answer("Access denied.", show_alert=True)
    if not params:
        logger.warning("handle_sales_select_period called without report_type.")
        return await query.answer("Error: Report type missing.", show_alert=True)
    report_type = params[0]
    context.user_data['sales_report_type'] = report_type
    keyboard = [
        [InlineKeyboardButton("Today", callback_data=f"sales_run|{report_type}|today"),
         InlineKeyboardButton("Yesterday", callback_data=f"sales_run|{report_type}|yesterday")],
        [InlineKeyboardButton("This Week", callback_data=f"sales_run|{report_type}|week"),
         InlineKeyboardButton("Last Week", callback_data=f"sales_run|{report_type}|last_week")],
        [InlineKeyboardButton("This Month", callback_data=f"sales_run|{report_type}|month"),
         InlineKeyboardButton("Last Month", callback_data=f"sales_run|{report_type}|last_month")],
        [InlineKeyboardButton("Year To Date", callback_data=f"sales_run|{report_type}|year")],
        [InlineKeyboardButton("⬅️ Back", callback_data="sales_analytics_menu")]
    ]
    await query.edit_message_text("📅 Select Reporting Period", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=None)

async def handle_sales_run(update: Update, context: ContextTypes.DEFAULT_TYPE, params=None):
    """Generates and displays the selected sales report."""
    query = update.callback_query
    if query.from_user.id != ADMIN_ID: return await query.answer("Access denied.", show_alert=True)
    if not params or len(params) < 2:
        logger.warning("handle_sales_run called with insufficient parameters.")
        return await query.answer("Error: Report type or period missing.", show_alert=True)
    report_type, period_key = params[0], params[1]
    start_time, end_time = get_date_range(period_key)
    if not start_time or not end_time:
        return await query.edit_message_text("❌ Error: Invalid period selected.", parse_mode=None)
    period_title = period_key.replace('_', ' ').title()
    msg = ""
    conn = None # Initialize conn
    try:
        conn = get_db_connection() # Use helper
        # row_factory is set in helper
        c = conn.cursor()
        base_query = "FROM purchases WHERE purchase_date BETWEEN ? AND ?"
        base_params = (start_time, end_time)
        if report_type == "main":
            c.execute(f"SELECT COALESCE(SUM(price_paid), 0.0) as total_revenue, COUNT(*) as total_units {base_query}", base_params)
            result = c.fetchone()
            revenue = result['total_revenue'] if result else 0.0
            units = result['total_units'] if result else 0
            aov = revenue / units if units > 0 else 0.0
            revenue_str = format_currency(revenue)
            aov_str = format_currency(aov)
            msg = (f"📊 Sales Report: {period_title}\n\nRevenue: {revenue_str} EUR\n"
                   f"Units Sold: {units}\nAvg Order Value: {aov_str} EUR")
        elif report_type == "by_city":
            c.execute(f"SELECT city, COALESCE(SUM(price_paid), 0.0) as city_revenue, COUNT(*) as city_units {base_query} GROUP BY city ORDER BY city_revenue DESC", base_params)
            results = c.fetchall()
            msg = f"🏙️ Sales by City: {period_title}\n\n"
            if results:
                for row in results:
                    msg += f"{row['city'] or 'N/A'}: {format_currency(row['city_revenue'])} EUR ({row['city_units'] or 0} units)\n"
            else: msg += "No sales data for this period."
        elif report_type == "by_type":
            c.execute(f"SELECT product_type, COALESCE(SUM(price_paid), 0.0) as type_revenue, COUNT(*) as type_units {base_query} GROUP by product_type ORDER BY type_revenue DESC", base_params)
            results = c.fetchall()
            msg = f"📊 Sales by Type: {period_title}\n\n"
            if results:
                for row in results:
                    type_name = row['product_type'] or 'N/A'
                    emoji = PRODUCT_TYPES.get(type_name, DEFAULT_PRODUCT_EMOJI)
                    msg += f"{emoji} {type_name}: {format_currency(row['type_revenue'])} EUR ({row['type_units'] or 0} units)\n"
            else: msg += "No sales data for this period."
        elif report_type == "top_prod":
            c.execute(f"""
                SELECT pu.product_name, pu.product_size, pu.product_type,
                       COALESCE(SUM(pu.price_paid), 0.0) as prod_revenue,
                       COUNT(pu.id) as prod_units
                FROM purchases pu
                WHERE pu.purchase_date BETWEEN ? AND ?
                GROUP BY pu.product_name, pu.product_size, pu.product_type
                ORDER BY prod_revenue DESC LIMIT 10
            """, base_params) # Simplified query relying on purchase record details
            results = c.fetchall()
            msg = f"🏆 Top Products: {period_title}\n\n"
            if results:
                for i, row in enumerate(results):
                    type_name = row['product_type'] or 'N/A'
                    emoji = PRODUCT_TYPES.get(type_name, DEFAULT_PRODUCT_EMOJI)
                    msg += f"{i+1}. {emoji} {row['product_name'] or 'N/A'} ({row['product_size'] or 'N/A'}): {format_currency(row['prod_revenue'])} EUR ({row['prod_units'] or 0} units)\n"
            else: msg += "No sales data for this period."
        else: msg = "❌ Unknown report type requested."
    except sqlite3.Error as e:
        logger.error(f"DB error generating sales report '{report_type}' for '{period_key}': {e}", exc_info=True)
        msg = "❌ Error generating report due to database issue."
    except Exception as e:
        logger.error(f"Unexpected error generating sales report: {e}", exc_info=True)
        msg = "❌ An unexpected error occurred."
    finally:
         if conn: conn.close()
    keyboard = [[InlineKeyboardButton("⬅️ Back to Period", callback_data=f"sales_select_period|{report_type}"),
                 InlineKeyboardButton("📊 Analytics Menu", callback_data="sales_analytics_menu")]]
    try:
        await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=None)
    except telegram_error.BadRequest as e:
        if "message is not modified" not in str(e).lower(): logger.error(f"Error editing sales report: {e}")
        else: await query.answer()

# --- Add Product Flow Handlers ---
async def handle_adm_city(update: Update, context: ContextTypes.DEFAULT_TYPE, params=None):
    """Admin selects city to add product to."""
    query = update.callback_query
    if query.from_user.id != ADMIN_ID: return await query.answer("Access denied.", show_alert=True)
    lang, lang_data = _get_lang_data(context) # Use helper
    if not CITIES:
        return await query.edit_message_text("No cities configured. Please add a city first via 'Manage Cities'.", parse_mode=None)
    sorted_city_ids = sorted(CITIES.keys(), key=lambda city_id: CITIES.get(city_id, ''))
    keyboard = [[InlineKeyboardButton(f"🏙️ {CITIES.get(c,'N/A')}", callback_data=f"adm_dist|{c}")] for c in sorted_city_ids]
    keyboard.append([InlineKeyboardButton("⬅️ Back", callback_data="admin_menu")])
    select_city_text = lang_data.get("admin_select_city", "Select City to Add Product:")
    await query.edit_message_text(select_city_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=None)

async def handle_adm_dist(update: Update, context: ContextTypes.DEFAULT_TYPE, params=None):
    """Admin selects district within the chosen city."""
    query = update.callback_query
    if query.from_user.id != ADMIN_ID: return await query.answer("Access denied.", show_alert=True)
    if not params: return await query.answer("Error: City ID missing.", show_alert=True)
    city_id = params[0]
    city_name = CITIES.get(city_id)
    if not city_name:
        return await query.edit_message_text("Error: City not found. Please select again.", parse_mode=None)
    districts_in_city = DISTRICTS.get(city_id, {})
    lang, lang_data = _get_lang_data(context) # Use helper
    select_district_template = lang_data.get("admin_select_district", "Select District in {city}:")
    if not districts_in_city:
        keyboard = [[InlineKeyboardButton("⬅️ Back to Cities", callback_data="adm_city")]]
        return await query.edit_message_text(f"No districts found for {city_name}. Please add districts via 'Manage Districts'.",
                                reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=None)
    sorted_district_ids = sorted(districts_in_city.keys(), key=lambda dist_id: districts_in_city.get(dist_id,''))
    keyboard = []
    for d in sorted_district_ids:
        dist_name = districts_in_city.get(d)
        if dist_name:
            keyboard.append([InlineKeyboardButton(f"🏘️ {dist_name}", callback_data=f"adm_type|{city_id}|{d}")])
        else: logger.warning(f"District name missing for ID {d} in city {city_id}")
    keyboard.append([InlineKeyboardButton("⬅️ Back to Cities", callback_data="adm_city")])
    select_district_text = select_district_template.format(city=city_name)
    await query.edit_message_text(select_district_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=None)

async def handle_adm_type(update: Update, context: ContextTypes.DEFAULT_TYPE, params=None):
    """Admin selects product type."""
    query = update.callback_query
    if query.from_user.id != ADMIN_ID: return await query.answer("Access denied.", show_alert=True)
    if not params or len(params) < 2: return await query.answer("Error: City or District ID missing.", show_alert=True)
    city_id, dist_id = params[0], params[1]
    city_name = CITIES.get(city_id)
    district_name = DISTRICTS.get(city_id, {}).get(dist_id)
    if not city_name or not district_name:
        return await query.edit_message_text("Error: City/District not found. Please select again.", parse_mode=None)
    lang, lang_data = _get_lang_data(context) # Use helper
    select_type_text = lang_data.get("admin_select_type", "Select Product Type:")
    if not PRODUCT_TYPES:
        return await query.edit_message_text("No product types configured. Add types via 'Manage Product Types'.", parse_mode=None)

    keyboard = []
    for type_name, emoji in sorted(PRODUCT_TYPES.items()):
        keyboard.append([InlineKeyboardButton(f"{emoji} {type_name}", callback_data=f"adm_add|{city_id}|{dist_id}|{type_name}")])

    keyboard.append([InlineKeyboardButton("⬅️ Back to Districts", callback_data=f"adm_dist|{city_id}")])
    await query.edit_message_text(select_type_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=None)


async def handle_adm_add(update: Update, context: ContextTypes.DEFAULT_TYPE, params=None):
    """Admin selects size for the new product."""
    query = update.callback_query
    if query.from_user.id != ADMIN_ID: return await query.answer("Access denied.", show_alert=True)
    if not params or len(params) < 3: return await query.answer("Error: Location/Type info missing.", show_alert=True)
    city_id, dist_id, p_type = params
    city_name = CITIES.get(city_id)
    district_name = DISTRICTS.get(city_id, {}).get(dist_id)
    if not city_name or not district_name:
        return await query.edit_message_text("Error: City/District not found. Please select again.", parse_mode=None)
    type_emoji = PRODUCT_TYPES.get(p_type, DEFAULT_PRODUCT_EMOJI)
    context.user_data["admin_city_id"] = city_id
    context.user_data["admin_district_id"] = dist_id
    context.user_data["admin_product_type"] = p_type
    context.user_data["admin_city"] = city_name
    context.user_data["admin_district"] = district_name
    keyboard = [[InlineKeyboardButton(f"📏 {s}", callback_data=f"adm_size|{s}")] for s in SIZES]
    keyboard.append([InlineKeyboardButton("📏 Custom Size", callback_data="adm_custom_size")])
    keyboard.append([InlineKeyboardButton("⬅️ Back to Types", callback_data=f"adm_type|{city_id}|{dist_id}")])
    await query.edit_message_text(f"📦 Adding {type_emoji} {p_type} in {city_name} / {district_name}\n\nSelect size:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=None)

async def handle_adm_size(update: Update, context: ContextTypes.DEFAULT_TYPE, params=None):
    """Handles selection of a predefined size."""
    query = update.callback_query
    if query.from_user.id != ADMIN_ID: return await query.answer("Access denied.", show_alert=True)
    if not params: return await query.answer("Error: Size missing.", show_alert=True)
    size = params[0]
    if not all(k in context.user_data for k in ["admin_city", "admin_district", "admin_product_type"]):
        return await query.edit_message_text("❌ Error: Context lost. Please start adding the product again.", parse_mode=None)
    context.user_data["pending_drop_size"] = size
    context.user_data["state"] = "awaiting_price"
    keyboard = [[InlineKeyboardButton("❌ Cancel Add", callback_data="cancel_add")]]
    await query.edit_message_text(f"Size set to {size}. Please reply with the price (e.g., 12.50 or 12.5):",
                            reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=None)
    await query.answer("Enter price in chat.")

async def handle_adm_custom_size(update: Update, context: ContextTypes.DEFAULT_TYPE, params=None):
    """Handles 'Custom Size' button press."""
    query = update.callback_query
    if query.from_user.id != ADMIN_ID: return await query.answer("Access denied.", show_alert=True)
    if not all(k in context.user_data for k in ["admin_city", "admin_district", "admin_product_type"]):
        return await query.edit_message_text("❌ Error: Context lost. Please start adding the product again.", parse_mode=None)
    context.user_data["state"] = "awaiting_custom_size"
    keyboard = [[InlineKeyboardButton("❌ Cancel Add", callback_data="cancel_add")]]
    await query.edit_message_text("Please reply with the custom size (e.g., 10g, 1/4 oz):",
                            reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=None)
    await query.answer("Enter custom size in chat.")

async def handle_confirm_add_drop(update: Update, context: ContextTypes.DEFAULT_TYPE, params=None):
    """Handles confirmation (Yes/No) for adding the drop."""
    query = update.callback_query
    user_id = query.from_user.id
    if user_id != ADMIN_ID: return await query.answer("Access denied.", show_alert=True)
    chat_id = query.message.chat_id
    user_specific_data = context.user_data # Use context.user_data for the admin's data
    pending_drop = user_specific_data.get("pending_drop")

    if not pending_drop:
        logger.error(f"Confirmation 'yes' received for add drop, but no pending_drop data found for user {user_id}.")
        user_specific_data.pop("state", None)
        return await query.edit_message_text("❌ Error: No pending drop data found. Please start again.", parse_mode=None)

    city = pending_drop.get("city"); district = pending_drop.get("district"); p_type = pending_drop.get("product_type")
    size = pending_drop.get("size"); price = pending_drop.get("price"); original_text = pending_drop.get("original_text", "")
    media_list = pending_drop.get("media", []); temp_dir = pending_drop.get("temp_dir")

    if not all([city, district, p_type, size, price is not None]):
        logger.error(f"Missing data in pending_drop for user {user_id}: {pending_drop}")
        if temp_dir and await asyncio.to_thread(os.path.exists, temp_dir): await asyncio.to_thread(shutil.rmtree, temp_dir, ignore_errors=True)
        keys_to_clear = ["state", "pending_drop", "pending_drop_size", "pending_drop_price", "admin_city_id", "admin_district_id", "admin_product_type", "admin_city", "admin_district"]
        for key in keys_to_clear: user_specific_data.pop(key, None)
        return await query.edit_message_text("❌ Error: Incomplete drop data. Please start again.", parse_mode=None)

    product_name = f"{p_type} {size} {int(time.time())}"; conn = None; product_id = None
    try:
        conn = get_db_connection(); c = conn.cursor(); c.execute("BEGIN")
        insert_params = (
            city, district, p_type, size, product_name, price, original_text, ADMIN_ID, datetime.now(timezone.utc).isoformat()
        )
        logger.debug(f"Inserting product with params count: {len(insert_params)}") # Add debug log
        c.execute("""INSERT INTO products
                        (city, district, product_type, size, name, price, available, reserved, original_text, added_by, added_date)
                     VALUES (?, ?, ?, ?, ?, ?, 1, 0, ?, ?, ?)""", insert_params)
        product_id = c.lastrowid

        if product_id and media_list and temp_dir:
            final_media_dir = os.path.join(MEDIA_DIR, str(product_id)); await asyncio.to_thread(os.makedirs, final_media_dir, exist_ok=True); media_inserts = []
            for media_item in media_list:
                if "path" in media_item and "type" in media_item and "file_id" in media_item:
                    temp_file_path = media_item["path"]
                    if await asyncio.to_thread(os.path.exists, temp_file_path):
                        new_filename = os.path.basename(temp_file_path); final_persistent_path = os.path.join(final_media_dir, new_filename)
                        try: await asyncio.to_thread(shutil.move, temp_file_path, final_persistent_path); media_inserts.append((product_id, media_item["type"], final_persistent_path, media_item["file_id"]))
                        except OSError as move_err: logger.error(f"Error moving media {temp_file_path}: {move_err}")
                    else: logger.warning(f"Temp media not found: {temp_file_path}")
                else: logger.warning(f"Incomplete media item: {media_item}")
            if media_inserts: c.executemany("INSERT INTO product_media (product_id, media_type, file_path, telegram_file_id) VALUES (?, ?, ?, ?)", media_inserts)

        conn.commit(); logger.info(f"Added product {product_id} ({product_name}).")
        if temp_dir and await asyncio.to_thread(os.path.exists, temp_dir): await asyncio.to_thread(shutil.rmtree, temp_dir, ignore_errors=True); logger.info(f"Cleaned temp dir: {temp_dir}")
        await query.edit_message_text("✅ Drop Added Successfully!", parse_mode=None)
        ctx_city_id = user_specific_data.get('admin_city_id'); ctx_dist_id = user_specific_data.get('admin_district_id'); ctx_p_type = user_specific_data.get('admin_product_type')
        add_another_callback = f"adm_add|{ctx_city_id}|{ctx_dist_id}|{ctx_p_type}" if all([ctx_city_id, ctx_dist_id, ctx_p_type]) else "admin_menu"
        keyboard = [ [InlineKeyboardButton("➕ Add Another Same Type", callback_data=add_another_callback)],
                     [InlineKeyboardButton("🔧 Admin Menu", callback_data="admin_menu"), InlineKeyboardButton("🏠 User Home", callback_data="back_start")] ]
        await send_message_with_retry(context.bot, chat_id, "What next?", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=None)
    except (sqlite3.Error, OSError, Exception) as e:
        try: conn.rollback() if conn and conn.in_transaction else None
        except Exception as rb_err: logger.error(f"Rollback failed: {rb_err}")
        logger.error(f"Error saving confirmed drop for user {user_id}: {e}", exc_info=True)
        await query.edit_message_text("❌ Error: Failed to save the drop. Please check logs and try again.", parse_mode=None)
        if temp_dir and await asyncio.to_thread(os.path.exists, temp_dir): await asyncio.to_thread(shutil.rmtree, temp_dir, ignore_errors=True); logger.info(f"Cleaned temp dir after error: {temp_dir}")
    finally:
        if conn: conn.close()
        keys_to_clear = ["state", "pending_drop", "pending_drop_size", "pending_drop_price"]
        for key in keys_to_clear: user_specific_data.pop(key, None)


async def cancel_add(update: Update, context: ContextTypes.DEFAULT_TYPE, params=None):
    """Cancels the add product flow and cleans up."""
    query = update.callback_query
    user_id = update.effective_user.id
    user_specific_data = context.user_data # Use context.user_data
    pending_drop = user_specific_data.get("pending_drop")
    if pending_drop and "temp_dir" in pending_drop and pending_drop["temp_dir"]:
        temp_dir_path = pending_drop["temp_dir"]
        if await asyncio.to_thread(os.path.exists, temp_dir_path):
            try: await asyncio.to_thread(shutil.rmtree, temp_dir_path, ignore_errors=True); logger.info(f"Cleaned temp dir on cancel: {temp_dir_path}")
            except Exception as e: logger.error(f"Error cleaning temp dir {temp_dir_path}: {e}")
    keys_to_clear = ["state", "pending_drop", "pending_drop_size", "pending_drop_price", "admin_city_id", "admin_district_id", "admin_product_type", "admin_city", "admin_district", "collecting_media_group_id", "collected_media"]
    for key in keys_to_clear: user_specific_data.pop(key, None)
    if 'collecting_media_group_id' in user_specific_data:
        media_group_id = user_specific_data.pop('collecting_media_group_id', None)
        if media_group_id: job_name = f"process_media_group_{user_id}_{media_group_id}"; remove_job_if_exists(job_name, context)
    if query:
         try:
             await query.edit_message_text("❌ Add Product Cancelled", parse_mode=None)
         except telegram_error.BadRequest as e:
             if "message is not modified" in str(e).lower():
                 pass # It's okay if the message wasn't modified
             else:
                 logger.error(f"Error editing cancel message: {e}")
         keyboard = [[InlineKeyboardButton("🔧 Admin Menu", callback_data="admin_menu"), InlineKeyboardButton("🏠 User Home", callback_data="back_start")]]; await send_message_with_retry(context.bot, query.message.chat_id, "Returning to Admin Menu.", reply_markup=InlineKeyboardMarkup(keyboard))
    elif update.message: await send_message_with_retry(context.bot, update.message.chat_id, "Add product cancelled.")
    else: logger.info("Add product flow cancelled internally (no query/message object).")


# --- Manage Geography Handlers ---
async def handle_adm_manage_cities(update: Update, context: ContextTypes.DEFAULT_TYPE, params=None):
    """Shows options to manage existing cities."""
    query = update.callback_query
    if query.from_user.id != ADMIN_ID: return await query.answer("Access denied.", show_alert=True)
    if not CITIES:
         return await query.edit_message_text("No cities configured. Use 'Add New City'.", parse_mode=None,
                                 reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("➕ Add New City", callback_data="adm_add_city")],
                                                                      [InlineKeyboardButton("⬅️ Back to Admin Menu", callback_data="admin_menu")]]))
    sorted_city_ids = sorted(CITIES.keys(), key=lambda city_id: CITIES.get(city_id, ''))
    keyboard = []
    for c in sorted_city_ids:
        city_name = CITIES.get(c,'N/A')
        keyboard.append([
             InlineKeyboardButton(f"🏙️ {city_name}", callback_data=f"adm_edit_city|{c}"),
             InlineKeyboardButton(f"🗑️ Delete", callback_data=f"adm_delete_city|{c}")
        ])
    keyboard.append([InlineKeyboardButton("➕ Add New City", callback_data="adm_add_city")])
    keyboard.append([InlineKeyboardButton("⬅️ Back to Admin Menu", callback_data="admin_menu")])
    await query.edit_message_text("🏙️ Manage Cities\n\nSelect a city or action:",
                            reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=None)

async def handle_adm_add_city(update: Update, context: ContextTypes.DEFAULT_TYPE, params=None):
    """Handles 'Add New City' button press."""
    query = update.callback_query
    if query.from_user.id != ADMIN_ID: return await query.answer("Access denied.", show_alert=True)
    context.user_data["state"] = "awaiting_new_city_name"
    keyboard = [[InlineKeyboardButton("❌ Cancel", callback_data="adm_manage_cities")]]
    await query.edit_message_text("🏙️ Please reply with the name for the new city:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=None)
    await query.answer("Enter city name in chat.")

async def handle_adm_edit_city(update: Update, context: ContextTypes.DEFAULT_TYPE, params=None):
    """Handles 'Edit City' button press."""
    query = update.callback_query
    if query.from_user.id != ADMIN_ID: return await query.answer("Access denied.", show_alert=True)
    if not params: return await query.answer("Error: City ID missing.", show_alert=True)
    city_id = params[0]
    city_name = CITIES.get(city_id)
    if not city_name:
        return await query.edit_message_text("Error: City not found.", parse_mode=None)
    context.user_data["state"] = "awaiting_edit_city_name"
    context.user_data["edit_city_id"] = city_id
    keyboard = [[InlineKeyboardButton("❌ Cancel", callback_data="adm_manage_cities")]]
    await query.edit_message_text(f"✏️ Editing city: {city_name}\n\nPlease reply with the new name for this city:",
                            reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=None)
    await query.answer("Enter new city name in chat.")

async def handle_adm_delete_city(update: Update, context: ContextTypes.DEFAULT_TYPE, params=None):
    """Handles 'Delete City' button press, shows confirmation."""
    query = update.callback_query
    if query.from_user.id != ADMIN_ID: return await query.answer("Access denied.", show_alert=True)
    if not params: return await query.answer("Error: City ID missing.", show_alert=True)
    city_id = params[0]
    city_name = CITIES.get(city_id)
    if not city_name:
        return await query.edit_message_text("Error: City not found.", parse_mode=None)
    context.user_data["confirm_action"] = f"delete_city|{city_id}"
    msg = (f"⚠️ Confirm Deletion\n\n"
           f"Are you sure you want to delete city: {city_name}?\n\n"
           f"🚨 This will permanently delete this city, all its districts, and all products listed within those districts!")
    keyboard = [[InlineKeyboardButton("✅ Yes, Delete City", callback_data="confirm_yes"),
                 InlineKeyboardButton("❌ No, Cancel", callback_data="adm_manage_cities")]]
    await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=None)

async def handle_adm_manage_districts(update: Update, context: ContextTypes.DEFAULT_TYPE, params=None):
    """Shows list of cities to choose from for managing districts."""
    query = update.callback_query
    if query.from_user.id != ADMIN_ID: return await query.answer("Access denied.", show_alert=True)
    if not CITIES:
         return await query.edit_message_text("No cities configured. Add a city first.", parse_mode=None,
                                 reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back to Admin Menu", callback_data="admin_menu")]]))
    sorted_city_ids = sorted(CITIES.keys(), key=lambda city_id: CITIES.get(city_id,''))
    keyboard = [[InlineKeyboardButton(f"🏙️ {CITIES.get(c, 'N/A')}", callback_data=f"adm_manage_districts_city|{c}")] for c in sorted_city_ids]
    keyboard.append([InlineKeyboardButton("⬅️ Back to Admin Menu", callback_data="admin_menu")])
    await query.edit_message_text("🗺️ Manage Districts\n\nSelect the city whose districts you want to manage:",
                            reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=None)

async def handle_adm_manage_districts_city(update: Update, context: ContextTypes.DEFAULT_TYPE, params=None):
    """Shows districts for the selected city and management options."""
    query = update.callback_query
    if query.from_user.id != ADMIN_ID: return await query.answer("Access denied.", show_alert=True)
    if not params: return await query.answer("Error: City ID missing.", show_alert=True)
    city_id = params[0]
    city_name = CITIES.get(city_id)
    if not city_name:
        return await query.edit_message_text("Error: City not found.", parse_mode=None)
    districts_in_city = {}
    conn = None
    try:
        conn = get_db_connection() # Use helper
        c = conn.cursor()
        # Use column names
        c.execute("SELECT id, name FROM districts WHERE city_id = ? ORDER BY name", (int(city_id),))
        districts_in_city = {str(row['id']): row['name'] for row in c.fetchall()}
    except (sqlite3.Error, ValueError) as e:
        logger.error(f"Failed to reload districts for city {city_id}: {e}")
        districts_in_city = DISTRICTS.get(city_id, {}) # Fallback to potentially outdated global
    finally:
        if conn: conn.close()

    msg = f"🗺️ Districts in {city_name}\n\n"
    keyboard = []
    if not districts_in_city: msg += "No districts found for this city."
    else:
        sorted_district_ids = sorted(districts_in_city.keys(), key=lambda dist_id: districts_in_city.get(dist_id,''))
        for d_id in sorted_district_ids:
            dist_name = districts_in_city.get(d_id)
            if dist_name:
                 keyboard.append([
                     InlineKeyboardButton(f"✏️ Edit {dist_name}", callback_data=f"adm_edit_district|{city_id}|{d_id}"),
                     InlineKeyboardButton(f"🗑️ Delete {dist_name}", callback_data=f"adm_remove_district|{city_id}|{d_id}")
                 ])
            else: logger.warning(f"District name missing for ID {d_id} in city {city_id} (manage view)")
    keyboard.extend([
        [InlineKeyboardButton("➕ Add New District", callback_data=f"adm_add_district|{city_id}")],
        [InlineKeyboardButton("⬅️ Back to Cities", callback_data="adm_manage_districts")]
    ])
    try:
        await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=None)
    except telegram_error.BadRequest as e:
        if "message is not modified" not in str(e).lower(): logger.error(f"Error editing manage districts city message: {e}")
        else: await query.answer()

async def handle_adm_add_district(update: Update, context: ContextTypes.DEFAULT_TYPE, params=None):
    """Handles 'Add New District' button press."""
    query = update.callback_query
    if query.from_user.id != ADMIN_ID: return await query.answer("Access denied.", show_alert=True)
    if not params: return await query.answer("Error: City ID missing.", show_alert=True)
    city_id = params[0]
    city_name = CITIES.get(city_id)
    if not city_name:
        return await query.edit_message_text("Error: City not found.", parse_mode=None)
    context.user_data["state"] = "awaiting_new_district_name"
    context.user_data["admin_add_district_city_id"] = city_id
    keyboard = [[InlineKeyboardButton("❌ Cancel", callback_data=f"adm_manage_districts_city|{city_id}")]]
    await query.edit_message_text(f"➕ Adding district to {city_name}\n\nPlease reply with the name for the new district:",
                            reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=None)
    await query.answer("Enter district name in chat.")

async def handle_adm_edit_district(update: Update, context: ContextTypes.DEFAULT_TYPE, params=None):
    """Handles 'Edit District' button press."""
    query = update.callback_query
    if query.from_user.id != ADMIN_ID: return await query.answer("Access denied.", show_alert=True)
    if not params or len(params) < 2: return await query.answer("Error: City/District ID missing.", show_alert=True)
    city_id, dist_id = params
    city_name = CITIES.get(city_id)
    district_name = None
    conn = None
    try:
        conn = get_db_connection() # Use helper
        c = conn.cursor()
        # Use column name
        c.execute("SELECT name FROM districts WHERE id = ? AND city_id = ?", (int(dist_id), int(city_id)))
        res = c.fetchone(); district_name = res['name'] if res else None
    except (sqlite3.Error, ValueError) as e: logger.error(f"Failed to fetch district name for edit: {e}")
    finally:
         if conn: conn.close()
    if not city_name or district_name is None:
        return await query.edit_message_text("Error: City/District not found.", parse_mode=None)
    context.user_data["state"] = "awaiting_edit_district_name"
    context.user_data["edit_city_id"] = city_id
    context.user_data["edit_district_id"] = dist_id
    keyboard = [[InlineKeyboardButton("❌ Cancel", callback_data=f"adm_manage_districts_city|{city_id}")]]
    await query.edit_message_text(f"✏️ Editing district: {district_name} in {city_name}\n\nPlease reply with the new name for this district:",
                           reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=None)
    await query.answer("Enter new district name in chat.")

async def handle_adm_remove_district(update: Update, context: ContextTypes.DEFAULT_TYPE, params=None):
    """Handles 'Delete District' button press, shows confirmation."""
    query = update.callback_query
    if query.from_user.id != ADMIN_ID: return await query.answer("Access denied.", show_alert=True)
    if not params or len(params) < 2: return await query.answer("Error: City/District ID missing.", show_alert=True)
    city_id, dist_id = params
    city_name = CITIES.get(city_id)
    district_name = None
    conn = None
    try:
        conn = get_db_connection() # Use helper
        c = conn.cursor()
        # Use column name
        c.execute("SELECT name FROM districts WHERE id = ? AND city_id = ?", (int(dist_id), int(city_id)))
        res = c.fetchone(); district_name = res['name'] if res else None
    except (sqlite3.Error, ValueError) as e: logger.error(f"Failed to fetch district name for delete confirmation: {e}")
    finally:
        if conn: conn.close()
    if not city_name or district_name is None:
        return await query.edit_message_text("Error: City/District not found.", parse_mode=None)
    context.user_data["confirm_action"] = f"remove_district|{city_id}|{dist_id}"
    msg = (f"⚠️ Confirm Deletion\n\n"
           f"Are you sure you want to delete district: {district_name} from {city_name}?\n\n"
           f"🚨 This will permanently delete this district and all products listed within it!")
    keyboard = [[InlineKeyboardButton("✅ Yes, Delete District", callback_data="confirm_yes"),
                 InlineKeyboardButton("❌ No, Cancel", callback_data=f"adm_manage_districts_city|{city_id}")]]
    await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=None)


# --- Manage Products Handlers ---
async def handle_adm_manage_products(update: Update, context: ContextTypes.DEFAULT_TYPE, params=None):
    """Admin selects city to manage products in."""
    query = update.callback_query
    if query.from_user.id != ADMIN_ID: return await query.answer("Access denied.", show_alert=True)
    if not CITIES:
         return await query.edit_message_text("No cities configured. Add a city first.", parse_mode=None,
                                 reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back to Admin Menu", callback_data="admin_menu")]]))
    sorted_city_ids = sorted(CITIES.keys(), key=lambda city_id: CITIES.get(city_id,''))
    keyboard = [[InlineKeyboardButton(f"🏙️ {CITIES.get(c,'N/A')}", callback_data=f"adm_manage_products_city|{c}")] for c in sorted_city_ids]
    keyboard.append([InlineKeyboardButton("⬅️ Back to Admin Menu", callback_data="admin_menu")])
    await query.edit_message_text("🗑️ Manage Products\n\nSelect the city where the products are located:",
                            reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=None)


async def handle_adm_manage_products_city(update: Update, context: ContextTypes.DEFAULT_TYPE, params=None):
    """Admin selects district to manage products in."""
    query = update.callback_query
    if query.from_user.id != ADMIN_ID: return await query.answer("Access denied.", show_alert=True)
    if not params: return await query.answer("Error: City ID missing.", show_alert=True)
    city_id = params[0]
    city_name = CITIES.get(city_id)
    if not city_name:
        return await query.edit_message_text("Error: City not found.", parse_mode=None)
    districts_in_city = DISTRICTS.get(city_id, {})
    if not districts_in_city:
         keyboard = [[InlineKeyboardButton("⬅️ Back to Cities", callback_data="adm_manage_products")]]
         return await query.edit_message_text(f"No districts found for {city_name}. Cannot manage products.",
                                 reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=None)
    sorted_district_ids = sorted(districts_in_city.keys(), key=lambda d_id: districts_in_city.get(d_id,''))
    keyboard = []
    for d in sorted_district_ids:
         dist_name = districts_in_city.get(d)
         if dist_name:
             keyboard.append([InlineKeyboardButton(f"🏘️ {dist_name}", callback_data=f"adm_manage_products_dist|{city_id}|{d}")])
         else: logger.warning(f"District name missing for ID {d} in city {city_id} (manage products)")
    keyboard.append([InlineKeyboardButton("⬅️ Back to Cities", callback_data="adm_manage_products")])
    await query.edit_message_text(f"🗑️ Manage Products in {city_name}\n\nSelect district:",
                            reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=None)


async def handle_adm_manage_products_dist(update: Update, context: ContextTypes.DEFAULT_TYPE, params=None):
    """Admin selects product type to manage within the district."""
    query = update.callback_query
    if query.from_user.id != ADMIN_ID: return await query.answer("Access denied.", show_alert=True)
    if not params or len(params) < 2: return await query.answer("Error: City/District ID missing.", show_alert=True)
    city_id, dist_id = params
    city_name = CITIES.get(city_id)
    district_name = DISTRICTS.get(city_id, {}).get(dist_id)
    if not city_name or not district_name:
        return await query.edit_message_text("Error: City/District not found.", parse_mode=None)
    conn = None # Initialize conn
    try:
        conn = get_db_connection() # Use helper
        c = conn.cursor()
        # Use column name
        c.execute("SELECT DISTINCT product_type FROM products WHERE city = ? AND district = ? ORDER BY product_type", (city_name, district_name))
        product_types_in_dist = sorted([row['product_type'] for row in c.fetchall()])
        if not product_types_in_dist:
             keyboard = [[InlineKeyboardButton("⬅️ Back to Districts", callback_data=f"adm_manage_products_city|{city_id}")]]
             return await query.edit_message_text(f"No product types found in {city_name} / {district_name}.",
                                     reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=None)
        keyboard = []
        for pt in product_types_in_dist:
             emoji = PRODUCT_TYPES.get(pt, DEFAULT_PRODUCT_EMOJI)
             keyboard.append([InlineKeyboardButton(f"{emoji} {pt}", callback_data=f"adm_manage_products_type|{city_id}|{dist_id}|{pt}")])

        keyboard.append([InlineKeyboardButton("⬅️ Back to Districts", callback_data=f"adm_manage_products_city|{city_id}")])
        await query.edit_message_text(f"🗑️ Manage Products in {city_name} / {district_name}\n\nSelect product type:",
                                reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=None)
    except sqlite3.Error as e:
        logger.error(f"DB error fetching product types for managing in {city_name}/{district_name}: {e}", exc_info=True)
        await query.edit_message_text("❌ Error fetching product types.", parse_mode=None)
    finally:
        if conn: conn.close() # Close connection if opened


async def handle_adm_manage_products_type(update: Update, context: ContextTypes.DEFAULT_TYPE, params=None):
    """Shows specific products of a type and allows deletion."""
    query = update.callback_query
    if query.from_user.id != ADMIN_ID: return await query.answer("Access denied.", show_alert=True)
    if not params or len(params) < 3: return await query.answer("Error: Location/Type info missing.", show_alert=True)
    city_id, dist_id, p_type = params
    city_name = CITIES.get(city_id)
    district_name = DISTRICTS.get(city_id, {}).get(dist_id)
    if not city_name or not district_name:
        return await query.edit_message_text("Error: City/District not found.", parse_mode=None)

    type_emoji = PRODUCT_TYPES.get(p_type, DEFAULT_PRODUCT_EMOJI)

    conn = None # Initialize conn
    try:
        conn = get_db_connection() # Use helper
        c = conn.cursor()
        # Use column names
        c.execute("""
            SELECT id, size, price, available, reserved, name
            FROM products WHERE city = ? AND district = ? AND product_type = ?
            ORDER BY size, price, id
        """, (city_name, district_name, p_type))
        products = c.fetchall()
        msg = f"🗑️ Products: {type_emoji} {p_type} in {city_name} / {district_name}\n\n"
        keyboard = []
        full_msg = msg # Initialize full message

        if not products:
            full_msg += "No products of this type found here."
        else:
             header = "ID | Size | Price | Status (Avail/Reserved)\n" + "----------------------------------------\n"
             full_msg += header
             items_text_list = []
             for prod in products:
                prod_id, size_str, price_str = prod['id'], prod['size'], format_currency(prod['price'])
                status_str = f"{prod['available']}/{prod['reserved']}"
                items_text_list.append(f"{prod_id} | {size_str} | {price_str}€ | {status_str}")
                keyboard.append([InlineKeyboardButton(f"🗑️ Delete ID {prod_id}", callback_data=f"adm_delete_prod|{prod_id}")])
             full_msg += "\n".join(items_text_list)

        keyboard.append([InlineKeyboardButton("⬅️ Back to Types", callback_data=f"adm_manage_products_dist|{city_id}|{dist_id}")])
        try:
            await query.edit_message_text(full_msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=None)
        except telegram_error.BadRequest as e:
             if "message is not modified" not in str(e).lower(): logger.error(f"Error editing manage products type: {e}.")
             else: await query.answer() # Acknowledge if not modified
    except sqlite3.Error as e:
        logger.error(f"DB error fetching products for deletion: {e}", exc_info=True)
        await query.edit_message_text("❌ Error fetching products.", parse_mode=None)
    finally:
        if conn: conn.close() # Close connection if opened


async def handle_adm_delete_prod(update: Update, context: ContextTypes.DEFAULT_TYPE, params=None):
    """Handles 'Delete Product' button press, shows confirmation."""
    query = update.callback_query
    if query.from_user.id != ADMIN_ID: return await query.answer("Access denied.", show_alert=True)
    if not params: return await query.answer("Error: Product ID missing.", show_alert=True)
    try: product_id = int(params[0])
    except ValueError: return await query.answer("Error: Invalid Product ID.", show_alert=True)
    product_name = f"Product ID {product_id}"
    product_details = ""
    back_callback = "adm_manage_products" # Default back location
    conn = None # Initialize conn
    try:
        conn = get_db_connection() # Use helper
        c = conn.cursor()
        # Use column names
        c.execute("""
            SELECT p.name, p.city, p.district, p.product_type, p.size, p.price, ci.id as city_id, di.id as dist_id
            FROM products p LEFT JOIN cities ci ON p.city = ci.name
            LEFT JOIN districts di ON p.district = di.name AND ci.id = di.city_id
            WHERE p.id = ?
        """, (product_id,))
        result = c.fetchone()
        if result:
            type_name = result['product_type']
            emoji = PRODUCT_TYPES.get(type_name, DEFAULT_PRODUCT_EMOJI)
            product_name = result['name'] or product_name
            product_details = f"{emoji} {type_name} {result['size']} ({format_currency(result['price'])}€) in {result['city']}/{result['district']}"
            if result['city_id'] and result['dist_id'] and result['product_type']:
                back_callback = f"adm_manage_products_type|{result['city_id']}|{result['dist_id']}|{result['product_type']}"
            else: logger.warning(f"Could not retrieve full details for product {product_id} during delete confirmation.")
        else:
            return await query.edit_message_text("Error: Product not found.", parse_mode=None)
    except sqlite3.Error as e:
         logger.warning(f"Could not fetch full details for product {product_id} for delete confirmation: {e}")
    finally:
        if conn: conn.close() # Close connection if opened

    context.user_data["confirm_action"] = f"confirm_remove_product|{product_id}"
    msg = (f"⚠️ Confirm Deletion\n\nAre you sure you want to permanently delete this specific product instance?\n"
           f"Product ID: {product_id}\nDetails: {product_details}\n\n🚨 This action is irreversible!")
    keyboard = [[InlineKeyboardButton("✅ Yes, Delete Product", callback_data="confirm_yes"),
                 InlineKeyboardButton("❌ No, Cancel", callback_data=back_callback)]] # Use dynamic back callback
    await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=None)


# --- Manage Product Types Handlers ---
async def handle_adm_manage_types(update: Update, context: ContextTypes.DEFAULT_TYPE, params=None):
    """Shows options to manage product types (edit emoji, delete)."""
    query = update.callback_query
    if query.from_user.id != ADMIN_ID: return await query.answer("Access denied.", show_alert=True)
    load_all_data() # Ensure PRODUCT_TYPES is up-to-date
    if not PRODUCT_TYPES: msg = "🧩 Manage Product Types\n\nNo product types configured."
    else: msg = "🧩 Manage Product Types\n\nSelect a type to edit or delete:"
    keyboard = []
    for type_name, emoji in sorted(PRODUCT_TYPES.items()):
         keyboard.append([
             InlineKeyboardButton(f"{emoji} {type_name}", callback_data=f"adm_edit_type_menu|{type_name}"),
             InlineKeyboardButton(f"🗑️ Delete", callback_data=f"adm_delete_type|{type_name}")
         ])
    keyboard.extend([
        [InlineKeyboardButton("➕ Add New Type", callback_data="adm_add_type")],
        [InlineKeyboardButton("⬅️ Back to Admin Menu", callback_data="admin_menu")]
    ])
    await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=None)

# --- Edit Type Menu ---
async def handle_adm_edit_type_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, params=None):
    """Shows options for a specific product type: change emoji, edit description, or delete."""
    query = update.callback_query
    lang, lang_data = _get_lang_data(context) # Use helper
    if query.from_user.id != ADMIN_ID: return await query.answer("Access Denied.", show_alert=True)
    if not params: return await query.answer("Error: Type name missing.", show_alert=True)

    type_name = params[0]
    current_emoji = PRODUCT_TYPES.get(type_name, DEFAULT_PRODUCT_EMOJI)

    # Fetch current description
    current_description = ""
    conn = None
    try:
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("SELECT description FROM product_types WHERE name = ?", (type_name,))
        res = c.fetchone()
        if res: current_description = res['description'] or "(Description not set)"
        else: current_description = "(Type not found in DB)"
    except sqlite3.Error as e:
        logger.error(f"Error fetching description for type {type_name}: {e}")
        current_description = "(DB Error fetching description)"
    finally:
        if conn: conn.close()


    safe_name = type_name # No Markdown V2 here
    safe_desc = current_description # No Markdown V2 here

    msg_template = lang_data.get("admin_edit_type_menu", "🧩 Editing Type: {type_name}\n\nCurrent Emoji: {emoji}\nDescription: {description}\n\nWhat would you like to do?")
    msg = msg_template.format(type_name=safe_name, emoji=current_emoji, description=safe_desc)

    change_emoji_button_text = lang_data.get("admin_edit_type_emoji_button", "✏️ Change Emoji")
    change_desc_button_text = lang_data.get("admin_edit_type_desc_button", "📝 Edit Description") # Keep commented out

    keyboard = [
        [InlineKeyboardButton(change_emoji_button_text, callback_data=f"adm_change_type_emoji|{type_name}")],
        # [InlineKeyboardButton(change_desc_button_text, callback_data=f"adm_edit_type_desc|{type_name}")], # Description editing for types not implemented
        [InlineKeyboardButton(f"🗑️ Delete {type_name}", callback_data=f"adm_delete_type|{type_name}")],
        [InlineKeyboardButton("⬅️ Back to Types", callback_data="adm_manage_types")]
    ]

    try:
        await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=None)
    except telegram_error.BadRequest as e:
        if "message is not modified" in str(e).lower(): await query.answer()
        else:
            logger.error(f"Error editing type menu: {e}. Message: {msg}")
            await query.answer("Error displaying menu.", show_alert=True)

# --- Change Type Emoji Prompt ---
async def handle_adm_change_type_emoji(update: Update, context: ContextTypes.DEFAULT_TYPE, params=None):
    """Handles 'Change Emoji' button press."""
    query = update.callback_query
    lang, lang_data = _get_lang_data(context) # Use helper
    if query.from_user.id != ADMIN_ID: return await query.answer("Access denied.", show_alert=True)
    if not params: return await query.answer("Error: Type name missing.", show_alert=True)
    type_name = params[0]

    context.user_data["state"] = "awaiting_edit_type_emoji"
    context.user_data["edit_type_name"] = type_name
    current_emoji = PRODUCT_TYPES.get(type_name, DEFAULT_PRODUCT_EMOJI)

    prompt_text = lang_data.get("admin_enter_type_emoji", "✍️ Please reply with a single emoji for the product type:")
    keyboard = [[InlineKeyboardButton("❌ Cancel", callback_data=f"adm_edit_type_menu|{type_name}")]]
    await query.edit_message_text(f"Current Emoji: {current_emoji}\n\n{prompt_text}", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=None)
    await query.answer("Enter new emoji in chat.")

# --- Add Type asks for name first ---
async def handle_adm_add_type(update: Update, context: ContextTypes.DEFAULT_TYPE, params=None):
    """Handles 'Add New Type' button press - asks for name first."""
    query = update.callback_query
    if query.from_user.id != ADMIN_ID: return await query.answer("Access denied.", show_alert=True)
    context.user_data["state"] = "awaiting_new_type_name"
    keyboard = [[InlineKeyboardButton("❌ Cancel", callback_data="adm_manage_types")]]
    await query.edit_message_text("🧩 Please reply with the name for the new product type:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=None)
    await query.answer("Enter type name in chat.")

async def handle_adm_delete_type(update: Update, context: ContextTypes.DEFAULT_TYPE, params=None):
    """Handles 'Delete Type' button, checks usage, shows confirmation."""
    query = update.callback_query
    if query.from_user.id != ADMIN_ID: return await query.answer("Access denied.", show_alert=True)
    if not params: return await query.answer("Error: Type name missing.", show_alert=True)
    type_name = params[0]
    conn = None # Initialize conn
    try:
        conn = get_db_connection() # Use helper
        c = conn.cursor()
        # Check products table
        c.execute("SELECT COUNT(*) FROM products WHERE product_type = ?", (type_name,))
        product_count = c.fetchone()[0]
        # <<< ADDED: Check reseller_discounts table >>>
        c.execute("SELECT COUNT(*) FROM reseller_discounts WHERE product_type = ?", (type_name,))
        reseller_discount_count = c.fetchone()[0]
        # <<< END ADDED >>>

        if product_count > 0 or reseller_discount_count > 0: # Check both counts
            error_msg_parts = []
            if product_count > 0: error_msg_parts.append(f"{product_count} product(s)")
            if reseller_discount_count > 0: error_msg_parts.append(f"{reseller_discount_count} reseller discount rule(s)")
            usage_details = " and ".join(error_msg_parts)

            keyboard = [[InlineKeyboardButton("⬅️ Back", callback_data="adm_manage_types")]]
            await query.edit_message_text(f"⚠️ Cannot Delete Type\n\nType {type_name} is currently used by {usage_details}. Please delete or reassign those first.",
                                    reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=None)
        else:
            context.user_data["confirm_action"] = f"delete_type|{type_name}"
            msg = (f"⚠️ Confirm Deletion\n\nAre you sure you want to delete product type: {type_name}?\n\n"
                   f"🚨 This action is irreversible!")
            keyboard = [[InlineKeyboardButton("✅ Yes, Delete Type", callback_data="confirm_yes"),
                         InlineKeyboardButton("❌ No, Cancel", callback_data="adm_manage_types")]]
            await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=None)
    except sqlite3.Error as e:
        logger.error(f"DB error checking product type usage for '{type_name}': {e}", exc_info=True)
        await query.edit_message_text("❌ Error checking type usage.", parse_mode=None)
    finally:
        if conn: conn.close() # Close connection if opened


# --- Discount Handlers ---
async def handle_adm_manage_discounts(update: Update, context: ContextTypes.DEFAULT_TYPE, params=None):
    """Displays existing discount codes and management options."""
    query = update.callback_query
    if query.from_user.id != ADMIN_ID: return await query.answer("Access Denied.", show_alert=True)
    conn = None # Initialize conn
    try:
        conn = get_db_connection() # Use helper
        c = conn.cursor()
        c.execute("""
            SELECT id, code, discount_type, value, is_active, max_uses, uses_count, expiry_date
            FROM discount_codes ORDER BY created_date DESC
        """)
        codes = c.fetchall()
        msg = "🏷️ Manage General Discount Codes\n\n" # Clarified title
        keyboard = []
        if not codes: msg += "No general discount codes found."
        else:
            for code in codes: # Access by column name
                status = "✅ Active" if code['is_active'] else "❌ Inactive"
                value_str = format_discount_value(code['discount_type'], code['value'])
                usage_limit = f"/{code['max_uses']}" if code['max_uses'] is not None else "/∞"
                usage = f"{code['uses_count']}{usage_limit}"
                expiry_info = ""
                if code['expiry_date']:
                     try:
                         # Ensure stored date is treated as UTC before comparison
                         expiry_dt = datetime.fromisoformat(code['expiry_date']).replace(tzinfo=timezone.utc)
                         expiry_info = f" | Expires: {expiry_dt.strftime('%Y-%m-%d')}"
                         # Compare with current UTC time
                         if datetime.now(timezone.utc) > expiry_dt and code['is_active']: status = "⏳ Expired"
                     except ValueError: expiry_info = " | Invalid Date"
                toggle_text = "Deactivate" if code['is_active'] else "Activate"
                delete_text = "🗑️ Delete"
                code_text = code['code']
                msg += f"`{code_text}` ({value_str} {code['discount_type']}) | {status} | Used: {usage}{expiry_info}\n" # Use markdown for code
                keyboard.append([
                    InlineKeyboardButton(f"{'❌' if code['is_active'] else '✅'} {toggle_text}", callback_data=f"adm_toggle_discount|{code['id']}"),
                    InlineKeyboardButton(f"{delete_text}", callback_data=f"adm_delete_discount|{code['id']}")
                ])
        keyboard.extend([
            [InlineKeyboardButton("➕ Add New General Discount", callback_data="adm_add_discount_start")],
            [InlineKeyboardButton("⬅️ Back to Admin Menu", callback_data="admin_menu")]
        ])
        try:
             # Use MarkdownV2 for code formatting
            await query.edit_message_text(helpers.escape_markdown(msg, version=2), reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN_V2)
        except telegram_error.BadRequest as e:
             if "message is not modified" not in str(e).lower():
                 logger.error(f"Error editing discount list (MarkdownV2): {e}. Falling back to plain.")
                 try:
                     # Fallback to plain text
                     plain_msg = msg.replace('`', '') # Simple removal
                     await query.edit_message_text(plain_msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=None)
                 except Exception as fallback_e:
                     logger.error(f"Error editing discount list (Fallback): {fallback_e}")
                     await query.answer("Error updating list.", show_alert=True)
             else: await query.answer() # Ignore not modified
    except sqlite3.Error as e:
        logger.error(f"DB error loading discount codes: {e}", exc_info=True)
        await query.edit_message_text("❌ Error loading discount codes.", parse_mode=None)
    except Exception as e:
         logger.error(f"Unexpected error managing discounts: {e}", exc_info=True)
         await query.edit_message_text("❌ An unexpected error occurred.", parse_mode=None)
    finally:
        if conn: conn.close() # Close connection if opened


async def handle_adm_toggle_discount(update: Update, context: ContextTypes.DEFAULT_TYPE, params=None):
    """Activates or deactivates a specific discount code."""
    query = update.callback_query
    if query.from_user.id != ADMIN_ID: return await query.answer("Access Denied.", show_alert=True)
    if not params: return await query.answer("Error: Code ID missing.", show_alert=True)
    conn = None # Initialize conn
    try:
        code_id = int(params[0])
        conn = get_db_connection() # Use helper
        c = conn.cursor()
        c.execute("SELECT is_active FROM discount_codes WHERE id = ?", (code_id,))
        result = c.fetchone()
        if not result: return await query.answer("Code not found.", show_alert=True)
        current_status = result['is_active']
        new_status = 0 if current_status == 1 else 1
        c.execute("UPDATE discount_codes SET is_active = ? WHERE id = ?", (new_status, code_id))
        conn.commit()
        action = 'deactivated' if new_status == 0 else 'activated'
        logger.info(f"Admin {query.from_user.id} {action} discount code ID {code_id}.")
        await query.answer(f"Code {action} successfully.")
        await handle_adm_manage_discounts(update, context) # Refresh list
    except (sqlite3.Error, ValueError) as e:
        logger.error(f"Error toggling discount code {params[0]}: {e}", exc_info=True)
        await query.answer("Error updating code status.", show_alert=True)
    finally:
        if conn: conn.close() # Close connection if opened


async def handle_adm_delete_discount(update: Update, context: ContextTypes.DEFAULT_TYPE, params=None):
    """Handles delete button press for discount code, shows confirmation."""
    query = update.callback_query
    if query.from_user.id != ADMIN_ID: return await query.answer("Access Denied.", show_alert=True)
    if not params: return await query.answer("Error: Code ID missing.", show_alert=True)
    conn = None # Initialize conn
    try:
        code_id = int(params[0])
        conn = get_db_connection() # Use helper
        c = conn.cursor()
        c.execute("SELECT code FROM discount_codes WHERE id = ?", (code_id,))
        result = c.fetchone()
        if not result: return await query.answer("Code not found.", show_alert=True)
        code_text = result['code']
        context.user_data["confirm_action"] = f"delete_discount|{code_id}"
        msg = (f"⚠️ Confirm Deletion\n\nAre you sure you want to permanently delete discount code: `{helpers.escape_markdown(code_text, version=2)}`?\n\n"
               f"🚨 This action is irreversible!")
        keyboard = [[InlineKeyboardButton("✅ Yes, Delete Code", callback_data="confirm_yes"),
                     InlineKeyboardButton("❌ No, Cancel", callback_data="adm_manage_discounts")]]
        await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN_V2)
    except (sqlite3.Error, ValueError) as e:
        logger.error(f"Error preparing delete confirmation for discount code {params[0]}: {e}", exc_info=True)
        await query.answer("Error fetching code details.", show_alert=True)
    except telegram_error.BadRequest as e_tg:
         # Fallback if Markdown fails
         logger.warning(f"Markdown error displaying delete confirm: {e_tg}. Falling back.")
         msg_plain = msg.replace('`', '') # Simple removal
         await query.edit_message_text(msg_plain, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=None)
    finally:
        if conn: conn.close() # Close connection if opened


async def handle_adm_add_discount_start(update: Update, context: ContextTypes.DEFAULT_TYPE, params=None):
    """Starts the process of adding a new discount code."""
    query = update.callback_query
    if query.from_user.id != ADMIN_ID: return await query.answer("Access Denied.", show_alert=True)
    context.user_data['state'] = 'awaiting_discount_code'
    context.user_data['new_discount_info'] = {} # Initialize dict
    random_code = secrets.token_urlsafe(8).upper().replace('-', '').replace('_', '')[:8]
    keyboard = [
        [InlineKeyboardButton(f"Use Generated: {random_code}", callback_data=f"adm_use_generated_code|{random_code}")],
        [InlineKeyboardButton("❌ Cancel", callback_data="adm_manage_discounts")]
    ]
    await query.edit_message_text(
        "🏷️ Add New General Discount Code\n\nPlease reply with the code text you want to use (e.g., SUMMER20), or use the generated one below.\n"
        "Codes are case-sensitive.",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=None
    )
    await query.answer("Enter code text or use generated.")


async def handle_adm_use_generated_code(update: Update, context: ContextTypes.DEFAULT_TYPE, params=None):
    """Handles using the suggested random code."""
    query = update.callback_query
    if query.from_user.id != ADMIN_ID: return await query.answer("Access Denied.", show_alert=True)
    if not params: return await query.answer("Error: Generated code missing.", show_alert=True)
    code_text = params[0]
    await process_discount_code_input(update, context, code_text) # This function will handle message editing


async def handle_adm_set_discount_type(update: Update, context: ContextTypes.DEFAULT_TYPE, params=None):
    """Sets the discount type and asks for the value."""
    query = update.callback_query
    if query.from_user.id != ADMIN_ID: return await query.answer("Access Denied.", show_alert=True)
    if not params: return await query.answer("Error: Discount type missing.", show_alert=True)
    current_state = context.user_data.get("state")
    if current_state not in ['awaiting_discount_type', 'awaiting_discount_code']: # Check if state is valid
         logger.warning(f"handle_adm_set_discount_type called in wrong state: {current_state}")
         if context.user_data and 'new_discount_info' in context.user_data and 'code' in context.user_data['new_discount_info']:
             context.user_data['state'] = 'awaiting_discount_type'
             logger.info("Forcing state back to awaiting_discount_type")
         else:
             return await handle_adm_manage_discounts(update, context)

    discount_type = params[0]
    if discount_type not in ['percentage', 'fixed']:
        return await query.answer("Invalid discount type.", show_alert=True)
    if 'new_discount_info' not in context.user_data: context.user_data['new_discount_info'] = {}
    context.user_data['new_discount_info']['type'] = discount_type
    context.user_data['state'] = 'awaiting_discount_value'
    value_prompt = ("Enter the percentage value (e.g., 10 for 10%):" if discount_type == 'percentage' else
                    "Enter the fixed discount amount in EUR (e.g., 5.50):")
    code_text = context.user_data.get('new_discount_info', {}).get('code', 'N/A')
    msg = f"Code: {code_text} | Type: {discount_type.capitalize()}\n\n{value_prompt}"
    keyboard = [[InlineKeyboardButton("❌ Cancel", callback_data="adm_manage_discounts")]]
    try:
        await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=None)
        await query.answer("Enter the discount value.")
    except telegram_error.BadRequest as e:
        if "message is not modified" not in str(e).lower():
             logger.error(f"Error editing message in handle_adm_set_discount_type: {e}. Message: {msg}")
             await query.answer("Error updating prompt. Please try again.", show_alert=True)
        else: await query.answer()

# --- Set Bot Media Handlers ---
async def handle_adm_set_media(update: Update, context: ContextTypes.DEFAULT_TYPE, params=None):
    """Handles 'Set Bot Media' button press."""
    query = update.callback_query
    if query.from_user.id != ADMIN_ID: return await query.answer("Access denied.", show_alert=True)
    lang, lang_data = _get_lang_data(context) # Use helper
    set_media_prompt_text = lang_data.get("set_media_prompt_plain", "Send a photo, video, or GIF to display above all messages:")
    context.user_data["state"] = "awaiting_bot_media"
    keyboard = [[InlineKeyboardButton("❌ Cancel", callback_data="admin_menu")]]
    await query.edit_message_text(set_media_prompt_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=None)
    await query.answer("Send photo, video, or GIF.")


# --- Review Management Handlers ---
async def handle_adm_manage_reviews(update: Update, context: ContextTypes.DEFAULT_TYPE, params=None):
    """Displays reviews paginated for the admin with delete options."""
    query = update.callback_query
    user_id = query.from_user.id
    is_primary_admin = (user_id == ADMIN_ID)
    is_secondary_admin = (user_id in SECONDARY_ADMIN_IDS)
    if not is_primary_admin and not is_secondary_admin: return await query.answer("Access Denied.", show_alert=True)
    offset = 0
    if params and len(params) > 0 and params[0].isdigit(): offset = int(params[0])
    reviews_per_page = 5
    reviews_data = fetch_reviews(offset=offset, limit=reviews_per_page + 1) # Sync function uses helper
    msg = "🚫 Manage Reviews\n\n"
    keyboard = []
    item_buttons = []
    if not reviews_data:
        if offset == 0: msg += "No reviews have been left yet."
        else: msg += "No more reviews to display."
    else:
        has_more = len(reviews_data) > reviews_per_page
        reviews_to_show = reviews_data[:reviews_per_page]
        for review in reviews_to_show:
            review_id = review.get('review_id', 'N/A')
            try:
                date_str = review.get('review_date', '')
                formatted_date = "???"
                if date_str:
                    try: formatted_date = datetime.fromisoformat(date_str.replace('Z','+00:00')).strftime("%Y-%m-%d") # Handle Z for UTC
                    except ValueError: pass
                username = review.get('username', 'anonymous')
                username_display = f"@{username}" if username and username != 'anonymous' else username
                review_text = review.get('review_text', '')
                review_text_preview = review_text[:100] + ('...' if len(review_text) > 100 else '')
                msg += f"ID {review_id} | {username_display} ({formatted_date}):\n{review_text_preview}\n\n"
                if is_primary_admin: # Only primary admin can delete
                     item_buttons.append([InlineKeyboardButton(f"🗑️ Delete Review #{review_id}", callback_data=f"adm_delete_review_confirm|{review_id}")])
            except Exception as e:
                 logger.error(f"Error formatting review item #{review_id} for admin view: {review}, Error: {e}")
                 msg += f"ID {review_id} | (Error displaying review)\n\n"
                 if is_primary_admin: item_buttons.append([InlineKeyboardButton(f"🗑️ Delete Review #{review_id}", callback_data=f"adm_delete_review_confirm|{review_id}")])
        keyboard.extend(item_buttons)
        nav_buttons = []
        if offset > 0: nav_buttons.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"adm_manage_reviews|{max(0, offset - reviews_per_page)}"))
        if has_more: nav_buttons.append(InlineKeyboardButton("➡️ Next", callback_data=f"adm_manage_reviews|{offset + reviews_per_page}"))
        if nav_buttons: keyboard.append(nav_buttons)
    back_callback = "admin_menu" if is_primary_admin else "viewer_admin_menu"
    keyboard.append([InlineKeyboardButton("⬅️ Back to Admin Menu", callback_data=back_callback)])
    try:
        await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=None)
    except telegram_error.BadRequest as e:
        if "message is not modified" not in str(e).lower():
            logger.warning(f"Failed to edit message for adm_manage_reviews: {e}"); await query.answer("Error updating review list.", show_alert=True)
        else:
            await query.answer() # Acknowledge if not modified
    except Exception as e:
        logger.error(f"Unexpected error in adm_manage_reviews: {e}", exc_info=True)
        await query.edit_message_text("❌ An unexpected error occurred while loading reviews.", parse_mode=None)


async def handle_adm_delete_review_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE, params=None):
    """Handles 'Delete Review' button press, shows confirmation."""
    query = update.callback_query
    user_id = query.from_user.id
    if user_id != ADMIN_ID: return await query.answer("Access denied.", show_alert=True)
    if not params: return await query.answer("Error: Review ID missing.", show_alert=True)
    try: review_id = int(params[0])
    except ValueError: return await query.answer("Error: Invalid Review ID.", show_alert=True)
    review_text_snippet = "N/A"
    conn = None # Initialize conn
    try:
        conn = get_db_connection() # Use helper
        c = conn.cursor()
        # Use column name
        c.execute("SELECT review_text FROM reviews WHERE review_id = ?", (review_id,))
        result = c.fetchone()
        if result: review_text_snippet = result['review_text'][:100]
        else:
            await query.answer("Review not found.", show_alert=True)
            try: await query.edit_message_text("Error: Review not found.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back to Reviews", callback_data="adm_manage_reviews|0")]]), parse_mode=None)
            except telegram_error.BadRequest: pass
            return
    except sqlite3.Error as e: logger.warning(f"Could not fetch review text for confirmation (ID {review_id}): {e}")
    finally:
        if conn: conn.close() # Close connection if opened
    context.user_data["confirm_action"] = f"delete_review|{review_id}"
    msg = (f"⚠️ Confirm Deletion\n\nAre you sure you want to permanently delete review ID {review_id}?\n\n"
           f"Preview: {review_text_snippet}{'...' if len(review_text_snippet) >= 100 else ''}\n\n"
           f"🚨 This action is irreversible!")
    keyboard = [[InlineKeyboardButton("✅ Yes, Delete Review", callback_data="confirm_yes"),
                 InlineKeyboardButton("❌ No, Cancel", callback_data="adm_manage_reviews|0")]]
    await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=None)


# --- Broadcast Handlers ---

async def handle_adm_broadcast_start(update: Update, context: ContextTypes.DEFAULT_TYPE, params=None):
    """Starts the broadcast message process by asking for the target audience."""
    query = update.callback_query
    if query.from_user.id != ADMIN_ID: return await query.answer("Access Denied.", show_alert=True)

    lang, lang_data = _get_lang_data(context) # Use helper

    # Clear previous broadcast data
    context.user_data.pop('broadcast_content', None)
    context.user_data.pop('broadcast_target_type', None)
    context.user_data.pop('broadcast_target_value', None)

    prompt_msg = lang_data.get("broadcast_select_target", "📢 Broadcast Message\n\nSelect the target audience:")
    keyboard = [
        [InlineKeyboardButton(lang_data.get("broadcast_target_all", "👥 All Users"), callback_data="adm_broadcast_target_type|all")],
        [InlineKeyboardButton(lang_data.get("broadcast_target_city", "🏙️ By Last Purchased City"), callback_data="adm_broadcast_target_type|city")],
        [InlineKeyboardButton(lang_data.get("broadcast_target_status", "👑 By User Status"), callback_data="adm_broadcast_target_type|status")],
        [InlineKeyboardButton(lang_data.get("broadcast_target_inactive", "⏳ By Inactivity (Days)"), callback_data="adm_broadcast_target_type|inactive")],
        [InlineKeyboardButton("❌ Cancel", callback_data="admin_menu")]
    ]
    await query.edit_message_text(prompt_msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=None)
    await query.answer()


async def handle_adm_broadcast_target_type(update: Update, context: ContextTypes.DEFAULT_TYPE, params=None):
    """Handles the selection of the broadcast target type."""
    query = update.callback_query
    if query.from_user.id != ADMIN_ID: return await query.answer("Access Denied.", show_alert=True)
    if not params: return await query.answer("Error: Target type missing.", show_alert=True)

    target_type = params[0]
    context.user_data['broadcast_target_type'] = target_type
    lang, lang_data = _get_lang_data(context) # Use helper

    if target_type == 'all':
        context.user_data['state'] = 'awaiting_broadcast_message'
        ask_msg_text = lang_data.get("broadcast_ask_message", "📝 Now send the message content (text, photo, video, or GIF with caption):")
        keyboard = [[InlineKeyboardButton("❌ Cancel Broadcast", callback_data="cancel_broadcast")]]
        await query.edit_message_text(ask_msg_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=None)
        await query.answer("Send the message content.")

    elif target_type == 'city':
        load_all_data()
        if not CITIES:
             await query.edit_message_text("No cities configured. Cannot target by city.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="adm_broadcast_start")]]), parse_mode=None)
             return
        sorted_city_ids = sorted(CITIES.keys(), key=lambda city_id: CITIES.get(city_id, ''))
        keyboard = [[InlineKeyboardButton(f"🏙️ {CITIES.get(c,'N/A')}", callback_data=f"adm_broadcast_target_city|{CITIES.get(c,'N/A')}")] for c in sorted_city_ids if CITIES.get(c)]
        keyboard.append([InlineKeyboardButton("❌ Cancel Broadcast", callback_data="cancel_broadcast")])
        select_city_text = lang_data.get("broadcast_select_city_target", "🏙️ Select City to Target\n\nUsers whose last purchase was in:")
        await query.edit_message_text(select_city_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=None)
        await query.answer()

    elif target_type == 'status':
        select_status_text = lang_data.get("broadcast_select_status_target", "👑 Select Status to Target:")
        vip_label = lang_data.get("broadcast_status_vip", "VIP 👑")
        regular_label = lang_data.get("broadcast_status_regular", "Regular ⭐")
        new_label = lang_data.get("broadcast_status_new", "New 🌱")
        keyboard = [
            [InlineKeyboardButton(vip_label, callback_data=f"adm_broadcast_target_status|{vip_label}")],
            [InlineKeyboardButton(regular_label, callback_data=f"adm_broadcast_target_status|{regular_label}")],
            [InlineKeyboardButton(new_label, callback_data=f"adm_broadcast_target_status|{new_label}")],
            [InlineKeyboardButton("❌ Cancel Broadcast", callback_data="cancel_broadcast")]
        ]
        await query.edit_message_text(select_status_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=None)
        await query.answer()

    elif target_type == 'inactive':
        context.user_data['state'] = 'awaiting_broadcast_inactive_days'
        inactive_prompt = lang_data.get("broadcast_enter_inactive_days", "⏳ Enter Inactivity Period\n\nPlease reply with the number of days since the user's last purchase (or since registration if no purchases). Users inactive for this many days or more will receive the message.")
        keyboard = [[InlineKeyboardButton("❌ Cancel Broadcast", callback_data="cancel_broadcast")]]
        await query.edit_message_text(inactive_prompt, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=None)
        await query.answer("Enter number of days.")

    else:
        await query.answer("Unknown target type selected.", show_alert=True)
        await handle_adm_broadcast_start(update, context)


async def handle_adm_broadcast_target_city(update: Update, context: ContextTypes.DEFAULT_TYPE, params=None):
    """Handles selecting the city for targeted broadcast."""
    query = update.callback_query
    if query.from_user.id != ADMIN_ID: return await query.answer("Access Denied.", show_alert=True)
    if not params: return await query.answer("Error: City name missing.", show_alert=True)

    city_name = params[0]
    context.user_data['broadcast_target_value'] = city_name
    lang, lang_data = _get_lang_data(context) # Use helper

    context.user_data['state'] = 'awaiting_broadcast_message'
    ask_msg_text = lang_data.get("broadcast_ask_message", "📝 Now send the message content (text, photo, video, or GIF with caption):")
    keyboard = [[InlineKeyboardButton("❌ Cancel Broadcast", callback_data="cancel_broadcast")]]
    await query.edit_message_text(f"Targeting users last purchased in: {city_name}\n\n{ask_msg_text}", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=None)
    await query.answer("Send the message content.")

async def handle_adm_broadcast_target_status(update: Update, context: ContextTypes.DEFAULT_TYPE, params=None):
    """Handles selecting the status for targeted broadcast."""
    query = update.callback_query
    if query.from_user.id != ADMIN_ID: return await query.answer("Access Denied.", show_alert=True)
    if not params: return await query.answer("Error: Status value missing.", show_alert=True)

    status_value = params[0]
    context.user_data['broadcast_target_value'] = status_value
    lang, lang_data = _get_lang_data(context) # Use helper

    context.user_data['state'] = 'awaiting_broadcast_message'
    ask_msg_text = lang_data.get("broadcast_ask_message", "📝 Now send the message content (text, photo, video, or GIF with caption):")
    keyboard = [[InlineKeyboardButton("❌ Cancel Broadcast", callback_data="cancel_broadcast")]]
    await query.edit_message_text(f"Targeting users with status: {status_value}\n\n{ask_msg_text}", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=None)
    await query.answer("Send the message content.")


async def handle_confirm_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE, params=None):
    """Handles the 'Yes' confirmation for the broadcast."""
    query = update.callback_query
    if query.from_user.id != ADMIN_ID: return await query.answer("Access Denied.", show_alert=True)

    broadcast_content = context.user_data.get('broadcast_content')
    if not broadcast_content:
        logger.error("Broadcast content not found during confirmation.")
        return await query.edit_message_text("❌ Error: Broadcast content not found. Please start again.", parse_mode=None)

    text = broadcast_content.get('text')
    media_file_id = broadcast_content.get('media_file_id')
    media_type = broadcast_content.get('media_type')
    target_type = broadcast_content.get('target_type', 'all')
    target_value = broadcast_content.get('target_value')
    admin_chat_id = query.message.chat_id

    try:
        await query.edit_message_text("⏳ Broadcast initiated. Fetching users and sending messages...", parse_mode=None)
    except telegram_error.BadRequest: await query.answer()

    context.user_data.pop('broadcast_target_type', None)
    context.user_data.pop('broadcast_target_value', None)
    context.user_data.pop('broadcast_content', None)

    asyncio.create_task(send_broadcast(context, text, media_file_id, media_type, target_type, target_value, admin_chat_id))


async def handle_cancel_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE, params=None):
    """Cancels the broadcast process."""
    query = update.callback_query
    if query.from_user.id != ADMIN_ID: return await query.answer("Access Denied.", show_alert=True)

    context.user_data.pop('state', None)
    context.user_data.pop('broadcast_content', None)
    context.user_data.pop('broadcast_target_type', None)
    context.user_data.pop('broadcast_target_value', None)

    try:
        await query.edit_message_text("❌ Broadcast cancelled.", parse_mode=None)
    except telegram_error.BadRequest: await query.answer()

    keyboard = [[InlineKeyboardButton("⬅️ Back to Admin Menu", callback_data="admin_menu")]]
    await send_message_with_retry(context.bot, query.message.chat_id, "Returning to Admin Menu.", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=None)

async def send_broadcast(context: ContextTypes.DEFAULT_TYPE, text: str, media_file_id: str | None, media_type: str | None, target_type: str, target_value: str | int | None, admin_chat_id: int):
    """Sends the broadcast message to the target audience."""
    bot = context.bot
    lang_data = LANGUAGES.get('en', {}) # Use English for internal messages

    user_ids = await asyncio.to_thread(fetch_user_ids_for_broadcast, target_type, target_value)

    if not user_ids:
        logger.warning(f"No users found for broadcast target: type={target_type}, value={target_value}")
        no_users_msg = lang_data.get("broadcast_no_users_found_target", "⚠️ Broadcast Warning: No users found matching the target criteria.")
        await send_message_with_retry(bot, admin_chat_id, no_users_msg, parse_mode=None)
        return

    success_count, fail_count, block_count, total_users = 0, 0, 0, len(user_ids)
    logger.info(f"Starting broadcast to {total_users} users (Target: {target_type}={target_value})...")

    status_message = None
    status_update_interval = max(10, total_users // 20)

    try:
        status_message = await send_message_with_retry(bot, admin_chat_id, f"⏳ Broadcasting... (0/{total_users})", parse_mode=None)

        for i, user_id in enumerate(user_ids):
            try:
                send_kwargs = {'chat_id': user_id, 'caption': text, 'parse_mode': None}
                if media_file_id and media_type == "photo": await bot.send_photo(photo=media_file_id, **send_kwargs)
                elif media_file_id and media_type == "video": await bot.send_video(video=media_file_id, **send_kwargs)
                elif media_file_id and media_type == "gif": await bot.send_animation(animation=media_file_id, **send_kwargs)
                else: await bot.send_message(chat_id=user_id, text=text, parse_mode=None, disable_web_page_preview=True)
                success_count += 1
            except telegram_error.BadRequest as e:
                 error_str = str(e).lower()
                 if "chat not found" in error_str or "user is deactivated" in error_str or "bot was blocked" in error_str:
                      logger.warning(f"Broadcast fail/block for user {user_id}: {e}")
                      fail_count += 1; block_count += 1
                 else: logger.error(f"Broadcast BadRequest for {user_id}: {e}"); fail_count += 1
            except telegram_error.Unauthorized: logger.info(f"Broadcast skipped for {user_id}: Bot blocked."); fail_count += 1; block_count += 1
            except telegram_error.RetryAfter as e:
                 retry_seconds = e.retry_after + 1
                 logger.warning(f"Rate limit hit during broadcast. Sleeping {retry_seconds}s.")
                 if retry_seconds > 300: logger.error(f"RetryAfter > 5 min. Aborting for {user_id}."); fail_count += 1; continue
                 await asyncio.sleep(retry_seconds)
                 try: # Retry send after sleep
                     send_kwargs = {'chat_id': user_id, 'caption': text, 'parse_mode': None}
                     if media_file_id and media_type == "photo": await bot.send_photo(photo=media_file_id, **send_kwargs)
                     elif media_file_id and media_type == "video": await bot.send_video(video=media_file_id, **send_kwargs)
                     elif media_file_id and media_type == "gif": await bot.send_animation(animation=media_file_id, **send_kwargs)
                     else: await bot.send_message(chat_id=user_id, text=text, parse_mode=None, disable_web_page_preview=True)
                     success_count += 1
                 except Exception as retry_e: logger.error(f"Broadcast fail after retry for {user_id}: {retry_e}"); fail_count += 1;
                 if isinstance(retry_e, (telegram_error.Unauthorized, telegram_error.BadRequest)): block_count +=1 # Count as blocked if retry fails with these
            except Exception as e: logger.error(f"Broadcast fail (Unexpected) for {user_id}: {e}", exc_info=True); fail_count += 1

            await asyncio.sleep(0.05) # ~20 messages per second limit

            if status_message and (i + 1) % status_update_interval == 0:
                 try:
                     await context.bot.edit_message_text(
                         chat_id=admin_chat_id,
                         message_id=status_message.message_id,
                         text=f"⏳ Broadcasting... ({i+1}/{total_users} | ✅{success_count} | ❌{fail_count})",
                         parse_mode=None
                     )
                 except telegram_error.BadRequest: pass # Ignore if message is not modified
                 except Exception as edit_e: logger.warning(f"Could not edit broadcast status message: {edit_e}")

    finally:
         # Final summary message
         summary_msg = (f"✅ Broadcast Complete\n\nTarget: {target_type} = {target_value or 'N/A'}\n"
                        f"Sent to: {success_count}/{total_users}\n"
                        f"Failed: {fail_count}\n(Blocked/Deactivated: {block_count})")
         if status_message:
             try: await context.bot.edit_message_text(chat_id=admin_chat_id, message_id=status_message.message_id, text=summary_msg, parse_mode=None)
             except Exception: await send_message_with_retry(bot, admin_chat_id, summary_msg, parse_mode=None)
         else: await send_message_with_retry(bot, admin_chat_id, summary_msg, parse_mode=None)
         logger.info(f"Broadcast finished. Target: {target_type}={target_value}. Success: {success_count}, Failed: {fail_count}, Blocked: {block_count}")


# <<< ADDED: Handler for Clear Reservations Confirmation Button >>>
async def handle_adm_clear_reservations_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE, params=None):
    """Shows confirmation prompt for clearing all reservations."""
    query = update.callback_query
    if query.from_user.id != ADMIN_ID: return await query.answer("Access Denied.", show_alert=True)

    context.user_data["confirm_action"] = "clear_all_reservations"
    msg = (f"⚠️ Confirm Action: Clear All Reservations\n\n"
           f"Are you sure you want to clear ALL product reservations and empty ALL user baskets?\n\n"
           f"🚨 This action cannot be undone and will affect all users!")
    keyboard = [[InlineKeyboardButton("✅ Yes, Clear Reservations", callback_data="confirm_yes"),
                 InlineKeyboardButton("❌ No, Cancel", callback_data="admin_menu")]]
    await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=None)

# --- Confirmation Handler ---
async def handle_confirm_yes(update: Update, context: ContextTypes.DEFAULT_TYPE, params=None):
    """Handles generic 'Yes' confirmation based on stored action in user_data."""
    query = update.callback_query
    user_id = query.from_user.id
    is_primary_admin = (user_id == ADMIN_ID)
    if not is_primary_admin:
        logger.warning(f"Non-primary admin {user_id} tried to confirm a destructive action.")
        await query.answer("Permission denied for this action.", show_alert=True)
        return

    user_specific_data = context.user_data
    action = user_specific_data.pop("confirm_action", None)

    if not action:
        try: await query.edit_message_text("❌ Error: No action pending confirmation.", parse_mode=None)
        except telegram_error.BadRequest: pass # Ignore if not modified
        return
    chat_id = query.message.chat_id
    action_parts = action.split("|")
    action_type = action_parts[0]
    action_params = action_parts[1:]
    logger.info(f"Admin {user_id} confirmed action: {action_type} with params: {action_params}")
    success_msg, next_callback = "✅ Action completed successfully!", "admin_menu"
    conn = None # Initialize conn
    try:
        conn = get_db_connection() # Use helper
        c = conn.cursor()
        c.execute("BEGIN")
        # --- Delete City Logic ---
        if action_type == "delete_city":
             if not action_params: raise ValueError("Missing city_id")
             city_id_str = action_params[0]; city_id_int = int(city_id_str)
             city_name = CITIES.get(city_id_str)
             if city_name:
                 c.execute("SELECT id FROM products WHERE city = ?", (city_name,))
                 product_ids_to_delete = [row['id'] for row in c.fetchall()] # Use column name
                 # >>> ADDED LOGGING <<<
                 logger.info(f"Admin Action (delete_city): Deleting city '{city_name}'. Associated product IDs to be deleted: {product_ids_to_delete}")
                 # >>> END LOGGING <<<
                 if product_ids_to_delete:
                     placeholders = ','.join('?' * len(product_ids_to_delete))
                     c.execute(f"DELETE FROM product_media WHERE product_id IN ({placeholders})", product_ids_to_delete)
                     for pid in product_ids_to_delete:
                          media_dir_to_del = os.path.join(MEDIA_DIR, str(pid))
                          if await asyncio.to_thread(os.path.exists, media_dir_to_del):
                              asyncio.create_task(asyncio.to_thread(shutil.rmtree, media_dir_to_del, ignore_errors=True))
                              logger.info(f"Scheduled deletion of media dir: {media_dir_to_del}")
                 c.execute("DELETE FROM products WHERE city = ?", (city_name,)) # Actual product deletion
                 c.execute("DELETE FROM districts WHERE city_id = ?", (city_id_int,))
                 delete_city_result = c.execute("DELETE FROM cities WHERE id = ?", (city_id_int,))
                 if delete_city_result.rowcount > 0:
                     conn.commit(); load_all_data()
                     success_msg = f"✅ City '{city_name}' and contents deleted!"
                     next_callback = "adm_manage_cities"
                 else: conn.rollback(); success_msg = f"❌ Error: City '{city_name}' not found."
             else: conn.rollback(); success_msg = "❌ Error: City not found (already deleted?)."
        # --- Delete District Logic ---
        elif action_type == "remove_district":
             if len(action_params) < 2: raise ValueError("Missing city/dist_id")
             city_id_str, dist_id_str = action_params[0], action_params[1]
             city_id_int, dist_id_int = int(city_id_str), int(dist_id_str)
             city_name = CITIES.get(city_id_str)
             c.execute("SELECT name FROM districts WHERE id = ? AND city_id = ?", (dist_id_int, city_id_int))
             dist_res = c.fetchone(); district_name = dist_res['name'] if dist_res else None # Use column name
             if city_name and district_name:
                 c.execute("SELECT id FROM products WHERE city = ? AND district = ?", (city_name, district_name))
                 product_ids_to_delete = [row['id'] for row in c.fetchall()] # Use column name
                 # >>> ADDED LOGGING <<<
                 logger.info(f"Admin Action (remove_district): Deleting district '{district_name}' in '{city_name}'. Associated product IDs to be deleted: {product_ids_to_delete}")
                 # >>> END LOGGING <<<
                 if product_ids_to_delete:
                     placeholders = ','.join('?' * len(product_ids_to_delete))
                     c.execute(f"DELETE FROM product_media WHERE product_id IN ({placeholders})", product_ids_to_delete)
                     for pid in product_ids_to_delete:
                          media_dir_to_del = os.path.join(MEDIA_DIR, str(pid))
                          if await asyncio.to_thread(os.path.exists, media_dir_to_del):
                              asyncio.create_task(asyncio.to_thread(shutil.rmtree, media_dir_to_del, ignore_errors=True))
                              logger.info(f"Scheduled deletion of media dir: {media_dir_to_del}")
                 c.execute("DELETE FROM products WHERE city = ? AND district = ?", (city_name, district_name)) # Actual product deletion
                 delete_dist_result = c.execute("DELETE FROM districts WHERE id = ? AND city_id = ?", (dist_id_int, city_id_int))
                 if delete_dist_result.rowcount > 0:
                     conn.commit(); load_all_data()
                     success_msg = f"✅ District '{district_name}' removed from {city_name}!"
                     next_callback = f"adm_manage_districts_city|{city_id_str}"
                 else: conn.rollback(); success_msg = f"❌ Error: District '{district_name}' not found."
             else: conn.rollback(); success_msg = "❌ Error: City or District not found."
        # --- Delete Product Logic ---
        elif action_type == "confirm_remove_product":
             if not action_params: raise ValueError("Missing product_id")
             product_id = int(action_params[0])
             c.execute("SELECT ci.id as city_id, di.id as dist_id, p.product_type FROM products p LEFT JOIN cities ci ON p.city = ci.name LEFT JOIN districts di ON p.district = di.name AND ci.id = di.city_id WHERE p.id = ?", (product_id,))
             back_details_tuple = c.fetchone() # Result is already a Row object
             # >>> ADDED LOGGING <<<
             logger.info(f"Admin Action (confirm_remove_product): Deleting product ID {product_id}")
             # >>> END LOGGING <<<
             c.execute("DELETE FROM product_media WHERE product_id = ?", (product_id,))
             delete_prod_result = c.execute("DELETE FROM products WHERE id = ?", (product_id,)) # Actual product deletion
             if delete_prod_result.rowcount > 0:
                  conn.commit()
                  success_msg = f"✅ Product ID {product_id} removed!"
                  media_dir_to_delete = os.path.join(MEDIA_DIR, str(product_id))
                  if await asyncio.to_thread(os.path.exists, media_dir_to_delete):
                       asyncio.create_task(asyncio.to_thread(shutil.rmtree, media_dir_to_delete, ignore_errors=True))
                       logger.info(f"Scheduled deletion of media dir: {media_dir_to_delete}")
                  if back_details_tuple and all([back_details_tuple['city_id'], back_details_tuple['dist_id'], back_details_tuple['product_type']]):
                      next_callback = f"adm_manage_products_type|{back_details_tuple['city_id']}|{back_details_tuple['dist_id']}|{back_details_tuple['product_type']}" # Use column names
                  else: next_callback = "adm_manage_products"
             else: conn.rollback(); success_msg = f"❌ Error: Product ID {product_id} not found."
        # --- Delete Product Type Logic ---
        elif action_type == "delete_type":
              if not action_params: raise ValueError("Missing type_name")
              type_name = action_params[0]
              c.execute("SELECT COUNT(*) FROM products WHERE product_type = ?", (type_name,))
              product_count = c.fetchone()[0]
              c.execute("SELECT COUNT(*) FROM reseller_discounts WHERE product_type = ?", (type_name,)) # <<< Check reseller discounts
              reseller_discount_count = c.fetchone()[0]
              if product_count == 0 and reseller_discount_count == 0: # <<< Check both
                  delete_type_result = c.execute("DELETE FROM product_types WHERE name = ?", (type_name,))
                  if delete_type_result.rowcount > 0:
                       conn.commit(); load_all_data()
                       success_msg = f"✅ Type '{type_name}' deleted!"
                       next_callback = "adm_manage_types"
                  else: conn.rollback(); success_msg = f"❌ Error: Type '{type_name}' not found."
              else:
                  conn.rollback();
                  error_msg_parts = []
                  if product_count > 0: error_msg_parts.append(f"{product_count} product(s)")
                  if reseller_discount_count > 0: error_msg_parts.append(f"{reseller_discount_count} reseller discount rule(s)")
                  usage_details = " and ".join(error_msg_parts)
                  success_msg = f"❌ Error: Cannot delete type '{type_name}' as it is used by {usage_details}."
                  next_callback = "adm_manage_types" # Still go back
        # --- Delete General Discount Code Logic ---
        elif action_type == "delete_discount":
             if not action_params: raise ValueError("Missing discount_id")
             code_id = int(action_params[0])
             c.execute("SELECT code FROM discount_codes WHERE id = ?", (code_id,))
             code_res = c.fetchone(); code_text = code_res['code'] if code_res else f"ID {code_id}" # Use column name
             delete_disc_result = c.execute("DELETE FROM discount_codes WHERE id = ?", (code_id,))
             if delete_disc_result.rowcount > 0:
                 conn.commit()
                 success_msg = f"✅ Discount code {code_text} deleted!"
                 next_callback = "adm_manage_discounts"
             else: conn.rollback(); success_msg = f"❌ Error: Discount code {code_text} not found."
        # --- Delete Review Logic ---
        elif action_type == "delete_review":
            if not action_params: raise ValueError("Missing review_id")
            review_id = int(action_params[0])
            delete_rev_result = c.execute("DELETE FROM reviews WHERE review_id = ?", (review_id,))
            if delete_rev_result.rowcount > 0:
                conn.commit()
                success_msg = f"✅ Review ID {review_id} deleted!"
                next_callback = "adm_manage_reviews|0"
            else: conn.rollback(); success_msg = f"❌ Error: Review ID {review_id} not found."
        # <<< Welcome Message Delete Logic >>>
        elif action_type == "delete_welcome_template":
            if not action_params: raise ValueError("Missing template_name")
            name_to_delete = action_params[0]
            # Check if active - Now prevented in confirmation step
            delete_wm_result = c.execute("DELETE FROM welcome_messages WHERE name = ?", (name_to_delete,))
            if delete_wm_result.rowcount > 0:
                 conn.commit()
                 success_msg = f"✅ Welcome template '{name_to_delete}' deleted!"
                 next_callback = "adm_manage_welcome|0" # Go back to first page
            else: conn.rollback(); success_msg = f"❌ Error: Welcome template '{name_to_delete}' not found."
        # <<< Reset Welcome Message Logic >>>
        elif action_type == "reset_default_welcome":
            try:
                # Get the built-in text
                built_in_text = LANGUAGES['en']['welcome']
                # Update the 'default' template text
                c.execute("UPDATE welcome_messages SET template_text = ? WHERE name = ?", (built_in_text, "default"))
                # Set 'default' as active
                c.execute("INSERT OR REPLACE INTO bot_settings (setting_key, setting_value) VALUES (?, ?)",
                          ("active_welcome_message_name", "default"))
                conn.commit()
                success_msg = "✅ 'default' welcome template reset and activated."
                next_callback = "adm_manage_welcome|0"
            except Exception as reset_e:
                 conn.rollback()
                 logger.error(f"Error resetting default welcome message: {reset_e}", exc_info=True)
                 success_msg = "❌ Error resetting default template."
                 next_callback = "adm_manage_welcome|0"
        # <<< ADDED: Delete Reseller Discount Rule Logic >>>
        elif action_type == "confirm_delete_reseller_discount":
            if len(action_params) < 2: raise ValueError("Missing reseller_id or product_type")
            try:
                reseller_id = int(action_params[0])
                product_type = action_params[1]
                # Get old value for logging before deleting
                c.execute("SELECT discount_percentage FROM reseller_discounts WHERE reseller_user_id = ? AND product_type = ?", (reseller_id, product_type))
                old_res = c.fetchone()
                old_value = old_res['discount_percentage'] if old_res else None
                # Delete the rule
                delete_res_result = c.execute("DELETE FROM reseller_discounts WHERE reseller_user_id = ? AND product_type = ?", (reseller_id, product_type))
                if delete_res_result.rowcount > 0:
                    conn.commit()
                    # Log the action
                    log_admin_action(user_id, ACTION_RESELLER_DISCOUNT_DELETE, reseller_id, reason=f"Type: {product_type}", old_value=old_value)
                    success_msg = f"✅ Reseller discount rule deleted for {product_type}."
                    next_callback = f"reseller_manage_specific|{reseller_id}" # Go back to specific user's discount list
                else:
                    conn.rollback(); success_msg = f"❌ Error: Reseller discount rule for {product_type} not found."
                    next_callback = f"reseller_manage_specific|{reseller_id}" # Still go back
            except (ValueError, IndexError) as param_err:
                conn.rollback(); logger.error(f"Invalid params for delete reseller discount: {action_params} - {param_err}")
                success_msg = "❌ Error processing request."; next_callback = "admin_menu"
        # <<< ADDED: Clear All Reservations Logic >>>
        elif action_type == "clear_all_reservations":
            logger.warning(f"ADMIN ACTION: Admin {user_id} is clearing ALL reservations and baskets.")
            # Update products table
            update_products_res = c.execute("UPDATE products SET reserved = 0 WHERE reserved > 0")
            products_cleared = update_products_res.rowcount if update_products_res else 0
            # Update users table
            update_users_res = c.execute("UPDATE users SET basket = '' WHERE basket IS NOT NULL AND basket != ''")
            baskets_cleared = update_users_res.rowcount if update_users_res else 0
            conn.commit()
            # Log the action
            log_admin_action(admin_id=user_id, action="CLEAR_ALL_RESERVATIONS", reason=f"Cleared {products_cleared} reservations and {baskets_cleared} user baskets.")
            success_msg = f"✅ Cleared {products_cleared} product reservations and emptied {baskets_cleared} user baskets."
            next_callback = "admin_menu"
        # <<< END ADDED >>>
        else: # Unknown action type
            logger.error(f"Unknown confirmation action type: {action_type}")
            conn.rollback()
            success_msg = "❌ Unknown action confirmed."
            next_callback = "admin_menu"

        # Edit the original confirmation message
        try: await query.edit_message_text(success_msg, parse_mode=None)
        except telegram_error.BadRequest: pass # Ignore if not modified

        # Send follow-up message with navigation
        keyboard = [[InlineKeyboardButton("⬅️ Back", callback_data=next_callback)]]
        await send_message_with_retry(context.bot, chat_id, "Action complete. What next?", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=None)

    except (sqlite3.Error, ValueError, OSError, Exception) as e:
        logger.error(f"Error executing confirmed action '{action}': {e}", exc_info=True)
        if conn and conn.in_transaction: conn.rollback()
        error_text = str(e)
        try: await query.edit_message_text(f"❌ An error occurred: {error_text}", parse_mode=None)
        except Exception as edit_err: logger.error(f"Failed to edit message with error: {edit_err}")
    finally:
        if conn: conn.close() # Close connection if opened


# --- Welcome Message Management Handlers --- START
async def handle_adm_manage_welcome(update: Update, context: ContextTypes.DEFAULT_TYPE, params=None):
    """Displays the paginated menu for managing welcome message templates."""
    query = update.callback_query
    if query.from_user.id != ADMIN_ID:
        return await query.answer("Access Denied.", show_alert=True)

    lang, lang_data = _get_lang_data(context) # Use helper
    offset = 0
    if params and len(params) > 0 and params[0].isdigit():
        offset = int(params[0])

    # Fetch templates and active template name
    templates = get_welcome_message_templates(limit=TEMPLATES_PER_PAGE, offset=offset)
    total_templates = get_welcome_message_template_count()
    conn = None
    active_template_name = "default" # Default fallback
    try:
        conn = get_db_connection()
        c = conn.cursor()
        # Use column name
        c.execute("SELECT setting_value FROM bot_settings WHERE setting_key = ?", ("active_welcome_message_name",))
        setting_row = c.fetchone()
        if setting_row and setting_row['setting_value']: # Check if value is not None/empty
            active_template_name = setting_row['setting_value'] # Use column name
    except sqlite3.Error as e:
        logger.error(f"DB error fetching active welcome template name: {e}")
    finally:
        if conn: conn.close()

    # Build message and keyboard
    title = lang_data.get("manage_welcome_title", "⚙️ Manage Welcome Messages")
    prompt = lang_data.get("manage_welcome_prompt", "Select a template to manage or activate:")
    msg_parts = [f"{title}\n\n{prompt}\n"] # Use list to build message
    keyboard = []

    if not templates and offset == 0:
        msg_parts.append("\nNo custom templates found. Add one?")
    else:
        for template in templates:
            name = template['name']
            # <<< FIX: Escape name and description >>>
            safe_name = helpers.escape_markdown(name, version=2)
            desc = template.get('description') or "No description"
            safe_desc = helpers.escape_markdown(desc, version=2)

            is_active = (name == active_template_name)
            # <<< FIX: Escape the parentheses in the active indicator >>>
            active_indicator_raw = lang_data.get("welcome_template_active", " (Active ✅)") if is_active else lang_data.get("welcome_template_inactive", "")
            active_indicator = active_indicator_raw.replace("(", "\\(").replace(")", "\\)") # Manually escape parentheses for MDv2


            # Display Name, Description, and Active Status
            msg_parts.append(f"\n📄 *{safe_name}*{active_indicator}\n_{safe_desc}_\n") # Removed extra newline

            # Buttons: Edit | Activate (if not active) | Delete (if not default and not active)
            row = [InlineKeyboardButton(lang_data.get("welcome_button_edit", "✏️ Edit"), callback_data=f"adm_edit_welcome|{name}|{offset}")]
            if not is_active:
                 row.append(InlineKeyboardButton(lang_data.get("welcome_button_activate", "✅ Activate"), callback_data=f"adm_activate_welcome|{name}|{offset}"))

            can_delete = not (name == "default") and not is_active # Cannot delete default or active
            if can_delete:
                 row.append(InlineKeyboardButton(lang_data.get("welcome_button_delete", "🗑️ Delete"), callback_data=f"adm_delete_welcome_confirm|{name}|{offset}"))
            keyboard.append(row)

        # Pagination
        total_pages = math.ceil(total_templates / TEMPLATES_PER_PAGE)
        current_page = (offset // TEMPLATES_PER_PAGE) + 1
        nav_buttons = []
        if current_page > 1: nav_buttons.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"adm_manage_welcome|{max(0, offset - TEMPLATES_PER_PAGE)}"))
        if current_page < total_pages: nav_buttons.append(InlineKeyboardButton("➡️ Next", callback_data=f"adm_manage_welcome|{offset + TEMPLATES_PER_PAGE}"))
        if nav_buttons: keyboard.append(nav_buttons)
        if total_pages > 1:
            # Escape page number indicator too
            page_indicator = f"Page {current_page}/{total_pages}"
            escaped_page_indicator = helpers.escape_markdown(page_indicator, version=2)
            msg_parts.append(f"\n{escaped_page_indicator}")


    # Add "Add New" and "Reset Default" buttons
    keyboard.append([InlineKeyboardButton(lang_data.get("welcome_button_add_new", "➕ Add New Template"), callback_data="adm_add_welcome_start")])
    keyboard.append([InlineKeyboardButton(lang_data.get("welcome_button_reset_default", "🔄 Reset to Built-in Default"), callback_data="adm_reset_default_confirm")]) # <<< Added Reset Button
    keyboard.append([InlineKeyboardButton("⬅️ Back to Admin Menu", callback_data="admin_menu")])

    final_msg = "".join(msg_parts)

    # Send/Edit message
    try:
        # Try sending with Markdown V2
        await query.edit_message_text(final_msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN_V2)
    except telegram_error.BadRequest as e:
        if "message is not modified" not in str(e).lower():
            logger.error(f"Error editing welcome management menu (Markdown V2): {e}. Message: {final_msg[:500]}...") # Log snippet
            # Fallback to plain text
            plain_msg_fallback = final_msg
            for char in ['*', '_', '`', '[', ']', '(', ')', '~', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']:
                plain_msg_fallback = plain_msg_fallback.replace(f'\\{char}', char) # Remove escapes first
            for char in ['*', '_', '`']: # Remove common markdown chars
                plain_msg_fallback = plain_msg_fallback.replace(char, '')

            try:
                await query.edit_message_text(plain_msg_fallback, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=None)
                logger.info("Sent welcome management menu with plain text fallback due to Markdown V2 error.")
            except Exception as fallback_e:
                logger.error(f"Error editing welcome management menu (Fallback): {fallback_e}")
                await query.answer("Error displaying menu.", show_alert=True)
        else:
             await query.answer() # Acknowledge if not modified
    except Exception as e:
        logger.error(f"Unexpected error in handle_adm_manage_welcome: {e}", exc_info=True)
        await query.answer("An error occurred displaying the menu.", show_alert=True)

async def handle_adm_activate_welcome(update: Update, context: ContextTypes.DEFAULT_TYPE, params=None):
    """Activates the selected welcome message template."""
    query = update.callback_query
    if query.from_user.id != ADMIN_ID: return await query.answer("Access Denied.", show_alert=True)
    if not params or len(params) < 2 or not params[1].isdigit():
        return await query.answer("Error: Template name or offset missing.", show_alert=True)

    template_name = params[0]
    offset = int(params[1])
    lang, lang_data = _get_lang_data(context) # Use helper

    success = set_active_welcome_message(template_name) # Use helper from utils
    if success:
        msg_template = lang_data.get("welcome_activate_success", "✅ Template '{name}' activated.")
        await query.answer(msg_template.format(name=template_name))
        await handle_adm_manage_welcome(update, context, params=[str(offset)]) # Refresh menu at same page
    else:
        msg_template = lang_data.get("welcome_activate_fail", "❌ Failed to activate template '{name}'.")
        await query.answer(msg_template.format(name=template_name), show_alert=True)

async def handle_adm_add_welcome_start(update: Update, context: ContextTypes.DEFAULT_TYPE, params=None):
    """Starts the process of adding a new welcome template (gets name)."""
    query = update.callback_query
    if query.from_user.id != ADMIN_ID: return await query.answer("Access Denied.", show_alert=True)
    lang, lang_data = _get_lang_data(context) # Use helper

    context.user_data['state'] = 'awaiting_welcome_template_name'
    prompt = lang_data.get("welcome_add_name_prompt", "Enter a unique short name for the new template (e.g., 'default', 'promo_weekend'):")
    keyboard = [[InlineKeyboardButton("❌ Cancel", callback_data="adm_manage_welcome|0")]] # Go back to first page
    await query.edit_message_text(prompt, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=None)
    await query.answer("Enter template name in chat.")


async def handle_adm_edit_welcome(update: Update, context: ContextTypes.DEFAULT_TYPE, params=None):
    """Shows options for editing an existing welcome template (text or description)."""
    query = update.callback_query
    if query.from_user.id != ADMIN_ID: return await query.answer("Access Denied.", show_alert=True)
    if not params or len(params) < 2 or not params[1].isdigit():
        return await query.answer("Error: Template name or offset missing.", show_alert=True)

    template_name = params[0]
    offset = int(params[1])
    lang, lang_data = _get_lang_data(context) # Use helper

    # Fetch current text and description
    current_text = ""
    current_description = ""
    conn = None
    try:
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("SELECT template_text, description FROM welcome_messages WHERE name = ?", (template_name,))
        row = c.fetchone()
        if not row:
             await query.answer("Template not found.", show_alert=True)
             return await handle_adm_manage_welcome(update, context, params=[str(offset)])
        current_text = row['template_text']
        current_description = row['description'] or ""
    except sqlite3.Error as e:
        logger.error(f"DB error fetching template '{template_name}' for edit options: {e}")
        await query.answer("Error fetching template details.", show_alert=True)
        return await handle_adm_manage_welcome(update, context, params=[str(offset)])
    finally:
        if conn: conn.close()

    # Store info needed for potential edits
    context.user_data['editing_welcome_template_name'] = template_name
    context.user_data['editing_welcome_offset'] = offset

    # Display using plain text
    safe_name = template_name
    safe_desc = current_description or 'Not set'

    msg = f"✏️ Editing Template: {safe_name}\n\n"
    msg += f"📝 Description: {safe_desc}\n\n"
    msg += "Choose what to edit:"

    keyboard = [
        [InlineKeyboardButton(lang_data.get("welcome_button_edit_text","Edit Text"), callback_data=f"adm_edit_welcome_text|{template_name}")],
        [InlineKeyboardButton(lang_data.get("welcome_button_edit_desc","Edit Description"), callback_data=f"adm_edit_welcome_desc|{template_name}")],
        [InlineKeyboardButton("⬅️ Back", callback_data=f"adm_manage_welcome|{offset}")]
    ]
    try:
        await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=None)
    except telegram_error.BadRequest as e:
        if "message is not modified" not in str(e).lower(): logger.error(f"Error editing edit welcome menu: {e}. Message: {msg}")
        else: await query.answer() # Acknowledge if not modified
    except Exception as e:
        logger.error(f"Unexpected error in handle_adm_edit_welcome: {e}")
        await query.answer("Error displaying edit menu.", show_alert=True)

async def handle_adm_edit_welcome_text(update: Update, context: ContextTypes.DEFAULT_TYPE, params=None):
    """Initiates editing the template text."""
    query = update.callback_query
    if query.from_user.id != ADMIN_ID: return await query.answer("Access Denied.", show_alert=True)
    if not params: return await query.answer("Error: Template name missing.", show_alert=True)

    template_name = params[0]
    offset = context.user_data.get('editing_welcome_offset', 0) # Get offset from context
    lang, lang_data = _get_lang_data(context) # Use helper

    # Fetch current text to show in prompt
    current_text = ""
    conn = None
    try:
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("SELECT template_text FROM welcome_messages WHERE name = ?", (template_name,))
        row = c.fetchone()
        if row: current_text = row['template_text']
    except sqlite3.Error as e: logger.error(f"DB error fetching text for edit: {e}")
    finally:
         if conn: conn.close()

    context.user_data['state'] = 'awaiting_welcome_template_edit' # Reusing state, but specifically for text
    context.user_data['editing_welcome_template_name'] = template_name # Ensure it's set
    context.user_data['editing_welcome_field'] = 'text' # Indicate we are editing text

    placeholders = "{username}, {status}, {progress_bar}, {balance_str}, {purchases}, {basket_count}" # Plain text placeholders
    prompt_template = lang_data.get("welcome_edit_text_prompt", "Editing Text for '{name}'. Current text:\n\n{current_text}\n\nPlease reply with the new text. Available placeholders:\n{placeholders}")
    # Display plain text
    prompt = prompt_template.format(
        name=template_name,
        current_text=current_text,
        placeholders=placeholders
    )
    if len(prompt) > 4000: prompt = prompt[:4000] + "\n[... Current text truncated ...]"

    # Go back to the specific template's edit menu
    keyboard = [[InlineKeyboardButton("❌ Cancel Edit", callback_data=f"adm_edit_welcome|{template_name}|{offset}")]]
    try:
        await query.edit_message_text(prompt, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=None)
    except telegram_error.BadRequest as e:
        if "message is not modified" not in str(e).lower(): logger.error(f"Error editing edit text prompt: {e}")
        else: await query.answer()
    await query.answer("Enter new template text.")

async def handle_adm_edit_welcome_desc(update: Update, context: ContextTypes.DEFAULT_TYPE, params=None):
    """Initiates editing the template description."""
    query = update.callback_query
    if query.from_user.id != ADMIN_ID: return await query.answer("Access Denied.", show_alert=True)
    if not params: return await query.answer("Error: Template name missing.", show_alert=True)

    template_name = params[0]
    offset = context.user_data.get('editing_welcome_offset', 0)
    lang, lang_data = _get_lang_data(context) # Use helper

    # Fetch current description
    current_desc = ""
    conn = None
    try:
        conn = get_db_connection(); c = conn.cursor()
        c.execute("SELECT description FROM welcome_messages WHERE name = ?", (template_name,))
        row = c.fetchone(); current_desc = row['description'] or ""
    except sqlite3.Error as e: logger.error(f"DB error fetching desc for edit: {e}")
    finally:
        if conn: conn.close()

    context.user_data['state'] = 'awaiting_welcome_description_edit' # New state for description edit
    context.user_data['editing_welcome_template_name'] = template_name # Ensure it's set
    context.user_data['editing_welcome_field'] = 'description' # Indicate we are editing description

    prompt_template = lang_data.get("welcome_edit_description_prompt", "Editing description for '{name}'. Current: '{current_desc}'.\n\nEnter new description or send '-' to skip.")
    prompt = prompt_template.format(name=template_name, current_desc=current_desc or "Not set")

    keyboard = [[InlineKeyboardButton("❌ Cancel Edit", callback_data=f"adm_edit_welcome|{template_name}|{offset}")]]
    await query.edit_message_text(prompt, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=None)
    await query.answer("Enter new description.")

async def handle_adm_delete_welcome_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE, params=None):
    """Confirms deletion of a welcome message template."""
    query = update.callback_query
    if query.from_user.id != ADMIN_ID: return await query.answer("Access Denied.", show_alert=True)
    if not params or len(params) < 2 or not params[1].isdigit():
         return await query.answer("Error: Template name or offset missing.", show_alert=True)

    template_name = params[0]
    offset = int(params[1])
    lang, lang_data = _get_lang_data(context) # Use helper

    # Fetch current active template
    conn = None
    active_template_name = "default"
    try:
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("SELECT setting_value FROM bot_settings WHERE setting_key = ?", ("active_welcome_message_name",))
        row = c.fetchone(); active_template_name = row['setting_value'] if row else "default" # Use column name
    except sqlite3.Error as e: logger.error(f"DB error checking template status for delete: {e}")
    finally:
         if conn: conn.close()

    if template_name == "default":
        await query.answer("Cannot delete the 'default' template.", show_alert=True)
        return await handle_adm_manage_welcome(update, context, params=[str(offset)])

    # <<< Improvement: Prevent deleting the active template >>>
    if template_name == active_template_name:
        cannot_delete_msg = lang_data.get("welcome_cannot_delete_active", "❌ Cannot delete the active template. Activate another first.")
        await query.answer(cannot_delete_msg, show_alert=True)
        return await handle_adm_manage_welcome(update, context, params=[str(offset)]) # Refresh list

    context.user_data["confirm_action"] = f"delete_welcome_template|{template_name}"
    title = lang_data.get("welcome_delete_confirm_title", "⚠️ Confirm Deletion")
    text_template = lang_data.get("welcome_delete_confirm_text", "Are you sure you want to delete the welcome message template named '{name}'?")
    msg = f"{title}\n\n{text_template.format(name=template_name)}"

    keyboard = [
        [InlineKeyboardButton(lang_data.get("welcome_delete_button_yes", "✅ Yes, Delete Template"), callback_data="confirm_yes")],
        [InlineKeyboardButton("❌ No, Cancel", callback_data=f"adm_manage_welcome|{offset}")]
    ]
    await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=None)

# <<< Reset Default Welcome Handler >>>
async def handle_reset_default_welcome(update: Update, context: ContextTypes.DEFAULT_TYPE, params=None):
    """Confirms resetting the 'default' template to the built-in text and activating it."""
    query = update.callback_query
    if query.from_user.id != ADMIN_ID: return await query.answer("Access Denied.", show_alert=True)
    lang, lang_data = _get_lang_data(context)

    context.user_data["confirm_action"] = "reset_default_welcome"
    title = lang_data.get("welcome_reset_confirm_title", "⚠️ Confirm Reset")
    text = lang_data.get("welcome_reset_confirm_text", "Are you sure you want to reset the text of the 'default' template to the built-in version and activate it?")
    msg = f"{title}\n\n{text}"

    keyboard = [
        [InlineKeyboardButton(lang_data.get("welcome_reset_button_yes", "✅ Yes, Reset & Activate"), callback_data="confirm_yes")],
        [InlineKeyboardButton("❌ No, Cancel", callback_data="adm_manage_welcome|0")]
    ]
    await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=None)


# --- Welcome Message Management Handlers --- END


# --- Welcome Message Preview & Save Handlers --- START

async def _show_welcome_preview(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Shows a preview of the welcome message with dummy data."""
    query = update.callback_query # Could be None if called from message handler
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    lang, lang_data = _get_lang_data(context)

    pending_template = context.user_data.get("pending_welcome_template")
    if not pending_template or not pending_template.get("name"): # Need at least name
        logger.error("Attempted to show welcome preview, but pending data missing.")
        await send_message_with_retry(context.bot, chat_id, "❌ Error: Preview data lost.", parse_mode=None)
        context.user_data.pop("state", None)
        context.user_data.pop("pending_welcome_template", None)
        # Attempt to go back to the management menu
        if query:
             await handle_adm_manage_welcome(update, context, params=["0"])
        return

    template_name = pending_template['name']
    template_text = pending_template.get('text', '') # Use get with fallback
    template_description = pending_template.get('description', 'Not set')
    is_editing = pending_template.get('is_editing', False)
    offset = pending_template.get('offset', 0)

    # Dummy data for formatting
    dummy_username = update.effective_user.first_name or "Admin"
    dummy_status = "VIP 👑"
    dummy_progress = get_progress_bar(10)
    dummy_balance = format_currency(123.45)
    dummy_purchases = 15
    dummy_basket = 2
    preview_text_raw = "_(Formatting Error)_" # Fallback preview

    try:
        # Format using the raw username and placeholders
        preview_text_raw = template_text.format(
            username=dummy_username,
            status=dummy_status,
            progress_bar=dummy_progress,
            balance_str=dummy_balance,
            purchases=dummy_purchases,
            basket_count=dummy_basket
        ) # Keep internal markdown

    except KeyError as e:
        logger.warning(f"KeyError formatting welcome preview for '{template_name}': {e}")
        err_msg_template = lang_data.get("welcome_invalid_placeholder", "⚠️ Formatting Error! Missing placeholder: `{key}`\n\nRaw Text:\n{text}")
        preview_text_raw = err_msg_template.format(key=e, text=template_text[:500]) # Show raw text in case of error
    except Exception as format_e:
        logger.error(f"Unexpected error formatting preview: {format_e}")
        err_msg_template = lang_data.get("welcome_formatting_error", "⚠️ Unexpected Formatting Error!\n\nRaw Text:\n{text}")
        preview_text_raw = err_msg_template.format(text=template_text[:500])

    # Prepare display message (plain text)
    title = lang_data.get("welcome_preview_title", "--- Welcome Message Preview ---")
    name_label = lang_data.get("welcome_preview_name", "Name")
    desc_label = lang_data.get("welcome_preview_desc", "Desc")
    confirm_prompt = lang_data.get("welcome_preview_confirm", "Save this template?")

    msg = f"{title}\n\n"
    msg += f"{name_label}: {template_name}\n"
    msg += f"{desc_label}: {template_description or 'Not set'}\n"
    msg += f"---\n"
    msg += f"{preview_text_raw}\n" # Display the formatted (and potentially error) message raw
    msg += f"---\n"
    msg += f"\n{confirm_prompt}"

    # Set state for confirmation callback
    context.user_data['state'] = 'awaiting_welcome_confirmation'

    # Go back to the specific template edit menu if editing, or manage menu if adding
    cancel_callback = f"adm_edit_welcome|{template_name}|{offset}" if is_editing else f"adm_manage_welcome|{offset}"

    keyboard = [
        [InlineKeyboardButton(lang_data.get("welcome_button_save", "💾 Save Template"), callback_data=f"confirm_save_welcome")],
        [InlineKeyboardButton("❌ Cancel", callback_data=cancel_callback)]
    ]

    # Send or edit the message (using plain text)
    message_to_edit = query.message if query else None
    if message_to_edit:
        try:
            await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=None)
        except telegram_error.BadRequest as e:
             if "message is not modified" not in str(e).lower():
                 logger.error(f"Error editing preview message: {e}")
                 # Send as new message if edit fails
                 await send_message_with_retry(context.bot, chat_id, msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=None)
             else: await query.answer() # Ignore modification error
    else:
        # Send as new message if no original message to edit
        await send_message_with_retry(context.bot, chat_id, msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=None)

    if query:
        await query.answer()

# <<< NEW >>>
async def handle_confirm_save_welcome(update: Update, context: ContextTypes.DEFAULT_TYPE, params=None):
    """Handles the 'Save Template' button after preview."""
    query = update.callback_query
    user_id = query.from_user.id
    if user_id != ADMIN_ID: return await query.answer("Access Denied.", show_alert=True)
    if context.user_data.get("state") != 'awaiting_welcome_confirmation':
        logger.warning("handle_confirm_save_welcome called in wrong state.")
        return await query.answer("Invalid state.", show_alert=True)

    pending_template = context.user_data.get("pending_welcome_template")
    if not pending_template or not pending_template.get("name") or pending_template.get("text") is None: # Text can be empty, but key must exist
        logger.error("Attempted to save welcome template, but pending data missing.")
        await query.edit_message_text("❌ Error: Save data lost. Please start again.", parse_mode=None)
        context.user_data.pop("state", None)
        context.user_data.pop("pending_welcome_template", None)
        return

    template_name = pending_template['name']
    template_text = pending_template['text']
    template_description = pending_template.get('description') # Can be None
    is_editing = pending_template.get('is_editing', False)
    offset = pending_template.get('offset', 0)
    lang, lang_data = _get_lang_data(context) # Use helper

    # Perform the actual save operation
    success = False
    if is_editing:
        success = update_welcome_message_template(template_name, template_text, template_description)
        msg_template = lang_data.get("welcome_edit_success", "✅ Template '{name}' updated.") if success else lang_data.get("welcome_edit_fail", "❌ Failed to update template '{name}'.")
    else:
        success = add_welcome_message_template(template_name, template_text, template_description)
        msg_template = lang_data.get("welcome_add_success", "✅ Welcome message template '{name}' added.") if success else lang_data.get("welcome_add_fail", "❌ Failed to add welcome message template.")

    # Clean up context
    context.user_data.pop("state", None)
    context.user_data.pop("pending_welcome_template", None)

    await query.edit_message_text(msg_template.format(name=template_name), parse_mode=None)

    # Go back to the management list
    await handle_adm_manage_welcome(update, context, params=[str(offset)])


# --- Welcome Message Management Handlers --- END


# --- Admin Message Handlers (Used when state is set) ---
# --- These handlers are primarily for the core admin flow ---
# --- Reseller state message handlers are defined in reseller_management.py ---

async def handle_adm_add_city_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles text reply when state is 'awaiting_new_city_name'."""
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    if user_id != ADMIN_ID: return
    if not update.message or not update.message.text: return
    if context.user_data.get("state") != "awaiting_new_city_name": return
    text = update.message.text.strip()
    if not text: return await send_message_with_retry(context.bot, chat_id, "City name cannot be empty.", parse_mode=None)
    conn = None # Initialize conn
    try:
        conn = get_db_connection() # Use helper
        c = conn.cursor()
        c.execute("INSERT INTO cities (name) VALUES (?)", (text,))
        new_city_id = c.lastrowid
        conn.commit()
        load_all_data() # Reload global data
        context.user_data.pop("state", None)
        success_text = f"✅ City '{text}' added successfully!"
        keyboard = [[InlineKeyboardButton("⬅️ Manage Cities", callback_data="adm_manage_cities")]]
        await send_message_with_retry(context.bot, chat_id, success_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=None)
    except sqlite3.IntegrityError:
        await send_message_with_retry(context.bot, chat_id, f"❌ Error: City '{text}' already exists.", parse_mode=None)
    except sqlite3.Error as e:
        logger.error(f"DB error adding city '{text}': {e}", exc_info=True)
        if conn and conn.in_transaction: conn.rollback()
        await send_message_with_retry(context.bot, chat_id, "❌ Error: Failed to add city.", parse_mode=None)
        context.user_data.pop("state", None)
    finally:
        if conn: conn.close() # Close connection if opened

async def handle_adm_add_district_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles text reply when state is 'awaiting_new_district_name'."""
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    if user_id != ADMIN_ID: return
    if not update.message or not update.message.text: return
    if context.user_data.get("state") != "awaiting_new_district_name": return
    text = update.message.text.strip()
    city_id_str = context.user_data.get("admin_add_district_city_id")
    city_name = CITIES.get(city_id_str)
    if not city_id_str or not city_name:
        await send_message_with_retry(context.bot, chat_id, "❌ Error: Could not determine city.", parse_mode=None)
        context.user_data.pop("state", None); context.user_data.pop("admin_add_district_city_id", None)
        return
    if not text: return await send_message_with_retry(context.bot, chat_id, "District name cannot be empty.", parse_mode=None)
    conn = None # Initialize conn
    try:
        city_id_int = int(city_id_str)
        conn = get_db_connection() # Use helper
        c = conn.cursor()
        c.execute("INSERT INTO districts (city_id, name) VALUES (?, ?)", (city_id_int, text))
        conn.commit()
        load_all_data() # Reload global data
        context.user_data.pop("state", None); context.user_data.pop("admin_add_district_city_id", None)
        success_text = f"✅ District '{text}' added to {city_name}!"
        keyboard = [[InlineKeyboardButton("⬅️ Manage Districts", callback_data=f"adm_manage_districts_city|{city_id_str}")]]
        await send_message_with_retry(context.bot, chat_id, success_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=None)
    except sqlite3.IntegrityError:
        await send_message_with_retry(context.bot, chat_id, f"❌ Error: District '{text}' already exists in {city_name}.", parse_mode=None)
    except (sqlite3.Error, ValueError) as e:
        logger.error(f"DB/Value error adding district '{text}' to city {city_id_str}: {e}", exc_info=True)
        if conn and conn.in_transaction: conn.rollback()
        await send_message_with_retry(context.bot, chat_id, "❌ Error: Failed to add district.", parse_mode=None)
        context.user_data.pop("state", None); context.user_data.pop("admin_add_district_city_id", None)
    finally:
        if conn: conn.close() # Close connection if opened

async def handle_adm_edit_district_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles text reply when state is 'awaiting_edit_district_name'."""
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    if user_id != ADMIN_ID: return
    if not update.message or not update.message.text: return
    if context.user_data.get("state") != "awaiting_edit_district_name": return
    new_name = update.message.text.strip()
    city_id_str = context.user_data.get("edit_city_id")
    dist_id_str = context.user_data.get("edit_district_id")
    city_name = CITIES.get(city_id_str)
    old_district_name = None
    conn = None # Initialize conn
    try:
        conn = get_db_connection() # Use helper
        c = conn.cursor()
        # Use column name
        c.execute("SELECT name FROM districts WHERE id = ? AND city_id = ?", (int(dist_id_str), int(city_id_str)))
        res = c.fetchone(); old_district_name = res['name'] if res else None
    except (sqlite3.Error, ValueError) as e: logger.error(f"Failed to fetch old district name for edit: {e}")
    finally:
        if conn: conn.close() # Close connection if opened
    if not city_id_str or not dist_id_str or not city_name or old_district_name is None:
        await send_message_with_retry(context.bot, chat_id, "❌ Error: Could not find district/city.", parse_mode=None)
        context.user_data.pop("state", None); context.user_data.pop("edit_city_id", None); context.user_data.pop("edit_district_id", None)
        return
    if not new_name: return await send_message_with_retry(context.bot, chat_id, "New district name cannot be empty.", parse_mode=None)
    if new_name == old_district_name:
        await send_message_with_retry(context.bot, chat_id, "New name is the same. No changes.", parse_mode=None)
        context.user_data.pop("state", None); context.user_data.pop("edit_city_id", None); context.user_data.pop("edit_district_id", None)
        keyboard = [[InlineKeyboardButton("⬅️ Manage Districts", callback_data=f"adm_manage_districts_city|{city_id_str}")]]
        return await send_message_with_retry(context.bot, chat_id, "No changes detected.", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=None)
    conn = None # Re-initialize for update transaction
    try:
        city_id_int, dist_id_int = int(city_id_str), int(dist_id_str)
        conn = get_db_connection() # Use helper
        c = conn.cursor()
        c.execute("BEGIN")
        c.execute("UPDATE districts SET name = ? WHERE id = ? AND city_id = ?", (new_name, dist_id_int, city_id_int))
        # Update products table as well
        c.execute("UPDATE products SET district = ? WHERE district = ? AND city = ?", (new_name, old_district_name, city_name))
        conn.commit()
        load_all_data() # Reload global data
        context.user_data.pop("state", None); context.user_data.pop("edit_city_id", None); context.user_data.pop("edit_district_id", None)
        success_text = f"✅ District updated to '{new_name}' successfully!"
        keyboard = [[InlineKeyboardButton("⬅️ Manage Districts", callback_data=f"adm_manage_districts_city|{city_id_str}")]]
        await send_message_with_retry(context.bot, chat_id, success_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=None)
    except sqlite3.IntegrityError:
        await send_message_with_retry(context.bot, chat_id, f"❌ Error: District '{new_name}' already exists.", parse_mode=None)
    except (sqlite3.Error, ValueError) as e:
        logger.error(f"DB/Value error updating district {dist_id_str}: {e}", exc_info=True)
        if conn and conn.in_transaction: conn.rollback()
        await send_message_with_retry(context.bot, chat_id, "❌ Error: Failed to update district.", parse_mode=None)
        context.user_data.pop("state", None); context.user_data.pop("edit_city_id", None); context.user_data.pop("edit_district_id", None)
    finally:
         if conn: conn.close() # Close connection if opened


async def handle_adm_edit_city_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles text reply when state is 'awaiting_edit_city_name'."""
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    if user_id != ADMIN_ID: return
    if not update.message or not update.message.text: return
    if context.user_data.get("state") != "awaiting_edit_city_name": return
    new_name = update.message.text.strip()
    city_id_str = context.user_data.get("edit_city_id")
    old_name = None
    conn = None # Initialize conn
    try:
        conn = get_db_connection() # Use helper
        c = conn.cursor()
        # Use column name
        c.execute("SELECT name FROM cities WHERE id = ?", (int(city_id_str),))
        res = c.fetchone(); old_name = res['name'] if res else None
    except (sqlite3.Error, ValueError) as e: logger.error(f"Failed to fetch old city name for edit: {e}")
    finally:
        if conn: conn.close() # Close connection if opened
    if not city_id_str or old_name is None:
        await send_message_with_retry(context.bot, chat_id, "❌ Error: Could not find city.", parse_mode=None)
        context.user_data.pop("state", None); context.user_data.pop("edit_city_id", None)
        return
    if not new_name: return await send_message_with_retry(context.bot, chat_id, "New city name cannot be empty.", parse_mode=None)
    if new_name == old_name:
        await send_message_with_retry(context.bot, chat_id, "New name is the same. No changes.", parse_mode=None)
        context.user_data.pop("state", None); context.user_data.pop("edit_city_id", None)
        keyboard = [[InlineKeyboardButton("⬅️ Manage Cities", callback_data="adm_manage_cities")]]
        return await send_message_with_retry(context.bot, chat_id, "No changes detected.", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=None)
    conn = None # Re-initialize for update transaction
    try:
        city_id_int = int(city_id_str)
        conn = get_db_connection() # Use helper
        c = conn.cursor()
        c.execute("BEGIN")
        c.execute("UPDATE cities SET name = ? WHERE id = ?", (new_name, city_id_int))
        # Update products table as well
        c.execute("UPDATE products SET city = ? WHERE city = ?", (new_name, old_name))
        conn.commit()
        load_all_data() # Reload global data
        context.user_data.pop("state", None); context.user_data.pop("edit_city_id", None)
        success_text = f"✅ City updated to '{new_name}' successfully!"
        keyboard = [[InlineKeyboardButton("⬅️ Manage Cities", callback_data="adm_manage_cities")]]
        await send_message_with_retry(context.bot, chat_id, success_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=None)
    except sqlite3.IntegrityError:
        await send_message_with_retry(context.bot, chat_id, f"❌ Error: City '{new_name}' already exists.", parse_mode=None)
    except (sqlite3.Error, ValueError) as e:
        logger.error(f"DB/Value error updating city {city_id_str}: {e}", exc_info=True)
        if conn and conn.in_transaction: conn.rollback()
        await send_message_with_retry(context.bot, chat_id, "❌ Error: Failed to update city.", parse_mode=None)
        context.user_data.pop("state", None); context.user_data.pop("edit_city_id", None)
    finally:
         if conn: conn.close() # Close connection if opened


async def handle_adm_custom_size_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles text reply when state is 'awaiting_custom_size'."""
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    if user_id != ADMIN_ID: return
    if not update.message or not update.message.text: return
    if context.user_data.get("state") != "awaiting_custom_size": return
    custom_size = update.message.text.strip()
    if not custom_size: return await send_message_with_retry(context.bot, chat_id, "Custom size cannot be empty.", parse_mode=None)
    if len(custom_size) > 50: return await send_message_with_retry(context.bot, chat_id, "Custom size too long (max 50 chars).", parse_mode=None)
    if not all(k in context.user_data for k in ["admin_city", "admin_district", "admin_product_type"]):
        await send_message_with_retry(context.bot, chat_id, "❌ Error: Context lost.", parse_mode=None)
        context.user_data.pop("state", None)
        return
    context.user_data["pending_drop_size"] = custom_size
    context.user_data["state"] = "awaiting_price"
    keyboard = [[InlineKeyboardButton("❌ Cancel Add", callback_data="cancel_add")]]
    await send_message_with_retry(context.bot, chat_id, f"Custom size set to '{custom_size}'. Reply with the price (e.g., 12.50):",
                            reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=None)

async def handle_adm_price_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles text reply when state is 'awaiting_price'."""
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    if user_id != ADMIN_ID: return
    if not update.message or not update.message.text: return
    if context.user_data.get("state") != "awaiting_price": return
    price_text = update.message.text.strip().replace(',', '.')
    try:
        price = round(float(price_text), 2)
        if price <= 0: raise ValueError("Price must be positive")
    except ValueError:
        return await send_message_with_retry(context.bot, chat_id, "❌ Invalid Price Format. Enter positive number (e.g., 12.50):", parse_mode=None)
    if not all(k in context.user_data for k in ["admin_city", "admin_district", "admin_product_type", "pending_drop_size"]):
        await send_message_with_retry(context.bot, chat_id, "❌ Error: Context lost.", parse_mode=None)
        context.user_data.pop("state", None); context.user_data.pop("pending_drop_size", None)
        return
    context.user_data["pending_drop_price"] = price
    context.user_data["state"] = "awaiting_drop_details"
    keyboard = [[InlineKeyboardButton("❌ Cancel Add", callback_data="cancel_add")]]
    price_f = format_currency(price)
    await send_message_with_retry(context.bot, chat_id,
                                  f"Price set to {price_f} EUR. Now send drop details:\n"
                                  f"- Send text only, OR\n"
                                  f"- Send photo(s)/video(s) WITH text caption, OR\n"
                                  f"- Forward a message containing media and text.",
                                  reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=None)

async def handle_adm_bot_media_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the media message when state is 'awaiting_bot_media'."""
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    if user_id != ADMIN_ID: return
    if not update.message: return
    if context.user_data.get("state") != "awaiting_bot_media": return

    new_media_type, file_to_download, file_extension, file_id = None, None, None, None
    if update.message.photo: file_to_download, new_media_type, file_extension, file_id = update.message.photo[-1], "photo", ".jpg", update.message.photo[-1].file_id
    elif update.message.video: file_to_download, new_media_type, file_extension, file_id = update.message.video, "video", ".mp4", update.message.video.file_id
    elif update.message.animation: file_to_download, new_media_type, file_extension, file_id = update.message.animation, "gif", ".mp4", update.message.animation.file_id
    elif update.message.document and update.message.document.mime_type and 'gif' in update.message.document.mime_type.lower():
         file_to_download, new_media_type, file_extension, file_id = update.message.document, "gif", ".gif", update.message.document.file_id
    else: return await send_message_with_retry(context.bot, chat_id, "❌ Invalid Media Type. Send photo, video, or GIF.", parse_mode=None)
    if not file_to_download or not file_id: return await send_message_with_retry(context.bot, chat_id, "❌ Could not identify media file.", parse_mode=None)

    context.user_data.pop("state", None)
    await send_message_with_retry(context.bot, chat_id, "⏳ Downloading and saving new media...", parse_mode=None)

    final_media_path = os.path.join(MEDIA_DIR, f"bot_media{file_extension}")
    temp_download_path = final_media_path + ".tmp"

    try:
        logger.info(f"Downloading new bot media ({new_media_type}) ID {file_id} to {temp_download_path}")
        file_obj = await context.bot.get_file(file_id)
        await file_obj.download_to_drive(custom_path=temp_download_path)
        logger.info("Media download successful to temp path.")

        if not await asyncio.to_thread(os.path.exists, temp_download_path) or await asyncio.to_thread(os.path.getsize, temp_download_path) == 0:
             raise IOError("Downloaded file is empty or missing.")

        old_media_path_global = BOT_MEDIA.get("path")
        if old_media_path_global and old_media_path_global != final_media_path and await asyncio.to_thread(os.path.exists, old_media_path_global):
            try:
                await asyncio.to_thread(os.remove, old_media_path_global)
                logger.info(f"Removed old bot media file: {old_media_path_global}")
            except OSError as e:
                logger.warning(f"Could not remove old bot media file '{old_media_path_global}': {e}")

        await asyncio.to_thread(shutil.move, temp_download_path, final_media_path)
        logger.info(f"Moved media to final path: {final_media_path}")

        BOT_MEDIA["type"] = new_media_type
        BOT_MEDIA["path"] = final_media_path

        try:
            def write_json_sync(path, data):
                try:
                    with open(path, 'w') as f:
                        json.dump(data, f, indent=4)
                    logger.info(f"Successfully wrote updated BOT_MEDIA to {path}: {data}")
                    return True
                except Exception as e_sync:
                    logger.error(f"Failed during synchronous write to {path}: {e_sync}")
                    return False

            write_successful = await asyncio.to_thread(write_json_sync, BOT_MEDIA_JSON_PATH, BOT_MEDIA)

            if not write_successful:
                raise IOError(f"Failed to write bot media configuration to {BOT_MEDIA_JSON_PATH}")

        except Exception as e:
            logger.error(f"Error during bot media JSON writing process: {e}")
            await send_message_with_retry(context.bot, chat_id, f"❌ Error saving media configuration: {e}", parse_mode=None)
            if await asyncio.to_thread(os.path.exists, final_media_path):
                 try: await asyncio.to_thread(os.remove, final_media_path)
                 except OSError: pass
            return

        await send_message_with_retry(context.bot, chat_id, "✅ Bot Media Updated Successfully!", parse_mode=None)
        keyboard = [[InlineKeyboardButton("⬅️ Back to Admin Menu", callback_data="admin_menu")]]
        await send_message_with_retry(context.bot, chat_id, "Changes applied.", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=None)

    except (telegram_error.TelegramError, IOError, OSError) as e:
        logger.error(f"Error downloading/saving bot media: {e}")
        await send_message_with_retry(context.bot, chat_id, "❌ Error downloading or saving media. Please try again.", parse_mode=None)
        if await asyncio.to_thread(os.path.exists, temp_download_path):
            try: await asyncio.to_thread(os.remove, temp_download_path)
            except OSError: pass
    except Exception as e:
        logger.error(f"Unexpected error updating bot media: {e}", exc_info=True)
        await send_message_with_retry(context.bot, chat_id, "❌ An unexpected error occurred.", parse_mode=None)
    finally:
        if 'temp_download_path' in locals() and await asyncio.to_thread(os.path.exists, temp_download_path):
             try: await asyncio.to_thread(os.remove, temp_download_path)
             except OSError as e: logger.warning(f"Could not remove temp dl file '{temp_download_path}': {e}")


# --- Add Product Type Handlers ---
async def handle_adm_add_type_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles text reply when state is 'awaiting_new_type_name'."""
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    lang, lang_data = _get_lang_data(context) # Use helper

    if user_id != ADMIN_ID: return
    if not update.message or not update.message.text: return
    if context.user_data.get("state") != "awaiting_new_type_name": return

    type_name = update.message.text.strip()
    if not type_name: return await send_message_with_retry(context.bot, chat_id, "Product type name cannot be empty.", parse_mode=None)
    if len(type_name) > 100: return await send_message_with_retry(context.bot, chat_id, "Product type name too long (max 100 chars).", parse_mode=None)
    if type_name.lower() in [pt.lower() for pt in PRODUCT_TYPES.keys()]:
        return await send_message_with_retry(context.bot, chat_id, f"❌ Error: Type '{type_name}' already exists.", parse_mode=None)

    context.user_data["new_type_name"] = type_name
    context.user_data["state"] = "awaiting_new_type_emoji"
    prompt_text = lang_data.get("admin_enter_type_emoji", "✍️ Please reply with a single emoji for the product type:")
    keyboard = [[InlineKeyboardButton("❌ Cancel", callback_data="adm_manage_types")]]
    await send_message_with_retry(context.bot, chat_id, f"Type name set to: {type_name}\n\n{prompt_text}", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=None)


async def handle_adm_add_type_emoji_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the emoji reply when state is 'awaiting_new_type_emoji'."""
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    lang, lang_data = _get_lang_data(context) # Use helper

    if user_id != ADMIN_ID: return
    if not update.message or not update.message.text: return
    if context.user_data.get("state") != "awaiting_new_type_emoji": return

    emoji = update.message.text.strip()
    type_name = context.user_data.get("new_type_name")

    if not type_name:
        logger.error(f"State is awaiting_new_type_emoji but new_type_name missing for user {user_id}")
        context.user_data.pop("state", None)
        await send_message_with_retry(context.bot, chat_id, "❌ Error: Context lost. Please start adding the type again.", parse_mode=None)
        return

    # Basic emoji validation (checks length and if it's likely an emoji)
    # This is not foolproof but avoids adding the 'emoji' library dependency
    is_likely_emoji = len(emoji) == 1 and ord(emoji) > 256
    if not is_likely_emoji:
        invalid_emoji_msg = lang_data.get("admin_invalid_emoji", "❌ Invalid input. Please send a single emoji.")
        await send_message_with_retry(context.bot, chat_id, invalid_emoji_msg, parse_mode=None)
        return

    conn=None
    try:
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("INSERT INTO product_types (name, emoji) VALUES (?, ?)", (type_name, emoji))
        conn.commit()
        load_all_data()
        context.user_data.pop("state", None)
        context.user_data.pop("new_type_name", None)

        emoji_set_msg = lang_data.get("admin_type_emoji_set", "Emoji set to {emoji}.")
        success_text = f"✅ Product Type '{type_name}' added!\n{emoji_set_msg.format(emoji=emoji)}"
        keyboard = [[InlineKeyboardButton("⬅️ Manage Types", callback_data="adm_manage_types")]]
        await send_message_with_retry(context.bot, chat_id, success_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=None)

    except sqlite3.IntegrityError:
        await send_message_with_retry(context.bot, chat_id, f"❌ Error: Product type '{type_name}' already exists.", parse_mode=None)
        context.user_data.pop("state", None); context.user_data.pop("new_type_name", None)
    except sqlite3.Error as e:
        logger.error(f"DB error adding product type '{type_name}' with emoji '{emoji}': {e}", exc_info=True)
        if conn and conn.in_transaction: conn.rollback()
        await send_message_with_retry(context.bot, chat_id, "❌ Error: Failed to add type.", parse_mode=None)
        context.user_data.pop("state", None); context.user_data.pop("new_type_name", None)
    finally:
        if conn: conn.close()


# --- Edit Product Type Emoji Message Handler ---
async def handle_adm_edit_type_emoji_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the emoji reply when state is 'awaiting_edit_type_emoji'."""
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    lang, lang_data = _get_lang_data(context) # Use helper

    if user_id != ADMIN_ID: return
    if not update.message or not update.message.text: return
    if context.user_data.get("state") != "awaiting_edit_type_emoji": return

    new_emoji = update.message.text.strip()
    type_name = context.user_data.get("edit_type_name")

    if not type_name:
        logger.error(f"State is awaiting_edit_type_emoji but edit_type_name missing for user {user_id}")
        context.user_data.pop("state", None)
        await send_message_with_retry(context.bot, chat_id, "❌ Error: Context lost. Please start editing the type again.", parse_mode=None)
        return

    # Basic emoji validation
    is_likely_emoji = len(new_emoji) == 1 and ord(new_emoji) > 256
    if not is_likely_emoji:
        invalid_emoji_msg = lang_data.get("admin_invalid_emoji", "❌ Invalid input. Please send a single emoji.")
        await send_message_with_retry(context.bot, chat_id, invalid_emoji_msg, parse_mode=None)
        return

    conn = None
    try:
        conn = get_db_connection()
        c = conn.cursor()
        update_result = c.execute("UPDATE product_types SET emoji = ? WHERE name = ?", (new_emoji, type_name))
        conn.commit()

        if update_result.rowcount == 0:
            logger.warning(f"Attempted to update emoji for non-existent type: {type_name}")
            await send_message_with_retry(context.bot, chat_id, f"❌ Error: Type '{type_name}' not found.", parse_mode=None)
        else:
            load_all_data()
            success_msg_template = lang_data.get("admin_type_emoji_updated", "✅ Emoji updated successfully for {type_name}!")
            success_text = success_msg_template.format(type_name=type_name) + f" New emoji: {new_emoji}"
            keyboard = [[InlineKeyboardButton("⬅️ Manage Types", callback_data="adm_manage_types")]]
            await send_message_with_retry(context.bot, chat_id, success_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=None)

        context.user_data.pop("state", None)
        context.user_data.pop("edit_type_name", None)

    except sqlite3.Error as e:
        logger.error(f"DB error updating emoji for type '{type_name}': {e}", exc_info=True)
        if conn and conn.in_transaction: conn.rollback()
        await send_message_with_retry(context.bot, chat_id, "❌ Error: Failed to update emoji.", parse_mode=None)
        context.user_data.pop("state", None); context.user_data.pop("edit_type_name", None)
    finally:
        if conn: conn.close()


# --- Message Handlers for Discount Creation ---
async def process_discount_code_input(update: Update, context: ContextTypes.DEFAULT_TYPE, code_text: str):
    """Shared logic to process entered/generated discount code and ask for type."""
    chat_id = update.effective_chat.id
    query = update.callback_query
    if not code_text:
        msg = "Code cannot be empty. Please try again."
        if query: await query.answer(msg, show_alert=True)
        else: await send_message_with_retry(context.bot, chat_id, msg, parse_mode=None)
        return
    if len(code_text) > 50:
        msg = "Code too long (max 50 chars)."
        if query: await query.answer(msg, show_alert=True)
        else: await send_message_with_retry(context.bot, chat_id, msg, parse_mode=None)
        return
    conn = None # Initialize conn
    try:
        conn = get_db_connection() # Use helper
        c = conn.cursor()
        c.execute("SELECT 1 FROM discount_codes WHERE code = ?", (code_text,))
        if c.fetchone():
            error_msg = f"❌ Error: Discount code '{code_text}' already exists."
            if query:
                try: await query.edit_message_text(error_msg, parse_mode=None)
                except telegram_error.BadRequest: await send_message_with_retry(context.bot, chat_id, error_msg, parse_mode=None)
            else: await send_message_with_retry(context.bot, chat_id, error_msg, parse_mode=None)
            return
    except sqlite3.Error as e:
        logger.error(f"DB error checking discount code uniqueness: {e}")
        error_msg = "❌ Database error checking code uniqueness."
        if query: await query.answer("DB Error.", show_alert=True)
        await send_message_with_retry(context.bot, chat_id, error_msg, parse_mode=None)
        context.user_data.pop('state', None)
        return
    finally:
        if conn: conn.close() # Close connection if opened
    if 'new_discount_info' not in context.user_data: context.user_data['new_discount_info'] = {}
    context.user_data['new_discount_info']['code'] = code_text
    context.user_data['state'] = 'awaiting_discount_type'
    keyboard = [
        [InlineKeyboardButton("％ Percentage", callback_data="adm_set_discount_type|percentage"),
         InlineKeyboardButton("€ Fixed Amount", callback_data="adm_set_discount_type|fixed")],
        [InlineKeyboardButton("❌ Cancel", callback_data="adm_manage_discounts")]
    ]
    prompt_msg = f"Code set to: {code_text}\n\nSelect the discount type:"
    if query:
        try: await query.edit_message_text(prompt_msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=None)
        except telegram_error.BadRequest: await query.answer() # Ignore if not modified
    else: await send_message_with_retry(context.bot, chat_id, prompt_msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=None)


async def handle_adm_discount_code_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the admin entering the discount code text via message."""
    user_id = update.effective_user.id
    if user_id != ADMIN_ID: return
    if context.user_data.get("state") != "awaiting_discount_code": return
    if not update.message or not update.message.text: return
    code_text = update.message.text.strip()
    await process_discount_code_input(update, context, code_text)


async def handle_adm_discount_value_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the admin entering the discount value and saves the code."""
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    if user_id != ADMIN_ID: return
    if context.user_data.get("state") != "awaiting_discount_value": return
    if not update.message or not update.message.text: return
    value_text = update.message.text.strip().replace(',', '.')
    discount_info = context.user_data.get('new_discount_info', {})
    code = discount_info.get('code'); dtype = discount_info.get('type')
    if not code or not dtype:
        await send_message_with_retry(context.bot, chat_id, "❌ Error: Discount context lost.", parse_mode=None)
        context.user_data.pop("state", None); context.user_data.pop("new_discount_info", None)
        return
    conn = None # Initialize conn
    try:
        value = float(value_text)
        if value <= 0: raise ValueError("Discount value must be positive.")
        if dtype == 'percentage' and (value > 100): raise ValueError("Percentage cannot exceed 100.")
        conn = get_db_connection() # Use helper
        c = conn.cursor()
        c.execute("INSERT INTO discount_codes (code, discount_type, value, created_date, is_active) VALUES (?, ?, ?, ?, 1)",
                  (code, dtype, value, datetime.now(timezone.utc).isoformat())) # Use UTC Time
        conn.commit()
        logger.info(f"Admin {user_id} added discount code: {code} ({dtype}, {value})")
        context.user_data.pop("state", None); context.user_data.pop("new_discount_info", None)
        await send_message_with_retry(context.bot, chat_id, f"✅ Discount code '{code}' added!", parse_mode=None)
        keyboard = [[InlineKeyboardButton("🏷️ View Discount Codes", callback_data="adm_manage_discounts")]]
        await send_message_with_retry(context.bot, chat_id, "Returning to discount management.", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=None)
    except ValueError as e:
        await send_message_with_retry(context.bot, chat_id, f"❌ Invalid Value: {e}. Enter valid positive number.", parse_mode=None)
    except sqlite3.Error as e:
        logger.error(f"DB error saving discount code '{code}': {e}", exc_info=True)
        if conn and conn.in_transaction: conn.rollback()
        await send_message_with_retry(context.bot, chat_id, "❌ Database error saving code.", parse_mode=None)
        context.user_data.pop("state", None); context.user_data.pop("new_discount_info", None)
    finally:
        if conn: conn.close() # Close connection if opened


# --- Message Handler for Broadcast Inactive Days ---
async def handle_adm_broadcast_inactive_days_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the admin entering the number of days for inactive broadcast."""
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    if user_id != ADMIN_ID: return
    if context.user_data.get("state") != 'awaiting_broadcast_inactive_days': return
    if not update.message or not update.message.text: return

    lang, lang_data = _get_lang_data(context) # Use helper
    invalid_days_msg = lang_data.get("broadcast_invalid_days", "❌ Invalid number of days. Please enter a positive whole number.")
    days_too_large_msg = lang_data.get("broadcast_days_too_large", "❌ Number of days is too large. Please enter a smaller number.")

    try:
        days = int(update.message.text.strip())
        if days <= 0:
            await send_message_with_retry(context.bot, chat_id, invalid_days_msg, parse_mode=None)
            return # Keep state
        if days > 365 * 5: # Arbitrary limit to prevent nonsense
            await send_message_with_retry(context.bot, chat_id, days_too_large_msg, parse_mode=None)
            return # Keep state

        context.user_data['broadcast_target_value'] = days
        context.user_data['state'] = 'awaiting_broadcast_message' # Change state

        ask_msg_text = lang_data.get("broadcast_ask_message", "📝 Now send the message content (text, photo, video, or GIF with caption):")
        keyboard = [[InlineKeyboardButton("❌ Cancel Broadcast", callback_data="cancel_broadcast")]]
        await send_message_with_retry(context.bot, chat_id, f"Targeting users inactive for >= {days} days.\n\n{ask_msg_text}", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=None)

    except ValueError:
        await send_message_with_retry(context.bot, chat_id, invalid_days_msg, parse_mode=None)
        return # Keep state

# --- Message Handler for Broadcast Content ---
async def handle_adm_broadcast_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles receiving the message content for the broadcast, AFTER target is set."""
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    if user_id != ADMIN_ID: return
    if context.user_data.get("state") != 'awaiting_broadcast_message': return
    if not update.message: return

    lang, lang_data = _get_lang_data(context) # Use helper

    text = (update.message.text or update.message.caption or "").strip()
    media_file_id, media_type = None, None
    if update.message.photo: media_file_id, media_type = update.message.photo[-1].file_id, "photo"
    elif update.message.video: media_file_id, media_type = update.message.video.file_id, "video"
    elif update.message.animation: media_file_id, media_type = update.message.animation.file_id, "gif"

    if not text and not media_file_id:
        await send_message_with_retry(context.bot, chat_id, "Broadcast message cannot be empty. Please send text or media.", parse_mode=None)
        return

    target_type = context.user_data.get('broadcast_target_type', 'all')
    target_value = context.user_data.get('broadcast_target_value')

    context.user_data['broadcast_content'] = {
        'text': text, 'media_file_id': media_file_id, 'media_type': media_type,
        'target_type': target_type, 'target_value': target_value
    }
    context.user_data.pop('state', None)

    confirm_title = lang_data.get("broadcast_confirm_title", "📢 Confirm Broadcast")
    target_desc = lang_data.get("broadcast_confirm_target_all", "Target: All Users")
    if target_type == 'city': target_desc = lang_data.get("broadcast_confirm_target_city", "Target: Last Purchase in {city}").format(city=target_value)
    elif target_type == 'status': target_desc = lang_data.get("broadcast_confirm_target_status", "Target: Status - {status}").format(status=target_value)
    elif target_type == 'inactive': target_desc = lang_data.get("broadcast_confirm_target_inactive", "Target: Inactive >= {days} days").format(days=target_value)

    preview_label = lang_data.get("broadcast_confirm_preview", "Preview:")
    preview_msg = f"{confirm_title}\n\n{target_desc}\n\n{preview_label}\n"
    if media_file_id: preview_msg += f"{media_type.capitalize()} attached\n"
    text_preview = text[:500] + ('...' if len(text) > 500 else '')
    preview_msg += text_preview if text else "(No text)"
    preview_msg += f"\n\n{lang_data.get('broadcast_confirm_ask', 'Send this message?')}"

    keyboard = [
        [InlineKeyboardButton("✅ Yes, Send Broadcast", callback_data="confirm_broadcast")],
        [InlineKeyboardButton("❌ No, Cancel", callback_data="cancel_broadcast")]
    ]
    await send_message_with_retry(context.bot, chat_id, preview_msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=None)


# --- Message Handlers for Welcome Message Management ---

async def handle_adm_welcome_template_name_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles admin entering the name for a new welcome template."""
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    if user_id != ADMIN_ID or context.user_data.get("state") != 'awaiting_welcome_template_name': return
    if not update.message or not update.message.text: return

    template_name = update.message.text.strip()
    lang, lang_data = _get_lang_data(context) # Use helper

    if not template_name or len(template_name) > 50 or '|' in template_name:
        await send_message_with_retry(context.bot, chat_id, "❌ Invalid name. Please use a short, unique name without '|' (max 50 chars).")
        return # Keep state

    # Check if name exists
    templates = get_welcome_message_templates()
    if any(t['name'] == template_name for t in templates):
        exists_msg = lang_data.get("welcome_add_name_exists", "❌ Error: A template with the name '{name}' already exists.")
        await send_message_with_retry(context.bot, chat_id, exists_msg.format(name=template_name))
        return # Keep state

    # Store name and ask for text
    context.user_data['pending_welcome_template'] = {'name': template_name, 'is_editing': False}
    context.user_data['state'] = 'awaiting_welcome_template_text'

    placeholders = "`{username}`, `{status}`, `{progress_bar}`, `{balance_str}`, `{purchases}`, `{basket_count}`"
    prompt_template = lang_data.get("welcome_add_text_prompt", "Template Name: {name}\n\nPlease reply with the full welcome message text. Available placeholders:\n{placeholders}")
    prompt = prompt_template.format(name=template_name, placeholders=placeholders.replace('`','')) # Plain text display
    keyboard = [[InlineKeyboardButton("❌ Cancel", callback_data="adm_manage_welcome|0")]] # Back to first page

    await send_message_with_retry(context.bot, chat_id, prompt, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=None)

async def handle_adm_welcome_template_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles admin entering the text for a new/edited welcome template."""
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    current_state = context.user_data.get("state")
    if user_id != ADMIN_ID or current_state not in ['awaiting_welcome_template_text', 'awaiting_welcome_template_edit']: return
    if not update.message or not update.message.text: return

    template_text = update.message.text # Keep raw text
    lang, lang_data = _get_lang_data(context) # Use helper

    if len(template_text) > 3500: # Keep below Telegram limit
        await send_message_with_retry(context.bot, chat_id, "❌ Template text too long (max ~3500 chars). Please shorten it.")
        return # Keep state

    if 'pending_welcome_template' not in context.user_data:
        # This might happen if the state wasn't cleaned up properly, try to recover
        if current_state == 'awaiting_welcome_template_edit':
            name = context.user_data.get('editing_welcome_template_name')
            if name:
                context.user_data['pending_welcome_template'] = {'name': name, 'is_editing': True}
                logger.warning("Recovered pending_welcome_template context for editing.")
            else:
                 logger.error("State is awaiting_welcome_template_edit but name is missing and cannot recover.")
                 await send_message_with_retry(context.bot, chat_id, "❌ Error: Context lost. Please start again.", parse_mode=None)
                 context.user_data.pop('state', None)
                 return
        else:
            logger.error("State is awaiting_welcome_template_text but pending_welcome_template missing.")
            await send_message_with_retry(context.bot, chat_id, "❌ Error: Context lost. Please start again.", parse_mode=None)
            context.user_data.pop('state', None)
            return

    # Store the text
    context.user_data['pending_welcome_template']['text'] = template_text

    # Determine if adding or editing
    is_editing = (current_state == 'awaiting_welcome_template_edit')
    context.user_data['pending_welcome_template']['is_editing'] = is_editing

    if not is_editing:
        # If adding new, now ask for description
        context.user_data['state'] = 'awaiting_welcome_description'
        prompt_template = lang_data.get("welcome_add_description_prompt", "Optional: Enter a short description for this template (admin view only). Send '-' to skip.")
        template_name = context.user_data.get('pending_welcome_template',{}).get('name', 'New Template')
        prompt = f"Text for '{template_name}' received.\n\n{prompt_template}"
        offset = context.user_data.get('editing_welcome_offset', 0) # Use offset if available (though unlikely for add)
        keyboard = [[InlineKeyboardButton("❌ Cancel", callback_data=f"adm_manage_welcome|{offset}")]]
        await send_message_with_retry(context.bot, chat_id, prompt, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=None)
    else:
        # If editing text, show preview directly
        context.user_data.pop('state', None) # Clear current state before showing preview
        # Fetch description to include in preview
        template_name = context.user_data.get('pending_welcome_template', {}).get('name')
        if template_name:
            conn = None; current_desc = ""
            try:
                conn = get_db_connection(); c = conn.cursor()
                c.execute("SELECT description FROM welcome_messages WHERE name = ?", (template_name,))
                row = c.fetchone(); current_desc = row['description'] if row else ""
            except Exception as e: logger.error(f"Error fetching desc for preview: {e}")
            finally:
                 if conn: conn.close()
            context.user_data['pending_welcome_template']['description'] = current_desc # Add existing desc for preview
        await _show_welcome_preview(update, context)

# <<< NEW >>>
async def handle_adm_welcome_description_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the description for a NEW welcome template."""
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    if user_id != ADMIN_ID or context.user_data.get("state") != 'awaiting_welcome_description': return
    if not update.message or not update.message.text: return

    description = update.message.text.strip()
    if description == '-': description = None # Treat '-' as skip/None
    elif len(description) > 200:
        await send_message_with_retry(context.bot, chat_id, "❌ Description too long (max 200 chars).")
        return # Keep state

    if 'pending_welcome_template' not in context.user_data:
        logger.error("State is awaiting_welcome_description but pending data missing.")
        context.user_data.pop('state', None)
        await send_message_with_retry(context.bot, chat_id, "❌ Error: Context lost. Please start again.")
        return

    context.user_data['pending_welcome_template']['description'] = description
    context.user_data.pop('state', None) # Clear state before showing preview
    await _show_welcome_preview(update, context)

# <<< NEW >>>
async def handle_adm_welcome_description_edit_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the edited description for an EXISTING welcome template."""
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    if user_id != ADMIN_ID or context.user_data.get("state") != 'awaiting_welcome_description_edit': return
    if not update.message or not update.message.text: return

    new_description = update.message.text.strip()
    template_name = context.user_data.get('editing_welcome_template_name')

    if not template_name:
        logger.error("State is awaiting_welcome_description_edit but name is missing.")
        context.user_data.pop('state', None)
        context.user_data.pop("editing_welcome_template_name", None) # Clean up
        context.user_data.pop("editing_welcome_field", None)
        await send_message_with_retry(context.bot, chat_id, "❌ Error: Context lost. Please start again.")
        return

    if new_description == '-':
        # User wants to skip editing description, treat as cancel of this specific edit step
        offset = context.user_data.get('editing_welcome_offset', 0)
        await handle_adm_edit_welcome(update, context, params=[template_name, str(offset)])
        return

    if len(new_description) > 200:
        await send_message_with_retry(context.bot, chat_id, "❌ Description too long (max 200 chars).")
        return # Keep state

    # Fetch the existing text (needed because we only edited the description)
    conn_text = None; existing_text = ""
    try:
        conn_text = get_db_connection(); c_text = conn_text.cursor()
        c_text.execute("SELECT template_text FROM welcome_messages WHERE name = ?", (template_name,))
        row_text = c_text.fetchone()
        if row_text: existing_text = row_text['template_text']
        else: logger.warning(f"Could not fetch existing text for template {template_name} during desc edit.")
    except Exception as e: logger.error(f"Error fetching existing text: {e}")
    finally:
        if conn_text: conn_text.close()

    # Prepare data for preview
    context.user_data['pending_welcome_template'] = {
        'name': template_name,
        'text': existing_text, # Use existing text
        'description': new_description if new_description else None, # Store new description (or None)
        'is_editing': True, # It's an edit overall
        'offset': context.user_data.get('editing_welcome_offset', 0)
    }
    context.user_data.pop("state", None)
    context.user_data.pop("editing_welcome_template_name", None) # Clean up specific edit state
    context.user_data.pop("editing_welcome_field", None) # Clean up field indicator
    await _show_welcome_preview(update, context)
