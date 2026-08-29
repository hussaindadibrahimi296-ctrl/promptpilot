import os
import logging
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import psycopg2
from google import genai

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)


# =========================================================
# SETTINGS
# =========================================================

BOT_TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

GEMINI_MODEL = "gemini-3.7-flash"

gemini_client = None

if GEMINI_API_KEY:
    gemini_client = genai.Client(
        api_key=GEMINI_API_KEY
    )

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

LANGUAGE_SELECTION_TEXT = (
    "🤖 PromptPilot\n\n"
    "🌐 زبان خود را انتخاب کنید\n"
    "Choose your language\n"
    "اختر لغتك:"
)


# =========================================================
# MAIN MENU TEXT
# =========================================================

def get_main_menu_text(language):

    if language == "fa":

        return (
            "🤖 <b>PromptPilot</b>\n\n"
            "👋 خوش آمدید!\n\n"
            "PromptPilot به شما کمک می‌کند ایده‌های ساده "
            "خود را به Promptهای حرفه‌ای برای ابزارهای "
            "هوش مصنوعی تبدیل کنید.\n\n"
            "می‌توانید تصویر، ویدیو، موسیقی، متن، تبلیغات، "
            "کدنویسی و انواع کارهای دیگر را به یک Prompt "
            "دقیق و حرفه‌ای تبدیل کنید.\n\n"
            "👇 یک قابلیت را انتخاب کنید:"
        )

    if language == "ar":

        return (
            "🤖 <b>PromptPilot</b>\n\n"
            "👋 مرحباً بك!\n\n"
            "يساعدك PromptPilot على تحويل أفكارك البسيطة "
            "إلى Prompts احترافية لأدوات الذكاء الاصطناعي.\n\n"
            "يمكنك إنشاء Prompts للصور والفيديو والموسيقى "
            "والنصوص والإعلانات والبرمجة وغيرها.\n\n"
            "👇 اختر إحدى الميزات:"
        )

    return (
        "🤖 <b>PromptPilot</b>\n\n"
        "👋 Welcome!\n\n"
        "PromptPilot helps you turn simple ideas into "
        "professional prompts for AI tools.\n\n"
        "You can create prompts for images, videos, "
        "music, text, advertising, coding and many "
        "other tasks.\n\n"
        "👇 Choose a feature:"
    )


# =========================================================
# MAIN MENU KEYBOARD
# =========================================================

def main_menu_keyboard(language):

    if language == "fa":

        keyboard = [

            [
                InlineKeyboardButton(
                    "🧠 تولید Prompt",
                    callback_data="feature_generator"
                )
            ],

            [
                InlineKeyboardButton(
                    "🔥 بهبود Prompt",
                    callback_data="feature_improver"
                )
            ],

            [
                InlineKeyboardButton(
                    "🩺 Prompt Doctor",
                    callback_data="feature_doctor"
                )
            ],

            [
                InlineKeyboardButton(
                    "🎯 AI Detector",
                    callback_data="feature_detector"
                )
            ],

            [
                InlineKeyboardButton(
                    "🖼️ Image Prompt",
                    callback_data="feature_image"
                )
            ],

            [
                InlineKeyboardButton(
                    "🎬 Video Prompt",
                    callback_data="feature_video"
                )
            ],

            [
                InlineKeyboardButton(
                    "🌍 ایده → Prompt حرفه‌ای",
                    callback_data="feature_pro"
                )
            ],

            [
                InlineKeyboardButton(
                    "🔄 Prompt Remix",
                    callback_data="feature_remix"
                )
            ],

        ]

    elif language == "ar":

        keyboard = [

            [
                InlineKeyboardButton(
                    "🧠 إنشاء Prompt",
                    callback_data="feature_generator"
                )
            ],

            [
                InlineKeyboardButton(
                    "🔥 تحسين Prompt",
                    callback_data="feature_improver"
                )
            ],

            [
                InlineKeyboardButton(
                    "🩺 طبيب Prompt",
                    callback_data="feature_doctor"
                )
            ],

            [
                InlineKeyboardButton(
                    "🎯 كاشف الذكاء الاصطناعي",
                    callback_data="feature_detector"
                )
            ],

            [
                InlineKeyboardButton(
                    "🖼️ Prompt للصور",
                    callback_data="feature_image"
                )
            ],

            [
                InlineKeyboardButton(
                    "🎬 Prompt للفيديو",
                    callback_data="feature_video"
                )
            ],

            [
                InlineKeyboardButton(
                    "🌍 فكرة → Prompt احترافي",
                    callback_data="feature_pro"
                )
            ],

            [
                InlineKeyboardButton(
                    "🔄 إعادة صياغة Prompt",
                    callback_data="feature_remix"
                )
            ],

        ]

    else:

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

            [
                InlineKeyboardButton(
                    "🩺 Prompt Doctor",
                    callback_data="feature_doctor"
                )
            ],

            [
                InlineKeyboardButton(
                    "🎯 AI Detector",
                    callback_data="feature_detector"
                )
            ],

            [
                InlineKeyboardButton(
                    "🖼️ Image Prompt",
                    callback_data="feature_image"
                )
            ],

            [
                InlineKeyboardButton(
                    "🎬 Video Prompt",
                    callback_data="feature_video"
                )
            ],

            [
                InlineKeyboardButton(
                    "🌍 Idea → Pro Prompt",
                    callback_data="feature_pro"
                )
            ],

            [
                InlineKeyboardButton(
                    "🔄 Prompt Remix",
                    callback_data="feature_remix"
                )
            ],

        ]

    return InlineKeyboardMarkup(keyboard)


# =========================================================
# COMMON NAVIGATION
# =========================================================

def back_main_keyboard(language):

    label = {
        "fa": "🏠 منوی اصلی",
        "en": "🏠 Main Menu",
        "ar": "🏠 القائمة الرئيسية",
    }

    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    label.get(language, label["en"]),
                    callback_data="back_main"
                )
            ]
        ]
    )


# =========================================================
# FEATURE INFORMATION
# =========================================================

