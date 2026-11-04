# ETF terminali incelemesi — 23 Ekim 2026

Antigravity'nin kısa komutları ve yerel pano fikri kullanılabilir. Ancak önceki sürümde doğrulanmamış portföy girdileri ve sabit piyasa yorumları, hesaplanmış güncel sonuçlar gibi gösteriliyordu. Bu nedenle önceki rapor yatırım kararında güvenilir bir veri kaynağı değildi. Etkin sürüm, kullanıcının seçtiği ETF ve uzun vade kapsamına uyarlandı.

## Bulgu ve düzeltmeler

| Önceki davranış | Kanıt / sorun | Etkin sürüm |
|---|---|---|
| Haftalık ve aylık portföy getirisi | Eski `engine.py:213–214`: günlük getiriden `×1.5−2.1` ve `×2.2−6.5` formülleri. Bunlar tarihsel getiri değil. | Değer serisi ve nakit hareketleri olmadan getiri üretilmiyor. |
| Yıllık, başlangıçtan beri ve zirveden getiri | Eski `holdings.yaml`: €10.000 başlangıç, €10.200 yıl sonu, €10.500 zirve, €10.100 önceki kapanış ve sıfır nakit. Kullanıcı bunları paylaşmadı. | Bu girdiler etkin kaynaktan kaldırıldı. Nakit ve performans bilinmiyor. |
| Pozisyon adetleri ve maliyetleri | Görüntüden doğrulanamayan kesirli adetler ve alış fiyatları kullanılmıştı. | Etkin kaynak mevcut CSV. Gerçek adet/borsa/maliyet boş kalıyor; ekran tutarıyla yeni değerleme yapılmıyor. |
| Core / Factor / Emerging alt portföyleri | Kullanıcının onaylamadığı yaklaşık %42/%35/%23 hedefleri ve yatırım tezleri girilmişti. | Hedef, alt portföy politikası ve yeniden dengeleme kuralı uygulanmıyor. Dört fon ayrı gösteriliyor. |
| Momentum fonu kimliği | Eski YAML'da `IE00BP3QZ824` vardı. | Mevcut, resmi ürün adıyla eşleştirilmiş kayıt `IE00BP3QZ825`. Broker teyidi hâlâ bekliyor. |
| Makro skorlar | İklim 3,9; genişlik 65; FedWatch olasılıkları sabitti. Reel faiz için 10 yıldan sabit 2,30 çıkarılıyordu. 10–5 yıl farkı 10–2 yıl diye adlandırılmıştı. | Kaynağa dayanmayan skor/olasılıklar kaldırıldı. ABD 10 ve 5 yıl **nominal** faizleri doğru adla, değişimleri baz puanla gösteriliyor. |
| Gamma, AI, COT ve akış | Gamma seviyesi `SPY ×1.008`; AI skoru 52,2; net call primi −609 milyon gibi değerler sabitti. | Bu modüller etkin değil. Kaynak veya hesap yöntemi olmadan sayılar gösterilmiyor. |
| Haberler ve işlem fırsatları | META/NVDA/MU başlıkları ve AMZN/IBIT/META/PLTR giriş/stop/hedefleri kod içinde sabitti. | Sabit haber ve işlem kurulumları kaldırıldı. `news` resmi fon kaynaklarını gösterir; güncel haber araştırması ayrı skill görevidir. |
| 26 tema rotasyonu | Bazı temalar tek hisseyle temsil ediliyor, eksik veride sıfır değişim / olumlu trend oluşabiliyordu. | `themes` yalnız kayıtlı dört fonun maruziyet tanımını gösterir. Gerçek sepet örtüşmesi veya tema endeksi ölçüldüğü iddia edilmez. |
| Canlı fiyat / zaman | Günlük mumlar, zaman dilimi taşımayan tek saatle canlı ve TSİ diye sunuluyordu. | Kapanış tarihi, borsa saat dilimi, kaynak ve çekim zamanı ayrı kaydediliyor. Rapor saati Europe/Berlin. İçinde bulunulan seansın mumu dışarıda bırakılır. |
| Veri indirme hataları | Eksik kapsamla da başarı mesajı verilebiliyordu. Eski kayıt ezilebiliyordu. | Başarı kapsamı 0–6 olarak raporlanır. Hata halinde önceki geçerli kayıt korunur ve eski olarak işaretlenir. Kısmi indirmede çıkış kodu başarısızdır. |
| Pano açma | Mevcut HTML varsa tekrar üretilmiyordu. | `open` her çağrıda mevcut kayıttan raporu yeniden üretir. |

