#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ربات سرگرمی و محتوای زرد تلگرام (فارسی)
────────────────────────────────────────
• اجرا روی GitHub Actions (رایگان، خارج از ایران، مقاوم به قطعی/فیلترینگ)
• سردبیرِ هوش مصنوعی از GitHub Models (رایگان با GITHUB_TOKEN داخلی)
• پوششِ سلبریتی/شوبیز + وایرال و عجیب‌غریب + حاشیه‌های ورزشی
• روشِ پشتیبانِ کلیدواژه‌ای + ترجمه تا ربات هیچ‌وقت خاموش نشود
• ضدتکرارِ دولایه و حافظه در seen.json
"""

import os
import re
import time
import json
import html
import hashlib

import requests
import feedparser

# ═══════════════════════════ تنظیمات ═══════════════════════════
# توکن‌ها فقط از env خوانده می‌شوند — هرگز داخلِ کد هاردکد نکن
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
GITHUB_TOKEN       = os.environ.get("GITHUB_TOKEN", "")

# ↓↓↓ فقط این دو خط را با مشخصاتِ کانالِ خودت عوض کن ↓↓↓
CHANNEL   = "@MediaZard"                # آیدی کانال (ربات باید ادمینش باشد)
SIGNATURE = "@MediaZard | مدیا زرد"    # امضای پای هر پست
# ↑↑↑ ─────────────────────────────────────────────── ↑↑↑

# مدلِ هوش مصنوعی — gpt-4o-mini ارزان‌تر / gpt-4o قوی‌تر
AI_MODEL    = "openai/gpt-4o-mini"
AI_ENDPOINT = "https://models.github.ai/inference/chat/completions"

# منابع RSS — سرگرمی، شوبیز، وایرال، لایف‌استایل و ورزش
# همه استانداردِ RSS دارند و معمولاً برای ایران بازند.
# سایت‌های گاشیپِ سلبریتیِ متعارف که RSSِ عمومی دارن.
# هر فیدی که جواب نده خودکار رد می‌شود.
RSS_FEEDS = [
    "https://www.tmz.com/rss.xml",                       # TMZ
    "https://www.dailymail.co.uk/tvshowbiz/index.rss",   # دیلی‌میل (شوبیز)
    "https://pagesix.com/feed/",                         # Page Six
    "https://www.justjared.com/feed/",                   # JustJared
    "https://hollywoodlife.com/feed/",                   # HollywoodLife
    "https://bossip.com/feed/",                          # Bossip
]

NUM_CANDIDATES     = 12                 # تعداد کاندیدای ارسالی به سردبیر
RECENT_TITLES_KEEP = 40                # چند تیترِ اخیر برای ضدتکرار نگه داشته شود
SEEN_IDS_KEEP      = 1000              # چند شناسه نگه داشته شود
ARTICLE_MAX_CHARS  = 1800              # سقفِ متنِ استخراجی مقاله
MAX_VIDEO_BYTES    = 50 * 1024 * 1024  # سقفِ دانلودِ ویدیو = ۵۰ مگابایت
JACCARD_THRESHOLD  = 0.5               # آستانه‌ی شباهتِ توکنی
OVERLAP_THRESHOLD  = 0.6               # آستانه‌ی نسبتِ اشتراک به مجموعه‌ی کوچک‌تر

STATE_FILE = "seen.json"
UA = {"User-Agent": "Mozilla/5.0 (compatible; fun-bot/1.0; +https://github.com)"}

# ═══════════════════════════ پرامپتِ سردبیر ═══════════════════════════
SYSTEM_PROMPT = """تو سردبیرِ یه کانالِ سرگرمی و محتوای زردِ پرمخاطبِ تلگرامی. کارت اینه از بینِ چندتا خبر، آب‌دارترین و سرگرم‌کننده‌ترینش رو که عامه‌ی مردم حال می‌کنن بخونن انتخاب کنی و باحال و محاوره‌ای بازنویسی کنی.