FEATURE_INFO = {

    "generator": {

        "fa": (
            "🧠 <b>تولید Prompt</b>\n\n"
            "این بخش عمومی است.\n\n"
            "می‌توانی هر ایده‌ای را برای ما بفرستی؛ "
            "مثلاً برای تصویر، ویدیو، موسیقی، متن، "
            "تبلیغات، کدنویسی یا هر کار دیگری.\n\n"
            "💡 هرچه ایده و جزئیات بیشتری بدهی، "
            "Prompt نهایی می‌تواند دقیق‌تر و حرفه‌ای‌تر باشد.\n\n"
            "❌ <b>نمونه ایده ضعیف:</b>\n"
            "یک ماشین زیبا\n\n"
            "✅ <b>نمونه ایده بهتر:</b>\n"
            "یک ماشین اسپرت مشکی در خیابان‌های توکیو "
            "در شب، هنگام بارندگی، با نورهای نئون و "
            "نمای سینمایی.\n\n"
            "بعد از ارسال ایده، می‌توانی ابزار مورد "
            "نظرت را مشخص کنی تا Prompt متناسب با آن ساخته شود.\n\n"
            "✍️ حالا ایده خود را بفرست:"
        ),

        "en": (
            "🧠 <b>Prompt Generator</b>\n\n"
            "This is the general-purpose prompt section.\n\n"
            "You can send an idea for an image, video, "
            "music, text, advertising, coding or almost "
            "any other task.\n\n"
            "💡 The more useful details you provide, "
            "the more precise and professional the final "
            "prompt can be.\n\n"
            "❌ <b>Weak idea:</b>\n"
            "A beautiful car\n\n"
            "✅ <b>Better idea:</b>\n"
            "A black sports car driving through Tokyo "
            "at night during rainfall, surrounded by "
            "neon lights with a cinematic look.\n\n"
            "After sending your idea, you can specify "
            "the AI tool you want to use.\n\n"
            "✍️ Send your idea:"
        ),

        "ar": (
            "🧠 <b>إنشاء Prompt</b>\n\n"
            "هذا القسم عام ويمكن استخدامه لأي نوع من المهام.\n\n"
            "يمكنك إرسال فكرة لصورة أو فيديو أو موسيقى "
            "أو نص أو إعلان أو برمجة أو أي مهمة أخرى.\n\n"
            "💡 كلما قدمت تفاصيل أكثر، أصبح الـ Prompt "
            "أكثر دقة واحترافية.\n\n"
            "❌ <b>فكرة ضعيفة:</b>\n"
            "سيارة جميلة\n\n"
            "✅ <b>فكرة أفضل:</b>\n"
            "سيارة رياضية سوداء في شوارع طوكيو ليلاً "
            "أثناء المطر، مع أضواء نيون ومظهر سينمائي.\n\n"
            "بعد إرسال فكرتك يمكنك تحديد أداة الذكاء "
            "الاصطناعي التي تريد استخدامها.\n\n"
            "✍️ أرسل فكرتك:"
        ),
    },


    "improver": {

        "fa": (
            "🔥 <b>بهبود Prompt</b>\n\n"
            "یک Prompt معمولی یا ضعیف داری؟ آن را بفرست.\n\n"
            "منطق این بخش این است که Prompt از نظر "
            "وضوح، جزئیات، زمینه، هدف، ساختار و نتیجه "
            "مورد انتظار بهتر شود.\n\n"
            "❌ <b>نمونه ضعیف:</b>\n"
            "make a cool car\n\n"
            "✅ <b>نمونه بهتر:</b>\n"
            "Create a cinematic, photorealistic scene "
            "of a luxury sports car...\n\n"
            "💡 اگر ابزار مورد استفاده‌ات را هم مشخص کنی، "
            "Prompt می‌تواند متناسب با همان ابزار تنظیم شود.\n\n"
            "✍️ Prompt خود را بفرست:"
        ),

        "en": (
            "🔥 <b>Prompt Improver</b>\n\n"
            "Have a weak or basic prompt? Send it here.\n\n"
            "The prompt can be improved for clarity, "
            "detail, context, goal, structure and expected output.\n\n"
            "❌ <b>Weak example:</b>\n"
            "make a cool car\n\n"
            "✅ <b>Better example:</b>\n"
            "Create a cinematic, photorealistic scene "
            "of a luxury sports car...\n\n"
            "💡 You can also specify the AI tool you want "
            "to use so the prompt can be adapted to it.\n\n"
            "✍️ Send your prompt:"
        ),

        "ar": (
            "🔥 <b>تحسين Prompt</b>\n\n"
            "هل لديك Prompt ضعيف أو عادي؟ أرسله هنا.\n\n"
            "يمكن تحسينه من حيث الوضوح والتفاصيل والسياق "
            "والهدف والبنية والنتيجة المطلوبة.\n\n"
            "❌ <b>مثال ضعيف:</b>\n"
            "make a cool car\n\n"
            "✅ <b>مثال أفضل:</b>\n"
            "Create a cinematic, photorealistic scene "
            "of a luxury sports car...\n\n"
            "💡 يمكنك أيضاً تحديد أداة الذكاء الاصطناعي "
            "حتى يتم تكييف الـ Prompt معها.\n\n"
            "✍️ أرسل Prompt:"
        ),
    },


    "doctor": {

        "fa": (
            "🩺 <b>Prompt Doctor</b>\n\n"
            "این بخش Prompt تو را بررسی می‌کند و کیفیت "
            "آن را از جنبه‌های مختلف ارزیابی می‌کند.\n\n"
            "مثلاً:\n"
            "🎯 هدف\n"
            "📝 وضوح\n"
            "🔍 جزئیات\n"
            "🎨 سبک\n"
            "⚙️ ساختار\n\n"
            "سپس مشکلات Prompt مشخص می‌شود و می‌توان "
            "نسخه بهتر آن را ساخت.\n\n"
            "❌ <b>نمونه ضعیف:</b>\n"
            "a house\n\n"
            "✅ <b>نمونه بهتر:</b>\n"
            "A modern coastal house with large glass walls, "
            "located beside the ocean at sunset...\n\n"
            "✍️ Prompt خود را برای بررسی بفرست:"
        ),

        "en": (
            "🩺 <b>Prompt Doctor</b>\n\n"
            "This feature checks your prompt and evaluates "
            "its quality from multiple dimensions.\n\n"
            "For example:\n"
            "🎯 Goal\n"
            "📝 Clarity\n"
            "🔍 Detail\n"
            "🎨 Style\n"
            "⚙️ Structure\n\n"
            "It then identifies problems and can create "
            "a stronger version.\n\n"
            "❌ <b>Weak example:</b>\n"
            "a house\n\n"
            "✅ <b>Better example:</b>\n"
            "A modern coastal house with large glass walls, "
            "located beside the ocean at sunset...\n\n"
            "✍️ Send your prompt for analysis:"
        ),

        "ar": (
            "🩺 <b>طبيب Prompt</b>\n\n"
            "يفحص هذا القسم الـ Prompt ويقيّم جودته "
            "من عدة جوانب.\n\n"
            "مثلاً:\n"
            "🎯 الهدف\n"
            "📝 الوضوح\n"
            "🔍 التفاصيل\n"
            "🎨 الأسلوب\n"
            "⚙️ البنية\n\n"
            "ثم يحدد المشاكل ويمكنه إنشاء نسخة أفضل.\n\n"
            "❌ <b>مثال ضعيف:</b>\n"
            "a house\n\n"
            "✅ <b>مثال أفضل:</b>\n"
            "A modern coastal house with large glass walls, "
            "located beside the ocean at sunset...\n\n"
            "✍️ أرسل Prompt للتحليل:"
        ),
    },


    "detector": {

        "fa": (
            "🎯 <b>AI Detector / Recommender</b>\n\n"
            "این بخش برای تشخیص این است که برای کاری "
            "که می‌خواهی انجام بدهی، چه نوع ابزار و "
            "چه سبک Prompt مناسب‌تر است.\n\n"
            "مثلاً اگر بگویی:\n"
            "«می‌خواهم یک ویدیوی تبلیغاتی بسازم.»\n\n"
            "سیستم می‌تواند ابزارها و روش مناسب را پیشنهاد کند.\n\n"
            "💡 اگر ابزار مورد نظرت را نمی‌دانی، مشکلی نیست؛ "
            "سیستم می‌تواند پیشنهاد بدهد.\n\n"
            "✍️ کاری را که می‌خواهی انجام بدهی توضیح بده:"
        ),

        "en": (
            "🎯 <b>AI Detector / Recommender</b>\n\n"
            "This feature helps determine what type of AI "
            "tool and prompt style may be suitable for your task.\n\n"
            "For example:\n"
            "“I want to create a video advertisement.”\n\n"
            "The system can recommend suitable tools "
            "and a prompt approach.\n\n"
            "💡 If you don't know which tool to use, "
            "that's okay. A recommendation can be provided.\n\n"
            "✍️ Describe what you want to do:"
        ),

        "ar": (
            "🎯 <b>كاشف / مقترح أدوات الذكاء الاصطناعي</b>\n\n"
            "تساعدك هذه الميزة على معرفة نوع أداة الذكاء "
            "الاصطناعي وأسلوب الـ Prompt المناسب لمهمتك.\n\n"
            "مثلاً:\n"
            "«أريد إنشاء فيديو إعلاني.»\n\n"
            "يمكن للنظام اقتراح الأدوات والأسلوب المناسب.\n\n"
            "💡 إذا كنت لا تعرف الأداة المناسبة، لا مشكلة؛ "
            "يمكن للنظام اقتراحها لك.\n\n"
            "✍️ اشرح ما الذي تريد القيام به:"
        ),
    },


    "image": {

        "fa": (
            "🖼️ <b>Image Prompt</b>\n\n"
            "این بخش مخصوص ساخت Prompt حرفه‌ای برای تصاویر است.\n\n"
            "سیستم روی مواردی مثل موضوع، محیط، نور، "
            "ترکیب‌بندی، دوربین، لنز، زاویه دید، حالت، "
            "رنگ، سبک، کیفیت و موارد منفی تمرکز می‌کند.\n\n"
            "❌ <b>نمونه ایده ضعیف:</b>\n"
            "یک خانه زیبا\n\n"
            "✅ <b>نمونه ایده بهتر:</b>\n"
            "یک خانه مدرن کنار اقیانوس هنگام غروب، "
            "با دیوارهای شیشه‌ای بزرگ، معماری مینیمال "
            "و نور گرم داخلی.\n\n"
            "💡 اگر ابزار تصویر را هم مشخص کنی، Prompt "
            "برای همان ابزار تنظیم می‌شود.\n\n"
            "✍️ ایده تصویر خود را بفرست:"
        ),

        "en": (
            "🖼️ <b>Image Prompt</b>\n\n"
            "This feature is designed specifically for "
            "professional image-generation prompts.\n\n"
            "It focuses on subject, environment, lighting, "
            "composition, camera, lens, perspective, mood, "
            "color, style, quality and negative elements.\n\n"
            "❌ <b>Weak idea:</b>\n"
            "A beautiful house\n\n"
            "✅ <b>Better idea:</b>\n"
            "A modern coastal house beside the ocean at sunset, "
            "featuring large glass walls, minimalist architecture "
            "and warm interior lighting.\n\n"
            "💡 You can specify the image tool so the prompt "
            "can be adapted to it.\n\n"
            "✍️ Send your image idea:"
        ),

        "ar": (
            "🖼️ <b>Prompt للصور</b>\n\n"
            "هذه الميزة مخصصة لإنشاء Prompts احترافية للصور.\n\n"
            "تركز على الموضوع والبيئة والإضاءة والتركيب "
            "والكاميرا والعدسة والمنظور والمزاج والألوان "
            "والأسلوب والجودة والعناصر السلبية.\n\n"
            "❌ <b>فكرة ضعيفة:</b>\n"
            "منزل جميل\n\n"
            "✅ <b>فكرة أفضل:</b>\n"
            "منزل عصري بجانب المحيط وقت الغروب، مع جدران "
            "زجاجية كبيرة وهندسة معمارية بسيطة وإضاءة داخلية دافئة.\n\n"
            "💡 يمكنك تحديد أداة الصور لتكييف الـ Prompt معها.\n\n"
            "✍️ أرسل فكرة الصورة:"
        ),
    },


    "video": {

        "fa": (
            "🎬 <b>Video Prompt</b>\n\n"
            "این بخش برای ساخت Prompt حرفه‌ای ویدیو است.\n\n"
            "سیستم روی صحنه، حرکت سوژه، حرکت دوربین، "
            "حرکت محیط، نور، سبک سینمایی، مدت زمان، "
            "ترکیب‌بندی و موارد منفی تمرکز می‌کند.\n\n"
            "❌ <b>نمونه ضعیف:</b>\n"
            "یک ماشین در برف حرکت می‌کند.\n\n"
            "✅ <b>نمونه بهتر:</b>\n"
            "A cinematic shot of a black sports car driving "
            "through a snowy mountain road while the camera "
            "slowly tracks alongside the vehicle...\n\n"
            "💡 مشخص کردن ابزار ویدیو باعث می‌شود Prompt "
            "متناسب با همان ابزار آماده شود.\n\n"
            "✍️ ایده ویدیوی خود را بفرست:"
        ),

        "en": (
            "🎬 <b>Video Prompt</b>\n\n"
            "This feature creates professional prompts for video generation.\n\n"
            "It focuses on scene, subject movement, camera movement, "
            "environment movement, lighting, cinematic style, duration, "
            "composition and negative elements.\n\n"
            "❌ <b>Weak idea:</b>\n"
            "A car drives in snow.\n\n"
            "✅ <b>Better idea:</b>\n"
            "A cinematic shot of a black sports car driving "
            "through a snowy mountain road while the camera "
            "slowly tracks alongside the vehicle...\n\n"
            "💡 Specifying the video tool helps adapt the prompt "
            "to that tool.\n\n"
            "✍️ Send your video idea:"
        ),

        "ar": (
            "🎬 <b>Prompt للفيديو</b>\n\n"
            "هذه الميزة مخصصة لإنشاء Prompts احترافية للفيديو.\n\n"
            "تركز على المشهد وحركة الشخص أو العنصر وحركة "
            "الكاميرا وحركة البيئة والإضاءة والأسلوب السينمائي "
            "والمدة والتركيب والعناصر السلبية.\n\n"
            "❌ <b>فكرة ضعيفة:</b>\n"
            "سيارة تتحرك في الثلج.\n\n"
            "✅ <b>فكرة أفضل:</b>\n"
            "A cinematic shot of a black sports car driving "
            "through a snowy mountain road while the camera "
            "slowly tracks alongside the vehicle...\n\n"
            "💡 تحديد أداة الفيديو يساعد على تكييف الـ Prompt معها.\n\n"
            "✍️ أرسل فكرة الفيديو:"
        ),
    },


    "pro": {

        "fa": (
            "🌍 <b>ایده → Prompt حرفه‌ای</b>\n\n"
            "ایده خود را به زبان خودت بنویس؛ فارسی، عربی "
            "یا انگلیسی.\n\n"
            "این بخش ترجمه ساده نیست. هدف این است که ایده "
            "تو به یک Prompt حرفه‌ای انگلیسی تبدیل شود.\n\n"
            "❌ <b>ایده ضعیف:</b>\n"
            "یک خانه کنار دریا\n\n"
            "✅ <b>ایده بهتر:</b>\n"
            "یک خانه مدرن کنار دریا هنگام غروب، در یک "
            "کشور گرم، با معماری مینیمال و پنجره‌های بزرگ.\n\n"
            "💡 هرچه توضیحات بیشتری بدهی، نتیجه دقیق‌تر خواهد بود.\n\n"
            "✍️ ایده خود را به هر زبانی که راحت هستی بفرست:"
        ),

        "en": (
            "🌍 <b>Idea → Professional Prompt</b>\n\n"
            "Write your idea in the language you are comfortable with.\n\n"
            "This is not simple translation. The goal is to "
            "turn your idea into a professional English prompt.\n\n"
            "❌ <b>Weak idea:</b>\n"
            "A house beside the sea\n\n"
            "✅ <b>Better idea:</b>\n"
            "A modern house beside the ocean at sunset, "
            "located in a warm coastal country, featuring "
            "minimalist architecture and large windows.\n\n"
            "💡 More useful details can produce a more precise result.\n\n"
            "✍️ Send your idea:"
        ),

        "ar": (
            "🌍 <b>فكرة → Prompt احترافي</b>\n\n"
            "اكتب فكرتك باللغة التي تشعر بالراحة معها.\n\n"
            "هذه ليست ترجمة عادية. الهدف هو تحويل فكرتك "
            "إلى Prompt احترافي باللغة الإنجليزية.\n\n"
            "❌ <b>فكرة ضعيفة:</b>\n"
            "منزل بجانب البحر\n\n"
            "✅ <b>فكرة أفضل:</b>\n"
            "منزل عصري بجانب المحيط وقت الغروب، في بلد ساحلي "
            "دافئ، مع هندسة بسيطة ونوافذ كبيرة.\n\n"
            "💡 كلما أضفت تفاصيل مفيدة، أصبحت النتيجة أكثر دقة.\n\n"
            "✍️ أرسل فكرتك:"
        ),
    },


    "remix": {

        "fa": (
            "🔄 <b>Prompt Remix</b>\n\n"
            "یک Prompt موجود را بفرست تا بتوانیم آن را "
            "در سبک‌های مختلف بازطراحی کنیم.\n\n"
            "سبک‌های پیشنهادی:\n"
            "🎬 سینمایی\n"
            "📷 واقع‌گرایانه\n"
            "🎨 هنری\n"
            "💡 خلاقانه\n"
            "💎 لوکس\n"
            "⚡ تبلیغاتی\n"
            "🌑 تاریک و دراماتیک\n"
            "✨ مینیمال\n\n"
            "💡 هدف این است که ایده اصلی حفظ شود اما "
            "نسخه‌های متفاوت و کاربردی ساخته شوند.\n\n"
            "✍️ Prompt خود را بفرست:"
        ),

        "en": (
            "🔄 <b>Prompt Remix</b>\n\n"
            "Send an existing prompt and create different "
            "versions of the same idea.\n\n"
            "Suggested styles:\n"
            "🎬 Cinematic\n"
            "📷 Photorealistic\n"
            "🎨 Artistic\n"
            "💡 Creative\n"
            "💎 Luxury\n"
            "⚡ Commercial\n"
            "🌑 Dark & Dramatic\n"
            "✨ Minimalist\n\n"
            "💡 The goal is to preserve the core idea while "
            "creating useful alternative versions.\n\n"
            "✍️ Send your prompt:"
        ),

        "ar": (
            "🔄 <b>إعادة صياغة Prompt</b>\n\n"
            "أرسل Prompt موجوداً لإنشاء نسخ مختلفة "
            "من الفكرة نفسها.\n\n"
            "الأساليب المقترحة:\n"
            "🎬 سينمائي\n"
            "📷 واقعي\n"
            "🎨 فني\n"
            "💡 إبداعي\n"
            "💎 فاخر\n"
            "⚡ إعلاني\n"
            "🌑 مظلم ودرامي\n"
            "✨ بسيط\n\n"
            "💡 الهدف هو الحفاظ على الفكرة الأساسية مع "
            "إنشاء نسخ مختلفة ومفيدة.\n\n"
            "✍️ أرسل Prompt:"
        ),
    },

}


