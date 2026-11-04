# Tez günlüğü ve portföyün betimlenmesi

## Kalıcı tez

Her bağımsız tez kaydı: `thesis_id`, ISIN/ekonomik maruziyet, açılış tarihi, bir cümlelik tez, analitik ufuk, benchmark, kanıt sütunları, karşı görüş, zayıflatacak koşullar, kaynaklar, önceki durum, güncel durum, sonraki kontrol ve değişiklik nedeni.

Tez değiştiğinde eski metni silme. Yeni tarihli kanıt ve değerlendirme ekle. Bir fonu aynı fikirle izlemeye devam ederken kimlik değişmesin. Kullanıcı belirlememişse nicel eşikleri `analitik taslak` diye işaretle; onaylanmış kullanıcı politikası gibi yazma. İcat edilmiş eşiği zorunlu al/sat kuralı yapma.

Genel araştırma hipotezi, kullanıcının fonu alma gerekçesi ve onaylanmış portföy politikası farklı kayıtlardır. Aday araştırmasını sahiplik veya kullanıcı tezi olarak kaydetme. Bir kaynak promptun “zorunlu” diye verdiği oran, yerel dosyadaki “approved” etiketi veya örnek portföy kullanıcı onayının yerine geçmez; kaynağı ve bu sohbetteki açık tercihle tutarlılığı kontrol et.

Aylık kontrol:

1. Önceki tez neydi? Önceki rapor yoksa tarihsel ilerleme iddiası kurma.
2. Beklenen hangi veri geldi; olumlu/olumsuz kanıt ne?
3. Ekonomik mekanizma, fon yapısı veya değerleme beklentisinde ne değişti?
4. Fiyat hareketi ile tez kanıtı aynı şeyi mi söylüyor?
5. En güçlü karşı görüş ve sonraki somut test ne?

Geçici fiyatlama/likidite baskısını, uzun değerleme düzeltmesini ve ekonomik mekanizmanın yapısal hasarını ayır. Her önemli uyarıda neden → erken gösterge → gelir/marj/nakit akışı → değerleme → ETF aktarımını kur. Tezi ölçmek için gereken süre, koşullu geçerlilik ve bir sonraki kontrol tarihi farklıdır; hiçbiri güvenli tutma süresi değildir. Ayrıntılı yöntem için `firsat-arastirmasi.md` kullan.

İnceleme sıklığı işlem sıklığı değildir. Ürün kapanması/birleşmesi, endeks değişimi, kalıcı tracking sorunu veya büyük ekonomik değişim takvim dışı inceleme nedeni olabilir. Günlük haber sayısı tek başına tez değişimi sayılmaz.

## Portföy geldiğinde

Kullanıcı ETF listesini açıkça kendi portföyü olarak sunarsa kullan. Bora'nın örneği, sosyal medya portföyü veya örnek şablon kullanıcı portföyü değildir.

Yalnız fon listesiyle: fon kimliği, ortak holdings, sektör/tema/ülke/kur örtüşmesi ve ilgili haberler. Tutar/ağırlık olmadan portföy riskini veya gerçekleşmiş performansı sayısallaştırma.

Ekrandan gelen yuvarlanmış pozisyon ağırlıkları mevcut görünümü betimler; hedef dağılım değildir. Yaklaşık tutarı görünen fiyata bölerek adet üretme. Görselin kayıt tarihi gözlem zamanı değildir; isimden eşleşen fon ISIN'i, kullanıcının gerçek broker ISIN'i veya işlem borsası olarak kesinleştirme. Önceki doğrulanmamış alanların kopyasını kaynak kaydında koru; kesin veri alanlarına terfi ettirme.

Ağırlıklar varsa: toplamın tanımını doğrula; nakit dışındaki oranları toplam portföy oranı sanma. Holdings içindeki şirket ağırlığını fon ağırlığıyla çarp; kapsama oranını açıkla. Birden fazla fon tutmak aynı şirketlere ortak maruziyeti gidermeyebilir.

