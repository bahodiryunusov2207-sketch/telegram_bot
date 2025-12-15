import os
import telebot
import requests
import re
import json
import asyncio
import aiohttp
import time
import threading
from datetime import datetime
from dotenv import load_dotenv
import logging
from flask import Flask, request, jsonify
from io import BytesIO
import tempfile
import urllib.parse

# Logging sozlash
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

# Bot token
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    logger.error("❌ BOT_TOKEN topilmadi!")
    exit(1)

# Max video size (150MB)
MAX_VIDEO_SIZE = 150 * 1024 * 1024  # 150MB in bytes

bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")

# Flask app
app = Flask(__name__)

# Render URL
RENDER_EXTERNAL_URL = os.getenv('RENDER_EXTERNAL_URL', 'https://telegram-bot-cicd.onrender.com')
WEBHOOK_URL = f"{RENDER_EXTERNAL_URL}/{BOT_TOKEN}"


# ==================== INSTAGRAM DOWNLOADER ====================

class InstagramDownloader:
    """Instagram video downloader with multiple methods"""

    def __init__(self):
        self.USER_AGENTS = [
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:120.0) Gecko/20100101 Firefox/120.0',
            'Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1',
            'Mozilla/5.0 (Linux; Android 13; SM-S901B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/112.0.0.0 Mobile Safari/537.36',
            'Instagram 269.0.0.18.75 Android (28/9.0; 480dpi; 1080x2028; Google/google; Pixel 3; blueline; blueline; en_US)'
        ]

        self.headers = {
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Accept-Encoding': 'gzip, deflate, br',
            'DNT': '1',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
            'Sec-Fetch-User': '?1',
            'Cache-Control': 'max-age=0',
        }

    def get_random_headers(self):
        import random
        headers = self.headers.copy()
        headers['User-Agent'] = random.choice(self.USER_AGENTS)
        return headers

    def extract_shortcode(self, url):
        """Extract shortcode from Instagram URL"""
        patterns = [
            r'(?:https?://)?(?:www\.)?instagram\.com/(?:p|reel|tv)/([A-Za-z0-9_-]{11})',
            r'(?:https?://)?(?:www\.)?instagram\.com/(?:p|reel|tv)/([^/?]+)',
            r'instagram\.com/(?:p|reel|tv)/([^/?]+)'
        ]

        for pattern in patterns:
            match = re.search(pattern, url, re.IGNORECASE)
            if match:
                return match.group(1)
        return None

    async def get_video_url_async(self, shortcode):
        """Get video URL using multiple methods"""

        methods = [
            self._method_graphql,
            self._method_embed,
            self._method_oembed,
            self._method_ddinstagram,
            self._method_bibliogram
        ]

        for method in methods:
            try:
                video_url, caption = await method(shortcode)
                if video_url:
                    logger.info(f"✅ Method success: {method.__name__}")
                    return video_url, caption
            except Exception as e:
                logger.debug(f"Method {method.__name__} failed: {e}")
                continue

        return None, "Video topilmadi"

    async def _method_graphql(self, shortcode):
        """Method 1: GraphQL API"""
        url = f"https://www.instagram.com/p/{shortcode}/?__a=1&__d=dis"
        headers = self.get_random_headers()

        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.get(url, timeout=10) as response:
                if response.status == 200:
                    data = await response.json()

                    # Try different response structures
                    video_url = None
                    caption = ""

                    # New structure
                    if 'items' in data and len(data['items']) > 0:
                        item = data['items'][0]
                        if 'video_versions' in item:
                            video_url = item['video_versions'][0]['url']
                        caption = item.get('caption', {}).get('text', '')

                    # Old structure
                    elif 'graphql' in data:
                        media = data['graphql']['shortcode_media']
                        if media.get('is_video'):
                            video_url = media.get('video_url')
                            if 'edge_media_to_caption' in media:
                                edges = media['edge_media_to_caption']['edges']
                                if edges:
                                    caption = edges[0]['node']['text']

                    if video_url:
                        return video_url, caption

        return None, ""

    async def _method_embed(self, shortcode):
        """Method 2: Embed page"""
        url = f"https://www.instagram.com/p/{shortcode}/embed/captioned/"
        headers = self.get_random_headers()

        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.get(url, timeout=10) as response:
                if response.status == 200:
                    html = await response.text()

                    # Look for video URL in embed
                    patterns = [
                        r'src="([^"]+\.mp4[^"]*)"',
                        r'video_url":"([^"]+)"',
                        r'content="([^"]+\.mp4[^"]*)"',
                        r'videoSrc":"([^"]+)"'
                    ]

                    for pattern in patterns:
                        match = re.search(pattern, html)
                        if match:
                            video_url = match.group(1)
                            video_url = video_url.replace('\\u0026', '&')
                            return video_url, "Instagram video"

        return None, ""

    async def _method_oembed(self, shortcode):
        """Method 3: OEmbed API"""
        url = f"https://www.instagram.com/p/{shortcode}/"
        oembed_url = f"https://api.instagram.com/oembed/?url={urllib.parse.quote(url)}"
        headers = self.get_random_headers()

        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.get(oembed_url, timeout=10) as response:
                if response.status == 200:
                    data = await response.json()
                    # OEmbed only gives metadata, need another method for actual video
                    return None, data.get('title', '')

        return None, ""

    async def _method_ddinstagram(self, shortcode):
        """Method 4: ddinstagram.com (alternative frontend)"""
        url = f"https://www.ddinstagram.com/p/{shortcode}"
        headers = self.get_random_headers()

        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.get(url, timeout=10) as response:
                if response.status == 200:
                    html = await response.text()

                    # Look for video
                    patterns = [
                        r'<video[^>]+src="([^"]+)"',
                        r'src="([^"]+\.mp4)"'
                    ]

                    for pattern in patterns:
                        match = re.search(pattern, html)
                        if match:
                            return match.group(1), "Instagram video"

        return None, ""

    async def _method_bibliogram(self, shortcode):
        """Method 5: Bibliogram (alternative frontend)"""
        url = f"https://bibliogram.art/p/{shortcode}"
        headers = self.get_random_headers()

        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.get(url, timeout=10) as response:
                if response.status == 200:
                    html = await response.text()

                    # Bibliogram specific parsing
                    if 'video' in html.lower():
                        # Try to find video source
                        patterns = [
                            r'<source[^>]+src="([^"]+)"',
                            r'src="([^"]+/video/[^"]+)"'
                        ]

                        for pattern in patterns:
                            match = re.search(pattern, html)
                            if match:
                                return match.group(1), "Instagram video"

        return None, ""

    def download_video(self, video_url, max_size=MAX_VIDEO_SIZE):
        """Download video with progress and size check"""
        try:
            headers = self.get_random_headers()

            # First, check size
            response_head = requests.head(video_url, headers=headers, timeout=10)
            content_length = response_head.headers.get('content-length')

            if content_length:
                size = int(content_length)
                if size > max_size:
                    return None, f"Video juda katta ({size // 1024 // 1024}MB). Max: {max_size // 1024 // 1024}MB"

            # Download with streaming
            response = requests.get(video_url, headers=headers, stream=True, timeout=30)

            if response.status_code == 200:
                # Create temporary file
                temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.mp4')

                downloaded = 0
                start_time = time.time()

                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        temp_file.write(chunk)
                        downloaded += len(chunk)

                        # Check if exceeding max size during download
                        if downloaded > max_size:
                            temp_file.close()
                            os.unlink(temp_file.name)
                            return None, f"Video {max_size // 1024 // 1024}MB dan katta"

                temp_file.close()

                # Check final size
                file_size = os.path.getsize(temp_file.name)
                if file_size > max_size:
                    os.unlink(temp_file.name)
                    return None, f"Video {max_size // 1024 // 1024}MB dan katta"

                download_time = time.time() - start_time
                speed = downloaded / download_time / 1024  # KB/s

                logger.info(f"✅ Video downloaded: {file_size // 1024 // 1024}MB, speed: {speed:.1f}KB/s")
                return temp_file.name, None

            else:
                return None, f"Download error: {response.status_code}"

        except Exception as e:
            logger.error(f"Download error: {e}")
            return None, str(e)


