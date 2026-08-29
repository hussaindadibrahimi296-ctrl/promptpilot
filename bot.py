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
    MessageHandler,
    ContextTypes,
    filters,
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

    return names.get(language, names["en"]).get(
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

    # Reset temporary state

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
    context.user_data.pop("user_idea", None)
    context.user_data.pop("selected_tool", None)

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

    language = get_user_language(user.id)

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

    language = get_user_language(
        query.from_user.id
    )

    tool = query.data.replace(
        "tool_",
        "",
        1
    )

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

    if language == "fa":

        if tool == "unknown":

            text = (
                "🤖 <b>انتخاب شد: نمی‌دانم</b>\n\n"
                "اشکالی ندارد.\n"
                "در مرحله هوش مصنوعی، سیستم ایده تو را "
                "بررسی می‌کند و ابزارهای مناسب را پیشنهاد می‌دهد.\n\n"
                "⏳ فعلاً این مرحله آماده دریافت ایده و انتخاب ابزار است.\n\n"
                "🏠 برای برگشت به منوی اصلی از دکمه زیر استفاده کن."
            )

        elif tool == "other":

            text = (
                "❓ <b>سایر ابزارها</b>\n\n"
                "در این حالت Prompt به شکل عمومی و قابل "
                "استفاده تولید خواهد شد تا وابستگی به یک "
                "ابزار خاص نداشته باشد.\n\n"
                "⏳ موتور هوش مصنوعی در مرحله بعد این قسمت را تکمیل می‌کند."
            )

        else:

            text = (
                f"✅ <b>ابزار انتخاب شد:</b> {selected_name}\n\n"
                "ایده تو ثبت شد.\n\n"
                "در مرحله بعد موتور هوش مصنوعی بررسی می‌کند "
                "که برای این ابزار چه ساختار و سبک Prompt "
                "مناسب‌تر است.\n\n"
                "⏳ تولید واقعی Prompt در مرحله اتصال Gemini فعال می‌شود."
            )

    elif language == "ar":

        if tool == "unknown":

            text = (
                "🤖 <b>تم اختيار: لا أعرف</b>\n\n"
                "لا مشكلة.\n"
                "في مرحلة الذكاء الاصطناعي سيتم تحليل فكرتك "
                "واقتراح الأدوات المناسبة.\n\n"
                "⏳ هذه المرحلة حالياً تجهز المسار للمرحلة التالية."
            )

        elif tool == "other":

            text = (
                "❓ <b>أداة أخرى</b>\n\n"
                "سيتم إنشاء Prompt عام يمكن استخدامه مع "
                "أدوات مختلفة دون ربطه بأداة واحدة.\n\n"
                "⏳ سيتم تفعيل الإنشاء الفعلي في المرحلة التالية."
            )

        else:

            text = (
                f"✅ <b>الأداة المختارة:</b> {selected_name}\n\n"
                "تم حفظ فكرتك.\n\n"
                "في المرحلة التالية سيقوم محرك الذكاء الاصطناعي "
                "بتحديد أفضل أسلوب وبنية Prompt لهذه الأداة.\n\n"
                "⏳ إنشاء Prompt الفعلي سيتم تفعيله عند ربط Gemini."
            )

    else:

        if tool == "unknown":

            text = (
                "🤖 <b>Selected: I don't know</b>\n\n"
                "No problem.\n"
                "The AI engine will analyze your idea and "
                "recommend suitable tools in the next stage.\n\n"
                "⏳ The AI generation engine will be connected next."
            )

        elif tool == "other":

            text = (
                "❓ <b>Other Tool</b>\n\n"
                "A general-purpose prompt will be created "
                "without depending on a specific tool.\n\n"
                "⏳ Actual generation will be enabled in the next stage."
            )

        else:

            text = (
                f"✅ <b>Selected tool:</b> {selected_name}\n\n"
                "Your idea has been saved.\n\n"
                "In the next stage, the AI engine will determine "
                "the most suitable prompt structure and style "
                "for this tool.\n\n"
                "⏳ Actual prompt generation will be enabled "
                "after Gemini is connected."
            )

    await query.edit_message_text(
        text,
        parse_mode="HTML",
        reply_markup=back_main_keyboard(language)
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
    context.user_data.pop("user_idea", None)
    context.user_data.pop("selected_tool", None)

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
