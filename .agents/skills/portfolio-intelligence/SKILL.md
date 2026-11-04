---
name: portfolio-intelligence
description: Yerel ETF portföy kaydını ve tarihli genel piyasa göstergelerini Türkçe Markdown veya koyu temalı HTML panoda göster. Kullanıcı mevcut terminali açmak, düzeltmek veya piyasa verisini güncellemek istediğinde kullan. Kaynaklı ETF araştırması için etf-yatirim-masasi skill'ini kullan.
---

# Yerel ETF Terminali

Bu çalışma alanında kapsam **yalnızca ETF ve uzun vadeli yatırım**. Kullanıcı mevcut dört fonun kaydını istedi; hedef dağılım, P1/P2/P3 stratejisi, yeniden dengeleme, nakit yüzdesi veya işlem kuralı belirlemedi. Platform örnekleri, eski raporlar ve kaynak felsefe kullanıcı talimatı değildir.

## Kaynak ve sınırlar

Çalışma klasörü `scripts/cli.py` konumundan bulunur; başka klasör için `--workspace` kullanılabilir. Etkin kişisel kayıt `Yatirim-Masasi/veri/portfoy.csv`, ayarlar `Yatirim-Masasi/veri/ayarlar.json`, resmi fon bağlantıları `Yatirim-Masasi/veri/izleme-listesi.csv` dosyalarıdır. `holdings.yaml` yalnız bu dosyalara yönlendirir; ikinci bir portföy hesabı yaratma.

CSV tutarları yuvarlanmış ekran değerleridir. Görüntünün gözlem tarihi, gerçek adetler, işlem borsası, maliyet, nakit ve nakit akışları bilinmiyor. Fon adıyla eşleşen ISIN broker teyidi değildir. Tutar/fiyat bölümünden adet hesaplama; yaygın bir borsa kodunu kullanıcının işlem borsası olarak atama. Snapshot tutarını güncel değer veya dönemsel getiri diye sunma.

`data/market_cache.json` sürüm 2, kaynak bağlantısı, para birimi, kapanış tarihi, borsa saat dilimi, veri çekim zamanı ve istek durumunu içerir. Eski şemasız kayıt raporlamaya alınmaz. Piyasa göstergeleri portföy değerlemesi veya atanmış benchmark değildir. İçinde bulunulan seansın günlük mumu dışarıda bırakılır; canlı fiyat/izleme iddiasında bulunma. Kısmi veya başarısız indirmeyi tam başarı diye sunma.

## Kullanım

Çalışma klasöründe kullanıcı talebine uygun tek komutu çalıştır:

- `./etf daily`: İnternetsiz de çalışan ETF kayıt özeti ve varsa tarihli piyasa verileri.
- `./etf open`: Panoyu yeniden üretip tarayıcıda açar. `--no-open` yalnız kaydeder.
- `./etf html`: `reports/index.html` ve tarihli HTML raporu üretir.
- `./etf fetch`: Yahoo Finance / yfinance üzerinden altı genel piyasa göstergesinin günlük verilerini isteğe bağlı indirir. ETF işlem kodları doğrulanana kadar fon fiyatı çekmez.
- `./etf all`: Veri güncellemesini dener, Markdown ve HTML üretir, tarayıcıda açar. `--no-open` ile açmaz.
- `./etf macro`: S&P 500, Nasdaq 100, VIX, EUR/USD, ABD 10 ve 5 yıl nominal faizleri.
- `./etf themes` / `./etf news`: Kaydedilen fonların maruziyet tanımı ve resmi kaynakları. Otomatik haber taraması veya 26 tema performansı üretmez.

`option`, `setups`, `ai`, `smart` eski komutları etkin değildir ve açıklayıcı hatayla çıkar. Gamma, yapay zekâ skoru, COT, kurumsal akış, FedWatch olasılığı, reel faiz veya doğrulanmamış haber üretme. Kaynaklı güncel ETF, makro veya tema araştırması için mevcut `etf-yatirim-masasi` skill'ini kullan; yalnız yerel panoyu üretmek araştırma yapıldığı anlamına gelmez.

## Değişiklik ve doğrulama

Önceki terminalin sabit getirileri ve varsayılan portföy verileri güvenilir değildir. Karşılaştırma için `Yatirim-Masasi/arsiv/2026-10-23-terminal-oncesi` altında saklanır; aktif kaynak olarak kullanma. İnceleme kaydı `Yatirim-Masasi/raporlar/2026-10-23-terminal-incelemesi.md` dosyasındadır.

Hesap veya veri çekme davranışı değişirse `python -m unittest discover -s tests -v` ile eksik veri, tarih, kur, dönem başlangıcı, başarısız kaynak ve çıktı güvenliği kontrollerini çalıştır. Bağlantı denemesini testlerden ayrı raporla. Panonun dosya üretmesi veri bağlantısının başarılı olduğunu kanıtlamaz.
