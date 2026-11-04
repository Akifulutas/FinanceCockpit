# ETFCockpit (macOS) — Bağımsız Test Bulguları, Düzeltmeler ve İyileştirmeler

> Bu promptu, `~/Documents/ETF` klasörüne erişimi olan kodlama asistanına verin.
> 01.11.2026'da bağımsız kod incelemesi yapıldı:
> - `macos/Sources` (16.000 satır Swift) okundu.
> - Uygulamanın 24 SQL sorgusu canlı `masa.db`'nin kopyasına karşı denendi: **24/24 geçerli**.
> - Uygulamanın tetiklediği her CLI komutu, `masa` argparse tanımlarıyla karşılaştırıldı.
> - Swift derleme ve testleri bu incelemede çalıştırılamadı (Linux ortamı). Bunlar aşağıdaki kabul adımlarında Mac'te çalıştırılacak.

---

## 0. KURALLAR (önceki şartnamedeki kurallar aynen geçerli: `masa/prompts/KALAN_ISLER_ANA_PROMPT.md` §0.2)

1. **Uygulama gösterdiği hiçbir değeri uydurmaz.**
   - Her sayı, durum ve rozet ya `masa.db`'den (salt-okunur), ya `masa/config/*.json`'dan, ya da bir `masa` CLI komutunun çıktısından gelir.
   - Veri yoksa ekranda "Veri yok", "Hesaplanmadı" veya "Bilinmiyor" yazar.
   - Varsayılan "başarılı", "kurulu", "geçti" durumları yasaktır.
2. **"Kaydedildi" yalnız gerçekten kaydedildiyse yazılır.** Her kaydetme işlemi bir CLI komutuyla yapılır ve sonucu doğrulanır.
3. **Kaynak kodda kişisel veri yok.** Hesap/portföy kimliği, ad, e-posta, gerçek veya "örnek" API anahtarı kaynak koda, testlere ya da fixture'lara yazılmaz.
4. **Broker'a yazma yolu yok.** Uygulama yalnız `masa` CLI'sini çağırır, `sc`'yi asla doğrudan çağırmaz.
5. **İzinli komut listesi:** uygulamanın çalıştırabileceği `masa` alt komutları Swift'te tek bir listede tutulur. Serbest metin girdileri (ISIN vb.) doğrulanmadan argüman yapılmaz.
6. **Testler gerçek dosyalara dokunmaz.**
   - Swift testleri canlı `masa.db`'yi, `var/`'ı ve `config/`'i değiştiremez; geçici bir kopya ya da fixture kullanır.
   - Python tarafındaki test koruması (conftest) korunur.
7. **Teslim:**
   - Her düzeltmeden sonra `swift build`, `swift test`, `cd masa && uv run pytest -q` ve `./etf-masa dogrula` çıktısı gösterilir.
   - Arayüz değişikliklerinde ekran görüntüsü eklenir.

---

## 1. HATALAR (önce bunlar düzeltilecek)

### H1 · KRİTİK — Yapılandırma editörü sahte veri gösteriyor ve hiçbir şeyi kaydetmiyor
**Dosya:** `Features/Configuration/SystemConfigurationViewModel.swift`

**Bulgular**
- `resetToDefaults()` içinde sabit kodlanmış değerler var:
  - Hedef ağırlıklar %45/20/20/15. Kullanıcı hiç hedef onaylamadı; `config/portfoy.json`'da `hedef_agirliklar` boş.
  - `ucitsEnforcement = true`, oysa UCITS kontrolü kapatıldı.
  - **Gerçek Scalable hesap kimliği** `brokerAccountId` olarak kaynak kodda duruyor (satır 54 ve 119).
  - İki **sahte API anahtarı** "macOS Keychain'de kayıtlı, isConfigured: true, 30.10.2026" diye gösteriliyor. Kullanıcının OpenAI API anahtarı yok; ChatGPT aboneliği ile girişi var.
- `savePortfolioTargets()`, `saveInvestmentPolicies()` ve `updateCredential()` hiçbir dosyaya, CLI'ye veya Keychain'e yazmıyor, yine de "başarıyla kaydedildi / Keychain'de güncellendi" mesajı veriyor.

