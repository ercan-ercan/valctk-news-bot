# === VALCTK — HABER FİLTRE & PUANLAMA AYARLARI ===

# Kaynak ağırlıkları (isteğe göre artır/azalt)
SOURCE_WEIGHTS = {
    "haber7.com": 1.0,
    "cnnturk.com": 1.0,
    "ntv.com.tr": 1.0,
    "hurriyet.com.tr": 0.9,
    "bbcturkce.com": 1.0,
    "sabah.com.tr": 0.9,
    "sozcu.com.tr": 0.9,
}

# Öne çıkar (boost) — geçerse ekstra puan
BOOST_KEYWORDS = [
    # Gündem
    "son dakika","deprem","afet","saldırı","patlama","ateşkes","OHAL","yargı","mahkeme",
    # Ekonomi/Finans
    "faiz","enflasyon","asgari ücret","vergi","bütçe","MB","Merkez Bankası","BDDK",
    "dolar","euro","altın","kur","zam","ÖTV","KDV",
    # Siyaset (etkisi yüksek)
    "cumhurbaşkanı","bakan","kabine","tbmm","seçim","diplomasi","nato","ab","abd",
    # Teknoloji (büyük platform/cihaz)
    "apple","iphone","ios","macbook","samsung","galaxy","google","meta","openai","yapay zeka","ai",
    # Spor (yüksek etki)
    "pfdk","tff","derbi","transfer","milli takım","Şampiyonlar Ligi","UEFA",
    "beşiktaş","fenerbahçe","galatasaray","Arda Güler",
]

# İzin verilen konu anahtarları (temel eşik için)
ALLOW_KEYWORDS = [
    # Gündem/olay
    "deprem","yangın","sel","fırtına","tahliye","kaza","soruşturma","tutuklandı","serbest bırakıldı",
    # Ekonomi
    "faiz","enflasyon","asgari ücret","vergi","dolar","euro","altın","bütçe","tasarı","meclis",
    # Siyaset (yüksek etki)
    "cumhurbaşkanı","bakan","kabine","kararname","yasa","tbmm","seçim","diplomasi","anlaşma",
    # Teknoloji
    "yapay zeka","ai","uygulama","güncelleme","özellik","gizlilik","veri ihlali",
    # Spor (yüksek etki)
    "pfdk","tff","transfer","milli takım","sakatlık","ceza","hakem","idman yasağı",
]

# Engelle — geldiyse direkt atla
BLOCK_KEYWORDS = [
    # Tık tuzağı / düşük değer
    "indirim","kampanya","çekiliş","kupon","bedava","fırsat","şoke eden","şok","tıklayın",
    "video için","galeri için","izleyin","fotoğraflar","bakın",
    # Yerel küçük asayiş / magazin
    "magazin","ünlü","sevgilisi","evlendi","boşandı","düğün",
    "sokak kavgası","kıskançlık","komşu tartışması",
    # Çok yerel/etkisiz
    "mahalle","sokak röportajı","ilginç anlar",
    # Belirsiz/asılsız
    "iddia edildi","görüntülendi","sosyal medyada gündem",
]

# Tekrarlı konu frenleyici (dakika cinsinden — aynı anahtar geçenleri tut)
DUP_WINDOW_MIN = 30

# Puanlama eşikleri
BOOST_WEIGHT = 1.0     # BOOST eşleşmesi başına ek puan
ALLOW_WEIGHT = 0.6     # ALLOW eşleşmesi başına puan
SOURCE_BONUS = 0.2     # Weight>1.0 ise bonus
MIN_SCORE = 1.2        # Bu puanın altı atlanır

# Tweet format kısıtları
MAX_TWEET_LEN = 280
MAX_LIST_ITEMS = 6

# Özet üslup bayrakları (model için rehber)
STYLE_HINT = (
    "Resmi-sade, kısa, bilgi odaklı yaz. Gereksiz bağlaç yok. "
    "Varsa alıntıyı tırnak içine al. Özel isimleri doğru yaz. "
    "Aynı konuda peş peşe post üretme."
)
# === /VALCTK AYARLARI ===