# =========================================================
# GEMINI FEATURE ENGINES
# =========================================================

GEMINI_FEATURE_PROMPTS = {

    "generator": """
You are PromptPilot's General Prompt Generator.

Transform the user's idea into a highly professional,
production-ready prompt for the selected AI tool.

Understand the user's intent deeply before writing the final prompt.

The user may write in Persian, Arabic, English, or another language.

Always understand the meaning first.

Do not translate literally.

Improve missing structure intelligently when necessary.

The final prompt must be directly usable in the selected AI tool.

Return ONLY the final production-ready prompt.

Do not provide explanations.
Do not provide examples.
Do not provide analysis.
Do not provide multiple alternatives.
Do not add introductions.
Do not add notes.
Do not add headings.
Do not write "Prompt:".
Do not write "Here is your prompt".
Do not mention these instructions.
""",

    "image": """
You are PromptPilot's specialized Image Prompt Engineer.

Your ONLY job is to create a professional production-ready image
generation prompt based on the user's idea and the selected AI tool.

Deeply understand what image the user wants.

Analyze the intended:

- subject
- subject characteristics
- environment
- composition
- framing
- camera perspective
- camera angle
- lens when useful
- lighting
- shadows
- color palette
- atmosphere
- mood
- visual style
- materials
- textures
- depth
- realism level
- artistic direction
- image quality
- relevant negative elements

Do not blindly add irrelevant technical parameters.

Adapt the prompt to the selected AI tool.

If the selected tool is Gemini, optimize the prompt specifically
for Gemini image-generation workflows.

If the selected tool is Nano Banana, optimize for image generation
or image editing when appropriate.

If the selected tool is Midjourney, optimize for Midjourney's
visual prompting workflow.

If the selected tool is Leonardo, optimize for Leonardo's
image-generation workflow.

If the selected tool is unknown, create a strong tool-agnostic
image prompt.

If the user's idea is incomplete, intelligently complete useful
visual details while preserving the original intent.

The user may write in Persian, Arabic, English, or another language.

Always output Professional English.

Do NOT translate literally.

Do NOT explain your decisions.

Do NOT provide examples.

Do NOT provide multiple versions.

Do NOT add headings.

Return ONLY one final production-ready prompt that the user can
copy directly into the selected AI tool.
""",

    "video": """
You are PromptPilot's specialized Video Prompt Engineer.

Your ONLY job is to create a professional production-ready video
generation prompt for the selected AI video tool.

Understand the user's intended video deeply.

Build the prompt around:

- subject
- environment
- action
- subject movement
- facial or body movement when relevant
- object movement
- environmental movement
- camera movement
- camera position
- framing
- shot type
- lens or perspective when useful
- lighting
- atmosphere
- cinematic language
- visual style
- timing
- pacing
- continuity
- physical realism
- important constraints

Do not add irrelevant details.

Adapt the prompt to the selected AI video tool.

If the selected tool is Veo, optimize specifically for Google's
Veo video-generation workflow.

If the selected tool is Sora, optimize for Sora's video prompting
workflow.

If the selected tool is Runway, optimize for Runway's video
generation workflow.

If the selected tool is Kling, optimize for Kling's video
generation workflow.

If the selected tool is unknown, create a strong tool-agnostic
video prompt.

The user may write in Persian, Arabic, English, or another language.

Always output Professional English.

Do NOT provide explanations.
Do NOT provide examples.
Do NOT provide analysis.
Do NOT provide alternatives.
Do NOT add headings.
Do NOT add notes.

Return ONLY one final production-ready prompt.
""",

    "improver": """
You are PromptPilot's Professional Prompt Improver.

The user provides an existing prompt.

Transform it into a substantially stronger, clearer, more precise,
professional and production-ready prompt while preserving the
original intent.

Improve:

- clarity
- specificity
- structure
- context
- constraints
- desired output
- relevant technical details
- consistency
- ambiguity

Do not unnecessarily change the user's intended task.

Adapt the improved prompt to the selected AI tool.

The final output MUST be Professional English.

Do NOT explain what you changed.

Do NOT provide before/after versions.

Do NOT provide analysis.

Do NOT add headings.

Do NOT provide examples.

Return ONLY the final improved prompt.
""",

    "doctor": """
You are PromptPilot's Prompt Doctor.

The user provides a prompt that may contain weaknesses.

Internally diagnose:

- ambiguity
- missing context
- weak instructions
- missing constraints
- poor structure
- unclear output requirements
- unnecessary wording
- contradictions
- tool incompatibility

Then silently repair all relevant problems.

Preserve the original intention.

Adapt the repaired prompt to the selected AI tool.

The final result MUST be Professional English and immediately usable.

Do NOT show the diagnosis.

Do NOT show scores.

Do NOT explain the problems.

Do NOT show the original prompt.

Do NOT provide before/after versions.

Do NOT add headings.

Return ONLY the final repaired production-ready prompt.
""",

    "detector": """
You are PromptPilot's AI Task and Tool Recommender.

Understand exactly what the user wants to accomplish.

Internally determine:

- task type
- appropriate AI workflow
- suitable tool category
- most effective prompting approach

If a tool has already been selected, optimize specifically for it.

If the user selected "I don't know", intelligently determine the
most appropriate workflow based on the task.

The purpose is not to give the user a long explanation.

Create a professional, immediately usable prompt for the identified
workflow.

The final result MUST be Professional English.

Do NOT provide a tutorial.
Do NOT provide examples.
Do NOT provide analysis.
Do NOT provide long explanations.
Do NOT add headings.

Return ONLY the final production-ready prompt.
""",

    "pro": """
You are PromptPilot's Professional Idea-to-Prompt Engine.

The user gives you a raw idea in Persian, Arabic, English, or another
language.

Your job is NOT simple translation.

Understand the idea deeply and transform it into a sophisticated,
production-ready prompt.

Infer useful missing details when appropriate without changing the
user's original intention.

Structure the prompt according to the selected AI tool.

The final prompt MUST always be Professional English.

The final result must be immediately usable.

Do NOT explain the translation.

Do NOT explain your reasoning.

Do NOT provide examples.

Do NOT provide alternatives.

Do NOT add headings.

Do NOT add notes.

Return ONLY the final production-ready prompt.
""",

    "remix": """
You are PromptPilot's Professional Prompt Remix Engine.

The user provides an existing prompt.

Create a refined and more distinctive version that preserves the
core intention while making the prompt more polished and effective.

Respect the selected AI tool.

Do not completely replace the original concept.

Improve creative direction, specificity, quality and practical
usability where appropriate.

The final output MUST be Professional English.

Do NOT explain the changes.

Do NOT provide multiple versions.

Do NOT add headings.

Do NOT add commentary.

Return ONLY the final production-ready prompt.
""",

}


