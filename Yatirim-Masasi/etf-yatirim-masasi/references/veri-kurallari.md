# Kaynak ve hesaplama disiplini

## Kaynak seçimi

| Alan | Öncelikli kaynak | Kontrol |
|---|---|---|
| Fon kimliği, pay sınıfı, TER, dağıtım, hedge | İhraççı ürün sayfası, factsheet, KID, prospectus | ISIN ve belge sürümü aynı mı? |
| Sepet ve ağırlıklar | İhraççının tarihli tam holdings dosyası | Tam sepet mi, yalnız ilk 10 mu? |
| Endeks | Resmi endeks sağlayıcısının metodolojisi | Ağırlık sınırı, seçim, yeniden dengeleme, lisans değişimi |
| NAV, AUM, fon akışı | İhraççı ve tanımı açık veri sağlayıcısı | Fon mu pay sınıfı mı? Para birimi ve tarih? |
| Piyasa fiyatı ve spread | Borsa veya erişilebilir fiyat sağlayıcısı | Borsa, saat, kapanış/gecikme, bid/ask |
| Büyüme, enflasyon, istihdam | BLS, BEA, ECB, Eurostat, resmi istatistikler | Dönem, mevsimsellik, öncü/nihai veri, revizyon |
| Politika, faiz, kredi, finansal koşullar | Merkez bankası, US Treasury, FRED ve asıl seri sahibi | Seri tanımı, tarih, faiz birimi |
| Sektör ekonomisi | Şirket raporları, resmi sektör/enerji verileri | Fonun gerçek maruziyetine etkisi |
| Haber | Doğrudan şirket/fon açıklaması; güvenilir haber kaynağı | Olay tarihi ve haber tarihi ayrı mı? |

Fon arama siteleri evren keşfinde kullanılabilir; kritik ürün özelliğini mümkünse resmi belgede doğrula. Aynı haberi aktaran beş site beş bağımsız kanıt değildir. İhraççı tema araştırmasının pazarlama bağlamını hesaba kat.

## Bir veri kaydının asgari alanları

`source_id`, başlık/URL veya yerel dosya, yayımlayan, `observed_at`, `published_at`, `retrieved_at`, birim/para birimi, fon/seri kimliği, veri türü, kapsam ve sınırlama.

Tür: `gerçek`, `kaynaklı tahmin`, `hesaplama`, `çıkarım`, `bilinmiyor`.

Veri güveni: `yüksek`, `orta`, `düşük`, `değerlendirilemiyor`; nedenini yaz. Güven bir kazanma olasılığı değildir.

## Güncellik

Çalıştırma anındaki tarihi ve `Europe/Berlin` saat dilimini kullan. ABD etkinliklerini `America/New_York`, Türkiye saatlerini `Europe/Istanbul` üzerinden çevir; sabit saat farkı varsayma.

Uzun vadeli raporda en son tamamlanmış ortak işlem günü yeterlidir. Canlı fiyat arayışı analizi durdurmasın. Tatil ve yaz saati farklarını dikkate al. Makro seri son yayın dönemine; holdings ise ihraççının yayın takvimine göre değerlendirilir. Aylık veriyi günlük olmadığı için otomatik geçersiz sayma. Son önemli olaydan önceki verinin bunu kapsamadığını belirt.

Web yoksa: sağlanan belgelerin tarihlerine dayanan bir değerlendirme veya boş şablon üret; bugünün fiyatı, en iyi fonu veya güncel sıralaması gibi sunma.

PDF sayfa görüntüsü/OCR tablolarında sütun kayması, ondalık, eksi işareti ve bps kontrolü yap. Kritik sayı belirsizse sayfa görüntüsünden doğrula veya sayıyı kullanma. Tarihli örnek rapor, bugün için doğrulanmış piyasa verisi değildir.

## Karşılaştırılabilirlik

- Bir UCITS fonun fiyatı yerine ABD benzerinin fiyatını koyma.
- EUR borsa kotasyonu ekonomik döviz riskinin hedge edildiğini göstermez. İşlem, fon baz ve alttaki varlık para birimlerini ayrı yaz.
- Hedge'li ve hedge'siz pay sınıflarını aynı ekonomik sonuç sayma.
- Birikimli/dağıtan sınıfları toplam getiri üzerinden kıyasla. Dağıtım oranı getiri değildir; dağıtımın sermayeden gelme ihtimali ayrıca incelenir.
- Aynı dönem, para birimi ve gross/net total return tanımı kullan. Döviz dönüşümü için yönü ve FX gözlem tarihini göster.
- AUM değişimini net giriş diye etiketleme: fiyat ve kur etkileri de AUM'yi değiştirir. Oluşturma/geri alma verisi yoksa akışı `bilinmiyor` yaz veya açık varsayımlı tahmin de.
- Tracking difference = seçilen tanımla fon toplam getirisi eksi aynı bazdaki endeks toplam getirisi. Tracking error = aktif getiri serisinin oynaklığı. Birbirine karıştırma.
- TER ile tracking difference'ı bağımsız iki masraf gibi toplayıp aynı gideri iki kez sayma. Komisyon, spread ve kur maliyeti ayrı uygulama kalemleridir.
- Portföy P/E'sini hisse P/E'lerinin basit aritmetik ortalamasıyla üretme; zararlı şirket ve kapsam yöntemini kaydet. Analist al tavsiyesi sayısı, kâr tahmini revizyonu değildir.

