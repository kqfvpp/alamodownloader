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
    self.wfile.write(b"TikTok Bot is alive and running!")

  def log_message(self, format, *args):
    pass


def run_web_server():
  try:
    with socketserver.TCPServer(("0.0.0.0", PORT), SimpleHandler) as httpd:
      print(f"Web server running on port {PORT}")
      httpd.serve_forever()
  except Exception as e:
    print(f"Web server error: {e}")


# Start web server in background thread
threading.Thread(target=run_web_server, daemon=True).start()

# Initialize bot
bot = telebot.TeleBot(TOKEN)
os.makedirs("downloads", exist_ok=True)


@bot.message_handler(commands=["start", "help"])
def send_welcome(message):
  bot.reply_to(
      message,
      "🎬 <b>TikTok Original Quality Downloader</b>\n\nSend me any TikTok link"
      " (video or slide), and I will send you the raw, uncompressed file in"
      " its original quality and 60fps!",
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
    # yt-dlp configuration to fetch the highest quality stream
    ydl_opts = {
        "format": "best",
        "outtmpl": "downloads/%(id)s.%(ext)s",
        "noplaylist": True,
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
      info = ydl.extract_info(tiktok_url, download=True)
      file_path = ydl.prepare_filename(info)
      title = info.get("title", "TikTok Video")

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
          "❌ Failed to process this link. Make sure it's a public TikTok"
          " video.",
          chat_id,
          processing_msg.message_id,
      )
    except Exception:
      pass

  finally:
    # Cleanup temporary local file immediately
    if file_path and os.path.exists(file_path):
      try:
        os.remove(file_path)
      except Exception:
        pass


if __name__ == "__main__":
  print("TikTok bot is online...")
  while True:
    try:
      bot.infinity_polling(
          skip_pending=True, timeout=60, long_polling_timeout=60
      )
    except Exception as e:
      print(f"Polling error: {e}, restarting in 5 seconds...")
      time.sleep(5)