اولویتِ انتخاب (هرچی وایرال‌تر و خوش‌آب‌ورنگ‌تر، بهتر):
۱) سوژه‌های وایرال، شوک‌آور، عجیب‌وغریب و بحث‌برانگیز
۲) حاشیه‌های سلبریتی و شوبیز (جدایی، رابطه، دعوا، استایل، ثروت، اتفاقِ خفن سرِ صحنه...)
۳) حاشیه‌های ورزشی (انتقالِ پرسروصدا، دعوا، زندگیِ خصوصیِ ستاره‌ها)
۴) بقیه‌ی چیزای سرگرم‌کننده و جالب

تقریباً همیشه یه چیز انتخاب کن. index = -1 فقط وقتی همه‌چی واقعاً خشک/کسل‌کننده‌ست یا عینِ تکرارِ چیزیه که قبلاً تو «پست‌های اخیر» گذاشتی. یه آپدیتِ تازه روی یه ماجرای در‌جریان «تکراری» حساب نمی‌شه؛ فقط اگه دقیقاً همون سوژه‌ی قبلیه (حتی از منبع/زبانِ دیگه) ردش کن.

سبکِ نگارش (مهم‌ترین بخش):
- فارسیِ محاوره‌ای، شوخ و پرانرژی؛ مثلِ یه آدم که داره برای رفیقش یه سوژه‌ی باحال تعریف می‌کنه: «می‌گه/کرده/قراره/دیگه/یه/اینا/خفن/ترکوند».
- با لیدِ منبع شروع کن: «پیج‌سیکس:»، «ورایتی:»، «گاردین:»، «مشابل:».
- کامل بگو دقیقاً چی شد و چرا جالبه (محتوا، عدد، نتیجه). فقط «فلانی یه پست گذاشت» کافی نیست — بگو چی گذاشت و چی شد.
- ایموجیِ بامزه و مرتبط بذار 😱🔥💔💸😂🎬⚽.
- شایعه رو «شایعه» بگو نه قطعی. هیچی از خودت نساز؛ هرچی هست از منبع بیار.
- درباره‌ی آدما بامزه بنویس ولی توهین‌آمیز و تخریب‌گر نه. سرگرم‌کننده آره، بی‌رحم نه.
- اسم‌ها خنثی و بدونِ جهت‌گیری.
- طول: معمولاً ۲ تا ۴ جمله.
- این کلیشه‌ها ممنوعن: «شایان ذکر است»، «گفتنی است»، «لازم به ذکر است»، «در همین راستا»، «بر این اساس»، «در همین حال»، «بنا بر این گزارش».

hot=true فقط برای سوژه‌های واقعاً منفجرشده/وایرال یا شوکِ بزرگ (مثلِ فوتِ یه ستاره، جداییِ پرسروصدا، رکورد یا اتفاقِ خیلی عجیب). برای چیزای معمولی hot نزن.

خروجی فقط یه JSON، بدونِ هیچ متنِ اضافه و بدونِ بک‌تیک:
{"index": <شماره‌ی کاندیدِ انتخابی یا -1>, "title_fa": "تیترِ کوتاهِ جذاب", "summary_fa": "خلاصه‌ی محاوره‌ای و باحال", "hot": true یا false}

— نمونه ۱ —
{"index": 0, "title_fa": "جداییِ پرسروصدای یکی از معروف‌ترین زوج‌های هالیوود", "summary_fa": "پیج‌سیکس: بعدِ ماه‌ها شایعه، بالاخره تأیید شد که این زوجِ معروف از هم جدا شدن. نزدیکانشون می‌گن رابطه چند ماهه به‌هم ریخته بوده ولی جلوی دوربینا نقش بازی می‌کردن. طرفدارا تو شبکه‌های اجتماعی شوکه شدن و اسمشون سریع ترند شد. 💔😱", "hot": true}

