import os
import telebot
import requests
import re
import json
import asyncio
import aiohttp
from datetime import datetime
from dotenv import load_dotenv
import logging
import time

# Logging sozlash
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

# Bot token (Render Environment Variables dan olinadi)
BOT_TOKEN = os.getenv("BOT_TOKEN")

if not BOT_TOKEN:
    logger.error("❌ BOT_TOKEN topilmadi! Render Environment Variables ni tekshiring.")
    exit(1)

bot = telebot.TeleBot(BOT_TOKEN)

# User Agents
USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:120.0) Gecko/20100101 Firefox/120.0'
]


def get_random_user_agent():
    import random
    return random.choice(USER_AGENTS)


def extract_shortcode(url):
    """Instagram URL'dan shortcode olish"""
    patterns = [
        r'(?:https?://)?(?:www\.)?instagram\.com/(?:p|reel|tv)/([A-Za-z0-9_-]{11})',
        r'instagram\.com/(?:p|reel|tv)/([^/?]+)'
    ]

    for pattern in patterns:
        match = re.search(pattern, url, re.IGNORECASE)
        if match:
            return match.group(1)
    return None


async def get_video_url_async(shortcode):
    """Async video URL olish"""
    try:
        headers = {
            'User-Agent': get_random_user_agent(),
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
        }

        async with aiohttp.ClientSession(headers=headers) as session:
            # Birinchi usul
            url = f"https://www.instagram.com/p/{shortcode}/?__a=1&__d=dis"
            try:
                async with session.get(url, timeout=10) as response:
                    if response.status == 200:
                        data = await response.json()
                        if 'graphql' in data:
                            media = data['graphql']['shortcode_media']
                            if media.get('is_video'):
                                video_url = media.get('video_url')
                                caption = ""
                                if 'edge_media_to_caption' in media:
                                    edges = media['edge_media_to_caption']['edges']
                                    if edges:
                                        caption = edges[0]['node']['text']
                                return video_url, caption
            except:
                pass

            # Ikkinchi usul
            url2 = f"https://www.instagram.com/p/{shortcode}/embed/captioned/"
            try:
                async with session.get(url2, timeout=10) as response:
                    if response.status == 200:
                        html = await response.text()
                        # Video URL ni extract qilish
                        patterns = [
                            r'src="([^"]+\.mp4[^"]*)"',
                            r'video_url":"([^"]+)"'
                        ]
                        for pattern in patterns:
                            match = re.search(pattern, html)
                            if match:
                                video_url = match.group(1).replace('\\u0026', '&')
                                return video_url, "Instagram video"
            except:
                pass

        return None, "Video topilmadi"

    except Exception as e:
        logger.error(f"Video URL olish xatosi: {e}")
        return None, f"Xato: {str(e)}"


@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    welcome_text = """
🤖 *Instagram Video Yuklovchi Bot*

*Qo'llanma:*
1. Instagram video/reels linkini yuboring
2. Video Telegram'ga yuklanadi

*Namuna linklar:*
• https://instagram.com/p/Cxxxxxx/
• https://instagram.com/reel/Cxxxxxx/

*Muhim:* Faqat ochiq profildagi videolar ishlaydi!

🔗 *Hosted on Render.com*
    """
    bot.reply_to(message, welcome_text, parse_mode='Markdown')


@bot.message_handler(commands=['status'])
def show_status(message):
    status_text = """
✅ *Bot Status: Online*
📊 *Platform:* Render.com
⚡ *Performance:* High
🕐 *Uptime:* 24/7
🔒 *Security:* HTTPS Enabled
    """
    bot.reply_to(message, status_text, parse_mode='Markdown')


@bot.message_handler(func=lambda message: True)
def handle_message(message):
    url = message.text.strip()

    if not any(x in url for x in ['instagram.com', 'instagr.am']):
        bot.reply_to(message, "❌ Iltimos, Instagram linkini yuboring!")
        return

    shortcode = extract_shortcode(url)
    if not shortcode:
        bot.reply_to(message, "❌ Noto'g'ri Instagram linki!")
        return

    progress_msg = bot.reply_to(message, "🔍 Video qidirilmoqda...")

    try:
        # Async video URL olish
        video_url, caption = asyncio.run(get_video_url_async(shortcode))

        if not video_url:
            bot.edit_message_text(f"❌ {caption}",
                                  message.chat.id,
                                  progress_msg.message_id)
            return

        bot.edit_message_text("📥 Video yuklanmoqda...",
                              message.chat.id,
                              progress_msg.message_id)

        # Videoni yuklab olish
        headers = {'User-Agent': get_random_user_agent()}
        response = requests.get(video_url, headers=headers, stream=True, timeout=30)

        if response.status_code == 200:
            # Temporary file in memory
            from io import BytesIO
            video_buffer = BytesIO()

            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    video_buffer.write(chunk)

            video_buffer.seek(0)

            # Send video
            bot.send_video(
                message.chat.id,
                video_buffer,
                caption=caption[:1000] if caption else "📹 Instagram video",
                reply_to_message_id=message.message_id,
                supports_streaming=True
            )

            bot.delete_message(message.chat.id, progress_msg.message_id)

        else:
            bot.edit_message_text("❌ Videoni yuklab bo'lmadi",
                                  message.chat.id,
                                  progress_msg.message_id)

    except Exception as e:
        logger.error(f"Xatolik: {e}")
        bot.edit_message_text(f"❌ Xatolik: {str(e)}",
                              message.chat.id,
                              progress_msg.message_id)


def main():
    """Main function with error handling"""
    logger.info("🤖 Bot Render.com da ishga tushmoqda...")
    logger.info(f"📋 Token uzunligi: {len(BOT_TOKEN)}")

    while True:
        try:
            bot.polling(none_stop=True, interval=0, timeout=30)
        except Exception as e:
            logger.error(f"Bot xatosi: {e}")
            time.sleep(5)


if __name__ == "__main__":
    main()