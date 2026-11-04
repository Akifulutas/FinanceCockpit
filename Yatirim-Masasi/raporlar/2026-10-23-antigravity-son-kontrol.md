# Antigravity geliştirmesi — bağımsız kontrol, 23 Ekim 2026

Antigravity'nin eklediği fon kayıtları, araştırma kartları ve `research` komutu mevcut dosyalarda bulunuyor. Bildirdiği 22 testi bağımsız olarak yeniden çalıştırdım; geçti. Bu testler, kayıtlardaki finansal iddiaların doğruluğunu tek başına göstermiyor.

## Bulunan ve giderilen sorunlar

- **Yanlış referans kotasyonlar:** SPDR kaydında LSE için SPYI/ACWE, İtalya için SPYI ve SIX için SPYI/CHF yazıyordu. Resmi Eylül factsheet tablosuna göre LSE IMID/USD, İtalya IMIE/EUR ve SIX IMID/USD olarak düzeltildi. Paris IMIE/EUR eklendi; bu seçenekler kişisel broker teyidi değildir. [SSGA factsheet, sayfa 1](https://www.ssga.com/library-content/products/factsheets/etfs/emea/factsheet-emea-en_gb-spyi-gy.pdf).
- **iShares referansları:** EIMI fonunda Amsterdam EMIM/EUR; Momentum GBP hattı IWFM; Value GBP hattı IWFV; ilgili SIX satırları USD olarak düzeltildi. [EIMI Listings](https://www.ishares.com/uk/individual/en/products/264659/ishares-msci-emerging-markets-imi-ucits-etf), [Momentum Listings](https://www.ishares.com/uk/individual/en/products/270051/ishares-msci-world-momentum-factor-ucits-etf), [Value Listings](https://www.ishares.com/uk/individual/en/products/270048/ishares-msci-world-value-factor-ucits-etf).
- **Replikasyon etiketi:** İhraççı sayfalarının sınıflaması EIMI ve Value için Physical / Replicated, Momentum için Physical / Optimised. Bunlar kaynak terimleriyle kaydedildi; hepsine otomatik “optimize edilmiş” yazılmıyor. Kaynaklar yukarıdaki ürün sayfalarının Key Facts bölümleridir.
- **Belge tarihi:** Dört kaydın tamamına yazılan 30 Eylül tarihi, iShares ürün sayfasının genel yayın tarihi olarak doğrulanamadı. Gün bilinmiyorsa boş bırakıldı; kaynak bölüm ve gerçek erişim zamanı ayrıca kaydedildi. SSGA kaynağı KIID yerine kotasyon tablosunu içeren factsheet olarak işaretlendi. Eylül 2026 belge dönemiyle tam gün birbirine karıştırılmadı.
- **Eksik bilgi dosyası:** Katalog silindiğinde kod dört fon için yine USD ve hedge yok bilgisi üretiyordu. Bu davranış geçici bir çalışma klasöründe yeniden üretildi ve düzeltildi. Eksik/bozuk katalogda alanlar bilinmiyor kalır ve uyarı verilir. Sabit “ihraççı teyitli” iddiaları kaldırıldı.
- **Bozuk araştırma:** Geçerli JSON içindeki `funds: [null]` raporu AttributeError ile çökertiyordu. Tür ve kaynak URL denetimleri eklendi. Araştırma seçimi dosya adından ziyade içeriğin tarihine göre yapılır; geçerli eski kayıt bozuk yeni dosya yüzünden kaybolmaz. Gelecekteki üretim zamanı reddedilir.
- **Tarih ve doğrulama ayrımı:** Bugünün tarihini taşıyan bir dosya artık tek başına içerik doğrulaması anlamına gelmiyor. Doğrulama durumu ayrıca gösteriliyor.
- **Kotasyon duyurusu:** Value ürün sayfası 15 Aralık 2026'da bir kotasyon hattının kaldırılacağını belirtiyor. Bu kontrolde yönlendirilen belge kütüphanesinden etkilenen borsa belirlenemedi. “İkincil borsalar kapanıyor, ana hatlar devam ediyor” genellemesi kaldırıldı; kullanıcı hattına etkisi belirsiz kaldı. [İhraççı duyurusu](https://www.ishares.com/uk/individual/en/products/270048/ishares-msci-world-value-factor-ucits-etf).

## Araştırma içeriğinin sınırı

Bazı MarketScreener, Euronext ve AP bağlantıları kullanılan web aracında açılamadı. Bu, haberlerin yanlış olduğunu kanıtlamaz; bu kontrolde yeniden doğrulanamadıkları anlamına gelir. Eski metindeki PMI, Meta CAPEX, petrol/dolar ve %4,20 tahvil seviyesi iddiaları etkin araştırmada olgu olarak kullanılmadı. Tam metin yedekte korunuyor.

Etkin araştırma **doğrulama kısıtlı** olarak işaretlendi. [16 Eylül Fed kararı](https://www.federalreserve.gov/newsevents/pressreleases/monetary20260916a.htm) ve [10 Eylül ECB kararı](https://www.ecb.europa.eu/press/pr/date/2026/html/ecb.mp260910~314e508016.en.html) tarihleriyle veriliyor; güncel günlük haber taraması yapıldığı iddia edilmiyor. Makro kaynakları artık kart üzerinde de görünür.

Value'ın yalnız bankacılık/enerji fonu gibi anlatılması da kaldırıldı. Resmi 22 Ekim sektör tablosunda bilgi teknolojisi %31,50, finansallar %15,52 ve enerji %4,29. Önceki döneme göre rotasyon veya katkı hesabı yapılmadı. [İhraççı sektör tablosu](https://www.ishares.com/uk/individual/en/products/270048/ishares-msci-world-value-factor-ucits-etf).

## Yeni gönderilen fiyat / makas çıktısı

7–21 Ekim 2026 aralığındaki kullanıcı çıktısından 11 ISIN için 77 satır, yedi gözlem grubu ve altı tarih ayrıştırıldı. Fiyat ve tablo alınma zamanı ayrı kaydedildi. En büyük gözlem yaşı GRID için yaklaşık 59,30 dakika. Kaynakta borsa belirtilmiyor; kullanıcı etiketleri borsa teyidi sayılmadı. Mevcut portföy dört fon olarak korunuyor.

Özgün `jq` ifadesinde `false // "N/A"` ifadesi N/A döndürür. Bu nedenle geçmiş satırların güncellik bayrağı sonradan false olarak tamamlanmadı; bilinmiyor tutuldu. Null ile false'u ayıran düzeltme [tarihsel fiyat / makas raporunda](2026-10-23-tarihsel-fiyat-makas.md) yer alır. Broker komutu çalıştırılmadı; yalnız verilen metin işlendi.

## Doğrulama ve koruma

22 mevcut teste 9 terminal ve 3 kotasyon aktarımı kontrolü eklendi; toplam **34 test geçti**. Gerçek kaynak kontrolü test çalıştırmasından ayrı yapıldı. HTML ve Markdown aynı veri paketinden yeniden üretildi. Antigravity'nin masaüstü/mobil/PDF görsel doğrulama iddiaları bu oturumda bağımsız olarak tekrarlanmadı.

Değişiklik öncesi dosyalar `Yatirim-Masasi/arsiv/2026-10-23-antigravity-kontrol-oncesi/` altında SHA-256 manifestiyle korunuyor. Kişisel adet, maliyet, nakit, dağılım hedefi veya getiri eklenmedi. Araştırma CSV/JSON dosyaları `veri/arastirma-kotasyonlari/` altında; bunlar etkin portföy veya kalıcı izleme listesi değildir.
