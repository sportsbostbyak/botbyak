import logging
import os
import threading
import time
import urllib.parse
from flask import Flask, send_from_directory, request, jsonify, Response
from pyngrok import ngrok, conf
from qbittorrentapi import Client
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackContext

# 🚀 Replace with your own values
TELEGRAM_BOT_TOKEN = "7596719015:AAEfnelPZgsnXRNwLdKVgeIn963gcbS75PM"
QBITTORRENT_HOST = "localhost"
QBITTORRENT_PORT = 8080
QBITTORRENT_USERNAME = "akadmin"
QBITTORRENT_PASSWORD = "12qw12"

# 📂 User-Specific Download Directory
BASE_DOWNLOAD_DIR = r"C:\Users\anilk\Downloads\Torrents"

# ✅ Setup Logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# 🌍 Flask App for file hosting
app = Flask(__name__)
@app.after_request
def remove_ngrok_warning(response):
    response.headers["ngrok-skip-browser-warning"] = "true"
    response.headers["User-Agent"] = "MyCustomAgent"
    return response

# 🚀 Configure Ngrok
conf.get_default().request_timeout = 120
ngrok_tunnel = ngrok.connect(5000)
PUBLIC_URL = ngrok_tunnel.public_url
logging.info(f"🌍 Ngrok Public URL: {PUBLIC_URL}")

# 🔗 Connect to qBittorrent
try:
    qb = Client(host=QBITTORRENT_HOST, port=QBITTORRENT_PORT, username=QBITTORRENT_USERNAME, password=QBITTORRENT_PASSWORD)
    qb.auth_log_in()
    logging.info("✅ Connected to qBittorrent successfully!")
except Exception as e:
    logging.error(f"❌ Failed to connect to qBittorrent: {e}")
    exit(1)

# 🌐 Track multiple torrents per user
user_torrent_map = {}  # {chat_id: [torrent_hash1, torrent_hash2, ...]}
torrent_user_map = {}  # {torrent_hash: chat_id}

# ✅ Ensure base download directory exists
os.makedirs(BASE_DOWNLOAD_DIR, exist_ok=True)

# 🎯 Telegram Bot Handlers
async def start(update: Update, context: CallbackContext) -> None:
    await update.message.reply_text("🚀 Send me a magnet link to start downloading!")

async def add_torrent(update: Update, context: CallbackContext) -> None:
    """Handles the user sending a magnet link and adds the torrent to qBittorrent."""
    global user_torrent_map, torrent_user_map

    message = update.message.text
    chat_id = update.message.chat_id

    if not message.startswith("magnet:?"):
        await update.message.reply_text("⚠️ Please send a valid magnet link.")
        return

    # 📂 Create user-specific download directory
    user_download_dir = os.path.join(BASE_DOWNLOAD_DIR, str(chat_id))
    os.makedirs(user_download_dir, exist_ok=True)

    try:
        # 🌐 Add magnet link to qBittorrent with user-specific download location
        qb.torrents_add(urls=message, save_path=user_download_dir)
        time.sleep(3)  # Wait for qBittorrent to process the torrent

        # 🔍 Fetch torrent list
        torrents = qb.torrents_info()
        added_torrent = max(torrents, key=lambda t: t.added_on) if torrents else None

        if not added_torrent:
            await update.message.reply_text("❌ Failed to add torrent. Try again.")
            return

        torrent_hash = added_torrent.hash
        logging.info(f"✅ Torrent added: {added_torrent.name} ({torrent_hash})")

        # 🔹 Store the torrent under the user's chat_id
        user_torrent_map.setdefault(chat_id, []).append(torrent_hash)
        torrent_user_map[torrent_hash] = chat_id

        await update.message.reply_text(f"✅ Torrent added: {added_torrent.name}!\nYou'll receive the download link when it's done.")

    except Exception as e:
        logging.error(f"❌ Error adding torrent: {e}")
        await update.message.reply_text("❌ Error adding the torrent. Please try again.")