**Düzeltme**
1. Bütün sabit değerleri kaldır. Ekran `config/portfoy.json`, `config/politika.json` ve `config/modeller.json`'dan okunur.
   - Python tarafına `masa ayar goster --json` ekle; uygulama bunu çağırsın.
   - Hedef boşsa "Hedef tanımlı değil" göster.
2. Kaydetme için Python tarafına `masa ayar yaz --dosya portfoy|politika --json -` komutu ekle. Komut:
   - (a) JSON şemasıyla doğrular (ağırlık toplamı ≤ 1, ISIN Luhn, eşik aralıkları),
   - (b) eski dosyayı `config/arsiv/<ad>-<zaman>.json` olarak saklar,
   - (c) atomik yazar,
   - (d) audit olayı düşer.
   Uygulama komutun çıkış koduna göre mesaj verir.
   `politika.json` → `durum: ONAYLANDI` değişikliği ayrı bir onay diyaloğuyla yapılır ("Bu eşikleri yatırım politikam olarak onaylıyorum").
3. **API anahtarı bölümünü tamamen kaldır.** Model anahtarları TradingAgents'ın kendi `.env`'inde kalır; uygulama ve masa onları okumaz, göstermez, yazmaz. Yerine salt-okunur bir "Model erişimi" kartı koy:
   - `masa kontrol --json` çıktısındaki `describe_providers()` bilgisi,
   - ChatGPT giriş durumu (`~/.tradingagents/chatgpt-auth.json` dosyası var mı; içeriği okunmaz),
   - Google için yalnız "sağlayıcı: google / gemini-3.8-flash".
4. Hesap kimliği gerekirse veritabanındaki maskelenmiş değerden (`cash_observations.account_id_masked`) okunur.

**Kabul testleri**
- `grep -rn "rSwZbPLMCFk7WNgdja7zaJ\|AIzaSy\|sk-proj" macos/` → 0 sonuç.
- Hedef boşken ekranda "Hedef tanımlı değil" görünür.
- Kaydet → `config/portfoy.json` gerçekten değişir, arşiv kopyası oluşur, geçersiz JSON reddedilir.
- Swift testleri geçici bir config klasörü kullanır.

### H2 · KRİTİK — Sepet / sapma paneli uydurma hedeflere göre sapma gösteriyor
**Dosya:** `Features/Basket/TargetBasketOverlapViewModel.swift`, satır 40–44 ve 115.

**Bulgu:** `defaultTargetWeights` %60/10/15/15 sabit kodlanmış ve sapma (drift) çubukları buna göre çiziliyor. Üstelik yapılandırma editöründeki %45/20/20/15'ten de farklı. Kullanıcının onaylı hedefi yok.

**Düzeltme**
- Hedefler yalnız `config/portfoy.json` → `hedef_agirliklar`'dan okunur. Boşsa sapma bölümü "Hedef tanımlı değil — Yapılandırma'dan ekleyin" der ve çubuk çizmez.
- "Dengeleme planı" düğmesi yalnız hedef varsa aktif olur (`masa plan`).
- Örtüşme matrisi ve Top 25 yalnız `holdings_sets` doluysa gösterilir. Şu an 0 kayıt var; boş-durum ekranında "ihraççı sepet dosyalarını `masa/var/private/holdings/inbox/` klasörüne bırakın → `masa sepet yukle`" talimatı gösterilir.

### H3 · KRİTİK — Tez ekleme komutu masa CLI'siyle uyumsuz, her zaman başarısız olur
**Dosya:** `Features/Thesis/ThesisManagementViewModel.swift`, ~satır 244.

**Uyumsuzluk:**
- Uygulama şu komutu üretiyor: `tez ekle <ISIN> --baslik --ozet --kategori --vade --curutme ...`
- `masa` CLI'nin beklediği: `tez ekle --isin <ISIN> --baslik --ozet --gerekce <..> --tetikleyiciler <t1> <t2> ...`
  - `--isin` ve `--gerekce` zorunlu.
  - `--curutme` diye bir bayrak yok.
- Sonuç: argparse hata verir, tez hiç kaydedilmez. Testler mock kullandığı için bu yakalanmadı.
- Ayrıca form, "hedef ağırlık %60" ve bir benchmark değerini önceden doldurulmuş getiriyor (uydurma değer).

