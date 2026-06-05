#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ربات سرگرمی و محتوای زرد تلگرام (نسخه ۱۸+ نهایی)
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
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
GITHUB_TOKEN       = os.environ.get("GITHUB_TOKEN", "")

CHANNEL   = "@MediaZard"
SIGNATURE = "@MediaZard | مدیا زرد"

AI_MODEL    = "openai/gpt-4o-mini"
AI_ENDPOINT = "https://models.github.ai/inference/chat/completions"

# منابع با تمرکز ۱۸+
RSS_FEEDS = [
    "https://www.tmz.com/rss.xml", "https://pagesix.com/feed/", "https://www.dailymail.co.uk/tvshowbiz/index.rss",
    "https://www.justjared.com/feed/", "https://hollywoodlife.com/feed/", "https://toofab.com/feed/",
    "https://www.the-sun.com/feed/", "https://radaronline.com/feed/", "https://www.maxim.com/feed",
    "https://www.playboy.com/rss", "https://www.cosmopolitan.com/rss/",
    "https://www.pornhub.com/rss", "https://www.xvideos.com/rss", "https://www.xnxx.com/rss",
]

NUM_CANDIDATES     = 20
RECENT_TITLES_KEEP = 40
SEEN_IDS_KEEP      = 1000
ARTICLE_MAX_CHARS  = 1800
MAX_VIDEO_BYTES    = 50 * 1024 * 1024   # ۵۰ مگابایت
MAX_IMAGE_BYTES    = 20 * 1024 * 1024   # ۲۰ مگابایت برای عکس

STATE_FILE = "seen.json"
UA = {"User-Agent": "Mozilla/5.0 (compatible; fun-bot/1.0; +https://github.com)"}

# پرامپت (صمیمی)
SYSTEM_PROMPT = """تو سردبیر یه کانال زرد ۱۸+ تلگرامی هستی. مخاطب‌ها عاشق محتوای بصری جذاب هستن.

اولویت: سوژه‌های بصری قوی ۱۸+ (مدل، استایل، عکس/ویدیو داغ، پورن، سلبریتی)
سبک: خیلی صمیمی و خودمونی مثل رفیق («داداش ببین»، «این ترکوند»، «خفنه»)
با منبع شروع کن و بگو چی تو عکس/ویدیو هست.
تقریبا همیشه یه سوژه انتخاب کن.

خروجی فقط JSON:
{"index": <شماره یا -1>, "title_fa": "...", "summary_fa": "...", "hot": true/false}"""

# STOPWORDS و HOT_KW
STOPWORDS = set(("و در به از که این آن را با برای تا یک رو تو هم می اون یه قراره دیگه اینا اونا خیلیا های ها بر روی یا کرد شد گفت می‌گه می‌کنه است بود شده the a an of to in on for and or is are was were be by at with from as that this it its has have had will would new says said after over amid star").split())

HOT_KW = ["viral", "scandal", "divorce", "breakup", "dating", "pregnant", "leaked", "drama", "وایرال", "جدایی", "حاشیه", "سکسی", "استایل", "پورن"]

# ═══════════════════════════ توابع پایه و جمع‌آوری ═══════════════════════════
def load_state():
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

def domain_of(url):
    m = re.search(r"https?://([^/]+)/?", url)
    return m.group(1) if m else url

def tokenize(text):
    text = re.sub(r"[^\w\s]", " ", (text or "").lower())
    return [t for t in text.split() if t and t not in STOPWORDS and len(t) > 1]

def is_duplicate(title, recent_titles):
    a = set(tokenize(title))
    if not a: return False
    for rt in recent_titles:
        b = set(tokenize(rt))
        if not b: continue
        inter = len(a & b)
        union = len(a | b)
        if union == 0: continue
        if inter / union >= 0.65 or inter / min(len(a), len(b)) >= 0.7:
            return True
    return False

