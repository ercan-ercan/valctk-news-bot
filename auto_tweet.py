#!/usr/bin/env python3
"""
auto_tweet.py (v2 endpoint)

Kullanım:
- Test (kimlik doğrulama):
    python auto_tweet.py --mode test
- Dosyadan sıradaki tweeti göster (göndermez):
    python auto_tweet.py --mode next --file tweets.txt
- Dosyadan sıradaki tweeti gönder:
    python auto_tweet.py --mode next --file tweets.txt --post
- Doğrudan metin gönder:
    python auto_tweet.py --mode text --text "Merhaba" --post
"""

import os
import argparse
import sys
from dotenv import load_dotenv
import tweepy

def load_env():
    load_dotenv()
    API_KEY = os.getenv("API_KEY")
    API_SECRET = os.getenv("API_SECRET")
    ACCESS_TOKEN = os.getenv("ACCESS_TOKEN")
    ACCESS_TOKEN_SECRET = os.getenv("ACCESS_TOKEN_SECRET")
    BEARER_TOKEN = os.getenv("BEARER_TOKEN")
    missing = [k for k,v in {
        "API_KEY": API_KEY,
        "API_SECRET": API_SECRET,
        "ACCESS_TOKEN": ACCESS_TOKEN,
        "ACCESS_TOKEN_SECRET": ACCESS_TOKEN_SECRET,
        "BEARER_TOKEN": BEARER_TOKEN
    }.items() if not v]
    if missing:
        raise RuntimeError(f".env içinde eksik alan(lar): {', '.join(missing)}")
    return API_KEY, API_SECRET, ACCESS_TOKEN, ACCESS_TOKEN_SECRET, BEARER_TOKEN

def make_client(api_key, api_secret, access_token, access_secret, bearer):
    # v2 user-context client (create_tweet için)
    client = tweepy.Client(
        consumer_key=api_key,
        consumer_secret=api_secret,
        access_token=access_token,
        access_token_secret=access_secret,
        bearer_token=bearer,
        wait_on_rate_limit=True
    )
    return client

def verify_v2(client):
    try:
        me = client.get_me()
        if me.data:
            return True, me.data.username
        return False, "get_me boş döndü"
    except Exception as e:
        return False, str(e)

def read_next_tweet(path):
    if not os.path.exists(path):
        return None, "tweets dosyası yok."
    with open(path, "r", encoding="utf-8") as f:
        lines = [line.rstrip("\n") for line in f if line.strip() != ""]
    if not lines:
        return None, "tweets dosyasında atılacak satır yok."
    return lines[0], lines[1:]

def save_remaining_and_archive(path, remaining_lines, sent_line):
    with open(path, "w", encoding="utf-8") as f:
        for l in remaining_lines:
            f.write(l + "\n")
    with open("tweets_sent.txt", "a", encoding="utf-8") as af:
        af.write(sent_line + "\n")

def create_tweet(client, text):
    try:
        resp = client.create_tweet(text=text)
        # resp.data -> {'id': '...', 'text': '...'}
        tid = resp.data.get("id") if resp and resp.data else None
        return True, tid or "unknown_id"
    except tweepy.TweepyException as te:
        # v2 yetki hataları burada yakalanır
        return False, f"TweepyException: {te}"
    except Exception as e:
        return False, str(e)

def main():
    parser = argparse.ArgumentParser(description="Auto Tweet Bot (v2)")
    parser.add_argument("--mode", choices=["test","next","text"], required=True)
    parser.add_argument("--file", default="tweets.txt")
    parser.add_argument("--text")
    parser.add_argument("--post", action="store_true", help="Gerçekten tweet at")
    args = parser.parse_args()

    try:
        api_key, api_secret, access_token, access_secret, bearer = load_env()
    except Exception as e:
        print("Hata: .env yüklenemiyor:", e)
        sys.exit(1)

    client = make_client(api_key, api_secret, access_token, access_secret, bearer)
    ok, user = verify_v2(client)
    if not ok:
        print("Kimlik doğrulama (v2) başarısız:", user)
        sys.exit(1)
    else:
        print(f"Başarılı giriş (v2): @{user}")

    if args.mode == "test":
        print("Test modu (v2): kimlik doğrulama OK. Tweet gönderilmeyecek.")
        sys.exit(0)

    if args.mode == "next":
        tweet, rest_or_msg = read_next_tweet(args.file)
        if tweet is None:
            print("Bilgi:", rest_or_msg)
            sys.exit(0)
        print("GÖSTERİM: Sıradaki tweet:")
        print("----------")
        print(tweet)
        print("----------")
        if not args.post:
            print("Dry-run (gönderilmeyecek). Gerçek göndermek için '--post' ekle.")
            sys.exit(0)
        success, res = create_tweet(client, tweet)
        if success:
            print("Tweet gönderildi (v2). ID:", res)
            save_remaining_and_archive(args.file, rest_or_msg, tweet)
        else:
            print("Gönderme hatası (v2):", res)
        sys.exit(0)

    if args.mode == "text":
        if not args.text:
            print("Hata: '--text' ile gönderilecek metni belirt.")
            sys.exit(1)
        tweet = args.text.strip()
        if len(tweet) > 280:
            print(f"Hata: Tweet {len(tweet)} karakter, 280'den fazla. Kısalt.")
            sys.exit(1)
        print("GÖSTERİM: Gönderilecek metin:")
        print("----------")
        print(tweet)
        print("----------")
        if not args.post:
            print("Dry-run (gönderilmeyecek). Gerçek göndermek için '--post' ekle.")
            sys.exit(0)
        success, res = create_tweet(client, tweet)
        if success:
            print("Tweet gönderildi (v2). ID:", res)
        else:
            print("Gönderme hatası (v2):", res)
        sys.exit(0)

if __name__ == "__main__":
    main()