# Initialize downloader
downloader = InstagramDownloader()


# ==================== TELEGRAM BOT HANDLERS ====================

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    welcome_text = """
<b>🤖 Instagram Video Yuklovchi Bot</b>

<b>📌 Qo'llanma:</b>
1. Instagram video/reels linkini yuboring
2. Bot video Telegram'ga yuklaydi

<b>✅ Qo'llab-quvvatlanadi:</b>
• Post videolari
• Reels
• IGTV
• Ochiq profillar

<b>❌ Cheklovlar:</b>
• Yopiq profillar
• 150MB dan katta videolar
• Mualliflik huquqi bilan himoyalangan

<b>⚡ Maxsus:</b>
• 150MB gacha videolar
• Tez yuklash
• Ko'p usullar

📎 <b>Namuna:</b>
<code>https://instagram.com/p/Cxxxxxx/</code>
<code>https://instagram.com/reel/Cxxxxxx/</code>

🔗 <i>Hosted on Render.com</i>
    """
    bot.reply_to(message, welcome_text)


@bot.message_handler(commands=['status'])
def show_status(message):
    status_text = """
<b>📊 Bot Status</b>
✅ <b>Holat:</b> Online
🌐 <b>Platform:</b> Render.com
⚡ <b>Rejim:</b> Webhook
💾 <b>Video hajmi:</b> Max 150MB
🔧 <b>Versiya:</b> Premium
🕐 <b>Uptime:</b> 24/7
    """
    bot.reply_to(message, status_text)


