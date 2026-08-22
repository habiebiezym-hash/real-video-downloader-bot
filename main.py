import os
import asyncio
import logging
import time
import aiohttp
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
import yt_dlp

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', 
    level=logging.INFO
)

USER_DATA = {}
SEARCH_CACHE = {}

def make_progress_bar(percent: float) -> str:
    total_blocks = 10
    filled = int((percent / 100) * total_blocks)
    return "▰" * filled + "▱" * (total_blocks - filled)

def format_bytes(size: float) -> str:
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size < 1024.0:
            return f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} TB"

async def resolve_redirect_url(url: str) -> str:
    """vt.tiktok.com သို့မဟုတ် Short URLs များကို Original URL သို့ ပြောင်းလဲခြင်း"""
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.get(url, allow_redirects=True, timeout=10) as resp:
                return str(resp.url)
    except Exception:
        return url

async def cobalt_download_fallback(url: str, is_audio: bool = False) -> dict:
    """yt-dlp ပျက်သွားပါက Cobalt API သို့ Fallback အဖြစ် ပြောင်းလဲအသုံးပြုခြင်း"""
    api_url = "https://api.cobalt.tools/api/json"
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json"
    }
    payload = {
        "url": url,
        "downloadMode": "audio" if is_audio else "auto",
        "audioFormat": "mp3"
    }
    async with aiohttp.ClientSession() as session:
        async with session.post(api_url, json=payload, headers=headers, timeout=20) as resp:
            if resp.status == 200:
                return await resp.json()
            return None

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome_text = (
        "✨ **PRO MEDIA & MUSIC DOWNLOADER** ✨\n"
        "━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "⚡ **Supported Platforms:**\n"
        "├ 🔴 YouTube (Videos, Shorts, Music)\n"
        "├ 🖤 TikTok (No Watermark)\n"
        "└ 🔵 Facebook (Reels & Videos)\n\n"
        "🎵 **Music Search & Downloader:**\n"
        "└ `/search <သီချင်းအမည်/အဆိုတော်>`\n\n"
        "💡 **How to use:** Video Link အား တိုက်ရိုက် ပို့ပေးပါ သို့မဟုတ် `/search` ဖြင့် ရှာပါ။"
    )
    await update.message.reply_text(welcome_text, parse_mode="Markdown")

