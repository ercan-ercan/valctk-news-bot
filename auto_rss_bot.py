#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
auto_rss_bot.py — Kısa, doğal özetli otomatik haber tweet botu
- RSS'ten haber çeker.
- Haberi indirir, 1–2 cümlelik sade bir özet oluşturur.
- Link paylaşmaz.
- Karakter sınırına (280) uyar.
- Yazım ve noktalama düzgün.
- Filtre: gündem, ekonomi, siyaset, spor, teknoloji, sosyal.
"""

import os, sys, json, time, argparse, re
import requests
from bs4 import BeautifulSoup
import feedparser
import tweepy
from dotenv import load_dotenv

STATE_PATH = "rss_state.json"

# ======== Filtre (önemli haberler) ========
KEYWORDS = [
    # Gündem & Siyaset
    "son dakika","açıklama","cumhurbaşkanı","bakan","kabine","kararname",
    "meclis","yasa","seçim","skandal","yolsuzluk","soruşturma",
    # Ekonomi
    "dolar","euro","altın","borsa","enflasyon","faiz","zam","asgari ücret","ekonomi",
    # Teknoloji
    "apple","iphone","samsung","galaxy","android","yapay zeka","ai","teknoloji",
    # Spor
    "tff","pfdk","fenerbahçe","galatasaray","beşiktaş","trabzonspor","transfer","derbi",
    # Sosyal Medya & Gündem
    "video","gündem oldu","tepki","trend","viral","paylaşım","sosyal medya",
    # Dünya
    "israil","gazze","abd","avrupa","rusya","ukrayna","iran","çin"
]

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; ValctkNewsBot/1.0)"}


# ======== Yardımcı Fonksiyonlar ========
def load_env_or_die():
    load_dotenv()
    for k in ["API_KEY","API_SECRET","ACCESS_TOKEN","ACCESS_TOKEN_SECRET","BEARER_TOKEN"]:
        if not os.getenv(k):
            raise SystemExit(f".env eksik: {k}")

def tw_client():
    return tweepy.Client(
        consumer_key=os.getenv("API_KEY"),
        consumer_secret=os.getenv("API_SECRET"),
        access_token=os.getenv("ACCESS_TOKEN"),
        access_token_secret=os.getenv("ACCESS_TOKEN_SECRET"),
        bearer_token=os.getenv("BEARER_TOKEN")
    )

def load_sources(path="rss_sources.txt"):
    if not os.path.exists(path):
        raise SystemExit("rss_sources.txt bulunamadı.")
    with open(path, "r", encoding="utf-8") as f:
        return [x.strip() for x in f if x.strip() and not x.startswith("#")]

def load_state():
    if not os.path.exists(STATE_PATH): return {}
    try:
        return json.load(open(STATE_PATH, "r", encoding="utf-8"))
    except Exception:
        return {}

def save_state(state):
    json.dump(state, open(STATE_PATH, "w", encoding="utf-8"), ensure_ascii=False, indent=2)


# ======== Haber Metnini Getir ========
def fetch_article_text(link):
    try:
        r = requests.get(link, headers=HEADERS, timeout=10)
        r.raise_for_status()
    except Exception:
        return ""
    soup = BeautifulSoup(r.text, "lxml")
    for tag in soup(["script","style","noscript","header","footer","nav","aside"]):
        tag.decompose()

    paragraphs = [p.get_text(" ", strip=True) for p in soup.find_all("p")]
    text = " ".join(paragraphs)
    return text.strip()[:2000]


# ======== Otomatik Özet (Kısa, net, doğal dilde) ========
def summarize(title, text):
    # sadece ilk birkaç cümleyi al
    sentences = re.split(r'(?<=[.!?])\s+', text)
    short = sentences[:2]
    summary = " ".join(short).strip()

    # Eğer özet yoksa başlığı kullan
    if not summary or len(summary) < 60:
        summary = title

    # Karakter sınırı 280
    if len(summary) > 270:
        summary = summary[:270].rsplit(" ", 1)[0] + "…"

    # Noktalama ve dil düzeltmesi
    summary = re.sub(r'\s+', ' ', summary)
    summary = summary.replace(" ,", ",").replace(" .", ".")
    summary = summary.replace(" ?", "?").replace(" !", "!").strip()

    return summary


# ======== Tweet Akışı ========
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-posts", type=int, default=3)
    ap.add_argument("--per-feed", type=int, default=2)
    ap.add_argument("--dry", action="store_true")
    args = ap.parse_args()

    load_env_or_die()
    client = tw_client()
    sources = load_sources()
    state = load_state()

    posted = 0

    for url in sources:
        if posted >= args.max_posts:
            break
        feed = feedparser.parse(url)
        entries = getattr(feed, "entries", [])
        seen = set(state.get(url, {}).get("seen", []))
        new_entries = [e for e in entries if e.get("link") not in seen]

        for e in new_entries[:args.per_feed]:
            title = getattr(e, "title", "").strip()
            link = getattr(e, "link", "").strip()
            if not title or not link: 
                continue

            if not any(k in (title + " ").lower() for k in KEYWORDS):
                continue

            article = fetch_article_text(link)
            tweet_text = summarize(title, article)

            print("\n--- TWEET ---")
            print(tweet_text)

            if not args.dry:
                try:
                    client.create_tweet(text=tweet_text)
                    posted += 1
                    state.setdefault(url, {}).setdefault("seen", []).append(link)
                    print("→ Tweet gönderildi.")
                except Exception as ex:
                    print(f"Hata: {ex}")

            if posted >= args.max_posts:
                break

    save_state(state)
    print(f"\nToplam gönderilen: {posted}")


if __name__ == "__main__":
    main()