## Şu an güvenle kullanılan kayıt

Gönderilen ekran başlığı **€10.000,00**. Görünen dört satırın yuvarlanmış toplamı **€10.000,00**; fark **€0,00**. Paylar bu satır toplamından hesaplanıyor. Görüntünün çekim zamanı bilinmiyor; 23 Ekim kayıt tarihi fiyat tarihi olarak kullanılmıyor. İşlem borsası ve fon adetleri tahmin edilmiyor. Ekran tutarı güncel hesap değeri diye sunulmuyor.

Etkin veri dosyaları:

- `Yatirim-Masasi/veri/portfoy.csv`
- `Yatirim-Masasi/veri/ayarlar.json`
- `Yatirim-Masasi/veri/izleme-listesi.csv`

Kökteki `holdings.yaml` bunlara yönlendiren bir nottur; ikinci bir bağımsız portföy yaratmaz. Kullanıcının bu dosyalardaki fon kayıtları ve tercihleri değiştirilmedi.

## Doğrulama

- Eksik adet/maliyet/nakit, para birimi uyuşmazlığı, eksik pozisyon tutarı, 5 seans hesabı, yıl/ay başlangıcı, faiz birimi, zaman dilimi, gelecekteki gözlem, eski veri, kısmi indirme, bozuk önbellek, HTML metin güvenliği, kapsam dışı komutlar ve yeniden raporlama için **19 test geçti**.
- İki skill dosyasının yapısal doğrulaması geçti.
- İlk kısıtlı bağlantı denemesinde alan adı çözülemedi; sonuç doğru biçimde 0/6 ve başarısız olarak raporlandı. İzinli bağlantı denemesinde **6/6 gösterge indirildi**. Kaydedilen gözlem tarihi 22 Ekim 2026; çekim 23 Ekim 2026 yaklaşık 17:13 UTC. Bu, fonların veya hesabın canlı değerlemesi değildir.
- HTML ve Markdown aynı veri paketinden üretilir. Panonun tarayıcıda görsel doğrulaması tamamlanamadı: uygulamanın URL politikası yerel `file:` adresini reddetti. Tarayıcı kısıtı başka bir yoldan aşılmadı. Masaüstü ve dar ekran düzenleri bu oturumda görsel olarak doğrulanmış sayılmaz.
- Kullanıcının aktardığı Antigravity `INTERNAL (500)` hatası bu yerel dosyalarda yeniden üretilemedi. Yerel terminalde bu hata kimliğini üreten bir model API çağrısı bulunmadı; hata giderildiği iddia edilmiyor.

## Kullanım

`Documents/ETF` içinde `./etf daily` kayıt özetini; `./etf open` panoyu açar. `./etf fetch` piyasa bağlamını günceller. `./etf all --no-open` güncellemeyi dener, Markdown ve HTML kaydeder. Ağ erişimi yoksa `daily` yine mevcut kaydı okuyabilir. `option`, `setups`, `ai`, `smart` etkin değildir.

Kaynaklı güncel ETF araştırması için sohbet çağrısı:

> $etf-yatirim-masasi Bugünkü ETF özetini hazırla

Mevcut fonların güncel değerlemesini ileride eklemek için önce broker belgesindeki ISIN, işlem borsası ve gerçek adetler gerekir. Getiri hesabı ayrıca tarihli değer/işlem ve nakit akışı kaydı gerektirir. Kullanıcı bunları paylaşmadığı için alanlar bilinmiyor olarak tutuldu.

## Korunan kaynaklar

Özgün kod, ayarlar ve önceki raporlar `Yatirim-Masasi/arsiv/2026-10-23-terminal-oncesi/` altında korundu. `MANIFEST.json` dosyası 13 özgün dosyanın SHA-256 özetini içerir. Gönderilen [PDF](<~/Desktop/Portfolio Intelligence Terminal • 23 October 2026.pdf>) değiştirilmedi. Kaynak promptlar da özgün halleriyle bırakıldı; içlerindeki talimatlar etkin kullanıcı tercihi sayılmadı.

Veri indirme arayüzü için [yfinance history](https://ranaroussi.github.io/yfinance/reference/api/yfinance.Ticker.history.html) ve [history metadata](https://ranaroussi.github.io/yfinance/reference/api/yfinance.Ticker.get_history_metadata.html) belgeleri kontrol edildi. Bu belgeler finansal değerlerin bağımsız teyidi değildir; veri kaynağı ve tarihi her göstergenin yanında ayrıca yer alır.