# =========================================================
# GEMINI TOOL PROFILES
# =========================================================

GEMINI_TOOL_PROFILES = {

    "chatgpt": """
Optimize the final prompt for ChatGPT's instruction-following,
reasoning, context handling and structured-output capabilities.
""",

    "gemini": """
Optimize the final prompt specifically for Google's Gemini ecosystem.
Use clear natural-language instructions and structured requirements
when useful.
""",

    "nanobanana": """
Optimize the final prompt specifically for Nano Banana image
generation and image-editing workflows.

Prioritize precise visual descriptions, composition, subject
consistency, identity preservation and editing intent when relevant.
""",

    "midjourney": """
Optimize the final prompt for Midjourney image generation.

Prioritize rich visual direction, composition, lighting, subject
details, atmosphere, style and visual coherence.

Do not add unsupported or unnecessary syntax.
""",

    "leonardo": """
Optimize the final prompt for Leonardo image generation.

Prioritize detailed visual direction, subject consistency,
composition, lighting, style and generation-relevant details.
""",

    "veo": """
Optimize the final prompt specifically for Google's Veo video
generation workflow.

Focus strongly on scene description, subject action, camera movement,
temporal progression, cinematic direction and physical continuity.
""",

    "sora": """
Optimize the final prompt for Sora video generation.

Prioritize cinematic scene construction, subject action, camera
movement, timing, environment and visual continuity.
""",

    "runway": """
Optimize the final prompt for Runway video generation.

Prioritize visual motion, camera movement, subject behavior,
environmental motion, composition and cinematic direction.
""",

    "kling": """
Optimize the final prompt for Kling video generation.

Prioritize subject movement, camera motion, scene continuity,
visual realism and cinematic details.
""",

    "suno": """
Optimize the final prompt for Suno music generation.

Translate the user's intent into clear professional musical direction
including genre, mood, instrumentation, vocals when relevant,
arrangement, energy, tempo, structure and production character.
""",

    "ud io": """
Optimize the final prompt for Udio music generation.

Provide clear professional musical direction including genre, mood,
instrumentation, vocals when relevant, arrangement, energy, tempo,
structure and production character.
""",

    "other": """
Create a tool-agnostic professional prompt that can work across
compatible AI systems.
""",

    "unknown": """
The user does not know the appropriate tool.

Determine the most suitable prompting approach internally and create
a professional tool-agnostic prompt that remains immediately usable.
""",

}


