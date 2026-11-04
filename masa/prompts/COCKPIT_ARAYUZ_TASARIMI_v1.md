# ETFCockpit: Arayüz Yeniden Tasarımı (v1, 1 Kasım 2026)

**Amaç:** Hiçbir özelliği kaybetmeden 14 ekranı 6 net bölüme indirmek. Her sayının ne zaman ve nereden geldiğini göstermek. Tahmin üretme → uzlaştırma → karne döngüsünü uygulamanın merkezine koymak.
**Girdi:** 1 Kasım 16:03 tarihli 14 ekran görüntüsü, Swift kaynak kodu, canlı veritabanının bir kopyası.
**Kapsam:** Tasarım ve içerik planı. Kod değişikliği içermez. Uygulama sırası 10. bölümde.

---

## 0. Önce düzeltilmesi gereken ekran hataları

Ekranlarda görünen bazı sayılar yanlış. Yeni tasarım yanlış veriyi daha güzel göstermemeli; bunlar ilk iş paketidir.

| # | Ekran | Görünen | Gerçek (DB kopyası, 16:10) | Muhtemel neden |
|---|---|---|---|---|
| U1 | Bugün, Portföy | "€0,00 · Pozisyon Yok", "0 Pozisyon" | Son portföy mührü `run_20261101T114810Z_70f907_portfolio`: 4 pozisyon, 5.000,00 € | Asıl sorgunun neden boş döndüğü incelenmeli. Yedek sorgu (`DatabaseService.swift:144`) "türü ne olursa olsun en son snapshot"u alıyor; bu şu an bir *tarama kotasyon* mührü olduğu için hep boş. Değerlendirme ekranı aynı 4 pozisyonu doğru gösteriyor. |
| U2 | Bugün | Başlangıç akışının 3 adımı da yeşil ✓ | Portföy 0 gösterilirken | Akış çıkış kodunu okumuyor (Y1). Yeşil tik yalnızca doğrulanmış sonuçta yanmalı. |
| U3 | İşlem Defteri | "3 İşlem Kayıtlı", alış toplamı 0,00 € | 626 işlem gözlemi | Ekran yalnızca *en son* işlem mührünü (artımlı, 3 kayıt) okuyor. Defter tüm mühürleri birleştirip `transaction_versions` ile tekilleştirmeli. |
| U4 | İşlem Defteri | 4 mutabakat kartı da "Eşleşti / %100" | Veri yüklenmemişken | Sahte yeşil. Mutabakat hiç çalışmadıysa "Çalıştırılmadı" gri görünmeli. |
| U5 | Bütünlük | "TEST EDİLMEDİ", "100 olay", "0 Mühürlü Snapshot", zincir "UNKNOWN" | Üst çubukta MATCH_SEALED; DB'de 64 mühür ve 145 olay | Ekran kendi sayaçlarını sayfa açılışında hesaplamıyor. Üst çubukla çelişiyor. |
| U6 | Tezler | 'Küresel 🚀 ETF Tezi: "Tek Dünya, Tek Fon" --json flag testi', hedef %0.5 | Canlı DB'ye yazılmış test verisi | Append-only olduğu için silinemez. "Geçersiz kıl" yapılmalı ve test kayıtlarını ayırt eden bir işaret eklenmeli. %0.5 değeri, hedef ağırlık normalizasyon hatasının (D5) canlı örneği. |
| U7 | Bütünlük (denetim günlüğü) | #144–145 tarama koşusu 16:04'te | Fırsat Taraması ekranı açıldığı anda | O2 doğrulandı: ekranı açmak canlı tarama başlatıyor ve kalıcı kayıt yazıyor. |
| U8 | Bütünlük | 13:59, 14:11, 14:17 yedekleri | Yedek şişmesi sürüyor | O3 (saklama politikası yok). |
| U9 | Üst çubuk | "Pazartesi 09:30 CET Bekleniyor" | Xetra 09:00'da açılır; 09:30 tahmin saati | Etiket karışık. "Xetra Pzt 09:00'da açılır · Sabah tahmini 09:30" olmalı. |
| U10 | Fırsat Taraması | "Tarama Skoru 1.17 / 10.0" | Skor bir z-skoru, 10 üzerinden değil | Ölçek yanlış. Ayrıca etiket sırası skor sırasıyla çelişiyor (0.1 "Araştırmaya değer", 0.7 "İzle") ve kural açıklanmıyor. |
| U11 | Tahmin, Model Kaydı | "Görünüm" kelimesi harf harf alt alta | Düzen hatası | Etiket genişliği sıfıra sıkışıyor. |
| U12 | Tüm tablolar | Solda ~400 px boş sütun | Düzen hatası | Kullanılmayan seçim/ikon sütunu. |
| U13 | Hedef Sepet | "Terminalden sepet yüklemek için: `./etf-masa sepet yukle …`" | GUI kullanıcıyı terminale yolluyor | Dosya seçici veya sürükle-bırak olmalı. |
| U14 | Hedef Sepet | "UCITS 5/10/40 Durumu" kartı | UCITS kuralı fonlar içindir, kişisel portföye uygulanmaz | Kart kaldırılmalı, yerine "Tekil şirket yoğunlaşması" konmalı. |
| U15 | Model Kaydı | "0,00 € · ZERO COST", "%100 GÜVENLİ", ama 5 modelin hepsi "DOĞRULANMADI" | Doğrulanmamış iddia | Kontrol edilmemiş güvence gösterilmemeli. `gemini-1.5-pro` için "subscription" erişimi de doğrulanmalı (Gemini uygulama aboneliği API erişimi değildir). |
| U16 | Alt durum çubuğu | `~/Documents/ETF/masa/var/private/masa.db` | Kişisel yol arayüzde | Gizlilik ve gürültü. Ayarlar > Hakkında içine taşınmalı. |

---

## 1. Mevcut arayüzün teşhisi

**Ekran gruplarının özeti:**
- 14 kenar çubuğu öğesinin 9'unda iç geliştirme kodları var (İP-1/10, İP-3, İP-7 …). Kullanıcı için anlamsız.
- 7 ekranın çoğunluğu boş ya da sıfır: Portföy, Tahmin, Araştırma, Sepet, Zamanlayıcı, Ayarlar. Boş ekranlar "neden boş, ne yapmalıyım" demiyor.
- Aynı bilgi 3 yerde tekrar ediyor: piyasa durumu üst çubukta iki kez ve sayfa başlığında bir kez; bütünlük üst çubukta, Bugün'de ve Bütünlük'te.
- Değerli içerik gömülü:
  * Değerlendirme kartlarındaki vergi notları gerçekten iyi, ama her kartta aynı iki satır tekrar ediyor ("Eşikler TASLAK", "Piyasa kapalı").
  * Rapor ekranı, LLM'e verilecek ham promptu monospace metin olarak gösteriyor.

**Görsel gürültü:**
- Her kartta renkli etiket (EUR, CASH, SHARES, METRICS, AUDIT …).
- Kalın, turuncu yasal uyarı bandı.
- Sıfır değerli 10 KPI kartı.

**Eksik olan:**
- Hiçbir sayının yanında "ne zaman ve hangi kaynaktan" yok.
- Bir varlığa tıklayıp onun her şeyini (grafik, tahmin geçmişi, tez, kararlar) tek yerde görmek mümkün değil.
- Tahminlerin geçmişini izlemek mümkün değil.

---

## 2. Tasarım ilkeleri

1. **Tek bakış, tek soru.** Her ekran tek bir soruyu cevaplar. Bugün: "Bugün bir şey yapmam gerekiyor mu?" Portföy: "Neyim var, nasıl gidiyor?" Tahminler: "Modeller ne kadar isabetli?" …
2. **Her sayı tarih ve kaynak taşır.**
   - Küçük bir tazelik noktası: ● canlı (<15 dk), ◐ son kapanış, ○ bayat.
   - Üzerine gelince ipucu: "Scalable · 31 Eki 17:35 · run_…".