@bot.message_handler(commands=['size'])
def show_size_limit(message):
    size_info = """
<b>📏 Video Hajmi Cheklovlari</b>
✅ <b>Maksimal:</b> 150 MB
✅ <b>Tavsiya:</b> 100 MB gacha
✅ <b>Optimal:</b> 50 MB gacha

<i>150MB dan katta videolar yuklanmaydi.
Telegram API limiti: 50MB (botlar uchun 2000MB)</i>
    """
    bot.reply_to(message, size_info)


@bot.message_handler(func=lambda message: True)
def handle_message(message):
    """Asynchronous message handler"""

    # Start processing in background thread
    thread = threading.Thread(
        target=process_message,
        args=(message,),
        daemon=True
    )
    thread.start()

    # Send immediate response
    bot.reply_to(message, "🔍 Video qidirilmoqda...")


def process_message(message):
    """Process message in background"""
    try:
        url = message.text.strip()
        chat_id = message.chat.id
        message_id = message.message_id

        # Check if Instagram URL
        if not any(x in url.lower() for x in ['instagram.com', 'instagr.am']):
            bot.send_message(chat_id, "❌ Iltimos, faqat Instagram linkini yuboring!")
            return

        # Extract shortcode
        shortcode = downloader.extract_shortcode(url)
        if not shortcode:
            bot.send_message(chat_id, "❌ Noto'g'ri Instagram linki!")
            return

        # Send progress message
        progress_msg = bot.send_message(chat_id, "🔍 Video manzili qidirilmoqda...")

        # Get video URL
        video_url, caption = asyncio.run(downloader.get_video_url_async(shortcode))

        if not video_url:
            bot.edit_message_text(
                f"❌ {caption}",
                chat_id,
                progress_msg.message_id
            )
            return

        # Update progress
        bot.edit_message_text(
            "📥 Video yuklanmoqda... (150MB gacha)",
            chat_id,
            progress_msg.message_id
        )

        # Download video
        video_path, error = downloader.download_video(video_url)

        if error:
            bot.edit_message_text(
                f"❌ {error}",
                chat_id,
                progress_msg.message_id
            )
            return

        # Update progress
        bot.edit_message_text(
            "📤 Telegram'ga yuborilmoqda...",
            chat_id,
            progress_msg.message_id
        )

        # Get video size
        file_size = os.path.getsize(video_path)
        size_mb = file_size / 1024 / 1024

        # Send video to Telegram
        with open(video_path, 'rb') as video_file:
            bot.send_video(
                chat_id,
                video_file,
                caption=f"{caption[:500]}\n\n📏 Hajmi: {size_mb:.1f}MB" if caption else f"📹 Instagram video\n📏 Hajmi: {size_mb:.1f}MB",
                reply_to_message_id=message_id,
                supports_streaming=True,
                timeout=60
            )

        # Delete progress message
        bot.delete_message(chat_id, progress_msg.message_id)

        # Clean up temp file
        os.unlink(video_path)

        logger.info(f"✅ Video sent to {chat_id}, size: {size_mb:.1f}MB")

    except Exception as e:
        logger.error(f"Error processing message: {e}")
        try:
            bot.send_message(
                message.chat.id,
                f"❌ Xatolik: {str(e)[:200]}"
            )
        except:
            pass


