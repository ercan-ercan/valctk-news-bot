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

# ---------------------- Veri kaynakları ----------------------

STOOQ_URL = "https://stooq.com/q/l/?s={symbols}&i=d"

def fetch_stooq_latest(symbols):
    """Stooq list API tek satırlık CSV döndürür. close değerlerini alır."""
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

def fetch_erapi(base):
    """open.er-api.com — base -> TRY oranını döndürür (float)"""
    url = f"https://open.er-api.com/v6/latest/{base}"
    r = requests.get(url, timeout=10)
    r.raise_for_status()
    data = r.json()
    if data.get("result") != "success":
        raise RuntimeError("er-api fail")
    rate = data["rates"].get("TRY")
    if not rate:
        raise RuntimeError("TRY not in er-api")
    return float(rate)

def safe_try(func, *args, **kwargs):
    try:
        return func(*args, **kwargs)
    except Exception:
        return None

def fetch_fx_snapshot():
    """Önce Stooq, olmazsa er-api ile USD/EUR/GBP getir.
       Altın (xauusd) sadece Stooq’tan, yoksa None."""
    usd = eur = gbp = xau_usd = None

    # 1) Stooq dene
    stooq = safe_try(fetch_stooq_latest, ["usdntry", "eurtry", "gbptry", "xauusd"])
    if stooq:
        usd = stooq.get("usdntry") or usd
        eur = stooq.get("eurtry") or eur
        gbp = stooq.get("gbptry") or gbp
        xau_usd = stooq.get("xauusd") or xau_usd

    # 2) Eksik kalanlar için er-api yedeği
    if usd is None:
        usd = safe_try(fetch_erapi, "USD")
    if eur is None:
        eur = safe_try(fetch_erapi, "EUR")
    if gbp is None:
        gbp = safe_try(fetch_erapi, "GBP")

    # En azından USD veya EUR yoksa, tweet atmanın anlamı yok
    if usd is None and eur is None:
        raise RuntimeError("Kurlar alınamadı (Stooq/er-api)")

    gram_altin = None
    if xau_usd is not None and usd is not None:
        # Gram altın ≈ ons altın(USD) * USD/TRY / 31.1035
        gram_altin = (xau_usd * usd) / 31.1035

    return {
        "Dolar": usd,
        "Euro": eur,
        "Pound": gbp,
        "Gram Altın": gram_altin,
        "Ons Altın (USD)": xau_usd,
    }

# ---------------------- Metin oluşturma ----------------------

def format_price(x):
    if x is None:
        return "-"
    return f"{x:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

def build_text(data):
    lines = ["Güncel Kurlar:"]
    if data["Dolar"] is not None:
        lines.append(f"• Dolar : {format_price(data['Dolar'])}")
    if data["Euro"] is not None:
        lines.append(f"• Euro  : {format_price(data['Euro'])}")
    if data["Pound"] is not None:
        lines.append(f"• Pound : {format_price(data['Pound'])}")

    # Altınlar opsiyonel — varsa ekle
    extras = []
    if data["Gram Altın"] is not None:
        extras.append(f"Gram Altın: {format_price(data['Gram Altın'])} TL")
    if data["Ons Altın (USD)"] is not None:
        extras.append(f"Ons Altın : {format_price(data['Ons Altın (USD)'])} $")
    if extras:
        lines.append("")  # boş satır
        lines.extend(extras)

    return "\n".join(lines)

# ---------------------- Ana akış ----------------------

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
