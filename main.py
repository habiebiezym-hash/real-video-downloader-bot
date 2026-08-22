import os
import asyncio
import logging
import time
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)
import yt_dlp
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading

load_dotenv()

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = os.getenv("ADMIN_ID") # Admin Telegram ID
COOKIE_FILE = "cookies.txt"
ITEMS_PER_PAGE = 10

# Anti-Spam / Rate Limiting Tracker
USER_COOLDOWNS = {}
USERS_DB = set() # Store unique user IDs

def check_rate_limit(user_id: int, cooldown_seconds: int = 3) -> bool:
    current_time = time.time()
    last_time = USER_COOLDOWNS.get(user_id, 0)
    if current_time - last_time < cooldown_seconds:
        return False
    USER_COOLDOWNS[user_id] = current_time
    return True

# Simple Health Check Server for Railway Keep-Alive
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK - Bot is Alive")

def run_health_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    server.serve_forever()

# Start background thread for Railway Health check
threading.Thread(target=run_health_server, daemon=True).start()

def get_main_menu():
    keyboard = [
        [InlineKeyboardButton("🎬 YouTube", callback_data="menu_yt"), InlineKeyboardButton("🎵 TikTok", callback_data="menu_tt")],
        [InlineKeyboardButton("📘 Facebook", callback_data="menu_fb"), InlineKeyboardButton("🔍 Music Search", callback_data="menu_search")]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_quality_menu():
    keyboard = [
        [InlineKeyboardButton("🎵 MP3 (Audio)", callback_data="quality_mp3")],
        [InlineKeyboardButton("360p", callback_data="quality_360"), InlineKeyboardButton("480p", callback_data="quality_480")],
        [InlineKeyboardButton("720p", callback_data="quality_720"), InlineKeyboardButton("1080p", callback_data="quality_1080")]
    ]
    return InlineKeyboardMarkup(keyboard)

def build_search_keyboard(results, page=0):
    start_idx = page * ITEMS_PER_PAGE
    end_idx = start_idx + ITEMS_PER_PAGE
    page_results = results[start_idx:end_idx]
    
    keyboard = []
    for idx, entry in enumerate(page_results, start=start_idx):
        title = entry.get('title', 'Unknown')[:35]
        keyboard.append([InlineKeyboardButton(f"🎵 {title}", callback_data=f"select_search_{idx}")])
    
    total_pages = (len(results) + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE
    nav_row = []
    
    if page > 0:
        nav_row.append(InlineKeyboardButton("◀️ Back", callback_data=f"page_{page - 1}"))
    else:
        nav_row.append(InlineKeyboardButton("⛔", callback_data="noop"))
        
    nav_row.append(InlineKeyboardButton(f"📄 {page + 1}/{total_pages}", callback_data="noop"))
    
    if end_idx < len(results):
        nav_row.append(InlineKeyboardButton("Next ▶️", callback_data=f"page_{page + 1}"))
    else:
        nav_row.append(InlineKeyboardButton("⛔", callback_data="noop"))
        
    keyboard.append(nav_row)
    return InlineKeyboardMarkup(keyboard)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    USERS_DB.add(user_id)
    
    welcome_text = (
        "မမရေ💖🍓 မမကြိုက်တဲ့ Videoလေးတွေ Download ရပြီနော်။\n"
        "လောလောဆယ်တော့ Tiktok, Facebookနဲ့ YouTube Music Search ရပါပြီ။\n"
        "မောင်ကြိုးစားပြီးပြင်ပေးထားတယ်။ချစ်တယ်နော်🍓💖 အာဘွားမွကျိ😘🍓"
    )
    await update.message.reply_text(
        welcome_text,
        reply_markup=get_main_menu()
    )

async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    if ADMIN_ID and user_id == str(ADMIN_ID):
        await update.message.reply_text(f"📊 **Bot Status**\n\nTotal Users: {len(USERS_DB)}")

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    USERS_DB.add(user_id)
    
    if not check_rate_limit(user_id, cooldown_seconds=2):
        await query.answer("⚠️ ကျေးဇူးပြု၍ ခေတ္တစောင့်ပြီးမှ ထပ်မံနှိပ်ပါ!", show_alert=True)
        return

    await query.answer()
    data = query.data

    if data == "noop":
        return

    if data.startswith("menu_"):
        if data == "menu_search":
            context.user_data["awaiting_search"] = True
            await query.edit_message_text("🔍 ရှာဖွေချင်သည့် သီချင်း အမည် သို့မဟုတ် အဆိုတော် အမည်ကို ရိုက်ပို့ပေးပါ:")
        else:
            platform = data.split("_")[1].upper()
            await query.edit_message_text(f"📥 {platform} Link ကို ပေးပို့ပေးပါ။")

    elif data.startswith("page_"):
        page = int(data.split("_")[1])
        results = context.user_data.get("search_results", [])
        if results:
            reply_markup = build_search_keyboard(results, page)
            await query.edit_message_text("👇 ဒေါင်းလုဒ်ဆွဲလိုသည့် သီချင်းကို ရွေးပါ:", reply_markup=reply_markup)

    elif data.startswith("quality_"):
        quality = data.split("_")[1]
        url = context.user_data.get("pending_url")
        if not url:
            await query.edit_message_text("❌ Link မရှိတော့ပါ။ Link ပြန်ပို့ပေးပါ။")
            return

        await query.edit_message_text("⏳ Download ပြုလုပ်နေပါသည်... ခေတ္တစောင့်ပေးပါ။")
        asyncio.create_task(process_download(query, context, url, quality))

    elif data.startswith("select_search_"):
        idx = int(data.split("_")[2])
        results = context.user_data.get("search_results", [])
        if 0 <= idx < len(results):
            selected = results[idx]
            url = f"https://www.youtube.com/watch?v={selected['id']}"
            await query.edit_message_text(f"🎵 **{selected['title']}** ကို ဒေါင်းလုဒ်ဆွဲနေပါသည်...")
            asyncio.create_task(process_download(query, context, url, "mp3"))

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    USERS_DB.add(user_id)
    text = update.message.text.strip()

    if context.user_data.get("awaiting_search"):
        context.user_data["awaiting_search"] = False
        msg = await update.message.reply_text(f"🔍 '{text}' အတွက် သီချင်းများ ရှာဖွေနေပါသည်...")
        
        ydl_opts = {
            'extract_flat': True, 
            'quiet': True,
            'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'extractor_args': {'youtube': {'player_client': ['android', 'web']}}
        }
        if os.path.exists(COOKIE_FILE):
            ydl_opts['cookiefile'] = COOKIE_FILE

        loop = asyncio.get_running_loop()
        
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = await loop.run_in_executor(None, lambda: ydl.extract_info(f"ytsearch30:{text}", download=False))
                entries = info.get('entries', [])
                if not entries:
                    await msg.edit_text("❌ မည်သည့် သီချင်းမျှ ရှာမတွေ့ပါ။")
                    return

                context.user_data["search_results"] = entries
                reply_markup = build_search_keyboard(entries, page=0)
                await msg.edit_text("👇 ဒေါင်းလုဒ်ဆွဲလိုသည့် သီချင်းကို ရွေးပါ:", reply_markup=reply_markup)
        except Exception as e:
            logger.error(f"Search error: {e}")
            await msg.edit_text("❌ ရှာဖွေရာတွင် အမှားအယွင်း ရှိနေပါသည်။")
        return

    if text.startswith("http://") or text.startswith("https://"):
        context.user_data["pending_url"] = text
        await update.message.reply_text("🎬 Quality သို့မဟုတ် Format ရွေးချယ်ပါ:", reply_markup=get_quality_menu())
    else:
        await update.message.reply_text("❌ မှန်ကန်သော Link ပေးပို့ပါ။", reply_markup=get_main_menu())

async def process_download(query, context, url, quality):
    chat_id = query.message.chat_id
    loop = asyncio.get_running_loop()
    output_filename = f"dl_{query.message.message_id}"

    if quality == "mp3":
        ydl_opts = {
            'format': 'bestaudio/best',
            'postprocessors': [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3', 'preferredquality': '192'}],
            'outtmpl': f'{output_filename}.%(ext)s',
            'quiet': True,
            'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'extractor_args': {'youtube': {'player_client': ['android', 'web']}}
        }
    else:
        ydl_opts = {
            'format': f'bestvideo[height<={quality}]+bestaudio/best[height<={quality}]/best',
            'outtmpl': f'{output_filename}.%(ext)s',
            'merge_output_format': 'mp4',
            'quiet': True,
            'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'extractor_args': {'youtube': {'player_client': ['android', 'web']}}
        }

    if os.path.exists(COOKIE_FILE):
        ydl_opts['cookiefile'] = COOKIE_FILE

    try:
        def download():
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                return ydl.extract_info(url, download=True)

        info = await loop.run_in_executor(None, download)
        file_path = f"{output_filename}.mp3" if quality == "mp3" else f"{output_filename}.mp4"
        
        if not os.path.exists(file_path):
            for f in os.listdir('.'):
                if f.startswith(output_filename):
                    file_path = f
                    break

        file_size = os.path.getsize(file_path) / (1024 * 1024)

        if file_size > 50:
            await context.bot.send_message(chat_id=chat_id, text="❌ ဖိုင်ဆိုဒ် 50MB ထက်ကြီးသဖြင့် Telegram တွင် တင်၍ မရပါ။")
        else:
            await context.bot.send_message(chat_id=chat_id, text="📤 Telegram သို့ တင်ပို့နေပါသည်...")
            with open(file_path, 'rb') as file:
                if quality == "mp3":
                    await context.bot.send_audio(chat_id=chat_id, audio=file, title=info.get('title', 'Audio'))
                else:
                    await context.bot.send_video(chat_id=chat_id, video=file, caption=info.get('title', 'Video'))

    except Exception as e:
        logger.error(f"Download Error: {e}")
        await context.bot.send_message(chat_id=chat_id, text="❌ ဒေါင်းလုဒ်ဆွဲရာတွင် အမှားအယွင်း ဖြစ်ပေါ်ခဲ့ပါသည်။")
    finally:
        for f in os.listdir('.'):
            if f.startswith(output_filename):
                try:
                    os.remove(f)
                except Exception:
                    pass

def main():
    if not TOKEN:
        logger.error("BOT_TOKEN မရှိသေးပါ။ Environment Variable ကို စစ်ဆေးပါ။")
        return
    application = Application.builder().token(TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("stats", admin_stats))
    application.add_handler(CallbackQueryHandler(button_handler))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.run_polling()

if __name__ == "__main__":
    main()