# ==================== FLASK ROUTES ====================

@app.route('/')
def home():
    return '''
    <!DOCTYPE html>
    <html>
    <head>
        <title>Instagram Video Bot</title>
        <style>
            body { font-family: Arial, sans-serif; max-width: 800px; margin: 0 auto; padding: 20px; }
            .container { text-align: center; margin-top: 50px; }
            .status { color: green; font-weight: bold; }
            .features { text-align: left; margin: 30px 0; }
            .btn { display: inline-block; padding: 10px 20px; background: #0088cc; color: white; text-decoration: none; border-radius: 5px; margin: 10px; }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>🤖 Instagram Video Bot</h1>
            <p class="status">🟢 Bot is running on Render.com</p>

            <div class="features">
                <h3>✨ Xususiyatlari:</h3>
                <ul>
                    <li>✅ Instagram videolari va reels</li>
                    <li>✅ 150MB gacha videolar</li>
                    <li>✅ Tez yuklash</li>
                    <li>✅ Ko'p usullar</li>
                    <li>✅ Webhook rejimi</li>
                </ul>
            </div>

            <p>
                <a href="/health" class="btn">Health Check</a>
                <a href="/set_webhook" class="btn">Setup Webhook</a>
                <a href="/stats" class="btn">Statistics</a>
            </p>

            <p>Telegram: <strong>@your_bot_username</strong></p>
        </div>
    </body>
    </html>
    '''


@app.route('/health')
def health():
    return jsonify({
        "status": "healthy",
        "service": "instagram-video-bot",
        "timestamp": datetime.now().isoformat(),
        "max_video_size": "150MB",
        "version": "2.0"
    })


@app.route('/set_webhook')
def set_webhook():
    try:
        bot.remove_webhook()
        time.sleep(1)
        bot.set_webhook(url=WEBHOOK_URL)
        return f'''
        <h1>✅ Webhook Set Successfully!</h1>
        <p>URL: {WEBHOOK_URL}</p>
        <p><a href="/">Back to Home</a></p>
        '''
    except Exception as e:
        return f'''
        <h1>❌ Webhook Error</h1>
        <p>Error: {str(e)}</p>
        <p><a href="/">Back to Home</a></p>
        '''


@app.route('/stats')
def stats():
    return jsonify({
        "max_video_size_mb": 150,
        "supported_formats": ["mp4", "video"],
        "methods": ["graphql", "embed", "oembed", "ddinstagram", "bibliogram"],
        "updates": "2025-12-15 - Added 150MB support"
    })


@app.route(f'/{BOT_TOKEN}', methods=['POST'])
def webhook():
    """Telegram webhook endpoint"""
    if request.headers.get('content-type') == 'application/json':
        json_string = request.get_data().decode('utf-8')
        update = telebot.types.Update.de_json(json_string)
        bot.process_new_updates([update])
        return 'OK', 200
    else:
        return 'Bad Request', 400


# ==================== MAIN ====================

if __name__ == '__main__':
    # Portni Render'dan olish
    port = int(os.environ.get('PORT', 5000))

    logger.info("🚀 Starting Instagram Video Bot...")
    logger.info(f"🌐 Webhook URL: {WEBHOOK_URL}")
    logger.info(f"🔑 Token length: {len(BOT_TOKEN)}")
    logger.info(f"📏 Max video size: {MAX_VIDEO_SIZE // 1024 // 1024}MB")

    # Avtomatik webhook o'rnatish
    try:
        bot.remove_webhook()
        time.sleep(1)
        bot.set_webhook(url=WEBHOOK_URL)
        logger.info("✅ Webhook set successfully!")
    except Exception as e:
        logger.error(f"❌ Webhook error: {e}")

    # Flask serverni ishga tushirish
    app.run(host='0.0.0.0', port=port, debug=False)