# 39Dakika — Dual Mod: Twitter hesaplarından repost + RSS (opsiyonel)
# pip: tweepy, requests, beautifulsoup4, lxml, rapidfuzz, unidecode, beautifulsoup4

import os, re, json, tempfile
from typing import List, Dict, Optional
from urllib.parse import urlparse
import requests
from lxml import etree
from bs4 import BeautifulSoup
import tweepy
from unidecode import unidecode

# ====== ENV / FLAGS ======
DRY_MODE = os.getenv("DRY_MODE", "false").lower() in ("1","true","yes")
ATTACH_OG_IMAGE = os.getenv("ATTACH_OG_IMAGE", "true").lower() in ("1","true","yes")
# Twitter secrets
TW_API_KEY      = os.getenv("TW_API_KEY")
TW_API_SECRET   = os.getenv("TW_API_SECRET")
TW_ACCESS_TOKEN = os.getenv("TW_ACCESS_TOKEN")
TW_ACCESS_SECRET= os.getenv("TW_ACCESS_SECRET")

# ====== FILES ======
RSS_FILE      = "rss_sources.txt"   # RSS listesi
ACCOUNTS_FILE = "sources.txt"       # Twitter kullanıcı listesi (@ opsiyonel)
STATE_FILE    = "state.json"        # {"posted": ["url_or_tweetid", ...]}

HEADERS = {"User-Agent":"Mozilla/5.0 (39DakikaBot/1.0)"}
TIMEOUT = 15

# ====== STATE IO ======
def load_state() -> Dict:
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"posted": []}

def save_state(state: Dict):
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    os.replace(tmp, STATE_FILE)

def read_lines(path: str) -> List[str]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return [l.strip() for l in f if l.strip() and not l.strip().startswith("#")]
    except FileNotFoundError:
        return []

def dedup_keep_order(seq: List[str]) -> List[str]:
    seen, out = set(), []
    for x in seq:
        if x not in seen:
            seen.add(x); out.append(x)
    return out

# ====== TWEEPY CLIENTS ======
def get_client_v2() -> tweepy.Client:
    return tweepy.Client(
        consumer_key=TW_API_KEY,
        consumer_secret=TW_API_SECRET,
        access_token=TW_ACCESS_TOKEN,
        access_token_secret=TW_ACCESS_SECRET,
        wait_on_rate_limit=True,
    )

def get_api_v1() -> tweepy.API:
    auth = tweepy.OAuth1UserHandler(TW_API_KEY, TW_API_SECRET, TW_ACCESS_TOKEN, TW_ACCESS_SECRET)
    return tweepy.API(auth, wait_on_rate_limit=True)

# ====== HTTP ======
def fetch(url: str) -> Optional[requests.Response]:
    try:
        r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        if r.ok and r.content:
            return r
    except Exception:
        pass
    return None

# ====== RSS PARSE ======
def parse_rss_items(xml_bytes: bytes) -> List[Dict]:
    items: List[Dict] = []
    try:
        root = etree.fromstring(xml_bytes)
    except Exception:
        return items

    rss_items = root.findall(".//item")
    atom_items = root.findall(".//{http://www.w3.org/2005/Atom}entry")

    if rss_items:
        for it in rss_items:
            title = (it.findtext("title") or "").strip()
            link  = (it.findtext("link") or "").strip() or (it.findtext("guid") or "").strip()
            desc  = (it.findtext("description") or "").strip()
            if title and link:
                items.append({"title": title, "link": link, "summary": desc})
    elif atom_items:
        for it in atom_items:
            title = (it.findtext("{http://www.w3.org/2005/Atom}title") or "").strip()
            link_el = it.find("{http://www.w3.org/2005/Atom}link")
            link = link_el.attrib.get("href", "").strip() if link_el is not None else ""
            summary = (it.findtext("{http://www.w3.org/2005/Atom}summary") or "").strip()
            if title and link:
                items.append({"title": title, "link": link, "summary": summary})
    return items