— نمونه ۲ —
{"index": 0, "title_fa": "یه نقاشیِ کشیده‌شده با هوش مصنوعی تو حراجی ترکوند", "summary_fa": "گاردین: یه تابلوی نقاشی که کلاً با هوش مصنوعی کشیده شده بود، تو یه حراجیِ معروف چند صد هزار دلار فروخته شد و کلی بحث راه انداخت. یه عده می‌گن این دیگه آخرِ دنیای هنره، یه عده هم حسابی ذوق کردن. ویدیوی لحظه‌ی فروشش هم تو نت ترکوند. 🎨🤖💸", "hot": false}"""

# کلماتِ پرتکرار که در محاسبه‌ی شباهت نادیده گرفته می‌شوند
STOPWORDS = set((
    "و در به از که این آن را با برای تا یک رو تو هم می اون یه قراره دیگه اینا اونا "
    "خیلیا های ها بر روی یا کرد شد گفت می‌گه می‌کنه است بود شده یک دو سه "
    "the a an of to in on for and or is are was were be by at with from as that this "
    "it its has have had will would new says said after over amid star says how why"
).split())

# کلیدواژه‌های «داغ/وایرال» برای روشِ پشتیبان و تشخیصِ hot
HOT_KW = [
    "viral", "scandal", "divorce", "split", "breakup", "break up", "dating",
    "wedding", "married", "baby", "pregnant", "dies", "dead", "death",
    "shock", "shocking", "record", "billionaire", "leaked", "feud", "drama",
    "transfer", "fired", "quit", "arrest", "lawsuit", "rumor", "rumour",
    "وایرال", "جدایی", "طلاق", "ازدواج", "شایعه", "رکورد", "شوک", "حاشیه", "دعوا",
]


# ═══════════════════════════ حالت (seen.json) ═══════════════════════════
def load_state():
    """خواندنِ وضعیت با سازگاریِ عقب‌رو (فرمتِ قدیمیِ لیست هم پشتیبانی می‌شود)."""
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return {"seen": data, "recent": []}
        return {"seen": data.get("seen", []), "recent": data.get("recent", [])}
    except Exception:
        return {"seen": [], "recent": []}


def save_state(state):
    state["seen"] = state["seen"][-SEEN_IDS_KEEP:]
    state["recent"] = state["recent"][-RECENT_TITLES_KEEP:]
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


# ═══════════════════════════ ابزار ═══════════════════════════
def domain_of(url):
    m = re.search(r"https?://([^/]+)/?", url)
    return m.group(1) if m else url


def is_persian(text):
    if not text:
        return False
    fa = len(re.findall(r"[\u0600-\u06FF]", text))
    return fa > len(text) * 0.2


def tokenize(text):
    text = re.sub(r"[^\w\s]", " ", (text or "").lower())
    return [t for t in text.split() if t and t not in STOPWORDS and len(t) > 1]


def is_duplicate(title, recent_titles):
    """پیش‌فیلترِ شباهتِ توکنی نسبت به پست‌های اخیر."""
    a = set(tokenize(title))
    if not a:
        return False
    for rt in recent_titles:
        b = set(tokenize(rt))
        if not b:
            continue
        inter = len(a & b)
        union = len(a | b)
        jacc = inter / union if union else 0.0
        small = min(len(a), len(b))
        overlap = inter / small if small else 0.0
        if jacc >= JACCARD_THRESHOLD or overlap >= OVERLAP_THRESHOLD:
            return True
    return False


# ═══════════════════════════ خواندنِ منابع ═══════════════════════════
def get_entry_media(entry):
    """استخراجِ بهترین عکس/ویدیو از خودِ آیتمِ فید."""
    image = None
    videos = []  # (height, bitrate, url)
    for mc in entry.get("media_content", []):
        u = mc.get("url")
        t = (mc.get("type") or "")
        if not u:
            continue
        h = int(mc.get("height") or 0) if str(mc.get("height", "")).isdigit() else 0
        br = int(mc.get("bitrate") or 0) if str(mc.get("bitrate", "")).isdigit() else 0
        if "video" in t or u.lower().endswith((".mp4", ".m4v", ".mov")):
            videos.append((h, br, u))
        elif "image" in t and not image:
            image = u
    for mt in entry.get("media_thumbnail", []):
        if mt.get("url") and not image:
            image = mt["url"]
    for enc in entry.get("enclosures", []):
        u = enc.get("href") or enc.get("url")
        t = enc.get("type", "")
        if not u:
            continue
        if "video" in t:
            videos.append((0, 0, u))
        elif "image" in t and not image:
            image = u
    video = None
    if videos:
        videos.sort(key=lambda x: (x[0], x[1]), reverse=True)  # باکیفیت‌ترین
        video = videos[0][2]
    return image, video


def _meta(page, prop):
    """استخراجِ مقدارِ یک متاتگ og:* با regex (هر دو ترتیبِ property/content)."""
    p = re.escape(prop)
    m = re.search(
        r'<meta[^>]+(?:property|name)=["\']' + p + r'["\'][^>]+content=["\']([^"\']+)["\']',
        page, re.I,
    )
    if not m:
        m = re.search(
            r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+(?:property|name)=["\']' + p + r'["\']',
            page, re.I,
        )
    return html.unescape(m.group(1)) if m else None


def extract_article(url):
    """متنِ کاملِ مقاله + og:image + og:video. خطا را بی‌سروصدا رد می‌کند."""
    try:
        r = requests.get(url, headers=UA, timeout=12)
        r.raise_for_status()
        page = r.text
    except Exception:
        return "", None, None
    paras = re.findall(r"<p[^>]*>(.*?)</p>", page, re.S | re.I)
    parts = []
    for p in paras:
        clean = html.unescape(re.sub(r"<[^>]+>", "", p)).strip()
        if len(clean) > 40:
            parts.append(clean)
    article = " ".join(parts)[:ARTICLE_MAX_CHARS]
    og_image = _meta(page, "og:image")
    og_video = _meta(page, "og:video") or _meta(page, "og:video:url") or _meta(page, "og:video:secure_url")
    return article, og_image, og_video


def gather_candidates(seen):
    """جمع‌آوریِ سوژه‌های تازه از همه‌ی فیدها، مرتب بر اساسِ تازگی."""
    items = []
    for url in RSS_FEEDS:
        try:
            fp = feedparser.parse(url, request_headers=UA)
        except Exception as e:
            print(f"⚠️  فید رد شد: {url} ({e})")
            continue
        if getattr(fp, "bozo", 0) and not fp.entries:
            print(f"⚠️  فیدِ خراب/بی‌جواب رد شد: {url}")
            continue
        source = fp.feed.get("title", domain_of(url))
        for e in fp.entries:
            link = e.get("link")
            if not link:
                continue
            uid = hashlib.md5((e.get("id") or link).encode("utf-8")).hexdigest()
            if uid in seen:
                continue
            title = (e.get("title") or "").strip()
            if not title:
                continue
            ts = 0
            if e.get("published_parsed"):
                ts = time.mktime(e.published_parsed)
            elif e.get("updated_parsed"):
                ts = time.mktime(e.updated_parsed)
            fimg, fvid = get_entry_media(e)
            items.append({
                "id": uid, "source": source, "title": title, "link": link,
                "summary": re.sub(r"<[^>]+>", "", e.get("summary", "")).strip()[:500],
                "ts": ts, "feed_image": fimg, "feed_video": fvid,
            })
    seen_ids, uniq = set(), []
    for it in items:
        if it["id"] in seen_ids:
            continue
        seen_ids.add(it["id"])
        uniq.append(it)
    uniq.sort(key=lambda x: x["ts"], reverse=True)
    return uniq[:NUM_CANDIDATES]


# ═══════════════════════════ سردبیرِ هوش مصنوعی ═══════════════════════════
def ai_editor(candidates, recent):
    """یک فراخوانِ GitHub Models: انتخاب + بازنویسیِ زرد و محاوره‌ای."""
    if not GITHUB_TOKEN:
        return None
    lines = []
    for i, c in enumerate(candidates):
        body = c.get("article") or c.get("summary") or ""
        lines.append(f"[{i}] منبع: {c['source']}\nتیتر: {c['title']}\nمتن: {body[:1000]}\n")
    recent_block = "\n".join(f"- {t}" for t in recent[-15:]) or "(خالی)"
    user = (
        "پست‌های اخیراً منتشرشده (برای جلوگیری از تکرار):\n"
        f"{recent_block}\n\n"
        "سوژه‌های تازه (کاندیدها):\n"
        f"{chr(10).join(lines)}\n"
        "فقط یه JSON برگردان."
    )
    try:
        r = requests.post(
            AI_ENDPOINT,
            headers={
                "Authorization": f"Bearer {GITHUB_TOKEN}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            json={
                "model": AI_MODEL,
                "temperature": 0.8,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user},
                ],
            },
            timeout=60,
        )
        r.raise_for_status()
        content = r.json()["choices"][0]["message"]["content"].strip()
        content = re.sub(r"^```(?:json)?|```$", "", content, flags=re.M).strip()
        m = re.search(r"\{.*\}", content, re.S)
        if m:
            content = m.group(0)
        data = json.loads(content)
        return {
            "index": int(data.get("index", -1)),
            "title_fa": (data.get("title_fa") or "").strip(),
            "summary_fa": (data.get("summary_fa") or "").strip(),
            "hot": bool(data.get("hot", False)),
        }
    except Exception as e:
        print(f"⚠️  خطای سردبیرِ AI: {e}")
        return None


# ═══════════════════════════ روشِ پشتیبان ═══════════════════════════
def fa_translate(text):
    if not text:
        return ""
    if is_persian(text):
        return text
    try:
        from deep_translator import GoogleTranslator
        return GoogleTranslator(source="auto", target="fa").translate(text[:1500])
    except Exception as e:
        print(f"⚠️  ترجمه ناموفق: {e}")
        return text


def fallback_choice(candidates, recent):
    """امتیازدهیِ کلیدواژه‌ای + ترجمه — تضمین می‌کند ربات هیچ‌وقت خاموش نشود."""
    best, best_score = None, -1.0
    for i, c in enumerate(candidates):
        if is_duplicate(c["title"], recent):
            continue
        text = (c["title"] + " " + c.get("article", "")).lower()
        score = 0.0
        for kw in HOT_KW:
            if kw in text:
                score += 2
        score += max(0, len(candidates) - i) * 0.1  # امتیازِ تازگی
        if score > best_score:
            best_score, best = score, (i, c)
    if not best:
        return None
    i, c = best
    body = c.get("article") or c.get("summary") or c["title"]
    hot = any(kw in (c["title"] + " " + c.get("article", "")).lower() for kw in HOT_KW)
    src = c["source"].split(" - ")[0].split(" | ")[0]
    return {
        "index": i,
        "title_fa": fa_translate(c["title"]),
        "summary_fa": f"{src}: " + fa_translate(body[:600]),
        "hot": hot,
    }


# ═══════════════════════════ ساختِ پست ═══════════════════════════
def build_post(choice):
    title = html.escape(choice["title_fa"])
    summary = html.escape(choice["summary_fa"])
    lead = "🔥" if choice["hot"] else "✨"
    return (
        f"{lead} <b>{title}</b>\n\n"
        f"<blockquote expandable>{summary}</blockquote>\n\n"
        f"{SIGNATURE}"
    )


# ═══════════════════════════ ارسال به تلگرام ═══════════════════════════
def tg_url(method):
    return f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/{method}"


def tg_send_message(text):
    try:
        r = requests.post(tg_url("sendMessage"), data={
            "chat_id": CHANNEL, "text": text,
            "parse_mode": "HTML", "disable_web_page_preview": "true",
        }, timeout=30)
        ok = r.json().get("ok", False)
        if not ok:
            print("⚠️  sendMessage:", r.text[:300])
        return ok
    except Exception as e:
        print("⚠️  sendMessage err:", e)
        return False


def tg_send_photo(photo_url, caption):
    try:
        if len(caption) > 1024:
            requests.post(tg_url("sendPhoto"),
                          data={"chat_id": CHANNEL, "photo": photo_url}, timeout=30)
            return tg_send_message(caption)
        r = requests.post(tg_url("sendPhoto"), data={
            "chat_id": CHANNEL, "photo": photo_url,
            "caption": caption, "parse_mode": "HTML",
        }, timeout=30)
        ok = r.json().get("ok", False)
        if not ok:
            print("⚠️  sendPhoto:", r.text[:300])
        return ok
    except Exception as e:
        print("⚠️  sendPhoto err:", e)
        return False


def download_capped(url, cap):
    try:
        with requests.get(url, headers=UA, stream=True, timeout=40) as r:
            r.raise_for_status()
            cl = r.headers.get("Content-Length")
            if cl and int(cl) > cap:
                return None
            buf = b""
            for chunk in r.iter_content(65536):
                buf += chunk
                if len(buf) > cap:
                    return None
            return buf
    except Exception:
        return None


def tg_send_video(data, caption):
    d = {"chat_id": CHANNEL, "parse_mode": "HTML"}
    if len(caption) <= 1024:
        d["caption"] = caption
    try:
        r = requests.post(tg_url("sendVideo"), data=d,
                          files={"video": ("video.mp4", data)}, timeout=180)
        ok = r.json().get("ok", False)
        if not ok:
            print("⚠️  sendVideo:", r.text[:300])
            return False
        if len(caption) > 1024:
            tg_send_message(caption)
        return True
    except Exception as e:
        print("⚠️  sendVideo err:", e)
        return False


def publish(post, chosen):
    """اولویتِ رسانه: ویدیو > عکسِ باکیفیت > فقط‌متن.
    برای کیفیتِ بهتر، اول عکسِ full-resِ صفحه (og:image) رو امتحان می‌کنه،
    بعد عکسِ فید."""
    video_url = chosen.get("feed_video") or chosen.get("og_video")
    image_url = chosen.get("og_image") or chosen.get("feed_image")
    if video_url:
        data = download_capped(video_url, MAX_VIDEO_BYTES)
        if data and tg_send_video(data, post):
            return True
        print("ℹ️  دانلود/آپلودِ ویدیو نشد — با لینک می‌فرستم")
        return tg_send_message(post + f"\n\n🎬 {video_url}")
    if image_url and tg_send_photo(image_url, post):
        return True
    return tg_send_message(post)


# ═══════════════════════════ main ═══════════════════════════
def main():
    if not TELEGRAM_BOT_TOKEN:
        print("❌ TELEGRAM_BOT_TOKEN تنظیم نشده. خروج.")
        return

    state = load_state()
    seen = set(state["seen"])
    recent = list(state["recent"])

    print("📡 در حالِ خواندنِ منابع...")
    candidates = gather_candidates(seen)
    print(f"✅ {len(candidates)} سوژه‌ی تازه پیدا شد")
    if not candidates:
        print("ℹ️ سوژه‌ی تازه‌ای نبود. خروج.")
        return

    print("📰 در حالِ خواندنِ متنِ کاملِ مقاله‌ها...")
    for c in candidates:
        art, og_img, og_vid = extract_article(c["link"])
        c["article"] = art
        c["og_image"] = og_img
        c["og_video"] = og_vid

    print("🤖 سردبیرِ هوش مصنوعی در حالِ تصمیم‌گیری...")
    choice = ai_editor(candidates, recent)
    if choice is None:
        print("↩️  سردبیرِ AI در دسترس نبود — رفتم سراغِ روشِ پشتیبان")
        choice = fallback_choice(candidates, recent)

    if choice is None or choice["index"] == -1:
        print("⏭️  چیزی برای انتشار انتخاب نشد.")
        save_state({"seen": list(seen), "recent": recent})
        return

    idx = choice["index"]
    if idx < 0 or idx >= len(candidates):
        print(f"⚠️  ایندکسِ نامعتبر ({idx}). خروج.")
        return
    chosen = candidates[idx]

    if is_duplicate(choice["title_fa"], recent):
        print("🔁 سوژه‌ی انتخابی تکراری بود — رد شد.")
        seen.add(chosen["id"])
        save_state({"seen": list(seen), "recent": recent})
        return

    tag = "🔥 داغ" if choice["hot"] else "✨ عادی"
    print(f"🖊️  انتخاب شد [{tag}]: {choice['title_fa']}")

    post = build_post(choice)
    if publish(post, chosen):
        print("✅ با موفقیت منتشر شد")
        recent.append(choice["title_fa"])
    else:
        print("❌ انتشار ناموفق بود")

    seen.add(chosen["id"])
    save_state({"seen": list(seen), "recent": recent})
    print("💾 وضعیت ذخیره شد")


if __name__ == "__main__":
    main()
