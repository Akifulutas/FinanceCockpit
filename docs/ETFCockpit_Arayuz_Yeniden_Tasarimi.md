# ETFCockpit: Arayüz Yeniden Tasarımı ve Kapsamlı İçerik Planı

**Belge Sürümü:** 2.0 (Nihai Teknik Tasarım ve Mimari Şartname)  
**Tarih:** 1 Kasım 2026  
**Hedef Sistem:** ETFCockpit macOS Yerel İstemcisi (`macos/Sources/ETFCockpit/`) & `masa` SQLite Veri Tabanı (`masa/var/private/masa.db`)  
**Yazar:** ETFCockpit Mimari ve Tasarım Çalışma Grubu  
**Durum:** Onaylanmış Teknik Tasarım Belgesi (RFC / Mimari Şartname)  

---

## Bölüm 0: Yönetici Özeti ve Değişim Matrisi

### 0.1 Yeniden Tasarımın Gerekçesi ve Vizyonu

ETFCockpit, bireysel ETF yatırımcısına kurumsal düzeyde operasyonel disiplin, kriptografik veri bütünlüğü ve karar desteği sağlamak üzere geliştirilmiş yerel bir macOS uygulamasıdır. Ancak mevcut v1 uygulaması, artımlı ve hızlı özellik geliştirme süreçlerinin doğal bir sonucu olarak şu temel yapısal problemlerle karşı karşıyadır:

1. **Aşırı Parçalanmış Bilgi Mimarisi (14 Ayrı Ekran):** Kenar çubuğunda listelenen 14 ekran, kullanıcının bilişsel yükünü artırmakta, birbiriyle doğrudan ilişkili operasyonları (örneğin portföy varlıkları ile işlem defterini veya tahmin üretimi ile model karnesini) birbirinden koparmaktadır. 14 ekranın 9'unda `İP-1/10`, `İP-3`, `İP-7` gibi dahili geliştirme kodlarının yer alması, arayüzü operasyonel bir kokpitten ziyade bir geliştirici hata ayıklama paneline dönüştürmüştür.
2. **Kritik Ekran Hataları ve Sahte Durumlar (U1–U16):** Canlı veritabanında (`masa.db`) 4 pozisyon (örn: 5.000,00 € piyasa değeri) ve 626 işlem gözlemi bulunmasına rağmen, arayüzdeki hatalı SQL sorguları (`CROSS JOIN` kısıtları ve `WHERE NOT EXISTS` mantığı) sebebiyle ana ekranlarda "0 Pozisyon", "0,00 €" ve işlem defterinde "0,00 € Alış Toplamı" gösterilmektedir. Daha da vahimi, veri yüklenmediğinde devreye giren `?? true` gibi varsayılan yeşil mantıklar, 4 mutabakat kartının sahte bir şekilde "Eşleşti / %100" basmasına neden olmaktadır.
3. **Kopuk İş Akışı (Tahmin → Uzlaşma → Eylem Döngüsünün Olmayışı):** Sistemin en özgün katma değeri olan *09:30 CET Sabah Tahmini → 17:40 CET Akşam Uzlaşması → Model Karnesi Kıyaslaması → Tez ve Pozisyon Kararı* döngüsü tek bir akışta birleştirilmemiştir. Kullanıcı sabah tahmini görmek için bir ekrana, model skorunu incelemek için başka bir ekrana, portföy tavsiyesini görmek için üçüncü bir ekrana gitmek zorunda kalmaktadır.
4. **Varlık Odaklı Bakışın (Uniform Asset Lens) Eksikliği:** Bir yatırımcı portföyündeki veya izleme listesindeki bir ETF'i (örneğin SPYI) incelemek istediğinde; kotasyonunu Portföy'de, tahminini Tahmin'de, fon içi holding bileşenlerini Hedef Sepet'te, yatırım hipotezini Tezler'de, araştırma kanıtlarını ise Araştırma ekranında aramak zorundadır.

**Yeni Tasarımın Vizyonu:**  
Hiçbir mevcut özelliği, butonu, filtreyi veya hesaplama mantığını kaybetmeden; 14 ekranı **6 mantıksal ana bölüme (Bugün ⌘1, Portföy ⌘2, Tahminler ⌘3, Kararlar ⌘4, Keşif ⌘5, Sistem ⌘6)** ve her an erişilebilen **Sabitlenmiş Varlıklar (5.7 Varlık Detay Sayfası)** mimarisine dönüştürmektir.

### 0.2 Temel Kazanımlar

- **Sıfır Veri ve Yetenek Kaybı:** Mevcut 14 ekrandaki tüm tablo sütunları, metrik kartları, CLI tetikleyicileri ve modal diyaloglar yeni 6 bölümlü mimaride birebir korunmuş ve daha ergonomik bir yerleşime kavuşturulmuştur.
- **Kökten Veri Doğruluğu:** Canlı `masa.db` verilerini perdeleyen SQL sorgu hataları düzeltilerek, 5.000,00 € portföy değeri ve 626 işlem defteri kaydı eksiksiz olarak kullanıcıya sunulmuştur.
- **Dürüst Durum Anayasası:** Sahte yeşil durumlar (`?? true`), doğrulanmamış "ZERO COST" etiketleri ve küçük örneklemde ($N < 30$) yanıltıcı isabet oranları tamamen yasaklanmış; verisi olmayan her durum için gri nötr renk ve tek tıkla aksiyon alma rehberliği getirilmiştir.
- **Bütünleşik Varlık Sayfası (5.7):** Herhangi bir ETF'e tıklandığında fiyatı, portföy payı, günün tahmini, yatırım tezi, fon içi ilk 10 bileşeni, kurumsal işlemleri ve resmi Factsheet kanıtlarını tek bir sayfada toplayan birleşik lens kurulmuştur.
- **Modern macOS HIG Standartları:** Segmented picker metin kırılmaları (U11) ve tablolardaki 400 px boş sütun problemleri (U12) giderilmiş; SF Pro / SF Mono tipografisi, 3 sütunlu bölünmüş görünüm (Split View), ⌘K komut paleti ve sağ inceleme çekmecesi (Inspector Drawer) eklenmiştir.

### 0.3 Üst Düzey Değişim Matrisi

| Boyut | Mevcut Durum (v1) | Yeni Tasarım (v2) | Temel Fark ve Kullanıcı Faydası |
|---|---|---|---|
| **Kenar Çubuğu** | 14 düzensiz öğe (İP kodlu, dikey kaydırma gerektiren liste) | 6 net ana bölüm (⌘1–⌘6) + Sabitlenmiş Varlıklar | Bilişsel yük asgariye iner; klavye ile anında geçiş sağlanır. |
| **Portföy & Nakit** | Hatalı sorgu nedeniyle 0 Pozisyon / 0,00 € (U1) | 4 Pozisyon, 5.000,00 € değerleme ve 5'li nakit kırılımı | Canlı veritabanındaki 5.000,00 € net aktif değer tam doğrulanır. |
| **İşlem Defteri** | Yalnızca 3 nakit işlemi ve 0,00 € alış toplamı (U3) | 626 işlem gözleminin tamamı, 5.000,00 € maliyet toplamı | Broker işlem geçmişi, temettüler ve stopajlar eksiksiz listelenir. |
| **Mutabakat Durumu** | Veri yokken bile sahte "Eşleşti / %100" yeşil kartlar (U4) | Nötr gri "Çalıştırılmadı" kartı + tek tıkla `mutabakat` aksiyonu | Sahte güven duygusu engellenir; mutabakat açıkları anında yakalanır. |
| **Tahmin & Model** | Tahmin, Karne ve Modeller 2 ayrı ekrana bölünmüş | Tahmin → Uzlaşma → Model Karnesi → Kayıt (⌘3 Tahminler) | Günlük operasyonel döngü tek ekranda kronolojik olarak akar. |
| **Karar Desteği** | Değerlendirme, Sepet, Tez ve Raporlar 4 ayrı ekranda | Kararlar (⌘4) altında 5 sekmeli entegre strateji masası | Pozisyon tavsiyesi alınırken tez ve hedef sepet sapması anında görülür. |
| **Aday Taraması** | Ekran açılır açılmaz canlı CLI taraması tetiklenir (U7) | Salt-okunur son mühürlü sonuç + manuel "Şimdi Tara" butonu | GUI navigasyonu veritabanına istenmeyen kayıt yazmaz. |
| **Z-Skor Gösterimi** | "+1.17 σ" z-skoru "1.17 / 10.0" karne notu gibi sunulur (U10) | Standart sapma gösterimi (+1.17 σ) ve doğru Gaussian renk skalası | İstatistiksel veriler yanıltıcı olmadan profesyonelce sunulur. |
| **Güvenlik & Gizlilik** | Alt barda tam disk yolu (`~/Documents/ETF/...`) sızar (U16) | Maskeli dosya yolu (`~/.../masa.db`) ve gizlilik modu (Privacy Mode) | Ekran paylaşımlarında veya sunumlarda kişisel veriler korunur. |
| **Varlık Detayı** | Yok (Her veri parçası farklı bir ekranda) | Ortak Varlık Detay Sayfası (Bölüm 5.7) | Herhangi bir ISIN'a tıklandığında tüm alt sistem verileri tek ekranda. |

---

## Bölüm 1: Mevcut Arayüzün Teşhisi ve Ekran Hataları Analizi (U1–U16)

### 1.1 Mevcut Mimari Analiz ve Dağınıklık Teşhisi

Mevcut Swift/SwiftUI kod tabanı (`macos/Sources/ETFCockpit/`), SQLite veri tabanı (`masa/var/private/masa.db`) ve Python CLI katmanı (`masa`) incelendiğinde, sistemin sağlam bir veri modeli ve zengin bir iş mantığına sahip olduğu, ancak kullanıcı arayüzü katmanında ciddi mimari entegrasyon kusurları bulunduğu tespit edilmiştir:

1. **İç Geliştirme Kodları (İP-Kodları) Kirliliği:**  
   `CockpitNavigation.swift` dosyasında kenar çubuğu başlıkları ve kart metinlerinde `İP-1/10 (Bütünlük)`, `İP-3 (İşlemler)`, `İP-4 (Sepet)`, `İP-5 (Tezler)`, `İP-6 (Araştırma)`, `İP-7 (Modeller)` ve `İP-12 (Zamanlayıcı)` gibi teknik proje görev kodları doğrudan son kullanıcıya sunulmaktadır. Bu etiketler kullanıcının zihninde bir finans kokpiti değil, tamamlanmamış bir yazılım geliştirme aracı hissi uyandırmaktadır.
2. **Tekrarlayan ve Çelişen Durum Göstergeleri:**  
   Piyasa durumu ve borsa seansı hem üst araç çubuğundaki `LiveSessionTimerView` bileşeninde, hem Today ekranının tepe kartında, hem de Forecast ekranının başlığında üç kez tekrar etmektedir. Bütünlük durumu ise üst çubukta yeşil kalkanla `MATCH_SEALED` gösterilirken, Bütünlük ekranı açıldığında "TEST EDİLMEDİ" ve "UNKNOWN" yazarak kendi içinde bariz çelişkiler üretmektedir.
3. **Boş Ekranların Rehberlikten Yoksun Oluşu:**  
   Veritabanında henüz verisi bulunmayan Araştırma, Hedef Sepet, Model Kaydı ve Zamanlayıcı ekranları, kullanıcının ne yapması gerektiğini açıklamak yerine boş tablolar ve sıfır değerli kartlar sunmaktadır. Kullanıcı bir CLI komutu mu çalıştırmalıdır, bir dosya mı seçmelidir yoksa bir servisi mi başlatmalıdır sorusu yanıtsız bırakılmaktadır.
4. **Gömülü Kalmış Değerli Analizler:**  
   Değerlendirme ekranında yer alan Alman Sermaye Kazancı Vergisi muafiyet notları (Teilfreistellung %30, Sparer-Pauschbetrag) son derece değerli finansal öngörüler olmasına rağmen, her kartın altında statik metin olarak tekrarlanmakta ve asıl pozisyon tavsiyesini gölgelemektedir. Rapor ekranı ise üretilen analitik raporu zengin bir Markdown okuyucuda biçimlendirmek yerine, LLM'e gönderilen ham prompt metnini monospaced bir kutuda göstermektedir.

---

### 1.2 U1–U16 Ekran Hatalarının Ayrıntılı Kök Neden Analizi

