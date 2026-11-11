import http.server
import io
import os
import re
import threading
import time
import traceback
from html import escape

import requests
import telebot
from telebot import types

# Prefer an environment variable (set BOT_TOKEN on Render); fall back to config.py
TOKEN = os.environ.get("BOT_TOKEN")
if not TOKEN:
  from config import TOKEN

# --- KEEP-ALIVE WEB SERVER FOR RENDER (Supports GET & HEAD for UptimeRobot) ---
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
    httpd = http.server.ThreadingHTTPServer(("0.0.0.0", PORT), SimpleHandler)
    print(f"Web server running on port {PORT}")
    httpd.serve_forever()
  except Exception as e:
    print(f"Web server error: {e}")


# Start keep-alive server in background thread
threading.Thread(target=run_web_server, daemon=True).start()

# --- BOT SETUP ---
bot = telebot.TeleBot(TOKEN, threaded=True)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        " (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    )
}

TIKWM_BASE = "https://www.tikwm.com"
TIKTOK_RE = re.compile(r"https?://(?:[\w-]+\.)*tiktok\.com/\S+", re.IGNORECASE)
SHORT_RE = re.compile(
    r"https?://(?:vm|vt)\.tiktok\.com/|tiktok\.com/t/", re.IGNORECASE
)

# Telegram bots can upload files up to 50 MB
MAX_UPLOAD_BYTES = 49 * 1024 * 1024


class TooBigError(Exception):
  pass


def extract_tiktok_url(text):
  """Pull the first TikTok link out of a message (it may have extra text)."""
  match = TIKTOK_RE.search(text or "")
  if not match:
    return None
  return match.group(0).rstrip(").,!?\"'>]")


def expand_short_url(url):
  """Follow redirects for short links (vm./vt./tiktok.com/t/)."""
  if not SHORT_RE.search(url):
    return url
  try:
    r = requests.get(url, headers=HEADERS, allow_redirects=True, timeout=10)
    return r.url
  except Exception:
    return url


def absolute(url):
  """tikwm sometimes returns relative paths like /video/media/play/..."""
  if not url:
    return None
  if url.startswith("//"):
    return "https:" + url
  if url.startswith("/"):
    return TIKWM_BASE + url
  return url


def fetch_info(tiktok_url):
  """Ask tikwm for the video data. Retries because of its 1 request/sec limit."""
  last_error = "API error"
  for attempt in range(4):
    r = requests.get(
        f"{TIKWM_BASE}/api/",
        params={"url": tiktok_url, "hd": 1},
        headers=HEADERS,
        timeout=20,
    )
    res_json = r.json()
    if res_json.get("code") == 0 and res_json.get("data"):
      return res_json["data"]
    last_error = str(res_json.get("msg") or "API error")
    if "limit" in last_error.lower():
      time.sleep(1.5 * (attempt + 1))
      continue
    break
  raise RuntimeError(last_error)


def download_to_memory(url, limit=MAX_UPLOAD_BYTES):
  """Download a file into memory, refusing anything bigger than `limit`."""
  with requests.get(
      url, headers=HEADERS, stream=True, timeout=(10, 60)
  ) as r:
    r.raise_for_status()
    declared = int(r.headers.get("Content-Length") or 0)
    if declared > limit:
      raise TooBigError()
    buf = io.BytesIO()
    for chunk in r.iter_content(chunk_size=256 * 1024):
      buf.write(chunk)
      if buf.tell() > limit:
        raise TooBigError()
  if buf.tell() == 0:
    raise RuntimeError("Downloaded file is empty.")
  buf.seek(0)
  buf.name = "tiktok.mp4"
  return buf


def build_caption(title):
  title = (title or "TikTok Video").strip()
  if len(title) > 100:
    title = title[:97] + "..."
  return f"✨ <b>{escape(title)}</b>\n⚡ <i>Original Quality / No Watermark</i>"


@bot.message_handler(commands=["start", "help"])
def send_welcome(message):
  bot.reply_to(
      message,
      "🎬 <b>TikTok Pure Quality Downloader</b>\n\nSend me any public TikTok"
      " link (including short vm.tiktok.com links), and I will instantly send"
      " you the clean, unwatermarked video!",
      parse_mode="HTML",
  )


@bot.message_handler(
    func=lambda message: message.text and extract_tiktok_url(message.text)
)
def download_tiktok(message):
  chat_id = message.chat.id
  raw_url = extract_tiktok_url(message.text)

  processing_msg = bot.send_message(
      chat_id, "⏳ Resolving and fetching video from TikTok..."
  )

  def set_status(text):
    try:
      bot.edit_message_text(text, chat_id, processing_msg.message_id)
    except Exception:
      pass

  try:
    tiktok_url = expand_short_url(raw_url)
    data = fetch_info(tiktok_url)
    caption = build_caption(data.get("title"))

    # --- Photo slideshow posts ---
    images = [absolute(u) for u in (data.get("images") or [])]
    if images:
      set_status("📤 Sending photos...")
      for i in range(0, len(images), 10):
        chunk = images[i : i + 10]
        media = [
            types.InputMediaPhoto(
                u,
                caption=caption if (i == 0 and j == 0) else None,
                parse_mode="HTML" if (i == 0 and j == 0) else None,
            )
            for j, u in enumerate(chunk)
        ]
        bot.send_media_group(chat_id, media)
      try:
        bot.delete_message(chat_id, processing_msg.message_id)
      except Exception:
        pass
      return

    # --- Normal video posts: try HD first, then the standard version ---
    candidates = []
    for key in ("hdplay", "play"):
      u = absolute(data.get(key))
      if u and u not in candidates:
        candidates.append(u)

    if not candidates:
      raise RuntimeError("Video stream link not found.")

    set_status("⬇️ Downloading video...")
    video_file = None
    last_link = candidates[0]
    for u in candidates:
      last_link = u
      try:
        video_file = download_to_memory(u)
        break
      except TooBigError:
        continue
      except Exception as e:
        print(f"Download attempt failed for {u}: {e}")
        continue

    if video_file is None:
      # Too large for Telegram bots (or download kept failing): send the link
      bot.send_message(
          chat_id,
          "⚠️ This video is too large to send through Telegram. You can"
          f' download it here:\n<a href="{escape(last_link)}">Direct'
          " download link</a>",
          parse_mode="HTML",
      )
      try:
        bot.delete_message(chat_id, processing_msg.message_id)
      except Exception:
        pass
      return

    set_status("📤 Sending video...")
    bot.send_video(
        chat_id,
        video_file,
        caption=caption,
        parse_mode="HTML",
        supports_streaming=True,
        timeout=120,
    )

    try:
      bot.delete_message(chat_id, processing_msg.message_id)
    except Exception:
      pass

  except Exception as e:
    print(f"Download error: {e}")
    traceback.print_exc()
    set_status(
        "❌ Failed to process this link. Make sure it's a valid, public"
        " TikTok video and try again in a few seconds."
    )


if __name__ == "__main__":
  print("API-based TikTok bot is online and fully updated...")
  try:
    # A leftover webhook makes polling fail with "409 Conflict"
    bot.remove_webhook()
  except Exception as e:
    print(f"remove_webhook failed: {e}")

  while True:
    try:
      bot.infinity_polling(
          skip_pending=True, timeout=20, long_polling_timeout=30
      )
    except Exception as e:
      print(f"Polling error: {e}, restarting in 5 seconds...")
      time.sleep(5)
