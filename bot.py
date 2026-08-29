import os
import logging
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import psycopg2

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
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
# HEALTH CHECK SERVER
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
# DATABASE CONNECTION
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


# =========================================================
# DATABASE INITIALIZATION
# =========================================================

def initialize_database():

    logger.info("Connecting to PostgreSQL...")

    connection = None
    cursor = None

    try:

        connection = get_db_connection()
        cursor = connection.cursor()

        # -------------------------------------------------
        # USERS TABLE
        # -------------------------------------------------

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
# USER DATABASE FUNCTIONS
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
    # Save user in database
    # -----------------------------------------------------

    save_user(
        telegram_id=user.id,
        first_name=user.first_name,
        last_name=user.last_name,
        username=user.username,
    )

    # -----------------------------------------------------
    # Temporary welcome message
    # -----------------------------------------------------

    await update.message.reply_text(
        "🤖 PromptPilot\n\n"
        "Welcome!\n\n"
        "Your account has been registered successfully."
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
    # Check environment variables
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
    # Test / initialize database
    # -----------------------------------------------------

    initialize_database()

    # -----------------------------------------------------
    # Start HTTP server for Render
    # -----------------------------------------------------

    health_thread = threading.Thread(
        target=start_health_server,
        daemon=True,
    )

    health_thread.start()

    # -----------------------------------------------------
    # Telegram Application
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

    application.add_error_handler(
        error_handler
    )

    # -----------------------------------------------------
    # Start Bot
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