def gather_rss_candidates() -> List[Dict]:
    urls = read_lines(RSS_FILE)
    all_items: List[Dict] = []
    for u in urls:
        r = fetch(u); 
        if not r: continue
        all_items.extend(parse_rss_items(r.content))
    # uniq by link
    seen, uniq = set(), []
    for it in all_items:
        lk = it.get("link", "")
        if lk and lk not in seen:
            seen.add(lk); uniq.append(it)
    return uniq

# ====== TEXT HELPERS (rewrite RSS) ======
SPACE_FIX = re.compile(r"\s+")
PUNCT_FIX = re.compile(r"\s+([,.!?;:])")
QUOTES = {'“':'"', '”':'"', '’':"'", '‘':"'", '«':'"', '»':'"'}

BAD_END_TOKENS = {"ve", "ile", "gibi", "ancak", "fakat", "ama", "çünkü", "veya", "ya da", "vb", "vb."}
BAD_END_CHARS = {",", ":", ";", "—", "–", "-", "…", "“", "‘", "'", '"'}

def normalize_quotes(s: str) -> str:
    for k,v in QUOTES.items(): s = s.replace(k,v)
    return s

def clean_html_text(s: str) -> str:
    s = BeautifulSoup(s or "", "lxml").get_text(" ")
    s = normalize_quotes(s)
    s = SPACE_FIX.sub(" ", s).strip()
    s = PUNCT_FIX.sub(r"\1", s)
    return s

def ensure_period(s: str) -> str:
    s = s.strip()
    if not s: return s
    return s if s[-1] in ".!?" else s + "."

def is_complete_sentence(s: str) -> bool:
    if not s: return False
    s = s.strip()
    if s[-1] in BAD_END_CHARS: return False
    last = s.rstrip(".!?").split()[-1].lower() if s.split() else ""
    if last in BAD_END_TOKENS: return False
    if len(s) < 20 and " " not in s: return False
    if not (s[0].isupper() or s[0].isdigit()): return False
    return True

def split_sentences_tr(s: str) -> List[str]:
    parts = re.split(r"(?<=[.!?])\s+", s.strip())
    out = []
    for p in parts:
        p = p.strip()
        if not p: continue
        p = re.sub(r"http\S+", "", p).strip()
        out.append(p)
    return out

def too_similar(a: str, b: str) -> bool:
    A = set(unidecode(a.lower()).split())
    B = set(unidecode(b.lower()).split())
    if not A or not B: return False
    inter = len(A & B) / max(1, len(A | B))
    return inter >= 0.6

def strip_site_trailer(title: str) -> str:
    return re.sub(r"\s*\|\s*[^|]+$", "", title).strip()

def pick_title_speaker(title: str):
    if ":" not in title: return None
    left, right = title.split(":", 1)
    left = left.strip()
    right = right.strip().strip('"').strip("'")
    if 2 <= len(left.split()) <= 6 and left[0].isupper():
        return left, right
    return None

def trim_to_limit(text: str, limit: int = 240) -> str:
    if len(text) <= limit: return text
    cut = text[:limit-1].rsplit(" ", 1)[0].rstrip(",;:—–-")
    return (cut[:limit-1] + "…").rstrip()

def score_candidate(text: str) -> int:
    t = text.strip(); score = 0
    if is_complete_sentence(t): score += 5
    if 120 <= len(t) <= 240:   score += 3
    if t.count('"') + t.count("'") > 4: score -= 2
    if len([w for w in t.split() if w.isupper() and len(w) > 2]) > 2: score -= 2
    return score

def rebuild_without_repeated_name(text: str, speaker: str) -> str:
    parts = speaker.split()
    if len(parts) >= 2:
        name = parts[-2] + " " + parts[-1]
        text = re.sub(re.escape(name), "", text, flags=re.I).strip()
        text = SPACE_FIX.sub(" ", text)
    return text

