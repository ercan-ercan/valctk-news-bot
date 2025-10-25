#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
auto_fx_bot.py
→ Her akşam kapanış verilerini alır, PNG kart oluşturur ve tweet olarak paylaşır.
Kaynak: Stooq (usdtry, eurtry, xauusd)
"""

import os, sys, requests, csv, io, tweepy, argparse
from datetime import datetime
from dotenv import load_dotenv
from PIL import Image, ImageDraw, ImageFont

FONT_PATH = "/System/Library/Fonts/Supplemental/Arial Unicode.ttf"  # Mac için güvenli font
IMG_PATH = "fx_card.png"
TIMEOUT = 10
GRAM_PER_OUNCE = 31.1035
PREMIUM = 1.03  # tam altın primi

# --- yardımcılar ---
def tr_money(x: float) -> str:
    s = f"{x:,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")
    return s

def pct(now, prev):
    try: p = (now / prev - 1.0) * 100
    except: return "0.00%"
    arrow = "▲" if p >= 0 else "▼"
    return f"{arrow}{abs(p):.2f}%"

def fetch_last_two(symbol):
    url = f"https://stooq.com/q/d/l/?s={symbol}&i=d"
    r = requests.get(url, timeout=TIMEOUT)
    r.raise_for_status()
    rows = list(csv.DictReader(io.StringIO(r.text)))
    if len(rows) < 2: return None, None
    return float(rows[-2]["Close"]), float(rows[-1]["Close"])

# --- görsel üret ---
def create_image(data):
    bg = (16, 16, 24)
    fg = (255, 255, 255)
    accent = (0, 255, 127)
    im = Image.new("RGB", (700, 400), bg)
    d = ImageDraw.Draw(im)

    font_big = ImageFont.truetype(FONT_PATH, 38)
    font_small = ImageFont.truetype(FONT_PATH, 30)
    font_title = ImageFont.truetype(FONT_PATH, 42)

    d.text((40, 40), "Kapanış | Döviz & Altın", font=font_title, fill=accent)

    y = 130
    for label, val, change in data:
        d.text((60, y), label, font=font_big, fill=fg)
        d.text((300, y), tr_money(val), font=font_big, fill=fg)
        d.text((580, y), change, font=font_small, fill=(0, 200, 255) if "▲" in change else (255, 100, 100))
        y += 60

    d.text((40, 330), f"{datetime.now():%d %B %Y}", font=font_small, fill=(180,180,180))
    im.save(IMG_PATH)
    return IMG_PATH

# --- tweet işlemleri ---
def load_env_or_die():
    load_dotenv()
    for k in ["API_KEY","API_SECRET","ACCESS_TOKEN","ACCESS_TOKEN_SECRET","BEARER_TOKEN"]:
        if not os.getenv(k): raise SystemExit(f".env eksik: {k}")

def client():
    return tweepy.Client(
        consumer_key=os.getenv("API_KEY"),
        consumer_secret=os.getenv("API_SECRET"),
        access_token=os.getenv("ACCESS_TOKEN"),
        access_token_secret=os.getenv("ACCESS_TOKEN_SECRET"),
        bearer_token=os.getenv("BEARER_TOKEN")
    )

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    args = ap.parse_args()

    load_env_or_die()
    cli = client()

    usd_prev, usd_now = fetch_last_two("usdtry")
    eur_prev, eur_now = fetch_last_two("eurtry")
    xau_prev, xau_now = fetch_last_two("xauusd")

    if None in (usd_now, eur_now, xau_now):
        print("Veri alınamadı.")
        sys.exit(1)

    xautry_now = xau_now * usd_now
    xautry_prev = xau_prev * usd_prev

    gram_prev = xautry_prev / GRAM_PER_OUNCE
    gram_now = xautry_now / GRAM_PER_OUNCE

    tam_prev = gram_prev * 7.016 * PREMIUM
    tam_now = gram_now * 7.016 * PREMIUM

    data = [
        ("Dolar", usd_now, pct(usd_now, usd_prev)),
        ("Euro", eur_now, pct(eur_now, eur_prev)),
        ("Gram Altın", gram_now, pct(gram_now, gram_prev)),
        ("Tam Altın", tam_now, pct(tam_now, tam_prev)),
    ]

    img_path = create_image(data)
    caption = "Kapanış verileri 📊 #Dolar #Euro #Altın"

    if args.dry:
        print(f"Dry-run tamam. Kart: {img_path}")
        return

    try:
        media = cli.media_upload(filename=img_path)
        cli.create_tweet(text=caption, media_ids=[media.media_id])
        print("→ Görsel tweet gönderildi.")
    except Exception as e:
        print("Hata:", e)

if __name__ == "__main__":
    main()