def get_entry_media(entry):
    image = None
    videos = []
    for mc in entry.get("media_content", []):
        u = mc.get("url")
        if not u: continue
        t = mc.get("type") or ""
        if "video" in t or u.lower().endswith((".mp4", ".mov")):
            videos.append(u)
        elif "image" in t and not image:
            image = u
    for mt in entry.get("media_thumbnail", []):
        if mt.get("url") and not image:
            image = mt["url"]
    return image, videos[0] if videos else None

def get_all_media(chosen):
    images = []
    videos = []
    for key in ["feed_image", "og_image"]:
        if chosen.get(key): images.append(chosen[key])
    for key in ["feed_video", "og_video"]:
        if chosen.get(key): videos.append(chosen[key])
    
    images = list(dict.fromkeys([u for u in images if u and u.startswith("http")]))
    videos = list(dict.fromkeys([u for u in videos if u and u.startswith("http")]))
    return images[:6], videos[:2]

# ═══════════════════════════ دانلود و ارسال ═══════════════════════════
def download_file(url, max_size):
    try:
        with requests.get(url, headers=UA, stream=True, timeout=40) as r:
            r.raise_for_status()
            if int(r.headers.get("Content-Length", 0)) > max_size:
                return None
            buf = b""
            for chunk in r.iter_content(65536):
                buf += chunk
                if len(buf) > max_size:
                    return None
            return buf
    except Exception:
        return None

def tg_url(method):
    return f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/{method}"

def tg_send_message(text):
    try:
        r = requests.post(tg_url("sendMessage"), data={
            "chat_id": CHANNEL, "text": text, "parse_mode": "HTML", "disable_web_page_preview": "true"
        }, timeout=30)
        return r.json().get("ok", False)
    except Exception:
        return False

def tg_send_photo_data(data, caption):
    try:
        files = {"photo": ("photo.jpg", data)}
        data_dict = {"chat_id": CHANNEL, "parse_mode": "HTML"}
        if len(caption or "") <= 1024:
            data_dict["caption"] = caption
        r = requests.post(tg_url("sendPhoto"), data=data_dict, files=files, timeout=60)
        return r.json().get("ok", False)
    except Exception:
        return False

def tg_send_video(data, caption):
    try:
        d = {"chat_id": CHANNEL, "parse_mode": "HTML"}
        if len(caption or "") <= 1024:
            d["caption"] = caption
        r = requests.post(tg_url("sendVideo"), data=d, files={"video": ("video.mp4", data)}, timeout=180)
        ok = r.json().get("ok", False)
        if ok and len(caption or "") > 1024:
            tg_send_message(caption)
        return ok
    except Exception:
        return False

def publish(post, chosen):
    images, videos = get_all_media(chosen)
    success = False
    original_post = post

    print(f"📸 رسانه پیدا شد: {len(images)} عکس | {len(videos)} ویدیو")

    # ارسال ویدیوها
    for vid_url in videos:
        print(f"🎥 دانلود ویدیو: {vid_url[:80]}...")
        data = download_file(vid_url, MAX_VIDEO_BYTES)
        if data and tg_send_video(data, post):
            success = True
            post = ""
            print("✅ ویدیو ارسال شد")

    # ارسال عکس‌ها (دانلود شده)
    for img_url in images:
        print(f"🖼 دانلود عکس: {img_url[:80]}...")
        data = download_file(img_url, MAX_IMAGE_BYTES)
        if data and tg_send_photo_data(data, post if not success else ""):
            success = True
            post = ""
            print("✅ عکس ارسال شد")

    if not success:
        print("📝 فقط متن ارسال شد")
        return tg_send_message(original_post)
    return True

# (بقیه توابع ai_editor, fallback_choice, build_post, main و ... مثل نسخه قبلی)

def build_post(choice):
    title = html.escape(choice["title_fa"])
    summary = html.escape(choice["summary_fa"])
    lead = "🔥" if choice.get("hot", False) else "✨"
    return f"{lead} <b>{title}</b>\n\n<blockquote expandable>{summary}</blockquote>\n\n{SIGNATURE}"

# ... (ai_editor, fallback_choice, fa_translate, main رو از فایل قبلی‌ات کپی کن)

if __name__ == "__main__":
    main()