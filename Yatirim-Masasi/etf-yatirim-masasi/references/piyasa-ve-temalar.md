# Günlük özet, makro ve tema takibi

## Günlük ETF özeti

Üst satır: rapor tarihi, kullanılan kapanış tarihi, veri durumu. Ardından:

1. **Bugünün anlamı:** Uzun vadeli araştırmayı değiştiren en önemli gelişme, 2–3 cümle.
2. **Makro:** Büyüme, enflasyon/faiz ve kredi/finansal koşulların ilgili değişimleri.
3. **Piyasa:** Geniş piyasa ile sektör/faktör performansı; yoğun endeks ile eşit ağırlık farkı varsa açıklaması.
4. **Tema ve fon haberleri:** Gerçek maruziyeti olan temalar, ekonomik mekanizma ve etkilenebilecek ETF'ler.
5. **Tez kontrolü:** Varsa önceki araştırmaya göre güçlenen/zayıflayan kanıt. Yeni bulgu yoksa bunu yaz.
6. **Sonraki kontrol:** Doğrulanmış önemli yayın/olay ve neden önemli olduğu.

Portföy sağlanmamışsa piyasa ve izleme listesi düzeyinde kal. Aynı olayı makro, tema ve haber bölümlerinde yeni kanıtmış gibi tekrar sayma. Günlük hareket küçükse uzun rapor gerektirme.

Platform modüllerini ETF görevine göre kullan: Daily Summary sentez; Macro ekonomik zemin; MarketPulse katılım/göreli güç; ThemePulse/RotationPulse ekonomik maruziyet ve rotasyon; AiPulse yalnız ilgili temada değer zinciri; SmartMoney doğrulanabilir ETF akışı; PortNews fon ve önemli holdings haberi. Porttech/Protect karşılığı, veri/ürün/tez uyarılarıdır. Kaynak şablondaki tüm modüller her gün zorunlu değildir. Mevcut fon listesi varsa her önemli gelişmenin hangi fonun hangi maruziyetine dokunduğunu belirt; ağırlık/kapsam yoksa etki yüzdesi çıkarma.

## Makro modülü

Makro → şirket ekonomisi → endeks/sepet → ETF toplam getiri ve risk aktarımını açıkla. Tek göstergeden bütün piyasa rejimi çıkarma.

Çekirdek sorular:

- Büyüme hızlanıyor mu; öncü göstergeyle gerçekleşen veri tutarlı mı?
- Enflasyon ve reel faiz, değerlemeyi/finansman maliyetini nasıl etkiliyor?
- İstihdamdaki yavaşlama tek yayın mı, revizyonlarla devam eden bir eğilim mi?
- Kredi spread'leri ve finansal koşullar hisse hareketini doğruluyor mu?
- Petrol, kur veya politika değişimi hangi sepetin gelirini/maliyetini etkiliyor?

Coğrafyaya göre ECB/Avrupa, ABD, Japonya ve diğer ilgili ekonomileri dahil et. Kaynak örnekleri ABD ağırlıklı olsa da araştırmayı otomatik ABD/AI ile sınırlama.

Uzun dönem ekonomik zemin, güncel finansal/piyasa koşulu ve katılım üç ayrı değerlendirmedir. Kaynak prompttaki dealer gamma katmanını ETF uzun vade moduna otomatik taşıma. Gösterge tablosunu soruya göre faiz/reel faiz, eğri, kredi, büyüme, enflasyon, kur ve ilgili emtia ile kur; tüm kaynak listesini doldurma zorunluluğu yok. Faiz düşüşünün dezenflasyon mu talep bozulması mı olduğunu sorgula. Erişilebilir politika olasılıkları beklentidir, merkez bankası kararı değildir; veri yoksa olasılık üretme.

`Destekleyici`, `seçici`, `kırılgan`, `stresli` gibi nitel durum kullan; iki veya daha fazla farklı kanıt alanını ve karşı kanıtı göster. Özel 3.9/10 veya 65/100 gibi kaynak platform puanlarını yeni sisteme taşıma. Net likidite gibi türetilmiş proxy'leri tek başına nedensel piyasa motoru sayma.

Etkinlik tablosu gerekiyorsa: tarih/saat, veri, gözlem dönemi, resmi takvim kaynağı, önceki değer, erişilebiliyorsa beklenti, ETF'ye aktarım. Beklenti yoksa uydurma. Süresi geçmiş etkinliği gelecek takvime koyma.

## Piyasa ve rotasyon

Kapsamı ve benchmark'ı önce belirle. Uzun vade için 1/3/6/12 aylık toplam getiri ve varsa 3/5 yıllık bağlam kullan; günlük hareketi ek bağlam yap. Ortak tarih, para birimi ve pay sınıfı gerekir. Veri yoksa tablo hücresini boş/bilinmiyor bırak.

Göreli gücü örneğin 12 aylık benchmark getiri farkı; ivmeyi son 3 ay getiri farkının önceki 3 aya değişimi olarak tanımlayabilirsin. Seçilen tanım ve pencereler görünür olsun. Uzun tarih yoksa sınıflandırmayı zorlamadan kapsamı belirt.

