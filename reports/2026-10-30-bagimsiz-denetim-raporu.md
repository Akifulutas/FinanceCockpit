# Yatırım Masası — Bağımsız Kod ve Tasarım Denetimi

**Tarih:** 30.10.2026 · **Kapsam:** `masa/` (src, tests, schema), `ETF/tests`, canlı rapor, `masa.db`, nihai tasarım belgesi
**Yöntem:** Kod okundu; testler ayrı bir Python 3.13 ortamında yeniden çalıştırıldı; iddialar küçük kanıt betikleriyle (sentetik veri) tek tek sınandı. Hiçbir proje dosyası değiştirilmedi.

> Not: Denetim promptunu hazırlayan model, sonucun "satır satır onaylanacağını" öngörmüş. Bu denetim onay değildir. Sağlam temeller var, ama tasarımın Faz 1 çıkış koşullarından birkaçı karşılanmıyor ve "mühür" iddiası şu hâliyle doğru değil.

---

## 0. Yönetici özeti

| Alan | Hüküm |
|---|---|
| Testler | 85 + 34 = **119 test geçiyor** (doğrulandı). Ancak 34'ü eski `.agents` terminalini test ediyor; hesap/araştırma modüllerinin (~6.700 satır) **doğruluk testi yok**. |
| ISIN Luhn, XETR takvimi | **Doğru.** |
| SQLite TRUNCATE, FK, tetikleyiciler | Ayarlar doğru; ancak tetikleyiciler `INSERT OR REPLACE` ile **atlatılabiliyor**. |
| SHA-256 hash zinciri | **Veriyi korumuyor:** doğrulayıcı alt kayıt hash'lerini yeniden hesaplamıyor. Mühürlü fiyat değiştirildi, doğrulama yine "geçerli" dedi. |
| Tekrar başlatma (idempotency) | **Ters çalışıyor:** ilk çalıştırmadan sonraki her `veri` mühürü sessizce atılıyor. |
| Canlı rapor | Aritmetiği tutarlı; ama **mühürlü veriden üretilmiyor**, sistem durumu satırları sabit metin, vergi satırı yanlış. |
| Broker güvenliği | Kodda yazma yolu yok (doğru). Gerçek sınır ise oturumu açık `sc` CLI'nin kendisi; tasarımdaki `--local-read-only` ve "shell'siz model" koşulları uygulanmamış. |
| Finansal matematik | Performans (MD/TWR/XIRR/FIFO/WAC) ve look-through test ettiğim durumlarda **doğru**. Yeniden dengeleme ve ücret muamelesinde mantık hataları var. |

---

## 1. Doğrulanan ve sağlam olanlar

- **Testler:** `masa/tests` 85 geçti (9 dosya), `ETF/tests` 34 geçti. Toplam 119.
- **ISIN (ISO 6166 Luhn):** IE00B3YLTY66, IE00BKM4GZ66, IE00BP3QZ825, IE00BP3QZB59, US0378331005, DE0007164600 geçerli; check digit'i bozulmuş varyantlar reddedildi.
- **XETR takvimi:** 24.12, 31.12, 1.5 ve Kutsal Cuma 2026 kapalı; 30.10.2026 kapanışı 17:30 CET (16:30 UTC). Rapordaki "KAPALI" doğru (16:51 UTC).
- **SQLite:** her bağlantıda `journal_mode=TRUNCATE`, `foreign_keys=ON`, `synchronous=FULL`; 6 tabloda 12 adet `BEFORE UPDATE/DELETE` tetikleyicisi var.
- **`sc_reader.py`:** `shell=False`; argv sabit (`[sc, "broker", <beyaz liste>, "--json", ...]`); alt komut yalnız holdings / cash-breakdown / quote / transactions'a eşleniyor; tek ISIN zorunlu; JSON `parse_float=Decimal`. **Kodda alım, satım, emir, iptal veya Sparplan yolu yok.**
- **`performance.py`:** test ettiğim durumların hepsinde doğru sonuç verdi:
  - Akışsız +%10: MD = TWR = %10.
  - Dönem ortasında 5.000 € yatırım ve akış öncesi değerleme: TWR %11,774 (beklenen 1,05 × 16.500/15.500 − 1); MD %12,00 (beklenen 1.500/12.500).
  - 10@100 ve 10@120 alış, 10@130 satış (her işlemde 1 € ücret): FIFO gerçekleşen 298, WAC 198; kalan maliyet FIFO 1.201, WAC 1.101. Hepsi doğru. Almanya'da vergi FIFO'ya göre işlediği için FIFO'nun varsayılan olması da doğru.