async def check_completed_torrents(context: CallbackContext) -> None:
    """Checks torrents and notifies users when a torrent is complete."""
    global user_torrent_map, torrent_user_map

    try:
        torrents = qb.torrents_info()

        for torrent in torrents:
            torrent_hash = torrent.hash
            chat_id = torrent_user_map.get(torrent_hash)

            if not chat_id:
                continue  # Torrent not linked to a user

            # ✅ If torrent is complete, notify the user
            if torrent.state == "uploading" or torrent.progress == 1:
                user_download_dir = os.path.join(BASE_DOWNLOAD_DIR, str(chat_id))
                download_link = f"{PUBLIC_URL}/download/{chat_id}/{torrent.name}"
                stream_link = f"{PUBLIC_URL}/stream/{chat_id}/{torrent.name}"

                await context.bot.send_message(
                    chat_id=chat_id,
                    text=f"✅ Torrent *{torrent.name}* is complete!\n📥 [Download]({download_link})\n▶️ [Stream]({stream_link})",
                    parse_mode="Markdown"
                )

                # Remove from tracking after completion
                user_torrent_map[chat_id].remove(torrent_hash)
                del torrent_user_map[torrent_hash]

    except Exception as e:
        logging.error(f"❌ Error checking torrents: {e}")
async def check_status(update: Update, context: CallbackContext) -> None:
    """Allows users to check the status of their active torrents."""
    chat_id = update.message.chat_id
    user_torrents = user_torrent_map.get(chat_id, [])

    if not user_torrents:
        await update.message.reply_text("📂 You have no active torrents.")
        return

    try:
        torrents = qb.torrents_info()
        response_message = "📊 *Your Torrent Status:*\n\n"

        for torrent in torrents:
            if torrent.hash in user_torrents:
                progress = round(torrent.progress * 100, 2)
                status = torrent.state.capitalize()
                size = round(torrent.total_size / (1024 * 1024), 2)  # Convert to MB
                speed = round(torrent.dlspeed / (1024 * 1024), 2)  # Convert to MB/s

                response_message += (
                    f"🎬 *{torrent.name}*\n"
                    f"📥 *Progress:* {progress}%\n"
                    f"⚡ *Speed:* {speed} MB/s\n"
                    f"📌 *Size:* {size} MB\n"
                    f"📌 *Status:* {status}\n\n"
                )

        response_message += "ℹ️ *Note:* This Process does *not* consume your data though the status is Downloading! ✅"

        await update.message.reply_text(response_message, parse_mode="Markdown")

    except Exception as e:
        logging.error(f"❌ Error fetching torrent status: {e}")
        await update.message.reply_text("❌ Failed to fetch torrent status. Please try again.")

def find_actual_filename(user_chat_id, partial_name):
    """ Finds the actual filename in the user's download folder """
    user_download_dir = os.path.join(BASE_DOWNLOAD_DIR, str(user_chat_id))
    
    if not os.path.exists(user_download_dir):
        return None
    
    for filename in os.listdir(user_download_dir):
        if partial_name.lower() in filename.lower():
            return filename
    return None

@app.route("/download/<int:user_chat_id>/<path:partial_filename>")
def download_file(user_chat_id, partial_filename):
    """ Serves the file only if the requesting user is authorized """
    actual_filename = find_actual_filename(user_chat_id, partial_filename)

    if not actual_filename:
        return jsonify({"error": "File not found"}), 404

    file_path = os.path.join(BASE_DOWNLOAD_DIR, str(user_chat_id), actual_filename)
    
    response = send_from_directory(os.path.dirname(file_path), actual_filename, as_attachment=True)

    # Schedule file deletion after 24 hours
    def delayed_delete():
        time.sleep(86400)  # 24 hours
        if os.path.exists(file_path):
            os.remove(file_path)
            logging.info(f"🗑️ Deleted file after 24 hours: {actual_filename}")

    threading.Thread(target=delayed_delete).start()

    return response

@app.route("/stream/<int:user_chat_id>/<path:partial_filename>")
def stream_file(user_chat_id, partial_filename):
    """ Streams the file only if the requesting user is authorized """
    actual_filename = find_actual_filename(user_chat_id, partial_filename)

    if not actual_filename:
        return jsonify({"error": "File not found"}), 404

    file_path = os.path.join(BASE_DOWNLOAD_DIR, str(user_chat_id), actual_filename)

    def generate():
        with open(file_path, "rb") as f:
            while chunk := f.read(4096):
                yield chunk

    return Response(generate(), content_type="video/mp4")

# 🏃 Start the Telegram Bot
def run_bot():
    bot_app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    bot_app.add_handler(CommandHandler("start", start))
    bot_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, add_torrent))
    bot_app.add_handler(CommandHandler("status", check_status)) 
    job_queue = bot_app.job_queue
    job_queue.run_repeating(check_completed_torrents, interval=10, first=5)

    logging.info("🕒 Job queue started!")
    logging.info("🤖 Telegram Bot running!")

    bot_app.run_polling()

if __name__ == "__main__":
    threading.Thread(target=app.run, kwargs={"port": 5000, "use_reloader": False}).start()
    run_bot()