| Durum | Analitik anlam |
|---|---|
| Lider, güçleniyor | Göreli güç ve tanımlanan ivme pozitif |
| Lider, yavaşlıyor | Göreli güç pozitif, ivme negatif |
| Geride, toparlanıyor | Göreli güç negatif, ivme pozitif |
| Geride, zayıflıyor | Her ikisi negatif |

Sıfır çevresinde belirsizliği belirt; dört bölgeye zorla dağıtma. Bu şema özgün bir betimleme yöntemidir, platformun özel RotationPulse algoritması veya kanıtlanmış sinyal değildir. Hacmi fon net akışı diye sunma. Trend/momentum, gelecekteki kâr veya gerçek fiziksel darboğazın kanıtı değildir.

50/200 günlük ortalama ancak yeterli temiz seri varsa ek bağlam olabilir. Ortalamanın altına inmek otomatik satış, üstüne çıkmak uzun vadeli tezin doğrulanması değildir. RSI, gün içi seviye, stop ve opsiyon vadeleri varsayılan rapora girmez.

## Tema ekonomisi: AI dahil

Tema haritası: talep kaynağı → değer zinciri → ekonomik darboğaz → fiyatlama gücü → gelir/marj/nakit akışı → fonun holdings'i → mevcut değerlemede beklenti.

AI örneğinde compute, bellek, üretim ekipmanı, paketleme, ağ/optik, elektrik, şebeke, soğutma, yazılım/verimlilik ayrımı yapılabilir. Diğer temalarda da aynı mekanizma uygulanır; liste otomatik araştırma veya favori tema değildir.

Her temada şu ayrımları yap:

- Teknoloji yaygınlaşıyor olabilir; kârı hangi halka kazanıyor?
- Talep artışı, arz artışı ve rekabetle dengeleniyor mu?
- Müşteri capex'i satış ve serbest nakit akışına dönüşüyor mu?
- Fonun tema adı ile ekonomik gelir maruziyeti ne kadar örtüşüyor?
- Sepetin hangi kısmı ana tezi taşıyor; geri kalanı ne yapıyor?
- Büyümenin ne kadarı değerlemeye girmiş olabilir?

GPU kiralama, sipariş, teslim süresi veya kapasite gibi fiziksel veriler erişilemiyorsa bunu yaz; hisse momentumundan fiziksel kıtlık skoru üretme. Kaynak felsefedeki hayal gücünü, uzak olasılığı kesin baz senaryo yapmadan yeni ekonomik kategoriler sorgulamak için kullan.

Geniş tema taraması istendiğinde örnek menü: siber güvenlik/yazılım; sanayi/robotik/üretimin geri taşınması; savunma/uzay/LEO; sağlık/biyoteknoloji; EV/batarya/temiz enerji; bakır/kritik mineraller/nükleer; AI compute/özel çip/bellek/paketleme/EUV; ağ/fotonik; veri merkezi elektriği/şebeke/800VDC/soğutma. Ülke, bölge ve value/momentum/quality/small-cap gibi faktörleri ayrıca değerlendir. Kaynaktaki 26 tema sabit veya eksiksiz yatırım evreni değildir. Özel şirket, gelecekteki IPO veya ekosistem maruziyeti iddiasında doğrudan sahiplik/gelir bağını belgeyle doğrula; tema adından halka açıklık veya erişilebilir ETF varsayma.

Birden fazla fonun holdings'i az örtüşse bile ortak müşteri, faiz, kur, emtia veya CAPEX bağımlılığı olabilir. Sayısal hisse örtüşmesi ile ekonomik bağımsızlığı ayrı değerlendir. Ayrıntılı katalizör ve bozulma mekanizmaları gerektiğinde `firsat-arastirmasi.md` referansına geç.

## Akış ve haber

ETF sürümündeki SmartMoney: doğrulanabilir fon net giriş/çıkışı, AUM ve varsa sahiplik bağlamı. Haftalık/aylık eğilim tek günlük sayının önündedir. Fon akışı yatırımcı niyetini veya gelecek getiriyi kanıtlamaz. COT yalnız ilgili piyasa için yardımcı bağlam olabilir; gecikmeli vadeli pozisyonu ETF'nin sahibi veya yönlü nakit yatırımı sanma. Opsiyon primi ve dark-pool baskılarından uzun vadeli ETF sinyali üretme.

Haber kartı: olay/duyuru tarihi, kısa olgu, kaynak, ETF'ye doğrudan/dolaylı bağ, etkilenen sepet ağırlığı ve tarihi, ekonomik aktarım, ters görüş, izlenecek sonraki veri. Holding ağırlığı yoksa etkiyi sayısallaştırma. Şirketin haberde yalnız adının geçmesi ekonomik etki sayılmaz. Haberin tonu fiyat tahmini değildir; ücretli yazının tamamını okumuş gibi davranma.