**Düzeltme**
- Argümanları CLI sözleşmesine göre üret (`--gerekce`, `--tetikleyiciler`, `--kanitlar`, `--karsi-gorus`, `--hedef-agirlik`, `--sonraki-kontrol`).
- Form alanları boş başlasın.
- **Sözleşme testi (aşağıdaki İ1):** uygulamanın ürettiği her argv, Python tarafında `masa` argparse ile parse edilerek doğrulanır.

### H4 · YÜKSEK — Araştırma panelinde hakem (critic) kontrolleri sabit "GEÇTİ" olarak gösteriliyor
**Dosya:** `Features/Research/ResearchEvidenceViewModel.swift`, satır 95–125.

**Bulgu:** `setupDefaultCriticFindings()` dört kontrolü (ağırlık toplamı, makas matematiği, PSD matrisi, dayanaksız ifade) hiçbir şey çalışmadan `isPassed: true` olarak gösteriyor.

**Düzeltme:**
- Kontroller yalnız gerçek bir `arastir` / rapor doğrulama çıktısından veya `evidence_bundles`/`claims` tablolarından doldurulur.
- Hiç çalıştırılmadıysa "Henüz doğrulama yapılmadı" yazar.
- Rapor durumu (`draft` / `code_checked` / `independent_reviewed` / `needs_review`) DB'den okunur.

### H5 · YÜKSEK — Zamanlayıcı paneli launchd durumunu uyduruyor
**Dosya:** `Features/Scheduler/SchedulerAutomationViewModel.swift`, satır 35–62 ve 160–175.

**Bulgu:**
- Üç görev varsayılan olarak "kurulu, aktif, son çıkış kodu 0" gösteriliyor; gerçek durum hiç sorgulanmıyor.
- "Kur" komutu başarılı olunca durum yine elle "aktif / 0" yapılıyor.
- `runSchedulerAction(agent:action:)` içindeki `agent` parametresi kullanılmıyor.

**Düzeltme:**
- Python tarafına `masa zamanla durum --json` ekle (veya var olanı JSON verecek şekilde genişlet). Komut, her görev için `launchctl print gui/<uid>/<label>` ile şunları döndürür:
  - kurulu mu, yüklü mü,
  - son çıkış kodu,
  - son ve sonraki çalışma zamanı,
  - `var/logs` altındaki son satırlar.
- Panel yalnız bu çıktıyı gösterir.
- Bilinmeyen durum "Bilinmiyor" diye gösterilir.

### H6 · YÜKSEK — CLI çalıştırıcı: kilitlenme ve zaman aşımı riski
**Dosya:** `Core/CLI/CLIProcessRunner.swift`

**Bulgular:**
- **Kilitlenme:** `waitUntilExit()` çağrılmadan önce pipe'lar okunmuyor. Çıktı pipe tamponunu (~64 KB) aşarsa alt süreç yazarken bloke olur ve zaman aşımına kadar kilitlenir. Örnek riskli komutlar: `islemler cek` (614+ işlem), `arastir`, `guvenlik-tara`.
- **Zaman aşımı:** Varsayılan 60 sn. Artık `tahmin uret` 10 kotasyon + 20 grafik + holdings topluyor ve bu süreyi aşabilir. Zaman aşımında `terminate()` ile yarıda kesiliyor.
- **Sabit yollar:** `~/Documents/ETF/...` kodun içinde.

**Düzeltme:**
1. stdout/stderr `readabilityHandler` ile **eşzamanlı ve akış halinde** okunsun. Satırlar arayüze canlı aksın (ilerleme göstergesi).
2. Komut başına zaman aşımı tablosu olsun: `veri`/`tahmin` 300 sn, `gecmis` 600 sn, `tradingagents` 3600 sn. Ayrıca "İptal" düğmesi eklensin.
   - İptalde önce SIGINT gönderilsin, 10 sn sonra SIGTERM.
   - masa'nın `BEGIN IMMEDIATE` işlemleri yarıda kesilince geri alınır; bunu bir testle göster.
3. Yollar ayarlardan gelsin. Varsayılan: uygulama paketinin yanındaki `etf-masa` veya `~/Documents/ETF/etf-masa`. İlk açılışta bulunamazsa klasör seçtirsin.
4. Uzun işler `jobs` tablosuna da yazılsın. Uygulama kapatılıp açılsa bile durum oradan okunsun.

