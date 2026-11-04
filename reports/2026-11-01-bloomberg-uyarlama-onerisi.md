# Bloomberg iş akışlarından ETF Yatırım Masası'na uyarlanacak özellikler

**Tarih:** 1 Kasım 2026 · **Tür:** Mevcut uygulamaya yönelik ürün ve geliştirme önerisi · **Durum:** Öneri; kurulum veya uygulama değişikliği yapılmadı

## Önerinin özü

Bu sistemin ana ürünü, **açılışta Scalable verisini yenileyen, kendi tarihli kayıtlarını biriktiren, kaynakları araştırılabilir hale getiren ve modelleri aynı kanıt üzerinde karşılaştıran kişisel araştırma masası** olmalı. Bloomberg'den alınacak en değerli fikir, veri, haber, belge, hesap ve araştırmanın seçilen varlık etrafında birbirine bağlanmasıdır.

Hedef, Bloomberg'in özel veri kapsamına sahipmiş gibi görünmek değil; senin araştırma döngünü bu çalışma düzeniyle hızlandırmak. Arayüz benzerliği veri kalitesini veya kapsama eşitliğini kanıtlamaz. Bloomberg'in PORT ürünü de pozisyon, risk ve performansı ortak iş akışında birleştirmeyi vurguluyor. Bizim uyarlamamız daha dar kaynaklarla ve kapsamı açık göstererek çalışacak. [Bloomberg PORT](https://professional.bloomberg.com/products/bloomberg-terminal/portfolio-analytics/)

## 1. Bugünkü koddan başlayan değerlendirme

Önceki tasarımın ardından `masa/` uygulaması geliştirilmiş. Bu rapor, artık yalnız tasarım dosyasına değil mevcut kaynaklara da dayanıyor:

| Kodda görülen parça | Yeni önerinin başlangıç noktası |
|---|---|
| `cli.py` içindeki `cmd_baslat` | Oturum → veri → geçmiş → tarama → isteğe bağlı TradingAgents → rapor → yorum paketi akışı var. |
| `pipeline.py` | Pozisyon, nakit, kotasyon ve tarihsel seriler için toplama ve mühür kayıtları var. |
| `pano.py` | Veritabanından üretilen dört alanlı statik HTML pano var; `pano --ac` ile açma yolu tanımlı. |
| `research/`, `thesis/`, `forecast/` | Kanıt, araştırma doğrulaması, tez ve sonuç takibi için modüller bulunuyor. |
| `model_registry/` ve TradingAgents bağlantısı | Model manifesti, kayıt ve alternatif sağlayıcı akışı var. |
| `scheduler.py`, `backup.py` | Yerel zamanlama ve yedekleme için kod yolları var. |

Bu, bütün özelliklerin canlı hesapla çalıştığını veya eksiksiz entegre olduğunu kanıtlamaz. Bu incelemede broker verisi çekilmedi, ücretli/abonelik model çağrısı yapılmadı ve test paketi yeniden çalıştırılmadı. README'deki test sayısı güncel kabul sonucu olarak kullanılmadı. Kodda görülen yetenekler ile aşağıdaki öneriler ayrı tutuldu.

Yerel dayanaklar: [başlangıç akışı](~/Documents/ETF/masa/src/masa/cli.py:1920), [veri motoru](~/Documents/ETF/masa/src/masa/pipeline.py), [pano](~/Documents/ETF/masa/src/masa/pano.py), [araştırma ajanı](~/Documents/ETF/masa/src/masa/research/agent.py), [model kayıt yöneticisi](~/Documents/ETF/masa/src/masa/model_registry/manager.py:239).

Paylaşılan metin 22 videonun dökümünü içeriyor. Özellikle Bloomberg'in çalışma alanı, haber/araştırma, hisse ve grafik anlatımları ile ücretsiz terminal iddiaları karşılaştırıldı. Videolardaki kurulum komutları talimat olarak uygulanmadı; gösterilen eski fiyatlar, örnek şirketler ve piyasa yorumları güncel veri sayılmadı.

## 2. Hangi Bloomberg işlevleri uyarlanmalı?

Aşağıdaki Bloomberg adları işlev eşleştirmesidir. Bunlar Bloomberg bağlantısı, lisansı veya verisini kullanacağımız anlamına gelmez. İşlev isimleri için Bloomberg'in kendi başlangıç kılavuzu ve kullanıcının paylaştığı Bloomberg video dökümleri esas alındı. Öncelik ve yerel karşılıklar bu raporun ürün önerisidir. [Bloomberg işlev kılavuzu](https://data.bloomberglp.com/professional/sites/10/Getting-Started-Guide-for-Students-English.pdf)

| Esin kaynağı | Bizdeki karşılığı ve yararı | Ek ücret olmadan sınırı | Öncelik |
|---|---|---|---|
| **Launchpad + Worksheets (W)** | Bağlantılı çalışma ekranı: portföy, izleme, fiyat grafiği, haber, kanıt ve tez. Bir varlık seçildiğinde bütün alanlar aynı varlığı gösterir. | Kendi verilerimizle yapılabilir; yeni bir piyasa veri lisansı sağlamaz. | **İlk** |
| **DES — varlık tanımı** | Tek varlık kartı: ISIN, tam pay sınıfı, fon/şirket, ücret, yapı, kaynak ve son doğrulama. | Broker + ihraççı belgeleri; bulunmayan alan boş kalır. | **İlk** |
| **GP / HP / karşılaştırma grafikleri** | Tarihli fiyat ve spread arşivi; karşılaştırmalı getiri, drawdown ve olay işaretleri. | Broker serisinin düzeltme kapsamı doğrulanmalı. Kotasyon mid'i toplam getiri değildir. | **İlk** |
| **PORT** | Portföy getirisi, nakit akışı, risk, şirket/ülke/sektör maruziyeti ve ETF örtüşmesi. | Kurumsal risk modelini taklit etmeden doğrulanabilir hesaplar. Eksik holdings kapsamı gösterilir. | **İlk** |
| **TOP / CN / MREP / haber uyarıları** | Açılış özeti: son ziyaretten beri ne değişti, hangi açıklama hangi fonu/tezi etkileyebilir? | Açık resmî açıklama, şirket/ihraççı yayını ve izinli haber kaynakları; Bloomberg haber akışı değil. | **İlk** |
| **DS / şirket belge araması** | Kendi factsheet, KID, rapor ve açıklamalarında arama; cevaptan belge bölümüne geçiş. | Yalnız topladığımız ve erişim hakkımız olan belge evreni. | **Sonraki** |
| **ECO / şirket olay takvimi** | Merkez bankası, veri yayını, bilanço ve fon değişikliği takvimi; teze bağlanan olaylar. | Resmî tarihler bulunabilir; kapsamlı piyasa konsensüsü her zaman bulunamaz. | **Sonraki** |
| **EQS — tarama** | Kaydedilmiş filtreler: ürün yapısı, tema, gider, veri kapsamı, relatif davranış; eleme nedenlerinin kaydı. | Tüm dünya için eksiksiz ücretsiz evren varsayılmaz. Brokerda bulunmak, her emir koşulunda işlem yapılabilirlik kanıtı değildir. | **Sonraki** |
| **FA + RV** | Şirket finansal kartı ve karşılaştırma; ETF'lerde fon yapısı ve ekonomik maruziyet karşılaştırması. | SEC/şirket kaynakları güçlü başlangıç; Avrupa kapsamı ve normalleştirme ek emek ister. | **Sonraki** |
| **WEI / IMAP benzeri görünüm** | Piyasa ve tema özeti: bölge/sektör/faktör karşılaştırması. | ETF temsilcisi kullanılıyorsa endeksin kendisi diye gösterilmez; erişilebilir seri ve tarih açıklanır. | **Sonraki** |
| **BQL / alan kataloğu fikri** | Yerel veriye tutarlı soru: “Son ayda spread'i değişen, holdings'i güncel fonları göster.” | Kendi sorgu katmanımız; Bloomberg BQL hizmetine ücretsiz erişim değil. | **Sonraki** |
| **Araştırma yönetimi / BI çalışma biçimi** | Tema dosyası, kaynaklar, karşı tezler, katalizörler ve görüş değişimi tek yerde. | Kendi araştırmamız; Bloomberg Intelligence'ın özel raporları yerine geçmez. | **Sonraki** |
| **SPLC / DDIS** | Açıklanmış müşteri/tedarikçi bağı ve borç vadesi üzerinden risk incelemesi. | Yalnız kamuya açıklanan ilişkiler; tam tedarik zinciri grafiği veya borç veri tabanı iddiası yok. | **Daha sonra** |
| **WACC / DCF / XLTP fikri** | Kaynaklı girdilerle tekrar kullanılan şirket değerleme ve duyarlılık şablonları. | Varsayımlar açık olmalı; hesaplanan tek değer “doğru fiyat” sayılmaz. ETF'nin kendisine şirket DCF'i uygulanmaz. | **Daha sonra** |

Bağlantılı ekran ve izleme fikri özellikle değerli: veriyi ayrı tablolarda bulundurmak yerine aynı ISIN/varlık kimliği ve aynı veri kesim tarihiyle dolaşabilirsin. Bloomberg'in Worksheets açıklaması da izleme listesi ile haber, olay, araştırma ve grafiklerin bir arada kullanımını anlatıyor. [Bloomberg Worksheets](https://professional.bloomberg.com/products/bloomberg-terminal/access/bloomberg-professional-app/)

### Birinci öncelik: açılışta çalışan veri masası

Kullanıcının yeni isteğiyle ilk ürün ölçütü açık: **Uygulamayı açmak, yalnız eski bir raporu açmakla sınırlı kalmamalı.** Mevcut `baslat` veri akışı ile `pano` görüntüsü tek yerel açılış deneyimine bağlanmalı.

Önerilen açılış davranışı:

1. Son başarılı pano hemen gösterilir; üzerinde açık tarih ve güncellik durumu bulunur.
2. Yerel başlatıcı Scalable oturumunu ve o an çalışan yenileme işini kontrol eder. Oturum yoksa insanlı giriş gerekir; başarısız bağlantı eski veriyi güncel yapmaz.
3. Pozisyon ve nakit okunur; mevcut portföy, izleme ve o çalışmanın adayları için gerekli kotasyonlar toplanır. Broker çağrıları yalnız okuma listesinden yapılır.
4. İşlem geçmişi örtüşen aralık ve tekilleştirme ile güncellenir. Grafik serileri her açılışta baştan indirilmek yerine kaynak ve aralık politikasına göre tamamlanır.
5. Mutabakat ve kalite kontrollerinden sonra yeni kayıt grubu mühürlenir. Kaynak bazında eksikler görünür kalır.
6. Son başarılı çalışmaya göre fark çıkarılır. Yeni belge, olay veya hesap verisi değişimi araştırma kuyruğuna girer.
7. Yeni pano ve kısa değişim özeti yayımlanır. Daha uzun model araştırması ayrı durum göstergesiyle devam eder; sonuç hazır olmadan eski görüşün tarihi yenilenmez.

Bu akış için ilk aşamada büyük bir web uygulaması zorunlu değil. Yerel açılış komutu/başlatıcısı veri işini yönetip mevcut statik panoyu üretebilir; yenileme durumunu tarayıcı içinde anlık izlemek istenirse sonraki adımda korumalı yerel arayüz bağlanır. Tarayıcıdan serbest shell veya broker komutu çalıştırılmaz.

Başarılı açılış için saniye hedefi şu anda verilmedi. İlk pilotta veri, mutabakat ve model süreleri ayrı ölçülür; kullanıcı modeli beklerken fiyat/toplam/veri durumu ekranını kullanabilir.

Scalable belgeleri, yenilenen erişim token'ına rağmen oturumun azami ömrü ve insanlı yeniden giriş ihtiyacı bulunduğunu belirtiyor. Bu yüzden açılışta otomatik okuma tasarlanabilir; sonsuza kadar giriş istemeyen bir hesap bağlantısı varsayılamaz. [Scalable oturum davranışı](https://github.com/ScalableCapital/scalable-cli/blob/main/public-docs/automation.md)

## 3. Geçmişi üç ayrı kayıt olarak kurmak

### A. Gerçekte çektiğimiz veri

Her toplama için ham cevap, kaynak, gözlem/erişim zamanı, kimlik ve içerik özeti saklanır. Fonun kotasyon örnekleri ile brokerın tarihsel grafik serileri ayrı veri türüdür. Bugün indirilen eski bir grafik, geçmişte o grafiğin elimizde bulunduğunu kanıtlamaz.

### B. O gün ne biliyorduk?

Kaynak belgesi, holdings seti, makro serinin sürümü ve o günkü hesap çıktısı korunur. Kullanıcı “Geçen ay bu fon hakkında ne biliyorduk?” diye sorunca sistem o tarihte erişilebilir kaydı getirir. Sonradan düzeltilen finansal veri önceki raporun içine geriye doğru yazılmaz.

### C. O gün ne düşündük ve ne oldu?

Tez, karşı tez, hangi kanıtla görüşün değişeceği, ufuk, kullanılan model ve araştırma referansı kaydedilir. Vadesi gelen değerlendirme uygun seriyle karşılaştırılır. Model görüşü, gerçekleştirilmiş broker işlemi gibi kaydedilmez; kısa dönem sonuç uzun dönem tezin başarısı yerine geçmez.

Bu üç kayıt mevcut mühür, tez ve tahmin modüllerini ortak zaman çizelgesinde birleştirir. Tek bir “geçmiş fiyat” tablosu aynı amacı karşılamaz. Brokerın bugüne kadar eriştirdiği tarihsel kapsam ile bundan sonra kendimizin biriktireceği gözlem geçmişi ayrı gösterilir. Scalable komut belgeleri grafiklerin tarihsel olduğunu ve kendi başına canlı güncelleme/hesaplanmış yüzde getiri sağlamadığını belirtiyor. [Scalable grafik kapsamı](https://github.com/ScalableCapital/scalable-cli/blob/main/public-docs/commands.md)

## 4. Agentic critical thinking nasıl ürünleşmeli?

Temel akış **kaynak → ortak kanıt → hesap → tez → karşı tez → denetim → tarihli sonuç** olmalı. Çok model çalıştırmak tek başına eleştirel düşünme sağlamaz; hangi varsayımın sınandığı görünür olmalı.

| Görev | Yapacağı iş | Yapmaması gereken |
|---|---|---|
| Veri ve hesap kontrolü | Kimlik, tarih, sayı, birim, mutabakat ve kapsama kontrolü | Modelden eksik fiyat veya getiri uydurmasını istemek |
| Araştırmacı | Yeni ve ilgili birincil kaynakları toplamak; varlık/tema ile ilişkilendirmek | Aynı haberin kopyalarını bağımsız kanıt saymak |
| Tez analisti | Mekanizmayı açıklamak: gelişme → şirket/sepet etkisi → değerleme beklentisi | Haber ile eşzamanlı fiyat hareketini kanıtlanmış neden-sonuç saymak |
| Karşı tez analisti | Alternatif açıklamayı, beklentinin fiyatlanmış olmasını ve başarısızlık koşulunu araştırmak | Sırf rolü gereği bütün olumlu kanıtları reddetmek |
| Doğrulayıcı | Kaynak desteği, hesap uyumu, eski veri, yetki ve ücret sınırlarını sınamak | Aynı modelin tekrarını bağımsız ikinci doğrulama saymak |
| Editör ve hafıza | Kısa sonuç, ayrışma noktaları, bilinmeyenler ve sonraki kontrol olayını kaydetmek | Çoğunluk oyunu doğruluk yüzdesi gibi sunmak |

Farklı model ailesi bulunamazsa kod kontrolü çalışır; “bağımsız model denetimi yapılmadı” bilgisi korunur. Modelin özel düşünce dökümü yerine kontrol edilebilir gerekçe, kanıt, varsayım ve itiraz gösterilir.

TradingAgents bu yapıda tartışma aracı olarak kullanılabilir. Mevcut köprü kendi verisini kullanan çıktıyı harici görüş olarak saklıyor; ortak kanıtı gerçekten zorunlu kılmak için araç/veri yolları ayrıca doğrulanmalıdır. ETF için fonun şirket bilançosu varmış gibi analiz yapılmaz; şirket bileşenleri uygun kapsam ve tarihli holdings ile incelenir. [TradingAgents projesi](https://github.com/TauricResearch/TradingAgents)

### Önce kapatılması gereken mevcut erişim boşluğu

Kaynak incelemesinde `record_run`, modelin `PAUSED/REVOKED` durumunu engelliyor; aynı noktada doğrulanmış ücretsiz erişim, bölge uygunluğu, araç maliyeti ve görev değerlendirmesinin tamamını zorunlu kılan koşul görünmüyor. Bazı varsayılan model kayıtları da `ELIGIBLE` etiketiyle hazırlanmış. Bu etiket hesabın gerçek erişiminin kanıtı sayılamaz. [Kayıt kontrolü](~/Documents/ETF/masa/src/masa/model_registry/manager.py:239)

Bu sınırlı kod bulgusu ücret oluştuğu anlamına gelmez; canlı hesap veya fatura denetlenmedi. Ancak “ek API ücreti olmayacak” hedefi için geliştirme gerektirir:

- Her gerçek LLM çağrısından önce **tek ortak çağrı kapısı** çalışmalı; kayıt tutmak veya ekranda onay istemek yeterli kabul edilmemeli.
- Quick/deep katmanları, alternatif sağlayıcı, araştırma ajanı ve arama/embedding gibi yardımcı araçlar aynı kurala tabi olmalı.
- Yalnız ilgili görev için doğrulanmış yerel/abonelik/ücretsiz yol seçilmeli. Sağlayıcıdaki model adı veya anahtarın varlığı yeterli olmamalı.
- Uygun yol ve kota yoksa iş beklemeli; başka bir sağlayıcıya ancak aynı koşulları sağlıyorsa geçilmeli ve yeni alt çalışma kaydı açılmalı.
- Kaynak toplama ve sayısal kontroller model kotası bitince de çalışmalı. Açılış verisi güncellemesi model araştırmasına bağımlı olmamalı.

Kullanılan aboneliğin mevcut bedeli, yerel enerji/depolama ve işletim maliyeti devam eder; hedef yeni kullanım bazlı model/veri faturası açmamaktır. Bu raporda hesap erişimlerinin ücretsiz olduğu doğrulanmadı ve yeni bir ücretli bağlantı başlatılmadı.

## 5. Veriyle konuşma: yerel alan kataloğu ve belge arama

Bloomberg'deki sorgu ve kaynak bağlantısı fikirlerini şu şekilde uyarlardım:

**Alan kataloğu:** Her metrik için tanım, formül, birim, veri türü, kapsam, sıklık, son güncelleme ve kaynak. “Getiri” tek başına yeterli etiket olmaz; fiyat/toplam getiri, dönem ve para birimi açık olmalı.

**Sınırlı veri araçları:** Modeller yalnız onaylı işlevlerden veri ister: tarihli seri, varlık kartı, holdings kapsamı, şirket maruziyeti, kayıtlı tarama ve belge bölümü. Her cevap kaynak kimlikleri taşır. Modelin doğrudan serbest SQL, dosya veya broker komutu yürütmesi gerekmez.

**Belge arama:** Başlangıçta SQLite FTS5 ile metin, başlık, varlık, belge türü ve tarih araması yeterli olabilir; seçilen SQLite derlemesinde desteği sınanır. Sonuç ilgili metin bölümü ve özgün belgeyle açılır. Kaynak evreni ve arama kapsamı görünür; belgeyi bulamamak ekonomik olgunun yokluğunu kanıtlamaz. [SQLite FTS5](https://www.sqlite.org/fts5.html)

BQL adı ve servisi Bloomberg'e aittir; biz aynı kullanım fikrini kendi verimiz için uygularız. Microsoft'un Bloomberg bağlantı belgesi de gerçek Bloomberg veri erişimi için uygun abonelik/lisans gereksinimini açıklıyor. [Bloomberg veri bağlantısı](https://learn.microsoft.com/en-us/power-query/connectors/bloomberg-data-and-analytics)

## 6. Haber ve olay radarı nasıl farklılaşmalı?

En önemli soru “Bugün kaç haber var?” değil, **“Son görüşümüzden beri hangi kanıt değişti?”** olmalı. Her haber/olay kartı şu alanları taşımalı:

1. Ne yayımlandı veya değişti?
2. Kaynak ve yayın zamanı nedir?
3. Hangi varlık veya doğrulanmış ETF bileşeniyle ilgili?
4. Önceki tezle bağlantısı nedir: destek, karşı kanıt, kapsam belirsizliği?
5. Bu ilişki olgu mu, analitik çıkarım mı?
6. Hangi yeni veri geldiğinde tekrar incelenecek?

Bloomberg haber ve uyarı düzeni bu araştırma biçimine örnek olabilir; bizim kaynaklarımız açık/izinli kaynaklar olur. [Bloomberg haber iş akışı](https://professional.bloomberg.com/products/bloomberg-terminal/news/)

Takvim için ECB toplantıları, Eurostat yayınları ve şirket/ihraççı duyuruları başlangıç kaynaklarıdır. Tarih `kesin / duyurulmuş-geçici / tahmini` olarak işaretlenir; iptal/değişiklik sürümlenir. Beklenti verisi yoksa “gerçekleşen eksi konsensüs” hesabı yapılmaz. [ECB takvimi](https://www.ecb.europa.eu/press/calendars/mgcgc/html/index.en.html), [Eurostat takvimi](https://ec.europa.eu/eurostat/news/release-calendar)

## 7. Hangi GitHub araçları gerçekten işe yarar?

Bir proje, çözdüğü ihtiyaç netse eklenmeli. Mevcut modüllerin yerine ikinci bir platform kurmak başlangıç hedefi değildir.

| Araç | Kullanım kararı |
|---|---|
| Mevcut Scalable bağlayıcısı + SQLite | Açılış, geçmiş, kimlik ve veri kaydının çekirdeği. Hazır olan parçalar güçlendirilir. |
| [TradingAgents](https://github.com/TauricResearch/TradingAgents) | Mevcut bağlantıyı kullan; veri ve erişim kapılarıyla tartışma/karşı tez üret. |
| [Trafilatura](https://github.com/adbar/trafilatura) | Web metni çıkarımı; mevcut proje bağımlılık listesinde var. Belge ve alan doğruluğu ayrıca sınanır. |
| [EdgarTools](https://github.com/dgunning/edgartools) | Şirket bildirimleri ve finansal olgular; mevcut bağımlılık listesinde var. ETF issuer holdings'inin yerine geçmez. |
| [QuantStats](https://github.com/ranaroussi/quantstats) | Hazırlanmış doğru seriden risk/performance grafikleri; mevcut listede var. |
| [Docling](https://github.com/docling-project/docling) | Karmaşık PDF/tablo gerektiğinde ayrı ortamda; düzgün CSV'yi PDF/OCR'a çevirmek için kullanılmaz. |
| [FinanceDatabase](https://github.com/JerBouma/FinanceDatabase) | Mevcut havuzu genişletmek için isteğe bağlı keşif. İşlem yapılabilirlik ve fon kimliği ayrıca doğrulanır. |
| [Local Deep Research](https://github.com/LearningCircuit/local-deep-research) | Daha sonra bir tema üzerinde sınırlı pilot; kendi araştırma kuyruğumuzu devralmaz. Yerel model ve arama yollarının kullanım şartları doğrulanır. |
| [OpenBB](https://github.com/OpenBB-finance/OpenBB) | İleride çok sayıda veri sağlayıcısı için ortak erişim gerekirse ayrı adaptör pilotu. Bugünkü çekirdeğin yerine kurulmaz. |
| [Portfolio Performance](https://github.com/portfolio-performance/portfolio) | İsteğe bağlı muhasebe/getiri karşılaştırması; ikinci etkin portföy kaydı olmaz. |

Local Deep Research proje belgelerinde yerel model ve farklı arama bağlantıları, OpenBB ise kamuya açık ve lisanslı kaynakları birleştiren erişim katmanı anlatılıyor. Bu kabiliyetler tek başına bütün veri/model kullanımının ücretsiz olduğunu kanıtlamaz. [Local Deep Research belgeleri](https://github.com/LearningCircuit/local-deep-research), [OpenBB belgeleri](https://github.com/OpenBB-finance/OpenBB)

### GitHub Actions nerede kullanılmalı?

GitHub'daki projeler yazılım bileşenleridir; GitHub Actions ise işleri çalıştıran otomasyon hizmetidir. Önerilen görev ayrımı:

- **Mac'te:** Broker oturumu, kişisel hesap verisi, yerel model, günlük kayıt, kişisel rapor ve zamanlama.
- **Actions'ta:** Sentetik örneklerle test, veri sözleşmesi regresyonu, paket denetimi, kod taraması; gerekirse yalnız kamuya açık kaynağın şema/erişim testi.

Broker oturumu ve ham portföy geçmişi Actions'a taşınmaz. İlk sürümde kişisel Mac genel amaçlı self-hosted runner yapılmaz; yerel görev yöneticisi bu ihtiyacı karşılar.

Actions her koşulda ücretsiz ve tam zamanında çalışan hizmet sayılmaz: özel depolarda kullanım/depolama limitleri vardır; standard public runner ücretsizliği diğer seçeneklere genellenmez. Zamanlanmış işler yoğunlukta gecikebilir veya düşebilir. Bu yüzden hesap verisinin esas toplayıcısı yerel kalır. Ücretli aşımı engelleyen bütçe politikası ayrıca doğrulanır. [Actions ücretleri](https://docs.github.com/en/billing/concepts/product-billing/github-actions), [zamanlama sınırı](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule)

## 8. Hangi özellikleri şimdi hedeflememeli?

- **Tam EE/ANR konsensüsü:** Analist beklentileri ve hedef fiyat geçmişinin bütün evrende eksiksiz ücretsiz bulunduğu varsayılmaz. Yönetim rehberliği, model senaryosu ve analist konsensüsü ayrı türlerdir.
- **Instant Bloomberg ağı:** Araştırma sohbeti oluşturabiliriz; kurumlar arası profesyonel iletişim ağına eşdeğer erişim sağlayamayız.
- **Özel BI/BNEF araştırması ve haber akışı:** Kendi kaynaklı dosyalarımızı oluştururuz; lisanslı içerikleri paket kurarak elde etmiş olmayız.
- **Kurumsal tahvil/CDS kotasyonları, tam derinlik ve tick arşivi:** Ücretsiz kaynakların kapsamı doğrulanmadan destek sözü verilmez. Bir kotasyon gözlemi, o fiyattan işlem garantisi değildir.
- **YAS, opsiyon yüzeyi, ileri FX türevleri:** Mevcut ETF araştırma amacında ilk öncelik değildir; gelecekte ihtiyaç oluşursa kendi veri ve model sözleşmesi gerekir.
- **Her gün zorunlu işlem fikri ve model oylaması:** Aday veya yeni sonuç yoksa sistem bunu söyleyebilmelidir. Araştırma sayısı işlem sayısı hedefi olmaz.

Videolardaki Amber/ücretsiz terminal örnekleri görünüm ve kullanım fikirleri verebilir. Paylaşılan dökümlerde Yahoo/OpenBB ve kamuya açık şirket bildirimleri de geçiyor. Bunlar profesyonel veri kapsamıyla eşitlik kanıtı değil; tam repo kimliği, veri kaynağı ve koşulları doğrulanmadan mevcut sisteme yeni bağımlılık eklenmez.

## 9. Mevcut sisteme göre geliştirme sırası

| Sıra | Geliştirme | Bitti sayılacağı davranış |
|---|---|---|
| **1 — Açılış ve ücret kapısı** | `baslat` + pano bağlantısı, tek yenileme işi, çağrı öncesi ortak erişim denetimi | Açılış yeni veri toplamayı başlatıyor; başarısızlıkta eski tarih korunuyor; doğrulanmamış ücret yolu çalışmıyor. |
| **2 — Tarihli çalışma ekranı** | Varlık kartı, fiyat/geçmiş, portföy, son çalışmaya göre fark | Aynı varlık seçimi bütün alanlarda korunuyor; aynı tarihli pakete geri dönülebiliyor. |
| **3 — Kaynak ve olay merkezi** | Belge araması, metrikten kaynağa geçiş, yayın/olay takvimi | Kullanıcı olgunun dayandığı bölümü açabiliyor; aynı haber tekilleşiyor; belirsiz tarih açık. |
| **4 — Kayıtlı tarama ve ortak veri araçları** | Havuz filtreleri, alan kataloğu ve modellerin sınırlı sorgu araçları | Tarama kapsamı/eksikleri/eleme nedenleri kayıtlı; sorgular yeniden üretilebiliyor. |
| **5 — Araştırma konseyi ve karne** | Ortak kanıtla tez/karşı tez, model ayrışması, sonraki kontrol olayı | Görüş kaynaklarına bağlı; ikinci aile yoksa görünür; eski tahmin sonradan değiştirilmiyor. |
| **6 — İhtiyaç temelli ek araçlar** | Local Deep Research/OpenBB gibi tek tek pilotlar; ileri karşılaştırmalar | Her ek araç mevcut akışa ölçülebilir fayda sağlıyor ve erişim/maliyet kurallarını geçiyor. |

Son kabul senaryosu: uygulama açılır → Scalable okuması ve geçmiş güncellemesi tamamlanır → eksikler belirtilen yeni mühür oluşur → “son girişten beri değişenler” görünür → kullanıcı bir varlık seçer → grafik, şirket/sepet, olay ve tez aynı bağlamda açılır → model gerekirse yalnız o paketi yorumlar → karşı tez ve denetim sonrası tarihli sonuç kaydedilir. Bu döngünün her adımı gözlenebilir olmadan yeni paket veya daha karmaşık pano eklemek öncelik olmamalı.

Bu belge öneri ve sınırlı kaynak incelemesidir. Mevcut uygulama dosyaları, hesap ayarları, model bağlantıları ve zamanlamalar değiştirilmedi.