- **`lookthrough.py`:** iki ETF'lik sentetik örnekte şirket ağırlıkları (Apple %38, Alphabet %32, Microsoft %30) ve örtüşme Σmin = 0,20 doğru. Alphabet A/C hisse sınıfları da birleştiriliyor.
- **Canlı rapor aritmetiği:** adet × mid, toplam 5.000,00 €, ağırlıklar ve makas yüzdeleri tutarlı.

---

## 2. KRİTİK bulgular

### K1 — Hash zinciri fiyat verisini korumuyor; tetikleyiciler atlatılabiliyor
- `HashChainEngine.verify_snapshot_chain()` alt tablolardaki **saklı** `record_hash` değerlerini okuyor, ama bunları `bid/ask/computed_mid` alanlarından **yeniden hesaplamıyor**. Bir fiyatı değiştirip hash'ine dokunmayan biri fark edilmiyor.
- `INSERT OR REPLACE` çakışan satırı siliyor. SQLite'ta `recursive_triggers` kapalıyken bu silme **DELETE tetikleyicisini çalıştırmıyor**.
- **Kanıt** (tetikleyiciler yerindeyken, sentetik DB):
  ```sql
  INSERT OR REPLACE INTO quotes(quote_id, ..., bid, ask, computed_mid, ..., record_hash)
  SELECT quote_id, ..., '50.00','50.02','50.01', ..., record_hash FROM quotes WHERE quote_id=1;
  ```
  Sonuç: mühürlü fiyat 11,60 → 50,00 oldu, `SnapshotStore.verify_integrity()` → `(True, None)`. `raw_objects` satırı da aynı yolla "forged" içerikle değiştirildi.
- Ek olarak hash'e girmeyen alanlar var. Kotasyonda spread, provider_mid, retrieved_at ve source; pozisyonda maliyet, birim fiyat ve ağırlık hash dışında kalıyor.
- **Düzeltme:**
  1. Doğrulayıcı her alt kaydın hash'ini alanlardan yeniden hesaplasın ve saklı değerle karşılaştırsın.
  2. Hash girdisi `canonical_json` ile tüm alanları kapsasın; `|` ile birleştirme kaldırılsın.
  3. `PRAGMA recursive_triggers=ON` açılsın ve `BEFORE INSERT` tetikleyicisiyle var olan PK veya UNIQUE değerine yazma reddedilsin. Alternatif: uygulama SQL'inde REPLACE/UPSERT yasaklansın, bunu bir test yakalasın.
  4. Tasarımın istediği bağımsız yedek manifesti (zincir ucunun dışarıda saklanması) eklensin. O olmadan zincirin tamamı yeniden yazılabilir.

