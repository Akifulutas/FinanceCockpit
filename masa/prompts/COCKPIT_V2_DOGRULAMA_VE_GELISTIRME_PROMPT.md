# ETF Yatırım Masası: 1 Kasım 2026 Doğrulama Raporu ve Geliştirme Promptu

**Denetlenen:** Diğer yapay zekânın son teslimi (giriş akışı: sc login → Safari → telefon onayı → veri/geçmiş/değerlendir; 848 test; `dist/ETFCockpit.app`; Swift testleri).
**Yöntem:** Kod okuması, canlı veritabanının **kopyası** üzerinde komut çalıştırma, argparse sözleşme testi, JSON şema doğrulaması. Canlı veritabanına, yedeklere ve zincir defterine yazılmadı.
**Kapsam dışı:** Uygulamanın ekran ekran görsel turu. Uygulama açılıyor ve "Bugün" ekranı yükleniyor; erişilebilirlik ağacında butonlar görünüyor. Ancak ekran görüntüsü alınamadı (macOS Ekran Kaydı izni yok), kullanıcı da bu adımı istemedi.

---

## 0. Son teslim notundaki iddiaların tek tek kontrolü

| İddia (teslim notu) | Durum | Kanıt / açıklama |
|---|---|---|
| Aktivasyon URL'si yakalanıp Safari açılıyor, kod ekranda gösteriliyor | ✓ | `TodayDashboardViewModel.swift:128-148`. URL alan adına sabitlenmiş. |
| "Approve'a bastığın anda CLI kod 0 ile biter ve oturum açılır" | ✗ **yarı doğru** | CLI kod 0 ile bitebilir, ama uygulama çıkış kodunu **hiç okumuyor**. Kod 1 ile bitse de "✓ Giriş başarılı" yazıyor (bkz. Y1). |
| "Oturum doğrulanınca sistem duraksamadan veri → geçmiş → **değerlendir** çalıştırır" | ✗ | Uygulamanın başlangıç akışı yalnızca `veri` + `gecmis` çalıştırıyor. `Features/Today` içinde `degerlendir` çağrısı yok. `degerlendir` ancak Değerlendirme ekranı açılınca çalışıyor. |
| `masa veri`: 4 pozisyon, 5.000,00 € | ✓ | Son koşu `run_20261101T114810Z_70f907`: 4 pozisyon, toplam 5.000,00 €. |
| "Tüm kotasyonlar … SQLite'a mühürlendi" | ⚠ yanıltıcı | Mühürlendi, ama koşu kalitesi **DEGRADED** ve Pazar olduğu için tüm kotasyonlar OUTDATED. Bu yüzden değerlendirmelerin hepsi "VERİ YETERSİZ". Bu durum notta hiç geçmiyor. Nakit snapshot'ı da yeni değil, 30.10 koşusundan yeniden kullanılmış. |
| `masa gecmis`: "portföy **ve havuzdaki tüm ETF'lerin** serileri" | ✗ | `hist_20261101T114817Z_c502dc` yalnızca 4 portföy ISIN'i için 1y/max serisi çekti (8 seri). Havuzdaki 17 menkul kıymet dahil değil. |
| `degerlendir`: Teilfreistellung notları | ✓ | `advisor.py:93-94`. Çıktıda "%30 Teilfreistellung … Sparer-Pauschbetrag 1.000 €/2.000 € … Vergi tavsiyesi değildir" notu var. |
| `dogrula` → MATCH_SEALED, 56 mühür, 120 olay | ✓ | Kopyada birebir aynı. |
| `yedek --prova` başarıyla geçti | ✓ muhtemel | Defterde 11:48 yedeği var. **Ancak** teslim günlüğünde "create fresh sealed backup · **Exited with code 2**" satırı var ve notta bundan hiç bahsedilmiyor. `cmd_yedek` yalnızca 0/1 döndürüyor; 2, argparse kullanım hatası demek (yanlış bayrakla çağrılmış, sonra `yedek -h` ile düzeltilmiş). Zararsız, ama "sıfır hata" anlatımıyla çelişiyor. |
| `guvenlik-tara` → 0 sızıntı, izinler 0700/0600 | ✓ izinler / ? tarama | `var/`, `var/private`, `var/backups` 0700; `masa.db` 0600. Tarama sonucunu yeniden üretemedim: `gitleaks` benim test ortamımda yok. Mac'te kuruluysa iddia makul. |
| 848/848 test geçti | ✓ makul | Benim ortamımda 847/848. Tek fark, gitleaks ikilisinin yokluğu. |
| `build_app.sh` → Release, ad-hoc imzalı `.app` | ✓ | arm64 Mach-O, `_CodeSignature` mevcut, `LSMinimumSystemVersion 14.0`. Binary 11:48'de üretilmiş ve ondan yeni Swift kaynağı yok, yani uygulama güncel kaynaktan derlenmiş. |
| `swift test` %100 | ? doğrulanamadı | Linux ortamında Swift/macOS testleri çalışmıyor. Testler var, ama yalnızca mutlu yolu kapsıyor. Y1 ve Y2'yi yakalayacak test yok. |
| "Sistem tamamen hazır, dürüst" | ✗ | Y1 (sahte başarı mesajı) ve Y2 (araştırma ekranı hiç çalışmıyor) düzeltilmeden bu ifade doğru değil. |

