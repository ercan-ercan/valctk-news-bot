#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import csv
import requests
from datetime import datetime, timedelta, timezone
import tweepy
from tweepy.errors import Forbidden, TooManyRequests

# --- Modlar / env ---
DRY = os.environ.get("DRY_MODE", "false").lower() == "true"

# v1.1 anahtarları
API_KEY = os.environ.get("API_KEY")
API_SECRET = os.environ.get("API_SECRET")
ACCESS_TOKEN = os.environ.get("ACCESS_TOKEN")
ACCESS_TOKEN_SECRET = os.environ.get("ACCESS_TOKEN_SECRET")

# v2 için ayrıca bearer da gerekli
BEARER_TOKEN = os.environ.get("BEARER_TOKEN")

# --- Tweepy client'lar ---
def tweepy_api_v11():
    auth = tweepy.OAuth1UserHandler(API_KEY, API_SECRET, ACCESS_TOKEN, ACCESS_TOKEN_SECRET)
    return tweepy.API(auth)

def tweepy_client_v2():
    return tweepy.Client(
        bearer_token=BEARER_TOKEN,
        consumer_key=API_KEY,
        consumer_secret=API_SECRET,
        access_token=ACCESS_TOKEN,
        access_token_secret=ACCESS_TOKEN_SECRET,
        wait_on_rate_limit=False,
    )

# --- Veri kaynakları ---
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

def fetch_erapi(base):
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
    """Önce Stooq, olmazsa er-api; altın opsiyonel."""
    usd = eur = gbp = xau_usd = None

    stooq = safe_try(fetch_stooq_latest, ["usdntry", "eurtry", "gbptry", "xauusd"])
    if stooq:
        usd = stooq.get("usdntry") or usd
        eur = stooq.get("eurtry") or eur
        gbp = stooq.get("gbptry") or gbp
        xau_usd = stooq.get("xauusd") or xau_usd

    if usd is None: usd = safe_try(fetch_erapi, "USD")
    if eur is None: eur = safe_try(fetch_erapi, "EUR")
    if gbp is None: gbp = safe_try(fetch_erapi, "GBP")

    if usd is None and eur is None:
        raise RuntimeError("Kurlar alınamadı (Stooq/er-api)")

    gram_altin = None
    if xau_usd is not None and usd is not None:
        gram_altin = (xau_usd * usd) / 31.1035

    return {
        "Dolar": usd,
        "Euro": eur,
        "Pound": gbp,
        "Gram Altın": gram_altin,
        "Ons Altın (USD)": xau_usd,
    }

# --- Metin ---
def format_price(x):
    if x is None:
        return "-"
    return f"{x:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

def build_text(data):
    lines = ["Güncel Kurlar:"]
    if data["Dolar"] is not None:  lines.append(f"• Dolar : {format_price(data['Dolar'])}")
    if data["Euro"]  is not None:  lines.append(f"• Euro  : {format_price(data['Euro'])}")
    if data["Pound"] is not None:  lines.append(f"• Pound : {format_price(data['Pound'])}")

    extras = []
    if data["Gram Altın"] is not None:
        extras.append(f"Gram Altın: {format_price(data['Gram Altın'])} TL")
    if data["Ons Altın (USD)"] is not None:
        extras.append(f"Ons Altın : {format_price(data['Ons Altın (USD)'])} $")
    if extras:
        lines.append("")
        lines.extend(extras)

    return "\n".join(lines)

# --- Tweet at ---
def post_tweet(text: str) -> bool:
    # 1) v1.1 dene
    try:
        api = tweepy_api_v11()
        api.update_status(status=text)
        print("[TWITTER v1.1] ✅ Tweet gönderildi.")
        return True
    except Forbidden as e:
        # 453 → v2'ye düş
        print("[TWITTER v1.1] 403/453 — v2 create_tweet'e geçiliyor.")
    except TooManyRequests:
        print("[TWITTER v1.1] Rate limit — v2'yi deniyorum.")
    except Exception as e:
        print(f"[TWITTER v1.1 ERROR] {e} — v2'yi deniyorum.")

    # 2) v2 ile dene
    try:
        client = tweepy_client_v2()
        client.create_tweet(text=text)
        print("[TWITTER v2] ✅ Tweet gönderildi.")
        return True
    except Forbidden as e:
        # duplicate content gibi durumları şeffaf yaz
        print(f"[TWITTER v2 ERROR] Forbidden: {e}")
        return False
    except TooManyRequests:
        print("[TWITTER v2 ERROR] Rate limit.")
        return False
    except Exception as e:
        print(f"[TWITTER v2 ERROR] {e}")
        return False

# --- Main ---
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

    ok = post_tweet(text)
    if ok:
        print("✅ Tamam.")
    else:
        print("⚠️ Tweet gönderilemedi.")

if __name__ == "__main__":
    main()
