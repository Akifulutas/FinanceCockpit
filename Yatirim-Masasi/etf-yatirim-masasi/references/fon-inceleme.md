# ETF bulma, inceleme ve karşılaştırma

## Kimlik kartı

Tam ad, ISIN, pay sınıfı, ticker/borsa, işlem ve fon baz para birimi, domicile, UCITS durumu, Acc/Dist, hedge, başlangıç tarihi, ihraççı, aktif/pasif, endeks, fiziksel/sentetik yapı. Bir ticker belirsizse önce kimliği çöz; farklı ürünleri birleştirme.

Kullanıcının verdiği ISIN tek fonu kesin tanımlıyorsa gereksiz soru sorma. Kimlik belirsizliği sonucu değiştiriyorsa tek net soru sor; o sırada doğrulanabilen genel konu üzerinde ilerle.

## Üç ayrı değerlendirme

### 1. Fonun uygulama kalitesi

- TER/ongoing charges; pay sınıfı/fon AUM ayrımı; kapanma/birleşme duyurusu varsa kaynağı.
- Aynı tanımlı endekse tracking difference ve yeterli seri varsa tracking error.
- Replikasyon, örnekleme, swap/karşı taraf ve teminat, menkul kıymet ödünç politikası.
- Spread, NAV primi/iskontosu ve alttaki sepetin likiditesi. Tek borsadaki düşük hacmi tek başına likiditesizlik sayma.
- Metodoloji, yeniden dengeleme, yoğunlaşma sınırları, endeks değişimi ve aktif yönetimde süreç/turnover.

### 2. Ekonomik sepet ve tez

- Güncel holdings ve tarihi, ilk 10 ağırlığı, şirket/sektör/ülke/faktör/kur maruziyeti.
- Tema saflığı: fon adını değil gerçek gelir kaynaklarını kontrol et.
- Bir cümlelik ana tez; 2–4 ölçülebilir kanıt sütunu; karşı görüş ve tezi zayıflatacak veri.
- Kâr büyümesi, sermaye ihtiyacı, rekabet, döngüsellik, finansman ve değerleme beklentisi.
- Fon stratejisinin yapısal özelliğini, konjonktürel sektör görüşünden ayır.

Derin incelemede en büyük 10 şirketi ve toplam ağırlıklarını, kâr/nakit akışının asıl sürükleyicilerini, borç/yeniden finansman ve müşteri/tedarikçi bağımlılığını değerlendir. Analizin temsil ettiği sepet ağırlığını belirt. Kâr iyileşmesi ortalama/medyan şirkete yayılıyor mu, yoksa birkaç dev şirkette mi? Tam sepet yerine örnek şirketler inceleniyorsa kapsama sınırını yaz. Analist tavsiye dağılımını kâr tahmini revizyonu olarak kullanma.

Tahvil ETF'lerinde duration, vade, kredi kalitesi, faiz eğrisi, yield tanımı, temerrüt/likidite ve hedge öne çıkar. Hisse P/E kontrolünü buraya kopyalama. Aktif/çoklu varlık ETF'lerinde strateji ve gerçek varlık dağılımını incele.

### 3. Bugünkü beklenti ve piyasa bağlamı

- Aynı bazda 1/3/5 yıllık ve erişilebilen daha uzun toplam getiri, drawdown ve benchmark bağlamı.
- İlgili büyüme/değerleme varsayımlarının hangisi fiyatlanmış olabilir?
- Tez doğruyken düşük getiriye yol açabilecek mekanizma: fazla ödeme, arz/rekabet artışı, kur, maliyet, metodoloji sapması.
- Zayıf fiyat, döngüsel duraklama veya yapısal bozulma ayrımı.

Sonucu bu üç alanda ayrı yaz. İyi ürün, iyi tema ve cazip bugünkü fiyat farklı değerlendirmelerdir. Yeni fonda uzun geçmiş yoksa benchmark geçmişini fonun gerçekleşmiş sicili diye sunma; backtest, endeks ve fon dönemlerini ayır. Kapanmış fonların dışarıda kalması ve geriye dönük tema seçimi yanlılığını unutma.

Fiyatlanmış beklenti ve aday taramasında `firsat-arastirmasi.md` içindeki beklenti farkı, katalizör, senaryo ve ortak stres akışını kullan. Her basit fon kimliği sorusunda geniş tarama veya panel çalıştırma.

Fon kapanması, pay sınıfı birleşmesi, tek borsadaki kotasyonun kaldırılması ve endeks değişimi farklı olaylardır. İhraççı duyurusunda etkilenen ISIN, kot ve tarihi doğrula; kullanıcının işlem borsası bilinmiyorsa uygulanabilirliği belirsiz bırak. Güncel spread eksikliği ürün uygulama güvenini etkiler; sağlam ekonomik tezi tek başına reddetmez. Farklı saatli NAV/fiyattan eşzamanlı prim/iskonto hesaplama. Fonun gerçekleşmiş net getirisinden TER'i tekrar düşme.

## Geniş tarama

Önce ekonomik fırsatları karşılaştır; ardından onları taşıyan fonları bul. Geniş piyasa, sektör, faktör, ülke/bölge, piyasa büyüklüğü ve ilgili yeni temalar değerlendirilebilir. Mevcut dönemde güçlü kanıt varsa derinleş; popülerlik nedeniyle AI'ye öncelik verme.

Taranan gerçek fon sayısı, benzersiz ekonomik maruziyet sayısı, kaynak ve kapsam tarihini yaz. Kısmi taramayı bütün pazarın en iyileri diye sunma. Sayı doldurmak için finalist ekleme. Cazip veya yeterince kanıtlı aday yoksa bunu söyle.

## Karşılaştırma çıktısı

| Alan | Fon A | Fon B | Anlamı |
|---|---|---|---|
| ISIN / pay sınıfı | | | Ürün kimliği |
| Endeks ve gerçek maruziyet | | | Aynı yatırım fikri mi? |
| TER / tracking / spread | | | Maliyet ve uygulama kalitesi |
| Yoğunlaşma / örtüşme | | | Yeni fon gerçekten çeşitlendiriyor mu? |
| Acc/Dist / hedge / kur | | | Sonuçlar neden farklı olabilir? |
| Aynı baz toplam getiri / risk | | | Geçmiş bağlam; tahmin değil |
| Tez / ters görüş | | | Ekonomik fark |
| Veri tarihi / eksik alan | | | Sonuç ne kadar sağlam? |

Tabloyu yalnız ilgili satırlarla doldur. Her fon için güçlü yan, zayıf yan, araştırma durumu ve sonraki kanıtı belirt. Ağırlıklar ve yöntem kullanıcıdan gelmedikçe 100 puanlık skor veya kesin lig tablosu icat etme. Kullanıcı skor isterse bile tanımı/varsayımları görünür kıl; eksikleri sıfırla cezalandırma ve skoru kazanma olasılığına dönüştürme.

## Senaryolar

Uzun vadede büyüme, kârlılık, değerleme, kur ve maliyet mekanizmalarıyla iyimser/baz/zayıf koşulları tarif et. Nicel varsayımlar varsa bunları kaynağa veya açık senaryo kabulüne bağla. 10 yıllık kurum tahminini 12 aylık hedefe dönüştürme. Getiri garantisi, güvenli minimum tutma süresi veya kanıtsız hassas fiyat hedefi verme.