### H7 · ORTA — Model sicili simülasyonu gerçek değerlendirme gibi gösteriyor
**Bulgu:** `model_evaluations` kayıtlarının hepsi `mod_local_deterministic` için ve hiçbir model çağrılmıyor. `gemini-1.5-pro` doğrulanmadan "eligible / Google AI Pro / EU_COMPLIANT" olarak kayıtlı.

**Düzeltme:**
- Panel, `last_verified_at` boş olan modelleri "Doğrulanmadı" olarak göstersin.
- Simülasyon değerlendirmeleri "Simülasyon (gerçek model çağrısı yok)" rozeti taşısın.
- Python tarafında `gemini-1.5-pro` kaydı için yeni bir sürümle `status=revoked` / `discovered` düzeltmesi yapılsın (append-only: mevcut kayıt silinmez).

---

## 2. EKSİK: KULLANICININ ASIL AKIŞI UYGULAMADA YOK

Kullanıcının temel isteği, sırasıyla:

1. Oturum kontrolü ve giriş yönlendirmesi,
2. Başlangıç verisinin çekilmesi,
3. Elindekiler hakkında yorum,
4. Tut/sat değerlendirmesi,
5. Hisse/ETF havuzunda fırsat taraması.

Uygulamada **`baslat`, `gecmis`, `degerlendir`, `tarama`, `tradingagents`, `rapor`, `yorum` için hiçbir ekran yok.** 10 panelin hepsi altyapıyı gösteriyor.

### E1 · "Bugün" ana ekranı (kenar çubuğunda ilk sırada)

1. **Oturum durumu**
   - `masa giris --json`: açık / kapalı / süresi dolmak üzere.
   - Kapalıysa büyük bir "Giriş yap" kartı: "Terminal'de `sc login --local-read-only` çalıştırın" + "Tekrar kontrol et" düğmesi.
   - Uygulama girişi kendisi yapmaz, yalnız yönlendirir.
2. **"Verileri yenile"** = `masa veri` + `masa gecmis`, akış halindeki çıktıyla. Son mühür zamanı ve kotasyon yaşı görünür.
3. **Portföy özeti:** toplam, günlük değişim, FIFO'ya göre kâr/zarar, Xetra açık/kapalı.
4. **Uyarılar:** bütünlük sorunu, `waiting_auth`, bekleyen uzlaşma, 45 günden eski sepet belgesi.

### E2 · "Değerlendirme" ekranı (tut / ekle / azalt / gözden geçir)

1. Pozisyon başına:
   - etiket ve gerekçe maddeleri,
   - politika durumu: TASLAK / ONAYLANDI,
   - vergi notu (Teilfreistellung, Pauschbetrag),
   - varsa TradingAgents görüşü ve hangi modelden geldiği (route).
   Veri `masa degerlendir --json` komutundan gelir; Python tarafına JSON çıktısı eklenmeli.
2. "TradingAgents ile derin analiz" düğmesi:
   - Önce sağlayıcı ve maliyet özetini gösterip onay ister.
   - İlerleme akışı gösterir.
   - Sonuç "harici görüş" etiketiyle gösterilir.
3. Ekranın en üstünde kalıcı bir not: "Karar desteğidir; sistem işlem yapmaz."

### E3 · "Fırsat taraması" ekranı

- `masa tarama --json`:
  - sıralı tablo: puan, 6A/1Y, Sharpe, maksimum düşüş, makas, portföyle korelasyon, etiket,
  - satır detayında gerekçeler.
- **Havuz düzenleme:** ISIN ekle/çıkar.
  - `masa ayar yaz --dosya havuz` ile yazılır.
  - ISIN Luhn kontrolü yapılır ve `sc quote` ile adı doğrulanır.
- Seçilen adaylar için "TradingAgents" düğmesi.

### E4 · "Rapor ve yorum" ekranı

- Son `masa rapor` Markdown'ını yerel olarak işle: güvenli Markdown, dış kaynak yok.
- "Yorum paketi oluştur" (`masa yorum`) ve "Panoya kopyala / Finder'da göster" düğmeleri.
- Rapor geçmişi listesi.

---

## 3. İYİLEŞTİRMELER

