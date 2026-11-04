# ETF Yatırım Masası — Kalan İşler: Ana Uygulama Promptu (v1, 30.10.2026)

> Bu metni, `~/Documents/ETF` klasörüne dosya ve terminal erişimi olan bir kodlama
> asistanına (Claude, Codex, Gemini vb.) olduğu gibi verin. Asistan işleri **iş paketi (İP) sırasıyla**,
> her paketin sonunda durup rapor vererek yapmalıdır.

---

## 0. ROLÜN VE ÇALIŞMA KURALLARIN

Sen kıdemli bir Python yazılım mimarı ve finansal veri mühendisisin. Görevin, mevcut **ETF Yatırım
Masası** (`ETF/masa/`, v0.2, şema v2) sistemini tasarım belgesindeki eksik fazlara göre tamamlamak.
Sıfırdan yazmıyorsun; **çalışan bir sistemi bozmadan genişletiyorsun.**

### 0.1 Önce oku (kod yazmadan önce, bu sırayla)

1. `ETF/reports/2026-10-30-nihai-yatirim-masasi-tasarimi.md`: nihai tasarım. Bağlayıcı belge budur.
2. `ETF/reports/2026-10-30-bagimsiz-denetim-raporu.md`: bağımsız denetim ve "Düzeltme durumu" bölümü.
3. `ETF/masa/README.md`: komutlar ve güvenlik sınırları.
4. `ETF/Yatirim-Masasi/etf-yatirim-masasi/SKILL.md` ve `references/*.md`, özellikle
   `tez-ve-portfoy.md`, `veri-kurallari.md`, `fon-inceleme.md` ve `firsat-arastirmasi.md`.
   Bunlar kullanıcının **kendi yatırım yöntemidir**; kurallarına uy.
5. Kod: `masa/src/masa/` altında
   - `pipeline.py`: veri hattı, mühürler, `latest_run`, `integrity_report`
   - `storage/`: `schema.sql`, `db.py`, `hash_chain.py`, `snapshot_store.py`
   - `ingestion/sc_reader.py`, `analytics.py`, `advisor.py`, `scanner.py`, `report.py`, `cli.py`
   - `config.py`, `integrations/tradingagents.py`
   - `calc/`, `research/`, `identity/`, `audit/`
6. Ayarlar: `masa/config/{portfoy,politika,havuz,modeller}.json`.
7. Testler: `masa/tests/` (126 test) ve `ETF/tests/` (34 eski test).
8. Eski veri: `ETF/Yatirim-Masasi/veri/` (`tezler.json`, `izleme-listesi.csv`, `dogrulanmis-fon-bilgileri.json`, `ayarlar.json`, `kaynaklar/`).

Okuduktan sonra, kod yazmadan önce, **her iş paketi için 5–10 satırlık bir uygulama planı** çıkar ve
kullanıcıya göster. "Karar gerekli" diye işaretlenmiş maddelerde dur ve sor.

### 0.2 Mutlak kurallar (ihlal = iş başarısız)

1. **Broker'a yazma yolu yok.** `sc` yalnız şu okuma komutlarıyla çağrılır: `whoami`, `broker context show`,
   `broker holdings`, `broker cash-breakdown`, `broker quote --isin`, `broker transactions`, `broker chart --isin`.
   Yeni okuma komutu eklersen (örn. `sc capabilities --json`, `sc broker watchlist --json`):
   - `OPERATION_TO_CLI_SUBCOMMAND` ve `ALLOWED_FLAGS` beyaz listesine ekle,
   - bunun için test yaz,
   - argv'de `trade`, `buy`, `sell`, `cancel`, `add`, `remove`, `select`, `--confirm`, `login` ve `logout` geçmediğini test et.
   `shell=False` ve sabit mutlak `sc` yolu korunur.
2. **Mevcut testler kırılmaz.** Her iş paketinin sonunda şu üç komut çalıştırılıp çıktısı rapora konur:
   - `cd ETF/masa && uv run pytest -q`
   - `cd ETF && .venv/bin/python -m pytest -q tests`
   - `uv lock --check`
   Bir testi değiştirmen gerekiyorsa nedenini yaz. Yanlış davranışı kodlayan test, düzeltilmiş davranışı
   kodlayan testle değiştirilir; test sırf geçsin diye gevşetilmez.
3. **Mühürlü veri değişmez.** `raw_objects`, `snapshots`, alt tablolar ve `audit_events` append-only'dir.
   UPDATE, DELETE ve REPLACE yasaktır. Düzeltme yeni kayıt ve `supersedes_id` ile yapılır.
   Yeni immutable tablolara da 3 tetikleyici eklenir: `prevent_update_*`, `prevent_delete_*`, `prevent_overwrite_*`.
4. **Şema geçişi veri kaybetmez.** Şu an `PRAGMA user_version = 2` ve `DatabaseManager.initialize_schema()`
   farklı sürümü reddediyor. v3 için bir `masa gecis` (migrate) komutu yaz. Komut:
   - (a) önce İP-1'deki yedeği alır,
   - (b) yalnız `CREATE TABLE/TRIGGER IF NOT EXISTS` ve gerekiyorsa yeni tablolar ekler (mevcut tabloları ALTER ile bozmaz),
   - (c) `user_version`'ı 3 yapar,
   - (d) geçiş sonrası `integrity_report()` ok=True döndüğünü doğrular; aksi halde yedekten geri döner.
   `SCHEMA_VERSION` sabitini ve testleri güncelle.