Aşağıdaki alt bölümlerde, tespit edilen 16 kritik hatanın her biri; belirti, kök neden (dosya, satır numarası ve SQL sorgusu), canlı veritabanı gerçeği ve yeni arayüzdeki kesin çözüm kuralı ile belgelenmiştir.

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                        U1–U16 HATA VE KÖK NEDEN HARİTASI                               │
├────────────────────────────────────────────────────────────────────────────────────────┤
│ VERİ TABANI SORGUSU HATALARI:                                                          │
│   • U1: CROSS JOIN latest_quote_snap & Fallback'te eksik WHERE filtresi               │
│   • U3: WHERE NOT EXISTS (SELECT 1 FROM transaction_versions) 626 işlemi dışlar        │
│   • U6: Canlı DB'ye kazara yazılmış test tezi (th_5aab39e8bc85)                       │
│                                                                                        │
│ SAHTE YEŞİL VE YANILTICI DURUM HATALARI:                                               │
│   • U2: Çıkış kodu 0 olunca veri kontrolsüz yeşil yanan sabah akışı                   │
│   • U4: rec?.sharesMatch ?? true nil-coalescing ile sahte %100 mutabakat               │
│   • U5: Ekran açılışında hesaplanmayan sayaçlar ("TEST EDİLMEDİ" vs MATCH_SEALED)      │
│   • U14: Bireysel yatırımcıya uygulanan fon kuralı ("UCITS 5/10/40 İhlali")            │
│   • U15: Doğrulanmamış statik "0,00 € ZERO COST" ve "%100 GÜVENLİ" iddiaları          │
│                                                                                        │
│ ÇALIŞMA ZAMANI VE YAN ETKİ HATALARI:                                                   │
│   • U7: ScreenerView açıldığı an tetiklenen canlı tarama subprocess'i (#144-145)       │
│   • U8: masa/config/politika.json saklama kurallarının otomatik işletilmemesi (231 MB)│
│   • U9: Hafta sonu ve seans sonunda 09:00 XETR yerine 09:30 CET gösterilmesi           │
│   • U13: Hedef sepet yüklemede GUI yerine terminal komut metni basılması               │
│                                                                                        │
│ GÖRSEL DÜZEN VE GİZLİLİK HATALARI:                                                     │
│   • U10: +1.17 σ istatistiksel z-skorunun "1.17 / 10.0" karne notu formatlanması      │
│   • U11: Segmented Picker sol etiketine yer kalmaması ve "Görünüm" dikey kırılması    │
│   • U12: Table bileşeninde TableColumn genişliği verilmemesi ve 400px sol boşluk      │
│   • U16: Alt durum çubuğunda tam kullanıcı adının (~/Documents/ETF/...) sızması      │
└────────────────────────────────────────────────────────────────────────────────────────┘
```

---

#### U1: Bugün ve Portföy Ekranlarında 0 Pozisyon ve 0,00 € Hatası

- **Belirti ve Kullanıcı Deneyimi Etkisi:**  
  Kullanıcı uygulamayı açtığında Bugün (⌘1) ve Portföy (⌘2) ekranlarında "€0,00 · Pozisyon Yok", "0 Pozisyon Kayıtlı" ibareleriyle karşılaşmaktadır. Kullanıcı portföyünün silindiğini veya broker bağlantısının koptuğunu düşünerek panik yaşamakta, oysa Değerlendirme ekranına geçtiğinde 4 pozisyonun listelendiğini görerek arayüze olan güvenini kaybetmektedir.
- **Kök Neden (Kod Satırı ve SQL Sorgusu):**  
  Dosya: `macos/Sources/ETFCockpit/Core/Database/DatabaseService.swift`, satır 70–104 ve 140–165 (`fetchPositions()` fonksiyonu).  
  Asıl SQL sorgusu:
  ```sql
  WITH latest_quote_snap AS (
      SELECT run_id, snapshot_id, raw_object_id, collection_completed_at
      FROM snapshots
      WHERE snapshot_type = 'quotes' AND run_id LIKE 'run_%'
      ORDER BY rowid DESC
      LIMIT 1
  ),
  latest_portfolio_snap AS (
      SELECT snapshot_id
      FROM snapshots
      WHERE snapshot_type = 'portfolio'
      ORDER BY rowid DESC
      LIMIT 1
  )
  SELECT p.isin, ...
  FROM position_observations p
  CROSS JOIN latest_quote_snap lqs
  LEFT JOIN quotes q ON q.snapshot_id = lqs.snapshot_id AND q.isin = p.isin
  WHERE p.snapshot_id = (SELECT snapshot_id FROM latest_portfolio_snap);
  ```
  Sorgudaki `latest_quote_snap` CTE'si `run_id LIKE 'run_%'` kısıtına bağlanmıştır. Oysa son kotasyon snapshot'ları `scan_20261101T150418Z_...` gibi tarama öneki taşımaktadır. `latest_quote_snap` boş döndüğünde, `CROSS JOIN latest_quote_snap` ifadesi Kartezyen çarpım gereği **tüm ana sorgu sonucunu sıfır (0) satıra düşürmektedir!**  
  Daha da vahimi, satır 141–147'de yer alan yedek sorgu (fallback):
  ```sql
  SELECT position_id, ... FROM position_observations
  WHERE snapshot_id = (SELECT snapshot_id FROM snapshots ORDER BY rowid DESC LIMIT 1);
  ```
  `WHERE snapshot_type = 'portfolio'` filtresine sahip DEĞİLDİR! Veritabanındaki en son snapshot bir kotasyon veya işlem mühürlemesi olduğunda, `position_observations` tablosunda o snapshot kimliğine ait hiçbir kayıt bulunamadığından yedek sorgu da sıfır satır dönmektedir.
- **Veri Kaynağı Gerçeği (`masa.db`):**  
  `snapshots` tablosundaki son portföy mührü `run_20261101T114810Z_70f907_portfolio` kimliğine sahiptir. Bu mühür altında `position_observations` tablosunda tam **4 adet menkul kıymet** yer almaktadır (örnek sentetik değerler):
  - `IE00B3YLTY66` (SPYI): 100 adet, 12,000 €, Piyasa Değeri: **1.200,00 €**
  - `IE00BKM4GZ66` (IS3N): 50 adet, 40,000 €, Piyasa Değeri: **2.000,00 €**
  - `IE00BP3QZ825` (IS3R): 25 adet, 40,000 €, Piyasa Değeri: **1.000,00 €**
  - `IE00BP3QZB59` (IS3S): 20 adet, 40,000 €, Piyasa Değeri: **800,00 €**  
  **Örnek Toplam Portföy Değeri:** `1.200,00 + 2.000,00 + 1.000,00 + 800,00 = 5.000,00 €`'dur.
- **Yeni Arayüzdeki Çözüm ve Düzeltme Kuralı:**  
  1. `CROSS JOIN` kesinlikle yasaklanmıştır. Pozisyonlar ve kotasyonlar birbirinden bağımsız alt sorgularla birleştirilmelidir (`LEFT JOIN quotes q ON q.isin = p.isin AND q.snapshot_id = (SELECT snapshot_id FROM snapshots WHERE snapshot_type = 'quotes' ORDER BY rowid DESC LIMIT 1)`).
  2. Fallback sorgusu mutlaka `WHERE snapshot_type = 'portfolio'` koşulunu içermelidir.
  3. UI katmanında pozisyon sayısı > 0 ve değer > 0 olduğu anlık olarak doğrulanmadan asla "Pozisyon Yok" kartı render edilmeyecektir.

---

#### U2: Bugün Başlangıç Akışında Yanıltıcı Yeşil Onay Adımları

- **Belirti ve Kullanıcı Deneyimi Etkisi:**  
  Kullanıcı Bugün ekranında "Sabah Akışını Çalıştır" butonuna bastığında, 1. Adım (Oturum), 2. Adım (Portföy Verisi) ve 3. Adım (Geçmiş Seriler) yeşil onay işaretiyle (✓) "Başarılı" olarak tamamlanmaktadır. Ancak hemen altındaki Portföy kartında "0 Pozisyon, 0,00 €" yazmaya devam etmektedir. Başarılı gösterilen bir adımın sıfır sonuç üretmesi kullanıcıda arayüzün kandırıcı olduğu hissini uyandırmaktadır.
- **Kök Neden (Kod Satırı):**  
  Dosya: `Features/Today/TodayDashboardViewModel.swift`, satır 375–440 (`runFullMorningFlow()`) ve `Features/Today/TodayDashboardView.swift`, satır 262–345.  
  ViewModel içindeki `completeStep(stepId:status:)` fonksiyonu yalnızca CLI sürecinin işletim sistemi çıkış kodunu (`exitCode == 0`) kontrol etmektedir:
  ```swift
  if result.exitCode == 0 {
      step.status = .success(exitCode: 0)
  }
  ```
  CLI komutunun döndürdüğü JSON yükünün içeriği (örneğin çekilen pozisyon sayısı, mühürlenen kayıt adedi) kontrol edilmemektedir. `sc` oturumu kapalı veya boş bir JSON listesi dönse dahi komut hatasız kapandığı için adım yeşile boyanmaktadır.
- **Veri Kaynağı Gerçeği (`masa.db`):**  
  Veri çekme işlemi tamamlandığında veritabanında `snapshots` tablosuna yeni bir satır eklenmeli ve bu snapshot `raw_objects` üzerinden doğrulanmalıdır. Eğer yeni snapshot üretilmemişse işlem gerçekte yeni veri getirmemiştir.
- **Yeni Arayüzdeki Çözüm ve Düzeltme Kuralı:**  
  1. Çıkış kodu tek başına başarı kriteri olamaz. Adımın yeşil tik (✓) alabilmesi için hem `exitCode == 0` olmalı, hem de ilgili veritabanı tablosunda en az 1 yeni veya güncel kayıt doğrulanmalıdır.
  2. Eğer çıkış kodu 0 olmasına rağmen dönen veri kümesi boşsa adım "Kısmi Başarılı / Veri Boş" sarı uyarı ikonu (⚠) ile gösterilmeli; altına "0 pozisyon alındı" açıklaması yazılmalıdır.

---

#### U3: İşlem Defterinde 3 İşlem ve 0,00 € Alış Toplamı Hatası

- **Belirti ve Kullanıcı Deneyimi Etkisi:**  
  İşlem Defteri (⌘2) açıldığında kullanıcı "3 İşlem Kayıtlı", "Alış Toplamı: 0,00 €" ve "Satış Toplamı: 0,00 €" görmektedir. Oysa kullanıcı portföyündeki 4 ETF için aylardır onlarca alım yapmış ve tasarruf planı işletmiştir. Kullanıcı geçmiş işlemlerinin kaybolduğunu zannetmektedir.
- **Kök Neden (Kod Satırı ve SQL Sorgusu):**  
  Dosya: `macos/Sources/ETFCockpit/Core/Database/DatabaseService.swift`, satır 803–844 (`fetchTransactions()` fonksiyonu).  
  Sorgu:
  ```sql
  SELECT tv.version_id AS record_id, ... FROM v_transactions_current tv
  UNION ALL
  SELECT 'obs_' || tx.tx_row_id AS record_id, ... FROM transaction_observations tx
  WHERE NOT EXISTS (SELECT 1 FROM transaction_versions)
  ORDER BY event_time DESC LIMIT 100;
  ```
  Buradaki `WHERE NOT EXISTS (SELECT 1 FROM transaction_versions)` koşulu ölümcül bir mantık hatasıdır. `transaction_versions` tablosunda **tek bir kayıt dahi varsa**, `NOT EXISTS` koşulu `FALSE` olmakta ve `transaction_observations` tablosundaki yüzlerce kayıt tamamen filtrelenmektedir!  
  Veritabanında `transaction_versions` tablosunda yalnızca 3 adet mühürlenmiş nakit işlemi (FEE, DEPOSIT, WITHDRAWAL) bulunmaktadır. Bu 3 işlemde hiçbir `BUY` işlemi yer almadığı için `TransactionLedgerViewModel.swift:147-152` toplam alış tutarını `0,00 €` hesaplamaktadır.
- **Veri Kaynağı Gerçeği (`masa.db`):**  
  `transaction_observations` tablosunda tam **626 adet işlem gözlemi** (614 tekil `broker_tx_id`) mevcuttur:
  - 199 adet `SECURITY_TRANSACTION` / `BUY` / `SETTLED` (Tamamlanan alışlar)
  - 172 adet `SECURITY_TRANSACTION` / `SELL` / `SETTLED` (Tamamlanan satışlar)
  - 64 adet `CASH_TRANSACTION` / `SETTLED` (Nakit hareketleri)
  - Kalanlar: İptal ve reddedilen emirler.  
  *İki Ayrı Finansal Metrik:*
  - **Tarihsel Kümülatif Alış Hacmi:** 199 tamamlanmış alış işleminin toplam tarihi nakit çıkışı **-250.793,98 €**'dur (`SUM(amount) WHERE side='BUY' AND status='SETTLED'`). Bu değer kullanıcının broker hesabındaki tüm tarihsel alış cirosudur.
  - **Portföy Maliyet Tabanı:** Mevcut açık 4 pozisyonun (örnek: 100 SPYI, 50 IS3N, 25 IS3R, 20 IS3S) defter maliyet toplamı **5.000,00 €**'dur ($\sum quantity \times broker\_cost\_basis$).
  Bu iki metrik asla birbirine karıştırılmamalı, arayüzde ayrı göstergeler olarak sunulmalıdır.
- **Yeni Arayüzdeki Çözüm ve Düzeltme Kuralı (Çoğullama Tuzağı ve Tekilleştirme):**  
  1. `WHERE NOT EXISTS` koşulu kaldırılacaktır. Ancak sadece `WHERE NOT EXISTS` kaldırılıp kör bir `UNION ALL` yapılırsa, `transaction_versions` tablosundaki 3 işlem `transaction_observations` tablosunda da 5'er kez gözlemlendiği için ekranda 6'şar kez tekrarlanır; ayrıca 12 adet mükerrer snapshot gözlemi listeyi bozar.
  2. Mükerrerliği önleyen tekilleştirilmiş (deduplicated) birleştirme sorgusu kullanılacaktır:
     ```sql
     SELECT tv.version_id AS record_id, tv.broker_tx_id, tv.tx_type, tv.sub_type, tv.side, tv.isin, tv.amount, tv.event_time, 'SEALED_VERSION' AS source_layer
     FROM v_transactions_current tv
     UNION ALL
     SELECT 'obs_' || MIN(tx.tx_row_id) AS record_id, tx.broker_tx_id, tx.tx_type,
            COALESCE(tx.security_transaction_type, tx.cash_transaction_type) AS sub_type,
            tx.side, tx.isin, tx.amount, tx.event_time, 'OBSERVATION' AS source_layer
     FROM transaction_observations tx
     WHERE tx.broker_tx_id NOT IN (SELECT broker_tx_id FROM transaction_versions)
     GROUP BY tx.broker_tx_id
     ORDER BY event_time DESC;
     ```
  3. **Şema Kolon Düzeltmesi:** `transaction_observations` tablosunda `sub_type` kolonu **yoktur** (`Parse error: no such column: sub_type`). Ham gözlemlerde alt tipler `cash_transaction_type` ve `security_transaction_type` kolonlarında tutulur (`sub_type` yalnızca `v_transactions_current` view'ında ve `transaction_versions` tablosunda bulunur). Bu nedenle gözlem satırlarında `COALESCE(security_transaction_type, cash_transaction_type)` ifadesi kullanılacaktır.
  4. İşlem defteri istatistik barında *"Tarihsel Alış Hacmi: -250.793,98 € (199 İşlem)"* ve Portföy özetinde *"Maliyet Tabanı: 5.000,00 € (4 Açık Pozisyon)"* olarak iki ayrı metrik bağımsız kartlarda raporlanacaktır.

---

#### U4: İşlem Defterinde 4 Sahte Yeşil Mutabakat Kartı ("Eşleşti / %100")

- **Belirti ve Kullanıcı Deneyimi Etkisi:**  
  İşlem defteri ekranının üst kısmında yer alan "1. Hisse Adedi Mutabakatı", "2. Nakit Mutabakatı", "3. Değerleme Mutabakatı" ve "4. Maliyet Tabanı Mutabakatı" kartlarının dördü de parlak yeşil renkle "Eşleşti" ve "%100 Uyum" göstermektedir. Ancak veritabanında henüz tek bir mutabakat koşusu dahi yapılmamıştır. Bu durum denetim ciddiyetini yok etmektedir.
- **Kök Neden (Kod Satırı):**  
  Dosya: `Features/Ledger/TransactionLedgerView.swift`, satır 208–251 (`reconciliationKpiSection`) ve `TransactionLedgerViewModel.swift`, satır 175–178.  
  Görünüm kodunda nil-coalescing operatörü kötüye kullanılmıştır:
  ```swift
  let rec = viewModel.latestReconciliation
  MetricCardView(
      title: "1. Hisse Adedi Mutabakatı",
      value: rec?.sharesMatch ?? true ? "Eşleşti" : "Uyumsuz",
      badgeColor: rec?.sharesMatch ?? true ? .green : .red
  )
  ```
  `latestReconciliation` veritabanında kayıt olmadığı için `nil` dönmektedir. `rec?.sharesMatch ?? true` ifadesi ise değer nil olduğunda otomatik olarak `true` üretmekte ve kartı sahte yeşil "Eşleşti" yapmaktadır.
- **Veri Kaynağı Gerçeği (`masa.db`):**  
  `reconciliations` tablosunda canlı satır sayısı tam olarak **0'dır (SIFIR)**. Sistemde bugüne kadar hiçbir 4 boyutlu mutabakat mühürlenmemiştir.
- **Yeni Arayüzdeki Çözüm ve Düzeltme Kuralı (Sıfır Sahte Durum Kuralı):**  
  1. Hiçbir finansal veya denetimsel metrik `?? true` ile varsayılan olumlu duruma bağlanamaz.
  2. Eğer `latestReconciliation == nil` ise:
     - Değer metni: `"Çalıştırılmadı"`
     - Kart rengi / rozeti: Nötr Gri (`Color.secondary`)
     - Alt bilgi: `"Henüz mutabakat yapılmadı · [Şimdi Çalıştır]"`

---

#### U5: Bütünlük Ekranındaki Durum Çelişkileri ("TEST EDİLMEDİ" vs "MATCH_SEALED")

- **Belirti ve Kullanıcı Deneyimi Etkisi:**  
  Uygulamanın üst araç çubuğunda yeşil kalkan ikonuyla `MATCH_SEALED` rozeti parlamaktadır. Ancak kullanıcı Bütünlük (⌘6) ekranına tıkladığında; Genel Bütünlük kartında turuncu renkle "TEST EDİLMEDİ", Snapshot Mühürleri kartında "0 Mühürlü Snapshot", Zincir Durumu kartında "UNKNOWN" ve Denetim Olayları kartında "100 olay" görmektedir. Kullanıcı sistemin güvenli mi yoksa arızalı mı olduğunu anlayamamaktadır.
- **Kök Neden (Kod Satırları):**  
  Dosyalar: `Features/Integrity/SystemIntegrityViewModel.swift:56-80, 124-136`, `SystemIntegrityView.swift:174-207` ve `App/CockpitAppState.swift:34-36`.  
  1. `SystemIntegrityViewModel.loadData()` fonksiyonu sayfa açılışında sadece `databaseService.fetchAuditEvents(limit: 100)` sorgusunu çalıştırmaktadır. `integrityResult` model nesnesi `nil` bırakılmaktadır.
  2. Arayüzde `integrityResult?.snapshotsCount ?? 0` yazıldığı için snapshot sayısı "0" çıkmaktadır.
  3. `auditEvents.count` yazıldığı ve SQL sorgusu `LIMIT 100` içerdiği için olay sayısı gerçeği değil, limit değerini (100) göstermektedir.
  4. `CockpitAppState.swift` ise üst araç çubuğuna hiçbir doğrulama yapmadan statik olarak `auditStatusText = "MATCH_SEALED"` değerini basmaktadır.
- **Veri Kaynağı Gerçeği (`masa.db`):**  
  - `snapshots` tablosunda **65 adet** kriptografik mühürlü snapshot vardır.
  - `audit_events` tablosunda **147 adet** SHA-256 hash zincirli denetim olayı kayıtlıdır.
  - Hash zinciri `00000...` başlangıç kökünden son olaya kadar matematiki olarak sağlamdır.
- **Yeni Arayüzdeki Çözüm ve Düzeltme Kuralı:**  
  1. Üst araç çubuğu asla statik `MATCH_SEALED` göstermeyecektir; başlangıçta "Doğrulanıyor..." nötr durumu alacaktır.
  2. Bütünlük ekranı açıldığında doğrudan SQLite üzerinden `SELECT COUNT(*) FROM snapshots` (65) ve `SELECT COUNT(*) FROM audit_events` (147) sorgularını çekecektir.
  3. Zincir durumu, CLI doğrulama sonucu (`./etf-masa dogrula`) ile reaktif senkronize edilecektir.

---

#### U6: Canlı Veritabanındaki Test Tezi Verisi

- **Belirti ve Kullanıcı Deneyimi Etkisi:**  
  Yatırım Tezleri ekranında tek bir kart görünmektedir:  
  `Küresel 🚀 ETF Tezi: "Tek Dünya, Tek Fon" --json flag testi`  
  Açıklamasında emoji bulunmakta ve hedef ağırlık olarak `%0.5` yazmaktadır. Gerçek bir yatırım portföyünde %0.5 hedef ağırlıklı bir birikim tezi mantıksızdır. Kullanıcı sistemin test modunda kaldığını düşünmektedir.
- **Kök Neden (Kod Satırı):**  
  Dosya: `Features/Thesis/ThesisManagementView.swift` ve `masa/src/masa/cli.py`.  
  Geliştirme aşamasında `--json` bayrağının CLI çıktısını doğrulamak amacıyla canlı veritabanına `akif` kullanıcısı tarafından test kaydı girilmiştir. Veritabanında değişmezlik (append-only) tetikleyicileri devrede olduğu için `DELETE` çalıştırılamamış ve test tezi canlı ortamda kalmıştır. Ayrıca hedef ağırlık girilirken `0.45` (%45) değeri sistem tarafından `0.005` (%0.5) olarak yanlış normalleştirilmiştir.
- **Veri Kaynağı Gerçeği (`masa.db`):**  
  `thesis_versions` tablosunda `th_5aab39e8bc85` kimlikli tek bir kayıt mevcuttur. Başlığı `'Küresel 🚀 ETF Tezi: "Tek Dünya, Tek Fon" --json flag testi'`, hedef tahsis yüzdesi kolonu `target_allocation_pct = '0.45'` (%45) ve ISIN'ı `IE00B3YLTY66`'dır (Not: Tabloda `target_weight` adında bir kolon yoktur; doğru şema kolonu `target_allocation_pct`'dir).
- **Yeni Arayüzdeki Çözüm ve Düzeltme Kuralı:**  
  1. SQLite tablosundaki bu sürüm doğrudan silinemez (append-only kuralı). Ancak CLI üzerinden `SUPERSEDED` veya `ARCHIVED` statüsüne geçirilmelidir.
  2. Arayüzde "Test Kayıtlarını Gizle" filtresi eklenecek, başlığında `test`, `--json` veya `flag` geçen kayıtlar üretim görünümünden filtrelenebilecektir.
  3. Hedef ağırlık formunda girilen değerlerin (0.00–1.00 aralığı ile 0–100% aralığı) `target_allocation_pct` normalizasyonu katı biçimde doğrulanacaktır.

---

#### U7: Fırsat Taraması Ekranı Açıldığı Anda Tetiklenen Canlı Tarama Koşusu

- **Belirti ve Kullanıcı Deneyimi Etkisi:**  
  Kullanıcı sadece kenar çubuğundan Fırsat Taraması sekmesine tıkladığında arayüz birkaç saniye kilitlenmekte, fanlar hızlanmakta ve Bütünlük denetim günlüğünde arka arkaya yeni olaylar belirmektedir. Bir sayfayı görüntülemenin sisteme kalıcı veri yazması kabul edilemez bir yan etkidir.
- **Kök Neden (Kod Satırı ve Teknik Teşhis):**  
  Dosya: `Features/Screener/ScreenerView.swift`, satır 32–34 ve `ScreenerViewModel.swift`, satır 32–53.  
  SwiftUI görünümünün `.task { await viewModel.loadData() }` bloğu, doğrudan SQLite sorgusu yapmak yerine `cliRunner.runCommand(arguments: ["tarama", "--son", "--json"])` komutunu tetiklemektedir. `tarama --son` parametresi veritabanından son mühürlü sonucu salt-okunur çeken bir komut olsa da, sayfa açılışında tam teşekküllü bir Python CLI subprocess'i başlatılması ana iş parçacığını zorlamakta ve arayüzde gecikmeye yol açmaktadır. Canlı tarama komutu (`["tarama", "--json"]`) ise harici kotasyonları çekerek veritabanına #144 (`RUN_STARTED`) ve #145 (`RUN_SEALED`) denetim olaylarını mühürlemektedir.
- **Veri Kaynağı Gerçeği (`masa.db`):**  
  Veritabanı denetim kütüğünde 1 Kasım 15:04:18 ve 15:20:35 tarihlerinde sırf ekran tıklandı diye tetiklenmiş 2 adet gereksiz tarama mührü bulunmaktadır.
- **Yeni Arayüzdeki Çözüm ve Düzeltme Kuralı (Salt-Okunur Gezinme İlkesi):**  
  1. Kenar çubuğunda hiçbir sekmeye geçiş veya sayfa açılışı ASLA bir CLI yazma sürecini veya alt süreci (subprocess) tetikleyemez.
  2. Sayfa ilk açıldığında CLI subprocess'i başlatmak yerine doğrudan Swift SQLite servis katmanı üzerinden en son tamamlanmış taramanın önbellekteki verileri (`SELECT payload_json FROM audit_events WHERE actor = 'masa.scanner' ORDER BY event_id DESC LIMIT 1`) sıfır gecikmeyle ve salt-okunur olarak yüklenecektir.
  3. Canlı tarama (`masa tarama --json`) sadece ve sadece kullanıcının araç çubuğundaki **"Şimdi Tara"** butonuna açıkça tıklamasıyla başlatılacaktır.

---

#### U8: Bütünlük Ekranındaki Yedek Şişmesi Sorunu

- **Belirti ve Kullanıcı Deneyimi Etkisi:**  
  Bütünlük ekranında son yedekler listelendiğinde 13:59, 14:11, 14:17 gibi birkaç dakika arayla alınmış onlarca yedek görünmektedir. Disk üzerinde yedek klasörünün boyutu kontrolsüz biçimde yüzlerce megabayta tırmanmaktadır.
- **Kök Neden:**  
  `etf-masa` CLI mimarisinde her veri çekme, mühürleme ve test işleminden önce emniyet amacıyla tam bir SQLite veritabanı kopyası (`.db`) alınmaktadır. Ancak `politika.json` dosyasında tanımlanan saklama ve budama kuralları (`rotasyon: gunluk 7, haftalik 4, aylik 12`) otomatik bir temizlik iş parçacığı tarafından işletilmemektedir.
- **Veri Kaynağı Gerçeği (Disk Boyutu):**  
  - `masa/var/private/masa.db` boyutu: **3,7 MB**
  - `masa/var/backups/` dizininde tam **89 adet `.db` yedeği** birikmiş ve toplam boyut **231 MB**'a ulaşmıştır.
- **Yeni Arayüzdeki Çözüm ve Düzeltme Kuralı:**  
  1. Yeni Sistem (⌘6) ekranına "Yedek Depolama Yöneticisi" eklenecektir.
  2. Ekranda disk tüketimi (231 MB) bir uyarı bandı ile gösterilecek ve "Politikaya Göre Temizle (Prune)" butonu sunulacaktır.
  3. Yedek alma işleminden sonra otomatik budama mekanizması çağrılarak 7 günden eski günlük yedeklerin otomatik silinmesi sağlanacaktır.

---

#### U9: Üst Çubuktaki Xetra Açılış Saati Hatası

- **Belirti ve Kullanıcı Deneyimi Etkisi:**  
  Hafta sonu veya borsa kapandıktan sonra üst araç çubuğunda "Pazartesi 09:30 CET Bekleniyor" veya "Yarın 09:30 CET Bekleniyor" yazmaktadır. Xetra borsasında işlem yapan bir yatırımcı borsanın 09:00 CET'de açıldığını bildiği için arayüzün borsa saatlerinden habersiz olduğunu düşünmektedir.
- **Kök Neden (Kod Satırı):**  
  Dosya: `Components/LiveSessionTimerView.swift`, satır 67–91 (`nextEventInfo` hesaplama özelliği).  
  Satır 50'de Xetra açılış saati `xetrOpenSeconds = 9 * 3600` (09:00 CET) olarak doğru tanımlanmışken; satır 69 ve 89'da piyasa açılışı ile sabah tahmin motoru koşusu (09:30 CET) birbirine karıştırılmış ve metin olarak `"Pazartesi 09:30 CET Bekleniyor"` yazılmıştır.
- **Yeni Arayüzdeki Çözüm ve Düzeltme Kuralı:**  
  Piyasa açılış saati ile analitik motor saatleri birbirinden kesin olarak ayrılacaktır:  
  Metin formatı: `"XETRA Açılışı: Pazartesi 09:00 CET · Sabah Tahmini: 09:30 CET"`.

---

#### U10: Fırsat Taramasındaki Z-Skorunun "1.17 / 10.0" Olarak Gösterilmesi

- **Belirti ve Kullanıcı Deneyimi Etkisi:**  
  Fırsat taraması detay çekmecesinde Apple Inc. için "Tarama Skoru: 1.17 / 10.0" yazmakta ve turuncu renkle "düşük/başarısız" gibi gösterilmektedir. Hemen yanında ise yeşil rozetle "ARAŞTIRMAYA DEĞER" tavsiyesi yer almaktadır. Kullanıcı 10 üzerinden 1.17 alan bir varlığın neden tavsiye edildiğini anlayamamakta, bariz bir çelişki görmektedir.
- **Kök Neden (Kod Satırı):**  
  Dosya: `Features/Screener/ScreenerView.swift`, satır 201 ve 294–299.  
  Kod satırı:
  ```swift
  Text(item.score != nil ? String(format: "%.2f / 10.0", item.score!) : "Hesaplanmadı")
  ```
  Sistem algoritmasının ürettiği değer istatistiksel bir bileşik **Z-Skorudur** (ortalama 0, standart sapma 1). Tipik değerler -3.0 ile +3.0 arasında değişir. Geliştirici bu metriği lise karne notu zannederek `/ 10.0` formatlamış ve 5.0'ın altında kaldığı için turuncu renkle tehlikeye boyamıştır.
- **Veri Kaynağı Gerçeği (`masa.db` ve CLI):**  
  Son mühürlü taramada Apple'ın skoru **+1.1713 σ**'dır. Bu skor havuzdaki 17 enstrüman arasındaki en yüksek risk-düzeltilmiş getiri ve momentum değerini temsil etmekte olup son derece güçlü bir pozitif sinyaldir.
- **Yeni Arayüzdeki Çözüm ve Düzeltme Kuralı:**  
  1. `/ 10.0` formatı derhal kaldırılacaktır.
  2. Metrik `+1.17 σ (Z-Skor)` olarak gösterilecektir.
  3. Renk skalası Gaussian normal dağılıma göre ayarlanacaktır:  
     $Z \ge +1.0$ Yeşil (Güçlü Pozitif), $0.0 \le Z < +1.0$ Mavi (Pozitif), $-1.0 \le Z < 0.0$ Nötr Gri, $Z < -1.0$ Kırmızı (Negatif).

---

#### U11: Segmented Picker'larda "Görünüm" Kelimesinin Dikey Kırılması

- **Belirti ve Kullanıcı Deneyimi Etkisi:**  
  Tahminler, Model Kaydı, Hedef Sepet ve İşlem Defteri ekranlarında üstteki segment seçicinin solunda "G-ö-r-ü-n-ü-m" harfleri dikey olarak alt alta kırılmakta ve görsel olarak son derece çirkin bir görüntü oluşturmaktadır.
- **Kök Neden (Kod Satırı):**  
  Dosyalar: `ForecastSettlementView.swift:210`, `ModelRegistryView.swift:237`, `TargetBasketOverlapView.swift:194`.  
  Kod:
  ```swift
  Picker("Görünüm", selection: $viewModel.selectedSegment) { ... }
      .pickerStyle(.segmented)
      .frame(width: 360)
  ```
  macOS SwiftUI motorunda `.segmented` picker stili başlık etiketini ("Görünüm") denetimin soluna yerleştirir. Bileşene sabit genişlik (`.frame(width: 360)`) verildiğinde segment butonları genişliğin tamamına yakınını tüketir ve sol etikete yalnızca ~10 piksel alan kalır. SwiftUI metni sığdıramayınca harfleri dikeyde tek tek böler.
- **Yeni Arayüzdeki Çözüm ve Düzeltme Kuralı:**  
  Tüm segmented picker'lara `.labelsHidden()` niteleyicisi eklenecek veya `Picker("", ...)` kullanılarak sol etiket alanı sıfırlanacaktır.

---

#### U12: Tablolarda Solda ~400 px Boş Sütun Oluşması

- **Belirti ve Kullanıcı Deneyimi Etkisi:**  
  Model Kaydı, İşlem Defteri, Araştırma ve Hedef Sepet ekranlarındaki tablolarda veriler pencerenin en sağına sıkışmakta; tablonun sol tarafında ise yaklaşık 400 piksellik devasa, boş, gri bir alan oluşmaktadır.
- **Kök Neden (Kod Satırı):**  
  Dosyalar: `ModelRegistryView.swift:404`, `TargetBasketOverlapView.swift:350, 618`, `TransactionLedgerView.swift:378`.  
  macOS SwiftUI'da `Table` bileşeni kullanılırken her `TableColumn` için açık bir genişlik (`.width(min:ideal:max:)`) tanımlanmadığında veya seçim (`selection:`) bağlanmadığında, AppKit alt katmanındaki `NSTableView` ilk sütunu pencerenin tüm boşluğunu dolduracak şekilde anormal genişletmektedir.
- **Yeni Arayüzdeki Çözüm ve Düzeltme Kuralı:**  
  1. Tablolardaki tüm `TableColumn` tanımlarına açık `.width(min:ideal:max:)` verilecektir.
  2. Veya Portföy ekranında başarıyla uygulandığı gibi, dikey `ScrollView` içinde esnek ve piksel kontrollü `Grid` / `HStack` kart satırı mimarisine geçilecektir.

---

#### U13: Hedef Sepet Ekranında Terminal Komutu Gösterilmesi

- **Belirti ve Kullanıcı Deneyimi Etkisi:**  
  Hedef Sepet ekranında fon bileşenlerini yüklemek isteyen bir kullanıcıya arayüzde bir buton veya dosya seçici sunulmamakta; bunun yerine ekranın ortasında şu metin gösterilmektedir:  
  `Terminalden sepet yüklemek için: ./etf-masa sepet yukle --dosya <dosya_yolu> --isin <ISIN>`  
  Bu durum yerel bir macOS uygulamasının varlık amacıyla çelişmektedir.
- **Kök Neden:**  
  Dosya: `Features/Basket/TargetBasketOverlapView.swift`, satır 236–244. Arayüz geliştiricisi dosya seçici entegrasyonunu tamamlamadığı için placeholder olarak CLI komut şablonunu ekrana basmıştır.
- **Yeni Arayüzdeki Çözüm ve Düzeltme Kuralı:**  
  Metin kaldırılacak; yerine macOS yerel `NSOpenPanel` veya SwiftUI `.fileImporter(isPresented:allowedContentTypes:)` bileşeni ile çalışan **"Fon Sepeti CSV/JSON Yükle"** yerel butonu yerleştirilecektir.

---

#### U14: Hedef Sepet Ekranındaki "UCITS 5/10/40" Uyum Kartı Hatası

- **Belirti ve Kullanıcı Deneyimi Etkisi:**  
  Kullanıcı Hedef Sepet ekranına girdiğinde üstte kıpkırmızı bir kartla "UCITS 5/10/40 Uyum İhlali Tespiti!" uyarısı almaktadır. Kullanıcı yasa dışı bir işlem yaptığını veya portföyünün regülasyona aykırı olduğunu düşünerek tedirgin olmaktadır.
- **Kök Neden (Finansal Domain Hatası):**  
  Dosya: `Features/Basket/TargetBasketOverlapView.swift`, satır 86–90, 128–147.  
  UCITS 5/10/40 kuralı, yatırım fonu ihraç eden portföy yöneticileri (BlackRock, Vanguard vb.) için geçerli bir yasal çeşitlendirme kuralıdır. Bireysel bir yatırımcının kendi hesabında tek bir dünya ETF'ini (örneğin %45 ağırlıkla SPYI) tutması kesinlikle hiçbir regülasyona aykırı değildir. Kurumsal fon kuralı bireysel portföye hatalı olarak uygulanmıştır.
- **Yeni Arayüzdeki Çözüm ve Düzeltme Kuralı:**  
  1. Bireysel portföy genelinde yanıltıcı "UCITS 5/10/40 İhlali" kartı ve alarmı kaldırılacaktır.
  2. Yerine bireysel yatırımcı için anlamlı olan **"Konsolide Şirket Yoğunlaşması"** ve **"Tekil Hisse Maruziyeti (>%15)"** risk göstergesi konulacaktır.

---

#### U15: Model Kaydı Ekranındaki Doğrulanmamış Güvenceler

- **Belirti ve Kullanıcı Deneyimi Etkisi:**  
  Model Kaydı ekranında üstte "0,00 € · ZERO COST" ve "%100 GÜVENLİ" yeşil etiketleri yer almaktadır. Ancak hemen altındaki tabloda listelenen 5 yapay zeka modelinin tamamının durumunda gri rozetle "DOĞRULANMADI" yazmaktadır. Doğrulanmamış modeller için peşinen sıfır maliyet ve %100 güvenlik garantisi vermek sistemin denetim ciddiyetini zedelemektedir.
- **Kök Neden (Kod Satırı):**  
  Dosya: `Features/ModelsRegistry/ModelRegistryView.swift`, satır 145–163. Metrik kartları veritabanından dinamik değer okumak yerine statik metin olarak `"0,00 €"` ve `"%100 GÜVENLİ"` hardcode edilmiştir.
- **Veri Kaynağı Gerçeği (`masa.db`):**  
  `model_evaluations` tablosu tamamen BOŞTUR (0 kayıt). `gemini-1.5-pro` modelinin API maliyeti henüz test edilip ölçülmemiştir.
- **Yeni Arayüzdeki Çözüm ve Düzeltme Kuralı:**  
  1. Statik güvence metinleri yasaklanmıştır.
  2. Model değerlendirme tablosunda kayıt yoksa kartta `"Ölçülmedi"` nötr gri rozeti gösterilecektir.
  3. Modeller doğrulanıp harcanan token/maliyet kaydedildiğinde gerçek maliyet dinamik olarak yansıtılacaktır.

---

#### U16: Alt Durum Çubuğundaki Kişisel Dosya Yolu Sızıntısı

- **Belirti ve Kullanıcı Deneyimi Etkisi:**  
  Uygulamanın alt durum çubuğunda ve üzerine gelindiğinde açılan tooltip'te doğrudan şu metin görünmektedir:  
  `~/Documents/ETF/masa/var/private/masa.db`  
  Kullanıcının adı, soyadı ve bilgisayar dosya yapısı ekranda kabak gibi görünmektedir. Ekran görüntüsü paylaşıldığında kişisel gizlilik ihlal edilmektedir.
- **Kök Neden (Kod Satırı):**  
  Dosya: `App/CockpitShellView.swift`, satır 212 ve 218:
  ```swift
  Text(appState.databasePath)
      .help("Veritabanı yolu: \(appState.databasePath)")
  ```
- **Yeni Arayüzdeki Çözüm ve Düzeltme Kuralı (Gizlilik ve HIG Kuralı):**  
  1. Alt durum çubuğunda tam dosya yolu kesinlikle gösterilmeyecektir.
  2. Çubukta yalnızca sembolik ve temiz bir durum rozeti yer alacaktır: `Masa.db (v3 · 78 Tetikleyici Aktif)`.
  3. Dosya yolunun tam metni yalnızca Ayarlar (⌘6) > Hakkında bölümünde, `NSHomeDirectory()` kısmı `~` ile maskelenerek (`~/Documents/ETF/...`) ve isteğe bağlı kopyalama butonuyla sunulacaktır.


---

## Bölüm 2: Tasarım İlkeleri ve Veri Dürüstlüğü Anayasası

ETFCockpit v2 yeniden tasarımı, kullanıcı arayüzünü yalnızca estetik bir kabuk olarak değil; finansal doğruluğun, matematiksel dürüstlüğün ve adli denetlenebilirliğin tavizsiz bir kalesi olarak konumlandıran **7 temel anayasal ilkeye** dayanmaktadır.

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                        VERİ DÜRÜSTLÜĞÜ ANAYASASI (7 İLKE)                              │
├────────────────────────────────────────────────────────────────────────────────────────┤
│ 1. SIFIR SAHTE DURUM (ZERO FAKE STATE)                                                 │
│    Veri yoksa asla yeşil tik, "Eşleşti", "Başarılı" basılamaz. Nötr gri ve neden.     │
│                                                                                        │
│ 2. VERİ KÖKENİ VE TAZELİK (PROVENANCE & FRESHNESS)                                     │
│    Her sayının yanında doğum tarihi ve mühürlü kaynak ID'si yer alır (●, ◐, ○).        │
│                                                                                        │
│ 3. N < 30 KÜÇÜK ÖRNEKLEM KORUMASI (SAMPLE SIZE INTEGRITY)                              │
│    Gözlem sayısı N < 30 iken ampirik güven "—" olarak katı biçimde baskılanır.        │
│                                                                                        │
│ 4. KARAR DESTEĞİ VE EMNİYET BARİYERİ (DECISION SUPPORT ONLY)                          │
│    Sistem önerir, insan karar verir; arayüz asla broker'a doğrudan emir iletemez.      │
│                                                                                        │
│ 5. KİŞİSEL GİZLİLİK VE VERİ İZOLASYONU (PRIVACY BY DESIGN)                             │
│    Dosya yolları maskelenir (~/...), API key UI kaldırılır, gizlilik modu tek tuşla.  │
│                                                                                        │
│ 6. KADEMELİ AYRINTI VE EYLEM ODAKLI BOŞ DURUM (PROGRESSIVE DISCLOSURE)                 │
│    Boş ekran = "Neden Boş?" + "Ne Yapmalısın?" (Tek tıkla eylem butonu).               │
│                                                                                        │
│ 7. BİLİŞSEL ERGONOMİ VE APPLE HIG UYUMU (NATIVE MACOS)                                 │
│    İP kodlarından arındırılmış Türkçe dil, SF Pro/Mono hiyerarşisi, 3 sütunlu düzen.   │
└────────────────────────────────────────────────────────────────────────────────────────┘
```

