import aiohttp # aiohttp မရှိသေးပါက 'pip install aiohttp' လုပ်ပေးပါ

async def resolve_url(url: str) -> str:
    """vt.tiktok.com ကဲ့သို့ Short Link များကို Original URL သို့ ပြောင်းပေးခြင်း"""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, allow_redirects=True, timeout=10) as resp:
                return str(resp.url)
    except Exception:
        return url

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    raw_url = update.message.text.strip()
    user_id = update.message.from_user.id

    if not raw_url.startswith(("http://", "https://")):
        return

    msg = await update.message.reply_text("⚡ `Analyzing link...`", parse_mode="Markdown")

    # Short Link များကို Original Link သို့ Resolve လုပ်ခြင်း
    url = await resolve_url(raw_url)

    try:
        loop = asyncio.get_running_loop()
        
        # Cross-platform extract options (Cookies error မတက်စေရန် generic လုပ်ထားသည်)
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        }

        info = await loop.run_in_executor(
            None, 
            lambda: yt_dlp.YoutubeDL(ydl_opts).extract_info(url, download=False)
        )
        
        USER_DATA[user_id] = {'url': url, 'info': info}

        title = info.get('title', 'Media Content')
        uploader = info.get('uploader') or info.get('extractor_key', 'Unknown Source')
        
        caption = (
            f"🎬 **{title[:60]}**\n"
            "━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"👤 **Source:** `{uploader}`\n\n"
            "👇 **Select Download Option:**"
        )

        keyboard = [
            [
                InlineKeyboardButton("🎬 Best Quality (Video)", callback_data="res_best"),
                InlineKeyboardButton("🎵 MP3 Audio", callback_data="res_audio"),
            ]
        ]
        
        await msg.edit_text(caption, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

    except Exception as e:
        logging.error(f"Metadata Fetch Error: {e}")
        await msg.edit_text("❌ **Link မမှန်ကန်ပါ သို့မဟုတ် Public Video မဟုတ်ပါ။**", parse_mode="Markdown")

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

    # Platform အားလုံးနှင့် အဆင်ပြေမည့် Universal Format Selector
    if choice == "res_audio":
        fmt = "bestaudio/best"
        is_audio = True
    else:
        fmt = "bestvideo+bestaudio/best"
        is_audio = False

    os.makedirs("downloads", exist_ok=True)

    ytdl_opts = {
        'format': fmt,
        'outtmpl': f'downloads/{user_id}_%(id)s.%(ext)s',
        'quiet': True,
        'no_warnings': True,
        'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    }

    if is_audio:
        ytdl_opts['postprocessors'] = [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }]

    def _download():
        with yt_dlp.YoutubeDL(ytdl_opts) as ytdl:
            info = ytdl.extract_info(url, download=True)
            filename = ytdl.prepare_filename(info)
            if is_audio:
                filename = os.path.splitext(filename)[0] + ".mp3"
            return filename, info.get('title', 'Media File')

    try:
        await query.edit_message_text("⏳ `Downloading media...`", parse_mode="Markdown")
        
        loop = asyncio.get_running_loop()
        filepath, title = await loop.run_in_executor(None, _download)

        await query.edit_message_text("⬆️ `Uploading to Telegram...`", parse_mode="Markdown")

        caption_text = f"✅ **{title}**"

        with open(filepath, 'rb') as file:
            if is_audio:
                await context.bot.send_audio(chat_id=query.message.chat_id, audio=file, caption=caption_text, parse_mode="Markdown")
            else:
                await context.bot.send_video(chat_id=query.message.chat_id, video=file, caption=caption_text, supports_streaming=True, parse_mode="Markdown")

        if os.path.exists(filepath):
            os.remove(filepath)

        await query.delete_message()

    except Exception as e:
        logging.error(f"Download Error: {e}")
        await query.edit_message_text("❌ **Download မအောင်မြင်ပါ။ မီး၊ ကွန်ရက် သို့မဟုတ် File အကန့်အသတ်ကြောင့် ဖြစ်နိုင်ပါသည်။**", parse_mode="Markdown")

    finally:
        USER_DATA.pop(user_id, None)