def rewrite_rss(title: str, summary: str) -> str:
    t_raw = strip_site_trailer(clean_html_text(title))
    s_raw = clean_html_text(summary)
    t_raw = re.sub(r"^\s*(SON DAK[Iİ]KA[:\-–]?)\s*", "", t_raw, flags=re.I)

    candidates: List[str] = []

    sp = pick_title_speaker(t_raw)
    if sp:
        speaker, quote = sp
        q_sent = split_sentences_tr(quote)
        q_clean = ensure_period(q_sent[0] if q_sent else quote)
        base = trim_to_limit(f"{speaker}: {q_clean}")
        add = ""
        if s_raw and not too_similar(base, s_raw):
            s1 = [x for x in split_sentences_tr(s_raw) if is_complete_sentence(x)]
            if s1:
                st = rebuild_without_repeated_name(s1[0], speaker)
                if not too_similar(base, st):
                    add = " " + ensure_period(st)
        candidates.append(trim_to_limit((base + add).strip()))

    title_first = split_sentences_tr(t_raw)
    if title_first:
        t1 = trim_to_limit(ensure_period(title_first[0]))
        add = ""
        if s_raw and not too_similar(t1, s_raw):
            s1 = [x for x in split_sentences_tr(s_raw) if is_complete_sentence(x)]
            if s1 and not too_similar(t1, s1[0]):
                add = " " + ensure_period(s1[0])
        candidates.append(trim_to_limit((t1 + add).strip()))

    candidates.append(trim_to_limit(ensure_period(t_raw)))
    best = max(candidates, key=score_candidate)
    return best

# ====== IMAGE FILTERS ======
BLOCKED_DOMAINS = {
    "haber7.com", "cnnTurk.com".lower(), "cnnturk.com", "sozcu.com.tr",
    "onedio.com", "sondakika.com", "tv100.com", "haberturk.com", "ahaber.com.tr"
}
BLOCKED_HINTS = {"logo", "logotype", "banner", "watermark", "wm", "frame", "tv", "player"}

def is_blocked_image_url(url: str) -> bool:
    try:
        pu = urlparse(url)
        host = pu.hostname or ""
        host = host.lower()
        if any(d in host for d in BLOCKED_DOMAINS):
            path = (pu.path or "").lower()
            if any(h in path for h in BLOCKED_HINTS):
                return True
    except Exception:
        pass
    return False

def extract_og_image(url: str) -> Optional[str]:
    r = fetch(url)
    if not r: return None
    try:
        soup = BeautifulSoup(r.text, "lxml")
        og = soup.find("meta", attrs={"property":"og:image"}) or soup.find("meta", attrs={"name":"og:image"})
        if og and og.get("content"):
            img = og["content"].strip()
            if img.startswith("//"): img = "https:" + img
            if is_blocked_image_url(img):
                return None
            return img
    except Exception:
        pass
    return None

def download_temp(url: str) -> Optional[str]:
    try:
        rr = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        if rr.ok and rr.content:
            fd, path = tempfile.mkstemp(prefix="img_", suffix=".jpg")
            os.close(fd)
            with open(path, "wb") as f: f.write(rr.content)
            return path
    except Exception:
        pass
    return None

def try_upload_media(image_url: str) -> Optional[str]:
    if not image_url: return None
    try:
        path = download_temp(image_url)
        if not path: return None
        api = get_api_v1()
        up = api.media_upload(path)
        try: os.unlink(path)
        except Exception: pass
        return getattr(up, "media_id_string", None) or str(getattr(up, "media_id", ""))
    except Exception as e:
        print("[WARN] Medya yüklenemedi:", e)
        return None

# ====== TWITTER PULL (accounts) ======
def normalize_user(u: str) -> str:
    u = u.strip()
    if u.startswith("@"): u = u[1:]
    return u

def read_accounts() -> List[str]:
    users = [normalize_user(x) for x in read_lines(ACCOUNTS_FILE)]
    return [u for u in users if u]