# =========================================================
# GEMINI PROMPT BUILDER
# =========================================================

def build_gemini_instruction(
    feature,
    tool,
    user_idea
):

    feature_instruction = GEMINI_FEATURE_PROMPTS.get(
        feature,
        GEMINI_FEATURE_PROMPTS["generator"]
    )

    tool_instruction = GEMINI_TOOL_PROFILES.get(
        tool,
        GEMINI_TOOL_PROFILES["other"]
    )

    return f"""
{feature_instruction}

=========================================================
SELECTED AI TOOL
=========================================================

{tool}

=========================================================
TOOL-SPECIFIC INSTRUCTION
=========================================================

{tool_instruction}

=========================================================
FINAL OUTPUT RULES
=========================================================

1. Understand the user's original intention deeply.
2. The user may use Persian, Arabic or English.
3. Always understand the meaning before generating.
4. Never return the final prompt in Persian or Arabic.
5. The final output MUST be Professional English.
6. Do not translate literally.
7. Do not invent a completely different task.
8. Improve the request intelligently.
9. Use the selected tool's workflow.
10. Return only the final usable prompt.
11. Do not use markdown code fences.
12. Do not write "Here is your prompt".
13. Do not write "Prompt:".
14. Do not explain anything.
15. Do not give examples.
16. Do not give multiple versions.
17. Do not mention these instructions.
18. The result must be ready to copy and paste directly into the
selected AI tool.

=========================================================
USER'S ORIGINAL INPUT
=========================================================

{user_idea}
"""