---

### 2.1 Sıfır Sahte Durum İlkesi (Zero Fake State)

- **Temel Kural:** "Hiçbir şey varsayılan yeşil değildir." Bir durumun yeşil renk alabilmesi veya olumlu bir ifade ("Eşleşti", "Doğrulandı", "Başarılı") taşıyabilmesi için, arka plandaki veritabanında somut bir kanıtın bulunması zorunludur.
- **Null-Coalescing Yasağı:** Kod katmanında `status ?? true` veya `isMatched ?? true` gibi, verinin yokluğunu olumlu bir sonuca bağlayan programlama kalıpları katı biçimde yasaklanmıştır.
- **Standart Renk Semantiği:**
  - **Yeşil (`Color.green`):** Yalnızca adli olarak kanıtlanmış, doğrulanmış ve beklenen sınırlar içindeki durumlar için kullanılır.
  - **Sarı / Turuncu (`Color.orange`):** Kısmi durumlar, henüz uzlaşmamış tahminler, taslak politikalar veya dikkat gerektiren sapmalar için kullanılır.
  - **Kırmızı (`Color.red`):** Doğrulanmış hata, hash zinciri kopması, tezin çürütülmesi veya mutabakat açığı durumlarında kullanılır.
  - **Nötr Gri (`Color.secondary`):** Henüz çalıştırılmamış, verisi bulunmayan veya ölçülmemiş durumlar için kullanılır. Veri yoksa kart gri renkte `"Çalıştırılmadı"` veya `"Veri Yok"` yazacaktır.

---

### 2.2 Veri Kökeni ve Tazelik İlkesi (Provenance & Freshness)

- **Köken Bilgisi (Data Provenance):** Arayüzde yer alan her bir fiyat, oran veya portföy değerinin altında veya bilgi ipucunda (tooltip), o verinin hangi SQLite tablosundan (`position_observations`, `quotes` vb.) ve hangi mühürlü snapshot'tan (`run_...` veya `scan_...`) geldiği açıkça belirtilir.
- **Üç Kademeli Tazelik Noktası:**
  - **● Canlı (Yeşil Nokta):** Son 15 dakika içinde borsa seansından veya broker API'sinden çekilmiş taze veri.
  - **◐ Kapanış (Mavi/Gri Yarım Nokta):** Son işlem gününün resmi borsa kapanış kotasyonu (XETRA 17:30 CET).
  - **○ Bayat / Stale (Turuncu/Kırmızı Boş Nokta):** 24 saatten daha eski veya borsa açıkken güncellenmemiş gecikmiş veri.
- **İpucu (Tooltip) Standardı:** Fareyle herhangi bir metriğin üzerine gelindiğinde şu formatta mikro-kart açılır:  
  `Kaynak: Scalable Capital · 1 Kas 2026 11:48:10 UTC · Snapshot: run_20261101T114810Z_70f907`

---

### 2.3 N < 30 Küçük Örneklem Güvenilirlik İlkesi

- **İstatistiki Gerçeklik:** Finansal zaman serilerinde 30 günden daha az gözlem içeren veri setlerinde hesaplanan yön isabet oranları veya hata metrikleri istatistiksel olarak anlamsızdır ve aşırı uyuma (overfitting) açıktır.
- **Baskılama Kuralı (Suppression Rule):**  
  Uzlaşmış tahmin sayısı $N < 30$ iken:
  - Model Karnesi ve Varlık Sayfalarındaki ampirik isabet oranı ekranda yüzde olarak gösterilmez; yerine tire işareti **`"—"`** basılır.
  - Altına gri açıklama eklenir: `"N < 30 (Küçük Örneklem) · Ampirik güven bastırıldı (Şu an: N=0/30)"`.
  - Kullanıcıya modelin rastgele mi yoksa anlamlı mı çalıştığının henüz kanıtlanmadığı dürüstçe söylenir.
  - Ancak $N \ge 30$ barajı aşıldığında sayısal yüzde (`%62,4`) görünür hale gelir.

---

### 2.4 Karar Desteği ve Emniyet Ayrımı (Decision Support Only)

- **Yetki Sınırı:** ETFCockpit bir otomatik alım-satım robotu veya broker yürütme terminali değildir; kişisel bir **karar destek sistemidir (Decision Support System)**.
- **Yazma Yolu Yasağı (No Direct Broker Write):** Uygulama hiçbir koşulda Scalable Capital broker altyapısına doğrudan emir gönderme (`order place`, `buy`, `sell`) yetkisine ve koduna sahip olamaz. `sc` istemcisi yalnızca `--local-read-only` bayrağı ile salt-okunur çalıştırılır.
- **Kalıcı Yasal Bilgilendirme:** Kararlar (⌘4) ve Değerlendirme kartlarının üzerinde şu metin kalıcı ve silinemez bir standart bileşen olarak yer alır:  
  `"Bu ekran karar desteğidir; sistem kendi başına işlem yapmaz. Tüm kararlar yatırımcının Scalable Capital mobil uygulamasındaki manuel onayına bağlıdır."`

---

### 2.5 Kişisel Gizlilik ve Veri Güvenliği İlkesi (Privacy by Design)

- **Dosya Yolu Maskeleme:** Arayüzün hiçbir yerinde (başlık, durum çubuğu, log penceresi, hata diyalogları) kullanıcının ev dizini yolu açık metin olarak basılamaz. Tüm yollar `~/Documents/ETF/...` formatında tilde (`~`) ile maskelenir.
- **Gizlilik Modu (Privacy Mode - ⌘⇧P):** Tek bir klavye kısayoluyla (`⌘⇧P` / Cmd+Shift+P — macOS evrensel `⌘P` Yazdır/Print çakışmasını önlemek amacıyla `⌘⇧P` olarak atanmıştır) tüm parasal bakiyeler (örn: 5.000,00 €), pozisyon adetleri ve nakit tutarları `•••• €` şeklinde blurlanarak gizlenir. Bu mod açıkken kullanıcı kamuya açık alanlarda veya ekran paylaşımlarında kokpiti güvenle açabilir.
- **Sıfır Düz Metin Sır (Zero Plaintext Secret):** API anahtarları, şifreler veya kimlik belirteçleri arayüzde asla gösterilmez. Yapılandırma ekranında modellerin erişim durumu yalnızca dosya varlığı (`~/.tradingagents/chatgpt-auth.json: Mevcut`) ve sağlayıcı yetki durumu üzerinden gösterilir.

---

### 2.6 Kademeli Ayrıntı ve Eylem Odaklı Boş Durum İlkesi

- **Kademeli Sunum (Progressive Disclosure):**  
  Kullanıcı ekrana ilk baktığında yalnızca yüksek seviyeli özet metrikleri görür. Bir satıra tıkladığında sağda **İnceleme Paneli (Inspector)** açılır. İnceleme panelindeki "Tüm Sayfayı Aç" butonuna basıldığında ise derinlemesine **Varlık Sayfası (5.7)** veya modal görünüm devreye girer. Teknik hash'ler, JSON yükleri ve SQL run ID'leri en alt katmanda "Ayrıntılar" akordeonu arkasında tutulur.
- **Boş Durum Anayasası (Empty State = Reason + Action):**  
  Hiçbir ekran veya tablo kullanıcıya salt boş beyaz bir alan sunamaz. Her boş durum şu iki unsuru içermek zorundadır:
  1. **Neden Boş?** (Örn: *"Veritabanında henüz uzlaşmış akşam tahmini bulunmuyor."*)
  2. **Ne Yapmalısın?** (Örn: *"Sabah tahminlerini uzlaştırmak için akşam seans kapanışını (17:40 CET) bekleyin veya şimdi bir uzlaşma simülasyonu başlatın."* + **[Uzlaşmayı Çalıştır]** Butonu).

---

### 2.7 Bilişsel Ergonomi ve Apple HIG Standartları

- **Dahili Kodların Temizliği:** Kullanıcıyı ilgilendirmeyen tüm teknik kısaltmalar (`İP-1`, `İP-12` vb.) arayüzden kazınmıştır.
- **Finansal Terimler Standardı:** Borsa ve muhasebe kavramları Türkçeleştirilmiş (Sözlük, Bölüm 8.4); evrensel kabul gören finansal kısaltmalar (ISIN, WAC, FIFO, TER, Sharpe) ise açıklamalı tooltip'lerle desteklenmiştir.
- **Tipografi:** Rakamlar ve parasal tutarlar için basamak kaymasını önleyen `SF Mono` veya `monospacedDigit()` kullanılacak; başlıklar ve etiketler için Apple `SF Pro` font hiyerarşisi uygulanacaktır.

---

## Bölüm 3: Yeni Bilgi Mimarisi (14 Ekran -> 6 Bölüm + Sabitlenmiş Varlıklar)

### 3.1 6 Ana Bölüm Mimarisi

Yeni bilgi mimarisi, yatırımcının günlük ve stratejik karar alma döngüsünü 6 net ana bölümde ve sol kenar çubuğunun altında her an sabit duran bir varlık listesinde toplar.

```
┌────────────────────────────────────────────────────────┐
│              ETFCockpit v2 BİLGİ MİMARİSİ              │
├────────────────────────────────────────────────────────┤
│  KENAR ÇUBUĞU (SIDEBAR)                                │
│  ├── ☀︎  1. BUGÜN      (⌘1) : Günlük Brifing & Akış     │
│  ├── ◔  2. PORTFÖY    (⌘2) : Varlıklar, Defter, 4D Rec │
│  ├── ◎  3. TAHMİNLER  (⌘3) : Tahmin, Uzlaşma & Karne   │
│  ├── ⚖︎  4. KARARLAR   (⌘4) : Tavsiye, Sepet, Tezler    │
│  ├── ⌕  5. KEŞİF      (⌘5) : Tarama, Havuz & Kanıtlar  │
│  └── ⚙︎  6. SİSTEM     (⌘6) : Bütünlük, Yedek & Ayarlar │
│  ────────────────────────────────────────────────────  │
│  SABİTLENMİŞ VARLIKLAR (PINNED ASSETS)                 │
│  ├── SPYI   11,61 €  ▲%0,4  ● [Varlık Sayfası 5.7]    │
│  ├── IS3N   44,82 €  ▼%0,2  ● [Varlık Sayfası 5.7]    │
│  ├── IS3R   97,08 €  ▲%1,1  ● [Varlık Sayfası 5.7]    │
│  └── IS3S   70,11 €  ▲%0,1  ● [Varlık Sayfası 5.7]    │
└────────────────────────────────────────────────────────┘
```

1. **Bugün (⌘1 — Today Cockpit):**  
   Günün operasyonel merkezi. Scalable Capital 2FA oturumu, sabah 6 adımlı veri ve analiz başlangıç akışı, güncel portföy özeti (örn: 5.000,00 €), günün bekleyen tahminleri ve eylem maddeleri.
2. **Portföy (⌘2 — Holdings, Ledger, 4-Way Reconciliation):**  
   Portföyün muhasebesel ve operasyonel omurgası. 4 pozisyonun canlı dökümü, 5'li likidite/nakit kırılımı, 626 satırlık tarihi işlem defteri, 4 boyutlu mutabakat motoru (Hisse, Nakit, Değerleme, Maliyet) ve kurumsal işlemler.
3. **Tahminler (⌘3 — Forecasts, Model Registry, Scorecard):**  
   Tahmin ve model yönetim merkezi. Sabah 09:30 tahminleri, akşam 17:40 uzlaşması, naif modellerle (Martingale ve Momentum) kıyaslamalı Brier skoru ve model karnesi, 5 kayıtlı modelin şampiyonluk durumları.
4. **Kararlar (⌘4 — Decisions, Target Basket, Theses, Reports):**  
   Yatırım stratejisi ve karar destek masası. TUT/EKLE/AZALT tavsiyeleri, hedef sepet ağırlıkları, fonlar arası çiftli örtüşme ısı haritası, Top 25 konsolide şirket maruziyeti, satışsız nakit enjeksiyonu dengeleme simülatörü, yatırım tezleri defteri ve Markdown analitik raporlar.
5. **Keşif (⌘5 — Discovery, Screener, Research Desk):**  
   Piyasa taraması ve araştırma laboratuvarı. Z-skorlu aday ETF taraması, aday detay çekmecesi, Luhn kontrollü havuz yönetimi, resmi kaynak belgelerden birebir alıntılı kanıt paketleri ve Red-Team Critic denetim karnesi.
6. **Sistem (⌘6 — System Integrity, Scheduler, Configuration):**  
   Altyapı, denetim ve konfigürasyon konsolu. 65 mühürlü snapshot ve 147 denetim olayının SHA-256 hash zinciri doğrulaması, yedekleme yöneticisi ve disk budama, launchd zamanlayıcı servisleri, asenkron iş kuyruğu ve `portfoy.json` / `politika.json` yapılandırma editörü.
7. **Sabitlenmiş Varlıklar (5.7 Varlık Detay Sayfası):**  
   Kenar çubuğunun alt kısmında kullanıcının sık takip ettiği 4–8 ETF'in anlık fiyat, getiri ve tazelik hapları yer alır. Tıklandığında ilgili varlığın tüm alt sistemlerdeki verilerini birleştiren bağımsız detay sayfasını açar.

---

### 3.2 Birebir Kayıpsız Eşleme Tablosu (14 Ekrandan 6 Bölüme Geçiş)

Mevcut 14 ekranın içindeki her bir görsel ve işlevsel yeteneğin yeni 6 bölümlü mimarideki kesin adresi ve geliştirme detayları aşağıda eksiksiz olarak dökülmüştür:

| # | Eski Ekran (v1) | Eski Ekrandaki Bileşen / Özellik | Yeni Bölüm ve Alt Sekme (v2) | Korunma & Geliştirme Garantisi |
|---|---|---|---|---|
| **1** | **Today** | 6 adımlı sabah akışı kartı (`startMorningFlow`) | **⌘1 Bugün** / Sabah Akışı Kartı | Çıkış kodu doğrulamasının yanına DB veri teyidi eklendi. |
| | | Scalable 2FA login & Safari linki | **⌘1 Bugün** / Oturum Kartı | Tek tıkla Safari ve Terminal açma desteği korundu. |
| | | Portföy özet KPI'ları (Değer, Nakit, Pozisyon) | **⌘1 Bugün** / Üst Özet Kartları | Canlı 5.000,00 € ve 4 pozisyon verisine bağlandı. |
| | | Mevcut portföy varlıkları tablosu | **⌘1 Bugün** / Çekirdek Varlıklar | Tıklanınca 5.7 Varlık Sayfasını açma özelliği eklendi. |
| | | Canlı veri çekme (`masa veri`) & terminal log akışı | **⌘1 Bugün** / Konsol & Etkinlik Çubuğu | Terminal logları alt durum çubuğuna ve çekmeceye aktarıldı. |
| | | Zamanlayıcı kurulmamış uyarısı (İP-10) | **⌘1 Bugün** / Teşhis Bandı | Tek tıkla launchd kurma eylemine bağlandı. |
| **2** | **Portfolio** | 5 KPI kartı (Değer, Yatırılmış, Nakit, Alım Gücü, K/Z) | **⌘2 Portföy** / Canlı Pozisyonlar | Tüm maliyet temeli ve K/Z hesaplamaları korundu. |
| | | 5'li nakit kırılımı (Settled, Unsettled, Accrued vb.) | **⌘2 Portföy** / Likidite Sekmesi | T+2 takas ve muhtemel vergi satırları korundu. |
| | | Varlık sınıfı ve coğrafi maruziyet barları | **⌘2 Portföy** / Dağılım Sekmesi | Yüzdesel kırılım grafikleri korundu. |
| | | Pozisyon tablosu (Arama, Filtreleme, 7 Sıralama) | **⌘2 Portföy** / Pozisyonlar Tablosu | Satırlar 5.7 Varlık Sayfasına bağlandı. |
| | | Canlı kotasyon tazelik rozeti (FRESH/STALE) | **⌘2 Portföy** / Tablo Hücreleri | Saniye bazlı ISO8601 zaman damgaları eklendi. |
| **3** | **Ledger** | 4 boyutlu mutabakat KPI kartları | **⌘2 Portföy** / Mutabakat Motoru | Sahte yeşil durum (U4) giderilerek gerçek veriye bağlandı. |
| | | Hacim kartları (Alış, Satış, Temettü, Vergi) | **⌘2 Portföy** / İşlem Defteri | 626 işlemin tamamını toplayacak şekilde düzeltildi (U3). |
| | | İşlem defteri tablosu (8 tür filtresi, tarih aralığı) | **⌘2 Portföy** / İşlem Defteri | 626 satırın tümü sayfalanarak eksiksiz sunuldu. |
| | | Kurumsal işlemler listesi (Split, birleşme) | **⌘2 Portföy** / Kurumsal İşlemler | Tüm oranlar ve onaylayan aktörler korundu. |
| | | Nakit Açığı (Cash Gap) alarm bandı | **⌘2 Portföy** / Mutabakat Motoru | Fark > 0.01 € olduğunda otomatik uyarı verir. |
| | | `islemler cek` ve `mutabakat` CLI butonları | **⌘2 Portföy** / Araç Çubuğu | Birebir korundu. |
| **4** | **Forecast** | XETR seans sayacı ve geri sayım timer'ı | **App Shell** / Durum Kapsülü | 09:00 borsa açılış saati düzeltildi (U9). |
| | | Günün tahminleri tablosu (09:30 CET, yön rozeti) | **⌘3 Tahminler** / Günlük Tahminler | Çoklu model konsensüs ağırlıkları eklendi. |
| | | Akşam uzlaşma defteri (17:40 CET, kapanış, sapma) | **⌘3 Tahminler** / Akşam Uzlaşması | MAPE ve MAE hesaplamaları korundu. |
| | | Model karnesi (Brier skoru, isabet oranı) | **⌘3 Tahminler** / Model Karnesi | N<30 ampirik güven "—" baskılaması uygulandı. |
| | | Martingale ve Momentum baz modelleri kıyaslaması | **⌘3 Tahminler** / Model Karnesi | Üstünlük / yetersizlik rozetleri korundu. |
| | | `tahmin uret` ve `tahmin uzlas` CLI eylemleri | **⌘3 Tahminler** / Araç Çubuğu | Birebir korundu. |
| **5** | **ModelsRegistry**| Kayıtlı modeller listesi ve sağlayıcı hapları | **⌘3 Tahminler** / Model Kaydı Sekmesi | Doğrulanmamış modeller "Doğrulanmadı" etiketi aldı. |
| | | Görev şampiyonları vitrini (4 görev: 👑 Şampiyon) | **⌘3 Tahminler** / Model Kaydı Sekmesi | Birebir korundu. |
| | | Kıyaslama karnesi ve simülasyon rozetleri | **⌘3 Tahminler** / Model Kaydı Sekmesi | "Simülasyon" etiketleri korundu. |
| | | Çalıştırma manifestoları ve prompt hash'leri | **⌘3 Tahminler** / Model Kaydı Sekmesi | SHA-256 doğrulama bağlantıları korundu. |
| | | Sıfır maliyet ve yerel gizlilik ilkeleri kartı | **⌘3 Tahminler** / Güvenlik İlkeleri | Doğrulanmamış iddialar (U15) arındırıldı. |
| **6** | **Evaluation** | Pozisyon değerlendirme kartları (TUT/EKLE/AZALT) | **⌘4 Kararlar** / Portföy Değerlendirme | 5.7 Varlık Sayfasında da entegre gösterildi. |
| | | Gerekçe maddeleri ve Alman vergi notları | **⌘4 Kararlar** / Portföy Değerlendirme | Teilfreistellung %30 hesaplaması korundu. |
| | | Derin analiz çalıştırma (`masa degerlendir`) | **⌘4 Kararlar** / Değerlendirme Araç Çubuğu| Onay diyaloğu ile korundu. |
| | | Yasal bilgilendirme bandı (Karar desteğidir) | **⌘4 Kararlar** / Kalıcı Uyarı Bandı | Birebir korundu. |
| **7** | **Basket** | Hedef sepet ağırlıkları tablosu (`portfoy.json`) | **⌘4 Kararlar** / Hedef Sepet & Dengeleme | Boş sepet yönlendirmesi sağlandı (U13). |
| | | Fonlar arası çiftli örtüşme ısı haritası (Heatmap) | **⌘4 Kararlar** / Örtüşme & Konsolidasyon | Renk yoğunluk matrisi korundu. |
| | | Top 25 konsolide şirket maruziyeti tablosu | **⌘4 Kararlar** / Örtüşme & Konsolidasyon | Katkı veren fonlar kırılımı korundu. |
| | | UCITS 5/10/40 limit uyum kartı | **⌘4 Kararlar** / Risk Denetimi | Bireysel portföy odaklı yoğunlaşma analizine evrildi (U14). |
| | | Satışsız nakit enjeksiyonu dengeleme simülatörü | **⌘4 Kararlar** / Dengeleme Simülatörü | +500€, +1000€ simülasyonları korundu. |
| | | Fon sepeti yükleme kütüğü ve bileşenler tablosu | **⌘4 Kararlar** / Sepet Yükleme Sekmesi | Yerel dosya seçici (`NSOpenPanel`) eklendi (U13). |
| **8** | **Thesis** | Aktif yatırım tezleri grid kartları ve çürütme kutusu| **⌘4 Kararlar** / Yatırım Tezleri Defteri | Canlıdaki test verisi (U6) arındırıldı. |
| | | Tez bekleyen pozisyonlar listesi ve "Tez Yaz" | **⌘4 Kararlar** / Yatırım Tezleri Defteri | Birebir korundu. |
| | | Tez detay modalı ve dayanak sütunları | **⌘4 Kararlar** & **5.7 Varlık Sayfası** | Birebir korundu. |
| | | Yeni tez ekleme sihirbazı (En az 2 çürütme şartı) | **⌘4 Kararlar** / Yeni Tez Formu | CLI argümanları ile tam senkronize edildi. |
| | | Aylık sağlık kontrolü tetikleyicisi | **⌘4 Kararlar** / Tez Araç Çubuğu | Birebir korundu. |
| **9** | **Screener** | Aday havuzu sıralı tablosu ve Z-skor rozetleri | **⌘5 Keşif** / Fırsat Taraması Sekmesi | Açılışta otomatik tetikleme hatası (U7) çözüldü. |
| | | Aday detay çekmecesi ve seçim gerekçeleri | **⌘5 Keşif** / Detay Çekmecesi | Z-skoru +1.17 σ standardına dönüştürüldü (U10). |
| | | Havuz düzenleyici sheet (Luhn kontrolü) | **⌘5 Keşif** / Havuz Yönetimi Modalı | `ISINValidator` ve JSON şema kaydı korundu. |
| | | Canlı tarama tetikleme butonu (`masa tarama`) | **⌘5 Keşif** / Tarama Araç Çubuğu | Birebir korundu. |
| **10** | **Research** | Kanıt paketleri yatay seçicisi ve kartları | **⌘5 Keşif** / Kaynaklı Araştırma Masası| Mühürlü paketler arşivi korundu. |
| | | İddialar listesi ve birebir resmi alıntılar | **⌘5 Keşif** / Kanıt & İddia Sekmesi | Verbatim alıntı kutuları ve rozetleri korundu. |
| | | Doğrulanmış finansal metrikler tablosu | **⌘5 Keşif** / Metrikler Sekmesi | TER, Sharpe vb. alanlar korundu. |
| | | Resmi kaynak belgeler kütüğü ve SHA-256 hash'leri | **⌘5 Keşif** / Belgeler Sekmesi | Hash doğrulama bağlantıları korundu. |
| | | Red-Team Critic denetim paneli | **⌘5 Keşif** / Red-Team Critic Sekmesi | Boşken "Bilinmiyor" gösterecek şekilde düzeltildi. |
| | | Yeni araştırma başlatma sihirbazı | **⌘5 Keşif** / Araştırma Başlat Modalı | Birebir korundu. |
| **11** | **Reports** | Durum raporu oluşturma (`masa rapor`) | **⌘4 Kararlar** / Raporlar ve Yorum | Birebir korundu. |
| | | Yorum paketi derleme (`masa yorum`) | **⌘4 Kararlar** / Raporlar ve Yorum | Çoklu model yorumları korundu. |
| | | Rapor dosyaları tarayıcısı ve Markdown önizleme | **⌘4 Kararlar** / Raporlar ve Yorum | Tam metin seçilebilir Markdown görüntüleyici eklendi. |
| **12** | **Integrity** | Bütünlük doğrulama eylemi (`./etf-masa dogrula`) | **⌘6 Sistem** & **App Shell Toolbar** | Tek tıkla adli audit çalıştırma korundu. |
| | | Genel bütünlük, FileVault ve 78 Tetikleyici kartı | **⌘6 Sistem** / Bütünlük & Güvenlik | Sahte çelişkili durumlar (U5) giderildi. |
| | | Kriptografik Snapshot ve Audit hash zincir uçları | **⌘6 Sistem** / Bütünlük & Güvenlik | `zincir-uclari.jsonl` karşılaştırması korundu. |
| | | Canlı yedek alma ve geri yükleme provası (Drill) | **⌘6 Sistem** / Yedekleme Yöneticisi | Yedek şişmesi (U8) ve budama motoru eklendi. |
| | | POSIX 0700/0600 izinleri ve Gitleaks paneli | **⌘6 Sistem** / Bütünlük & Güvenlik | Birebir korundu. |
| | | Denetim olayları tablosu ve JSON yükü modalı | **⌘6 Sistem** / Denetim Kütüğü | 147 olayın tamamını listeler. |
| **13** | **Scheduler** | LaunchAgents servis kartları (`sabah/aksam/cuma`) | **⌘6 Sistem** / Zamanlayıcı & Otomasyon | Dinamik launchctl sorgusuna bağlandı. |
| | | LaunchAgent kurma/kaldırma eylemleri | **⌘6 Sistem** / Zamanlayıcı & Otomasyon | Birebir korundu. |
| | | WAITING_AUTH alarmı ve oturum doğrulama butonu | **⌘6 Sistem** & **⌘1 Bugün** | Birebir korundu. |
| | | Asenkron iş kuyruğu tablosu ve detay modalı | **⌘6 Sistem** / İş Kuyruğu | Status makinesi ve retry sayaçları korundu. |
| | | Bildirim testi tetikleyicisi | **⌘6 Sistem** / Zamanlayıcı & Otomasyon | UNUserNotificationCenter testi korundu. |
| **14** | **Configuration** | Portföy hedef ağırlıkları editörü (`portfoy.json`)| **⌘6 Sistem** / Yapılandırma Editörü | Stepper kontrolleri ve %100 toplam denetimi korundu. |
| | | Yatırım politikası eşikleri (`politika.json`) | **⌘6 Sistem** / Politika Editörü | Onaylama için teyit diyaloğu eklendi. |
| | | Model & Broker erişim kartları (Read-Only) | **⌘6 Sistem** / Model ve Broker Erişimi| API key UI kaldırıldı, güvenli dosya yolları korundu. |
| | | Bildirim ve zaman dilimi tercihleri | **⌘6 Sistem** / Tercihler Sekmesi | Birebir korundu. |
| **YENİ**| **(Çapraz)** | **Varlık Sayfası (Detay Görünümü)** | **Sabitlenmiş Varlıklar (Bölüm 5.7)**| **Tüm sistemin verilerini tek ETF'te birleştiren yeni lens.** |

---

## Bölüm 4: Uygulama Kabuğu Tasarımı (App Shell)

Uygulama kabuğu, kullanıcının nerede olursa olsun sistem durumunu tek bakışta görmesini, arka planda çalışan süreçleri izlemesini ve klavyeden elini kaldırmadan kokpiti yönetmesini sağlayan 4 ana bileşenden oluşur.

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│ [⌘1 Bugün] [⌘2 Portföy] ...  │  DURUM KAPSÜLÜ: XETRA 09:00 ● Scalable ✓  │ [⌘K] [Yenile]│
├──────────────────────────────┴───────────────────────────────────────────┴─────────────┤
│ KENAR ÇUBUĞU  │                    ANA İÇERİK ALANI                      │  İNCELEME   │
│ ───────────── │                                                          │   PANELİ    │
│ ☀︎ Bugün   ⌘1 │  Bölüm 5'te detaylandırılan aktif ekran yerleşimi       │  (INSPECTOR │
│ ◔ Portföy ⌘2 │  (Örn: 5.2 Portföy Pozisyonlar Tablosu)                 │   DRAWER)   │
│ ◎ Tahmin  ⌘3 │                                                          │             │
│ ⚖︎ Karar   ⌘4 │                                                          │ Seçili var- │
│ ⌕ Keşif   ⌘5 │                                                          │ lığın hızlı │
│ ⚙︎ Sistem  ⌘6 │                                                          │ verileri,   │
│ ───────────── │                                                          │ makas ve    │
│ SABİTLENENLER │                                                          │ tez özeti.  │
│ SPYI  11,61 € │                                                          │             │
│ IS3N  44,82 € │                                                          │             │
├───────────────┴──────────────────────────────────────────────────────────┴─────────────┤
│ ETKİNLİK ÇUBUĞU: Masa.db (v3 · 78 Triggers) │ Son Mühür: 11:48 UTC │ ⚡︎ Hazır / Boşta    │
└────────────────────────────────────────────────────────────────────────────────────────┘
```

### 4.1 Durum Kapsülü (Status Capsule — Üst Araç Çubuğu)

Pencerenin üst araç çubuğunun ortasında yer alan ve sistemin 5 hayati göstergesini tek bir kompakt hap görünümünde toplayan modüldür:

1. **Piyasa Seans Durumu ve Sayaç (U9 Düzeltmesi):**  
   - Borsa Açık: `XETRA Açık (Kapanışa 4s 12dk)` (Yeşil ışık, 09:00 - 17:30 CET).
   - Borsa Kapalı (Hafta İçi): `Piyasa Kapalı · XETRA Yarın 09:00 CET Bekleniyor` (Gri).
   - Hafta Sonu: `Piyasa Kapalı · XETRA Pazartesi 09:00 CET Bekleniyor` (Gri).
   - Operasyonel Hatırlatma: `Sabah Tahmini 09:30 CET · Akşam Uzlaşması 17:40 CET`.
2. **Broker Oturum Durumu:**  
   - Aktif: `Scalable Capital: Aktif` (Yeşil Kalkan).
   - Süresi Dolan / Kapalı: `Scalable Capital: Giriş Gerekli` (Turuncu Kalkan). Tıklandığında 1 saniyede oturum yenileme modalını açar.
3. **Veri Tazelik Göstergesi:**  
   - `● CANLI` (Yeşil, veriler <15 dakika önce güncellendi).
   - `◐ KAPANIŞ` (Mavi, son işlem günü borsa kapanış verisi).
   - `○ BAYAT` (Turuncu/Kırmızı, >24 saat).
4. **Kriptografik Mühür Durumu:**  
   - `✓ MÜHÜRLÜ` (Yeşil kilit, son 65 snapshot ve 147 denetim olayının SHA-256 zinciri sağlam).
   - `⚠ UYUMSUZ` (Kırmızı kilit, hash ucu uyuşmazlığı tespit edildi).

---

### 4.2 Etkinlik Çubuğu (Activity Bar — Alt Durum Çubuğu)

Pencerenin en altında yer alan, sistem kaynaklarını ve arka plan CLI operasyonlarını canlı izleyen alandır:

1. **Kişisel Veri İzolasyonu (U16 Düzeltmesi):**  
   Tam dosya yolu kesinlikle basılmaz. Sol tarafta temiz bir sistem rozeti yer alır:  
   `Masa.db (v3 · 78 Tetikleyici Aktif · 65 Mühür)`
2. **Arka Plan Süreç Göstergesi:**  
   - Boşta iken: `Hazır / Son doğrulama: Bugün 11:48 UTC` (Gri nokta).
   - CLI çalışırken: Dönen progress çarkı, yürütülen komut adı (`masa veri çalışıyor... · 4,2 sn`), geçen süre ve yanındaki küçük kırmızı `(x)` iptal butonu.
   - İptal Butonu (`SIGINT`): Tıklandığında sürece nazikçe `SIGINT` gönderir; veritabanı kilitlenmeden güvenli durdurulur.
3. **Son İşlem Çıkış Kodu:**  
   İşlem tamamlandığında sağ altta 5 saniye boyunca durum rozeti belirir: `Kod 0: Başarılı` (Yeşil) veya `Kod 1: Hata` (Kırmızı).

---

### 4.3 İnceleme Paneli (Inspector Drawer — Sağ Çekmece)

macOS HIG standartlarındaki sağ çekmece (`.inspector(isPresented:)`), ana tablodaki seçili öğenin detaylarını kullanıcıyı sayfasından koparmadan sunar:

- **Varlık Seçildiğinde:** Tıklanan ETF'in son 5 günlük fiyat trendi mini grafiği, alış/satış makası, broker maliyet temeli, bağlı yatırım tezi özeti ve "Tam Varlık Sayfasını Aç" butonu.
- **İşlem Seçildiğinde:** İşlemin Scalable Capital broker referans numarası (`broker_tx_id`), brüt tutar, kesilen ücret/vergi kırılımı, 4 boyutlu mutabakat durumu ve varsa hata kaydı.
- **Denetim Olayı Seçildiğinde:** Olayın kriptografik hash'i, tetikleyen aktör (`masa.scanner`, `masa.pipeline`), etkilenen tablo ve tam JSON yükü (payload) görüntüleyicisi.

---

### 4.4 ⌘K Komut Paleti (Command Palette)

Klavyeden `⌘K` tuş kombinasyonuna basıldığında ekranın ortasında açılan Spotlight tarzı hızlı erişim penceresidir:

- **Bölüm Atlama:** `Bugün`, `Portföy`, `Tahminler`, `Kararlar`, `Keşif`, `Sistem` yazarak anında geçiş.
- **Varlık Arama:** ISIN (`IE00B3...`), ticker (`SPYI`) veya fon adı (`All Country`) yazıldığında doğrudan ilgili varlığın 5.7 Varlık Sayfasını açar.
- **Hızlı Operasyonel Eylemler:**
  - *"Sabah Başlangıç Akışını Çalıştır"* (⌘1 akışını başlatır).
  - *"Verileri ve Fiyatları Yenile"* (`masa veri` tetikler).
  - *"Akşam Tahminlerini Uzlaştır"* (`masa tahmin uzlas` tetikler).
  - *"Sistem Bütünlüğünü Doğrula"* (`./etf-masa dogrula` tetikler).
  - *"Canlı Yedek Al ve Prova Yap"* (Restore drill başlatır).
  - *"Gizlilik Modunu Aç/Kapat"* (⌘⇧P).


---

## Bölüm 5: Ekran Ekran Tasarım, Veri Kaynakları ve Yerleşim Planı

Bu bölüm, ETFCockpit v2'nin 6 ana bölümünü ve çapraz Varlık Sayfasını (5.1–5.7) ekran ekran detaylandırır. Her ekran için:
1. **Yerleşim ve Bileşen Düzeni:** macOS HIG yönergelerine uygun yapısal organizasyon.
2. **Kullanıcı İş Akışları:** Ekran üzerindeki butonlar, modal sihirbazlar ve filtreleme mantıkları.
3. **Eksiksiz Veri Eşleme Tablosu:** Gösterilen her sayının, metnin ve rozetin SQLite tablo/kolon karşılığı, hesaplama formülü ve tazelik zaman damgası.

---

### 5.1 Bugün (⌘1 — Günlük Brifing & Operasyonel Kontrol)

#### 5.1.1 Amaç ve Görsel Düzen
Bugün ekranı, yatırımcının güne başlarken açtığı ilk operasyonel panodur. Temel hedefi; yatırımcının *"Bugün sistemim ne durumda, yapmam gereken bir işlem veya onay var mı?"* sorusunu tek bakışta cevaplamaktır.

- **Yerleşim:** Dikey `ScrollView`, 20 px kenar boşlukları, kart tabanlı modüler düzen.
- **Tepe Bildirim Çubuğu (Alarm & Teşhis):**  
  Eğer Scalable oturumu kapalıysa veya launchd zamanlayıcı servisleri kurulu değilse (İP-10) en üstte dikkat çekici ama göz yormayan bir turuncu bildirim bandı açılır:  
  `⚠ Scalable Capital Oturumu Kapalı · 2FA doğrulaması bekleniyor [Giriş Yap (Safari)]`  
  `ℹ launchd Görev Zamanlayıcısı Kurulu Değil · Sabah ve akşam otomasyonu için servisleri kurun [Servisleri Kur]`

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│ ☀︎ BUGÜN — 1 KASIM 2026, PAZAR (BERLİN 16:45 CET)                         [⌘R Yenile]  │
├────────────────────────────────────────────────────────────────────────────────────────┤
│ [!] Scalable Oturumu Kapalı: Lütfen 2FA onayınızı tamamlayın. [Giriş Yap] [Doğrula]    │
├────────────────────────────────────────────────────────────────────────────────────────┤
│ SABAH BAŞLANGIÇ AKIŞI (6 ADIM)                        [▶ Akışı Başlat] [■ İptal (Esc)] │
│ ┌────────────────────────────────────────────────────────────────────────────────────┐ │
│ │ 1. Oturum Denetimi       │ masa giris --json          │ 0,4 sn │ [✓ Tamamlandı]     │ │
│ │ 2. Canlı Kotasyon Çekme  │ masa veri                  │ 3,8 sn │ [✓ 4 ETF Mühürlendi]│
│ │ 3. Fiyat Geçmişi Serisi  │ masa gecmis                │ 8,2 sn │ [✓ 5.913 Nokta]    │ │
│ │ 4. Portföy Değerlendirme │ masa degerlendir --json    │ 1,1 sn │ [✓ 4 Pozisyon]     │ │
│ │ 5. Yorum Paketi Derleme  │ masa yorum                 │ 2,4 sn │ [✓ Rapor Hazır]    │ │
│ │ 6. Fırsat Taraması       │ masa tarama --son --json   │ 1,9 sn │ [✓ 17 Aday Skorlandı│
│ └────────────────────────────────────────────────────────────────────────────────────┘ │
├────────────────────────────────────────────────────────────────────────────────────────┤
│ PORTFÖY ÖZETİ                                                                          │
│ ┌──────────────────────┬──────────────────────┬──────────────────────┬───────────────┐ │
│ │ TOPLAM PORTFÖY DEĞERİ│ NAKİT & ALIM GÜCÜ    │ GÜNLÜK DEĞİŞİM (P&L) │ SON MÜHÜR     │ │
│ │ 5.000,00 €           │ 0,00 €               │ +25,00 € (+%0,50)    │ Bugün 11:48   │ │
│ │ ● Canlı (4 Pozisyon) │ Broker Bakiye: 0,00€ │ ▲ 3 Varlık Artıda    │ Mühür: 70f907 │ │
│ └──────────────────────┴──────────────────────┴──────────────────────┴───────────────┘ │
├────────────────────────────────────────────────────────────────────────────────────────┤
│ GÜNÜN ÇEKİRDEK VARLIKLARI (4 POZİSYON)                    [Tüm Portföyü Gör (⌘2) →]    │
│ ┌────────┬──────────────────────────────────────────┬───────┬──────────┬─────────────┐ │
│ │ SPYI   │ SPDR MSCI ACWI IMI UCITS ETF             │ 100 ad│ 1.200,00€│ %24,00 ●    │ │
│ │ IS3N   │ iShares Core MSCI EM IMI UCITS ETF       │  50 ad│ 2.000,00€│ %40,00 ●    │ │
│ │ IS3R   │ iShares Edge MSCI World Momentum Factor  │  25 ad│ 1.000,00€│ %20,00 ●    │ │
│ │ IS3S   │ iShares Edge MSCI World Value Factor     │  20 ad│   800,00€│ %16,00 ●    │ │
│ └────────┴──────────────────────────────────────────┴───────┴──────────┴─────────────┘ │
├────────────────────────────────────────────────────────────────────────────────────────┤
│ GÜNÜN TAHMİNLERİ VE EYLEM MADDELERİ (ACTION ITEMS)                                     │
│ • SPYI için sabah tahmini: 11,64 € (↑ %0,22 YUKARI) · Güven: — (N=0/30)               │
│ • U6 Tezi: "Tek Dünya, Tek Fon" sonraki kontrol tarihi 1 Aralık 2026 (Kalan 30 gün)    │
│ • 4 Boyutlu Mutabakat: Henüz çalıştırılmadı · [Şimdi Mutabakat Yap]                    │
└────────────────────────────────────────────────────────────────────────────────────────┘
```

#### 5.1.2 Kullanıcı Akışları ve Butonlar
1. **2FA Oturum Açma Akışı (Kullanıcı Talebi Entegrasyonu):**  
   - "Giriş Yap" butonuna basıldığında sistem arka planda `sc login --local-read-only` komutunu başlatır ve kullanıcının varsayılan tarayıcısında (Safari) Scalable Capital oturum açma sayfasını açar.
   - Arayüzde bildirim kartı belirir: *"Safari açıldı. Lütfen telefonunuza gelen 2FA bildirimini onaylayın."*
   - Kullanıcı onayladıktan sonra **"Oturumu Doğrula"** butonuna basar; `masa giris --json` tetiklenir ve kart yeşile (`Aktif`) döner.