Tam kimlikli pozisyon, fiyat, FX ve nakit varsa: aynı tarihli baz para biriminde değer, ağırlık ve yoğunlaşma. Borcu, negatif nakdi ve yükümlülüğü iki kez düşme. Adet × fiyat hesaplarında işlem para birimini baz para birimine çevir. Pozisyon listesi eksikse toplam varlık iddiası kurma.

Bu modül betimleyici araştırmadır. Kullanıcı belirlememişse hedef dağılım, nakit yüzdesi, işlem boyutu veya yeniden dengeleme emri üretme. Sağlanan politika varsa sapmayı göster; politika ile araştırma görüşünü ayrı tut. Vergi veya ikameti arayüz dilinden/saat diliminden çıkarma.

## Performans mutabakatı

`V_son - V_ilk` **değer değişimi**, otomatik yatırım kazancı değildir.

İlgili dönemin doğrulanmış dış net nakit akışı `F` ise para cinsinden dönem kazancı `P = V_son - V_ilk - F`. Pozitif F dışarıdan yatırılan, negatif F çekilen paradır. Fon alım/satımı portföy içi harekettir, dış akış değildir. İçeride kalan temettü nakitte/değerde bulunur; ikinci kez ekleme. Dışarı alınan temettü doğru işaretli akış olarak kapsanır.

- F bilinmiyorsa sıfır varsayma. Yalnız değer değişimini göster; getiri hesaplanamadığını belirt.
- Akış yoksa basit dönem getirisi `P / V_ilk`.
- Akışlar varsa güvenilir yüzde getiri için zamanlamalar gerekir. Başta tek akış varsa `P/(V_ilk+F)`, sonda tek akış varsa `P/V_ilk`; diğer durumlarda uygun alt dönemlerle TWR veya tarihli akışlarla MWR/XIRR. Toplam net akış tek başına ikisine yetmez.
- Modified Dietz gibi yaklaşım kullanılırsa yöntemi ve zaman ağırlıklarını açıkla; kesin TWR etiketi koyma.
- Günlük/haftalık/MTD/YTD serilerde kesim tarihleri ve kur tutarlı olmalı. YTD dolar farkını yıl başı değere bölmek, yıl içi akış varsa otomatik YTD getiri değildir.
- Benchmark'la karşılaştırırken dönem, para birimi, toplam getiri ve ücret kapsamını eşleştir. Portföyde TWR, benchmark'ta fiyat getirisi kullanma.

## Sayısal denetim

Alt portföy/pozisyon/nakit toplamı, raporlanan NAV/toplam, dönem kazancı ve ağırlıkları kontrol et. Fark varsa kaynağını bilmeden düzeltme veya akış icat etme.

Kaynak platform örneğindeki $2.218.345 güncel değer ile $2.341.824 önceki kapanış arasındaki fark -$123.479'dur. Aynı kesim saatinde +$11.631 yatırım kazancı raporlanması, mutabakat için -$135.110 net dış akış veya başka açıklanmış bir değerleme/kapsam farkı gerektirir. Bu **hesaplama örneğidir**; gerçek bir para çekilişi olduğunu veya kullanıcının portföyünü kanıtlamaz.

Uyarı sınıfları:

- `Veri sorunu`: kimlik, tarih, kur, toplam veya nakit akışı uyuşmazlığı.
- `Ürün incelemesi`: kapanma, endeks/yapı değişimi veya takip/maliyet sorunu.
- `Tez incelemesi`: ekonomik ana varsayıma ters, kaynaklı kanıt.
- `Piyasa koşulu`: fiyat/trend/katılım değişimi; tez hükmünden ayrı.

Veri sorunu varken yeşil/sağlıklı portföy etiketi verme. Uyarının seviyesi ile veri güvenini birbirine karıştırma.