5. **Para/adet Decimal'dir.** Ham JSON `parse_float=Decimal` ile okunur ve DB'de TEXT saklanır.
   float yalnız istatistik/optimizasyon içinde kullanılabilir, sonucu raporda yuvarlanmış gösterilir.
6. **Uydurma yok.** Eksik veri `None`/"hesaplanmadı" olur. Kullanıcı onaylamadıkça:
   - hedef ağırlık, eşik, benchmark, vergi bilgisi veya al/sat kuralı icat edilmez (bkz. `tez-ve-portfoy.md`),
   - varsayılan eşikler "TASLAK" etiketi taşır.
7. **Fiyat kaynağı tektir:** çekirdek fiyatlar yalnız Scalable (`sc`) mühürlerinden gelir.
   Yahoo/TradingAgents/başka kaynaktan gelen sayı "harici/yardımcı" etiketi taşır, çekirdek hesaba karışmaz.
8. **Gizlilik:**
   - Buluta (LLM'e) giden pakette ad, hesap/portföy kimliği, IBAN ve ham işlem geçmişi olmaz;
     yalnız sembol, tarih, adet, ortalama maliyet ve nakit gider.
   - Kişisel çıktılar `masa/var/` altında kalır (gitignore'da).
   - `.env`, oturum ve anahtar dosyaları **okunmaz ve yazdırılmaz**. Ayar için yalnız `TRADINGAGENTS_*`
     model/sağlayıcı satırları okunabilir.
9. **Ücret kapısı:** model çağrısı yapan her yol önce `integrations/tradingagents.describe_providers()`
   benzeri bir özet gösterir ve onay ister (`--evet` hariç). Kota/limit hatasında **ücretli API'ye geçilmez**;
   yalnız `config/modeller.json`'daki abonelik/ücretsiz sağlayıcılar arasında geçilir.
10. **Yeni bağımlılık:** önce gerekçe yaz, sonra `uv add <paket>` yap ve `uv.lock`'u güncelle.
    Mümkünse standart kütüphane veya mevcut paketler kullanılır (mevcutlar: pydantic, exchange-calendars,
    quantstats, numpy, pandas, scipy, statsmodels, jsonschema, trafilatura, edgartools).
    keyring bilinçli olarak kaldırıldı; geri ekleme.
11. **Doğrulamadan "doğrulandı" deme.** Bir komutu çalıştırmadıysan "çalıştırılmadı" yaz. Gerçek `sc` veya
    gerçek LLM çağrısı gerektiren adımlar için kullanıcıdan Mac'te çalıştırmasını iste ve çıktısını bekle.
12. **Türkçe arayüz:** CLI mesajları, raporlar ve config açıklamaları Türkçe; kod tanımlayıcıları İngilizce kalabilir.

### 0.3 Her iş paketinin teslim biçimi

Her İP sonunda kullanıcıya şu yapıda kısa bir rapor ver:

- **Yapılanlar:** dosya:satır referanslarıyla.
- **Yeni/değişen testler** ve **test çıktısı** (üç komut, bkz. 0.2-2).
- **Elle doğrulama komutu:** kullanıcının Mac'te çalıştıracağı komut ve beklenen çıktı.
- **Açık kalanlar ve riskler.**
- **Karar bekleyen sorular** (varsa).

Sonra bir sonraki İP'ye geçmek için onay bekle.

---

## 1. MEVCUT DURUM ÖZETİ (bunu yeniden yapma)

Çalışıyor ve testli:

- **Scalable veri hattı:** `masa veri`, `masa gecmis`.
  - Mühürler run bazında bağlanıyor; bağlar quote manifestindeki `binds` alanında.
  - Raw stdout'lar ayrı saklanıyor.
  - İşlem geçmişinin tüm sayfaları cursor ile çekiliyor.
- **Bütünlük:**
  - Alan düzeyinde yeniden hesaplanan hash zinciri ve denetim olayları.
  - TRUNCATE journal, `recursive_triggers`, REPLACE koruması.
  - `masa dogrula` komutu.
- **Analiz:**
  - Risk (quantstats) ve korelasyon.
  - İşlem geçmişinden TWR/MD/XIRR, nakit mutabakatı, FIFO'nun broker'la karşılaştırılması.
  - Tut/ekle/azalt (`advisor.py`), havuz taraması (`scanner.py`).
  - Yeniden dengeleme planı (`calc/rebalancing.py`; yalnız `hedef_agirliklar` doluysa).
  - Red-team kod denetimi (`research/critic.py`).
- **TradingAgents yardımcı kip:**
  - Ayrı süreç, `scripts/ta_bridge.py` köprüsü.
  - Quick katman Google/ChatGPT arasında ağırlıklı sırayla; limitte diğerine geçiş (`config/modeller.json`).
- **Çıktılar:** Markdown rapor `masa/var/reports/masa-rapor-*.md` ve yorum paketi `yorum-paketi-*.md`.
- **Ana akış:** `./etf-masa baslat [--derin]`.

Bilinen sınırlar:

- `sc broker chart` yalnız ISIN bazında çalışıyor, portföy grafiği yok.
- 1y serisi ~127 noktadan oluşuyor (örneklemeli); `max` serisi ~120 nokta.

---

## 2. İŞ PAKETLERİ (öncelik sırasıyla)

### İP-1 · Yedek ve geri yükleme provası (YÜKSEK, ilk iş)

**Amaç:** tasarım §2.3'te istenen "tutarlı yedek + geri yükleme provası + zincir ucu manifesti".
Şu an mühürlü verinin tek kopyası `masa/var/private/masa.db`.

**Yapılacaklar**

1. `masa/src/masa/backup.py`:
   - `create_backup(db, dest_dir) -> BackupManifest`: SQLite **online backup API** (`sqlite3.Connection.backup`) kullanır, dosya kopyalamaz.
   - Manifest: tarih, kaynak yol, şema sürümü, her tablonun satır sayısı, `chain_tip` (son `snapshots.curr_hash`), son `audit_events.curr_hash`, yedek dosyasının SHA-256'sı, masa sürümü.
   - Manifest `backup-<ts>.json` olarak yedeğin yanına yazılır.
   - Ayrıca `masa/var/backups/zincir-uclari.jsonl` dosyasına tek satır eklenir. Bu, zincir ucunun bağımsız kaydıdır (append-only dosya).
2. `restore_drill(backup_path)`:
   - Yedeği geçici klasöre açar ve `integrity_report()` çalıştırır.
   - Satır sayıları ile chain_tip'in manifestle eşleştiğini doğrular.
   - Canlı DB'ye **dokunmaz**.
3. `restore(backup_path, --onayla)`:
   - Önce canlı DB'yi `masa_pre_restore_<ts>.db` adıyla arşive alır, sonra yedeği yerine koyar.
   - Yalnız açık onayla çalışır.
4. Zincir ucu doğrulaması:
   - `integrity_report()` canlı DB'nin zincirini `zincir-uclari.jsonl`'daki son kayıtla karşılaştırır.
   - Kayıttaki uç hash canlı zincirde bulunmuyorsa → "zincir yeniden yazılmış olabilir" kritik uyarısı.
   - Bu, tasarımın "aynı dosyayı kontrol etmek yetmez" maddesini karşılar.
5. CLI: `masa yedek`, `masa yedek --prova <dosya|son>`, `masa geri-yukle <dosya> --onayla`.
   - `baslat` akışının sonuna otomatik yedek eklenir (yalnız yeni mühür oluştuysa).
   - Varsayılan saklama: son 30 yedek. Daha eskiler `var/backups/arsiv/` altına taşınır, silinmez.
6. **Şifreleme (KARAR GEREKLİ):** kullanıcıya şu seçenekleri sun ve seçimini bekle:
   - (a) FileVault açıksa düz yedek (`fdesetup status` ile kontrol et, raporla),
   - (b) macOS `hdiutil` ile şifreli sparsebundle'a yazma,
   - (c) harici diske kopyalama yolu.
   Kendi başına karar verme.

**Kabul testleri**

- Yedek → prova: satır sayıları ve chain_tip eşleşir, `ok=True`.
- Yedek alındıktan sonra yeni `veri` çalışması: canlı DB zinciri yedeğin ucunu içerir → uyarı yok.
- Canlı DB'de zincir baştan yeniden yazılırsa (testte tetikleyicileri düşürüp tüm hash'leri yeniden hesapla) `zincir-uclari.jsonl` karşılaştırması bunu yakalar.
- Bozuk yedek dosyası (byte değiştir) → SHA uyuşmazlığı → prova başarısız.
- `geri-yukle` onaysız çalışmaz.

---

### İP-2 · Kimlik katmanı ve CLI yetenek kaydı (Faz 0–1 eksikleri)

**Amaç:** tasarım §2.1 kimlik modeli (`instrument_id`, `listing_id`, `issuer_id`) ve Faz 0 "CLI yetenek kaydı".

**Yapılacaklar**

1. Şema v3 (İP-1'deki geçiş komutuyla):
   - `instruments`: isin, ad, tür (ETF/STOCK), pay sınıfı, dağıtım (Acc/Dist), ihraççı, para birimi, kaynak, `valid_from`, `supersedes_id`.
   - `listings`: instrument_id, mic, sembol, para birimi, kaynak, doğrulama durumu (`UNVERIFIED`/`VERIFIED`/`REJECTED`), doğrulama kanıtı.
   - `issuer_links`: şirket ↔ menkul kıymet (ADR/ana hisse, çok sınıflı hisseler).
   - Hepsi append-only.
2. `identity/registry.py` şu an yalnız bellekte. DB'ye bağla:
   - `veri` çalışmasında holdings/quote'tan gelen ISIN, ad ve tür, `instruments` tablosuna yalnız yeni ya da değişmişse eklenir.
3. `config/portfoy.json` ve `havuz.json`'daki Yahoo sembolleri (`SPYI.DE` vb.) `listings` tablosuna `UNVERIFIED` olarak taşınır. Config okunmaya devam eder ama kaynak DB olur.
   - Doğrulama: TradingAgents ortamında (`~/TradingAgents/.venv/bin/python`) küçük bir betikle `yfinance.Ticker(sym).isin` ve/veya ad karşılaştırması.
   - Eşleşen `VERIFIED`, eşleşmeyen `REJECTED` olur ve kullanıcıya gösterilir.
   - `.DE` uzantısı tahminle üretilmez (tasarım §2.1).
4. `sc capabilities --json`:
   - `sc_reader`'a okuma operasyonu olarak ekle (beyaz liste + test).
   - Çıktıyı her `kontrol` çalışmasında ham kayıt olarak sakla.
   - Komut seti değişirse (yeni/kaybolan komut) uyarı ver.
   - Çıktıda salt-okuma moduyla ilgili bir alan varsa `kontrol`'de göster. Yoksa "tespit edilemedi" yaz; uydurma.
5. İzleme listesi: `sc broker watchlist --json` (okuma).
   - Mutasyon alt komutları (`add`/`remove`) yasak kalır; test yaz.
   - İzleme listesindeki ISIN'ler `havuz.json`'a **öneri** olarak sunulur, otomatik eklenmez.
   - `Yatirim-Masasi/veri/izleme-listesi.csv` içeriği de içe aktarma önerisi olarak gösterilir.

**Kabul testleri**

- Geçiş sonrası mevcut v2 mühürleri doğrulanır.
- Aynı holdings iki kez işlenince `instruments`'a kopya eklenmez.
- `watchlist add` argv'si reddedilir.
- `capabilities` değişim uyarısı fixture ile test edilir.

---

### İP-3 · İşlem defteri: sürümler, kurumsal işlemler, mutabakat (Faz 2)

**Amaç:** tasarım §2.2-A. Şu an `analytics.realized_returns()` yalnız SETTLED işlemleri ve BUY/SELL ile DEPOSIT/WITHDRAWAL/FEE/DISTRIBUTION/INTEREST/TAX tiplerini tanıyor. Bilinmeyen tipler "kapsam dışı" listesine düşüyor.

**Yapılacaklar**

1. `transaction_versions` tablosu:
   - Aynı `broker_tx_id` farklı `status`/`amount` ile tekrar görülürse yeni sürüm olur.
   - "Son durum" bir görünümdür (VIEW).
   - Her `gecmis` çalışması tüm geçmişi tekrar okumak yerine **artımlı** çalışır: `--from-time = son görülen işlem − 7 gün` örtüşmesiyle (`sc broker transactions --from-time`, bayrak beyaz listede var). Haftada bir tam tarama.
2. Tip kapsamı (`sc broker transactions --help` listesine göre): `SAVINGS_PLAN`, `SWAP_IN`/`SWAP_OUT`, `TRANSFER_IN`/`TRANSFER_OUT`, `REINVESTMENT*`, `CURRENCY_SWITCH_*`, `POCKET_MONEY`, `CASH_TRANSFER_*`.
   - Her biri için iki karar yazılır:
     - dış akış mı, iç hareket mi (tasarım: Sparplan'ı finanse eden dış yatırma dış akış; nakitten Sparplan alımı iç hareket),
     - adet ve maliyet etkisi ne.
   - Kanıt: gerçek örnek gerekiyorsa kullanıcıdan `sc broker transactions --type-filter <TIP> --json` çıktısı iste. Örnek yoksa tip "needs_review" olur ve getiri hesabı durur, uydurulmaz.
3. `corporate_actions` tablosu (bölünme, ISIN değişimi, birleşme):
   - `calc/performance.py` zaten `EngineContext.corporate_actions` destekliyor; bağla.
   - SWAP_IN/OUT çiftlerinden önerilen kurumsal işlem çıkar ama **kullanıcı onayıyla** kaydet.
4. `reconciliations` tablosu: her `rapor` çalışmasında
   - (a) adetler: yeniden kurulum vs broker,
   - (b) nakit: defter vs `cash-breakdown`,
   - (c) değer: broker `valuation` vs mühürlü mid,
   - (d) FIFO maliyet: masa vs broker `fifo_price`.
   Fark, tolerans ve açıklama kaydedilir. Açıklanamayan fark etkilenen getiriyi durdurur; raporda "Veri sorunu" sınıfıyla gösterilir.
5. Performans motoru için ara değerleme: şu an `sc broker chart` gün sonu fiyatları kullanılıyor. Bu "yaklaşık TWR" olarak etiketli kalsın. Akış anına en yakın gözlemin zaman farkı da raporda gösterilsin.

**Kabul testleri**

- Fixture'larda şu senaryolar:
  - SWAP_IN/OUT ile ISIN değişimi,
  - Sparplan (dış yatırma + iç alım),
  - iptal edilmiş işlem (`is_cancellation`),
  - durumu PENDING→SETTLED değişen işlem (yeni sürüm),
  - bilinmeyen tip (needs_review → getiri "hesaplanmadı").
- Artımlı çekimde kopya yok ve eksik yok (örtüşme penceresi testi).

---

### İP-4 · ETF sepeti yükleyicisi ve fonlar arası örtüşme (Faz 2, portföy için en değerli bilgi)

**Amaç:** `calc/lookthrough.py` hazır ve testli (Σ min(wA,wB), şirket konsolidasyonu, kapsam), ama veri kaynağı yok. Kullanıcının portföyü ACWI IMI, EM IMI, World Momentum ve World Value'dan oluşuyor; ACWI IMI içinde EM ve World şirketleri zaten var. Örtüşme ve şirket bazında gerçek maruziyet raporda görünmeli.

**Yapılacaklar**

1. Kaynak önceliği (tasarım §2.1): **ihraççı holdings dosyası** (CSV/XLSX). 13F veya justETF ana kaynak olmaz.
   - iShares ve SPDR'ın fon sayfalarındaki "holdings" indirme bağlantıları.
   - **KARAR GEREKLİ:** otomatik indirme mi, kullanıcının elle indirip `masa/var/private/holdings/inbox/` klasörüne bırakması mı? İkisini de destekle; varsayılan elle bırakma.
   - Otomatik indirmede: yalnız config'te tanımlı ihraççı URL'leri, kullanıcı onayı, kaynak URL ve indirme zamanı kaydı. Sayfa kazıma için `trafilatura` yalnız bağlantı bulmada kullanılır.
2. `masa/src/masa/holdings/` paketi:
   - İhraççıya özel ayrıştırıcılar (iShares CSV başlık satırları, SPDR XLSX), sözleşme testleriyle.
   - Ağırlık birimi (yüzde/oran), belge tarihi, pay sınıfı/ISIN eşleşmesi ve kapsama oranı doğrulanır.
   - Ağırlıklar %100'e **şişirilmez**; nakit, türev ve diğer kalemler ayrı tutulur.
3. Şema: `holdings_sets` (fon, belge tarihi, kaynak, ham dosya `raw_objects`'ta, kapsama) ve `holding_items` (isin, ad, ülke, sektör, ağırlık). Append-only.
4. Rapor bölümü "Sepet ve örtüşme":
   - Fon çiftleri için örtüşme matrisi (Σmin).
   - Portföy düzeyinde ilk 25 şirket maruziyeti (doğrudan + fon üzerinden), ülke ve sektör dağılımı.
   - Bilinen/kapsanmayan pay.
   - Belge tarihi 45 günden eskiyse uyarı.
5. `advisor.py`'ye "yoğunlaşma" bilgisi eklenir: tek şirket veya ülke maruziyeti. **Eşik kullanıcının `politika.json`'ına yazılmadıkça yalnız bilgi olarak gösterilir.** Önceki raporlardaki %5/%10 sınırları kullanıcı politikası değildir.

**Kabul testleri**

- Örnek iShares CSV ve SPDR XLSX fixture'ları (sentetik, gerçek biçimde).
- ACWI IMI + EM IMI örtüşmesi > 0.
- Eksik sepet kapsaması doğru raporlanıyor.
- Belge tarihi uyarısı çalışıyor.
- Ağırlık toplamı 1'i geçen dosya reddediliyor.

---

### İP-5 · Tez kaydı ve tahmin defteri (Faz 2–3; tasarım "ilk günden kayıt" diyor)

**Amaç:** tasarım §1.1-6, §2.2-F ve `tez-ve-portfoy.md`'deki kalıcı tez alanları.

**Yapılacaklar**

1. Tablolar:
   - `thesis_versions`: alanlar `thesis_id`, ISIN/ekonomik maruziyet, açılış tarihi, tek cümlelik tez, analitik ufuk, benchmark (boşsa "araştırma referansı" etiketi), kanıt sütunları, karşı görüş, zayıflatacak koşullar, kaynaklar, durum, sonraki kontrol tarihi, değişiklik nedeni, `supersedes_id`.
   - `forecast_entries`: görüş, ufuk, ölçüt, giriş mührü (run_id + hash), referans.
   - `settlements`: sonuç ve ölçüm tarihi.
   - Hepsi append-only. Eski tez silinmez; yeni sürüm eklenir.
2. CLI: `masa tez listele | goster <id> | ekle | guncelle <id>`. Etkileşimli Türkçe sorularla; JSON dosyasıyla toplu giriş de olsun.
3. `Yatirim-Masasi/veri/tezler.json` içe aktarımı:
   - Önce içeriği göster, kullanıcı onaylarsa "içe aktarıldı (doğrulanmadı)" etiketiyle ekle.
   - Örnek/sosyal medya portföylerini kullanıcı tezi yapma (`tez-ve-portfoy.md`).
4. `advisor.py` etiketleri ile TradingAgents görüşleri `forecast_entries`'e **yalnız kullanıcı isterse** yazılır (`masa rapor --tahmin-kaydet`). Ufuk zorunlu alandır; 5 günlük TradingAgents ufku uzun vadeli ETF tezi için ölçüt sayılmaz.
5. Aylık kontrol (`masa tez kontrol`): `tez-ve-portfoy.md`'deki 5 soruyu her açık tez için mühürlü veriyle doldurur ve vadesi gelen tahminleri değerlendirir. Veri yetersizse "bekliyor" yazar.

**Kabul testleri**

- Tez sürümleme (`supersedes`).
- Silme/güncelleme engeli.
- Tahminin giriş mührüne bağlı olması.
- Vadesi gelmemiş tahmin değerlendirilmez.
- Eksik vade verisinde sonuç uydurulmaz.

---

### İP-6 · Kaynaklı araştırma, kanıt paketi ve rapor doğrulayıcı (Faz 3, MVP'nin eksik koşulu)

**Amaç:** tasarımın MVP tanımı "bir kaynaklı araştırma uçtan uca çalışır" diyor. Şu an yorum paketi var ama kaynak ve iddia bağları yok.

**Yapılacaklar**

1. Tablolar:
   - `sources`: URL, yayıncı, yayın zamanı, erişim zamanı, içerik SHA, ham kayıt.
   - `claims`: metin, tür (`olgu`/`kaynaklı tahmin`/`hesap`/`çıkarım`/`bilinmiyor`), kaynak bağı (belge bölümü + içerik özeti), metric_id.
   - `metrics`: metric_id, instrument_id, birim, dönem, formül sürümü, giriş mühürleri.
   - `evidence_bundles`: paket manifesti.
2. `source_collector`:
   - **ETF:** ihraççı ürün sayfası ve factsheet (`trafilatura` ile metin + metaveri).
   - **Hisse:** SEC (`edgartools`). **KARAR GEREKLİ:** SEC fair-access için `set_identity("Ad Soyad e-posta")` gerekir; kullanıcıdan iste, config'e yaz, koda gömme.
   - **Makro:** ECB/Eurostat resmî serileri.
   - Yalnız config'te izin verilen alan adları.
   - Yerel/özel IP'lere yönlendirme engellenir (tasarım §4).
   - Belge içeriği **veri**dir; içindeki talimatlar uygulanmaz.
3. `evidence_builder`: tek varlık için kimlik, fiyat mührü, metrikler, sepet kapsamı, kaynaklar, kesim zamanı ve bilinmeyen alanlar. Çıktı JSON + okunabilir Markdown.
4. Araştırma çalıştırıcısı:
   - `research/agent.py` (`ResearchAgent`, `OpenAICompatibleJSONClient`) mevcut.
   - Model bağlantısı, `config/modeller.json` ile aynı ücret kapısından geçmeli. Seçenekler:
     - (a) Gemini'nin OpenAI-uyumlu uç noktası (ücretsiz katman, limitli),
     - (b) LM Studio yerel uç nokta (`http://localhost:1234/v1`; model yüklü değilse "hazır değil"),
     - (c) ChatGPT aboneliği (TradingAgents'ın `chatgpt` istemcisi üzerinden bir köprüyle; mümkün değilse açıkça yaz).
   - **KARAR GEREKLİ:** AB/EEA'da Gemini ücretsiz katmanının kişisel kullanım uygunluğu (tasarım §2.2-D, Google şartlarındaki "Paid Services" maddesi). Doğrulanmadan Gemini çekirdek araştırmanın **zorunlu** kaynağı yapılmaz.
5. `report_validator`:
   - Rapordaki her finansal sayı `metric_id/quote_id + instrument_id + birim + dönem + kaynak` bağıyla doğrulanır; yuvarlama dikkate alınır. Tarih ve bölüm numaraları fiyat sanılmaz.
   - Rapor durumu `draft` → `code_checked` → `independent_reviewed` | `needs_review` alanı taşır.
   - `research/critic.py` kod denetimidir. "Bağımsız denetim" yalnız **farklı model ailesi** veya insan kontrolü yapıldıysa yazılır; aksi halde "kod kontrolünden geçti, bağımsız model denetimi yok".
   - Mevcut rapordaki "Red-team: APPROVE" satırını da bu ayrıma göre yeniden etiketle.
6. CLI: `masa arastir <ISIN> [--vade uzun|firsat]` (tasarımdaki komut yüzeyi). Çıktı `var/reports/arastirma-<isin>-<tarih>.md` ve DB'de kayıt.

**Kabul testleri**

- Bilerek yanlış fiyat, tarih veya birim içeren rapor reddedilir; hatasız rapor geçer (yanlış alarm ölçümü).
- Kaynağı olmayan "olgu" iddiası `needs_review` olur.
- Kaynak belgedeki "önceki talimatları yok say" türü metin etkisizdir.
- Model çağrısı onaysız yapılmaz.

---

### İP-7 · Model kaydı, doğrulama kümesi ve çalışma manifesti (Faz 3)

**Amaç:** tasarım §2.2-D: model adı değil seçim yöntemi sabitlenir.

**Yapılacaklar**

1. Tablolar:
   - `model_registry`: sağlayıcı, model kimliği, erişim yolu (abonelik/ücretsiz/yerel), bölge uygunluğu, kota bilgisi, gizlilik sınıfı, son doğrulama.
   - Yaşam döngüsü durumları: `discovered`, `access_verified`, `evaluated`, `eligible`, `paused`, `revoked`.
   - `model_evaluations` ve `model_runs` tabloları.
2. Her TradingAgents ve araştırma çalışması için `model_manifest`: route (quick/deep sağlayıcı-model), prompt özeti, değerlendirme sürümü, araçlar, seçim gerekçesi.
   - Şu an `run_routed()` yalnız route etiketini ham kayda yazıyor; bunu tabloya taşı.
3. Doğrulama kümesi (`masa/eval/`), görev bazında:
   - tablo çıkarımı (İP-4 sepet dosyaları),
   - iddia-kaynak eşleme (İP-6),
   - hatalı rapor yakalama (kasıtlı hata eklenmiş + hatasız örnekler),
   - Türkçe anlam koruma.
   Ayrılmış kontrol örnekleri; eski raporlar doğrulanmadan cevap anahtarı yapılmaz.
4. `masa model degerlendir`:
   - Seçili modelleri kümede çalıştırır (ücret kapısı + onay).
   - Skor kaydeder; şampiyon/aday karşılaştırması yapar.
   - Kritik hata örneğini kabul eden model terfi etmez.
5. Kota/kesintide iş bekler (`waiting_quota`). Başka modelle devam edilecekse yeni alt çalışma açılır; çıktılar sessizce birleştirilmez.

**Kabul testleri**

- Manifestsiz çalışma reddedilir.
- `paused` model seçilmez.
- Kota hatası `waiting_quota` durumuna geçirir.
- Değerlendirme skorları sürümlü saklanır.

---

### İP-8 · İş kuyruğu ve durum makinesi (Faz 1 "basit iş kuyruğu", Faz 5 hazırlığı)

**Amaç:**
- `audit/queue.py` (`JobQueue`) ve `JobState` (`queued` → `collecting` → `validating` → `calculating` → `researching` → `reviewing` → `published`; ayrıca `waiting_auth`, `waiting_quota`, `needs_review`, `failed`, `cancelled`) mevcut, ama CLI kullanmıyor.
- Tasarım §2.2-F ve §4: tekrar önleme anahtarı, kesinti sonrası devam, retry fırtınası yok.

**Yapılacaklar**

1. `veri`, `gecmis`, `tarama`, `tradingagents`, `arastir` ve `rapor` birer job olarak çalışır. `dedup_key` = komut + girdi özeti + gün.
2. Scalable oturum hatası → `waiting_auth` ve `masa giris` yönlendirmesi; otomatik tekrar deneme yok.
3. 429/limit → `waiting_quota`; sağlayıcının bekleme süresine uyulur, üstel geri çekilme + jitter.
4. Tek uçuş: aynı anda tek `sc` çağrısı (dosya kilidi `var/private/sc.lock`).
5. `masa durum`: son işler, durumları, bekleyenler.
6. Yayın atomikliği: rapor önce geçici dosyaya yazılır, doğrulama geçince yeniden adlandırılır. Yarım rapor görünmez.

**Kabul testleri**

- Çökme sonrası `recover_in_flight_jobs` + aynı işin ikinci kez kayıt üretmemesi.
- `waiting_auth` iken veri komutu bekler.
- Eşzamanlı iki `veri` çağrısından biri kilitte bekler.

---

### İP-9 · Statik HTML pano (Faz 1 "ilk statik pano"; tasarım §2.4)

**Amaç:** Markdown rapora ek olarak, mevcut koyu panonun (`ETF/reports/index.html`, `.agents/skills/portfolio-intelligence/scripts/render_html.py`) yerini alan tek sayfalık statik pano.

**Yapılacaklar**

1. `masa pano` → `masa/var/reports/pano.html`. Dört alan (tasarım §2.4):
   - Bugün ve veri durumu,
   - Portföy ve sepet,
   - Araştırma,
   - Tez ve sonuç geçmişi.
2. Güvenlik:
   - Tüm metin HTML-escape edilir; URL'ler doğrulanır.
   - Uzak betik, font veya izleme yok; grafikler yerel SVG.
   - Sayfa "canlı" iddiası taşımaz; üretim ve kotasyon zamanlarını gösterir.
3. Veri yalnız mühürlerden. Pano üretimi `rapor` ile aynı veri nesnelerini kullanır; ayrı hesap yapmaz.
4. Eski `./etf` komutu ve 34 eski test bozulmaz.

**Kabul testleri**

- XSS denemesi içeren ad/açıklama (`<script>`) kaçışlanır.
- Sayfada dış kaynak URL'si yok.
- Pano değerleri rapor değerleriyle aynı.

---

### İP-10 · Güvenlik sertleştirmesi

1. **gitleaks:**
   - `ETF/.gitleaks.toml`'a IBAN (DE..), Scalable hesap/portföy kimliği biçimi (22 karakter base62), e-posta ve kullanıcı adı soyadı kuralları ekle.
   - `masa tara` komutu, `gitleaks detect --redact` ile kod ve `var/reports` dışa aktarımlarını tarar.
   - gitleaks yoksa "kurulu değil" der, kurmaz.
2. **Rapor dışa aktarma:** `masa rapor --paylasim` ad, hesap kimliği ve tutarları maskeleyerek (ağırlıklar kalabilir) ayrı bir dosya üretir.
3. **OS izolasyonu (KARAR GEREKLİ, yalnız rehber):** Scalable oturumunun ayrı macOS kullanıcısında tutulması ve model/araştırma süreçlerinin `sc`'ye erişememesi için adım adım rehber yaz; **uygulamayı kullanıcı yapar.**
   - Ayrıca `sc login --local-read-only` önerisini `kontrol`'de göster.
   - Yapay zeka araçlarının izin ayarlarında `sc broker trade|savings-plans|watchlist add|...` komutlarının yasaklanması için örnek kurallar ver.
4. Dosya izinleri: `var/` 0700, dosyalar 0600. `kontrol` bunu doğrular.

---

### İP-11 · Açık orta öncelikli bulgular (denetim raporu bölüm 4)

1. **UCITS 5/10/40** (`calc/optimization.py`): bireysel ETF portföyünde anlamsız. Seçenekleri listele:
   - kaldır,
   - "look-through sonrası ihraççı yoğunlaşması" olarak yeniden tanımla (İP-4'e bağlı).
   Kararı kullanıcıya bırak.
2. **Faktör regresyonu** (`calc/valuation.py`): HAC (Newey-West) birincil çıkarım olsun; OLS ikinci.
   - Faktör veri kaynağı için kullanıcıya seçenek sun: Ken French "Developed"/"Europe" faktörleri (USD) + kur dönüşümü notu.
   - Kaynak onaylanmadan akışa bağlama.
3. **Optimizasyon modülü** akışa bağlı değil. Tasarım "onaylı hedef yok" dediği için bağlama; yalnız `masa senaryo` altında "senaryo" etiketiyle çalıştırılabilir yap (isteğe bağlı).
4. **Tarama puanı:**
   - z-skor ağırlıkları (`scanner.py`: 0.25/0.25/0.25/0.15/0.10) config'e (`politika.json` → `tarama.agirliklar`) taşınsın.
   - Hisse ve ETF ayrı sıralansın (farklı oynaklık ölçeği).
   - Az örnekli z-skor uyarısı eklensin.
5. **Seri örneklemesi:** `chart` ~2 günde bir nokta veriyor. Yıllıklaştırmanın gözlem sıklığıyla yapıldığı raporda yazıyor; ayrıca `1m`/`3m` serileriyle kısa vade oynaklığını karşılaştıran bir tutarlılık kontrolü ekle.

---

### İP-12 · Zamanlama ve bildirim (Faz 5; yalnız İP-1…8 bittikten sonra)

1. macOS `launchd` plist üretici (`masa zamanla kur|kaldir|durum`): Europe/Berlin saatiyle günlük (Xetra seans sonrası, takvimden hesaplanan) `veri` + `rapor`, haftalık `tarama`, aylık `tez kontrol`.
   - Mac uykudayken kaçan işler bir kez, "geç çalıştı" etiketiyle çalışır.
   - **Kurulum kullanıcı onayıyla.**
2. Yerel macOS bildirimi (`osascript`):
   - yalnız yeni ve eyleme dönük değişiklikte (veri sorunu, tez tetikleyicisi, oturum süresi doldu),
   - aynı durum tekrar bildirilmez.
3. FastAPI arayüzü **bu aşamada yapılmaz**. İstenirse ayrı İP: yalnız loopback, oturum doğrulama, Origin/Host ve CSRF denetimi, tarayıcıdan serbest komut yok.

---

### İP-13 · Faz 6 (isteğe bağlı, kullanıcı ayrıca isterse)

- **Karne:** tamamlanan/toplam tahmin, ufuk ve benchmark bazında; küçük örneklem uyarısı.
- **DuckDB/Parquet:** yalnız seri hacmi ölçülüp gerekirse.
- **Vergi gölge defteri:** varsayılan KAPALI.
  - Açılırsa yalnız kullanıcının verdiği kişisel bilgilerle çalışır (medeni durum ve kalan Pauschbetrag).
  - Teilfreistellung, Vorabpauschale ve FIFO kuralları kaynakla (EStG/InvStG) belgelenir.
  - Banka belgesindeki gerçek kesinti ile sistem tahmini ayrı tutulur.
  - Vergi danışmanlığı iddiası yok.

---

## 3. KULLANICIDAN ALINACAK KARARLAR (başlamadan veya ilgili İP'de sor)

1. İP-1: yedek şifreleme yöntemi (FileVault / şifreli sparsebundle / harici disk).
2. İP-4: holdings dosyaları otomatik mi indirilsin, elle mi bırakılsın?
3. İP-6: SEC için ad + e-posta (edgartools `set_identity`); Gemini ücretsiz katmanının AB'de kullanımı onayı; LM Studio kullanılacak mı?
4. İP-5: `tezler.json` içe aktarılsın mı?
5. İP-11: UCITS kuralı kaldırılsın mı / yeniden tanımlansın mı; faktör veri kaynağı.
6. Genel: `politika.json` eşiklerini ONAYLANDI yapmak ve `portfoy.json`'a hedef ağırlık yazmak tamamen kullanıcının kararıdır. Sen önermezsin, yalnız alanları açıklarsın.

## 4. BİTİŞ TANIMI

Tasarım §5.5'teki son kabul denemesi uçtan uca geçmeli:

- aynı ham veriyle aynı hesaplar üretiliyor;
- yanlış ISIN/kur/tarih reddediliyor;
- iç alış dış nakit akışı sayılmıyor;
- eski fiyat güncel görünmüyor;
- maliyet kapısı quick/deep katmanları ve araç çağrılarını kapsıyor;
- desteklenmeyen iddia yayına geçmiyor;
- yeniden başlatmada aynı tahmin çoğalmıyor;
- kişisel veriler rapor dışa aktarımına sızmıyor;
- yedek geri yüklenebiliyor.

Her madde için hangi testin veya komutun bunu kanıtladığını gösteren bir tablo teslim et. Kanıtlanamayan
madde "açık" kalır.
