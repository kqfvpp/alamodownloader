from datetime import datetime, timedelta, timezone
from html import escape
import http.server
import os
import socketserver
import threading
import time
import requests
import telebot
from telebot import types
from config import TOKEN

# --- KEEP-ALIVE WEB SERVER FOR RENDER ---
PORT = int(os.environ.get("PORT", 10000))


class SimpleHandler(http.server.BaseHTTPRequestHandler):

  def do_GET(self):
    self.send_response(200)
    self.end_headers()
    self.wfile.write(b"TikTok Downloader Bot is active!")

  def do_HEAD(self):
    self.send_response(200)
    self.end_headers()

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


@bot.message_handler(commands=["start", "help"])
def send_welcome(message):
  bot.reply_to(
      message,
      "🎬 <b>TikTok Pure Quality Downloader</b>\n\nSend me any public TikTok"
      " link, and I will instantly send you the clean, unwatermarked video!",
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
      chat_id, "⏳ Fetching video from TikTok..."
  )

  try:
    # Use reliable API endpoint to bypass cloud IP blocks
    api_url = f"https://www.tikwm.com/api/?url={tiktok_url}&hd=1"
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        )
    }

    response = requests.get(api_url, headers=headers, timeout=15)
    res_json = response.json()

    if res_json.get("code") != 0:
      raise Exception("API returned an error for this link.")

    data = res_json["data"]
    # Get HD link if available, otherwise fallback to standard play link
    video_url = data.get("hdplay") or data.get("play")
    title = data.get("title", "TikTok Video")

    if not video_url:
      raise Exception("Video stream link not found.")

    bot.edit_message_text(
        "📤 Sending video...", chat_id, processing_msg.message_id
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

    # Telegram streams the video directly from the URL (no server storage needed!)
    bot.send_video(
        chat_id,
        video_url,
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


if __name__ == "__main__":
  print("API-based TikTok bot is online and bulletproof...")
  while True:
    try:
      bot.infinity_polling(
          skip_pending=True, timeout=60, long_polling_timeout=60
      )
    except Exception as e:
      print(f"Polling error: {e}, restarting in 5 seconds...")
      time.sleep(5)