def fetch_latest_tweet_from_users(limit_each: int = 3) -> Optional[Dict]:
    """
    accounts.txt listesinden en taze uygun tweet'i getirir.
    Öncelik: orijinal tweet (retweet/reply değil). Medya varsa +1.
    """
    users = read_accounts()
    if not users: 
        return None

    cl = get_client_v2()
    # usernames -> ids
    ids_resp = cl.get_users(usernames=users)
    if not ids_resp or not ids_resp.data:
        return None

    best = None
    for u in ids_resp.data:
        try:
            tweets = cl.get_users_tweets(
                id=u.id,
                max_results=min(5, limit_each*2),
                expansions=["attachments.media_keys", "entities.mentions.username"],
                tweet_fields=["created_at","text","referenced_tweets","entities"],
                media_fields=["url","preview_image_url","width","height","type"],
                exclude=["retweets","replies"],  # orijinal
            )
        except Exception as e:
            print("[WARN] get_users_tweets:", e)
            continue

        if not tweets or not tweets.data:
            continue

        media_lookup = {}
        if tweets.includes and "media" in tweets.includes:
            for m in tweets.includes["media"]:
                # sadece photo
                if getattr(m, "type", "") == "photo" and getattr(m, "url", None):
                    media_lookup.setdefault("keys", []).append(m.url)

        for tw in tweets.data:
            text = (tw.text or "").strip()
            # t.co linklerini temizle
            text = re.sub(r"https?://t\.co/\S+", "", text).strip()
            if not text:
                continue

            media_urls = media_lookup.get("keys", []) if media_lookup else []
            score = 1 + (1 if media_urls else 0)  # foto varsa daha iyi
            cand = {
                "kind": "tweet",
                "tweet_id": str(tw.id),
                "user": u.username,
                "text": text,
                "media_urls": media_urls
            }
            if (best is None) or (score > best.get("score", 0)):
                cand["score"] = score
                best = cand

    return best

# ====== TWEET SENDER ======
def post_tweet(text: str, img_url: Optional[str]) -> Optional[str]:
    if DRY_MODE:
        print("[DRY] Tweet atılacak (görsel={}):\n{}".format(bool(img_url), text))
        return "DRY"

    client = get_client_v2()
    media_ids = None
    if ATTACH_OG_IMAGE and img_url:
        mid = try_upload_media(img_url)
        if mid: media_ids = [mid]
        else:   print("[WARN] Görsel eklenemedi, metinle devam.")

    try:
        if media_ids:
            resp = client.create_tweet(text=text, media_ids=media_ids)
        else:
            resp = client.create_tweet(text=text)
        tid = getattr(resp, "data", {}).get("id")
        print(f"[OK] Tweet gönderildi. ID: {tid}")
        return tid
    except Exception as e:
        print("Error:", e)
        return None

# ====== MAIN FLOW ======
def choose_unposted_link(cands: List[Dict], posted: List[str]) -> Optional[Dict]:
    for it in cands:
        lk = it.get("link", "")
        if lk and lk not in posted:
            return it
    return None

def main():
    state = load_state()
    posted = state.get("posted", [])

    # 1) Önce Twitter hesaplarından uygun bir tweet bul
    tw = fetch_latest_tweet_from_users(limit_each=3)
    if tw and tw["tweet_id"] not in posted:
        # görsel: önce tweet fotoları; yoksa None
        img = None
        if ATTACH_OG_IMAGE and tw.get("media_urls"):
            # filtrele
            for u in tw["media_urls"]:
                if not is_blocked_image_url(u):
                    img = u; break
        tid = post_tweet(tw["text"], img)
        if tid:
            posted.append(tw["tweet_id"])
            state["posted"] = dedup_keep_order(posted)[-1000:]
            save_state(state)
            return

    # 2) Olmazsa RSS'ten al
    cands = gather_rss_candidates()
    if cands:
        it = choose_unposted_link(cands, posted)
        if it:
            text = rewrite_rss(it.get("title",""), it.get("summary",""))
            link = it.get("link","")
            img = None
            if ATTACH_OG_IMAGE:
                og = extract_og_image(link)
                if og and not is_blocked_image_url(og):
                    img = og
            tid = post_tweet(text, img)
            if tid:
                posted.append(link)
                state["posted"] = dedup_keep_order(posted)[-1000:]
                save_state(state)
                return

    print("[INFO] Uygun paylaşım bulunamadı (Twitter/RSS).")

if __name__ == "__main__":
    miss = [k for k in ("TW_API_KEY","TW_API_SECRET","TW_ACCESS_TOKEN","TW_ACCESS_SECRET") if not os.getenv(k)]
    if miss: print("[WARN] Eksik env:", miss)
    main()