# ----------------- VIDEO DOWNLOADER SECTION -----------------

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    raw_url = update.message.text.strip()
    user_id = update.message.from_user.id

    if not raw_url.startswith(("http://", "https://")):
        return

    msg = await update.message.reply_text("⚡ `Analyzing media link...`", parse_mode="Markdown")
    url = await resolve_redirect_url(raw_url)

    try:
        loop = asyncio.get_running_loop()
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
        }

        info = await loop.run_in_executor(
            None, 
            lambda: yt_dlp.YoutubeDL(ydl_opts).extract_info(url, download=False)
        )
        
        USER_DATA[user_id] = {'url': url, 'info': info}

        title = info.get('title', 'Media File')
        uploader = info.get('uploader') or info.get('extractor_key', 'Social Media')

        caption = (
            f"🎬 **{title[:60]}**\n"
            "━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"👤 **Source:** `{uploader}`\n\n"
            "👇 **Select Option:**"
        )

        keyboard = [
            [
                InlineKeyboardButton("✨ Best Quality Video", callback_data="res_best"),
                InlineKeyboardButton("🎵 MP3 Audio", callback_data="res_audio"),
            ]
        ]
        
        await msg.edit_text(caption, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    except Exception as e:
        logging.warning(f"yt-dlp extract failed: {e}. Saving URL for Direct Download.")
        USER_DATA[user_id] = {'url': url, 'info': {}}
        
        caption = (
            "🎬 **Media Content**\n"
            "━━━━━━━━━━━━━━━━━━━━━━━\n"
            "👇 **Select Format to Download:**"
        )
        keyboard = [
            [
                InlineKeyboardButton("⚡ Download Video", callback_data="res_best"),
                InlineKeyboardButton("🎵 Download Audio", callback_data="res_audio"),
            ]
        ]
        await msg.edit_text(caption, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    data = USER_DATA.get(user_id)

    if not data:
        await query.edit_message_text("❌ Session သက်တမ်းကုန်သွားပါပြီ။ Link ပြန်ပို့ပေးပါ။")
        return

    url = data['url']
    choice = query.data
    is_audio = (choice == "res_audio")

    await query.edit_message_text("📥 `Processing Media...`", parse_mode="Markdown")

    os.makedirs("downloads", exist_ok=True)
    filepath = None

    # Primary Download Strategy: yt-dlp
    try:
        fmt = "bestaudio/best" if is_audio else "bestvideo+bestaudio/best"
        last_update_time = [0]

        def progress_hook(d):
            if d['status'] == 'downloading':
                now = time.time()
                if now - last_update_time[0] > 2.5:
                    last_update_time[0] = now
                    total = d.get('total_bytes') or d.get('total_bytes_estimate', 0)
                    downloaded = d.get('downloaded_bytes', 0)
                    speed = d.get('speed', 0) or 0
                    if total > 0:
                        percent = (downloaded / total) * 100
                        bar = make_progress_bar(percent)
                        status_text = (
                            f"📥 **Downloading Media...**\n"
                            "━━━━━━━━━━━━━━━━━━━━━━━\n"
                            f"`[{bar}]` **{percent:.1f}%**\n\n"
                            f"🚀 **Speed:** `{format_bytes(speed)}/s`"
                        )
                        asyncio.run_coroutine_threadsafe(
                            query.edit_message_text(status_text, parse_mode="Markdown"),
                            asyncio.get_event_loop()
                        )

        ytdl_opts = {
            'format': fmt,
            'outtmpl': f'downloads/{user_id}_%(id)s.%(ext)s',
            'progress_hooks': [progress_hook],
            'quiet': True,
            'no_warnings': True,
            'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'
        }

        if is_audio:
            ytdl_opts['postprocessors'] = [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }]

        def _download_ytdlp():
            with yt_dlp.YoutubeDL(ytdl_opts) as ytdl:
                info = ytdl.extract_info(url, download=True)
                fn = ytdl.prepare_filename(info)
                if is_audio:
                    fn = os.path.splitext(fn)[0] + ".mp3"
                return fn, info.get('title', 'Downloaded Media')

        loop = asyncio.get_running_loop()
        filepath, title = await loop.run_in_executor(None, _download_ytdlp)

    except Exception as e:
        logging.warning(f"yt-dlp download failed: {e}. Trying Cobalt Fallback Engine...")
        
        # Secondary Download Strategy: Cobalt Engine Fallback
        try:
            cobalt_res = await cobalt_download_fallback(url, is_audio)
            if cobalt_res and cobalt_res.get("status") in ["tunnel", "redirect"]:
                download_link = cobalt_res.get("url")
                filename = f"downloads/{user_id}_file.{ 'mp3' if is_audio else 'mp4' }"
                
                async with aiohttp.ClientSession() as session:
                    async with session.get(download_link) as resp:
                        if resp.status == 200:
                            with open(filename, 'wb') as f:
                                f.write(await resp.read())
                            filepath = filename
                            title = "Media Download"
            
            if not filepath:
                raise Exception("Both Download Engines Failed.")
        except Exception as fallback_err:
            logging.error(f"Fallback Error: {fallback_err}")
            await query.edit_message_text("❌ **Download မအောင်မြင်ပါ။ မီး၊ ကွန်ရက် သို့မဟုတ် IP Block ကြောင့် ဖြစ်နိုင်ပါသည်။**", parse_mode="Markdown")
            USER_DATA.pop(user_id, None)
            return

    # Upload Phase
    try:
        await query.edit_message_text("⬆️ `Uploading to Telegram...`", parse_mode="Markdown")
        caption_text = f"✅ **{title}**"

        with open(filepath, 'rb') as file:
            if is_audio:
                await context.bot.send_audio(chat_id=query.message.chat_id, audio=file, caption=caption_text, parse_mode="Markdown")
            else:
                await context.bot.send_video(chat_id=query.message.chat_id, video=file, caption=caption_text, supports_streaming=True, parse_mode="Markdown")

        if filepath and os.path.exists(filepath):
            os.remove(filepath)

        await query.delete_message()

    except Exception as upload_err:
        logging.error(f"Upload Error: {upload_err}")
        await query.edit_message_text("❌ File ပေးပို့ရာတွင် အမှားအယွင်း ရှိနေပါသည်။")

    finally:
        USER_DATA.pop(user_id, None)

# ----------------- MUSIC SEARCH SECTION -----------------

async def search_music(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = " ".join(context.args)
    if not query:
        await update.message.reply_text("💡 **အသုံးပြုပုံ:** `/search <သီချင်းအမည်/အဆိုတော်>`\nဥပမာ - `/search Coldplay`", parse_mode="Markdown")
        return

    msg = await update.message.reply_text("🔎 `Searching music...`", parse_mode="Markdown")
    user_id = update.message.from_user.id

    def _yt_search():
        ydl_opts = {'extract_flat': True, 'skip_download': True, 'quiet': True}
        with yt_dlp.YoutubeDL(ydl_opts) as ytdl:
            res = ytdl.extract_info(f"ytsearch50:{query}", download=False)
            return res.get('entries', [])

    try:
        loop = asyncio.get_running_loop()
        results = await loop.run_in_executor(None, _yt_search)

        if not results:
            await msg.edit_text("❌ မည်သည့် သီချင်းမှ ရှာမတွေ့ပါ။")
            return

        SEARCH_CACHE[user_id] = {'results': results, 'page': 0}
        await render_search_page(msg, user_id)

    except Exception as e:
        logging.error(f"Search Error: {e}")
        await msg.edit_text("❌ ရှာဖွေရာတွင် အမှားအယွင်း ရှိနေပါသည်။")

async def render_search_page(message, user_id: int):
    cache = SEARCH_CACHE.get(user_id)
    if not cache:
        return

    results = cache['results']
    page = cache['page']
    
    items_per_page = 10
    start_idx = page * items_per_page
    end_idx = start_idx + items_per_page
    current_items = results[start_idx:end_idx]
    
    total_pages = (len(results) + items_per_page - 1) // items_per_page

    text = "🎵 **MUSIC SEARCH RESULTS**\n"
    text += "━━━━━━━━━━━━━━━━━━━━━━━\n\n"

    for idx, item in enumerate(current_items, start=1):
        duration = item.get('duration', 0) or 0
        mins, secs = divmod(int(duration), 60)
        dur_str = f"{mins:02d}:{secs:02d}"
        
        num_emoji = f"{idx}️⃣" if idx < 10 else "🔟"
        title = item.get('title', 'Unknown Title')[:40]
        text += f"{num_emoji} **{title}**\n⏱ `{dur_str}`\n\n"

    text += f"📄 **Page {page + 1} of {total_pages}** • လိုချင်သော နံပါတ်ကို နှိပ်ပါ"

    btn_row1 = [InlineKeyboardButton(f"{i}", callback_data=f"play_{start_idx + i - 1}") for i in range(1, 6) if (start_idx + i - 1) < len(results)]
    btn_row2 = [InlineKeyboardButton(f"{i}", callback_data=f"play_{start_idx + i - 1}") for i in range(6, 11) if (start_idx + i - 1) < len(results)]

    nav_btns = []
    if page > 0:
        nav_btns.append(InlineKeyboardButton("◀️ Back", callback_data="page_prev"))
    nav_btns.append(InlineKeyboardButton("❌ Close", callback_data="close_search"))
    if page < total_pages - 1:
        nav_btns.append(InlineKeyboardButton("Next ▶️", callback_data="page_next"))

    keyboard = [btn_row1, btn_row2, nav_btns]
    await message.edit_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def search_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    action = query.data
    cache = SEARCH_CACHE.get(user_id)

    if not cache and action != "close_search":
        await query.edit_message_text("❌ Session သက်တမ်းကုန်သွားပါပြီ။ `/search` ဖြင့် ပြန်ရှာပါ။", parse_mode="Markdown")
        return

    if action == "page_next":
        cache['page'] += 1
        await render_search_page(query.message, user_id)
        
    elif action == "page_prev":
        cache['page'] -= 1
        await render_search_page(query.message, user_id)
        
    elif action == "close_search":
        SEARCH_CACHE.pop(user_id, None)
        await query.message.delete()

    elif action.startswith("play_"):
        song_idx = int(action.split("_")[1])
        selected_song = cache['results'][song_idx]
        song_url = selected_song.get('url') or f"https://www.youtube.com/watch?v={selected_song['id']}"
        song_title = selected_song.get('title', 'Audio Track')

        await query.edit_message_text(f"⏳ `Downloading '{song_title[:30]}...'`", parse_mode="Markdown")
        
        os.makedirs("downloads", exist_ok=True)
        filepath = f"downloads/music_{user_id}_{selected_song['id']}.mp3"

        ytdl_opts = {
            'format': 'bestaudio/best',
            'outtmpl': f'downloads/music_{user_id}_{selected_song["id"]}.%(ext)s',
            'quiet': True,
            'no_warnings': True,
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }]
        }

        def _download_audio():
            with yt_dlp.YoutubeDL(ytdl_opts) as ytdl:
                ytdl.download([song_url])

        try:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, _download_audio)

            await query.edit_message_text("⬆️ `Uploading audio...`", parse_mode="Markdown")

            with open(filepath, 'rb') as file:
                await context.bot.send_audio(
                    chat_id=query.message.chat_id, 
                    audio=file, 
                    caption=f"🎵 **{song_title}**",
                    parse_mode="Markdown"
                )

            if os.path.exists(filepath):
                os.remove(filepath)

            await query.delete_message()

        except Exception as e:
            logging.error(f"Music Download Error: {e}")
            await query.edit_message_text("❌ သီချင်းဒေါင်းလုဒ်ဆွဲရာတွင် အမှားအယွင်း ရှိနေပါသည်။")

        finally:
            SEARCH_CACHE.pop(user_id, None)

def main():
    token = os.getenv("BOT_TOKEN")
    if not token:
        raise ValueError("BOT_TOKEN ထည့်ရန် လိုအပ်ပါသည်။")

    app = Application.builder().token(token).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("search", search_music))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(CallbackQueryHandler(button_callback, pattern="^(res_)"))
    app.add_handler(CallbackQueryHandler(search_callback_handler, pattern="^(page_|play_|close_search)"))

    app.run_polling()

if __name__ == "__main__":
    main()