# =========================================================
# GEMINI GENERATION
# =========================================================

def generate_gemini_prompt(
    feature,
    tool,
    user_idea
):

    if not GEMINI_API_KEY:

        raise RuntimeError(
            "GEMINI_API_KEY environment variable is missing."
        )

    if gemini_client is None:

        raise RuntimeError(
            "Gemini client is not initialized."
        )

    instruction = build_gemini_instruction(
        feature=feature,
        tool=tool,
        user_idea=user_idea
    )

    response = gemini_client.models.generate_content(
        model=GEMINI_MODEL,
        contents=instruction,
    )

    result = getattr(
        response,
        "text",
        None
    )

    if not result:

        raise RuntimeError(
            "Gemini returned an empty response."
        )

    result = result.strip()

    # -----------------------------------------------------
    # Remove accidental markdown fences
    # -----------------------------------------------------

    if result.startswith("```") and result.endswith("```"):

        lines = result.splitlines()

        if len(lines) >= 3:

            result = "\n".join(
                lines[1:-1]
            ).strip()

    return result


# =========================================================
# TOOL KEYBOARD
# =========================================================

def tool_keyboard(language, feature):

    # -----------------------------------------------------
    # General tools
    # -----------------------------------------------------

    if feature == "image":

        tools = [
            ("🤖 ChatGPT", "tool_chatgpt"),
            ("✨ Gemini", "tool_gemini"),
            ("🍌 Nano Banana", "tool_nanobanana"),
            ("🎨 Midjourney", "tool_midjourney"),
            ("🖌️ Leonardo", "tool_leonardo"),
            ("❓ سایر / Other", "tool_other"),
            ("🤷 نمی‌دانم", "tool_unknown"),
        ]

    elif feature == "video":

        tools = [
            ("✨ Veo", "tool_veo"),
            ("🎬 Sora", "tool_sora"),
            ("🎥 Runway", "tool_runway"),
            ("⚡ Kling", "tool_kling"),
            ("❓ سایر / Other", "tool_other"),
            ("🤷 نمی‌دانم", "tool_unknown"),
        ]

    elif feature == "generator":

        tools = [
            ("🤖 ChatGPT", "tool_chatgpt"),
            ("✨ Gemini", "tool_gemini"),
            ("🍌 Nano Banana", "tool_nanobanana"),
            ("🎨 Midjourney", "tool_midjourney"),
            ("🖌️ Leonardo", "tool_leonardo"),
            ("🎬 Veo", "tool_veo"),
            ("🎥 Sora", "tool_sora"),
            ("⚡ Runway", "tool_runway"),
            ("🎞️ Kling", "tool_kling"),
            ("🎵 Suno", "tool_suno"),
            ("🎶 Udio", "tool_ud io"),
            ("❓ سایر / Other", "tool_other"),
            ("🤷 نمی‌دانم", "tool_unknown"),
        ]

    else:

        tools = [
            ("🤖 ChatGPT", "tool_chatgpt"),
            ("✨ Gemini", "tool_gemini"),
            ("❓ سایر / Other", "tool_other"),
            ("🤷 نمی‌دانم", "tool_unknown"),
        ]

    rows = []

    for label, callback in tools:

        rows.append(
            [
                InlineKeyboardButton(
                    label,
                    callback_data=callback
                )
            ]
        )

    if language == "fa":

        rows.append(
            [
                InlineKeyboardButton(
                    "⬅️ بازگشت",
                    callback_data="back_feature"
                )
            ]
        )

    elif language == "ar":

        rows.append(
            [
                InlineKeyboardButton(
                    "⬅️ رجوع",
                    callback_data="back_feature"
                )
            ]
        )

    else:

        rows.append(
            [
                InlineKeyboardButton(
                    "⬅️ Back",
                    callback_data="back_feature"
                )
            ]
        )

    return InlineKeyboardMarkup(rows)


# =========================================================
# TOOL SELECTION TEXT
# =========================================================

def get_tool_selection_text(language):

    if language == "fa":

        return (
            "🎯 <b>انتخاب ابزار</b>\n\n"
            "Prompt را برای کدام ابزار می‌خواهی؟\n\n"
            "انتخاب ابزار کمک می‌کند Prompt متناسب با "
            "روش کار همان ابزار آماده شود.\n\n"
            "اگر مطمئن نیستی، گزینه «نمی‌دانم» را بزن."
        )

    if language == "ar":

        return (
            "🎯 <b>اختيار الأداة</b>\n\n"
            "لأي أداة تريد هذا الـ Prompt؟\n\n"
            "اختيار الأداة يساعد على إعداد Prompt مناسب "
            "لطريقة عمل الأداة.\n\n"
            "إذا لم تكن متأكداً، اختر «لا أعرف»."
        )

    return (
        "🎯 <b>Choose an AI Tool</b>\n\n"
        "Which tool do you want to use this prompt with?\n\n"
        "Choosing the tool helps prepare the prompt "
        "according to that tool's workflow.\n\n"
        "If you are not sure, choose \"I don't know\"."
    )