2. **Sabah Akışını Çalıştır (`startMorningFlow`):**  
   - Tek tıkla 6 adımı sırayla çalıştırır. Her adımda geçen süre ve komut parametresi gösterilir.
   - İptal butonu sürecin güvenle durdurulmasını sağlar (`SIGINT`).

#### 5.1.3 Bugün Ekranı Veri Eşleme Tablosu

| Görsel Bileşen / Alan | Kaynak SQLite Tablosu | Sütun / JSON Alanı | Hesaplama / Çekme Mantığı | Güncellenme / Tazelik Zamanı |
|---|---|---|---|---|
| **Toplam Portföy Değeri** | `position_observations` + `cash_observations` | `p.value_eur`, `c.total_cash` | `SUM(CAST(p.value_eur AS REAL)) + CAST(c.total_cash AS REAL)` (**5.000,00 €**) | `snapshots.collection_completed_at` (11:48:10 UTC) |
| **Toplam Nakit Tutarı** | `cash_observations` | `total_cash` | En son kaydın `total_cash` değeri (**0,00 €**) | `cash_observations.observed_at` |
| **Alım Gücü (Buying Power)**| `cash_observations` | `buying_power` | En son kaydın `buying_power` değeri (**0,00 €**) | `cash_observations.observed_at` |
| **Günlük P&L Değişimi (€)**| `position_observations` + `quotes` | `p.quantity`, `q.computed_mid`, `series_points` | $\sum (Q_i \times (P_{live, i} - P_{prev\_close, i}))$ | `quotes.quote_timestamp` |
| **Pozisyon Sayısı** | `position_observations` | `count(distinct isin)` | En son portföy snapshot'ındaki tekil ISIN sayısı (**4**) | `snapshots.collection_completed_at` |
| **Varlık Satır Değerleri** | `position_observations` | `isin`, `quantity`, `value_eur` | 100 SPYI (1.200,00 €), 50 IS3N (2.000,00 €) vb. | `position_observations.observed_at` |
| **Portföy Ağırlıkları (%)**| `position_observations` | `value_eur` | $(V_i / \sum V) \times 100$ (%24,00, %40,00, %20,00, %16,00) | Hesaplanan metrik |
| **Son Mühür Zamanı & ID** | `snapshots` | `snapshot_id`, `created_at` | `run_20261101T114810Z_70f907_portfolio` | `snapshots.created_at` |
| **Günün Tahmini Satırı** | `forecast_entries` | `direction`, `target_price`, `confidence_pct` | `WHERE target_date = CURRENT_DATE` (N<30 ise güven "—") | `forecast_entries.created_at` |

---

### 5.2 Portföy (⌘2 — Varlıklar, Likidite, Defter ve 4D Mutabakat)

#### 5.2.1 Amaç ve Görsel Düzen
Portföy ekranı, yatırımcının finansal varlıklarının tam mülkiyet defteridir. 4 alt sekmeden oluşur:
- **[Canlı Pozisyonlar]:** 4 ETF pozisyonunun derinlemesine dökümü, birim maliyetler, kâr/zarar ve nakit kırılımı.
- **[İşlem Defteri]:** 626 broker işlem gözleminin tamamını filtreleyen ve arayan kütük.
- **[4 Boyutlu Mutabakat]:** Hisse, Nakit, Değerleme ve Maliyet uyumunu denetleyen adli motor.
- **[Kurumsal İşlemler]:** Split, birleşme ve temettü kayıtları.

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│ ◔ PORTFÖY — TOPLAM DEĞER: 5.000,00 € │ K/Z: +50,00 € (+%1,01)             [İşlemleri Çek]│
├────────────────────────────────────────────────────────────────────────────────────────┤
│ [ Canlı Pozisyonlar (4) ]  [ İşlem Defteri (626) ]  [ 4D Mutabakat ]  [ Kurumsal İşl. ]│
├────────────────────────────────────────────────────────────────────────────────────────┤
│ LİKİDİTE VE NAKİT KIRILIMI (5 KATMAN)                                                  │
│ ┌───────────────┬───────────────┬───────────────┬───────────────┬────────────────────┐ │
│ │ TAKAS EDİLMİŞ │ TAKASTA (T+2) │ TAHAKKUK EDEN │ AÇIK ALIŞLAR  │ MUHTEMEL VERGİ     │ │
│ │ 0,00 €        │ 0,00 €        │ 0,00 €        │ 0,00 €        │ 0,00 €             │ │
│ └───────────────┴───────────────┴───────────────┴───────────────┴────────────────────┘ │
├────────────────────────────────────────────────────────────────────────────────────────┤
│ POZİSYONLAR TABLOSU                     [Filtre: Tümü ▼] [Sırala: Değer ▼] [🔍 ISIN/Ad]│
│ ┌─────┬──────┬─────────────────────────┬──────┬─────────┬────────┬──────────┬────────┐ │
│ │TÜR  │KOD   │ FON ADI                 │ ADET │ MALİYET │ ANLIK  │ DEĞER    │ K/Z (%)│ │
│ ├─────┼──────┼─────────────────────────┼──────┼─────────┼────────┼──────────┼────────┤ │
│ │ETF  │SPYI  │ SPDR MSCI ACWI IMI Acc  │ 100  │ 11,50 € │12,000 €│1.200,00 €│ +%4,35 │ │
│ │ETF  │IS3N  │ iShares Core MSCI EM IMI│  50  │ 42,00 € │40,000 €│2.000,00 €│ -%4,76 │ │
│ │ETF  │IS3R  │ iShares MSCI World Mom. │  25  │ 39,00 € │40,000 €│1.000,00 €│ +%2,56 │ │
│ │ETF  │IS3S  │ iShares MSCI World Value│  20  │ 41,00 € │40,000 €│  800,00 €│ -%2,44 │ │
│ └─────┴──────┴─────────────────────────┴──────┴─────────┴────────┴──────────┴────────┘ │
│ TOPLAM: 4 Pozisyon │ Maliyet Tabanı: 4.950,00 € │ Net Gerçekleşmemiş K/Z: +50,00 €      │
└────────────────────────────────────────────────────────────────────────────────────────┘
```

#### 5.2.2 4 Boyutlu Mutabakat Motoru (U4 Sahte Yeşil Düzeltmesi)
Mutabakat sekmesinde 4 adli denetim boyutu yer alır:
1. **1. Hisse Adedi Mutabakatı:** `transaction_observations` toplam adetleri ile `position_observations` adetleri eşit mi? (Örnek SPYI: 100 == 100).
2. **2. Nakit Bakiye Mutabakatı:** Broker nakit gözlemi ile işlem defteri net nakit akışı eşit mi? (Fark $\le 0.01\ €$).
3. **3. Değerleme Mutabakatı:** $Adet \times Kotasyon$ ile bildirilen portföy değeri eşit mi?
4. **4. Maliyet Tabanı (Cost Basis) Mutabakatı:** Broker bildirdiği maliyet ile FIFO/WAC defter maliyeti uyumlu mu?

*Veri Yok Durumu Kuralı:* Eğer `reconciliations` tablosunda kayıt yoksa, kartlar asla yeşil "Eşleşti" göstermez. Gri renkte `"Çalıştırılmadı"` basılır ve altında **[Mutabakatı Çalıştır (`masa mutabakat --detay`)]** butonu yer alır.

#### 5.2.3 Portföy Ekranı Veri Eşleme Tablosu

| Görsel Bileşen / Alan | Kaynak SQLite Tablosu | Sütun / JSON Alanı | Hesaplama / Çekme Mantığı | Güncellenme / Tazelik Zamanı |
|---|---|---|---|---|
| **Varlık Ticker & İsim** | `instruments` + `listings` | `i.name`, `l.ticker` | `listings.is_primary = 1` olan borsa kotasyon adı | `instruments.created_at` |
| **Pay Adedi (Quantity)** | `position_observations` | `quantity` | `CAST(quantity AS REAL)` (100, 50, 25, 20) | `position_observations.observed_at` |
| **Birim Maliyet (Cost Basis)**| `position_observations` | `broker_cost_basis` | Broker birim alış maliyeti (11,50 €, 42,00 € vb.) | `position_observations.observed_at` |
| **Anlık Kotasyon Fiyatı**| `quotes` | `computed_mid` | `(bid + ask) / 2` veya resmi son işlem fiyatı | `quotes.quote_timestamp` |
| **Piyasa Değeri (€)** | `position_observations` | `value_eur` | $Adet \times Anlık\ Fiyat$ (1.200,00 €, 2.000,00 € vb.) | `position_observations.observed_at` |
| **Kâr / Zarar Tutarı (€)** | Hesaplanır | - | $value\_eur - (quantity \times broker\_cost\_basis)$ | Anlık hesaplama |
| **Kâr / Zarar Oranı (%)** | Hesaplanır | - | $((computed\_mid / broker\_cost\_basis) - 1) \times 100$| Anlık hesaplama |
| **İşlem Defteri Satırları**| `transaction_observations` + `v_transactions_current` | 614 tekil işlem (626 gözlem) | `tx.broker_tx_id NOT IN (SELECT broker_tx_id FROM transaction_versions) GROUP BY tx.broker_tx_id` tekilleştirmesi. Alt tip için `COALESCE(security_transaction_type, cash_transaction_type)` kullanılır (`sub_type` gözlem tablosunda yoktur). | `transaction_observations.event_time` |
| **Tarihsel Alış Hacmi (Kütük)**| `transaction_observations` | `amount` | `SUM(amount) WHERE side='BUY' AND status='SETTLED'` (-250.793,98 € · 199 tamamlanmış işlem) | Tarihsel kütük toplamı |
| **Portföy Maliyet Tabanı**| `position_observations` | `quantity, broker_cost_basis` | `SUM(CAST(quantity AS REAL) * CAST(broker_cost_basis AS REAL))` (örn: 4.950,00 € · 4 açık pozisyon) | `position_observations.observed_at` |
| **Mutabakat Bayrakları** | `reconciliations` | `shares_match`, `cash_match` | Veritabanında yoksa `nil` -> `"Çalıştırılmadı"` (Gri) | `reconciliations.reconciliation_time` |

---

### 5.3 Tahminler (⌘3 — Tahmin Üretme, Uzlaştırma ve Model Karnesi)

#### 5.3.1 Amaç ve Görsel Düzen
Bu ekran, sistemin kalbi olan **Tahmin → Uzlaşma → Karne** döngüsünü barındırır. 4 alt sekmeden oluşur:
- **[Günün Tahminleri (09:30 CET)]:** Borsa açılışından yarım saat sonra üretilen günlük yön ve hedef fiyat tahminleri.
- **[Akşam Uzlaşması (17:40 CET)]:** Borsa kapanışından sonra resmi fiyatla tahminin karşılaştırıldığı uzlaşma defteri.
- **[Model Karnesi & Kıyaslama]:** Brier skoru, isabet oranı, MAPE/MAE ve naif baz modellerle yarışma grafikleri.
- **[Model Kaydı & Şampiyonlar]:** 5 modelin teknik kimliği, prompt hash'leri ve görev şampiyonları vitrini.

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│ ◎ TAHMİNLER — SEANS: XETRA AÇIK (KAPANIŞA 2s 45dk)         [Sabah Tahmini] [Akşam Uzlaş]│
├────────────────────────────────────────────────────────────────────────────────────────┤
│ [ Günün Tahminleri (09:30) ] [ Uzlaşma Defteri (17:40) ] [ Model Karnesi ] [ Modeller ]│
├────────────────────────────────────────────────────────────────────────────────────────┤
│ TAHMİN PERFORMANS GÖSTERGELERİ                                                         │
│ ┌───────────────┬───────────────┬───────────────┬───────────────┬────────────────────┐ │
│ │ UZLAŞMIŞ GÖZLEM│ YÖN İSABETİ   │ ORTALAMA HATA │ ORTALAMA HATA │ NAİF BAZ ÜSTÜNLÜĞÜ │ │
│ │ N = 0         │ — (N < 30)    │ — (MAPE)      │ — (MAE €)     │ Değerlendirilmedi  │ │
│ │ Küçük Örneklem│ Ampirik Güven │ Yüzdesel Hata │ Mutlak Hata   │ Martingale & Mom.  │ │
│ └───────────────┴───────────────┴───────────────┴───────────────┴────────────────────┘ │
├────────────────────────────────────────────────────────────────────────────────────────┤
│ GÜNÜN AÇIK TAHMİNLERİ (HEDEF: 1 KASIM 17:30 CET KAPANIŞI)                             │
│ ┌──────┬───────────────────────┬──────────┬──────────┬──────────┬──────────┬─────────┐ │
│ │KOD   │ MODEL                 │ YÖN      │ 09:30 FİY│ HEDEF FİY│ BEKLENEN │ GÜVEN   │ │
│ ├──────┼───────────────────────┼──────────┼──────────┼──────────┼──────────┼─────────┤ │
│ │SPYI  │ Local Momentum v1     │ ↑ YUKARI │ 11,614 € │ 11,640 € │ +%0,22   │ — (N=0) │ │
│ │IS3N  │ Gemini Pro Multi-Fact │ ↓ AŞAĞI  │ 44,820 € │ 44,500 € │ -%0,71   │ — (N=0) │ │
│ │IS3R  │ Local Martingale      │ → YATAY  │ 97,080 € │ 97,080 € │  %0,00   │ — (N=0) │ │
│ │IS3S  │ Local Momentum v1     │ ↑ YUKARI │ 70,110 € │ 70,350 € │ +%0,34   │ — (N=0) │ │
│ └──────┴───────────────────────┴──────────┴──────────┴──────────┴──────────┴─────────┘ │
│ NOT: N < 30 olduğu için ampirik güven rozeti baskılanmıştır. Mühür: trg_forecast_records│
└────────────────────────────────────────────────────────────────────────────────────────┘
```

#### 5.3.2 Tahmin ve Uzlaşma Döngüsü Matematiksel Modeli

1. **Sabah Tahmini (09:30 CET):**  
   Her varlık için model bir hedef fiyat $P_{target}$ ve yön $D \in \{\text{UP}, \text{DOWN}, \text{FLAT}\}$ üretir. Bu kayıt SQLite `forecast_entries` tablosuna born-sealed olarak mühürlenir. Tetikleyici gereği bir daha güncellenemez (`trg_forecast_entries_no_update`).
2. **Akşam Uzlaşması (17:40 CET):**  
   XETRA 17:30 resmi borsa kapanış kotasyonu $P_{close}$ sisteme girer.  
   - Mutlak Hata: $MAE = |P_{close} - P_{target}|$
   - Yüzdesel Hata: $MAPE = \frac{|P_{close} - P_{target}|}{P_{close}} \times 100$
   - Gerçekleşen Yön:
     $$D_{actual} = \begin{cases} \text{UP}, & P_{close} > P_{ref} \times (1 + \epsilon) \\ \text{DOWN}, & P_{close} < P_{ref} \times (1 - \epsilon) \\ \text{FLAT}, & \text{aksi halde} \end{cases}$$
   - Yön İsabeti: $Hit = (D == D_{actual})$
3. **Brier Skoru ve Kalibrasyon ($N \ge 30$):**  
   Olasılıklı tahminlerin kalibrasyonu Brier Skoru ile ölçülür:
   $$BS = \frac{1}{N} \sum_{t=1}^{N} (f_t - o_t)^2$$
   Burada $f_t \in [0, 1]$ modelin verdiği yükseliş olasılığı, $o_t \in \{0, 1\}$ gerçekleşen ikili sonuçtur ($D_{actual} = \text{UP} \implies o_t = 1$, aksi halde $0$).
   - **YATAY / FLAT Tahminlerin $f_t$ Olasılık Eşlemesi:** Model YATAY (FLAT) tahmin ürettiğinde yönsüz/nötr kaldığı için ikili Brier formülünde yükseliş olasılığı $f_t = 0.50$ (tarafsız baz) olarak eşlenir ($BS = (0.50 - o_t)^2 = 0.25$ naif referansı).
   - **Çok Sınıflı (Multi-Category) Brier Skoru:** 3 yönlü piyasa hareketinde ($K = \{\text{YUKARI}, \text{AŞAĞI}, \text{YATAY}\}$) model her yön için ayrık olasılık dağılımı ($f_{t, UP}, f_{t, DOWN}, f_{t, FLAT}$) ürettiğinde çok sınıflı Brier skoru uygulanır:
     $$BS_{multi} = \frac{1}{N} \sum_{t=1}^{N} \sum_{k \in K} (f_{t, k} - o_{t, k})^2$$
     Burada gerçekleşen yön $k$ için $o_{t, k} = 1$, diğerleri için $0$ alınır. Model bir varlık için $f_{t, FLAT} = 1.0$ (veya yüksek olasılık) öngördüğünde ve gerçekleşen yön de FLAT olduğunda karesel hata 0 puan alır; böylece yatay piyasada doğru yönsüzlük tahmini yapan model haksız yere cezalandırılmaz.
   - Referans Değerler: $BS = 0.0$ mükemmel kalibrasyon, $BS = 0.25$ naif yazı-tura/rastgele tahmin eşiğidir. N < 30 iken ampirik güven bastırılır (`"—"`).
4. **Naif Baz Kıyaslaması:**  
   Modelin başarısı, piyasadaki iki naif kuralın isabetiyle doğrudan yarışır:
   - **Martingale Bazı:** "Yarınki fiyat bugünkü fiyata eşittir (YATAY)".
   - **Momentum Bazı:** "Dün yükselen bugün de yükselir".  
   Model bu iki bazdan daha yüksek isabet üretemiyorsa ekranda `"Naif Bazı Geçemedi"` uyarısı verilir.

#### 5.3.3 Tahminler Ekranı Veri Eşleme Tablosu

| Görsel Bileşen / Alan | Kaynak SQLite Tablosu | Sütun / JSON Alanı | Hesaplama / Çekme Mantığı | Güncellenme / Tazelik Zamanı |
|---|---|---|---|---|
| **Açık Tahmin Satırları** | `v_forecasts_unsettled` | `isin, model_id, direction, reference_price, target_price` | `WHERE target_date = CURRENT_DATE` | `forecast_entries.created_at` (09:30 CET) |
| **Uzlaşma Defteri Satırları**| `v_forecast_performance` | `actual_close_price, error_eur, error_pct, direction_hit` | `WHERE settlement_date IS NOT NULL` | `settlements.settled_at` (17:40 CET) |
| **Toplam Gözlem Sayısı (N)**| `v_forecast_performance` | `count(*)` | Toplam uzlaşmış gün sayısı (Mevcut: **0**) | `settlements.settled_at` |
| **Yön İsabet Oranı (%)** | `v_forecast_performance` | `direction_hit` | $N < 30 \rightarrow$ `" — "`; $N \ge 30 \rightarrow (Hit / N) * 100$ | Dinamik kural denetimi |
| **Model Kayıt Listesi** | `model_registry` | `model_id, provider, model_name, access_tier` | Kayıtlı 5 modelin teknik konfigürasyonu | `model_registry.created_at` |
| **Görev Şampiyonları (👑)** | `v_model_champions` | `task_category, model_name, score_pct` | Her görevde en yüksek kalibre skora sahip model | `model_evaluations.created_at` |


---

### 5.4 Kararlar (⌘4 — Değerlendirme, Sepet, Tezler, Dengeleme ve Raporlar)

#### 5.4.1 Amaç ve Görsel Düzen
Kararlar ekranı, yatırımcının stratejik yönetim merkezidir. Bireysel yatırımcının kural bazlı ve yapay zeka destekli önerileri değerlendirdiği, hedef sepet sapmalarını izlediği, satış yapmadan portföyünü dengelediği ve yatırım tezlerini denetlediği alandır. 5 alt sekmeden oluşur:

1. **[Değerlendirme & Tavsiye]:** Her pozisyon için kural bazlı TUT, EKLE veya AZALT kartları; model gerekçeleri ve Alman vergi muafiyeti (Teilfreistellung %30) analizleri.
2. **[Hedef Sepet & Örtüşme]:** Fonlar arası çiftli örtüşme ısı haritası matrisi (Heatmap) ve Top 25 konsolide şirket maruziyeti tablosu.
3. **[Dengeleme Simülatörü]:** Satış yapıp vergi ödemek yerine, yeni nakit enjeksiyonuyla (+500€, +1000€ vb.) portföyü hedef ağırlıklara yaklaştıran simülatör.
4. **[Yatırım Tezleri Defteri]:** Her varlık için oluşturulan hipotezler, sağlık kontrolleri ve en az 2 zorunlu çürütme şartı. (U6 test tezi arındırılmış görünüm).
5. **[Raporlar & Yorum]:** Markdown durum raporları (`masa rapor`) ve çoklu model yorum paketleri (`masa yorum`).

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│ ⚖︎ KARARLAR — KARAR DESTEĞİ VE PORTFÖY STRATEJİSİ                   [Derin Analiz (AI)]│
├────────────────────────────────────────────────────────────────────────────────────────┤
│ [ Değerlendirme ]  [ Hedef Sepet & Örtüşme ]  [ Dengeleme Sim. ]  [ Tezler ]  [ Rapor ]│
├────────────────────────────────────────────────────────────────────────────────────────┤
│ ℹ YASAL BİLGİLENDİRME: Sistem karar desteğidir; kendi başına işlem yapmaz.             │
│   Tüm kararlar yatırımcının Scalable Capital mobil uygulamasındaki manuel onayına bağlıdır.│
├────────────────────────────────────────────────────────────────────────────────────────┤
│ POZİSYON DEĞERLENDİRME KARTLARI (4 VARLIK)                                             │
│ ┌─────────────────────────────────────────────────┬──────────────────────────────────┐ │
│ │ SPYI — State Street SPDR MSCI ACWI IMI [TUT]   │ IS3N — iShares Core MSCI EM IMI [EKLE] │
│ │ Canlı Pay: %42,16 │ Hedef: %45,00 │ Sapma: -%2,84│ Canlı Pay: %22,65 │ Hedef: %25,00│ │
│ │ • Trend 200G üzerinde (+%4,12)                  │ • Gelişmekte olan piyasa iskonto │ │
│ │ • Falsification Trigger: İhlal yok (Sağlıklı)   │ • Hedef sapması tolerans sınırında│ │
│ │ • Vergi Notu: Teilfreistellung %30 geçerli      │ • Vergi Notu: Teilfreistellung %30│ │
│ └─────────────────────────────────────────────────┴──────────────────────────────────┘ │
├────────────────────────────────────────────────────────────────────────────────────────┤
│ SATIŞSIZ NAKİT ENJEKSİYONU DENGELEME SİMÜLATÖRÜ                                        │
│ Eklenecek Yeni Nakit: [ +500 € ] [ +1.000 € ] [ +2.500 € ] [ +5.000 € ] [ Manuel: [1000] € ] │
│ ┌──────┬──────────┬──────────┬──────────┬──────────────────────┬─────────────────────┐ │
│ │VARLIK│ MEVCUT € │ CANLI %  │ HEDEF %  │ SAPMA (DRIFT BAR)    │ ÖNERİLEN ALIM       │ │
│ ├──────┼──────────┼──────────┼──────────┼──────────────────────┼─────────────────────┤ │
│ │SPYI  │ 2.000,00€│ %40,00   │ %45,00   │ [====----] -%5,00    │ +700,00 € (~60 adet)│ │
│ │IS3N  │ 1.000,00€│ %20,00   │ %25,00   │ [===-----] -%5,00    │ +500,00 € (~11 adet)│ │
│ │IS3R  │ 1.200,00€│ %24,00   │ %20,00   │ [======++] +%4,00    │ +0,00 € (Alım Yok)  │ │
│ │IS3S  │   800,00€│ %16,00   │ %10,00   │ [======++] +%6,00    │ +0,00 € (Alım Yok)  │ │
│ └──────┴──────────┴──────────┴──────────┴──────────────────────┴─────────────────────┘ │
│ Simülasyon Sonucu: 0 € Satış (Sıfır Vergi Maliyeti) · 960,00 € Dağıtıldı · 40,00 € Nakit│
└────────────────────────────────────────────────────────────────────────────────────────┘
```

#### 5.4.2 Yatırım Tezleri ve Çürütme Şartları (Falsification Triggers)
- **U6 Test Tezi Çözümü:** `thesis_versions` tablosundaki `th_5aab39e8bc85` nolu test kaydı, üretim görünümünde "Arşivlenmiş Test" filtresiyle varsayılan olarak gizlenir.
- **En Az 2 Çürütme Şartı Zorunluluğu:** Yeni bir tez eklenirken sistem en az 2 adet somut, ölçülebilir yanlışlanabilirlik koşulu (`falsification_triggers`) talep eder. Örneğin:
  1. *"Küresel ticaret hacminde 6 ay üst üste %10 daralma olursa"*
  2. *"Fon yönetim ücreti (TER) %0.30 üzerine çıkarsa"*
- Eğer bu koşullardan biri piyasa verilerinde gerçekleşirse, tez durumu yeşil `SAĞLIKLI` rozetinden kırmızı `İHLAL EDİLDİ (BREACHED)` rozetine döner ve değerlendirme kartı pozisyonu derhal `AZALT / GÖZDEN GEÇİR` tavsiyesine çeker.

#### 5.4.3 Kararlar Ekranı Veri Eşleme Tablosu

| Görsel Bileşen / Alan | Kaynak SQLite Tablosu | Sütun / JSON Alanı | Hesaplama / Çekme Mantığı | Güncellenme / Tazelik Zamanı |
|---|---|---|---|---|
| **Pozisyon Önerisi (TUT/EKLE/AZALT)** | `masa/config/politika.json` + `quotes` | `policy.tolerans_*`, `trend_gap` | Ağırlık sapması ve trend filtre kuralları sonucu | `quotes.quote_timestamp` |
| **Hedef Sepet Ağırlıkları (%)** | `masa/config/portfoy.json` | `hedef_agirliklar` | Kullanıcının tanımladığı hedef dağılım (%45, %25 vb.). Dosyadaki `hedef_agirliklar: {}` boş ise "Hedef Tanımlanmadı" Boş Durumu gösterilir. | Dosya mtime |
| **Çiftli Fon Örtüşmesi (%)** | `holding_items` | `constituent_isin, weight_pct` | $\sum \min(w_{A, i}, w_{B, i})$ (İki fonun ortak hisse ağırlıkları) | `holdings_sets.as_of_date` |
| **Konsolide Top 25 Şirket** | `holding_items` + `position_observations` | `weight_pct * portfoy_payi` | Tüm portföy genelinde hisse senedi maruziyet toplamı | `holdings_sets.as_of_date` |
| **Satışsız Dengeleme Alım Tutarı** | Hesaplanır | - | $Order_i = \max(0, w_{target, i} \times (V + C_{new}) - V_i)$ · Hızlı butonlar: +500€, +1.000€, +2.500€, +5.000€ veya manuel | Anlık simülasyon |
| **Aktif Tez Başlık & Özeti** | `v_theses_current` | `title, one_line_summary, status` | En güncel aktif yatırım tezleri listesi | `thesis_versions.created_at` |
| **Çürütme Tetikleyicileri** | `v_theses_current` | `falsification_triggers_json` | JSON formatındaki en az 2 adet çürütme kuralı | `thesis_versions.created_at` |
| **Rapor Dosyaları Listesi** | Dosya Sistemi | `masa/var/reports/*.md` | Klasördeki üretilmiş analitik rapor dosyaları | Dosya mtime |

---

### 5.5 Keşif (⌘5 — Fırsat Taraması, Havuz Yönetimi ve Araştırma Masası)

#### 5.5.1 Amaç ve Görsel Düzen
Keşif ekranı, yeni yatırım fırsatlarının istatistiksel olarak tarandığı, aday havuzunun yönetildiği ve resmi belgeler üzerinden kaynaklı kanıtların incelendiği araştırma laboratuvarıdır. 4 alt sekmeden oluşur:

1. **[Fırsat Taraması]:** Z-skoruna göre sıralanmış aday listesi ve seçim gerekçeleri.
2. **[Aday Havuzu Yönetimi]:** Taranacak ISIN listesinin düzenlendiği, Luhn algoritması ile kontrol edilen form.
3. **[Kaynaklı Araştırma Masası]:** Mühürlü kanıt paketleri, resmi Factsheet alıntıları (Verbatim Quotes) ve doğrulanmış metrikler.
4. **[Red-Team Critic Denetimi]:** Yapay zeka ve deterministik modellerin iddialarını çapraz sorgulayan eleştirel denetim karnesi.

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│ ⌕ KEŞİF — ADAY HAVUZU: 17 ENSTRÜMAN │ SON TARAMA: 1 KASIM 15:04 UTC         [Şimdi Tara]│
├────────────────────────────────────────────────────────────────────────────────────────┤
│ [ Fırsat Taraması ]  [ Aday Havuzunu Düzenle ]  [ Kaynaklı Araştırma ]  [ Red-Team ]   │
├────────────────────────────────────────────────────────────────────────────────────────┤
│ TARAMA LİSTESİ (SPLIT VIEW)                 │ ADAY DETAYI: APPLE INC. (US0378331005)   │
│ ┌────┬──────────────┬──────────┬──────────┐ │ ┌──────────────────────────────────────┐ │
│ │SKOR│ ENSTRÜMAN    │ Z-SKOR   │ KARAR    │ │ │ APPLE INC. · NASDAQ (XNAS)           │ │
│ ├────┼──────────────┼──────────┼──────────┤ │ │ Bileşik Z-Skoru: +1.1713 σ (Güçlü Poz)│ │
│ │ 1  │ Apple Inc.   │ +1.17 σ  │ ARAŞTIR  │ │ ├──────────────────────────────────────┤ │
│ │ 2  │ IS3S (Value) │ +1.12 σ  │ İZLE     │ │ │ BİLEŞEN AYRINTILARI:                 │ │
│ │ 3  │ ASML Holding │ +0.68 σ  │ İZLE     │ │ │ • 6A Momentum: +%18,40 (Ağırlık: 0.25)│ │
│ │ 4  │ IS3Q (Qual)  │ +0.32 σ  │ ARAŞTIR  │ │ │ • 1Y Momentum: +%31,20 (Ağırlık: 0.25)│ │
│ │ 5  │ Microsoft    │ +0.31 σ  │ İZLE     │ │ │ • Sharpe Oranı: 1,84   (Ağırlık: 0.25)│ │
│ │ 6  │ SAP SE       │ +0.31 σ  │ İZLE     │ │ │ • 200G Trend Farkı: +%8,4 (Ağırlık: 0.15│
│ │ 7  │ SXR8 (S&P500)│ +0.05 σ  │ ARAŞTIR  │ │ │ • Portföy Korelasyonu: 0,42 (Ağ: 0.10)│ │
│ │ 8  │ EUNL (World) │ +0.05 σ  │ ARAŞTIR  │ │ ├──────────────────────────────────────┤ │
│ │ 9  │ VWCE (All-W) │ -0.03 σ  │ ARAŞTIR  │ │ │ SEÇİM GEREKÇELERİ:                   │ │
│ │ 10 │ IS3R (Mom.)  │ -0.25 σ  │ İZLE     │ │ │ 1. 200 günlük hareketli ortalama üstü│ │
│ └────┴──────────────┴──────────┴──────────┘ │ │ 2. Alış/satış makası limit içinde    │ │
│                                             │ └──────────────────────────────────────┘ │
└────────────────────────────────────────────────────────────────────────────────────────┘
```

#### 5.5.2 U7 ve U10 Düzeltmeleri Uygulama Mantığı
- **U7 Çözümü (Salt-Okunur Sayfa Açılışı):** Sayfa açıldığında hiçbir CLI komutu çalışmaz. Son mühürlü taramanın sonucu veritabanındaki denetim günlüğünden okunur. "Şimdi Tara" butonuna basılmadığı sürece arka planda hiçbir `RUN_STARTED` olayı üretilmez.
- **U10 Çözümü (İstatistiki Z-Skoru):** Karne notu formatı (`1.17 / 10.0`) kaldırılmış; yerine standart sapma sembolü (`+1.17 σ`) konulmuştur. Gaussian renklendirme kuralı ile +1.17 σ doğrudan parlak yeşil renkle gösterilmektedir.

#### 5.5.3 Keşif Ekranı Veri Eşleme Tablosu

| Görsel Bileşen / Alan | Kaynak SQLite Tablosu | Sütun / JSON Alanı | Hesaplama / Çekme Mantığı | Güncellenme / Tazelik Zamanı |
|---|---|---|---|---|
| **Aday Sıralaması & Z-Skor** | `audit_events` | `actor='masa.scanner'`, `payload_json.ranked` | 5 bileşenin z-skor formülü toplamı (+1.1713 vb.) | `audit_events.event_time` (15:04:27 UTC) |
| **Karar Etiketi** | `audit_events` | `payload_json.ranked[i][1]` | `ARAŞTIRMAYA DEĞER` veya `İZLE` | `audit_events.event_time` |
| **6A ve 1Y Getiriler** | `series_points` / `raw_objects` | `value` / `payload_text` | `quotes` tablosunda `performances` kolonu yoktur; getiriler `series_points.value` serilerinden dinamik hesaplanır veya ham API yanıtından (`raw_objects`) çekilir. | `series_points.point_time` |
| **Sharpe & Trend Farkı** | `series_points` | `series_key IN ('{isin}:1y', '{isin}:max')`, `value` | `series_points` tablosundaki `value` kolonundan hesaplanır (`close_price` adında bir kolon yoktur). | `series_points.point_time` |
| **Aday Havuzu Listesi** | `masa/config/havuz.json` | `etf`, `hisse` | Taranacak 17 enstrümanın ISIN listesi | Dosya mtime |
| **Resmi Alıntı (Verbatim)** | `claims` | `quote_verbatim` | Factsheet veya yasal belgeden birebir alıntı | `claims.created_at` |
| **Red-Team Denetim Skoru** | `audit_events` | `actor='masa.critic'`, `payload_json` | Matematiksel tutarlılık ve doğruluk skoru | `audit_events.event_time` |

---

### 5.6 Sistem (⌘6 — Bütünlük, Yedekleme, Zamanlayıcı ve Ayarlar)

#### 5.6.1 Amaç ve Görsel Düzen
Sistem ekranı, uygulamanın teknik altyapısını, güvenlik sınırlarını ve işletim sistemi entegrasyonunu yönetir. 4 alt sekmeden oluşur:

1. **[Bütünlük & Güvenlik]:** 65 snapshot ve 147 denetim olayının SHA-256 hash zinciri doğrulaması, FileVault, 78 SQLite tetikleyicisi ve adli denetim günlüğü.
2. **[Yedekleme Yöneticisi]:** 231 MB'a ulaşan yedek şişmesini önleyen budama motoru, canlı yedek alma ve geri yükleme provası (Restore Drill).
3. **[Zamanlayıcı & Otomasyon]:** macOS `launchd` servisleri (`sabah`, `aksam`, `cuma`), asenkron iş kuyruğu ve bildirim ayarları.
4. **[Sistem Yapılandırması]:** `masa/config/portfoy.json` (hedef ağırlıklar) ve `masa/config/politika.json` (risk ve sapma toleransları) güvenli editörü.

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│ ⚙︎ SİSTEM — DURUM: 78 TETİKLEYİCİ AKTİF │ 65 MÜHÜR SAĞLAM                [Bütünlüğü Doğrula]│
├────────────────────────────────────────────────────────────────────────────────────────┤
│ [ Bütünlük & Güvenlik ]  [ Yedekleme & POSIX ]  [ Zamanlayıcı ]  [ Yapılandırma ]      │
├────────────────────────────────────────────────────────────────────────────────────────┤
│ ADLİ BÜTÜNLÜK VE GÜVENLİK GÖSTERGELERİ                                                 │
│ ┌──────────────────────┬──────────────────────┬──────────────────────┬───────────────┐ │
│ │ KRİPTOGRAFİK MÜHÜR   │ ADLİ DENETİM ZİNCİRİ │ SQLİTE GÜVENCESİ     │ DİSK ŞİFRELEME│ │
│ │ 65 Mühürlü Snapshot  │ 147 Olay Doğrulandı  │ 78 Değişmezlik Tetik.│ FileVault AÇIK│ │
│ │ ✓ Zincir Ucu Eşleşti │ ✓ SHA-256 Kırıksız   │ ✓ UPDATE/DELETE Yasak│ 0700/0600 OK  │ │
│ └──────────────────────┴──────────────────────┴──────────────────────┴───────────────┘ │
├────────────────────────────────────────────────────────────────────────────────────────┤
│ YEDEK DEPOLAMA VE ŞİŞKİNLİK YÖNETİCİSİ (U8 DÜZELTMESİ)                                 │
│ ┌────────────────────────────────────────────────────────────────────────────────────┐ │
│ │ Canlı Veritabanı: 3,7 MB │ Yedek Depolama: 231 MB (89 Dosya) ⚠ ŞİŞKİNLİK UYARISI    │ │
│ │ Saklama Politikası: 7 Günlük, 4 Haftalık, 12 Aylık                                 │ │
│ │ [ Politikaya Göre Temizle (Prune) ]   [ Canlı Yedek Al ]   [ Geri Yükleme Provası ]│ │
│ └────────────────────────────────────────────────────────────────────────────────────┘ │
├────────────────────────────────────────────────────────────────────────────────────────┤
│ MACOS LAUNCHD ZAMANLAYICI SERVİSLERİ                                                   │
│ • com.etf.masa.sabah (09:30 CET): [YÜKLÜ / ÇALIŞIYOR] · Son çıkış: 0 (Başarılı)        │
│ • com.etf.masa.aksam (17:40 CET): [YÜKLÜ / ÇALIŞIYOR] · Son çıkış: 0 (Başarılı)        │
│ • com.etf.masa.cuma  (21:00 CET): [YÜKLÜ / BEKLEMEDE] · Haftalık mutabakat ve yedek     │
└────────────────────────────────────────────────────────────────────────────────────────┘
```

#### 5.6.2 U5 ve U8 Çözüm Detayları
- **U5 Çözümü (Doğru Sayaçlar):** Sayfa açılışında `SELECT COUNT(*) FROM snapshots` (65) ve `SELECT COUNT(*) FROM audit_events` (147) doğrudan SQLite üzerinden çekilir. "TEST EDİLMEDİ" veya "0 Mühürlü Snapshot" çelişkisi tamamen ortadan kalkar.
- **U8 Çözümü (Yedekleme Budama):** 89 adet `.db` dosyasından 7 günden eski olan günlük kopyalar `masa/config/politika.json` kurallarına göre temizlenir. Disk tüketimi 231 MB'tan ~30 MB seviyesine indirilir.

#### 5.6.3 Sistem Ekranı Veri Eşleme Tablosu

| Görsel Bileşen / Alan | Kaynak SQLite Tablosu | Sütun / JSON Alanı | Hesaplama / Çekme Mantığı | Güncellenme / Tazelik Zamanı |
|---|---|---|---|---|
| **Snapshot Mühür Sayısı** | `snapshots` | `count(*)` | `SELECT count(*) FROM snapshots` (**65**) | Canlı sorgu |
| **Denetim Olay Sayısı** | `audit_events` | `count(*)` | `SELECT count(*) FROM audit_events` (**147**) | Canlı sorgu |
| **Zincir Ucu Hash'i** | `audit_events` + `zincir-uclari.jsonl` | `curr_hash` | Son olayın `curr_hash` değeri ile mühürlü dosya kıyası | Son `event_time` |
| **Yedek Depolama Alanı** | Dosya Sistemi (`stat`) | `masa/var/backups/*.db` | 89 adet dosyanın toplam bayt boyutu (**231 MB**) | Anlık disk kontrolü |
| **LaunchAgent Durumları**| Sistem (`launchctl`) | `status, last_exit_code` | `launchctl print gui/<uid>/com.etf.masa.*` | Anlık servis kontrolü |
| **Asenkron İş Kuyruğu** | `jobs` | `job_id, status, error_message`| `SELECT * FROM jobs ORDER BY created_at DESC LIMIT 20` | `jobs.created_at` |
| **Hedef Ağırlık Ayarları** | `masa/config/portfoy.json` | `hedef_agirliklar` | JSON dosyasındaki hedef yüzdeler (Dosyada `hedef_agirliklar: {}` boş olduğunda Boş Durum gösterilir) | Dosya mtime |
| **Politika Toleransları** | `masa/config/politika.json` | `tolerans_mutlak, tolerans_goreli`| Risk yönetimi parametreleri | Dosya mtime |

---

### 5.7 Varlık Sayfası (Sabitlenmiş Varlıklar & Detay Görünümü)

#### 5.7.1 Amaç ve Mimari Konum
Varlık Sayfası, v2 yeniden tasarımının en güçlü yeniliğidir. Bir yatırımcının tek bir ETF veya hisse senedi hakkında bilmek isteyeceği **tüm verileri 7 farklı ekrandan toplayıp tek bir sayfada birleştiren** evrensel lenstir.

- **Erişim Yolları:**  
  1. Kenar çubuğunun altındaki **"Sabitlenmiş Varlıklar"** listesindeki herhangi bir ETF'e tıklayarak.
  2. ⌘1 Bugün veya ⌘2 Portföy tablolarındaki varlık satırına çift tıklayarak.
  3. ⌘3 Tahminler veya ⌘5 Keşif listesindeki enstrümana tıklayarak.
  4. `⌘K` Komut Paletinde ISIN/Ticker aratarak.

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│ ← GERİ  │  SPYI — STATE STREET SPDR MSCI ACWI IMI UCITS ETF (ACC)          [★ Sabitlendi]│
├────────────────────────────────────────────────────────────────────────────────────────┤
│ ISIN: IE00B3YLTY66 │ Ticker: SPYI.DE │ XETRA │ TER: %0,17 │ İrlanda UCITS │ Biriktiren │
│ Kotasyon: 11,614 € │ Alış: 11,600 € │ Satış: 11,628 € │ Makas: %0,24 ● CANLI           │
├────────────────────────────────────────────────────────────────────────────────────────┤
│ 1. MEVCUT POZİSYON VE DEĞERLEME (PORTFÖYÜMDEKİ DURUMU)                                 │
│ ┌───────────────┬───────────────┬───────────────┬───────────────┬────────────────────┐ │
│ │ PAY ADEDİ     │ PİYASA DEĞERİ │ ALIŞ MALİYETİ │ KÂR / ZARAR   │ PORTFÖY PAYI / HEDEF│ │
│ │ 100 Adet      │ 1.200,00 €    │ 11,500 €/ad   │ +50,00 €(+%4,35)│ %24,00 / %25,00   │ │
│ └───────────────┴───────────────┴───────────────┴───────────────┴────────────────────┘ │
├────────────────────────────────────────────────────────────────────────────────────────┤
│ 2. TAHMİN VE MODEL KONSENSÜSÜ (GÜNÜN TAHMİNİ: 1 KASIM 17:30 CET)                       │
│ • Günün Beklentisi: 11,640 € (↑ %0,22 YUKARI) · Yön İsabeti: — (N < 30 Koruması)       │
│ • Model Dağılımı: Local Momentum (↑ YUKARI), Gemini Pro (↑ YUKARI), Martingale (→ YATAY)│
├────────────────────────────────────────────────────────────────────────────────────────┤
│ 3. KARAR DESTEĞİ VE AKTİF YATIRIM TEZİ                                                 │
│ • Sistem Önerisi: [ TUT ] (Sapma -%2,84 tolerans sınırı içinde; tez sağlıklı)          │
│ • Aktif Tez: "Tek Dünya, Tek Fon Küresel Birikim Tezi" · Sağlık: [ SAĞLIKLI ]         │
│ • Çürütme Şartı 1: Global ticaret hacmi %40 daralırsa -> Normal (İhlal Yok)            │
│ • Çürütme Şartı 2: TER %0.30 üzerine çıkarsa -> Şu an %0.17 (İhlal Yok)                │
├────────────────────────────────────────────────────────────────────────────────────────┤
│ 4. FON İÇERİĞİ VE İLK 10 BİLEŞEN (HOLDING CONSTITUENTS)                                │
│ Apple (%4,2), Microsoft (%3,8), NVIDIA (%3,1), Amazon (%2,1), Alphabet (%1,9) ...      │
│ Portföy Örtüşmesi: IS3R ile %34,2 ortak bileşen · IS3S ile %18,4 ortak bileşen         │
├────────────────────────────────────────────────────────────────────────────────────────┤
│ 5. RESMİ KANITLAR VE BELGE İDDİALARI                                                   │
│ "State Street Factsheet (Eylül 2026): SPYI, 9.000+ hisse ile küresel pazarın %99'unu   │
│  kapsayan MSCI ACWI IMI endeksini tam fiziksel replikasyonla takip eder."              │
│ Kaynak: SPDR_Factsheet_202609.pdf (SHA-256: 4f8b2a...) · Red-Team Critic: [ DOĞRULANDI]│
└────────────────────────────────────────────────────────────────────────────────────────┘
```

#### 5.7.2 Varlık Sayfası Veri Eşleme Tablosu

| Görsel Modül / Kart | Kaynak SQLite Tablosu | Sütun / JSON Alanı | Hesaplama / Çekme Mantığı | Güncellenme Zamanı |
|---|---|---|---|---|
| **Kimlik & Borsa Bilgileri** | `instruments` + `listings` | `name, isin, base_currency, ticker, mic` | Resmi tanımlar ve birincil borsa kodu | `instruments.created_at` |
| **İhraççı Kuruluş & LEI** | `issuer_links` | `name, lei, country` | Varlığı ihraç eden tüzel kişilik ve LEI kodu | `issuer_links.created_at` |
| **Canlı Fiyat ve Makas** | `quotes` | `computed_mid, bid, ask, spread_pct` | Son geçerli kotasyon ve alış-satış farkı | `quotes.quote_timestamp` |
| **Pozisyon & Değerleme** | `position_observations` | `quantity, broker_cost_basis, value_eur` | Varlık portföyde varsa pay, maliyet ve değer | `position_observations.observed_at` |
| **Günün Tahmini & Yönü** | `v_forecasts_unsettled` | `target_price, direction, confidence_pct` | Varlığa ait günün mühürlü sabah tahmini | `forecast_entries.created_at` |
| **Yatırım Tezi & Çürütme** | `v_theses_current` | `title, falsification_triggers_json, status` | Bu ISIN'a atanmış aktif yatırım hipotezi | `thesis_versions.created_at` |
| **Fon İlk 10 Bileşeni** | `holding_items` | `constituent_isin, weight_pct` | `holdings_sets` üzerinden fonun en büyük holdingleri | `holdings_sets.as_of_date` |
| **Resmi Belge & Alıntı** | `v_evidence_verified` | `claim_text, quote_verbatim, source_title` | Doğrulanmış araştırma iddiaları ve alıntılar | `evidence_bundles.created_at` |
| **Geçmiş İşlemler** | `transaction_observations` | `event_time, side, quantity, amount` | Yalnızca bu ISIN ile yapılmış alım/satımlar | `transaction_observations.event_time` |


---

## Bölüm 6: Bileşen Kütüphanesi ve Veri Durumları

Yeni arayüz mimarisi, tutarlılığı sağlamak, kod tekrarını önlemek ve macOS HIG standartlarını tam olarak karşılamak amacıyla modüler bir **Bileşen Kütüphanesi (Design System)** üzerine inşa edilmiştir.

### 6.1 Yeniden Kullanılabilir UI Bileşenleri

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                        YENİDEN KULLANILABİLİR BİLEŞENLER                               │
├────────────────────────────────────────────────────────────────────────────────────────┤
│ 1. MetricCardView     : Başlık, büyük parasal değer, trend hapı, köken bilgisi.        │
│ 2. StatusBadge        : Renkli durum hapı (CANLI ●, BAYAT ○, MÜHÜRLÜ ✓, TASLAK ⚠).     │
│ 3. TrendPill          : Yüzdesel getiri ve yön oku (▲ +%0,42 Yeşil / ▼ -%2,19 Kırmızı).│
│ 4. FalsificationBox   : Yatırım tezi çürütme şartları kutusu (En az 2 kural).          │
│ 5. HeatmapCell        : Çiftli fon örtüşme matrisi renk yoğunluk hücresi.              │
│ 6. ConsoleStreamView  : Canlı CLI logları akış penceresi (SF Mono, otomatik kaydırma). │
│ 7. TableCell / DataRow: Standart finansal tablo hücresi (monospaced digit, sağa dayalı)│
└────────────────────────────────────────────────────────────────────────────────────────┘
```

1. **Finansal Metrik Kartı (`MetricCardView`):**  
   - Üst kısımda soluk kategori başlığı (örn: `TOPLAM PORTFÖY DEĞERİ`).
   - Ortada büyük, basamak kayması yapmayan `SF Mono` veya `monospacedDigit()` fontlu değer (örn: `5.000,00 €`).
   - Sağ üst köşede veri tazelik noktası (`●`, `◐` veya `○`).
   - Alt kısımda trend hapı (`+18,40 € (+%0,42)`) ve mikro köken etiketi (`run_70f907 · 11:48 UTC`).
2. **Durum Rozeti (`StatusBadge`):**  
   - Belirli bir varlığın, oturumun veya görevin durumunu ifade eden yuvarlatılmış hap (pill).
   - `ACTIVE` (Yeşil zemin, koyu yeşil yazı).
   - `DRAFT` / `WAITING` (Turuncu zemin, turuncu yazı).
   - `BREACHED` / `ERROR` (Kırmızı zemin, kırmızı yazı).
   - `UNVERIFIED` / `NOT_RUN` (Gri zemin, soluk yazı).
3. **K/Z Trend Rozeti (`TrendPill`):**  
   - Pozitif Değerler: `▲ +%1,45` (Yeşil zemin, yukarı ok).
   - Negatif Değerler: `▼ -%0,85` (Kırmızı zemin, aşağı ok).
   - Nötr / Sıfır: `▬ %0,00` (Gri zemin, yatay çizgi).
4. **Çürütme Şartları Kutusu (`FalsificationBox`):**  
   - Yatırım tezleri kartlarında yer alan özel denetim konteyneri.
   - Her çürütme kuralının başında mini radar ikonu, kural metni ve yanındaki canlı durum rozeti (`NORMAL` veya `İHLAL!`).
5. **Örtüşme Isı Haritası Hücresi (`HeatmapCell`):**  
   - İki ETF arasındaki ortak hisse senedi ağırlığına göre dinamik renk alan tablo hücresi:
     - %0 - %10: Koyu zemin (Nötr).
     - %10 - %30: Düşük mavi/yeşil yoğunluk.
     - %30 - %50: Orta sarı/turuncu yoğunluk.
     - > %50: Yüksek kırmızı yoğunluk (Aşırı portföy örtüşmesi uyarısı).
6. **Canlı Konsol Akış Penceresi (`ConsoleStreamView`):**  
   - Arka planda çalışan `etf-masa` süreçlerinin standart çıktısını (stdout/stderr) eşzamanlı gösteren koyu temalı terminal penceresi.
   - Yazı tipi: 11pt `SF Mono`, yeşil/beyaz metin.
   - Özellikler: Otomatik aşağı kaydırma (Auto-scroll), metin seçimi ve tek tıkla kopyalama (`⌘C`).
7. **Finansal Veri Tablosu Hücresi ve Satırı (`TableCell` / `DataTableRow`):**  
   - U12'de saptanan 400px genişliğindeki boş sütunları ve dikey/yatay hizalama bozukluklarını kökten önleyen, finansal veri standartlarına kilitlenmiş modüler tablo hücresi mimarisi.
   - Sütun Tipleri ve Katı Hizalama Kuralları:
     1. *Metin / Varlık / Ticker Hücreleri:* Sola dayalı (`alignment: .leading`), SF Pro Text 13pt Regular/Medium, metin taşmalarında `.truncationMode(.tail)`.
     2. *Parasal ve Sayısal Hücreler (Fiyat, Tutar, Piyasa Değeri, Maliyet):* Sağa dayalı (`alignment: .trailing`), SF Mono veya `Text(...).monospacedDigit()`, 13pt Regular, standart Alman/Avrupa para birimi formatlayıcı (`1.835,01 €`).
     3. *Yüzdesel Değerler ve Sapmalar (Getiri, Makas, Drift):* Sağa dayalı (`alignment: .trailing`), monospaced digit, semantik renk kodlamalı `TrendPill` veya renkli yüzde metni (`+%0,42`, `-%2,84`).
     4. *Durum ve Tazelik Hücreleri:* Ortalanmış veya sola dayalı sabit genişlikli `StatusBadge` / `FreshnessPillView`.
   - Dolgu (Padding) ve Satır Yüksekliği Standardı:
     - Yatay dolgu: Standart 8pt veya 12pt iç dolgu (`.padding(.horizontal, 8)`).
     - Dikey dolgu: 6pt satır aralığı (`.padding(.vertical, 6)`), sabit satır yüksekliği `rowHeight: 32pt`.
   - Sütun Genişliği Disiplini (U12 Garantisi): Her `TableColumn` tanımında `.width(min:ideal:max:)` zorunludur; `Table(..., selection: .constant(nil))` yerine verinin doğasına göre `TableCell` ile yapılandırılmış `LazyVStack` veya bounded `TableColumn` kullanılır.

---

### 6.2 Dört Temel Veri Durumu (Data States)

Uygulamanın her görünümü ve bileşeni, aşağıdaki 4 temel veri durumundan tam olarak birinde bulunmak zorundadır:

| Durum Adı | Tetiklenme Şartı | Görsel Temsil | Kullanıcı Etkileşimi |
|---|---|---|---|
| **1. Yükleniyor (Loading / Skeleton)** | SQLite sorgusu veya CLI komutu çalışırken. | İlgili satır ve kartlarda hafif yanıp sönen gri iskelet (Shimmer). Asla tüm ekranı donduran modal spinner kullanılmaz. | Arka plan işlemi iptal edilebilir (`Esc` veya `SIGINT`). |
| **2. Boş Veri (Empty State)** | Tabloda 0 satır olduğunda veya özellik hiç çalıştırılmadığında. | Ortalanmış simge, "Neden Boş?" açıklaması ve altında **[Tek Tıkla Eylem Butonu]**. Asla bomboş gri alan bırakılmaz. | Butona tıklayarak ilgili veri üretme sürecini başlatır. |
| **3. Hata Durumu (Error State)** | SQLite hatası, hash uyuşmazlığı veya CLI çıkış kodu $\ne 0$. | Kırmızı çerçeveli uyarı kutusu, anlaşılır hata metni ve **[Tekrar Dene]** butonu. Teknik detay "Hata Günlüğü" altındadır. | Tekrar dene butonu veya log kopyalama. |
| **4. Geçerli Veri (Populated State)** | Veritabanında doğrulanmış en az 1 mühürlü kayıt olduğunda. | Eksiksiz metrikler, tablolar, grafikler ve veri tazelik noktaları. | Sıralama, filtreleme, satıra tıklama ve inceleme. |

---

### 6.3 Dört Kademeli Veri Tazelik Sınıfı ve Swift `QuoteQualityStatus` Eşleşmesi

Finansal piyasaların dinamik yapısı gereği her veri alanının geçerlilik derecesi 4 sınıfa ayrılmıştır. Swift kod tabanındaki `QuoteQualityStatus` enum'ı (`FreshnessPillView.swift`) bu 4 finansal semantik sınıfla birebir eşleştirilmelidir:

1. **CANLI (`QuoteQualityStatus.FRESH` — Yeşil ●):**  
   - Veri son 15 dakika içinde borsa seansından veya broker API'sinden çekilmiştir.
   - Kullanım: Anlık piyasa değerleri, alış/satış makasları, canlı seans göstergeleri.
2. **GÜNCEL (`QuoteQualityStatus.RECENT` — Mavi ◐):**  
   - Son işlem gününün resmi borsa kapanış kotasyonuna (17:30 CET) aittir.
   - Borsa kapalıyken veya hafta sonu sistemdeki en taze resmi veridir. Eski `OUTDATED` etiketinin yarattığı "veri bozuk" algısını önler; seans kapalıyken verinin resmi kapanış niteliğini tescil eder.
3. **BAYAT (`QuoteQualityStatus.STALE` — Turuncu ○):**  
   - 24 saatten daha eski veya borsa seansı açık olmasına rağmen güncellenmemiş veriler.
   - Kartın kenarında turuncu uyarı çizgisi belirir; kullanıcıya "Verileri Yenile" (⌘R) önerisi sunulur.
4. **GEÇERSİZ / ÖLÇÜLMEDİ (`QuoteQualityStatus.UNVERIFIED` — Gri ◌):**  
   - Henüz doğrulama yapılmamış, simülasyon modunda veya $N < 30$ ampirik barajının altında kalan veriler (eski `UNKNOWN` durumunun finansal semantik karşılığıdır).

*Swift Entegrasyon Kuralı:* Aşama B kapsamında `macos/Sources/ETFCockpit/Components/FreshnessPillView.swift` içindeki `QuoteQualityStatus` enum'ı `{ case FRESH, RECENT, STALE, UNVERIFIED }` olarak modernize edilerek tüm kokpit genelinde tekilleştirilecektir.

---

## Bölüm 7: Düğme ve Eylem Envanteri

ETFCockpit v2 içindeki her buton, tetikleyici ve eylem doğrudan bir iş kuralına veya `etf-masa` CLI komutuna bağlıdır. Arayüzde hiçbir sahte, mock veya işlevsiz düğme bulunmaz.

| Düğme / Eylem Adı | Bulunduğu Ekran | Tetiklenen CLI Komutu / Swift Fonksiyonu | Yetki / Onay Seviyesi | Beklenen Sonuç ve UI Geri Bildirimi |
|---|---|---|---|---|
| **Sabah Akışını Çalıştır** | ⌘1 Bugün | `TodayDashboardViewModel.startMorningFlow()` | Standart (Tek tık) | 6 adım sırayla çalışır; canlı log akışı ve çıkış kodları basılır. |
| **Akışı İptal Et (SIGINT)** | ⌘1 Bugün & Shell | `CLIProcessRunner.cancel()` | Güvenli İptal | Çalışan sürece `SIGINT` gönderilir; işlem emniyetle durur. |
| **Giriş Yap (Safari/Terminal)**| ⌘1 Bugün | `sc login --local-read-only` | Kullanıcı Etkileşimi | Safari açılır; 2FA onay ekranı gelir; token beklenir. |
| **Oturumu Doğrula** | ⌘1 Bugün & ⌘6 | `masa giris --json` | Standart | Oturum aktifse kalkan yeşile döner; portföy yenilenir. |
| **Verileri Yenile** | ⌘1 Bugün & Toolbar | `masa veri && masa gecmis` | Standart | Canlı kotasyonlar çekilir; `snapshots` tablosuna yeni mühür yazılır. |
| **İşlemleri Çek** | ⌘2 Portföy | `masa islemler cek` | Standart | Scalable'dan yeni işlemler çekilir; deftere eklenir. |
| **Mutabakat Çalıştır** | ⌘2 Portföy | `masa mutabakat --detay` | Standart | 4 boyutlu mutabakat motoru koşar; kartlar güncellenir. |
| **Sabah Tahmini Üret** | ⌘3 Tahminler | `masa tahmin uret --json` | Standart | Günün 09:30 tahminleri `forecast_entries` tablosuna mühürlenir (`sabah` değil `uret`). |
| **Akşam Uzlaşması Yap** | ⌘3 Tahminler | `masa tahmin uzlas --json` | Standart | Kapanış kotasyonları ile hata/isabet hesaplanır ve mühürlenir. |
| **Derin Analiz Çalıştır** | ⌘4 Kararlar | `masa tradingagents [--evet] [isin ...]` veya `masa yorum` | **Açık Onay Diyaloğu** | Çok ajanlı derin analiz veya prompt derleme paketi koşturulur; LLM teyidi alınarak başlatılır (`--derin` bayrağı yoktur). |
| **Nakit Simülasyonu Butonları**| ⌘4 Kararlar | `RebalanceSimulator.simulate(cash:)` | Anlık Hesaplama | Satışsız alım adetleri drift tablosuna canlı yansır (+500€, +1.000€, +2.500€, +5.000€). |
| **Yeni Tez Ekle** | ⌘4 Kararlar | `masa tez ekle [argümanlar]` | Form Doğrulaması | En az 2 çürütme şartı kontrol edilir; DB'ye mühürlenir. |
| **Durum Raporu Oluştur** | ⌘4 Kararlar | `masa rapor` | Standart | Markdown durum raporu derlenir; önizleme paneline yüklenir. |
| **Yorum Paketi Derle** | ⌘4 Kararlar | `masa yorum` | Standart | Çoklu model yorum paketi üretilir; panoya kopyalama açılır. |
| **Şimdi Tara** | ⌘5 Keşif | `masa tarama --json` | Standart | Aday havuzu taranır; Z-skorları hesaplanır; sıralama yenilenir. |
| **Havuzu Kaydet** | ⌘5 Keşif | `masa ayar yaz --dosya havuz --json <JSON>` | Form Doğrulaması | Luhn algoritması ile kontrol edilir; `masa/config/havuz.json` güncellenir (`--json` parametresi zorunludur). |
| **Yeni Araştırma Başlat** | ⌘5 Keşif | `masa arastir <ISIN>` | Form Doğrulaması | Konumsal ISIN argümanı ile born-sealed kanıt paketi oluşturma süreci başlar (`--isin` bayrağı yoktur). |
| **Bütünlüğü Doğrula** | ⌘6 Sistem & Toolbar| `./etf-masa dogrula` | Standart | SHA-256 zinciri, 78 tetikleyici ve snapshot'lar adli taranır. |
| **Canlı Yedek Al** | ⌘6 Sistem | `masa yedek` | Standart | `masa/var/backups/` altında mühürlü `.db` kopyası oluşturulur (`al` alt komutu yoktur, doğrudan `masa yedek`). |
| **Geri Yükleme Provası** | ⌘6 Sistem | `masa yedek --prova` | Standart | Alınan yedeğin izolasyonda açılıp açılamadığı test edilir (`drill` değil `--prova` veya `masa geri-yukle --drill`). |
| **Yedekleri Budama (Prune)**| ⌘6 Sistem | `masa yedek budama --uygula --onay` | **Açık Onay Diyaloğu** | 7 günden eski günlük yedekler budanır; disk alanı kazanılır (Kuru çalışma: `masa yedek budama --kuru`). |
| **Servisleri Kur (Launchd)**| ⌘6 Sistem | `masa zamanla kur` | Yönetici İzni | `~/Library/LaunchAgents` altına plist dosyaları yüklenir. |
| **Servisleri Kaldır** | ⌘6 Sistem | `masa zamanla kaldir` | **Açık Onay Diyaloğu** | Otomasyon durdurulur; launchd servisleri bellekten atılır. |
| **Ajanı Manuel Çalıştır (`runAgentManually`)** | ⌘6 Sistem (Zamanlayıcı) | `./etf-masa calistir <agent_name>` veya `SchedulerAutomationViewModel.runAgentManually(agentLabel:)` (`launchctl start com.etf.masa.<agent>`) | Standart (Tek tık) | Zamanlayıcı ajanını (sabah, aksam, cuma) anında manuel tetikler; stdout loglarını `ConsoleStreamView`'a aktarır. |
| **Hedef Sepeti Kaydet** | ⌘6 Sistem | `masa ayar yaz --dosya portfoy --json <JSON>` | Toplam %100 Kontrolü | `masa/config/portfoy.json` dosyasına hedef ağırlıklar mühürlenir (`--json` parametresi zorunludur). |
| **Politikayı Onayla** | ⌘6 Sistem | `masa ayar yaz --dosya politika --json <JSON> --onayla-politika` | **Açık Onay Diyaloğu** | Yatırım politikası TASLAK statüsünden ONAYLANDI'ya geçer (`ayar` altında `onayla` komutu yoktur). |
| **Varlığı Sabitle / Kaldır** | 5.7 Varlık Sayfası | `AppState.togglePin(isin:)` | Standart | Kenar çubuğundaki hızlı erişim listesine ekler/çıkarır. |

*CLI Süreç Yönetimi ve Hata Yakalama Kuralı:* Arayüzdeki her eylem `CLIProcessRunner` asenkron sarmalayıcısı üzerinden yürütülür. Eğer çalıştırılan komut sözdizim hatası veya geçersiz parametre nedeniyle sıfır dışı bir çıkış kodu (özellikle `Exit code 2 - Argument Error` veya `Exit code 1`) üretirse; arayüz asla kilitlenmeyecek, `ConsoleStreamView` stderr çıktısını kırmızı renkle basacak ve görünüm otomatik olarak Bölüm 6.2'deki "Hata Durumu (Error State)" kutusunu ve "[Tekrar Dene]" butonunu devreye sokacaktır.

---

## Bölüm 8: Etkileşim Ayrıntıları, Kısayollar ve Bildirimler

### 8.1 Klavye Kısayolları Haritası

ETFCockpit v2, profesyonel finans terminallerinde olduğu gibi kullanıcının fareye dokunmadan tüm operasyonları klavyeden yürütmesini sağlayacak zengin bir kısayol haritasına sahiptir:

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                        KLAVYE KISAYOLLARI STANDARDI                                    │
├────────────────────────────────────────────────────────────────────────────────────────┤
│ GLOBAL NAVİGASYON:                                                                     │
│   ⌘1 : Bugün Ekranı              ⌘4 : Kararlar Ekranı                                  │
│   ⌘2 : Portföy Ekranı            ⌘5 : Keşif Ekranı                                     │
│   ⌘3 : Tahminler Ekranı          ⌘6 : Sistem Ekranı                                    │
│                                                                                        │
│ OPERASYONEL EYLEMLER:                                                                  │
│   ⌘K : Komut Paletini Aç         ⌘⇧P: Gizlilik Modunu Aç/Kapat (Bakiyeleri Maskele)    │
│   ⌘R : Verileri Yenile (masa veri)⌘F : Tabloda veya Ekranda Ara                        │
│   ⌘B : Bütünlüğü Doğrula         ⌘I : Sağ İnceleme Panelini (Inspector) Aç/Kapat        │
│   Esc: Çalışan Süreci İptal Et (SIGINT) / Açık Modalı Kapat                           │
└────────────────────────────────────────────────────────────────────────────────────────┘
```

---

### 8.2 macOS Menü Çubuğu (Menu Bar Extras) Entegrasyonu

Uygulama simge durumuna küçültüldüğünde veya arka planda çalışırken, macOS Menü Çubuğunun sağ üst köşesinde kompakt bir durum ikonu yer alır:

- **Görünüm:** Küçük borsa grafiği ikonu + anlık portföy değeri: `5.000,00 €`
- **Tıklanınca Açılan Menü:**
  - *Portföy Durumu:* `4 Pozisyon · Günlük: +18,40 € (+%0,42)`
  - *Borsa Seansı:* `XETRA Açık (Kapanışa 3s 15dk)`
  - *Broker Oturumu:* `Scalable Capital: Aktif ✓`
  - *Ayrıcı Çizgi*
  - *Hızlı Eylemler:*
    - "Verileri Yenile" (⌘R)
    - "Bugün Ekranını Aç" (⌘1)
    - "Sabah Başlangıç Akışını Çalıştır"
  - *Ayrıcı Çizgi*
  - *Uygulamayı Göster / Çıkış Yap (⌘Q)*
- **Güç Yönetimi ve Ekran Uykusu Optimizasyonu (`NSWorkspace` & `ProcessInfo`):**
  - Menü çubuğundaki seans sayacı ve veri sorgulama zamanlayıcısı (timer), `NSWorkspace.screensDidSleepNotification` dinlenerek ekran uyku moduna girdiğinde veya kapatıldığında tamamen durdurulur; gereksiz CPU ve pil tüketimi önlenir.
  - Mac pil gücündeyken (`IOPSGetProvidingPowerSourceType` denetimi) arka plan yoklama aralığı 15 saniyeden 60 saniyeye esnetilerek pil tasarrufu sağlanır.
  - Ekran uyandığında (`NSWorkspace.screensDidWakeNotification`) veya kullanıcı menü çubuğu simgesine tıkladığında anında tek bir taze veri sorgusu çekilerek arayüz senkronize edilir.

---

### 8.3 macOS Sistem Bildirimleri (`UNUserNotificationCenter`)

Uygulama, kritik piyasa ve sistem olaylarında macOS yerel bildirim merkezini kullanarak kullanıcıyı uyarır:

1. **Sabah Tahmini Hazır (09:30 CET):**  
   *"Günün sabah tahminleri mühürlendi. SPYI için beklenti: 11,64 € (↑ %0,22). İncelemek için tıklayın."*
2. **Akşam Uzlaşması Tamamlandı (17:40 CET):**  
   *"XETRA borsa kapanışı gerçekleşti. Günün 4 tahmini uzlaştırıldı. Model isabeti: %75. Detayları görün."*
3. **Kritik WAITING_AUTH Uyarısı (Oturum Düştü):**  
   *"Scalable Capital oturumunuzun süresi doldu. Akşam otomasyonunun aksamaması için lütfen 2FA girişinizi tazeleyin."*
4. **Tez Çürütme İhlali Alarmı:**  
   *"DİKKAT: SPYI için tanımlanan 'TER > %0.30' çürütme şartı tetiklendi. Yatırım tezinizi gözden geçirin."*

---

### 8.4 Finansal ve Teknik Terimler Sözlüğü (Domain Glossary)

Uygulama genelinde tutarlı bir dil birliği sağlamak ve gereksiz İngilizce jargonunu temizlemek amacıyla aşağıdaki terminoloji standardı benimsenmiştir:

| Terim (UI Dili) | İngilizce Karşılığı | Açıklama ve Finansal Anlamı |
|---|---|---|
| **Portföy Değeri** | Portfolio Value (NAV) | Portföydeki tüm menkul kıymetlerin ve nakdin güncel piyasa toplamı. |
| **Maliyet Tabanı** | Cost Basis | Menkul kıymetler satın alınırken ödenen komisyon dahil toplam birim maliyet. |
| **Ağırlık Sapması (Drift)**| Portfolio Drift | Bir varlığın canlı portföy payı ile hedef sepet ağırlığı arasındaki yüzdesel fark. |
| **Yatırım Tezi** | Investment Thesis | Bir ETF'in neden portföyde tutulduğunu açıklayan rasyonel gerekçe ve hipotez. |
| **Çürütme Şartı** | Falsification Trigger | Tezin artık geçerli olmadığını kanıtlayan ve satışı tetikleyen önceden tanımlı kural. |
| **Uzlaştırma** | Settlement / Reconciliation| Sabah üretilen tahmin hedef fiyatı ile akşam gerçekleşen resmi kapanış fiyatının kıyası. |
| **Yön İsabeti** | Directional Hit Rate | Modelin tahmin ettiği hareket yönünün (YUKARI/AŞAĞI) gerçekleşme yüzdesi. |
| **Brier Skoru** | Brier Score | Olasılıklı tahminlerin kalibrasyonunu ölçen karesel hata metriği (0 = Kusursuz, 0.25 = Naif). |
| **Kriptografik Mühür** | Born-Sealed Snapshot | Veritabanına yazılan verinin SHA-256 hash zinciri ile mühürlenip değiştirilemez kılınması. |
| **4 Boyutlu Mutabakat** | 4-Way Reconciliation | Hisse adedi, nakit, piyasa değeri ve maliyet tabanının bağımsız adli denetimi. |
| **Nakit Enjeksiyonu** | Cash Injection | Portföyü dengelemek için hisse satıp vergi ödemek yerine yeni nakitle eksik varlığı alma. |
| **Alış/Satış Makası** | Bid/Ask Spread | Piyasadaki en iyi alış teklifi ile en iyi satış teklifi arasındaki yüzdesel fark. |
| **Küçük Örneklem** | Small Sample ($N < 30$) | İstatistiksel olarak güvenilirlik barajını aşmamış yetersiz veri büyüklüğü. |
| **Teilfreistellung** | Partial Tax Exemption | Alman vergi kanununa göre hisse senedi fonlarının sermaye kazançlarının %30'unun vergiden muaf olması. |
| **TER** | Total Expense Ratio | Fonun yıllık toplam yönetim ve işletim gider oranı. |
| **Z-Skoru** | Standard Score ($\sigma$) | Bir metriğin havuz ortalamasından kaç standart sapma uzaklıkta olduğunu gösteren istatistik. |


---

## Bölüm 9: Görsel Düzen, Tipografi ve Bilgi Yoğunluğu Kuralları

ETFCockpit v2'nin görsel tasarımı, Apple'ın macOS İnsan Arayüzü Yönergeleri (Human Interface Guidelines — HIG) ile profesyonel finansal terminallerin (Bloomberg Terminal, FactSet) yüksek bilgi yoğunluğunu harmanlar. Arayüz ne süslü ve boşluklarla dolu bir web sayfası gibi gevşek, ne de okunması imkansız derecede karmaşık olmalıdır.

### 9.1 macOS HIG Standartları ve Bölünmüş Görünüm (Split View)

1. **3 Sütunlu Yerel Düzen (`NavigationSplitView`):**  
   - **Sol Sütun (Sidebar):** 220 px - 260 px genişliğinde, 6 ana bölüm ve altında Sabitlenmiş Varlıklar listesi.
   - **Orta Alan (Content):** Aktif ekranın ana tabloları, metrik kartları ve grafiklerini barındıran esnek içerik alanı (Minimum 800 px).
   - **Sağ Çekmece (Inspector Drawer):** Seçilen varlık, işlem veya olayın derin ayrıntılarını gösteren 320 px genişliğinde açılır-kapanır yan panel.
2. **Pencere Boyutları:**  
   - Minimum Desteklenen Boyut: `1100 x 750` piksel.
   - Varsayılan Açılış Boyutu: `1300 x 850` piksel.
   - Tam Ekran Desteği: Çoklu monitör veya büyük ekranlı Mac Studio/Pro ortamlarında tam ekran esneme kuralı.

---

### 9.2 Koyu Tema ve Finansal Semantik Renk Paleti

Finansal piyasaların saatlerce süren takibinde göz yorgunluğunu önlemek amacıyla ETFCockpit varsayılan olarak **Koyu Tema (Dark Mode)** odaklı tasarlanmıştır.

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                        FİNANSAL SEMANTİK RENK PALETİ                                   │
├────────────────────────────────────────────────────────────────────────────────────────┤
│ ARKA PLAN VE YÜZEYLER:                                                                 │
│   • Canvas Background  : #121316 (Koyu antrasit zemin)                                 │
│   • Card / Surface     : #1A1C22 (Kart ve panel arka planı)                            │
│   • Border / Divider   : #2A2D37 (İnce 1px kart sınırları ve tablo çizgileri)          │
│                                                                                        │
│ ANLAMSAL FİNANSAL RENKLER:                                                             │
│   • Finansal Pozitif   : #34C759 (Apple Green — Kâr, yükseliş, mühürlü durum)          │
│   • Finansal Negatif   : #FF3B30 (Apple Red — Zarar, düşüş, kural ihlali)             │
│   • Dikkat / Taslak    : #FF9500 (Apple Orange — Küçük örneklem, bayat kotasyon)       │
│   • Nötr / Çalışmadı   : #8E8E93 (Secondary Gray — Henüz ölçülmemiş, N/A veri)        │
│   • Vurgu / Aksiyon    : #0A84FF (Apple Blue — Yalnızca birincil butonlar ve linkler) │
└────────────────────────────────────────────────────────────────────────────────────────┘
```

- **Kontrast Oranı:** Tüm metin ve zemin kontrastları WCAG AAA standardında (minimum 7:1) tutulmuştur.
- **Doygunluk Kuralı:** Gözü yoran neon renklerden kaçınılmış; Apple'ın sistem renk paleti (`Color.green`, `Color.red`, `Color.orange`) yerel opaklıklarla (`opacity(0.15)` zemin) kullanılmıştır.

---

### 9.3 Tipografi Hiyerarşisi (SF Pro ve SF Mono)

Rakamların finansal tablolarda alt alta geldiğinde basamak kayması yapmaması ve profesyonel okunabilirlik için Apple sistem fontları katı bir kuralla eşleştirilmiştir:

| Kullanım Alanı | Yazı Tipi Ailesi | Boyut ve Ağırlık | Örnek Çıktı / Kod Karşılığı |
|---|---|---|---|
| **Ekran Başlıkları** | SF Pro Display | 20pt, Bold | `Portföy ve Varlıklar` |
| **Kart Başlıkları** | SF Pro Text | 11pt, Medium, Uppercase | `TOPLAM PORTFÖY DEĞERİ` |
| **Büyük Parasal Değerler**| SF Mono / Monospaced | 24pt, Semi-Bold | `5.000,00 €` |
| **Tablo Sayısal Hücreleri**| SF Mono / Monospaced | 13pt, Regular | `1.835,01 €`, `11,614 €` |
| **Varlık ve Fon İsimleri**| SF Pro Text | 13pt, Medium | `SPDR MSCI ACWI IMI UCITS ETF` |
| **Durum ve Rozet Metinleri**| SF Pro Text | 10pt, Semi-Bold | `● CANLI`, `✓ MÜHÜRLÜ` |
| **Terminal / CLI Logları**| SF Mono | 11pt, Regular | `run_70f907_portfolio sealed` |

---

### 9.4 Düzen Hatalarını Önleme Kuralları (U11 ve U12 Çözüm Kılavuzu)

1. **Segmented Picker Etiket Sıkışmasını Önleme (U11 Kuralı):**  
   - `Picker` bileşeni segmented stilde kullanılırken başlık metni genişliği çalmamalıdır.
   - **Kural:** Her segmented picker ya `.labelsHidden()` niteleyicisi almalı, ya da etiket boş string (`Picker("", ...)`) olarak geçilmelidir. Segment genişliği için `.frame(maxWidth: .infinity)` kullanılarak pencere boyutuna göre akışkan genişleme sağlanmalıdır.
2. **Tablolardaki 400 px Boş Sütun Hatasını Önleme (U12 Kuralı):**  
   - macOS `Table` bileşeni kullanılırken her `TableColumn` için kesin sınırlar belirlenmelidir:
     ```swift
     TableColumn("ISIN", value: \.isin)
         .width(min: 110, ideal: 120, max: 140)
     TableColumn("Piyasa Değeri") { item in
         Text(item.formattedValue).monospacedDigit()
     }.width(min: 90, ideal: 100, max: 120)
     ```
   - Seçim sütunu gerekmeyen yerlerde `Table(..., selection: .constant(nil))` yerine özel `LazyVStack` kart satırı mimarisi tercih edilmelidir.

---

## Bölüm 10: Aşamalı Uygulama Planı (A'dan H'ye) ve Kabul Kriterleri

Yeniden tasarımın hayata geçirilmesi, mevcut çalışan hiçbir işlevselliği bozmadan ve adli bütünlük zincirine (`./etf-masa dogrula`) zarar vermeden **8 mantıksal aşamada (A'dan H'ye)** yürütülmelidir.

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                     AŞAMALI UYGULAMA VE DOĞRULAMA PLANI                                │
├────────────────────────────────────────────────────────────────────────────────────────┤
│ Aşama A : Veri Katmanı ve SQL Sorgu Düzeltmeleri (U1, U3, U5, U8, U10 Kökleri)         │
│ Aşama B : Uygulama Kabuğu ve Bileşen Kütüphanesi Temeli (⌘1–⌘6, 7 UI Bileşeni, ⌘K)     │
│ Aşama C : Bugün (⌘1) ve Portföy (⌘2) Ekranlarının İnşası (Portföy Değer Doğrulaması)    │
│ Aşama D : Tahminler (⌘3) ve Döngü Entegrasyonu (09:30 Tahmin, 17:40 Uzlaşma, Karne)    │
│ Aşama E : Kararlar (⌘4) Ekranı (Değerlendirme, Sepet, +5.000€ Sim, U6 Arındırma)       │
│ Aşama F : Keşif (⌘5) Ekranı (Salt-Okunur Tarama, Z-Skoru +1.17 σ, Luhn Havuz)          │
│ Aşama G : Sistem (⌘6) Ekranı (Bütünlük, 231 MB Yedek Budama, launchd, Yapılandırma)   │
│ Aşama H : 5.7 Varlık Sayfası, Sistem Entegrasyonu ve Uçtan Uca Kabul Doğrulaması       │
└────────────────────────────────────────────────────────────────────────────────────────┘
```

---

### Aşama A: Veri Katmanı ve Sorgu Düzeltmeleri

- **Hedef:** Kullanıcı arayüzüne yanlış veya eksik veri sağlayan SQLite sorgularını ve veri erişim yöntemlerini düzeltmek.
- **Kapsam:**
  1. `DatabaseService.swift` içindeki `fetchPositions()` fonksiyonundan `CROSS JOIN` kaldırılacak; `latest_portfolio_snap` ve bağımsız kotasyon alt sorgusu yazılacak (U1).
  2. `fetchPositions()` fallback sorgusuna `WHERE snapshot_type = 'portfolio'` eklenecek (U1).
  3. `fetchTransactions()` sorgusundan `WHERE NOT EXISTS` kaldırılacak; `broker_tx_id NOT IN (SELECT broker_tx_id FROM transaction_versions)` ve `GROUP BY tx.broker_tx_id` tekilleştirmesiyle 614 tekil işlemin deftere akması sağlanacak; alt tipler için `COALESCE(security_transaction_type, cash_transaction_type)` kullanılacak (U3).
  4. `DatabaseService.swift` içine doğrudan `SELECT count(*) FROM snapshots` (65) ve `SELECT count(*) FROM audit_events` (147) sorguları eklenecek (U5).
  5. `LiveSessionTimerView.swift` içindeki XETRA açılış saati `09:00 CET` olarak düzeltilecek (U9).
- **Kabul Kriterleri (Doğrulanabilir):**
  - [ ] `DatabaseService.fetchPositions()` çağrısı canlı veritabanında tam 4 adet pozisyon ve doğru toplam portföy değerini döndürmelidir.
  - [ ] `DatabaseService.fetchTransactions()` çağrısı 600'den fazla işlem gözlemini tekilleştirilmiş biçimde başarıyla listelemelidir.
  - [ ] `swift test` çalıştırıldığında veri katmanı birim testleri 0 hata ile geçmelidir.

---

### Aşama B: Uygulama Kabuğu ve Bileşen Kütüphanesi Temeli

- **Hedef:** Kenar çubuğunu 14 dağınık öğeden 6 net bölüme ve Sabitlenmiş Varlıklar yapısına dönüştürmek; Durum Kapsülü ve ⌘K paletini kurmak; Bölüm 6.1'deki 7 temel atomik UI bileşenini ve `QuoteQualityStatus` tazelik modelini sonraki ekranların (C, D, E) doğrudan kullanabilmesi için stabilize etmek.
- **Kapsam:**
  1. `CockpitNavigationItem` enum'ı 6 değere indirgenecek (`today`, `portfolio`, `forecast`, `decisions`, `discovery`, `system`).
  2. İP kodları kenar çubuğundan tamamen kaldırılacak.
  3. Üst araç çubuğuna `StatusCapsuleView` yerleştirilecek (XETRA seans sayacı, Scalable oturum rozeti, veri tazeliği).
  4. Alt durum çubuğunda tam dosya yolu gizlenecek (`Masa.db v3 · 78 Tetikleyici`) (U16).
  5. `CommandPaletteView` (⌘K) Spotlight tarzı modal olarak entegre edilecek; `⌘⇧P` Gizlilik Modu kabuk düzeyinde bağlanacak.
  6. Sağ İnceleme Paneli (Inspector Drawer) altyapısı kurulacak.
  7. **Bileşen Kütüphanesi Temeli (Aşama C, D, E Ön Şartı):**
     - Bölüm 6.1'deki 7 temel atomik bileşen (`MetricCardView`, `StatusBadge`/`StatusPillView`, `TrendPill`, `TableCell` / `DataTableRow`, `FalsificationBox`, `HeatmapCell`, `ConsoleStreamView`) Swift görünümleri, katı hizalama ve dolgu standartlarıyla kodlanarak stabilize edilecek.
     - `macos/Sources/ETFCockpit/Components/FreshnessPillView.swift` içindeki `QuoteQualityStatus` enum'ı Bölüm 6.3'teki 4 sınıfa (`FRESH / CANLI`, `RECENT / GÜNCEL`, `STALE / BAYAT`, `UNVERIFIED / GEÇERSİZ`) genişletilecek.
     - `TableCell` / `DataTableRow` bileşeni monospaced digit, sağa dayalı sayısal hizalama ve para birimi formatlama ile U12'yi önleyecek standartta sunulacak.
- **Kabul Kriterleri:**
  - [ ] Kenar çubuğunda tam 6 ana bölüm ve altında Sabitlenmiş Varlıklar listesi görünmelidir.
  - [ ] ⌘1'den ⌘6'ya kadar kısayollar ilgili bölümleri anında açmalıdır.
  - [ ] Alt çubukta hiçbir kişisel dosya yolu (`~/...` ile maskelenmiş olmalıdır) yer almamalıdır.
  - [ ] 7 temel atomik bileşen (`MetricCardView`, `StatusBadge`, `TrendPill`, `TableCell`, `FalsificationBox`, `HeatmapCell`, `ConsoleStreamView`) SwiftUI Preview'ları ve birim testleriyle stabilize edilmiş olmalı; Aşama C, D, E ekranları bu bileşenleri doğrudan hatasız import edip derleyebilmelidir.

---

### Aşama C: Bugün (⌘1) ve Portföy (⌘2) Ekranlarının Hayata Geçirilmesi

- **Hedef:** Kullanıcının günlük operasyon panelini ve portföy/işlem/mutabakat defterini eksiksiz inşa etmek.
- **Kapsam:**
  1. Bugün (⌘1) ekranında 6 adımlı sabah akışı ve 2FA giriş yardımcısı kurulacak.
  2. Çıkış kodu 0 olsa dahi veri doğrulanmadan yeşil tik basılmayacak (U2).
  3. Bugün ekranı özet kartlarında 4 pozisyon ve portföy net aktif değeri gösterilecek.
  4. Portföy (⌘2) ekranında 4 alt sekme (`Canlı Pozisyonlar`, `İşlem Defteri`, `4D Mutabakat`, `Kurumsal İşlemler`) inşa edilecek; tablolar Aşama B'de stabilize edilen `TableCell` ile döşenecek.
  5. 4 boyutlu mutabakat kartlarında veri yokken sahte yeşil "Eşleşti" engellenecek; gri "Çalıştırılmadı" basılacak (U4).
  6. İşlem defterinde 614 tekil işlem filtrelenebilir ve aranabilir olacak; tarihsel alış hacmi (-250.793,98 €) ile portföy maliyet tabanı (örn: 5.000,00 €) bağımsız metrikler olarak gösterilecek.
- **Kabul Kriterleri:**
  - [ ] Bugün ve Portföy ekranlarında güncel portföy değeri eksiksiz görünmelidir.
  - [ ] Mutabakat çalıştırılmamışken kartlar gri "Çalıştırılmadı" göstermeli; butonla `masa mutabakat` tetiklenebilmelidir.
  - [ ] İşlem defterinde 614 tekil işlem listelenmeli; 0,00 € alış toplamı hatası görülmemeli; tarihsel alış hacmi ile maliyet tabanı ayrılmalıdır.

---

### Aşama D: Tahminler (⌘3) ve Döngü Entegrasyonu

- **Hedef:** Tahmin üretme → Uzlaşma → Model Karnesi döngüsünü ⌘3 altında birleştirmek.
- **Kapsam:**
  1. 4 alt sekme kurulacak: `Günün Tahminleri (09:30)`, `Uzlaşma Defteri (17:40)`, `Model Karnesi`, `Model Kaydı`.
  2. Sabah tahmini (`masa tahmin uret --json`) ve akşam uzlaşması (`masa tahmin uzlas --json`) CLI tetikleyicileri araç çubuğuna bağlanacak.
  3. $N < 30$ ampirik güvenilirlik kuralı katı uygulanacak; gözlem yokken isabet oranında tire `"—"` basılacak; YATAY tahminlerin $f_t = 0.50$ olasılık kuralı uygulanacak.
  4. Model karnesinde Martingale ve Momentum naif baz karşılaştırma kartları yer alacak.
  5. Model kaydı ekranındaki doğrulanmamış "0,00 € ZERO COST" statik rozetleri kaldırılacak (U15).
  6. Segmented picker'daki dikey metin kırılması engellenecek (`.labelsHidden()`, U11).
- **Kabul Kriterleri:**
  - [ ] $N < 30$ iken ekranda yüzde yerine `"—"` görünmeli ve küçük örneklem uyarısı yer almalıdır.
  - [ ] Segment seçicide "Görünüm" kelimesi dikey kırılmamalıdır.
  - [ ] Model kaydı ekranında test edilmemiş modeller gri "Doğrulanmadı" etiketi almalıdır.

---

### Aşama E: Kararlar (⌘4) Ekranı

- **Hedef:** Stratejik karar desteğini, hedef sepeti, tezleri ve raporları ⌘4 altında toplamak.
- **Kapsam:**
  1. 5 alt sekme kurulacak: `Değerlendirme`, `Hedef Sepet & Örtüşme`, `Dengeleme Simülatörü`, `Yatırım Tezleri`, `Raporlar`.
  2. Kalıcı yasal uyarı bandı yerleştirilecek ("Karar desteğidir; sistem işlem yapmaz").
  3. Çiftli fon örtüşme ısı haritası (`HeatmapCell`) ve Top 25 konsolide şirket tablosu inşa edilecek.
  4. Bireysel portföy genelindeki yanıltıcı "UCITS 5/10/40 İhlali" kartı kaldırılacak (U14).
  5. Satışsız nakit enjeksiyonu (+500€, +1.000€, +2.500€, +5.000€) dengeleme simülatörü kodlanacak.
  6. U6 test tezi üretim görünümünden filtrelenecek; yeni tez ekleme formunda en az 2 çürütme kuralı (`FalsificationBox`) zorunlu tutulacak.
  7. Hedef sepet için yerel dosya seçici (`NSOpenPanel`) entegre edilecek (`masa/config/portfoy.json` boş durum yönetimi, U13).
  8. Rapor ekranında tam metin seçilebilir Markdown görüntüleyici kurulacak.
- **Kabul Kriterleri:**
  - [ ] Dengeleme simülatöründe +1.000 € veya +5.000 € butonuna basıldığında satış yapmadan alım önerisi üretilmelidir.
  - [ ] Canlı ortamdaki U6 test tezi üretim tezleri arasında görünmemelidir.
  - [ ] Hedef sepet ekranında terminal komut metni yerine yerel dosya seçici butonu yer almalıdır.

---

### Aşama F: Keşif (⌘5) Ekranı

- **Hedef:** Aday taraması, aday havuzu yönetimi ve kaynaklı araştırma masasını ⌘5 altında yapılandırmak.
- **Kapsam:**
  1. 4 alt sekme kurulacak: `Fırsat Taraması`, `Aday Havuzu Düzenle`, `Kaynaklı Araştırma`, `Red-Team Critic`.
  2. Sayfa açılışındaki canlı tarama tetiklemesi engellenecek; salt-okunur son mühürlü sonuç doğrudan SQLite sorgusuyla yüklenecektir (U7).
  3. Z-skoru karne notu formatından (`1.17 / 10.0`) standart sapma formatına (`+1.17 σ`) dönüştürülecek (U10).
  4. Aday havuzu düzenleme ekranına `ISINValidator` ile Luhn algoritması denetimi eklenecek; `masa/config/havuz.json` güncellenecektir.
  5. Mühürlü kanıt paketleri, resmi verbatim alıntı kutuları ve Red-Team Critic skorkartı kurulacak; araştırma başlatma konumsal ISIN ile bağlanacaktır (`masa arastir <ISIN>`).
- **Kabul Kriterleri:**
  - [ ] Keşif ekranına girildiğinde `audit_events` tablosuna hiçbir yeni kayıt yazılmamalıdır (Salt-okunur gezinme).
  - [ ] Apple için tarama skoru `+1.17 σ` olarak yeşil renkle görünmelidir.

---

### Aşama G: Sistem (⌘6) Ekranı

- **Hedef:** Bütünlük, yedekleme budama, zamanlayıcı otomasyonu ve ayarları ⌘6 altında konsolide etmek.
- **Kapsam:**
  1. 4 alt sekme kurulacak: `Bütünlük & Güvenlik`, `Yedekleme & POSIX`, `Zamanlayıcı`, `Yapılandırma`.
  2. Snapshot mühür sayısı (65) ve denetim olay sayısı (147) doğrudan SQLite üzerinden çekilerek çelişki giderilecek (U5).
  3. 231 MB'a ulaşan yedekler için `masa/config/politika.json` budama motoru ve "Politikaya Göre Temizle" (`masa yedek budama --uygula --onay`) butonu eklenecek (U8).
  4. macOS `launchd` servis durumları `launchctl print` üzerinden dinamik okunacak; zamanlayıcı kartlarına "Şimdi Çalıştır (`runAgentManually`)" butonu eklenecek.
  5. `masa/config/portfoy.json` ve `masa/config/politika.json` yapılandırma editörleri stepper ve onay diyaloglarıyla güvenli hale getirilecek.
- **Kabul Kriterleri:**
  - [ ] Bütünlük ekranı "0 Mühürlü Snapshot" yerine tam 65 mühür göstermelidir.
  - [ ] "Politikaya Göre Temizle" butonuna basıldığında eski yedekler budanarak disk alanı kazanılmalıdır.
  - [ ] Zamanlayıcı kartındaki "Şimdi Çalıştır" butonu ajanı tetiklemeli ve logları konsola aktarmalıdır.
  - [ ] `./etf-masa dogrula` çalıştırıldığında 0 hata ile bütünlük doğrulanmalıdır.

---

### Aşama H: Varlık Sayfası (5.7), Sistem Entegrasyonu ve Uçtan Uca Kabul Doğrulaması

- **Hedef:** Çapraz Varlık Sayfasını (5.7) tamamlamak, sistem genelinde uçtan uca kabul testlerini yürütmek ve regresyon denetimini gerçekleştirmek.
- **Kapsam:**
  1. 5.7 Varlık Detay Sayfası kodlanacak; kenar çubuğundaki Sabitlenenler ve tablolardaki çift tıklama eylemlerine bağlanacak.
  2. Tablolardaki 400 px boş sütun hataları (`TableColumn.width`) ve `TableCell` entegrasyonu tüm ekranlarda doğrulanacak (U12).
  3. `⌘K` Komut Paleti tüm varlık ve eylemlerle test edilecek.
  4. `⌘⇧P` Gizlilik Modu tüm ekranlarda test edilecek.
  5. Swift derleme ve testleri koşturulacak (`swift test`).
- **Kabul Kriterleri (Nihai Kabul):**
  - [ ] SPYI varlığına tıklandığında kotasyon, portföy payı, günün tahmini, tezi, holding bileşenleri ve Factsheet kanıtları tek bir sayfada açılmalıdır.
  - [ ] **Adversarial Salt-Okunur Gezinme Denetimi:** Sekmeler arasında (⌘1–⌘6) 10 kez art arda hızlıca geçiş yapıldığında, salt-okunur gezinme ilkesi korunmalı ve `audit_events` tablosundaki kayıt sayısı (147) kesinlikle değişmemelidir (U7 regresyon testi).
  - [ ] U1'den U16'ya kadar 16 ekran hatasının tamamı çözülmüş olmalıdır.
  - [ ] `macos/` dizininde `swift test` sıfır (0) hata ile tamamlanmalıdır.
  - [ ] `cd masa && uv run pytest -q` sıfır (0) hata ile tamamlanmalıdır.
  - [ ] `./etf-masa dogrula` çalıştırıldığında 0 hata ile "Bütünlük Tam" onaylanmalıdır.
  - [ ] `git status` üzerinde `macos/` ve `masa/` kaynak kodlarında istenmeyen hiçbir değişiklik kalmamalıdır.
