#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Valctk-Haber • Auto Repost Bot
- X API v2 (tweet), v1.1 (media upload)
- Link YOK (kart yok)
- RSS kaynağı + (opsiyonel) belirli X hesaplarından içerik çekme
- Başlık/Tweet metnini parlatır, özet ekler, noktalama tamamlar
"""

import os, sys, json, argparse, tempfile, time
from typing import List, Dict, Optional
import requests
from bs4 import BeautifulSoup
from rapidfuzz import fuzz, process
from unidecode import unidecode

# ====== AYARLAR ======
RSS_SOURCES = [
    "https://www.trthaber.com/manset_articles.rss",
    "https://www.aa.com.tr/tr/rss/default?cat=guncel",
    "https://www.hurriyet.com.tr/rss/anasayfa",
]

STATE_DIR = ".state"
STATE_FILE = os.path.join(STATE_DIR, "posted.json")
SIMILARITY_THRESHOLD = 90
MAX_TWEET_LEN = 280

# Paylaşım davranışı
ATTACH_OG_IMAGE   = os.getenv("ATTACH_OG_IMAGE", "true").lower() in ("1","true","yes")
OG_IMAGE_TIMEOUT  = 12
HTTP_TIMEOUT      = 15

# X kaynaklarından çekme (opsiyonel)
ENABLE_X_SOURCES  = os.getenv("ENABLE_X_SOURCES", "false").lower() in ("1","true","yes")
X_HANDLES = [h.strip().lstrip("@") for h in (os.getenv("X_HANDLES","").split(",")) if h.strip()]

END_OK = (".", "?", "!", "…", ".”", "!”", "?”", ")", "»", "”")

# ====== State ======
def ensure_state():
    os.makedirs(STATE_DIR, exist_ok=True)
    if not os.path.exists(STATE_FILE):
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump({"links": [], "titles": [], "tweet_ids": [], "user_ids": {}}, f, ensure_ascii=False)

def load_state() -> Dict:
    ensure_state()
    with open(STATE_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_state(state: Dict):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

def sha1(s: str) -> str:
    import hashlib
    return hashlib.sha1(s.encode("utf-8")).hexdigest()

def normalize_text(s: str) -> str:
    return unidecode(" ".join((s or "").split()))

# ====== Metin parlatma ======
def ensure_sentence_end(t: str) -> str:
    t = (t or "").strip()
    if not any(t.endswith(p) for p in END_OK):
        t += "."
    return t

def polish_sentence(t: str) -> str:
    t = " ".join((t or "").strip().split())
    if t and not t.isupper():
        try: t = t[0].upper() + t[1:]
        except Exception: pass
    t = ensure_sentence_end(t)
    return t

def clean_html_to_text(html_or_text: str) -> str:
    try:
        soup = BeautifulSoup(html_or_text, "lxml")
        text = soup.get_text(" ", strip=True)
        return " ".join(text.split())
    except Exception:
        return " ".join(str(html_or_text).split())

def compose_with_summary(title_or_text: str, summary: Optional[str]) -> str:
    base = polish_sentence(title_or_text)
    if not summary:
        return base[:MAX_TWEET_LEN] if len(base) > MAX_TWEET_LEN else base
    s = polish_sentence(clean_html_to_text(summary))
    room = MAX_TWEET_LEN - (len(base) + 1)
    if room <= 0:
        return base[:MAX_TWEET_LEN]
    if len(s) > room:
        s = s[:max(0, room - 1)].rstrip()
        if not s.endswith("…"): s += "…"
    return f"{base} {s}"

# ====== RSS ======
def fetch_rss(url: str):
    items = []
    try:
        r = requests.get(url, timeout=HTTP_TIMEOUT, headers={"User-Agent": "ValctkBot/1.0"})
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "xml")
        for it in soup.find_all("item"):
            title = (it.title.text if it.title else "").strip()
            link = (it.link.text if it.link else "").strip()
            desc = ""
            if it.find("description"): desc = it.find("description").text or ""
            if title and link:
                items.append({"title": title, "link": link, "desc": desc})
    except Exception as e:
        print(f"[WARN] RSS çekilemedi: {url} -> {e}")
    return items

def collect_rss_candidates() -> List[Dict]:
    all_items = []
    for src in RSS_SOURCES: all_items.extend(fetch_rss(src))
    seen, uniq = set(), []
    for it in all_items:
        if it["link"] in seen: continue
        seen.add(it["link"]); uniq.append(it)
    return uniq

def is_duplicate_title(title: str, state: Dict) -> bool:
    cand = normalize_text(title)
    hist = state.get("titles", [])
    if hist:
        best = process.extractOne(cand, hist, scorer=fuzz.token_set_ratio)
        if best and best[1] >= SIMILARITY_THRESHOLD:
            return True
    return False

# ====== Sayfa yardımcıları ======
def extract_page_summary(html: str) -> Optional[str]:
    soup = BeautifulSoup(html, "lxml")
    for key in (
        {"name": "description"},
        {"property": "description"},
        {"property": "og:description"},
        {"name": "og:description"},
        {"name": "twitter:description"},
        {"property": "twitter:description"},
    ):
        tag = soup.find("meta", attrs=key)
        if tag and tag.get("content"): return tag["content"].strip()
    p = soup.find("p")
    if p: return p.get_text(" ", strip=True)
    return None

def find_og_image_url(html: str) -> Optional[str]:
    soup = BeautifulSoup(html, "lxml")
    for prop in ("og:image", "og:image:url", "twitter:image"):
        el = soup.find("meta", attrs={"property": prop}) or soup.find("meta", attrs={"name": prop})
        if el and el.get("content"): return el["content"].strip()
    img = soup.find("img")
    return img.get("src").strip() if img and img.get("src") else None

def absolutize(base: str, maybe: str) -> str:
    if maybe.startswith("//"): return "https:" + maybe
    if maybe.startswith("/"):
        from urllib.parse import urljoin
        return urljoin(base, maybe)
    return maybe

def get_article_summary_and_image(article_url: str):
    try:
        r = requests.get(article_url, timeout=OG_IMAGE_TIMEOUT, headers={"User-Agent": "ValctkBot/1.0"})
        r.raise_for_status()
        html = r.text
        summary = extract_page_summary(html)
        og = find_og_image_url(html)
        img_url = absolutize(article_url, og) if og else None
        return summary, img_url
    except Exception as e:
        print("[WARN] Makale meta alınamadı:", e)
        return None, None

def download_image(url: str) -> Optional[str]:
    try:
        r = requests.get(url, timeout=OG_IMAGE_TIMEOUT, headers={"User-Agent": "ValctkBot/1.0"})
        r.raise_for_status()
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".jpg")
        tmp.write(r.content); tmp.close()
        return tmp.name
    except Exception as e:
        print("[WARN] Görsel indirilemedi:", e)
        return None

# ====== X API ======
def get_client_v2():
    import tweepy
    return tweepy.Client(
        consumer_key=os.getenv("TW_API_KEY"),
        consumer_secret=os.getenv("TW_API_SECRET"),
        access_token=os.getenv("TW_ACCESS_TOKEN"),
        access_token_secret=os.getenv("TW_ACCESS_SECRET"),
        wait_on_rate_limit=True,
    )

def get_api_v1():
    import tweepy
    auth = tweepy.OAuth1UserHandler(
        os.getenv("TW_API_KEY"),
        os.getenv("TW_API_SECRET"),
        os.getenv("TW_ACCESS_TOKEN"),
        os.getenv("TW_ACCESS_SECRET"),
    )
    return tweepy.API(auth, wait_on_rate_limit=True)

def upload_media(image_path: str) -> Optional[str]:
    try:
        api = get_api_v1()
        media = api.media_upload(filename=image_path)
        return media.media_id_string
    except Exception as e:
        print("[WARN] Medya yüklenemedi:", e)
        return None

# ----- X kaynakları (timeline çekme) -----
def get_user_id(client, username: str, cache: Dict) -> Optional[str]:
    if "user_ids" not in cache: cache["user_ids"] = {}
    if username in cache["user_ids"]: return cache["user_ids"][username]
    u = client.get_user(username=username)
    uid = str(u.data.id) if u and u.data else None
    if uid: cache["user_ids"][username] = uid
    return uid

def fetch_latest_tweet_texts(client, usernames: List[str], state: Dict) -> List[Dict]:
    out = []
    for uname in usernames:
        uid = get_user_id(client, uname, state)
        if not uid: continue
        tw = client.get_users_tweets(
            id=uid, max_results=5,
            exclude=["replies", "retweets"],
            tweet_fields=["created_at", "lang", "entities"]
        )
        if not tw or not tw.data: continue
        for t in tw.data:
            tid = str(t.id)
            if tid in state.get("tweet_ids", []): continue
            text = (t.text or "").strip()
            if not text: continue
            out.append({"source":"x", "username": uname, "tweet_id": tid, "title": text, "link": f"https://x.com/{uname}/status/{tid}"})
            break
    return out

# ====== Tweet gönderme ======
def post_tweet(text: str, image_url: Optional[str], dry: bool):
    if dry:
        print(f"[DRY] Tweet (link yok):\n{text}\nimage={bool(image_url)}")
        return

    media_ids = None
    if image_url and ATTACH_OG_IMAGE:
        path = download_image(image_url)
        if path:
            mid = upload_media(path)
            if mid: media_ids = [mid]
            try: os.unlink(path)
            except Exception: pass

    client = get_client_v2()
    if media_ids:
        resp = client.create_tweet(text=text, media_ids=media_ids)
    else:
        resp = client.create_tweet(text=text)
    tid = getattr(resp, "data", {}).get("id")
    print(f"[OK] Tweet gönderildi. ID: {tid}")

# ====== Akış ======
def choose_candidate(state: Dict) -> Optional[Dict]:
    # Önce RSS
    rss = collect_rss_candidates()
    for it in rss:
        if sha1(it["link"]) in state.get("links", []): continue
        if is_duplicate_title(it["title"], state): continue
        return {"source":"rss", **it}

    # Sonra X kaynakları (opsiyonel)
    if ENABLE_X_SOURCES and X_HANDLES:
        client = get_client_v2()
        arr = fetch_latest_tweet_texts(client, X_HANDLES, state)
        for it in arr:
            if is_duplicate_title(it["title"], state): continue
            return it
    return None

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry", action="store_true")
    args = parser.parse_args()

    dry = args.dry or (os.getenv("DRY_MODE", "").lower() in ("1","true","yes"))
    state = load_state()

    cand = choose_candidate(state)
    if not cand:
        print("⚠️ Paylaşılacak yeni içerik bulunamadı.")
        return

    if cand["source"] == "rss":
        # RSS: başlık + kısa özet + (og:image)
        rss_summary = clean_html_to_text(cand.get("desc") or "")
        page_summary, img_url = (None, None)
        if not rss_summary or ATTACH_OG_IMAGE:
            s, iu = get_article_summary_and_image(cand["link"])
            page_summary = s if not rss_summary else rss_summary
            img_url = iu
        text = compose_with_summary(cand["title"], rss_summary or page_summary)
        post_tweet(text=text, image_url=img_url, dry=dry)

        # state güncelle
        state["links"] = list({*state.get("links", []), sha1(cand["link"])})
        titles = state.get("titles", []); titles.append(normalize_text(cand["title"]))
        state["titles"] = titles[-500:]

    else:  # X kaynağı
        text = compose_with_summary(cand["title"], None)
        post_tweet(text=text, image_url=None, dry=dry)

        tids = state.get("tweet_ids", [])
        tids.append(cand["tweet_id"])
        state["tweet_ids"] = tids[-1000:]
        titles = state.get("titles", []); titles.append(normalize_text(cand["title"]))
        state["titles"] = titles[-500:]

    save_state(state)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[!] İptal edildi.")
    except Exception as e:
        print(f"[ERROR] {e}"); sys.exit(1)