3. **Durum tek yerde.** Piyasa, oturum, veri tazeliği ve bütünlük yalnızca üst çubuktaki **Durum Kapsülü**'nde görünür. Sayfalar tekrar etmez.
4. **Kademeli ayrıntı.**
   - Liste → sağ **İnceleme paneli** (Inspector) → tam **Varlık sayfası**.
   - Teknik ayrıntı (hash, run_id, çıkış kodu) "Ayrıntı" altında saklanır.
5. **Boş durum = neden + tek eylem.** Örnek: "Henüz tahmin yok. Tahmin döngüsü kurulmadı. [Zamanlayıcıyı kur]".
6. **Dürüst renk.** Yalnızca 4 durum rengi:
   - yeşil = doğrulandı/iyi;
   - sarı = dikkat/taslak/kısmi;
   - kırmızı = hata/çelişki;
   - gri = bilinmiyor/çalıştırılmadı.

   Vurgu rengi (mavi) yalnızca birincil butonda. Hiçbir şey "varsayılan yeşil" değildir.
7. **Jargon yok, dil tutarlı.** İP kodları kalkar. İngilizce terimler Türkçeleşir (Sözlük, bölüm 8.6). Teknik terim gerekiyorsa ipucunda verilir.
8. **Tehlikeli eylem gizli ve onaylı.** Geri yükleme, sıfırlama, zamanlayıcı kaldırma: ana görünümde değil, "Gelişmiş" altında, sonucu açıklayan onay sayfasıyla.
9. **Uzun işler engellemez.** Veri çekme ve derin analiz arka planda çalışır. İlerleme üst çubuktaki **Etkinlik** düğmesinde görünür, iptal edilebilir. Gerçek çıkış kodları gösterilir.
10. **Mac yerlisi.**
    - Kenar çubuğu + içerik + inceleme paneli (üç sütunlu düzen), araç çubuğu, menü çubuğu komutları, klavye kısayolları.
    - Apple'ın Human Interface Guidelines yönergelerindeki bölünmüş görünüm (split view) düzeni izlenir.

---

## 3. Yeni bilgi mimarisi

### 3.1 Kenar çubuğu: 14 öğe → 6 bölüm

```
┌──────────────────────────┐
│  ☀︎  Bugün          ⌘1    │  günlük brifing, yapılacaklar
│  ◔  Portföy        ⌘2    │  pozisyonlar · işlemler · dağılım · maliyet&vergi
│  ◎  Tahminler      ⌘3    │  bugün · defter · karne · kalibrasyon
│  ⚖︎  Kararlar       ⌘4    │  değerlendirme · tezler · derin analiz · raporlar
│  ⌕  Keşif          ⌘5    │  tarama · izleme listesi · araştırma
│ ─────────────────────── │
│  ⚙︎  Sistem         ⌘6    │  sağlık · otomasyon · modeller · ayarlar
│ ─────────────────────── │
│  SABİTLENMİŞ VARLIKLAR   │  (kullanıcının sabitlediği 4–8 ISIN; tıkla → Varlık sayfası)
│   SPYI  ▲0,4%  ●         │
│   EIMI  ▼0,2%  ◐         │
│   …                      │
└──────────────────────────┘
```

- Alt başlık satırları (açıklamalar) kalkar; ad yeterli. Açıklama ipucuna taşınır.
- Kenar çubuğunda yalnızca anlamlı rozetler: Tahminler'de "3 uzlaşma bekliyor", Kararlar'da "1 çatışma".
- "Sabitlenmiş varlıklar" Bloomberg'deki izleme listesi mantığında çalışır. Tıklanınca o varlığın sayfası açılır.

### 3.2 Eski → yeni eşleme (hiçbir özellik kaybolmuyor)

| Eski ekran | Yeni yeri |
|---|---|
| Bugün | **Bugün** |
| Portföy ve Varlıklar | **Portföy › Pozisyonlar** |
| Günlük Tahmin ve Uzlaşma | **Tahminler** (4 sekme) |
| Değerlendirme | **Kararlar › Pozisyon kararları** |
| Fırsat Taraması | **Keşif › Tarama** |
| Rapor ve Yorum | **Kararlar › Raporlar** (yorum paketi = "Prompt'u kopyala" düğmesi) |
| Kaynaklı Araştırma | **Keşif › Araştırma** ve Varlık sayfası › Araştırma |
| Model Kaydı ve Değerlendirme | **Sistem › Modeller** (model *tahmin* başarısı → Tahminler › Karne) |
| İşlem Defteri ve Kurumsal | **Portföy › İşlemler** (mutabakat bu sekmenin üst şeridinde) |
| Hedef Sepet ve Örtüşme | **Portföy › Dağılım ve Örtüşme** + Ayarlar › Hedef portföy |
| Yatırım Tezleri | **Kararlar › Tezler** ve Varlık sayfası › Tez ve kararlar |
| Bütünlük ve Güvenlik | **Sistem › Sağlık** + üst çubuktaki Durum Kapsülü |
| Görev Zamanlayıcı | **Sistem › Otomasyon** + üst çubuktaki Etkinlik |
| Sistem Yapılandırması | **Sistem › Ayarlar** |
| (yok) | **Varlık sayfası**: her yerden açılan ortak varlık ekranı |
| (yok) | **⌘K komut paleti**: varlık ara, komut çalıştır |

---

## 4. Uygulama kabuğu (her ekranda ortak)

### 4.1 Üst araç çubuğu

```
[≡] Bugün          ( ● Piyasa kapalı · Xetra Pzt 09:00 │ ● Oturum açık · 5 g │ ◐ Veri: Cum 17:35 │ ✓ Mühür )      [⟳] [▶ Sabah Akışı] [⌘K] [⏱ 0] [▤]
 │                                     DURUM KAPSÜLÜ (tıklanınca açılır pencere)                                                     │       │      │     │
 sayfa adı                                                                                                    yenile  birincil  arama  etkinlik  inceleme paneli
```

**Durum Kapsülü** dört parçadan oluşur. Her biri renkli nokta ve kısa metin. Kapsüle tıklanınca ayrıntı penceresi açılır:

| Parça | Değerler | Ayrıntı penceresinde |
|---|---|---|
| Piyasa | Açık / Kapalı (hafta sonu, tatil, seans sonrası) | Xetra saatleri, bir sonraki açılış, bugünkü tahmin ve uzlaşma saatleri |
| Oturum | Açık (kalan süre) / Bitiyor (<24 sa) / Kapalı | Son giriş zamanı; 7 gün ve 24 saat boşta kalma kuralı; **[Giriş yap]** |
| Veri | Canlı / Son kapanış / Bayat (eşik politikada) | Son `veri`, `gecmis`, `islemler` zamanları ve kaliteleri (DEGRADED ise neden); **[Verileri yenile]** |
| Mühür | ✓ Doğrulandı / ! Uyuşmazlık / ? Doğrulanmadı | Son doğrulama zamanı ve sonucu; **[Şimdi doğrula]** → Sistem › Sağlık |

- **[▶ Sabah Akışı]**: tek birincil düğme, kısayol ⌘⇧S. Bölüm 5.1'deki 6 adımlı akışı başlatır. Akış çalışırken düğme "Durdur" olur.
- **[⟳]** (⌘R): yalnızca mevcut ekranın verisini DB'den yeniden okur. Broker'a gitmez. Broker'dan veri çekmek ayrı bir eylemdir ("Verileri yenile").
- **[⏱ Etkinlik]**: çalışan ve son 20 işin listesi. Her satırda ad, ilerleme, süre, çıkış kodu, "Günlüğü göster", "İptal". Hata varsa rozet kırmızı olur. Eski zamanlayıcı kuyruğu tablosu buraya taşınır.
- **[▤]** (⌘I): sağ inceleme panelini açar ve kapatır.