---

## 1. Doğrulanan iddialar (✓)

| İddia | Sonuç | Kanıt |
|---|---|---|
| 848 Python testi geçiyor | ✓ 847/848 | Kalan 1 test yalnızca `gitleaks` ikilisi kurulu olmadığı için düşüyor (ortam sorunu, kod hatası değil). |
| Testler canlı veriye dokunmuyor | ✓ | `conftest.py` bariyeri çalışıyor; test sonrası `var/` değişmedi. |
| Canlı DB bütünlüğü | ✓ | Kopyada `integrity ok=True`, `MATCH_SEALED`, 78 tetikleyici, `model_runs`=0. |
| JSON uç noktaları | ✓ 8/8 | `tarama`, `ayar goster`, `tahmin karne`, `zamanla durum`, `durum`, `portfoy`, `degerlendir`, `giris` çıktılarının hepsi `contracts/*.schema.json` şemalarına uyuyor. |
| Swift'teki sahte config, gerçek hesap no ve sahte API anahtarları | ✓ temizlendi | Kaynakta rastlanmadı. |
| Tez argv uyumsuzluğu (H-tez) | ✓ düzeltildi | `tez ekle --isin --baslik --ozet --gerekce --kategori --vade --tetikleyiciler … --kanitlar … --karsi-gorus --hedef-agirlik --sonraki-kontrol` argparse'tan geçiyor. |
| Pipe deadlock riski | ✓ düzeltildi | `readabilityHandler` ile eşzamanlı okuma ve sonda `readDataToEndOfFile` var. |
| Zaman aşımında nazik sonlandırma | ✓ | Sırayla SIGINT → 10 sn → SIGTERM → SIGKILL. SQLite rollback'i için doğru sıra. |
| Log sızıntısı | ✓ | Tüm loglar `SecretMasker.sanitizeLogMessage` üzerinden geçiyor. |
| Giriş akışı güvenliği | ✓ büyük ölçüde | Uygulama `sc`'yi doğrudan çağırmıyor; `etf-masa giris --login` → `sc login --local-read-only` (sabit argv, `shell=False`). Safari'de açılan URL regex'i `https://secure.scalable.capital/activate?user_code=…` ile sınırlı; başka alan adı açılamaz. |
| Uygulamanın kullandığı 30 sabit argv | ✓ 30/30 | Swift kaynaklarından otomatik çıkarıldı ve gerçek `build_parser()` ile parse edildi (betik Ek A'da). |

---

## 2. Bulunan hatalar

Önem sırası: **Y** = yüksek (yanlış bilgi gösterir veya özellik hiç çalışmaz), **O** = orta, **D** = düşük.

### Y1: Giriş ve başlangıç akışı başarısızlığı "başarılı" gösteriyor
**Dosyalar:** `CLIProcessRunnerProtocol.swift:73` (`_ = try await self.runCommand(...)`), `TodayDashboardViewModel.swift:153-157` ve `:203-207`.

- `runStream`, `runCommand`'ın döndürdüğü `CLIOperationResult` değerini atıyor.
- Sıfırdan farklı çıkış kodu istisna fırlatmadığı için akış "normal" bitiyor.
- Sonuç:
  - `sc login` reddedilse, telefon onayı verilmese ya da süre dolsa bile `isSessionActive = true` yapılıyor ve **"✓ Giriş başarılı!"** yazıyor.
  - `veri` oturum hatasıyla `exit 1` verse bile **"✓ Başlangıç akışı başarıyla tamamlandı: … tüm fiyatlar ve portföy güncellendi!"** yazıyor.
- Swift testleri yalnızca mutlu yolu (mock) deniyor.

**Neden kritik:** Kullanıcı, bayat fiyatlarla "güncel" olduğunu sanarak tut/sat yorumunu okur. Sistemin temel ilkesi "sahte değer yok" burada çiğneniyor.

### Y2: Araştırma ekranından başlatılan her araştırma hata veriyor
- **Dosyalar:** `ResearchEvidenceView.swift:681-685` (tag'ler: `LONG_TERM`, `MEDIUM_TERM`, `SHORT_TERM`), `CLIProcessRunner.swift:466-469` (`--vade <tag>`).
- **CLI tarafı:** `arastir --vade` yalnızca `uzun | orta | firsat` kabul ediyor.
- **Test:** `arastir IE00B3YLTY66 --vade LONG_TERM` → `invalid choice`, çıkış kodu 2. Kullanıcı ne seçerse seçsin araştırma başlamıyor.
- **Neden yakalanmadı:** `cockpit_commands.json` elle yazılmış ve bu argv içinde yok. Sözleşme testi, Swift'in gerçekte ürettiği komutları değil, birinin hatırladığı komutları test ediyor.

### O1: "-" ile başlayan tez metni argparse'ı bozuyor
`--tetikleyiciler -10% b` ya da `--ozet -5%` → `expected one argument`. "−%10 düşüş" Türkçe tetikleyici yazarken çok olası bir giriş. Boşluk içerirse geçiyor ama bu tesadüf.

### O2: Tarama ekranı her açılışta canlı tarama yapıyor
- `ScreenerView.swift:32` içindeki `.task { loadData() }` → `tarama --json`.
- Her açılışta:
  - 17 havuz ISIN'i için Scalable'a `chart` çağrısı gidiyor;
  - append-only veritabanına mühürlü bir `scan_*` koşusu ve 2 audit olayı yazılıyor (kopyada doğrulandı: audit sayısı 120 → 122).
- Ayrıca `tarama` için zaman aşımı çözümleyicide tanımlı değil, varsayılan 60 sn uygulanıyor.

**Sonuçları:**
- Gereksiz broker yükü ve rate-limit riski.
- Her sekme ziyaretinde DB büyüyor.
- Oturum yokken "ELENDİ" listesiyle dolu, yanıltıcı bir ekran çıkıyor.

### O3: Yedekler kontrolsüz büyüyor
- **Durum:** 2,5 günde 81 `.db` dosyası, 202 MB, defterde 74 BACKUP satırı. Bazı saatlerde 20+ yedek alınmış (31.10 21:00 → 23 adet, 01.11 08:00 → 20 adet).
- **Saklama:** `backup.py` içinde saklama/budama kodu **hiç yok**. "30 yedek tutulur" iddiası doğru değil.
- **Hash:** Her yedek bir audit olayı ekliyor, bu yüzden iş verisi değişmese bile her yedeğin hash'i farklı. Tekilleştirme imkânsız.
- **Adlandırma:** `yedek --prova` (UI'daki "Prova") gerçek bir yedek de oluşturuyor; isim "deneme" çağrıştırıyor.

### O4: Sabit 60 sn zaman aşımları, çözümleyicideki doğru değerleri eziyor
Çözümleyici mantığı doğru ama view-model'ler açık değer veriyor:

| Ekran | Komut | Verilen | Olması gereken |
|---|---|---|---|
| `PortfolioViewModel.swift:296` | `veri` | 60 | 300 |
| `TransactionLedgerViewModel.swift:197` | `islemler cek` | 60 | 300 |
| `TransactionLedgerViewModel.swift:219` | `mutabakat --detay` | 60 | ≥120 |
| `TargetBasketOverlapViewModel.swift:320` | `plan` | 60 | ≥120 |
| `ThesisManagementViewModel.swift:271/346` | `tez kontrol` / `tez ekle` | 60 | ≥120 |
| `ScreenerViewModel` | `tarama` | 60 (varsayılan) | 600 |

Yavaş bir pazartesi sabahı `veri` 60 sn'yi aşarsa işlem SIGINT ile kesilir.

### O5: Başlangıç akışı kullanıcının asıl 5 adımlı akışının yalnızca ilk 2'sini yapıyor
- **Kullanıcının istediği akış:**
  1. oturum kontrolü;
  2. veri;
  3. elimdekiler hakkında yorum (TradingAgents);
  4. tut/sat önerisi;
  5. havuz taraması.
- **Uygulama:** "Başlangıç Akışını Çalıştır" yalnızca `veri` + `gecmis` çalıştırıp "tamamlandı" diyor. CLI'da hepsini yapan `baslat` komutu var, ama uygulama onu zincirlemiyor.

### D1: Sabit kullanıcı yolları (7 yer)
- `DatabaseService.swift:43`
- `CLIProcessRunner.swift:56`, `:82`, `:112`
- `CockpitAppState.swift:47`
- `TargetBasketOverlapViewModel.swift:25` (`portfoy.json`'ı CLI yerine diskten okuyor)
- `ReportsViewModel.swift:54`

Ayrıca ikili dosya çözümleme sırası (cwd → PATH → bundle) PATH'teki herhangi bir `etf-masa` dosyasını çalıştırabilir (path planting). Tek bir yapılandırılmış mutlak yol ve sahiplik kontrolü daha güvenli.

### D2: Aktivasyon URL'si parçalara bölünürse Safari açılmıyor
Regex her `readabilityHandler` parçasına ayrı uygulanıyor. URL iki parçaya bölünürse eşleşme olmuyor ve Safari açılmıyor. Satır tamponu gerekli.

### D3: Zamanlayıcıda ölü kod
`runSchedulerAction(... "calistir")`, yani `zamanla calistir` diye bir alt komut yok. Bugün yalnızca 3 etiket (sabah/aksam/cuma) olduğu için bu dala girilmiyor, ama ileride eklenen ajan sessizce düşer.

### D4: Sözleşme şemaları gevşek
- Hiçbir şemada `additionalProperties: false` yok, `required` sayısı 1–5 arası. Bir alan adı değişse test yine geçer, Swift tarafındaki `Decodable` ise patlar.
- `cockpit_commands.json` elle tutuluyor (bkz. Y2).

### D5: Küçük kusurlar
- **stdin:** `stdin` verisi `process.run()` çağrısından **önce** pipe'a yazılıyor. 64 KB'yi aşan bir ayar JSON'unda kilitlenir. Bugünkü dosyalar küçük, risk düşük.
- **Hedef ağırlık:** `--hedef-agirlik` normalizasyonu belirsiz: "1" yazılınca %100 sayılıyor, "0.5" yazılınca %0,5 mi %50 mi belli değil.
- **giris --json:** `account_id` ve `email` uygulamaya ham olarak dönüyor. Ekranda gösterilmiyor ama gerek de yok, maskelenmeli.
- **gitleaks:** Kurulu değil, `guvenlik-tara` testi bu yüzden kırmızı. Ya `brew install gitleaks` ya da test, ikili yoksa `skip` olmalı.

### Veri ve kullanım gözlemleri (hata değil, ürün sorunu)
- **Hafta sonu:** Bugünkü (Pazar) koşu DEGRADED, tüm kotasyonlar OUTDATED, tüm değerlendirmeler "VERİ YETERSİZ". Teknik olarak doğru, ama kullanıcı "sistem bozuk" sanıyor. "Piyasa kapalı: son kapanış (Cuma 17:30) ile değerlendirildi" durumu gerekli.
- **Boş tablolar:** `forecast`, `thesis`, `holdings`, `reconciliation` tablolarında hâlâ 0 satır var. Özellikler var ama hiç kullanılmamış:
  - Tahmin karnesi için güven gösterimi en az 30 uzlaşmış gün istiyor. Zamanlayıcı kurulmazsa bu hiç dolmaz.

---

## 3. Diğer yapay zekâya verilecek düzeltme ve geliştirme promptu

> Aşağıdaki bölüm doğrudan kopyalanıp verilebilir.

```
ROL: ETF Yatırım Masası (Python masa çekirdeği + Swift ETFCockpit) bakımcısısın.
DEĞİŞMEZ KURALLAR (ihlal = iş reddedilir):
- Broker'a yazma yolu yok; sc yalnızca masa üzerinden, salt-okunur komutlarla, shell=False.
- Uygulama sc'yi asla doğrudan çağırmaz; yalnızca etf-masa.
- .env / API anahtarı okunmaz, yazdırılmaz, loglanmaz.
- Sahte değer, hedef, eşik uydurulmaz; bilinmeyen şey "bilinmiyor" diye gösterilir.
- Testler canlı DB'ye, yedeklere ve zincir defterine dokunmaz (conftest bariyeri korunur).
- Canlı DB'yi değiştiren her işlem kullanıcı onayı ister. Göç ya da yedek budama
  çalıştırmadan önce dur ve sor.
- Her iş paketi: kod + test + "nasıl doğrulandı" çıktısı. "Yaptım" demek kabul değildir.
  Komut çıktısını göster.

İŞ PAKETLERİ (bu sırayla):

İP-1 [Y1] Akış sonucunun dürüstlüğü
 a) CLIStreamChunk'a `case exit(Int32)` ekle. runStream, runCommand bitince
    .exit(result.exitCode) yield etsin. Timeout ve iptal durumunda mevcut throw'lar kalsın.
 b) TodayDashboardViewModel.runLoginStream:
    - exit != 0 ise başarısız say;
    - exit == 0 olsa bile `giris --json` ile doğrula; `active == true` değilse
      "Giriş tamamlanmadı" de;
    - isSessionActive'i YALNIZCA doğrulamadan sonra true yap.
 c) refreshData: veri ve gecmis için çıkış kodlarını ayrı ayrı kontrol et.
    - veri exit 1 (oturum) → "Veri çekilemedi: oturum gerekli", akışı durdur.
    - veri exit 2 (DEGRADED) → "Kısmi veri: N kotasyon alınamadı" (sarı).
    - "✓ tamamlandı" mesajı yalnızca hepsi 0 ise.
 d) Testler (MockCLI ile): login exit 1; login exit 0 ama giris --json active=false;
    veri exit 1; veri exit 2; URL hiç gelmeden süreç bitmesi. Her birinde mesaj ve
    isSessionActive doğru olmalı.
 Kabul: 5 yeni test yeşil. Eski mutlu yol testi de yeşil.

İP-2 [Y2 + D4] Sözleşmeyi Swift kaynağından üret
 a) Araştırma vade picker tag'lerini CLI ile eşle: uzun / orta / firsat (Türkçe etiket
    aynı kalsın). Ya da CLI'ya İngilizce alias ekle. TEK kaynak seç ve belgelendir.
 b) masa/tests/test_cockpit_argv_extracted.py:
    - ../macos/Sources altındaki tüm `arguments: [ "..." ]` literal dizilerini regex ile çıkar;
    - dinamik oluşturulanlar için (tez ekle, arastir --vade X, zamanla <eylem>,
      ayar yaz --dosya X) Swift'teki enum/picker değerlerini de tara
      (örn. `.tag("...")`);
    - hepsini build_parser().parse_args ile parse et.
    (Referans betik: rapor Ek A.)
 c) Swift'teki `zamanla calistir` dalını kaldır ya da CLI'ya gerçek bir
    `zamanla calistir --ajan <label>` ekle.
 d) Şemalara `additionalProperties: false` ekle (en azından üst seviyede) ve Swift
    Decodable modellerinin kullandığı her alanı `required` yap. Swift tarafında aynı
    fixture JSON'larla decode testi yaz (fixtures, Python testinin ürettiği gerçek
    çıktıdan alınsın).
 Kabul: Y2 düzeltilmeden önce yeni test KIRMIZI olmalı (ekran çıktısı), sonra yeşil.

İP-3 [O1] Serbest metin argümanları
 - tez ekle için metin alanlarını argv yerine stdin JSON ile geçir:
   `tez ekle --girdi-json -` (alanlar: isin, baslik, ozet, gerekce, kategori, vade,
   tetikleyiciler[], kanitlar[], karsi_gorus, hedef_agirlik, sonraki_kontrol).
 - CLI tarafında JSON şeması ile doğrula. Eski argv yolu insanlar için kalsın.
 - Test: "-10% düşüş", "--json", emoji ve 5.000 karakterlik gerekçe.
 - hedef_agirlik'i UI'da yüzde olarak al (0–100), CLI'ya oran (0–1) gönder.
   Belirsiz "1" girdisi kalmasın.

İP-4 [O2] Tarama ekranı okuma/çalıştırma ayrımı
 a) Yeni `masa tarama --son --json`: sc'ye gitmeden son mühürlü scan koşusunu DB'den
    okur. Alanlar: run_id, completed_at, yaş (dakika), candidates.
 b) ScreenerView .task → yalnızca `tarama --son --json`.
    "Şimdi Tara" butonu → `tarama --json` (timeout 600 sn).
 c) Oturum yoksa tarama çalıştırma. "ELENDİ: Veri alınamadı" yerine ekranda
    "Tarama için oturum gerekli" göster.
 Kabul: Ekranı 5 kez açıp kapamak audit_events sayısını DEĞİŞTİRMEMELİ
 (DB kopyasında test et).

İP-5 [O3] Yedek saklama politikası
 a) politika.json'a kullanıcı onaylı bir alan ekle (DEĞER UYDURMA, kullanıcıya sor):
    yedek_saklama: {gunluk: ?, haftalik: ?, aylik: ?}.
    Öneri olarak 7/4/12 sun, ama kullanıcı onaylamadan yazma.
 b) `masa yedek budama --kuru` (varsayılan kuru çalışma) ve
    `masa yedek budama --uygula --onay`.
    - Yalnızca .db/.json dosyaları silinir.
    - Zincir defterindeki BACKUP satırları SİLİNMEZ; yerine PRUNE satırı eklenir
      (dosya adı + sha256).
    - En son yedek ve en son başarılı prova yedeği asla silinmez.
 c) Aynı saat içinde, iş verisi değişmediyse (snapshot tip + audit tip hariç
    CREATE_BACKUP) yeni yedek alma; "değişiklik yok, son yedek X" de.
 d) UI'da "Prova" butonunun adını "Yedek al + geri yükleme provası" yap.
 Kabul: geçici dizinde 40 sahte yedekle budama testi; defter monotonluğu ve
 `dogrula` hâlâ MATCH_SEALED.

İP-6 [O4] Zaman aşımı tek kaynak
 - View-model'lerdeki tüm sabit `timeoutSeconds:` değerlerini kaldır.
   Hepsi CLIProcessRunner.resolveCommandTimeout'tan gelsin.
 - Tabloyu cockpit_commands.json'a taşı ({argv, timeout_s, mutating: bool}) ve
   hem Swift hem Python testi aynı dosyayı okusun.
 - tarama 600, plan 180, mutabakat 180, tez 120.
 Kabul: grep "timeoutSeconds: [0-9]" Features/ → yalnızca giris --login (300) kalır.

İP-7 [O5] Tam sabah akışı
 "Başlangıç Akışını Çalıştır" şu adımları sırayla yürütsün ve her adımın gerçek çıkış
 kodunu göstersin:
   1. giris --json; oturum yoksa login akışı (İP-1 kurallarıyla)
   2. veri
   3. gecmis (son 24 saatte çalıştıysa atla, nedenini yaz)
   4. degerlendir --json (tut/azalt/gözden geçir/ekle etiketleri)
   5. yorum (TradingAgents; kota/429 → "model kotası doldu, deterministik
      değerlendirme geçerli" de, akışı başarısız sayma)
   6. tarama --json
 - Her adım: başla/bitti/süre/çıkış kodu, ilerleme çubuğu, iptal butonu.
 - İptal → SIGINT, yarım kalan adım "iptal edildi" olarak işaretlenir.
 - Sonuç kartı: "X pozisyon değerlendirildi, Y fırsat adayı, veri tazeliği:
   <son kotasyon zamanı>".
 Kabul: MockCLI ile her adımın başarısız olduğu 6 ayrı test.

İP-8 [UX] Piyasa kapalı durumu
 - XETR takvimini kullan (forecast motorunda zaten var).
 - Piyasa kapalıyken OUTDATED kotasyonu son kapanışa kadar "SON KAPANIŞ" olarak
   işaretle. Değerlendirme "VERİ YETERSİZ" yerine "Son kapanışa göre" yapılsın, ama
   etiketin yanında açıkça gösterilsin.
 - Kapanıştan sonra geçen süre > 1 işlem günü ise yine VERİ YETERSİZ.
   Eşikler politika.json'da ve kullanıcı onaylı olmalı.
 Kabul: Cumartesi ve Pazar için sabit tarihli test; bayram günü testi.

İP-9 [D1 + D2 + D5] Sağlamlaştırma
 a) Yollar:
    - Uygulama ilk açılışta "Masa klasörü" seçtirsin (NSOpenPanel) ve
      UserDefaults'a security-scoped bookmark olarak kaydetsin.
    - etf-masa = <klasör>/etf-masa; sahibi mevcut kullanıcı ve grup/diğer yazma izni
      yoksa çalıştır.
    - cwd ve PATH taramasını kaldır.
    - Kaynakta "/Users/" geçen satır kalmasın (CI'da grep testi).
    - TargetBasketOverlapViewModel portfoy.json'ı `ayar goster --json`'dan okusun.
 b) Login çıktısını satır tamponuyla işle (parçalı URL testi).
 c) stdin'i process.run()'dan SONRA arka planda yaz. 200 KB stdin testi.
 d) giris --json: account_id → maskeli (son 4), email → maskeli. Şema güncelle.
 e) gitleaks yoksa güvenlik testi skip + uyarı. Ya da README'ye `brew install gitleaks`.

İP-10 [Veri] Özelliklerin canlıya alınması (kullanıcı onayıyla)
 - `zamanla durum`: ajanlar kurulu mu? Değilse UI'da büyük bir "Tahmin karnesi için
   zamanlayıcı kurulmamış" uyarısı ve "Kur" butonu (onaylı).
 - Tez ekranı boşsa: elde tutulan her pozisyon için "tez yok" rozeti ve
   "Tez yaz" kısayolu.
 - Mutabakat hiç çalışmamışsa: "İşlem defteri hiç mutabık edilmedi" uyarısı.

TESLİM FORMATI
 Her İP için:
  (1) değişen dosyalar;
  (2) eklenen testler;
  (3) gerçek komut çıktısı:
      - pytest -q son 5 satır;
      - swift test özeti;
      - İP'ye özel doğrulama komutu.
  (4) bilinen sınırlamalar.
 Canlı DB'de çalıştırılması gereken her şey için kullanıcıya önce SOR.
```

---

## 4. Ek geliştirme fikirleri (öncelik sırasıyla)

1. **Oturum ömrü göstergesi.**
   - Scalable oturumu en fazla 7 gün, boşta 24 saat yaşıyor. Başarılı girişten sonra giriş zamanını kaydet.
   - Üst barda "Oturum: 5 g 3 sa kaldı / boşta 18 sa" göster.
   - Sabah 09:30 ajanı oturum yoksa `waiting_auth` bildirimi zaten atıyor. Bildirime tıklayınca uygulama doğrudan giriş adımında açılsın.
2. **"Neden bu etiket?" paneli.** Her TUT/AZALT/EKLE kararının yanında şunlar dursun:
   - tetikleyen kural (politika.json satırı);
   - kullanılan veri ve tazeliği;
   - kırmızı takım (critic) sonucu.

   Bugün kullanıcı yalnızca etiketi görüyor.
3. **Vergi farkındalığı (yalnızca bilgi, tavsiye değil).**
   - Satış önerisinin yanında tahmini gerçekleşen kazanç göster.
   - Hisse fonları için %30 Teilfreistellung uygula.
   - Kalan Sparer-Pauschbetrag'ı göster: bekâr 1.000 €; Freistellungsauftrag tutarını kullanıcı girer.
   - Böylece "AZALT" önerisinin vergi maliyeti görünür olur.
4. **Değerlendirme geçmişi.** Aynı ISIN için son 10 koşunun etiket zaman çizelgesi. Etiket sık zıplıyorsa (TUT→AZALT→TUT) eşikler fazla hassas demektir; politika ayarı için kanıt olur.
5. **TradingAgents maliyet ve kota sayacı.**
   - ModelRouter'ın her çağrısını say: sağlayıcı, kademe, başarı, 429.
   - "Bugün Gemini %62, ChatGPT %38; 2 kota hatası" gibi bir panel göster. Abonelik ve ücretsiz kotanın orantılı kullanıldığını kullanıcı buradan doğrular.
6. **CI.** Her commit'te sırasıyla şunları çalıştıran tek bir `make kabul` komutu (bugün bunların hepsini elle koşturuyoruz):
   - pytest;
   - swift test;
   - argv çıkarım testi;
   - "/Users/" grep'i;
   - şema testleri;
   - `dogrula` (kopya DB üzerinde).
7. **Uygulama imzalama.** `dist/ETFCockpit.app` ad-hoc imzalı olabilir. Gatekeeper uyarısı ve ileride Ekran Kaydı/Bildirim izinleri için Developer ID ile imzalamak düşünülebilir. Bu turda doğrulanmadı.

---

## Ek A: Swift argv sözleşme betiği (masa/ dizininden çalıştırılır)

```python
import re, pathlib, sys
sys.path.insert(0, "src")
from masa.cli import build_parser
pat = re.compile(r'arguments:\s*\[((?:\s*"[^"]*"\s*,?)+)\]')
found = set()
for f in pathlib.Path("../macos/Sources").rglob("*.swift"):
    for m in pat.finditer(f.read_text()):
        found.add((tuple(re.findall(r'"([^"]*)"', m.group(1))), f.name))
p = build_parser(); bad = 0
for argv, src in sorted(found):
    try: p.parse_args(list(argv)); r = "OK"
    except SystemExit: r = "FAIL"; bad += 1
    print(f"{r:5} {src:40} {' '.join(argv)}")
print("bad", bad)
```

Bu turdaki sonuç: 30 sabit argv'nin hepsi OK. Ancak dinamik `arastir … --vade LONG_TERM` FAIL. Bu yüzden İP-2b, picker tag'lerini de taramalıdır.