# =========================================================
# FEATURE NAME
# =========================================================

def feature_name(language, feature):

    names = {

        "fa": {
            "generator": "🧠 تولید Prompt",
            "improver": "🔥 بهبود Prompt",
            "doctor": "🩺 Prompt Doctor",
            "detector": "🎯 AI Detector",
            "image": "🖼️ Image Prompt",
            "video": "🎬 Video Prompt",
            "pro": "🌍 ایده → Prompt حرفه‌ای",
            "remix": "🔄 Prompt Remix",
        },

        "en": {
            "generator": "🧠 Prompt Generator",
            "improver": "🔥 Prompt Improver",
            "doctor": "🩺 Prompt Doctor",
            "detector": "🎯 AI Detector",
            "image": "🖼️ Image Prompt",
            "video": "🎬 Video Prompt",
            "pro": "🌍 Idea → Professional Prompt",
            "remix": "🔄 Prompt Remix",
        },

        "ar": {
            "generator": "🧠 إنشاء Prompt",
            "improver": "🔥 تحسين Prompt",
            "doctor": "🩺 طبيب Prompt",
            "detector": "🎯 مقترح أدوات AI",
            "image": "🖼️ Prompt للصور",
            "video": "🎬 Prompt للفيديو",
            "pro": "🌍 فكرة → Prompt احترافي",
            "remix": "🔄 إعادة صياغة Prompt",
        },

    }

    return names.get(
        language,
        names["en"]
    ).get(
        feature,
        feature
    )


# =========================================================
# SHOW LANGUAGE SELECTION
# =========================================================