### 4.2 Alt durum çubuğu (sade)

`Son yenileme 16:03 (bugün) · Yedek: 2 sa önce · Şema v3`

- DB yolu, tetikleyici sayısı ve "Append-Only" yazısı kaldırılır; Sistem › Sağlık'ta durur.

### 4.3 İnceleme paneli (sağ, 320–380 pt)

Herhangi bir listede bir satır seçilince açılır: pozisyon, tahmin, tarama adayı, işlem, denetim olayı. İçerik türe göre değişir. Panelin altında her zaman:
- **[Varlık sayfasını aç]**
- **[ISIN'i kopyala]**

### 4.4 ⌘K komut paleti

- **Varlık arama:** ISIN, ad ya da sembol → Varlık sayfası.
- **Komutlar:** "Verileri yenile", "Sabah tahminlerini üret", "Uzlaştır", "Tarama yap", "Derin analiz: <varlık>", "Yedek al", "Mühürü doğrula", "Politika eşiklerini aç" …
- Her komutun yanında, broker'a gidip gitmediği ve model çağrısı yapıp yapmadığı simgeyle gösterilir (🔌 broker, ✦ model).

---

## 5. Ekran ekran tasarım

### 5.1 BUGÜN: "Bugün bir şey yapmam gerekiyor mu?"

```
┌───────────────────────────────────────────────────────────────────────────────────────┐
│ Pazar, 1 Kasım 2026                                                                     │
│ Piyasa kapalı · Değerler Cuma 30 Eki kapanışına göre                                    │
├───────────────────────────────┬───────────────────────────────────────────────────────┤
│ PORTFÖY                        │  DİKKAT GEREKTİRENLER (en fazla 5)                    │
│ 5.000,00 €        ◐ Cum 17:35 │  ! Politika eşikleri taslak     [Gözden geçir]         │
│ Hafta  +0,8 %  +34,10 €       │  ! Tahmin döngüsü kurulu değil  [Zamanlayıcıyı kur]   │
│ Toplam −95,54 € (−2,1 %)      │  · 3 pozisyonun tezi yok        [Tez yaz]             │
│ ▁▂▂▃▃▄▃▄▅▅▆ (3 ay, maliyet ---)│  · Oturum 5 gün sonra bitecek                         │
├───────────────────────────────┴───────────────────────────────────────────────────────┤
│ SON GİRİŞİNDEN BERİ NE DEĞİŞTİ?  (Cuma 30 Eki 19:22'den beri)                [Tümü ›]   │
│  · Fiyatlar: SPYI +0,4 %, EIMI −0,2 %, IWMO −0,1 %, IWVL +0,3 %                         │
│  · Kararlar: değişiklik yok (4 × TUT)                                                   │
│  · Yeni işlem yok · Tez tetikleyicisi yaklaşan yok                                      │
├────────────────────────────────────────────────────────────────────────────────────────┤
│ TAHMİN ŞERİDİ                                                                           │
│  Son iş günü (Cum): 7/10 isabet  ·  "Değişmez" ölçütü: 5/10  ·  20 günlük: %58 (N=12)    │
│  Pazartesi 09:30'da 10 yeni tahmin üretilecek                        [Tahminlere git ›] │
└────────────────────────────────────────────────────────────────────────────────────────┘
```
*(Örnekteki fiyat değişimleri ve isabet sayıları temsilidir.)*

**Davranış:**
- Açılışta önce **son başarılı durum** gerçek tarihiyle gösterilir; yenileme arka planda yapılır. Yenileme başarısız olursa eski tarih kalır ve sarı "güncellenemedi" notu çıkar.
- **Sabah Akışı** başlayınca "Ne değişti" kartının yerine geçici bir adım şeridi gelir:
  `① Oturum ✓ 0,8 sn  ② Veri ✓ 12 sn (çıkış 0)  ③ Geçmiş ↷ atlandı (son 24 sa)  ④ Değerlendirme …  ⑤ Yorum (model)  ⑥ Tarama`
  - Her adım tıklanınca günlüğü açılır.
  - Çıkış kodu 2 ise sarı "kısmi"; 1 ise kırmızı ve akış durur.
  - Model kotası dolarsa ⑤ gri "atlandı, deterministik karar geçerli" olur; akış başarısız sayılmaz.
- **Dikkat gerektirenler** bir gelen kutusu gibi çalışır. Kaynakları: oturum süresi, taslak politika, kurulmamış zamanlayıcı, tezi olmayan pozisyon, uzlaşma bekleyen tahmin, tez tetikleyicisi, çelişkili TradingAgents görüşü, başarısız iş.
  - Her öğe tek düğme taşır.
  - "Ertele (7 gün)" seçeneği var.
- **Kaldırılanlar:** Kriptografik bütünlük kartı (Durum Kapsülü'ne taşındı), yinelenen piyasa etiketleri, "Veri hattı" kartı (Sabah Akışı'na ve Durum Kapsülü › Veri'ye taşındı).

### 5.2 PORTFÖY: "Neyim var, nasıl gidiyor?"

Sekmeler: **Pozisyonlar · İşlemler · Dağılım ve Örtüşme · Maliyet ve Vergi**

#### 5.2.1 Pozisyonlar
Üst şerit en fazla 4 sayı içerir:
`Değer 5.000,00 € · Yatırılan 5.000,00 € · K/Z 0,00 € (0,0 %) · Nakit 0,00 €`
*(Yatırılan tutar ve K/Z temsilidir.)*

| Varlık | Adet | Fiyat | Değer | Ağırlık / hedef | K/Z | Karar | 3A |
|---|---|---|---|---|---|---|---|
| SPDR MSCI ACWI IMI · `IE00B3YLTY66` | 100,0 | 10,00 € ◐ | 1.000,00 € | ███████░ 20 % │ hedef — | 0,00 € | TUT | ▁▂▃▅ |

- **Sütunlar:** Sayılar sağa hizalı ve sabit genişlikli rakamla yazılır. Ağırlık sütunu, hedef tanımlıysa ince bir hedef çizgisi gösterir. "Karar", Kararlar ekranındaki etikettir.
- **Fiyat sütunu:** Tazelik noktası taşır. Bid/ask makası ve kotasyon kalitesi yalnızca ipucunda görünür.
- **Satır seçimi:** İnceleme panelinde 1 aylık mini grafik, son karar ve gerekçesi, tez özeti, son 3 işlem ve "Bu varlığın tahmin isabeti" gösterilir.
- **Filtre:** ETF / Hisse / Tümü. Arama alanı ⌘F ile açılır.
- **Nakit ayrıntısı:** Takası tamamlanan, takastaki, tahakkuk eden, açık emir. Tek satırlık katlanır bir bölüme taşınır; varsayılan kapalı. Sıfırsa gösterilmez.
- **Boş durum:** "Pozisyon verisi okunamadı. Son başarılı okuma: … [Verileri yenile]". U1 gibi bir hatada "0 €" asla gösterilmez; "okunamadı" gösterilir.

#### 5.2.2 İşlemler (eski İşlem Defteri + Mutabakat)

```
Mutabakat: ✓ 4/4 eşleşti · 31 Eki 19:30          [Mutabakatı çalıştır]  [İşlemleri çek 🔌]
(hiç çalışmadıysa:  ○ Mutabakat hiç çalıştırılmadı)
```

- **Filtre çipleri:** Alış · Satış · Tasarruf planı · Temettü · Ücret · Nakit giriş/çıkış · Kurumsal işlem. Ayrıca yıl seçici ve varlık seçici var.
- **Seçili filtrenin toplamları:** tablo altında, sabit satırda (adet, tutar, ücret).
- **Kaynak:** Tablo tüm işlem mühürlerinin tekilleştirilmiş birleşimidir (U3). Sürümü değişmiş işlemlerde "düzeltildi" simgesi bulunur. İnceleme panelinde sürüm geçmişi görünür.
- **Satır seçimi (İnceleme paneli):** işlem ayrıntısı, hangi mühürden geldiği, FIFO eşleşmesi (satışsa hangi alış lotlarını kapattığı).
- **Mutabakat ayrıntısı:** Adet, nakit, değerleme ve maliyet tabanı için dört satırlık bir tablo. Bu tablo işlem listesinin üstünde katlanır bölüm olarak durur; ayrı sekme değildir.

#### 5.2.3 Dağılım ve Örtüşme (eski Hedef Sepet)
1. **Gerçek ve hedef ağırlık:** Yatay çubuklar ve sapma (puan). Hedef yoksa "Hedef portföy tanımlı değil [Hedef belirle]" (Ayarlar'a gider).
2. **Birikim dağıtımı:** "Bu ay X € yatıracağım" alanı → satış gerektirmeden fon başına önerilen tutar.
   - Bu bir öneridir; sistem işlem yapmaz.
   - Asgari işlem tutarı politikadan gelir (bugün 25 €).
3. **Örtüşme matrisi:** 4×4 ısı haritası, fon çiftlerinin ortak ağırlığı. Hücreye tıklanınca ortak ilk 10 şirket listelenir.
4. **Gerçek maruziyet:** İlk 25 şirket, ülke ve sektör. Pozisyon ağırlığı × fon içi ağırlık olarak hesaplanır. Her satırda verinin "as of" tarihi bulunur.
5. **Yoğunlaşma uyarısı:** "Tek şirket portföyün % X'i" (eşik politikada). UCITS kartının yerine geçer.
- **Boş durum:** "Fon içerik dosyaları yüklenmedi. [İhraççıdan çek 🔌] veya [Dosya seç…]" ya da sürükle-bırak. Terminal komutu gösterilmez.

#### 5.2.4 Maliyet ve Vergi
- **Maliyet:** Ağırlıklı TER, yıllık maliyet (€), fon başına TER.
- **Freistellungsauftrag:** Kullanım çubuğu, örneğin `██████░░░░ 612 € / 1.000 €`. Kırılım: gerçekleşen kâr, dağıtım, Vorabpauschale.
- **Vorabpauschale tahmini:** Ocak'ta kesilecek tahmini tutar. Basiszins kullanıcı girdisidir (girilmediyse "Basiszins girilmedi [Gir]").
- **Gerçekleşmiş K/Z (FIFO):** yıl bazında.
- Her bölümde küçük not: "Tahmindir, vergi tavsiyesi değildir."

### 5.3 TAHMİNLER: "Modeller ne kadar isabetli, geçmişte ne dedik?"

Bu ekran isteğinizin merkezinde. Tasarımın temeli, her tahminin değiştirilemez bir kayıt olması. Bir tahmin yaşam döngüsü boyunca şu bilgileri taşır:

```
ÜRETİLDİ (09:30) ──► AÇIK (gün içi izleniyor) ──► UZLAŞTI (17:40) ──► KARNEYE GİRDİ
   kayıt:   tarih/saat, model+sürüm, varlık, ufuk (1 gün / 1 hafta / 1 ay), referans fiyat,
            tahmin (yön + hedef fiyat + [olasılık veya aralık]), kullanılan veri paketi hash'i,
            kısa gerekçe
   uzlaşma: gerçekleşen fiyat, hata (€ ve %), yön isabeti, ölçüt modellerin sonucu
   durumlar: Bekliyor · İsabet ✓ · Iska ✗ · Veri yok (gri) · İptal (piyasa kapalı, tatil)
```

Sekmeler: **Bugün · Defter · Karne · Kalibrasyon**

#### 5.3.1 Bugün
```
Pzt 2 Kas · Sabah tahmini 09:30 ✓ üretildi · Uzlaşma 17:40'ta (5 sa 12 dk)      [Uzlaştır] (17:35'ten önce pasif)
ETF ───────────────────────────────────────────────────────────────────────────────────────
│ SPYI  ▲ +0,3 %  hedef 11,67 €  │ ref 11,63 │ şimdi 11,65 ◐ ▓▓▓▓▓░ hedefe %60 │ güven: gizli (N<30) │
│ EIMI  ▼ −0,2 %  …                                                                              │
HİSSE ─────────────────────────────────────────────────────────────────────────────────────
│ SAP   ▲ …                                                                                      │
```
- **Gruplama:** ETF ve Hisse ayrı. Her kartta model adı küçük yazıyla bulunur. Birden çok model varsa kart genişler ve modeller satır satır, yan yana durur.
- **"Sabah tahminlerini üret":** Yalnızca bugün işlem günüyse ve tahmin henüz üretilmediyse aktiftir. Aksi halde nedeni ipucunda yazar ("Bugün tahmin zaten üretildi 09:30" / "Piyasa kapalı").
- **"Uzlaştır":** 17:35'ten sonra aktif.
- Aynı anlama gelen iki düğme bulunmaz; eski "Sabah Tahmini (09:30)" ve "Akşam Uzlaşması (17:40)" düğmeleri bu ikisine dönüşür.
- **Hafta sonu ve tatil:** "Bugün tahmin yok — Xetra kapalı. Sonraki: Pzt 09:30." Altında son iş gününün sonuçları gösterilir.

#### 5.3.2 Defter (tüm geçmiş tahminler; asla silinmez)

| Tarih | Varlık | Sınıf | Model | Ufuk | Tahmin | Referans | Gerçekleşen | Hata | Sonuç | Değişmez | Dünkü yön |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 30 Eki | SPYI | ETF | ens-v1 | 1G | ▲ 11,67 | 11,63 | 11,63 | −0,3 % | ✗ | ✓ | ✗ |

- **Filtreler:** tarih aralığı, sınıf (ETF/Hisse), varlık, model, ufuk, sonuç (✓/✗/veri yok), durum (açık/uzlaşmış/iptal).
- **Satır seçimi (İnceleme paneli):**
  - kaydın tamamı;
  - "o gün kullanılan veri paketi" (hash ve tarih);
  - model sürümü;
  - gerekçe metni;
  - uzlaşma hesabı (hangi kapanış, hangi kaynak);
  - **[O günün verisiyle aç]**: zamanda geriye dönük görünüm; sonradan gelen veri gösterilmez.
- Her satırda 🔒 değiştirilemez simgesi.
- **[CSV dışa aktar]** düğmesi.
- **Altta özet:** Filtrelenmiş kümenin isabet oranı ve ortalama hatası.

#### 5.3.3 Karne
**Üst şerit:**
`Uzlaşmış N = 47 · Yön isabeti %57 (%95 güven aralığı 43–70) · Ortalama mutlak yüzde hata %0,62 · "Değişmez"e göre +6 puan · "Dünkü yön"e göre +2 puan`
*(Sayılar temsilidir.)*

- **N < 30:** Şerit gri, metin "Örneklem küçük — sonuçlar istatistiksel olarak anlamlı değil". Güven aralığı bant olarak çizilir.
- **Grafik 1:** 20 günlük kayan isabet oranı. Çizgiler: model(ler), "Değişmez", "Dünkü yön". %50 referans çizgisi var.
- **Grafik 2:** ETF ve Hisse yan yana çubuk (isabet, MAE). Ufuk seçici: 1G / 1H / 1A.
- **Isı tablosu:** Satırlar varlıklar, sütunlar haftalar, hücre isabet oranı (renk + sayı). Hangi varlıkta model iyi, hangisinde kötü bir bakışta görünür.
- **Model karşılaştırma tablosu:** Model × metrik (N, isabet, MAE, Brier, ölçütlere göre fark).
  - "En iyi model" rozeti yalnızca N ≥ politika eşiğinde verilir (kullanıcı onaylı).
  - Eski Model Kaydı'ndaki "Görev şampiyonları" fikri buraya taşınır; ama ölçüt gerçek tahmin başarısıdır.
- **Model karşılaştırma araçları:**
  - Varlık sınıfı (ETF/Hisse) ve dönem seçici.
  - "Yalnızca ortak günler" anahtarı: modeller aynı günler üzerinden karşılaştırılır.

#### 5.3.4 Kalibrasyon (olasılıklı tahminler için)
Metaculus'un "track record" sayfasındaki yaklaşımın uyarlaması.
- **Güvenilirlik diyagramı:** X ekseni tahmin edilen "yükselme olasılığı" dilimleri (%50–60, 60–70 …), Y ekseni gerçekleşen yükselme oranı. Köşegen mükemmel kalibrasyondur. Nokta boyutu N'i gösterir.
- **Brier skoru** ve ölçüt Brier'ı (her gün %50 demek = 0,25).
- **Hata histogramı:** Hedef fiyattan sapmalar.
- Otomatik cümle örneği: "Model %70 dediğinde gerçekleşme %55 → aşırı güvenli."
- **Ön koşul:** Tahmin kaydı yalnızca yön değil olasılık da üretmeli. Bu bir şema ve tahmin motoru değişikliği; tasarım bunu varsayar.

#### 5.3.5 Boş durumlar
- **Tahmin yok, zamanlayıcı kurulu değil:** "Tahmin döngüsü kurulmadı. 09:30'da tahmin üretilir, 17:40'ta gerçekleşen fiyatla karşılaştırılır. [Zamanlayıcıyı kur] [Şimdi bir tahmin üret]".
- **N < 30:** Karnede yazı: "30 uzlaşmış tahminden önce isabet yüzdesi yanıltıcıdır; yaklaşık 3 işlem haftası gerekir."

### 5.4 KARARLAR: "Ne yapmalıyım ve neden?"

Sekmeler: **Pozisyon kararları · Tezler · Derin analiz · Raporlar**

Sayfanın üstünde tek bir sarı bant: "Eşikler taslak — kararlar onaylanmamış politikaya göre üretiliyor. [Politikayı gözden geçir]". Bu bant, her kartta tekrarlanan "Eşikler TASLAK" satırının yerine geçer.

Yasal not sayfanın en altında, küçük gri tek satır: "Karar desteğidir; sistem işlem yapmaz." Turuncu büyük bant kalkar.

#### 5.4.1 Pozisyon kararları (master-detail)
```
┌ Liste ───────────────────────┐┌ Ayrıntı: SPDR MSCI ACWI IMI ─────────────────────────────────────┐
│ ● SPYI   TUT   (değişmedi)   ││ KARAR  TUT        Önceki: TUT (30 Eki)       Veri: ◐ Cum kapanış │
│ ● EIMI   TUT                  ││ NEDEN                                                            │
│ ● IWMO   TUT                  ││  ✓ Ağırlık hedef bandında (kural: politika.agirlik_bandi)        │
│ ● IWVL   TUT                  ││  ✓ Trend ve risk göstergelerinde uyarı yok                       │
│                               ││ BU KARARI NE DEĞİŞTİRİR?                                         │
│ [Tümünü değerlendir]          ││  · Ağırlık %X'i aşarsa → AZALT    · Tez tetikleyicisi → GÖZDEN GEÇİR │
│                               ││ TEZ  "Küresel çekirdek…"  [Tezi aç]   (tez yoksa: [Tez yaz])      │
│                               ││ DERİN ANALİZ (TradingAgents)  Underweight · 30 Eki               │
│                               ││  Doğrulama: ✓ 9  ✗ 1  ○ 4 (kapsam dışı)   [Rapor] [Yeniden çalıştır] │
│                               ││  ⚠ ÇATIŞMA: masa TUT, model Underweight → inceleme gerekli       │
│                               ││ VERGİ ETKİSİ  Satışta ~3,29 € kâr → ~2,30 € matrah (%30 TF)       │
│                               ││ GEÇMİŞ  30 Eki TUT · 31 Eki TUT · 1 Kas TUT  (zaman çizgisi)       │
└───────────────────────────────┘└───────────────────────────────────────────────────────────────────┘
```
- Faktör fonu notu ("Faktör fonu 1 yılda çekirdeğe göre +27,0 puan") "Neden" bölümüne metrik olarak girer: `Çekirdeğe göre 1Y fark: +27,0 puan`.
- **[Derin analiz çalıştır]** önce bir **çağrı önizleme sayfası** gösterir:
  - "Model: ChatGPT (abonelik) + Gemini (ücretsiz katman)";
  - "Tahmini 8–12 çağrı";
  - "Gönderilecek veri: sembol ve kamuya açık fiyat; kişisel portföy bilgisi GÖNDERİLMEZ";
  - **[Başlat] [İptal]**.

#### 5.4.2 Tezler
- **Kart düzeni:** başlık, varlık, kategori/vade, hedef ağırlık (% olarak), sonraki kontrol tarihi.
- **Tetikleyiciler iki türe ayrılır:**
  - **Otomatik ölçülen** (örnek: "TER %1'i aşarsa", "fiyat 200 günlük ortalamanın %15 altına düşerse"): canlı durum çubuğuyla gösterilir.
  - **Elle kontrol edilen** (örnek: "küresel ticaret %40 daralırsa"): aylık kontrol listesinde onay kutusu olarak durur.
- **Aylık sağlık kontrolü:** 5 soruluk sihirbaz (önceki tez neydi, ne değişti, karşı kanıt, sonraki test). Cevaplar tarihli kayıt olur.
- **Durum filtresi:** Aktif · Gözden geçirilecek · Geçersiz kılınmış · Eski sürümler.
- **[Geçersiz kıl]:** Gerekçe zorunlu. U6'daki test tezi bu yolla kapatılır.
- **Yeni tez sayfası:** Alanlar 0.4'teki stdin JSON yoluyla gönderilir. Hedef ağırlık % olarak girilir. En az 2 tetikleyici zorunlu; en az 1'i otomatik ölçülebilir olmalı. Bu zorunluluk bir uyarıdır, engel değildir.

#### 5.4.3 Derin analiz
- TradingAgents koşularının listesi: varlık, tarih, model, görüş, doğrulama skoru, durum.
- **Rapor görünümü:** Bölümler katlanır (piyasa, haber, temel, bull/bear tartışması, karar). Rapordaki her sayının yanında doğrulama rozeti var:
  - ✓ Scalable ile doğrulandı;
  - ✗ çelişiyor (Scalable değeri ipucunda);
  - ○ kapsam dışı (haber, bilanço);
  - ⤳ Yahoo'ya düşüldü.
- **[Karşılaştır]:** Aynı varlığın iki koşusu yan yana açılır ve görüşün neden değiştiği gösterilir.

#### 5.4.4 Raporlar
- **Liste:** tür, tarih, kısa özet. Türler: Durum raporu · Araştırma raporu · Derin analiz · Yorum paketi.
- **Gösterim:** Rapor işlenmiş markdown olarak gösterilir: başlıklar, tablolar, monospace olmayan gövde.
- **Yorum paketi** bir rapor değil, LLM'e verilecek bir prompt. Bu yüzden ham metin olarak gösterilmez. Kart yalnızca üç bilgi taşır:
  - "Bu paket, kendi ChatGPT/Claude sohbetinize yapıştırmanız içindir";
  - **[Panoya kopyala]**;
  - **[İçeriği göster]** (katlanır).
- **Diğer düğmeler:** [Durum raporu oluştur] · [PDF olarak dışa aktar] · [Finder'da göster].

### 5.5 KEŞİF: "Yeni fırsat var mı?"

Sekmeler: **Tarama · İzleme listesi · Araştırma**

#### 5.5.1 Tarama
```
Son tarama: 1 Kas 16:04 · fiyat verisi Cum 30 Eki kapanışı · 17 varlık        [Havuzu düzenle] [⚡ Şimdi tara 🔌]
[ETF | Hisse | Tümü]   [☐ Portföydekileri gizle]
```
| # | Varlık | Etiket | Skor (z) | 1Y getiri | Volatilite | Maks. düşüş | Trend 3A | Portföye örtüşme |
|---|---|---|---|---|---|---|---|---|
| 1 | Apple `US0378331005` | Araştırmaya değer | +1,17σ | … | … | … | ▁▃▅▆ | — |
| 2 | iShares Edge MSCI World Value `IE00BP3QZB59` **[Portföyde]** | İzle | +1,10σ | … | … | … | … | %100 (zaten var) |

- **Skor gösterimi:** "/10" kaldırılır. Skor z-değeridir: 0 havuz ortalaması, +1σ havuzun belirgin üstü. Sütun başlığındaki "?" simgesi bunu açıklar.
- **Etiket kuralı ipucunda yazılır.** Örnek: "Araştırmaya değer = skor > X **ve** portföyle örtüşme < Y **ve** veri tam". Böylece U10'daki "neden 0.1 araştırmaya değer, 0.7 izle" sorusu cevaplanır.
- **İnceleme paneli:**
  - skor bileşenleri yatay çubuklarla: trend, risk-düzeltilmiş getiri, makas, düşüş;
  - 1Y grafik;
  - mevcut portföyle örtüşme;
  - **[İzlemeye al] [Araştır] [Karşılaştırmaya ekle] [Tahmin havuzuna ekle]**.
- **Karşılaştır:** En fazla 3 varlık seçilir. Yan yana tablo (Bloomberg RV mantığı) ve normalize edilmiş fiyat grafiği.
- **Ekranı açmak tarama başlatmaz** (U7). Yalnızca **[Şimdi tara]** broker'a gider.
- **Havuzu düzenle (sayfa):**
  - ISIN ekle: Scalable `quote` ile doğrulanır, ad otomatik gelir.
  - Çıkar.
  - ETF/Hisse sınıfı.
  - Tahmin döngüsüne dahil mi (5 ETF + 5 hisse sınırı).

#### 5.5.2 İzleme listesi
- Sabitlenmiş ve izlenen varlıklar listelenir: fiyat, günlük değişim, tazelik, son tahmin, son karar/etiket.
- Kenar çubuğundaki "Sabitlenmiş varlıklar" ile aynı veriyi kullanır.

#### 5.5.3 Araştırma (eski Kaynaklı Araştırma)
- **[Yeni araştırma] sayfası:**
  - varlık seçici;
  - vade: Uzun / Orta / Fırsat (CLI ile birebir aynı değerler; Y2 hatası);
  - model seçimi;
  - çağrı önizlemesi (5.4.1'deki gibi).
- **Kanıt paketleri listesi:** varlık, tarih, iddia sayısı, doğrulama oranı, karşı denetim sonucu.
- **Paket ayrıntısı, üç sekme:**
  - **İddialar:** iddia metni, kaynak alıntısı, doğrulama durumu.
  - **Metrikler:** TER, Sharpe … her biri kaynaklı.
  - **Kaynaklar:** URL, erişim tarihi, hash.
- **Karşı denetim (eski adıyla Red-Team) sonucu** üstte tek satır: "Geçti" / "3 sorun" + ayrıntı.

### 5.6 SİSTEM: kenar çubuğunda en altta, nadiren kullanılır

Sekmeler: **Sağlık · Otomasyon · Modeller · Ayarlar**

#### 5.6.1 Sağlık (eski Bütünlük ve Güvenlik)
```
Mühür zinciri   ✓ Doğrulandı · 1 Kas 16:03 · 64 mühür · 145 olay        [Şimdi doğrula]
Yedekler        ✓ Son yedek 14:17 · 81 dosya · 202 MB · saklama politikası: TANIMSIZ  [Yedek al] [Prova] [Politika…]
Güvenlik        ✓ Gizli anahtar taraması temiz · izinler 0700/0600 · 31 Eki         [Tara]
Disk şifreleme  ? FileVault durumu okunamadı                                    [Nasıl kontrol edilir?]
```
- Her satır tıklanınca katlanır ayrıntı açılır (zincir uçları, hash'ler, defter satırları).
- **Değerler gerçek ve tutarlı olmalı:** Üst çubuktaki "Mühür" parçasıyla aynı kaynaktan gelir (U5).
- **Denetim günlüğü:** Ayrı bir katlanır bölüm.
  - Filtre: aktör, eylem, tarih.
  - Hash'ler kısaltılmış, kopyalanabilir.
  - Satır seçilince payload JSON'u İnceleme panelinde açılır.
- **[Geri yükle…]** yalnızca "Gelişmiş" katlanır bölümünde durur. Onay sayfası sonucu açıklar ("Canlı veritabanı X tarihli yedekle değiştirilecek…") ve "GERİ YÜKLE" yazmayı ister.
- Eski tam genişlikli "Yedek Al" açılır menüsü kaldırılır.

#### 5.6.2 Otomasyon (eski Görev Zamanlayıcı)
- **Görev kartları:** Sabah 09:30, Akşam 17:40 ve Cuma 18:00 için. Her kartta:
  - durum: kurulu / değil;
  - **sonraki çalışma zamanı** (gerçek tarih);
  - son çalışma sonucu ve çıkış kodu;
  - **[Günlük]**;
  - **[Şimdi çalıştır]**.
- **Kurulum anahtarı:** Tek anahtar, "Otomatik tahmin döngüsü: Kapalı ⟷ Açık". Onay sayfası ne kurulacağını listeler. Anahtar, eski "Servisleri Kur" ve "Kaldır" düğmelerinin yerine geçer.
- **Bildirim ayarları:** "Bildirim testi" düğmesi ve hangi olayların bildirileceği (5.8).
- İş kuyruğu tablosu Etkinlik penceresine taşınır. Burada yalnızca "Son 7 gün: 15 iş, 1 hata [Ayrıntı]" özeti kalır.

#### 5.6.3 Modeller (eski Model Kaydı)
| Model | Sağlayıcı | Erişim | Veri sınıfı izni | Son erişim testi | Durum |
|---|---|---|---|---|---|
| gpt-6.1-sol | ChatGPT | Abonelik (OAuth) | Kişisel ✓ (kullanıcı onaylı) | 30 Eki ✓ | Kullanılabilir |
| gemini-3.8-flash | Google | Ücretsiz katman | Yalnızca kamu verisi | — | Doğrulanmadı **[Erişimi test et]** |

- **Rozetler:** "ZERO COST" ve "%100 GÜVENLİ" kalkar (U15). Yerine kapının gerçek kararı gösterilir: "Son 30 günde 0 ücretli çağrı (kayıtlardan)".
- **Model başarısı:** Karne burada değil, Tahminler › Karne'de. Burada yalnızca bağlantı var.
- **Yerel ve LLM kıyaslaması:** "Gelişmiş" altına alınır.

#### 5.6.4 Ayarlar
Sekmeler: **Hedef portföy · Politika ve eşikler · Vergi · Bağlantılar · Bildirimler · Hakkında**

- **Hedef portföy:**
  - ISIN başına hedef % (toplam %100 kontrolü canlı);
  - aylık birikim tutarı;
  - asgari işlem tutarı;
  - hedef nakit oranı.
- **Politika ve eşikler:**
  - Her eşik satırında: değer, açıklama ("Bu eşik hangi kararı etkiler?"), durum (**Taslak** sarı / **Onaylandı** yeşil, onay tarihiyle).
  - **[Değişiklikleri gözden geçir]** önce bir fark görünümü açar (eski → yeni), sonra **[Onayla ve kaydet]**. Yeni sürüm tarihli kayıt olur.
- **Vergi:** Freistellungsauftrag tutarı, yıllık Basiszins (girdi), kilise vergisi var/yok (oran hesabı için).
- **Bağlantılar:**
  - Scalable oturumu: durum, son giriş, **[Giriş yap]**, **[Oturumu kontrol et]**;
  - masa klasörü (seçici);
  - TradingAgents klasörü.
- **Hakkında:** Sürüm, DB yolu (U16 buraya), şema sürümü, lisanslar.
- **"Varsayılanlara sıfırla"** en alttaki kırmızı "Tehlikeli alan" bölümüne taşınır ve onay ister.

### 5.7 VARLIK SAYFASI (her yerden açılır; Bloomberg DES'in karşılığı)

```
SPDR MSCI All Country World Investable Market UCITS ETF (Acc)          [📌 Sabitle] [Araştır] [Derin analiz]
IE00B3YLTY66 · SPYI · Xetra · ETF · Biriktiren · Fiziksel · TER %0,17 (kaynak, 12 Eki)   11,63 € ◐ Cum 17:35
Pozisyon: 157,7 adet · 1.835,01 € · %42 · K/Z +3,29 €            Karar: TUT · Tez: var · Tahmin isabeti: %61 (N=18)
───────────────────────────────────────────────────────────────────────────────────────────────
 Özet | Grafik | Tahminler | Tez ve kararlar | İçerik ve örtüşme | Araştırma | İşlemler
```
*(TER ve tahmin isabeti temsilidir.)*

| Sekme | İçerik |
|---|---|
| **Özet** | Kimlik kartı: her alan kaynaklı ve tarihli; bilinmeyen alan "bilinmiyor". 1Y performans, volatilite, maks. düşüş. Son 3 olay. |
| **Grafik** | 1A / 3A / 1Y / Maks. Katmanlar (aç/kapa): maliyet çizgisi, alış/satış noktaları (işlemlerden), tahmin işaretleri (▲▼ ve ✓✗), tez açılış/değişiklik tarihleri. Not: Scalable "Maks." serisi kaba çözünürlükte; grafik bunu belirtir. |
| **Tahminler** | Yalnızca bu varlığın tahmin defteri ve karnesi. Model × isabet tablosu. |
| **Tez ve kararlar** | Zaman çizgisi: tez sürümleri, etiket değişimleri, TradingAgents görüşleri, kullanıcı notları. Her nokta "o gün bilinenler" ile açılabilir (görüş geçmişi). |
| **İçerik ve örtüşme** | (ETF) ilk 10 bileşen, ülke ve sektör, portföydeki diğer fonlarla örtüşme. (Hisse) hangi fonlarınızda ne ağırlıkta bulunduğu. |
| **Araştırma** | Bu varlığın kanıt paketleri ve derin analiz raporları. |
| **İşlemler** | Bu varlığın işlemleri ve FIFO lotları. |

---

## 6. Bileşen kütüphanesi (tutarlılık kuralları)

| Bileşen | Kural |
|---|---|
| **KPI kartı** | Bir ekranda en fazla 4. Başlık + büyük sayı + tek satır bağlam + tazelik noktası. Renkli köşe etiketi yok. |
| **Tazelik noktası** | ● canlı · ◐ son kapanış · ○ bayat · ? bilinmiyor. Her zaman ipucuyla: zaman + kaynak + run_id. |
| **Durum rozeti** | 4 renk: yeşil/sarı/kırmızı/gri. Her zaman simge + metin; yalnızca renk kullanılmaz (renk körlüğü). |
| **Karar etiketi** | TUT (nötr gri-mavi) · EKLE (yeşil) · AZALT (turuncu) · GÖZDEN GEÇİR (sarı) · VERİ YETERSİZ (gri, kesik kenarlı). |
| **Tablo** | Boş ilk sütun yok (U12). Sayılar sağa hizalı ve sabit genişlikli rakamla. Başlık sabit. Sıralanabilir sütunlar. Satır üzerinde sağ tık menüsü: ISIN kopyala / Varlığı aç / Araştır / İzlemeye al. Boş satır çizgileri gösterilmez. |
| **Boş durum** | Simge + "Neden boş" cümlesi + tek birincil düğme (+ isteğe bağlı "Daha fazla bilgi"). |
| **Hata bandı** | Kırmızı ince bant: "Veri çekilemedi (çıkış 1): oturum gerekli." + [Giriş yap] [Ayrıntı]. Hiçbir hata "0" değeri olarak gösterilmez. |
| **Uzun iş** | Başlatınca bildirim + Etkinlik rozeti. Bitince bildirim: "Veri yenilendi ✓ 12 sn" ya da "başarısız ✗ [Günlük]". |
| **Onay sayfası** | Yalnızca geri alınamaz ya da canlı veriyi değiştiren eylemlerde. Sonucu tek cümleyle açıklar. Varsayılan düğme "İptal". |
| **Çağrı önizlemesi** | Her model çağrısından önce: model, erişim türü, tahmini çağrı sayısı, gönderilecek veri sınıfı. |
| **Sayı biçimi** | `5.000,00 €` · `+0,8 %` (işaretli) · `−95,54 €` (gerçek eksi işareti) · tarih `1 Kas 2026 16:03`. Son 24 saat için göreli zaman ("2 sa önce"). |
| **Tipografi** | SF Pro. Rakamlar sabit genişlikli. Sayfa başlığı 22 pt, bölüm başlığı 13 pt yarı kalın büyük harf, gövde 13 pt. Monospace yalnızca ISIN, hash ve kod için. |

---

## 7. Düğme envanteri (son hali)

| Yer | Birincil | İkincil | Gelişmiş/tehlikeli |
|---|---|---|---|
| Araç çubuğu | ▶ Sabah Akışı | ⟳ Yenile · ⌘K · Etkinlik · İnceleme paneli | — |
| Bugün | (Dikkat öğelerindeki tekil düğmeler) | Tümü › | — |
| Portföy › Pozisyonlar | Verileri yenile 🔌 | Filtre · CSV | — |
| Portföy › İşlemler | Mutabakatı çalıştır | İşlemleri çek 🔌 · CSV | — |
| Portföy › Dağılım | Bu ay ne alayım? | İçerik çek 🔌 · Dosya seç | — |
| Tahminler › Bugün | Uzlaştır (17:35+) | Sabah tahminlerini üret (koşullu) | — |
| Tahminler › Defter | — | Filtreler · CSV · O günün verisiyle aç | — |
| Kararlar › Pozisyon | Tümünü değerlendir | Derin analiz ✦ · Tez yaz/aç | — |
| Kararlar › Tezler | Yeni tez | Aylık kontrol | Geçersiz kıl |
| Kararlar › Raporlar | Durum raporu oluştur | Prompt'u kopyala · PDF | — |
| Keşif › Tarama | Şimdi tara 🔌 | Havuzu düzenle · Karşılaştır | — |
| Keşif › Araştırma | Yeni araştırma ✦ | — | — |
| Sistem › Sağlık | Şimdi doğrula | Yedek al · Prova · Tara | Geri yükle… |
| Sistem › Otomasyon | Otomatik döngü anahtarı | Şimdi çalıştır · Günlük · Bildirim testi | — |
| Sistem › Modeller | Erişimi test et | — | — |
| Sistem › Ayarlar | Gözden geçir ve onayla | — | Varsayılanlara sıfırla |

Simgeler: 🔌 = Scalable'a gider · ✦ = model çağırır.

---

## 8. Etkileşim ayrıntıları

### 8.1 Klavye kısayolları
| Kısayol | İşlev |
|---|---|
| ⌘1 … ⌘6 | Bölümler |
| ⌘K | Komut paleti / varlık ara |
| ⌘R | Ekranı yenile (DB) |
| ⌘⇧R | Verileri yenile (broker) |
| ⌘⇧S | Sabah Akışı |
| ⌘I | İnceleme paneli |
| ⌘F | Ekranda ara |
| Space | Seçili satırın hızlı önizlemesi |
| ⌘C | Seçili ISIN'i kopyala |
| ⌘E | Görünümü CSV dışa aktar |

Hepsi menü çubuğunda da bulunur: Görünüm, Veri, Analiz, Pencere.

### 8.2 Menü çubuğu simgesi (isteğe bağlı)
- Küçük simge, rengi Durum Kapsülü'nün özetidir.
- Açılır menüde: portföy değeri, bugünkü tahmin durumu, "Sabah Akışı", "Uygulamayı aç".

### 8.3 Bildirimler (macOS; varsayılan sessiz, kullanıcı seçer)
- **Oturum:** 24 saat içinde bitecek.
- **Sabah 09:35:** "10 tahmin üretildi".
- **Akşam 17:45:** "Bugün 7/10 isabet ('Değişmez': 5/10)".
- **Tez tetikleyicisi** aşıldı.
- **Hata:** Başarısız zamanlanmış iş.
- **Kural:** Bildirim gövdesinde portföy değeri gösterilmez (kilit ekranı gizliliği).

### 8.4 Pencere ve durum hafızası
- Seçili bölüm, sekme, filtreler ve İnceleme paneli açık/kapalı durumu hatırlanır.
- Seçili varlık bölümler arasında taşınır. Örnek: Portföy'de SPYI seçiliyken Tahminler'e geçilince SPYI filtresi önerilir.

### 8.5 Erişilebilirlik
- Tüm simgeli düğmelerin VoiceOver etiketi var.
- Renk tek başına bilgi taşımaz.
- Kontrast AA.
- Tüm eylemler klavyeyle yapılabilir.

### 8.6 Sözlük (arayüz dili)

| Eski | Yeni |
|---|---|
| Settled / Unsettled / Accrued | Takası tamamlanan / Takastaki / Tahakkuk eden |
| Drift | Hedeften sapma |
| Red-Team Critic | Karşı denetim |
| Champion | En iyi model (N≥…) |
| MATCH_SEALED | Mühür doğrulandı |
| Falsification triggers | Çürütme koşulları |
| Asset Allocation / Domicile | Varlık dağılımı / Yerleşim ülkesi |
| İP-1 … İP-12 | (kaldırıldı) |

---

## 9. Görsel düzen ve yoğunluk
- **Boyutlar:** Ekran genişliği 1.280 pt ve üstü. Kenar çubuğu 220 pt; İnceleme paneli açıkken içerik en az 640 pt.
- **Boşluk:** 8 pt ızgara. Kartlar arası 12 pt, bölümler arası 24 pt.
- **Yoğunluk anahtarı:** Ayarlar'da "Rahat / Sıkı". Sıkı modda satır yüksekliği 22 pt; çok satırlı tablolar (Defter, İşlemler) için.
- **Görünüm:** Karanlık ve aydınlık tema; sistemi izler. Bugünkü karanlık tema korunur, ama kart arka planları tek ton yapılır.
- **Grafikler:** Swift Charts. En fazla 3 seri + ölçüt çizgileri. Eksenlerde birim. Üzerine gelince değer ve tarih.

---

## 10. Uygulama sırası ve kabul kriterleri

| Aşama | İçerik | Kabul kriteri |
|---|---|---|
| **A: Veri doğruluğu** | U1–U8, U10, U15 + ana promptun Faz 0'ı | Bugün ve Portföy 4 pozisyon / 5.000,00 € gösteriyor. İşlemler 626 gözlemi tekilleştirerek gösteriyor. Mutabakat çalışmadıysa gri. Sağlık ekranı üst çubukla aynı. Tarama ekranı açılınca audit sayısı değişmiyor. |
| **B: Kabuk** | 6 bölümlü kenar çubuğu, Durum Kapsülü, Etkinlik, İnceleme paneli, ⌘K, durum çubuğu, U9/U11/U12/U16 | Eski 14 ekranın her işlevine yeni yapıdan erişilebiliyor (3.2 tablosundaki her satır için UI testi). Yinelenen durum etiketi yok. Kaynakta "İP-" metni yok. |
| **C: Bugün + Portföy** | 5.1, 5.2 (Pozisyonlar, İşlemler) | Sabah Akışı 6 adımı gerçek çıkış kodlarıyla gösteriyor. "Ne değişti" mühürlü veriden üretiliyor. |
| **D: Tahminler** | 5.3 (Bugün, Defter, Karne); kalibrasyon için olasılık alanı | Defter değiştirilemez. "O günün verisiyle aç" çalışıyor. Karne ölçütlerle karşılaştırıyor. N<30 bandı görünüyor. |
| **E: Kararlar** | 5.4, U6 temizliği, tek taslak bandı, çağrı önizlemesi | Her karar "neden" ve "ne değiştirir" gösteriyor. Çatışma görünür. Yorum paketi "Kopyala" ile çalışıyor. |
| **F: Varlık sayfası + Keşif** | 5.5, 5.7, U13/U14 | Her listeden Varlık sayfası açılıyor. Grafikte işlem ve tahmin katmanları var. Skor σ ölçeğinde ve etiket kuralı açıklanıyor. |
| **G: Dağılım, Vergi, Kalibrasyon** | 5.2.3, 5.2.4, 5.3.4 (ana promptun Faz 2, 4 ve 5'ine bağlı) | Örtüşme gerçek içerik dosyasından hesaplanıyor. Vergi ekranında her tahmin "tahmindir" notu taşıyor. |
| **H: Sistem** | 5.6, bildirimler, menü çubuğu | Tehlikeli eylemler yalnızca Gelişmiş altında ve onaylı. Modeller ekranında doğrulanmamış güvence yok. |

**Her aşamada:**
- SwiftUI önizlemeleri için sahte veri setleri (fixture). En az şu durumlar kapsanır:
  - boş;
  - hafta sonu;
  - oturum kapalı;
  - kısmi veri;
  - hata;
  - N<30;
  - dolu.
- Her ekranın bu 7 durumda ekran görüntüsü (snapshot) testi.
- Teslimde ekran görüntüleri ve test çıktısı birlikte verilir.

---

## Kaynaklar
- [Apple HIG: Split views](https://developer-mdn.apple.com/design/human-interface-guidelines/components/layout-and-organization/split-views): kenar çubuğu, içerik ve inceleme paneli düzeni
- [WWDC25 oturumu 310](https://developer.apple.com/videos/play/wwdc2025/310?time=336): macOS uygulama yapısı ve araç çubuğu
- [Metaculus: Track record improvements](https://www.metaculus.com/news/2018/02/20/track-record-improvements/): tahmin karnesi ve kalibrasyon grafiği yaklaşımı
- [Metaculus topluluk tahminleri üzerine analiz (EA Forum)](https://forum.effectivealtruism.org/posts/zeL52MFB2Pkq9Kdme/exploring-metaculus-community-predictions): Brier skoruyla değerlendirme
- [Portfolio Performance (App Store)](https://apps.apple.com/us/app/portfolio-performance/id6451118191): kişisel portföy uygulamalarında pano ve performans görünümü örneği
- Bloomberg DES / PORT / RV kavramları: önceki "Bloomberg uyarlama" raporundan
