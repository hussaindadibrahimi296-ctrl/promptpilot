import os
import logging
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import psycopg2

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)


# =========================================================
# SETTINGS
# =========================================================

BOT_TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")

PORT = int(os.getenv("PORT", "10000"))


# =========================================================
# LOGGING
# =========================================================

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

logger = logging.getLogger(__name__)


# =========================================================
# HEALTH SERVER
# =========================================================

class HealthHandler(BaseHTTPRequestHandler):

    def do_GET(self):

        self.send_response(200)

        self.send_header(
            "Content-Type",
            "text/plain; charset=utf-8"
        )

        self.end_headers()

        self.wfile.write(
            b"PromptPilot is running."
        )

    def log_message(self, format, *args):
        return


def start_health_server():

    server = HTTPServer(
        ("0.0.0.0", PORT),
        HealthHandler,
    )

    logger.info(
        "Health server running on port %s",
        PORT
    )

    server.serve_forever()


# =========================================================
# DATABASE
# =========================================================

def get_db_connection():

    if not DATABASE_URL:

        raise RuntimeError(
            "DATABASE_URL environment variable is missing."
        )

    return psycopg2.connect(
        DATABASE_URL,
        connect_timeout=10
    )


def initialize_database():

    logger.info("Connecting to PostgreSQL...")

    connection = None
    cursor = None

    try:

        connection = get_db_connection()
        cursor = connection.cursor()

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS users (

                telegram_id BIGINT PRIMARY KEY,

                first_name TEXT,

                last_name TEXT,

                username TEXT,

                language VARCHAR(10) DEFAULT 'en',

                is_blocked BOOLEAN DEFAULT FALSE,

                created_at TIMESTAMPTZ DEFAULT NOW(),

                last_active TIMESTAMPTZ DEFAULT NOW()

            );
            """
        )

        connection.commit()

        logger.info(
            "Database connected successfully."
        )

        logger.info(
            "Users table is ready."
        )

    except Exception:

        if connection:
            connection.rollback()

        logger.exception(
            "Database initialization failed."
        )

        raise

    finally:

        if cursor:
            cursor.close()

        if connection:
            connection.close()


# =========================================================
# SAVE / UPDATE USER
# =========================================================

def save_user(
    telegram_id,
    first_name,
    last_name,
    username,
):

    connection = None
    cursor = None

    try:

        connection = get_db_connection()
        cursor = connection.cursor()

        cursor.execute(
            """
            INSERT INTO users (
                telegram_id,
                first_name,
                last_name,
                username,
                last_active
            )

            VALUES (
                %s,
                %s,
                %s,
                %s,
                NOW()
            )

            ON CONFLICT (telegram_id)

            DO UPDATE SET

                first_name = EXCLUDED.first_name,
                last_name = EXCLUDED.last_name,
                username = EXCLUDED.username,
                last_active = NOW();
            """,
            (
                telegram_id,
                first_name,
                last_name,
                username,
            )
        )

        connection.commit()

        logger.info(
            "User %s saved successfully.",
            telegram_id
        )

    except Exception:

        if connection:
            connection.rollback()

        logger.exception(
            "Failed to save user."
        )

    finally:

        if cursor:
            cursor.close()

        if connection:
            connection.close()


# =========================================================
# GET USER LANGUAGE
# =========================================================

def get_user_language(telegram_id):

    connection = None
    cursor = None

    try:

        connection = get_db_connection()
        cursor = connection.cursor()

        cursor.execute(
            """
            SELECT language
            FROM users
            WHERE telegram_id = %s
            """,
            (telegram_id,)
        )

        result = cursor.fetchone()

        if result and result[0]:

            return result[0]

        return "en"

    except Exception:

        logger.exception(
            "Failed to get user language."
        )

        return "en"

    finally:

        if cursor:
            cursor.close()

        if connection:
            connection.close()


# =========================================================
# UPDATE USER LANGUAGE
# =========================================================

def update_user_language(
    telegram_id,
    language
):

    connection = None
    cursor = None

    try:

        connection = get_db_connection()
        cursor = connection.cursor()

        cursor.execute(
            """
            UPDATE users

            SET
                language = %s,
                last_active = NOW()

            WHERE telegram_id = %s
            """,
            (
                language,
                telegram_id,
            )
        )

        connection.commit()

        logger.info(
            "User %s language changed to %s.",
            telegram_id,
            language
        )

        return True

    except Exception:

        if connection:
            connection.rollback()

        logger.exception(
            "Failed to update language."
        )

        return False

    finally:

        if cursor:
            cursor.close()

        if connection:
            connection.close()


# =========================================================
# LANGUAGE SELECTION KEYBOARD
# =========================================================

def language_keyboard():

    keyboard = [

        [
            InlineKeyboardButton(
                "🇦🇫 فارسی",
                callback_data="lang_fa"
            )
        ],

        [
            InlineKeyboardButton(
                "🇬🇧 English",
                callback_data="lang_en"
            )
        ],

        [
            InlineKeyboardButton(
                "🇸🇦 العربية",
                callback_data="lang_ar"
            )
        ],

    ]

    return InlineKeyboardMarkup(keyboard)


# =========================================================
# LANGUAGE SELECTION TEXT
# =========================================================

LANGUAGE_SELECTION_TEXT = {

    "fa":
        "🤖 PromptPilot\n\n"
        "زبان خود را انتخاب کنید:",

    "en":
        "🤖 PromptPilot\n\n"
        "Choose your language:",

    "ar":
        "🤖 PromptPilot\n\n"
        "اختر لغتك:",

}


# =========================================================
# MAIN MENU PLACEHOLDER
# =========================================================

def get_main_menu_text(language):

    if language == "fa":

        return (
            "🤖 PromptPilot\n\n"
            "👋 خوش آمدید!\n\n"
            "PromptPilot به شما کمک می‌کند "
            "ایده‌های ساده خود را به Promptهای "
            "حرفه‌ای برای ابزارهای AI تبدیل کنید.\n\n"
            "👇 یک قابلیت را انتخاب کنید:"
        )

    if language == "ar":

        return (
            "🤖 PromptPilot\n\n"
            "👋 مرحباً بك!\n\n"
            "يساعدك PromptPilot على تحويل أفكارك "
            "البسيطة إلى Prompts احترافية لأدوات الذكاء الاصطناعي.\n\n"
            "👇 اختر إحدى الميزات:"
        )

    return (
        "🤖 PromptPilot\n\n"
        "👋 Welcome!\n\n"
        "PromptPilot helps you turn simple ideas "
        "into professional prompts for AI tools.\n\n"
        "👇 Choose a feature:"
    )


# =========================================================
# TEMPORARY MAIN MENU
# =========================================================

def main_menu_keyboard():

    keyboard = [

        [
            InlineKeyboardButton(
                "🧠 Prompt Generator",
                callback_data="feature_generator"
            )
        ],

        [
            InlineKeyboardButton(
                "🔥 Prompt Improver",
                callback_data="feature_improver"
            )
        ],

    ]

    return InlineKeyboardMarkup(keyboard)


# =========================================================
# SHOW LANGUAGE SELECTION
# =========================================================

async def show_language_selection(
    update: Update
):

    if update.message:

        await update.message.reply_text(
            LANGUAGE_SELECTION_TEXT["en"],
            reply_markup=language_keyboard()
        )


# =========================================================
# START COMMAND
# =========================================================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    user = update.effective_user

    if not user:
        return

    # -----------------------------------------------------
    # Save user
    # -----------------------------------------------------

    save_user(
        telegram_id=user.id,
        first_name=user.first_name,
        last_name=user.last_name,
        username=user.username,
    )

    # -----------------------------------------------------
    # Always show language selection on /start
    # -----------------------------------------------------

    await show_language_selection(update)


# =========================================================
# LANGUAGE CALLBACK
# =========================================================

async def language_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    query = update.callback_query

    if not query:
        return

    await query.answer()

    user = query.from_user

    data = query.data

    # -----------------------------------------------------
    # Determine language
    # -----------------------------------------------------

    if data == "lang_fa":

        language = "fa"

    elif data == "lang_en":

        language = "en"

    elif data == "lang_ar":

        language = "ar"

    else:

        return

    # -----------------------------------------------------
    # Save language
    # -----------------------------------------------------

    success = update_user_language(
        user.id,
        language
    )

    if not success:

        await query.edit_message_text(
            "❌ Database error. Please try again."
        )

        return

    # -----------------------------------------------------
    # Show main menu
    # -----------------------------------------------------

    await query.edit_message_text(
        get_main_menu_text(language),
        reply_markup=main_menu_keyboard()
    )


# =========================================================
# FEATURE CALLBACK - TEMPORARY
# =========================================================

async def feature_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    query = update.callback_query

    if not query:
        return

    await query.answer()

    language = get_user_language(
        query.from_user.id
    )

    if language == "fa":

        text = (
            "⏳ این قابلیت در مرحله بعد "
            "فعال خواهد شد."
        )

    elif language == "ar":

        text = (
            "⏳ هذه الميزة سيتم تفعيلها "
            "في المرحلة التالية."
        )

    else:

        text = (
            "⏳ This feature will be activated "
            "in the next step."
        )

    await query.answer()

    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "🏠 Main Menu",
                        callback_data="back_main"
                    )
                ]
            ]
        )
    )


# =========================================================
# BACK TO MAIN MENU
# =========================================================

async def back_main_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    query = update.callback_query

    if not query:
        return

    await query.answer()

    language = get_user_language(
        query.from_user.id
    )

    await query.edit_message_text(
        get_main_menu_text(language),
        reply_markup=main_menu_keyboard()
    )


# =========================================================
# ERROR HANDLER
# =========================================================

async def error_handler(
    update: object,
    context: ContextTypes.DEFAULT_TYPE,
):

    logger.error(
        "Telegram error: %s",
        context.error
    )


# =========================================================
# MAIN
# =========================================================

def main():

    # -----------------------------------------------------
    # Environment checks
    # -----------------------------------------------------

    if not BOT_TOKEN:

        raise RuntimeError(
            "BOT_TOKEN environment variable is missing."
        )

    if not DATABASE_URL:

        raise RuntimeError(
            "DATABASE_URL environment variable is missing."
        )

    # -----------------------------------------------------
    # Initialize database
    # -----------------------------------------------------

    initialize_database()

    # -----------------------------------------------------
    # Start Render health server
    # -----------------------------------------------------

    health_thread = threading.Thread(
        target=start_health_server,
        daemon=True,
    )

    health_thread.start()

    # -----------------------------------------------------
    # Telegram application
    # -----------------------------------------------------

    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .build()
    )

    # -----------------------------------------------------
    # Handlers
    # -----------------------------------------------------

    application.add_handler(
        CommandHandler(
            "start",
            start
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            language_callback,
            pattern=r"^lang_(fa|en|ar)$"
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            feature_callback,
            pattern=r"^feature_"
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            back_main_callback,
            pattern=r"^back_main$"
        )
    )

    application.add_error_handler(
        error_handler
    )

    # -----------------------------------------------------
    # Start
    # -----------------------------------------------------

    logger.info(
        "PromptPilot is starting..."
    )

    application.run_polling()


# =========================================================
# RUN
# =========================================================

if __name__ == "__main__":

    main()