async def show_language_selection(update):

    if update.message:

        await update.message.reply_text(
            LANGUAGE_SELECTION_TEXT,
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

    save_user(
        telegram_id=user.id,
        first_name=user.first_name,
        last_name=user.last_name,
        username=user.username,
    )

    context.user_data.clear()

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

    if data == "lang_fa":

        language = "fa"

    elif data == "lang_en":

        language = "en"

    elif data == "lang_ar":

        language = "ar"

    else:

        return

    success = update_user_language(
        user.id,
        language
    )

    if not success:

        await query.edit_message_text(
            "❌ Database error. Please try again."
        )

        return

    context.user_data.clear()

    await query.edit_message_text(
        get_main_menu_text(language),
        parse_mode="HTML",
        reply_markup=main_menu_keyboard(language)
    )


# =========================================================
# FEATURE CALLBACK
# =========================================================

async def feature_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    query = update.callback_query

    if not query:
        return

    await query.answer()

    user_id = query.from_user.id

    language = get_user_language(user_id)

    feature = query.data.replace(
        "feature_",
        "",
        1
    )

    if feature not in FEATURE_INFO:

        return

    context.user_data["current_feature"] = feature
    context.user_data["waiting_for_idea"] = True

    context.user_data.pop(
        "user_idea",
        None
    )

    context.user_data.pop(
        "selected_tool",
        None
    )

    text = FEATURE_INFO[feature].get(
        language,
        FEATURE_INFO[feature]["en"]
    )

    await query.edit_message_text(
        text,
        parse_mode="HTML",
        reply_markup=back_main_keyboard(language)
    )


# =========================================================
# TEXT MESSAGE HANDLER
# =========================================================

async def text_message_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if not update.message:
        return

    user = update.effective_user

    if not user:
        return

    language = get_user_language(
        user.id
    )

    text = update.message.text.strip()

    if not text:
        return

    current_feature = context.user_data.get(
        "current_feature"
    )

    waiting_for_idea = context.user_data.get(
        "waiting_for_idea",
        False
    )

    # -----------------------------------------------------
    # If user has selected a feature
    # -----------------------------------------------------

    if current_feature and waiting_for_idea:

        context.user_data["user_idea"] = text

        context.user_data["waiting_for_idea"] = False

        await update.message.reply_text(
            get_tool_selection_text(language),
            parse_mode="HTML",
            reply_markup=tool_keyboard(
                language,
                current_feature
            )
        )

        return

    # -----------------------------------------------------
    # Otherwise
    # -----------------------------------------------------

    await update.message.reply_text(
        get_main_menu_text(language),
        parse_mode="HTML",
        reply_markup=main_menu_keyboard(language)
    )


# =========================================================
# TOOL CALLBACK
# =========================================================

async def tool_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    query = update.callback_query

    if not query:
        return

    await query.answer()

    user_id = query.from_user.id

    language = get_user_language(
        user_id
    )

    tool = query.data.replace(
        "tool_",
        "",
        1
    )

    feature = context.user_data.get(
        "current_feature"
    )

    user_idea = context.user_data.get(
        "user_idea"
    )

    if not feature:

        await query.edit_message_text(
            get_main_menu_text(language),
            parse_mode="HTML",
            reply_markup=main_menu_keyboard(language)
        )

        return

    if not user_idea:

        text = {

            "fa": (
                "❌ ابتدا ایده یا Prompt خود را ارسال کنید."
            ),

            "en": (
                "❌ Please send your idea or prompt first."
            ),

            "ar": (
                "❌ أرسل فكرتك أو الـ Prompt أولاً."
            ),

        }

        await query.edit_message_text(
            text.get(
                language,
                text["en"]
            ),
            reply_markup=back_main_keyboard(language)
        )

        return

    context.user_data["selected_tool"] = tool

    tool_names = {

        "chatgpt": "ChatGPT",
        "gemini": "Gemini",
        "nanobanana": "Nano Banana",
        "midjourney": "Midjourney",
        "leonardo": "Leonardo",
        "veo": "Veo",
        "sora": "Sora",
        "runway": "Runway",
        "kling": "Kling",
        "suno": "Suno",
        "ud io": "Udio",
        "other": "Other",
        "unknown": "Unknown",

    }

    selected_name = tool_names.get(
        tool,
        tool
    )

    # -----------------------------------------------------
    # Gemini API check
    # -----------------------------------------------------

    if not GEMINI_API_KEY:

        text = {

            "fa": (
                "❌ <b>Gemini API Key پیدا نشد.</b>\n\n"
                "لطفاً متغیر محیطی GEMINI_API_KEY را در Render "
                "تنظیم کنید."
            ),

            "en": (
                "❌ <b>Gemini API Key was not found.</b>\n\n"
                "Please configure the GEMINI_API_KEY environment "
                "variable in Render."
            ),

            "ar": (
                "❌ <b>لم يتم العثور على Gemini API Key.</b>\n\n"
                "يرجى إعداد متغير GEMINI_API_KEY في Render."
            ),

        }

        await query.edit_message_text(
            text.get(
                language,
                text["en"]
            ),
            parse_mode="HTML",
            reply_markup=back_main_keyboard(language)
        )

        return

    # -----------------------------------------------------
    # Processing message
    # -----------------------------------------------------

    processing_text = {

        "fa": (
            "🧠 <b>Gemini در حال ساخت Prompt حرفه‌ای است...</b>\n\n"
            f"🎯 ابزار: {selected_name}\n\n"
            "در حال تحلیل درخواست و ساخت خروجی اختصاصی..."
        ),

        "en": (
            "🧠 <b>Gemini is creating your professional prompt...</b>\n\n"
            f"🎯 Tool: {selected_name}\n\n"
            "Analyzing your request and building a specialized output..."
        ),

        "ar": (
            "🧠 <b>Gemini يقوم بإنشاء Prompt احترافي...</b>\n\n"
            f"🎯 الأداة: {selected_name}\n\n"
            "جاري تحليل طلبك وإنشاء نتيجة مخصصة..."
        ),

    }

    await query.edit_message_text(
        processing_text.get(
            language,
            processing_text["en"]
        ),
        parse_mode="HTML"
    )

    # -----------------------------------------------------
    # Generate prompt with Gemini
    # -----------------------------------------------------

    try:

        final_prompt = generate_gemini_prompt(
            feature=feature,
            tool=tool,
            user_idea=user_idea
        )

    except Exception:

        logger.exception(
            "Gemini generation failed for user %s",
            user_id
        )

        error_text = {

            "fa": (
                "❌ <b>خطا در اتصال به Gemini</b>\n\n"
                "در تولید Prompt مشکلی به وجود آمد.\n"
                "لطفاً دوباره تلاش کنید."
            ),

            "en": (
                "❌ <b>Gemini generation error</b>\n\n"
                "Something went wrong while generating your prompt.\n"
                "Please try again."
            ),

            "ar": (
                "❌ <b>خطأ في إنشاء Prompt بواسطة Gemini</b>\n\n"
                "حدثت مشكلة أثناء إنشاء الـ Prompt.\n"
                "يرجى المحاولة مرة أخرى."
            ),

        }

        await query.edit_message_text(
            error_text.get(
                language,
                error_text["en"]
            ),
            parse_mode="HTML",
            reply_markup=back_main_keyboard(language)
        )

        return

    # -----------------------------------------------------
    # Final result
    # -----------------------------------------------------

    result_header = {

        "fa": (
            "✅ <b>Prompt آماده است</b>\n\n"
            f"🎯 <b>ابزار:</b> {selected_name}\n"
            f"🧩 <b>قابلیت:</b> {feature_name(language, feature)}\n\n"
        ),

        "en": (
            "✅ <b>Your prompt is ready</b>\n\n"
            f"🎯 <b>Tool:</b> {selected_name}\n"
            f"🧩 <b>Feature:</b> {feature_name(language, feature)}\n\n"
        ),

        "ar": (
            "✅ <b>الـ Prompt جاهز</b>\n\n"
            f"🎯 <b>الأداة:</b> {selected_name}\n"
            f"🧩 <b>الميزة:</b> {feature_name(language, feature)}\n\n"
        ),

    }

    # -----------------------------------------------------
    # Escape HTML safely
    # -----------------------------------------------------

    safe_prompt = (
        final_prompt
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )

    final_text = (
        result_header.get(
            language,
            result_header["en"]
        )
        + "<code>"
        + safe_prompt
        + "</code>"
    )

    # -----------------------------------------------------
    # Telegram message size protection
    # -----------------------------------------------------

    if len(final_text) <= 4000:

        await query.edit_message_text(
            final_text,
            parse_mode="HTML",
            reply_markup=back_main_keyboard(language)
        )

    else:

        await query.edit_message_text(
            result_header.get(
                language,
                result_header["en"]
            ),
            parse_mode="HTML",
            reply_markup=back_main_keyboard(language)
        )

        await query.message.reply_text(
            final_prompt
        )

    # -----------------------------------------------------
    # Clear temporary state
    # -----------------------------------------------------

    context.user_data.pop(
        "waiting_for_idea",
        None
    )

    context.user_data.pop(
        "user_idea",
        None
    )


# =========================================================
# BACK TO MAIN
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

    context.user_data.clear()

    await query.edit_message_text(
        get_main_menu_text(language),
        parse_mode="HTML",
        reply_markup=main_menu_keyboard(language)
    )


# =========================================================
# BACK TO FEATURE
# =========================================================

async def back_feature_callback(
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

    feature = context.user_data.get(
        "current_feature"
    )

    if not feature or feature not in FEATURE_INFO:

        await query.edit_message_text(
            get_main_menu_text(language),
            parse_mode="HTML",
            reply_markup=main_menu_keyboard(language)
        )

        return

    context.user_data["waiting_for_idea"] = True

    context.user_data.pop(
        "user_idea",
        None
    )

    context.user_data.pop(
        "selected_tool",
        None
    )

    text = FEATURE_INFO[feature].get(
        language,
        FEATURE_INFO[feature]["en"]
    )

    await query.edit_message_text(
        text,
        parse_mode="HTML",
        reply_markup=back_main_keyboard(language)
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

    if not GEMINI_API_KEY:

        logger.warning(
            "GEMINI_API_KEY environment variable is missing."
        )

    # -----------------------------------------------------
    # Database
    # -----------------------------------------------------

    initialize_database()

    # -----------------------------------------------------
    # Render health server
    # -----------------------------------------------------

    health_thread = threading.Thread(
        target=start_health_server,
        daemon=True,
    )

    health_thread.start()

    # -----------------------------------------------------
    # Telegram
    # -----------------------------------------------------

    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .build()
    )

    # -----------------------------------------------------
    # Commands
    # -----------------------------------------------------

    application.add_handler(
        CommandHandler(
            "start",
            start
        )
    )

    # -----------------------------------------------------
    # Language
    # -----------------------------------------------------

    application.add_handler(
        CallbackQueryHandler(
            language_callback,
            pattern=r"^lang_(fa|en|ar)$"
        )
    )

    # -----------------------------------------------------
    # Features
    # -----------------------------------------------------

    application.add_handler(
        CallbackQueryHandler(
            feature_callback,
            pattern=r"^feature_"
        )
    )

    # -----------------------------------------------------
    # Tools
    # -----------------------------------------------------

    application.add_handler(
        CallbackQueryHandler(
            tool_callback,
            pattern=r"^tool_"
        )
    )

    # -----------------------------------------------------
    # Navigation
    # -----------------------------------------------------

    application.add_handler(
        CallbackQueryHandler(
            back_main_callback,
            pattern=r"^back_main$"
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            back_feature_callback,
            pattern=r"^back_feature$"
        )
    )

    # -----------------------------------------------------
    # Text
    # -----------------------------------------------------

    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            text_message_handler
        )
    )

    # -----------------------------------------------------
    # Errors
    # -----------------------------------------------------

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
