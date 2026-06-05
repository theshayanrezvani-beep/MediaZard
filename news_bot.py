#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ربات سرگرمی و محتوای زرد تلگرام (نسخه ۱۸+ بهینه‌شده)
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

# منابع قوی با تمرکز روی محتوای بصری
RSS_FEEDS = [
    "https://www.tmz.com/rss.xml",
    "https://pagesix.com/feed/",
    "https://www.dailymail.co.uk/tvshowbiz/index.rss",
    "https://www.justjared.com/feed/",
    "https://hollywoodlife.com/feed/",
    "https://bossip.com/feed/",
    "https://www.eonline.com/news/rss",
    "https://www.etonline.com/news/rss",
    "https://toofab.com/feed/",
    "https://www.perezhilton.com/feed/",
]

NUM_CANDIDATES     = 12
RECENT_TITLES_KEEP = 40
SEEN_IDS_KEEP      = 1000
ARTICLE_MAX_CHARS  = 1800
MAX_VIDEO_BYTES    = 50 * 1024 * 1024
JACCARD_THRESHOLD  = 0.5
OVERLAP_THRESHOLD  = 0.6

STATE_FILE = "seen.json"
UA = {"User-Agent": "Mozilla/5.0 (compatible; fun-bot/1.0; +https://github.com)"}

# ═══════════════════════════ پرامپت سردبیر ═══════════════════════════
SYSTEM_PROMPT = """تو سردبیر یه کانال زرد ۱۸+ پرمخاطب تلگرامی هستی. باید آب‌دارترین و بصری‌ترین سوژه رو انتخاب کنی و خیلی داغ و محاوره‌ای بنویسی.

اولویت انتخاب:
۱) محتوای بصری قوی (عکس/ویدیو سکسی، استایل، بدن، رابطه، جدایی، وایرال)
۲) حاشیه‌های سلبریتی و مدل‌ها
۳) هر چیزی که مخاطب ۱۸+ حال کنه

سبک نگارش (دقیقاً مثل Efsha):
- فارسی محاوره‌ای داغ و کلیک‌بیت: «ترکوند»، «آتیش»، «چالشتو»، «جهانبخت»، «سکسی داغه»، «اینو ببین»، «حالت می‌ده»
- با اسم منبع شروع کن (پیج‌سیکس:، دیلی‌میل:، TMZ:)
- روی جنبه بصری و جذابیت تأکید کن
- ایموجی زیاد: 🔥💦😈🍑💋😱✨❤️
- طول ۲ تا ۵ جمله پر انرژی
- شایعه رو شایعه بنویس

hot=true فقط برای سوژه‌های واقعاً آتشین.

خروجی فقط JSON:
{"index": <شماره یا -1>, "title_fa": "...", "summary_fa": "...", "hot": true/false}"""

# STOPWORDS و HOT_KW
STOPWORDS = set((
    "و در به از که این آن را با برای تا یک رو تو هم می اون یه قراره دیگه اینا اونا "
    "خیلیا های ها بر روی یا کرد شد گفت می‌گه می‌کنه است بود شده یک دو سه "
    "the a an of to in on for and or is are was were be by at with from as that this "
    "it its has have had will would new says said after over amid star says how why"
).split())

HOT_KW = [
    "viral", "scandal", "divorce", "split", "breakup", "dating", "wedding", "pregnant",
    "shock", "leaked", "feud", "drama", "وایرال", "جدایی", "طلاق", "حاشیه", "سکسی"
]

# ═══════════════════════════ توابع پایه ═══════════════════════════
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

def is_persian(text):
    if not text:
        return False
    fa = len(re.findall(r"[\u0600-\u06FF]", text))
    return fa > len(text) * 0.2

def tokenize(text):
    text = re.sub(r"[^\w\s]", " ", (text or "").lower())
    return [t for t in text.split() if t and t not in STOPWORDS and len(t) > 1]

def is_duplicate(title, recent_titles):
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

