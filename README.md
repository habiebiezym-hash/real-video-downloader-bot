# Telegram Video Downloader Bot 🎬

ဒီ Bot က YouTube, TikTok, Facebook နဲ့ YouTube Music Search ကနေ Video/Audio ဒေါင်းလုဒ်ဆွဲပေးနိုင်ပါတယ်။

## Features
- 🎬 YouTube Video Download (360p, 480p, 720p, 1080p)
- 🎵 YouTube Music Search & MP3 Download
- 📘 Facebook Video Download
- 🎵 TikTok Video Download
- 📊 Admin Stats
- 🛡️ Rate Limiting

## Deployment on Railway

1. Fork this repository
2. Create a new project on Railway
3. Add environment variables:
   - `BOT_TOKEN`: Your Telegram Bot Token
   - `ADMIN_ID`: Your Telegram User ID
   - `PORT`: 8080 (default)

## Local Development

```bash
# Install dependencies
pip install -r requirements.txt

# Create .env file with your BOT_TOKEN
# Run the bot
python bot.py