## Formüller

Yüzdeleri hesapta ondalık, sunumda yüzde kullan; eksik değer sıfır değildir.

- Aynı baz toplam getiri serisi: `R = TR_son / TR_ilk - 1`.
- Yıllık bileşik: `CAGR = (TR_son / TR_ilk)^(365.25 / gün_sayısı) - 1`; bir yıldan kısa dönem için yıllıklandırmayı açıkla, tercih etme.
- Benchmark farkı yüzde puan: `R_fon - R_benchmark`.
- Göreli servet artışı: `(1+R_fon)/(1+R_benchmark)-1`; yüzde puan farkından ayrı.
- Güncel drawdown: `değer / geçmiş_zirve - 1`. Maksimum drawdown için tüm seri gerekir. Nakit girişleri olan ham portföy toplamında bunu yatırım drawdown'ı diye sunma; akıştan arındırılmış seri kullan.
- Uzun, aynı kapsamdaki iki fiziksel sepetin örtüşmesi: `sum_i min(w_Ai, w_Bi)`. Yalnız ilk 10 mevcutsa alt sınırdır; ağırlıkları %100'e yeniden ölçekleme. Sentetik ETF'nin teminat sepeti ekonomik endeks maruziyeti olmayabilir.
- Portföy şirket maruziyeti: `sum_j (portföyde_ETF_j_ağırlığı × ETF_j_içinde_şirket_i_ağırlığı)`; kapsanmayan kısmı göster.
- Uygun hisse sepetinde basitleştirilmiş fiyat senaryosu: `(1 + EPS büyümesi) × (son P/E / ilk P/E) - 1`. Negatif/çok düşük kâr, sepet değişimi ve farklı değerleme ölçülerinde uygun olmayabilir; dağıtım, kur ve giderlerle toplam getiriye geçişi ayrıca açıkla.
- Hedge'siz tek yabancı para için EUR toplam getiri: `(1 + yabancı para toplam getirisi) × (1 + yabancı paranın EUR cinsinden değer değişimi) - 1`. Çok para birimli sepete tek FX varsayımını gerekçesiz uygulama; hedge edilen sınıfta korunma maliyeti ve tanımı farklıdır.

Bir fiyat hedefini, analitik puanı, tarihsel isabeti veya panel uzlaşmasını kazanma olasılığına dönüştürme. Getiri senaryosu ile yıl içi düşüş bandını ayır; yeterli veri yoksa hesaplanamıyor de. Aynı ekonomik şok aday ve benchmark için aynı varsayımla tanımlanmalı. Veri yokluğu için puanı sıfırlamak veya kalan ağırlıkları sessizce büyütmek yerine kapsamı ve belirsizliği göster.

Portföy değer değişimi ile yatırım kazancı için `references/tez-ve-portfoy.md` kurallarını uygula. Hipotetik senaryoları tahmin veya hedef gibi sunma; olasılıklar için dayanak yoksa sayısal olasılık atama.

## Yöntem kaynakları

Bu bağlantılar ürün seçimi değildir; her çalıştırmada fon belgeleri ayrıca alınır.

- [SEC ETF yatırımcı bülteni](https://www.investor.gov/introduction-investing/general-resources/news-alerts/alerts-bulletins/investor-bulletins-24): NAV/piyasa fiyatı, spread ve ürün belgeleri.
- [SEC fon maliyetleri bülteni](https://www.investor.gov/introduction-investing/general-resources/news-alerts/alerts-bulletins/investor-bulletins/mutual-fund-and-etf-fees-and-expenses-investor-bulletin): ücret ve uygulama maliyetleri.
- [FRED](https://fred.stlouisfed.org/), [BLS](https://www.bls.gov/), [BEA](https://www.bea.gov/), [ECB](https://www.ecb.europa.eu/), [Eurostat](https://ec.europa.eu/eurostat): ilgili makro seriyi ve güncel yayını bulmak için başlangıç noktaları.