# ═══════════════════════════ خواندن رسانه و مقاله ═══════════════════════════
def get_entry_media(entry):
    image = None
    videos = []
    for mc in entry.get("media_content", []):
        u = mc.get("url")
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
    if chosen.get("feed_image"): images.append(chosen["feed_image"])
    if chosen.get("feed_video"): videos.append(chosen["feed_video"])
    if chosen.get("og_image"): images.append(chosen["og_image"])
    if chosen.get("og_video"): videos.append(chosen["og_video"])
    
    images = list(dict.fromkeys([u for u in images if u]))
    videos = list(dict.fromkeys([u for u in videos if u]))
    return images[:5], videos[:2]

def _meta(page, prop):
    p = re.escape(prop)
    m = re.search(r'<meta[^>]+(?:property|name)=["\']' + p + r'["\'][^>]+content=["\']([^"\']+)["\']', page, re.I)
    if not m:
        m = re.search(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+(?:property|name)=["\']' + p + r'["\']', page, re.I)
    return html.unescape(m.group(1)) if m else None

def extract_article(url):
    try:
        r = requests.get(url, headers=UA, timeout=12)
        r.raise_for_status()
        page = r.text
    except Exception:
        return "", None, None
    paras = re.findall(r"<p[^>]*>(.*?)</p>", page, re.S | re.I)
    parts = [html.unescape(re.sub(r"<[^>]+>", "", p)).strip() for p in paras if len(html.unescape(re.sub(r"<[^>]+>", "", p)).strip()) > 40]
    article = " ".join(parts)[:ARTICLE_MAX_CHARS]
    og_image = _meta(page, "og:image")
    og_video = _meta(page, "og:video") or _meta(page, "og:video:url")
    return article, og_image, og_video

def gather_candidates(seen):
    items = []
    for url in RSS_FEEDS:
        try:
            fp = feedparser.parse(url, request_headers=UA)
        except Exception:
            continue
        source = fp.feed.get("title", domain_of(url))
        for e in fp.entries:
            link = e.get("link")
            if not link: continue
            uid = hashlib.md5((e.get("id") or link).encode()).hexdigest()
            if uid in seen: continue
            title = (e.get("title") or "").strip()
            if not title: continue
            ts = 0
            if e.get("published_parsed"):
                ts = time.mktime(e.published_parsed)
            fimg, fvid = get_entry_media(e)
            items.append({
                "id": uid, "source": source, "title": title, "link": link,
                "summary": re.sub(r"<[^>]+>", "", e.get("summary", "")).strip()[:500],
                "ts": ts, "feed_image": fimg, "feed_video": fvid,
            })
    items = list({it["id"]: it for it in items}.values())
    items.sort(key=lambda x: x["ts"], reverse=True)
    return items[:NUM_CANDIDATES]

# ═══════════════════════════ توابع ارسال به تلگرام ═══════════════════════════
def tg_url(method):
    return f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/{method}"

def tg_send_message(text):
    try:
        r = requests.post(tg_url("sendMessage"), data={
            "chat_id": CHANNEL, "text": text,
            "parse_mode": "HTML", "disable_web_page_preview": "true"
        }, timeout=30)
        ok = r.json().get("ok", False)
        if not ok:
            print("⚠️ sendMessage:", r.text[:300])
        return ok
    except Exception as e:
        print("⚠️ sendMessage err:", e)
        return False

def tg_send_photo(photo_url, caption):
    try:
        caption = caption or ""
        if len(caption) > 1024:
            requests.post(tg_url("sendPhoto"), data={"chat_id": CHANNEL, "photo": photo_url}, timeout=30)
            return tg_send_message(caption)
        r = requests.post(tg_url("sendPhoto"), data={
            "chat_id": CHANNEL, "photo": photo_url,
            "caption": caption, "parse_mode": "HTML"
        }, timeout=30)
        ok = r.json().get("ok", False)
        if not ok:
            print("⚠️ sendPhoto:", r.text[:300])
        return ok
    except Exception:
        return False

def download_capped(url, cap):
    try:
        with requests.get(url, headers=UA, stream=True, timeout=40) as r:
            r.raise_for_status()
            if int(r.headers.get("Content-Length", 0)) > cap:
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
    """ارسال همه رسانه‌ها (چند عکس + ویدیو)"""
    images, videos = get_all_media(chosen)
    success = False
    original_post = post

    for vid_url in videos:
        data = download_capped(vid_url, MAX_VIDEO_BYTES)
        if data and tg_send_video(data, post):
            success = True
            post = ""

    for img_url in images:
        if tg_send_photo(img_url, post if not success else ""):
            success = True
            post = ""

    if not success:
        return tg_send_message(original_post)
    return True

# ═══════════════════════════ سردبیر هوش مصنوعی ═══════════════════════════
def ai_editor(candidates, recent):
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
            headers={"Authorization": f"Bearer {GITHUB_TOKEN}", "Content-Type": "application/json"},
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
        print(f"⚠️ خطای AI: {e}")
        return None

# ═══════════════════════════ روش پشتیبان ═══════════════════════════
def fa_translate(text):
    if not text:
        return ""
    if is_persian(text):
        return text
    try:
        from deep_translator import GoogleTranslator
        return GoogleTranslator(source="auto", target="fa").translate(text[:1500])
    except Exception:
        return text

def fallback_choice(candidates, recent):
    best, best_score = None, -1.0
    for i, c in enumerate(candidates):
        if is_duplicate(c["title"], recent):
            continue
        text = (c["title"] + " " + c.get("article", "")).lower()
        score = sum(2 for kw in HOT_KW if kw in text)
        score += max(0, len(candidates) - i) * 0.1
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

# ═══════════════════════════ ساخت پست و main ═══════════════════════════
def build_post(choice):
    title = html.escape(choice["title_fa"])
    summary = html.escape(choice["summary_fa"])
    lead = "🔥" if choice.get("hot", False) else "✨"
    return f"{lead} <b>{title}</b>\n\n<blockquote expandable>{summary}</blockquote>\n\n{SIGNATURE}"

def main():
    if not TELEGRAM_BOT_TOKEN:
        print("❌ TELEGRAM_BOT_TOKEN تنظیم نشده.")
        return

    state = load_state()
    seen = set(state["seen"])
    recent = list(state["recent"])

    print("📡 در حال خواندن منابع...")
    candidates = gather_candidates(seen)
    print(f"✅ {len(candidates)} سوژه پیدا شد")
    if not candidates:
        print("ℹ️ سوژه تازه‌ای نبود.")
        return

    print("📰 خواندن متن مقاله‌ها...")
    for c in candidates:
        art, og_img, og_vid = extract_article(c["link"])
        c["article"] = art
        c["og_image"] = og_img
        c["og_video"] = og_vid

    print("🤖 تصمیم‌گیری سردبیر...")
    choice = ai_editor(candidates, recent)
    if choice is None:
        print("↩️ AI در دسترس نبود — fallback")
        choice = fallback_choice(candidates, recent)

    if not choice or choice.get("index") == -1:
        print("⏭️ چیزی برای انتشار نبود.")
        save_state({"seen": list(seen), "recent": recent})
        return

    idx = choice["index"]
    if idx < 0 or idx >= len(candidates):
        print("⚠️ ایندکس نامعتبر.")
        return
    chosen = candidates[idx]

    if is_duplicate(choice["title_fa"], recent):
        print("🔁 تکراری بود.")
        seen.add(chosen["id"])
        save_state({"seen": list(seen), "recent": recent})
        return

    post = build_post(choice)
    if publish(post, chosen):
        print("✅ منتشر شد")
        recent.append(choice["title_fa"])
    else:
        print("❌ خطا در انتشار")

    seen.add(chosen["id"])
    save_state({"seen": list(seen), "recent": recent})
    print("💾 ذخیره شد")

if __name__ == "__main__":
    main()