**İ1 · Tek veri sözleşmesi ve sözleşme testleri (en önemli iyileştirme)**
- Python tarafında her ekran için bir `--json` çıktısı olsun: `masa durum`, `portfoy`, `degerlendir`, `tarama`, `tahmin karne`, `zamanla durum`, `ayar goster`.
- JSON'larda `schema_version` alanı bulunsun ve JSON Schema dosyaları `masa/contracts/` altında tutulsun.
- **Python testleri:** gerçek fonksiyonlardan `contracts/fixtures/*.json` üretip şemaya karşı doğrular.
- **Swift testleri:** aynı fixture'ları decode eder.
- **Argv sözleşmesi:** uygulamanın çalıştırabileceği komutlar `contracts/cockpit_commands.json` dosyasında listelenir. Python testi her argv örneğini `masa` argparse ile parse eder. H3 türü hatalar böylece CI'da yakalanır.

**İ2 · Gerçek uçtan uca test**
- Swift tarafında bir entegrasyon testi:
  - geçici bir klasöre canlı DB'nin **kopyası** ve sahte bir `sc` (Python fixture'larıyla) koyar,
  - gerçek `etf-masa` komutlarını çalıştırır,
  - view model'lerin gerçek veriyi okuduğunu doğrular.
- Mock'lu birim testleri bunun yerine geçmez.

**İ3 · Paketleme**
- `swift run` yerine imzalı (ad-hoc) bir `.app` paketi: `scripts/build_app.sh`.
- Menü çubuğunda küçük bir öğe:
  - toplam değer,
  - oturum durumu,
  - son mühür yaşı,
  - "Verileri yenile".
- Bildirimler `UNUserNotificationCenter` ile.

**İ4 · Tazelik ve dürüstlük**
- Her kartta: veri kaynağı, mühür zamanı, kotasyon yaşı.
- Simülasyon veya taslak değerler görsel olarak ayrışsın (ör. gri "TASLAK" ve "SİMÜLASYON" rozetleri).

**İ5 · Biçim**
- Para ve yüzde biçimi `tr_TR` veya `de_DE` (1.234,56 €).
- Tarihler Europe/Berlin saatinde.
- Koyu ve açık tema ile erişilebilirlik etiketleri.

**İ6 · Tahmin ekranı**
- Araç başına N (uzlaşma sayısı).
- "Genel isabet" ile "araç isabeti" ayrımı.
- Baz modellerle (değişmez / dünkü yön) kıyas en üstte gösterilsin.
- N < 30 iken "örneklem küçük" bandı.
- Uzlaşamayan tahminler gerekçesiyle listelensin (17:30 öncesi fiyat, tatil, oturum vb.).

**İ7 · Güvenlik**
- Uygulama yalnız `masa` sarmalayıcısını çalıştırır.
- ISIN alanları regex + Luhn ile doğrulanır.
- Uygulama günlüğünde (`CockpitLogger`) argüman ve çıktılar `SecretMasker`'dan geçer.
- Ekran görüntüsü / paylaşım için bir "gizlilik modu" olsun: tutarları ve adı gizler.

---

## 4. ÖNCELİK SIRASI VE KABUL

**Önerilen sıra:**
1. H1–H3 (sahte değerler ve kırık komut)
2. H6 (çalıştırıcı)
3. H4, H5, H7
4. İ1 (sözleşme testleri)
5. E1–E4 (asıl akış)
6. İ2–İ7

**Bitiş için kabul listesi**
1. `grep` ile kaynakta kişisel veri ve sahte anahtar yok.
2. Hiçbir panel varsayılan "başarılı / kurulu / geçti" göstermiyor. Boş-durum ekranları gerçek.
3. Uygulamadan "tez ekle" ile gerçek bir tez kaydedilebiliyor; `masa tez listele` onu gösteriyor.
4. Uygulamanın ürettiği tüm argv'ler Python sözleşme testinde parse ediliyor.
5. Büyük çıktılı komutlarda (`islemler cek`, `gecmis`) kilitlenme yok. İptal çalışıyor ve DB `dogrula` ile sağlam çıkıyor.
6. Bugün, Değerlendirme, Tarama ve Rapor ekranları gerçek veriyle çalışıyor.
7. `swift test`, `uv run pytest -q` ve `./etf-masa dogrula` hepsi yeşil. Her ekranın ekran görüntüsü teslim ediliyor.