### K2 — İlk `veri` çalıştırmasından sonraki tüm mühürler sessizce atılıyor
- `cmd_veri` ham kayıt olarak yalnızca `{"count": 4, "account_id": "..."}` saklıyor. Bu metin her çalıştırmada aynı, dolayısıyla SHA da aynı.
- `store_raw_object` eski `raw_id`'yi döndürüyor, `save_quote_snapshot` "bu raw_id için mühür zaten var" deyip **eski snapshot_id'yi döndürüyor**. Yeni fiyatlar yazılmıyor.
- **Kanıt:** iki çalıştırmada bid 11,60 ve 12,00 gönderildi. DB'de tek snapshot ve yalnız 11,60 kaldı. Gerçek `masa.db`'de de 1 snapshot, 4 quote var.
- Bu hata Faz 1 çıkış koşulu olan "**her fiyat ham kayda bağlı**" maddesini de karşılamıyor: ham kayıt broker JSON'u değil, iki alanlık bir özet.
- **Düzeltme:** `RawBrokerPayload.stdout_raw` her komut için (holdings, cash, her quote) ayrı ham nesne olarak saklansın. Tekilleştirme anahtarı `(source, payload_sha256)` olsun, mühür de bu ham nesnelerin listesine bağlansın.

### K3 — Rapor mühürlü veriden üretilmiyor; "sistem bütünlüğü" satırları sabit metin
- `cmd_rapor` DB'yi hiç açmıyor; fiyatları yeniden canlı çekiyor. 16:51:13'teki mühür ile 16:51:26'daki rapor farklı:

  | ISIN | Mühür bid/ask | Rapor bid/ask |
  |---|---|---|
  | IE00B3YLTY66 | 11,602 / 11,616 | 11,602 / 11,614 |
  | IE00BKM4GZ66 | 44,699 / 44,866 | 44,689 / 44,856 |
  | IE00BP3QZB59 | 69,97 / 70,24 | 69,98 / 70,13 |

  Yani "Fiyat Mühürleri" başlıklı tablodaki fiyatların hiçbiri mühürlü değil.
- Bölüm 4'teki "yazma yolu engelli", "TRUNCATE ve hash zinciri aktif" ve "vergi... korunmaktadır" satırları f-string içinde **sabit yazılmış**; hiçbir kontrol çalıştırılmıyor.
- Bölüm 3'teki etiketler (ACWI, EM, Momentum, Value) **sıra numarasına göre** atanıyor (`items[0]..items[3]`). Broker sırayı değiştirirse etiketler yanlış fona yapışır; 4'ten az pozisyonda `IndexError`, fazlasında eksik rapor çıkar. Hesap sahibinin adı da koda gömülü.
- **Düzeltme:** `rapor` yalnız belirtilen snapshot_id'den (varsayılan: son geçerli mühür) okusun. Bölüm 4'te `verify_integrity()` ve `PRAGMA journal_mode` gerçekten çalıştırılsın, sonuç yazılsın. Etiketler ISIN → rol eşlemesinden gelsin.

### K4 — Hesap ve araştırma modülleri sisteme bağlı değil ve test edilmemiş
- `calc/*` ve `research/*`, `cevaplar/` klasöründeki harici yanıtların **birebir kopyası** (diff: aynı). CLI veya başka hiçbir çekirdek modül bunları import etmiyor.
- Testleri: biri import, ikisi modüllerin kendi `_self_test`'i, biri de performans motorunda "sonuç None değil" kontrolü. Look-through, rebalancing, optimization ve valuation **hiç çağrılmıyor**. 119 testin bu ~6.700 satırla ilgili kısmı 4 test.
- `cevaplar/README.md` "entegre edip birim testlerini çalıştıracağım" diyor; yapılan iş kopyalamadan ibaret.
- Kapsam notu: tasarıma göre bu modüller Faz 2–6 işi, Faz 1 kapanmadan yazılmış. Tasarımın kendi cümlesi: "karmaşık optimizasyon MVP koşulu değildir".

---

## 3. YÜKSEK bulgular

