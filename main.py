from datetime import datetime, timedelta, timezone
from html import escape
import http.server
import os
import socketserver
import threading
import time
import telebot
from telebot import types
import yt_dlp
from config import TOKEN

# --- KEEP-ALIVE WEB SERVER FOR RENDER ---
PORT = int(os.environ.get("PORT", 10000))


class SimpleHandler(http.server.BaseHTTPRequestHandler):

  def do_GET(self):
    self.send_response(200)
    self.end_headers()
    self.wfile.write(b"TikTok Downloader Bot is active!")

  def log_message(self, format, *args):
    pass


def run_web_server():
  try:
    with socketserver.TCPServer(("0.0.0.0", PORT), SimpleHandler) as httpd:
      print(f"Web server running on port {PORT}")
      httpd.serve_forever()
  except Exception as e:
    print(f"Web server error: {e}")


# Start keep-alive server in background
threading.Thread(target=run_web_server, daemon=True).start()

# Initialize bot
bot = telebot.TeleBot(TOKEN)
os.makedirs("downloads", exist_ok=True)


@bot.message_handler(commands=["start", "help"])
def send_welcome(message):
  bot.reply_to(
      message,
      "🎬 <b>TikTok Original Quality Downloader</b>\n\nSend me any public TikTok"
      " link, and I will fetch the pure, uncompressed file for you!",
      parse_mode="HTML",
  )


@bot.message_handler(
    func=lambda message: message.text
    and ("tiktok.com" in message.text or "vm.tiktok.com" in message.text)
)
def download_tiktok(message):
  chat_id = message.chat.id
  tiktok_url = message.text.strip()

  processing_msg = bot.send_message(
      chat_id, "⏳ Extracting original stream from TikTok..."
  )

  file_path = None
  try:
    # Advanced yt-dlp configuration with browser headers to bypass datacenter blocks
    ydl_opts = {
        "format": "best",
        "outtmpl": "downloads/%(id)s.%(ext)s",
        "noplaylist": True,
        "http_headers": {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                " (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
            ),
            "Accept": (
                "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8"
            ),
            "Accept-Language": "en-US,en;q=0.5",
        },
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
      info = ydl.extract_info(tiktok_url, download=True)
      file_path = ydl.prepare_filename(info)
      title = info.get("title", "TikTok Video")

    # Check file size (Telegram Bot API has a strict 50MB limit)
    if os.path.exists(file_path):
      file_size_mb = os.path.getsize(file_path) / (1024 * 1024)
      if file_size_mb > 49:
        bot.edit_message_text(
            "❌ This video is too large (>50MB) for Telegram's bot upload"
            " limit.",
            chat_id,
            processing_msg.message_id,
        )
        return

    bot.edit_message_text(
        "📤 Uploading original file to Telegram...",
        chat_id,
        processing_msg.message_id,
    )

    safe_title = (
        title.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .strip()
    )
    if len(safe_title) > 100:
      safe_title = safe_title[:97] + "..."

    caption = (
        f"✨ <b>{safe_title}</b>\n⚡ <i>Original Quality / No Watermark</i>"
    )

    with open(file_path, "rb") as video_file:
      bot.send_video(
          chat_id,
          video_file,
          caption=caption,
          parse_mode="HTML",
          supports_streaming=True,
      )

    bot.delete_message(chat_id, processing_msg.message_id)

  except Exception as e:
    print(f"Download error: {e}")
    try:
      bot.edit_message_text(
          "❌ Failed to process this link. Make sure it's a valid, public"
          " TikTok video.",
          chat_id,
          processing_msg.message_id,
      )
    except Exception:
      pass

  finally:
    # Guaranteed cleanup of local temporary files
    if file_path and os.path.exists(file_path):
      try:
        os.remove(file_path)
      except Exception:
        pass


if __name__ == "__main__":
  print("TikTok downloader bot is online and fully hardened...")
  while True:
    try:
      bot.infinity_polling(
          skip_pending=True, timeout=60, long_polling_timeout=60
      )
    except Exception as e:
      print(f"Polling error: {e}, restarting in 5 seconds...")
      time.sleep(5)
