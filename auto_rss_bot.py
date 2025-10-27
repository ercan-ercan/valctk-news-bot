#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
auto_rss_bot.py
- RSS kaynaklarını okur, sayfa içeriğini toplar.
- Kurallı, kısa ve düzgün noktalama ile özet çıkarır (5N1K YOK).
- Tek cümle veya en çok iki kısa cümle üretir; “tırnak”lar korunur.
- Aynı haberi ikinci kez atmaz (rss_state.json).
- Log çıktıları GitHub Actions’ta görünsün diye tüm print()’ler flush=True.
"""

import os, json, time, argparse, re, hashlib
from typing import List, Tuple, Dict, Set
import requests
from bs4 import BeautifulSoup
import feedparser
import tweepy

# -----------------------------
# Ortam değişkenleri (Twitter + OpenAI isteğe bağlı)
# -----------------------------
API_KEY             = os.getenv("API_KEY")
API_SECRET          = os.getenv("API_SECRET")
ACCESS_TOKEN        = os.getenv("ACCESS_TOKEN")
ACCESS_TOKEN_SECRET = os.getenv("ACCESS_TOKEN_SECRET")
BEARER_TOKEN        = os.getenv("BEARER_TOKEN", "")
OPENAI_API_KEY      = os.getenv("OPENAI_API_KEY", "")

# -----------------------------
# Sabitler / Dosyalar
# -----------------------------
SOURCES_FILE   = "rss_sources.txt"
STATE_FILE     = "rss_state.json"
USER_AGENT     = "Mozilla/5.0 (news-bot; +https://github.com)"
MAX_TWEET_LEN  = 280

# Basit filtre: clickbait/galeri vb. elemine et
SKIP_PATTERNS = [
    r"\bgaleri\b", r"foto\s*galeri", r"izle$", r"video$",
    r"canlı anlatım", r"canlı blog", r"son durum canlı",
]

# Odak: gündem/ekonomi/siyaset/spor/teknoloji ve viral sosyal
KEYWORDS_POSITIVE = [
    # Ekonomi & finans
    "enflasyon","faiz","dolar","euro","altın","borsa","vergi","zam",
    # Siyaset & kamu
    "cumhurbaşkanı","bakan","meclis","yasak","yasa","mahkeme","savcı","tutuklandı",
    # Güvenlik/olay
    "deprem","yangın","patlama","saldırı","kazası","gözaltı",
    # Spor büyükler & yıldız
    "fenerbahçe","galatasaray","beşiktaş","trabzonspor","transfer","tff","pfdk",
    # Teknoloji & platform
    "instagram","spotify","apple","samsung","yapay zeka","ai","playstation","ps5","xr",
]

# -----------------------------
# Yardımcılar
# -----------------------------
def log(msg: str) -> None:
    print(msg, flush=True)

def load_sources(path: str) -> List[str]:
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        urls = [ln.strip() for ln in f if ln.strip() and not ln.strip().startswith("#")]
    return urls

def load_state(path: str) -> Set[str]:
    if not os.path.exists(path):
        return set()
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return set(data.get("seen", []))
    except Exception:
        return set()

def save_state(path: str, seen: Set[str]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"seen": sorted(list(seen))}, f, ensure_ascii=False)

def get_hash(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:16]

def fetch_html_text(url: str, timeout: int = 10) -> str:
    try:
        r = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=timeout)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")

        # Ortak gereksiz alanlar
        for sel in ["script","style","noscript","header","footer","nav","aside"]:
            for node in soup.select(sel):
                node.decompose()

        # Başlık/habere yakın içerik için heuristik:
        main = soup.find("article") or soup.find("main") or soup.find("div", {"id":"content"}) or soup
        text = " ".join(main.get_text(" ", strip=True).split())
        return text
    except Exception as e:
        log(f"⚠️ İçerik indirilemedi: {e}")
        return ""

def clean_spaces(s: str) -> str:
    s = re.sub(r"\s+", " ", s).strip()
    s = s.replace(" ,", ",").replace(" .", ".")
    return s

def smart_truncate(s: str, limit: int) -> str:
    if len(s) <= limit:
        return s
    cut = s[:limit-1]
    # cümle sınırı kesimi tercih et
    m = re.finditer(r"[.!?…]", cut)
    ends = [mm.end() for mm in m]
    if ends:
        cut = cut[:ends[-1]]
    return cut.rstrip() + "…"

def looks_clickbait(title: str) -> bool:
    title_l = title.lower()
    for pat in SKIP_PATTERNS:
        if re.search(pat, title_l):
            return True
    return False

def matches_interest(title: str, text: str) -> bool:
    blob = (title + " " + text).lower()
    return any(kw in blob for kw in KEYWORDS_POSITIVE)

def normalize_quotes(s: str) -> str:
    # düz tırnak tercih
    s = s.replace("“", "\"").replace("”", "\"").replace("‘", "'").replace("’", "'")
    return s

def rule_based_summary(title: str, body: str) -> str:
    """
    Çok hızlı, deterministik özet:
    - Başlıktan abartı/etiket kırp,
    - Gövdeden ana cümleyi seç,
    - Max iki kısa cümle üret.
    """
    title = normalize_quotes(clean_spaces(title))
    body  = normalize_quotes(clean_spaces(body))

    # Başlıktan parazit temizliği
    title = re.sub(r"\s*\|.*$", "", title)              # | Site Adı
    title = re.sub(r"^\s*(SON DAKİKA\s*[:\-–])\s*", "", title, flags=re.I)
    title = re.sub(r"\s*\(video\)|\s*\(galeri\)", "", title, flags=re.I)

    # Gövdeden anlamlı ilk cümle(ler)
    sentences = re.split(r"(?<=[.!?…])\s+", body)
    sentences = [s for s in sentences if len(s.split()) >= 4][:3]
    core = " ".join(sentences[:2]) if sentences else ""

    # Aynı bilgiyi tekrar etmiyorsa başlığı koru, yoksa sadece gövde cümlesi
    if core and title.lower() not in core.lower():
        merged = f"{title}. {core}"
    else:
        merged = title if title else core

    merged = clean_spaces(merged)
    # Noktalama sonu
    if merged and merged[-1] not in ".!?…":
        merged += "."
    # Twitter limiti
    merged = smart_truncate(merged, MAX_TWEET_LEN)
    return merged

def prepare_tweet(title: str, link: str) -> Tuple[str, str]:
    txt = fetch_html_text(link)
    tw = rule_based_summary(title, txt) if txt else clean_spaces(title)
    # link eklemiyoruz (senin tercihine göre)
    return tw, txt

def post_tweet(client: tweepy.Client, text: str) -> Tuple[bool, str]:
    try:
        resp = client.create_tweet(text=text)
        tid = resp.data.get("id") if resp and resp.data else "unknown"
        return True, str(tid)
    except tweepy.TweepyException as e:
        return False, f"Twitter API error: {getattr(e, 'response', e)}"
    except Exception as e:
        return False, f"Hata: {e}"

# -----------------------------
# Ana akış
# -----------------------------
def run_bot(dry: bool, max_posts: int, per_feed: int) -> Tuple[int,int,int]:
    sources = load_sources(SOURCES_FILE)
    if not sources:
        log("⚠️ Kaynak bulunamadı (rss_sources.txt boş ya da yok).")
        return (0,0,0)

    seen = load_state(STATE_FILE)
    prepared, sent, skipped = 0, 0, 0

    # Twitter client
    client = None
    if not dry:
        if not all([API_KEY, API_SECRET, ACCESS_TOKEN, ACCESS_TOKEN_SECRET]):
            log("❌ Twitter anahtarları eksik. .env ve GitHub Secrets kontrol edin.")
            return (0,0,0)
        client = tweepy.Client(
            consumer_key=API_KEY,
            consumer_secret=API_SECRET,
            access_token=ACCESS_TOKEN,
            access_token_secret=ACCESS_TOKEN_SECRET
        )

    for feed_url in sources:
        log(f"\n[FEED] {feed_url}")
        try:
            parsed = feedparser.parse(feed_url)
        except Exception as e:
            log(f"⚠️ RSS okunamadı: {e}")
            continue

        count_this_feed = 0
        for entry in parsed.entries:
            if prepared >= max_posts:
                break

            title = entry.get("title", "").strip()
            link  = entry.get("link", "").strip() or entry.get("id", "")
            if not title or not link:
                continue

            hid = get_hash(link)
            if hid in seen:
                skipped += 1
                continue

            if looks_clickbait(title):
                skipped += 1
                continue

            tweet_text, raw_text = prepare_tweet(title, link)
            if not matches_interest(title, raw_text):
                skipped += 1
                continue

            prepared += 1
            count_this_feed += 1

            log("\n--- TWEET ---",)
            log(tweet_text)

            if dry:
                log("→ DRY-MODE (tweet edilmedi).")
            else:
                ok, info = post_tweet(client, tweet_text)
                if ok:
                    sent += 1
                    log(f"✅ Gönderildi. ID: {info}")
                else:
                    log(f"❌ Gönderilemedi: {info}")

            seen.add(hid)
            if count_this_feed >= per_feed:
                break

            # hız limiti koruması
            time.sleep(1)

        if prepared >= max_posts:
            break

    save_state(STATE_FILE, seen)
    return prepared, sent, skipped

# -----------------------------
# CLI
# -----------------------------
def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--dry", action="store_true", help="Tweet atmadan deneme çalıştır")
    p.add_argument("--max-posts", type=int, default=2, help="Toplam üst sınır")
    p.add_argument("--per-feed", type=int, default=2, help="Her feed’den en çok kaç adet")
    return p.parse_args()

if __name__ == "__main__":
    args = parse_args()
    prepared, sent, skipped = run_bot(args.dry, args.max_posts, args.per_feed)
    log(f"\nHazırlanan: {prepared} | Gönderilen: {sent} | Atlanan: {skipped}")
