#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
auto_rewriter_simple.py
Free plana uygun sade versiyon (format koru + cevapta kaynak).
- Tek hesap (valctk) kullanır.
- Okuma + tweet atma aynı hesaptan.
- Rate limit gelirse direkt çıkar.
- Ana tweet: kaynak metin olduğu gibi
- Cevap tweet: '— Kaynak: @username' (isteğe bağlı --credit-reply)
"""

import os, re, sys, time, json, tweepy, argparse
from dotenv import load_dotenv

load_dotenv()
for key in ["API_KEY", "API_SECRET", "ACCESS_TOKEN", "ACCESS_TOKEN_SECRET", "BEARER_TOKEN"]:
    if not os.getenv(key):
        raise SystemExit(f".env eksik: {key}")

client = tweepy.Client(
    consumer_key=os.getenv("API_KEY"),
    consumer_secret=os.getenv("API_SECRET"),
    access_token=os.getenv("ACCESS_TOKEN"),
    access_token_secret=os.getenv("ACCESS_TOKEN_SECRET"),
    bearer_token=os.getenv("BEARER_TOKEN"),
    wait_on_rate_limit=False
)

def fetch(username, since_id=None, limit=1):
    """Kaynaktan yeni tweetleri getir (en sondakiler)."""
    try:
        u = client.get_user(username=username)
        if not u or not u.data:
            print(f"[{username}] kullanıcı bulunamadı.")
            return []
        uid = u.data.id
        params = {
            "id": uid,
            "exclude": ["retweets","replies"],
            "tweet_fields": ["lang","created_at"],
            "max_results": 5
        }
        if since_id:
            params["since_id"] = since_id
        r = client.get_users_tweets(**params)
        if not r or not r.data:
            print(f"[{username}] yeni tweet yok.")
            return []
        arr = list(r.data)
        arr.sort(key=lambda x: int(x.id))
        return arr[-limit:]
    except tweepy.TooManyRequests:
        print(f"[{username}] Rate limit. Çıkılıyor.")
        sys.exit(0)
    except Exception as e:
        print(f"[{username}] Hata: {e}")
        return []

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--post", action="store_true", help="Gerçekten gönder")
    ap.add_argument("--only", type=str, default="", help="Sadece bu kullanıcı")
    ap.add_argument("--limit", type=int, default=1, help="Kaç tweet işlensin (sondan)")
    ap.add_argument("--credit-reply", action="store_true", help="Kaynağı cevap olarak ekle")
    args = ap.parse_args()

    print("Giriş: OK")

    # sources.txt oku
    if not os.path.exists("sources.txt"):
        raise SystemExit("sources.txt bulunamadı.")
    with open("sources.txt", "r", encoding="utf-8") as f:
        sources = [x.strip().lstrip("@") for x in f if x.strip()]

    # --only varsa filtrele
    if args.only:
        sources = [x for x in sources if x == args.only]
        if not sources:
            print("Seçtiğin --only sources.txt ile eşleşmiyor.")
            sys.exit(0)

    for username in sources:
        tweets = fetch(username, limit=args.limit)
        for tw in tweets:
            original = tw.text  # formatı KORU (hashtag/URL dahil)

            print("\n--- KAYNAK ---")
            print(f"@{username} | id={tw.id}")
            print(original)
            print("--- PLAN ---")
            print("1) Ana tweet: (kaynak metin aynen)")
            print("2) Cevap: '— Kaynak: @%s'" % username)

            if not args.post:
                print("→ Dry-run (gönderilmedi).")
                continue

            # 1) Ana tweeti at
            try:
                r1 = client.create_tweet(text=original)
                main_id = r1.data.get("id") if r1 and r1.data else None
                print(f"→ Ana tweet gönderildi. ID: {main_id}")
            except tweepy.TooManyRequests:
                print("→ Rate limit (ana tweet). Çıkılıyor.")
                sys.exit(0)
            except Exception as e:
                print(f"→ Ana tweet hatası: {e}")
                continue

            # 2) Cevap olarak kaynak ekle (opsiyonel)
            if args.credit_reply and main_id:
                try:
                    r2 = client.create_tweet(
                        text=f"— Kaynak: @{username}",
                        in_reply_to_tweet_id=main_id
                    )
                    reply_id = r2.data.get("id") if r2 and r2.data else None
                    print(f"→ Cevap (kaynak) gönderildi. ID: {reply_id}")
                except tweepy.TooManyRequests:
                    print("→ Rate limit (cevap). Çıkılıyor.")
                    sys.exit(0)
                except Exception as e:
                    print(f"→ Cevap hatası: {e}")

if __name__ == "__main__":
    main()