### Y1 — Broker güvenlik sınırı Python sınıfında, işletim sisteminde değil
- Kodda yazma yolu yok, ama `sc` CLI tam yetkili bir oturumla açık. Aynı makinede shell erişimi olan herhangi bir süreç ya da yapay zeka aracı `sc broker ...` ile emir verebilir.
- Tasarım belgesi bunu açıkça istiyor: "ayrı kullanıcı/izin veya OS izolasyonu… bu sağlanana kadar model çalışanı araçsızdır, shell… verilmez." Sistem ise shell yetkili bir ajan tarafından, canlı oturumla kuruldu ve çalıştırıldı.
- **Düzeltme (aynı gün):** `--local-read-only` her komuta eklenen bir bayrak değil; sc 1.0.0'da `sc login --local-read-only` ile oturum seviyesinde açılan bir mod ("locally enforced read-only mode for GraphQL mutations"). İlk sürümdeki "her komuta ekleyin" önerim yanlıştı: öyle yapılsaydı komutlar hata verirdi. Doğrusu oturumu bu modla açmak.
- `binary_path` `PATH` üzerinden çözülüyor (`shutil.which("sc")`); tasarım sabit çalıştırılabilir yolu istiyor.
- **Düzeltme:**
  1. Oturumu `sc logout` + `sc login --local-read-only` ile salt-okunur açın (masa `giris` bunu yönlendirir).
  2. `binary_path`'i sabit mutlak yol yapın.
  3. Kullandığınız yapay zeka araçlarının izin ayarlarında `sc broker trade|order|savings*` komutlarını yasaklayın.
  4. Mümkünse Scalable oturumunu ayrı bir macOS kullanıcısında tutun.

### Y2 — Yeniden dengeleme: yeni nakit tolerans bandına takılıp yatırılmıyor
- Tolerans bandı yalnız satışları değil **yeni nakitle yapılacak alımları da** engelliyor.
- **Kanıt:** gerçek portföy, hedefler mevcut ağırlıklarda, bant %2 mutlak ve %10 göreceli, nakit hedefi %0:
  - **150 € Sparplan → 0 emir**, 150 € boşta kalıyor (her iki modda).
  - **500 € → 104 € boşta**; Value fonu "WITHIN_TOLERANCE_BAND" ile atlanıyor.
- Aylık Sparplan kullanan biri için ana senaryo bu; para yatırılmadan birikir.
- **Düzeltme:** `new_cash_injection` bant kontrolünden muaf olsun. Yeni nakit her zaman hedefin altındaki pozisyonlara açık oranında dağıtılsın; bant yalnız satış gerektiren işlemlere uygulansın. Scalable kesirli Sparplan destekliyorsa `quantity_step` buna göre ayarlansın.

### Y3 — Performans: broker ücretleri getiriden "kayboluyor"
- `BROKER_FEE` dış akış (para çekme) sayılıyor. Başka hiçbir şey olmadan 100 € ücret alındığında MD = TWR = XIRR = **%0** çıkıyor; gerçek net getiri −%1.
- Kişisel yatırımcı için anlamlı ölçü ücret sonrası (net-of-fee) getiri. Ücret dış akış değil, portföy içi gider olmalı. Ayrı bir "brüt" metrik istenirse onun yanında raporlanabilir.

