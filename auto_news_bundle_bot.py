#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os, re, argparse, textwrap, html, time
from urllib.parse import urlparse
import requests
from bs4 import BeautifulSoup
import tweepy

# --- Config ---
UA = {"User-Agent": "Mozilla/5.0 (compatible; BundleScraper/1.0)"}
TIMEOUT = 12
RESERVE_TCO = 25          # t.co kısaltmaya pay (link + boşluk)
MAX_TWEET = 280
DRY = os.environ.get("DRY_MODE", "false").lower() == "true"

# --- Twitter v2 client (metin-only) ---
API_KEY = os.environ.get("API_KEY")
API_SECRET = os.environ.get("API_SECRET")
ACCESS_TOKEN = os.environ.get("ACCESS_TOKEN")
ACCESS_TOKEN_SECRET = os.environ.get("ACCESS_TOKEN_SECRET")
BEARER_TOKEN = os.environ.get("BEARER_TOKEN")

def tw_client_v2():
    return tweepy.Client(
        bearer_token=BEARER_TOKEN,
        consumer_key=API_KEY,
        consumer_secret=API_SECRET,
        access_token=ACCESS_TOKEN,
        access_token_secret=ACCESS_TOKEN_SECRET,
        wait_on_rate_limit=True,
    )

def get_html(url: str) -> BeautifulSoup:
    r = requests.get(url, headers=UA, timeout=TIMEOUT)
    r.raise_for_status()
    return BeautifulSoup(r.text, "lxml")

def clean_text(s: str) -> str:
    s = html.unescape(s)
    s = re.sub(r"\s+", " ", s).strip()
    # gereksiz prefixler
    s = re.sub(r"^\u2022\s*", "", s)  # baştaki bullet
    return s

def extract_title(doc: BeautifulSoup) -> str:
    # <h1> veya <title>
    h1 = doc.find(["h1","h2"])
    if h1 and h1.get_text(strip=True):
        return clean_text(h1.get_text())
    t = doc.find("meta", property="og:title")
    if t and t.get("content"):
        return clean_text(t["content"])
    if doc.title and doc.title.string:
        return clean_text(doc.title.string)
    return ""

def find_ai_summary_block(doc: BeautifulSoup) -> list[str]:
    """
    Bundle AI özet kutusundaki maddeleri yakalamaya odaklı esnek seçiciler.
    Dönüş: madde listesi (string).
    """
    # 1) "özetliyor" başlığı yakınındaki <li> maddeleri
    candidates = []
    for tag in doc.find_all(text=re.compile(r"Bundle\s*AI|özetliyor", re.I)):
        # yakınındaki listeleri topla
        parent = tag.parent
        for ul in parent.find_all_next(["ul","ol"], limit=2):
            lis = [clean_text(li.get_text(" ", strip=True)) for li in ul.find_all("li")]
            if lis:
                candidates.append(lis)
                break
        # bullet paragraf (•) varsa
        sibs = parent.find_all_next(["p","div"], limit=4)
        bullets = []
        for s in sibs:
            txt = s.get_text(" ", strip=True)
            if "•" in txt:
                parts = [clean_text(x) for x in re.split(r"[•\u2022]", txt) if x.strip()]
                bullets.extend(parts)
        if bullets:
            candidates.append(bullets)
    if candidates:
        # en dolu olanı seç
        return max(candidates, key=len)

    # 2) class adında 'summary' geçen bloklardan liste çıkar
    for div in doc.find_all(attrs={"class": re.compile("summary", re.I)}):
        lis = [clean_text(li.get_text(" ", strip=True)) for li in div.find_all("li")]
        if lis:
            return lis

    # yoksa boş
    return []

def fallback_description(doc: BeautifulSoup) -> str:
    for key in ["og:description","twitter:description","description"]:
        m = doc.find("meta", attrs={"property": key}) or doc.find("meta", attrs={"name": key})
        if m and m.get("content"):
            return clean_text(m["content"])
    # ilk uzun paragraf
    for p in doc.find_all("p"):
        txt = clean_text(p.get_text(" ", strip=True))
        if len(txt) > 100:
            return txt
    return ""

def compose_tweet(title: str, bullets: list[str], url: str) -> str:
    host = urlparse(url).netloc.replace("www.","")
    tail = f" — kaynak: {host} {url}"
    room = MAX_TWEET - RESERVE_TCO - len(tail)
    title = title[:room].rstrip()

    if bullets:
        # 2 maddeye kadar, kısa tut
        use = []
        for b in bullets:
            if len(" • " + b) + len(title) + sum(len(" • " + x) for x in use) > room:
                break
            use.append(b)
            if len(use) == 2: break
        body = (title + "\n" + "\n".join(f"• {b}" for b in use)).strip()
    else:
        body = title

    # hala uzun ise kısalt
    if len(body) > room:
        body = body[:max(0, room-1)].rstrip() + "…"

    return f"{body}{tail}"

def make_tweet_from_bundle(url: str) -> str:
    doc = get_html(url)
    title = extract_title(doc)
    bullets = find_ai_summary_block(doc)
    if not bullets:
        desc = fallback_description(doc)
        if desc:
            # desc'i bir maddeye çevir
            bullets = [desc]
    if not title and not bullets:
        raise RuntimeError("Sayfadan özet çekilemedi")

    return compose_tweet(title, bullets, url)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True, help="Bundle haber URL")
    ap.add_argument("--dry", action="store_true", help="Sadece yazdır, tweet atma")
    args = ap.parse_args()

    tweet = make_tweet_from_bundle(args.url)

    if DRY or args.dry:
        print("— DRY RUN —")
        print(tweet)
        return

    client = tw_client_v2()
    client.create_tweet(text=tweet)
    print("✅ Tweet gönderildi.")

if __name__ == "__main__":
    main()
