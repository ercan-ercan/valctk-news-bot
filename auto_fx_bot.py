#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import csv
import requests
from datetime import datetime, timedelta, timezone
import tweepy

DRY = os.environ.get("DRY_MODE", "false").lower() == "true"

API_KEY = os.environ.get("API_KEY")
API_SECRET = os.environ.get("API_SECRET")
ACCESS_TOKEN = os.environ.get("ACCESS_TOKEN")
ACCESS_TOKEN_SECRET = os.environ.get("ACCESS_TOKEN_SECRET")

def tweepy_client():
    auth = tweepy.OAuth1UserHandler(API_KEY, API_SECRET, ACCESS_TOKEN, ACCESS_TOKEN_SECRET)
    return tweepy.API(auth)

STOOQ_URL = "https://stooq.com/q/l/?s={symbols}&i=d"

def fetch_stooq_latest(symbols):
    url = STOOQ_URL.format(symbols=",".join(symbols))
    r = requests.get(url, timeout=10)
    r.raise_for_status()
    out = {}
    for row in csv.reader(r.text.strip().splitlines()):
        if len(row) < 7:
            continue
        sym = row[0].strip().lower()
        try:
            close = float(row[6])
        except Exception:
            continue
        out[sym] = close
    return out

def fetch_fx_snapshot():
    syms = ["usdntry", "eurtry", "gbpntry", "xauusd"]
    data = fetch_stooq_latest(syms)
    usd_try = data.get("usdntry")
    eur_try = data.get("eurtry")
    gbp_try = data.get("gbpntry")
    xau_usd = data.get("xauusd")
    if not usd_try or not eur_try or not xau_usd:
        raise RuntimeError("Kurlar alınamadı (Stooq)")
    gram_altin = (xau_usd * usd_try) / 31.1035
    return {
        "Dolar": usd_try,
        "Euro": eur_try,
        "Pound": gbp_try,
        "Gram Altın": gram_altin,
        "Ons Altın (USD)": xau_usd,
    }

def format_price(x):
    if x is None:
        return "-"
    return f"{x:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

def build_text(data):
    lines = [
        "Güncel Kurlar:",
        f"• Dolar : {format_price(data['Dolar'])}",
        f"• Euro  : {format_price(data['Euro'])}",
        f"• Pound : {format_price(data['Pound'])}",
        "",
        f"Gram Altın: {format_price(data['Gram Altın'])} TL",
        f"Ons Altın : {format_price(data['Ons Altın (USD)'])} $",
    ]
    return "\n".join(lines)

def main():
    try:
        data = fetch_fx_snapshot()
    except Exception as e:
        print(f"Veri alınamadı: {e}")
        print("⚠️ Veriler alınamadı, tweet atlanıyor.")
        return

    text = build_text(data)

    if DRY:
        print("— DRY RUN —")
        print(text)
        return

    api = tweepy_client()
    api.update_status(status=text)
    print("✅ Tweet gönderildi.")

if __name__ == "__main__":
    main()
PY