### Y4 — Faz 1 veri teslimatları eksik
- `position_observations` ve `cash_observations` tabloları **hiç doldurulmuyor** (gerçek DB'de 0 satır); `save_position_snapshot` ve `save_cash_snapshot` CLI'den çağrılmıyor.
- `audit_events` 0 satır; `AuditEventLogger.log_event` hiçbir akışta kullanılmıyor.
- Tazelik kontrolü: `quality_status = "FRESH" if not q.is_outdated` ifadesinde `None` (bilinmiyor) da FRESH sayılıyor. `CalendarAdapter.assess_quote_freshness` yazılmış ama kullanılmıyor.
- `cmd_veri` mühür yazımı başarısız olursa yalnız uyarı basıp `0` (başarılı) ile çıkıyor. Fiyatı alınamayan pozisyon da toplamdan sessizce düşüyor.
- `cmd_veri` "Zincir Hash" diye **snapshot_id'yi** yazdırıyor (`save_quote_snapshot` hash değil id döndürüyor). Ekrandaki "hash" gerçek değil.

### Y5 — Rapordaki vergi satırı yanlış ve yanıltıcı
- 2026'da Sparer-Pauschbetrag **bekâr için 1.000 €, birlikte değerlendirilen eşler için 2.000 €**. Rapor koşulsuz "2.000 €" yazıyor.
- Vergi modülü tamamen pasif (`NotImplementedError`); "muafiyet sınırı dahilinde korunmaktadır" cümlesi gerçekte olmayan bir işlevi ima ediyor. Bu satır kaldırılsın ya da "vergi hesabı yapılmıyor" diye düzeltilsin.

---

## 4. ORTA ve DÜŞÜK bulgular

1. **UCITS 5/10/40 kavramsal olarak yanlış yerde.** Bu kural fon yöneticisinin tek ihraççıya maruziyetine uygulanır; ETF'lerden oluşan bireysel portföyde anlamsız. 4 ETF'lik portföyde her pozisyon ≤ %10 olunca en fazla %40 yatırılabilir; kural açıldığında problem çözümsüz kalır. Varsayılan kapalı, ama kaldırılmalı ya da "look-through sonrası ihraççı yoğunlaşması" olarak yeniden tanımlanmalı.
2. **XIRR yıl uzunluğu 365,25 gün.** Tam 365 günde +%10 için %10,007 veriyor; Excel ve broker'ların çoğu %10,000 verir. Kural belgelenmeli ya da 365'e (Excel XIRR) çekilmeli.
3. **Faktör regresyonu:** birincil çıkarım klasik OLS t-istatistiği, HAC yalnız uyarı metninde. Getiri serilerinde HAC (Newey-West) birincil olmalı. Ken French faktörleri USD bazlı; EUR'luk UCITS ETF'lerde kur etkisi ve EUR risksiz faiz ayrıca ele alınmalı. Veri yükleyici de yok.
4. **Rebalancing vergi rezervi** %26,375 sabit, Teilfreistellung (hisse ETF'lerinde %30) ve FIFO yok; ortalama kazanç oranıyla hesaplıyor. Kendi notunda yazıyor ve varsayılan kapalı; açılmadan önce düzeltilmeli.
5. **`FORBIDDEN_TOKENS` alt dize eşlemesi.** Broker'dan gelen sayfalama `cursor`'ında "rm", "put" veya "post" geçerse sayfalama rastgele "güvenlik ihlali" ile kırılır. Cursor ayrıca `--` ile başlayabilir (seçenek enjeksiyonu). Çözüm: cursor'ı regex beyaz listesiyle doğrulayıp `--cursor=<değer>` biçiminde geçirmek.
6. **Look-through'da veri kaynağı yok.** Fon sepetlerini (iShares/SPDR holdings dosyaları) yükleyen modül yok; motor pratikte kullanılamıyor. Çok sınıflı hisse birleştirme yalnız Alphabet için sabit kodlu.
7. **"Kayıpsız Decimal" iddiası kısmen doğru:** optimization ve valuation numpy float kullanıyor. Sayısal olarak kabul edilebilir, ama iddia düzeltilmeli. Calc modüllerindeki ISIN alanları Luhn ile doğrulanmıyor (yalnız uzunluk/regex).
8. **Kişisel veri:** `raw_objects` hesap kimliğini maskesiz saklıyor (şemada `account_id_masked` sütunu var, demek ki niyet maskelemekti). Kişisel rapor `masa/var/reports/` yerine `ETF/reports/` altına yazılıyor; tasarıma göre kişisel raporlar `var/` altında olmalı. Bu dosyaları başka yapay zekalara verirken ad ve hesap bilgisi de gider.
9. **Eşzamanlılık:** `prev_hash` okuması yazma kilidinden önce yapılıyor; iki süreç aynı anda yazarsa zincir çatallanabilir. `BEGIN IMMEDIATE` kullanılmalı. Tek kullanıcıda düşük risk.
10. **Ağırlık hesabı:** rapor `computed_mid` ile, `portfoy` komutu broker'ın `quote_mid_price`'ı ile değerleme yapıyor. İki komut farklı toplam gösterebilir; broker `valuation` alanıyla mutabakat da yapılmıyor.

---

## 5. Tasarım belgesine uyum (Faz 0 / Faz 1)

| Gereksinim | Durum |
|---|---|
| İzole uv projesi, `uv.lock`, `.python-version` | ✅ |
| Mevcut 34 testlik taban korunuyor | ✅ |
| ISIN / para birimi / yasak komut reddi | ✅ (ISIN, yasak komut); para birimi kısmen |
| XETR takvimi, belirsiz kaynakta Xetra varsayılmaması | ✅ adaptörde var · ❌ CLI kullanmıyor |
| TRUNCATE journal, UPDATE/DELETE tetikleyicileri | ✅ var · ⚠️ REPLACE ile atlatılıyor (K1) |
| SHA-256 hash zinciri | ⚠️ var ama veri değişikliğini yakalamıyor (K1) |
| Her fiyat ham kayda bağlı | ❌ (K2) |
| Tekrar başlatma veri çoğaltmıyor | ⚠️ çoğaltmıyor ama yeni veriyi de atıyor (K2) |
| Pozisyon ve nakit için tarihli gözlem | ❌ (Y4) |
| Denetim olayları | ❌ (Y4) |
| Broker yazma yolu yok | ✅ kodda · ⚠️ OS seviyesinde yok, `--local-read-only` eksik (Y1) |
| Bağımsız yedek manifesti | ❌ |

**Sonuç:** Faz 1 çıkış koşulları **karşılanmamış.** Önerim: Faz 2+ modülleri bekletip önce K1, K2, K3, Y1 ve Y4'ü kapatmak.

---

## 6. Diğer modele verilecek düzeltme talimatı (kabul testleriyle)

```text
Aşağıdaki hataları düzelt. Her madde için önce başarısız olan bir test yaz, sonra düzelt:

1. verify_snapshot_chain: her quote/position/cash satırının record_hash'ini alanlardan YENİDEN hesapla.
   Test: bir quote'un bid'ini değiştir (record_hash'e dokunma) -> verify False dönmeli.
2. Tetikleyici atlatma: PRAGMA recursive_triggers=ON + mevcut PK/UNIQUE'ye INSERT'i reddeden BEFORE INSERT
   tetikleyicileri. Test: INSERT OR REPLACE INTO quotes(...) aynı quote_id ile -> hata vermeli.
3. Ham kayıt: holdings, cash ve her quote için sc stdout'unu ayrı raw_objects satırı olarak sakla.
   Test: aynı gün iki farklı fiyatla iki kez `veri` -> 2 snapshot, 8 quote olmalı.
4. Pozisyon ve nakit mühürleri cmd_veri içinde yazılsın; her adımda audit_events kaydı düşülsün.
   Test: veri sonrası position_observations=4, cash_observations=1, audit_events>=3.
5. cmd_rapor yalnız mühürden okusun (--snapshot-id, varsayılan son geçerli mühür); bölüm 4'te
   verify_integrity() ve PRAGMA journal_mode gerçekten çalıştırılıp sonucu yazılsın; etiketler
   ISIN->rol eşlemesinden gelsin; ad ve vergi satırı koddan çıkarılsın.
   Test: rapordaki her fiyat DB'deki quote satırıyla birebir eşleşmeli.
6. sc_reader: binary_path sabit mutlak yol olsun, bayraklar beyaz listeyle ve değer doğrulamasıyla
   sınırlansın, cursor regex ile doğrulansın; oturum `sc login --local-read-only` ile açılsın.
   Test: '--evil' cursor ve '--confirm' reddediliyor.
7. is_outdated None ise quality_status 'UNKNOWN' olsun; assess_quote_freshness kullanılsın.
   Mühür yazımı başarısızsa exit code != 0.
8. rebalancing: new_cash_injection tolerans bandından muaf olsun.
   Test: hedefte duran portföy + 150 € giriş -> 150 €'nun (min ticket ve step sınırları içinde) tamamı alıma gitmeli.
9. performance: BROKER_FEE dış akış değil, getiriyi azaltan gider olsun.
   Test: 10.000 -> 9.900, tek olay 100 € ücret -> TWR ve MD ≈ -%1.
10. calc modülleri için her birine en az 5 bilinen-cevaplı test (el hesabıyla doğrulanmış) ekle.
```

---

## 7. Düzeltme durumu (30.10.2026 akşam)

Bulguların düzeltmesi `masa` v0.2 / şema v2'de yapıldı. 125 masa testi ve 34 eski test geçiyor.

| Bulgu | Durum |
|---|---|
| K1 hash zinciri / REPLACE | ✅ Kayıt özetleri tüm alanlardan; `dogrula` her satırı yeniden hesaplıyor; satır silme (item_count), ham veri değişikliği ve REPLACE (recursive_triggers + INSERT koruması, yabancı istemcide de) testle yakalanıyor |
| K2 mühürlerin atılması | ✅ Her sc komutunun stdout'u ayrı ham kayıt; yeni veri yeni mühür, aynı veri kopya üretmiyor; çalışma (run) bağları manifestte |
| K3 rapor mühürsüz | ✅ Rapor yalnız mühürden; bölüm 9'daki bütünlük satırları gerçek kontrol çıktısı; roller ISIN eşlemesinden, ad Scalable oturumundan |
| K4 bağlı olmayan modüller | ✅ performans (işlem geçmişinden TWR/MD/XIRR + FIFO karşılaştırması), rebalancing (plan), red-team critic (rapor denetimi) ve quantstats/risk akışa bağlandı; bilinen-cevaplı testler eklendi |
| Y1 broker sınırı | ✅ Sabit sc yolu, bayrak beyaz listesi, `giris` → `sc login --local-read-only` yönlendirmesi. ⚠️ OS seviyesinde ayrı kullanıcı hâlâ öneri |
| Y2 Sparplan nakdi | ✅ Yeni nakit bant dışında da düşük ağırlıklara gidiyor (150 € → alım) |
| Y3 ücretler | ✅ Ücret getiriden düşüyor (100 € ücret → −%1) |
| Y4 Faz 1 teslimatları | ✅ Pozisyon/nakit mühürleri, denetim olayları, UNKNOWN/AGED kalite, kısmi çalışmada çıkış kodu ≠ 0 |
| Y5 vergi satırı | ✅ "Hesaplanmıyor" + 1.000 €/2.000 € bilgisi |
| Orta-2 XIRR yılı | ✅ actual/365 (Excel) |
| Orta-5 cursor | ✅ Tam kelime eşleşmesi + regex; gerçek cursor biçimi (`…|…`) destekli |
| Orta-1 UCITS, Orta-3 HAC, Orta-6 look-through veri kaynağı | ⏳ Açık (varsayılan kapalı / bilgi amaçlı) |

## Kaynaklar
- [Sparerpauschbetrag 2026 (§ 20 Abs. 9 EStG) – 1.000 € / 2.000 €](https://nexvyra.de/fakten/sparerpauschbetrag-2026.html)
- [VLH: Sparer-Pauschbetrag](https://www.vlh.de/kaufen-investieren/abgeltungssteuer/sparer-pauschbetrag-kapitalertraege-sind-bis-zu-einer-bestimmten-grenze-steuerfrei.html)
- Proje içi: `reports/2026-10-30-nihai-yatirim-masasi-tasarimi.md` §2.3, §5.1, §5.4
