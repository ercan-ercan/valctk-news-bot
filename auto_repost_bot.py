import os
import tweepy
import requests
from bs4 import BeautifulSoup
from unidecode import unidecode
from rapidfuzz import fuzz

# ENV
API_KEY = os.getenv("TW_API_KEY")
API_SECRET = os.getenv("TW_API_SECRET")
ACCESS_TOKEN = os.getenv("TW_ACCESS_TOKEN")
ACCESS_SECRET = os.getenv("TW_ACCESS_SECRET")
BEARER_TOKEN = os.getenv("BEARER_TOKEN")

# --- CLIENTS ---
def get_client_v2():
    return tweepy.Client(
        consumer_key=API_KEY,
        consumer_secret=API_SECRET,
        access_token=ACCESS_TOKEN,
        access_token_secret=ACCESS_SECRET,
        wait_on_rate_limit=True
    )

def get_ro_client_v2():
    # read-only (app-only)
    return tweepy.Client(
        bearer_token=BEARER_TOKEN,
        wait_on_rate_limit=True
    )

# --- UTILS ---
def clean_text(text):
    text = unidecode(text)
    text = text.replace("\n", " ").strip()
    if len(text) > 270:
        text = text[:267] + "..."
    return text

def valid_image(url):
    # filtre: logo veya site adı içeren görselleri atla
    bad_kw = ["logo", "banner", "haber", "7com", "cnn", "ntv", "tv", "watermark"]
    return not any(k in url.lower() for k in bad_kw)

def fetch_latest_tweet_from_users(limit_each=3):
    cl_ro = get_ro_client_v2()
    users = []
    with open("sources.txt") as f:
        users = [x.strip().replace("@", "") for x in f if x.strip()]

    tweets = []
    ids_resp = cl_ro.get_users(usernames=users)
    if not ids_resp.data:
        print("Kullanıcılar bulunamadı.")
        return []

    for u in ids_resp.data:
        tws = cl_ro.get_users_tweets(
            id=u.id,
            max_results=limit_each,
            expansions="attachments.media_keys",
            media_fields="url"
        )
        if not tws.data:
            continue

        for t in tws.data:
            txt = clean_text(t.text)
            media_url = None
            if hasattr(tws, "includes") and "media" in tws.includes:
                for m in tws.includes["media"]:
                    if m.type == "photo" and valid_image(m.url):
                        media_url = m.url
                        break
            tweets.append({"text": txt, "media": media_url})
    return tweets

def fetch_rss_items(limit=5):
    urls = []
    with open("rss_sources.txt") as f:
        urls = [x.strip() for x in f if x.strip()]
    items = []
    for url in urls:
        try:
            r = requests.get(url, timeout=10)
            soup = BeautifulSoup(r.content, "xml")
            for item in soup.find_all("item")[:limit]:
                title = clean_text(item.title.text)
                desc = clean_text(item.description.text if item.description else "")
                link = item.link.text if item.link else ""
                if fuzz.ratio(title, desc) < 70:
                    text = f"{title} — {desc[:150]}"
                else:
                    text = title
                items.append({"text": text, "link": link})
        except Exception as e:
            print("RSS error:", e)
    return items

def post_tweet(client, text, media_url=None):
    try:
        if media_url:
            img = requests.get(media_url, timeout=10)
            with open("temp.jpg", "wb") as f:
                f.write(img.content)
            media = client.media_upload(filename="temp.jpg")
            client.create_tweet(text=text, media_ids=[media.media_id])
        else:
            client.create_tweet(text=text)
        print("✅ Tweet gönderildi:", text[:60])
    except Exception as e:
        print("Tweet hatası:", e)

def main():
    cl = get_client_v2()
    print("🔍 Twitter hesaplarından veri çekiliyor...")
    tweets = fetch_latest_tweet_from_users(limit_each=2)
    print("📰 RSS kaynakları taranıyor...")
    news = fetch_rss_items(limit=3)

    all_posts = tweets + news
    if not all_posts:
        print("Hiç içerik bulunamadı.")
        return

    for post in all_posts[:5]:
        post_tweet(cl, post["text"], post.get("media"))

if __name__ == "__main__":
    main()
