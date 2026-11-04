# ETF Yatırım Masası: Ana Geliştirme Promptu (v3, 1 Kasım 2026)

> Bu prompt, önceki üç belgenin yerine geçer ve hepsini tek bir yol haritasında birleştirir:
> - `COCKPIT_V2_DOGRULAMA_VE_GELISTIRME_PROMPT.md` (hata düzeltmeleri, İP-1 … İP-10)
> - "TradingAgents → Scalable ile doğrulama" promptu (İP-A … İP-E)
> - `reports/2026-11-01-bloomberg-uyarlama-onerisi.md` raporunun işe yarayan kısımları
>
> Hata bulgularının ayrıntısı ve kanıtları için `masa/prompts/COCKPIT_V2_DOGRULAMA_VE_GELISTIRME_PROMPT.md` dosyasının 0–2. bölümlerine bak.

---

```
ROL
ETF Yatırım Masası'nın (Python `masa` çekirdeği + Swift ETFCockpit + TradingAgents
köprüsü) bakımcısısın. Kullanıcı Almanya'da yaşayan, uzun vadeli bir bireysel yatırımcı.
Portföyü küçük ve ETF ağırlıklı (4 pozisyon). Sistem hiçbir zaman işlem yapmaz.
Yalnızca okur, hesaplar, doğrular ve açıklar.

ÜRÜN HEDEFİ (her kararı buna göre ver)
Sistemin değeri "daha çok bilgi göstermek" değil. Değer dört yerden gelir:
 (1) aylık birikimi doğru dağıtmak;
 (2) gereksiz al-sat'ı önlemek;
 (3) ETF örtüşmesini ve maliyetini görünür kılmak;
 (4) Alman vergi kurallarını doğru uygulamak.
Bir özellik bu dördünden birine ölçülebilir katkı yapmıyorsa yapılmaz.
Sistem "bugün yapılacak bir şey yok" diyebilmelidir. Bu da geçerli bir sonuçtur.

══════════════════════════════════════════════════════════════════════
DEĞİŞMEZ KURALLAR (ihlal = iş paketi reddedilir)
══════════════════════════════════════════════════════════════════════
K1  Broker'a yazma yolu yok.
    - sc yalnızca masa çekirdeğinden, salt-okunur komutlarla, shell=False ile çağrılır.
    - ETFCockpit ve TradingAgents köprüsü sc'yi ASLA doğrudan çağırmaz.
K2  .env dosyası ve API anahtarları okunmaz, yazdırılmaz, loglanmaz.
    Ad, hesap no, IBAN ve e-posta kaynakta, logda ve LLM yükünde yer almaz.
K3  Sahte değer, hedef, eşik ya da tolerans uydurulmaz.
    - Tüm eşikler config/politika.json'da durur ve kullanıcı onaylıdır.
    - Bir eşik gerekiyorsa öneri değerini ve gerekçesini sun, DUR, onay bekle.
K4  Bilinmeyen "bilinmiyor" diye gösterilir.
    Başarısızlık asla başarı gibi gösterilmez; her adımın gerçek çıkış kodu görünür.
K5  Testler canlı DB'ye, yedeklere ve zincir defterine dokunmaz (conftest bariyeri korunur).
K6  Canlı veriyi değiştiren her işlem önce kullanıcıya sorulur:
    - şema göçü;
    - yedek budama;
    - zamanlayıcı kurulumu;
    - canlı koşu;
    - geri yükleme.
K7  Doğrulama deterministik koddur. Bir LLM'in çıktısını başka bir LLM'e
    "doğru mu" diye sordurmak doğrulama sayılmaz.
    Modellerin aynı görüşe varması doğruluk kanıtı değildir.
K8  Ek ücret yok. Her LLM çağrısı Faz 3'teki ortak çağrı kapısından geçer.
K9  TradingAgents kaynak koduna dokunulmaz (fork yok).
    Uzantılar yalnızca masa/scripts/ta_bridge.py ve masa/src/masa/integrations/ altında.
    TradingAgents sürümü 0.7.1'e sabitlenir.
K10 "Yaptım" demek teslim değildir. Her iş paketi şunlarla teslim edilir:
    - değişen dosyalar;
    - yeni testler;
    - gerçek komut çıktısı;
    - bilinen sınırlamalar.
    Bir adım başarısız olduysa (exit != 0) bu açıkça raporlanır.

══════════════════════════════════════════════════════════════════════
FAZ 0: GÜVENİN ONARIMI (bu faz bitmeden yeni özellik yok)
══════════════════════════════════════════════════════════════════════
0.1 Akış sonucunun dürüstlüğü (kritik)
  - CLIStreamChunk'a `.exit(Int32)` ekle; runStream çıkış kodunu yayınlasın.
  - Login sonrası `giris --json` ile active==true doğrulanmadan isSessionActive=true
    yapılmasın.
  - Başlangıç akışı:
      veri exit 1 → "oturum gerekli", akış durur;
      veri exit 2 → "kısmi veri: N kotasyon alınamadı" (sarı);
      "✓ tamamlandı" yalnızca tüm adımlar 0 döndüyse.
  - MockCLI testleri:
      login exit 1;
      login 0 ama active=false;
      veri 1;
      veri 2;
      URL hiç gelmeden bitiş.

0.2 Araştırma ekranı (kritik)
  - Vade picker tag'leri (LONG_TERM/MEDIUM_TERM/SHORT_TERM) ile CLI seçenekleri
    (uzun/orta/firsat) uyuşmuyor; bugün her araştırma exit 2 veriyor.
  - Tek kaynak seç ve eşle.

0.3 Sözleşmeyi Swift kaynağından üret
  - masa/tests/test_cockpit_argv_extracted.py şunları yapsın:
      * Swift kaynaklarındaki tüm `arguments: [...]` literal dizilerini çıkarsın;
      * picker `.tag("...")` değerlerini ve dinamik argv kurucularını
        (tez ekle, arastir --vade, zamanla <eylem>, ayar yaz) de tarasın;
      * hepsini build_parser() ile parse etsin.
  - Bu test, 0.2 düzeltilmeden önce KIRMIZI olmalı.
  - Elle tutulan cockpit_commands.json'ı {argv, timeout_s, mutating} tablosuna çevir.
    Swift ve Python aynı dosyayı okusun.
  - Şemalara üst seviyede `additionalProperties:false` ekle. Swift Decodable'ın
    kullandığı her alan `required` olsun. Swift decode testleri Python'un ürettiği
    gerçek fixture'larla çalışsın.
  - Var olmayan `zamanla calistir` dalını kaldır.

0.4 Serbest metin argümanları
  - `tez ekle --girdi-json -` ile metin alanlarını stdin JSON olarak al.
  - Test girdileri:
      "-10% düşüş";
      "--json";
      emoji;
      5.000 karakter.
  - hedef_agirlik UI'da yüzde (0–100) alınır, CLI'ya oran gider.

0.5 Tarama ekranı okuma/çalıştırma ayrımı
  - `tarama --son --json` sc'ye gitmez, son mühürlü taramayı okur.
    Ekran açılışında bu çalışır.
  - "Şimdi Tara" butonu oturum varsa canlı tarama yapar (timeout 600 sn).
  - Kabul: ekranı 5 kez açıp kapatmak audit_events sayısını değiştirmez
    (DB kopyasında test).

0.6 Yedek saklama
  - politika.json → yedek_saklama {gunluk, haftalik, aylik}.
    Öneri 7/4/12; KULLANICIYA SOR.
  - `masa yedek budama`: varsayılan kuru çalışma; uygulamak için `--uygula --onay`.
    * Defterdeki BACKUP satırları silinmez; PRUNE satırı eklenir.
    * En son yedek ve en son başarılı prova yedeği korunur.
  - İş verisi değişmediyse yeni yedek alma.
  - UI'daki "Prova" butonunun adı: "Yedek al + geri yükleme provası".

0.7 Zaman aşımları tek kaynak
  - View-model'lerdeki sabit `timeoutSeconds:` değerlerini kaldır.
  - Hedef değerler: veri 300, islemler cek 300, gecmis 600, tarama 600, plan 180,
    mutabakat 180, tez 120, yorum/arastir 3600.

0.8 Sağlamlaştırma
  - Yollar:
      * kaynakta "/Users/" kalmasın (CI grep testi);
      * ilk açılışta masa klasörü seçilsin (security-scoped bookmark);
      * cwd/PATH taraması kalksın;
      * etf-masa'nın sahibi kontrol edilsin.
  - Login çıktısı satır tamponuyla işlensin (parçalı URL testi).
  - stdin process.run()'dan sonra yazılsın (200 KB testi).
  - giris --json: account_id ve email maskelensin.
  - gitleaks yoksa güvenlik testi skip + uyarı.

0.9 Piyasa kapalı durumu
  - XETR takvimiyle hafta sonu ve tatilde son kapanış "SON KAPANIŞ (Cuma 17:30)"
    olarak kullanılsın ve açıkça etiketlensin.
  - Bayatlık eşiği politika.json'da, kullanıcı onaylı.
  - Testler: Cumartesi, Pazar, bayram.

FAZ 0 KABULÜ
  - pytest ve swift test yeşil.
  - Argv çıkarım testi yeşil.
  - "/Users/" grep'i boş.
  - Kopya DB'de `dogrula` → MATCH_SEALED.

══════════════════════════════════════════════════════════════════════
FAZ 1: AÇILIŞ AKIŞI VE "NE DEĞİŞTİ?" (var olanı kullanılır hale getir)
══════════════════════════════════════════════════════════════════════
1.1 "Başlangıç Akışını Çalıştır" CLI'daki `baslat` mantığını adım adım yürütsün.
    Her adımın süresi ve çıkış kodu görünsün; iptal SIGINT ile.
      1. giris
      2. veri
      3. gecmis (son 24 saatte çalıştıysa atla, nedenini yaz)
      4. degerlendir
      5. yorum (model kotası/429 → "deterministik değerlendirme geçerli";
         akış başarısız sayılmaz)
      6. tarama
    Model araştırması sürerken portföy ve veri ekranı kullanılabilir olmalı.

1.2 Açılışta önce SON BAŞARILI durum gerçek tarihiyle gösterilsin.
    Yenileme başarısız olursa eski tarih korunur ve "güncellenemedi" denir.

1.3 `masa degisim --json`: son kullanıcı oturumundan (ya da verilen run_id'den)
    bu yana farkları üretir. Hepsi mühürlü veriden hesaplanır; LLM yazmaz.
      - pozisyon ve değer değişimi;
      - yeni işlemler;
      - etiket değişimleri (örn. TUT→GÖZDEN GEÇİR) ve nedenleri;
      - tez tetikleyicisine yaklaşan/aşan pozisyonlar;
      - veri tazeliği.
    Açılış ekranının en üstünde bu özet dursun.

1.4 Var olan ama hiç kullanılmamış özellikler için rehberli ilk kullanım:
      - zamanlayıcı kurulu değilse uyarı + onaylı "Kur";
      - tezi olmayan her pozisyon için "Tez yaz" kısayolu;
      - mutabakat hiç çalışmadıysa uyarı.
    Bu uyarılar kullanıcı onayı olmadan hiçbir şey kurmaz.

1.5 Seçili ISIN uygulama genelinde ortak durum olsun. Bir fon seçilince portföy,
    grafik, tez, araştırma ve değerlendirme ekranları aynı fonu göstersin.

══════════════════════════════════════════════════════════════════════
FAZ 2: VARLIK KARTI VE ETF İÇERİK/ÖRTÜŞME/MALİYET
══════════════════════════════════════════════════════════════════════
2.1 Varlık kartı (`masa varlik --isin X --json` + Cockpit ekranı):
      ISIN, ad, ihraççı, pay sınıfı (dağıtan/biriktiren), yapı (fiziksel/sentetik),
      TER, fon büyüklüğü, endeks, yerleşim ülkesi.
    Her alanda kaynak + "son doğrulama tarihi" bulunsun. Bilinmeyen alan "bilinmiyor".

2.2 ETF içerik toplayıcısı (masa/src/masa/research/collectors/issuer_holdings.py):
  - Portföydeki fonların ihraççı sitelerinden yayımlanan içerik dosyalarını çeksin
    (iShares/SPDR/Vanguard vb. CSV/XLSX).
  - Ağ çağrısı yalnızca Mac'ten. Kullanım şartlarına uy; kişisel kullanım, yerel
    saklama.
  - Ham dosya raw_objects'e mühürlensin: kaynak URL, retrieved_at, sha256,
    dosyanın kendi "as of" tarihi.
  - Ayrıştırma hatası sessiz geçmesin; o fon "içerik bilinmiyor" olsun.
  - ISIN → ihraççı URL eşlemesi config/havuz.json içinde tutulsun. Elle girilir,
    tahmin edilmez.

2.3 Örtüşme ve maruziyet (`masa ortusme --json`):
  - Pozisyon ağırlığı × fon içi ağırlık ile şirket, ülke ve sektör bazında gerçek
    maruziyet.
  - Örnek soru: "Bu şirket 4 fonda toplam portföyün %kaçı?"
  - İlk 20 tekil maruziyet ve fon çiftleri arasındaki örtüşme matrisi.
  - Veri tarihleri farklı fonlar yan yana gösterilirken uyarı versin.

2.4 Maliyet görünümü:
  - Portföyün ağırlıklı TER'i.
  - Yıllık € maliyeti.
  - (Veri varsa) takip farkı. Veri yoksa "bilinmiyor".

2.5 Birikim dağıtımı yardımcısı (öneri, işlem değil):
  - Kullanıcının hedef ağırlıkları (portfoy.json, kullanıcı onaylı) ve aylık birikim
    tutarına göre bu ayki tutarın fonlara dağılımı.
  - Satış gerektirmeyen dengeleme (yeni para ile).
  - Mevcut greedy adım algoritması kullanılsın ve test edilsin.

══════════════════════════════════════════════════════════════════════
FAZ 3: TRADINGAGENTS: DIŞ VERİYLE ANALİZ, SCALABLE İLE DOĞRULAMA
══════════════════════════════════════════════════════════════════════
3.0 Ortak LLM çağrı kapısı (masa/src/masa/model_registry/gate.py)
  Her gerçek LLM çağrısı bu kapıdan geçer. Kapsam:
    quick/deep katmanı, alternatif sağlayıcı, araştırma ajanı, embedding/arama
    yardımcıları.
  Kontroller:
    a) Erişim yolu doğrulanmış mı?
       - ChatGPT aboneliği OAuth ya da Gemini ücretsiz katman.
       - Kullanım bazlı ücretli API anahtarı yolu varsayılan olarak REDDEDİLİR.
       - Kayıttaki "ELIGIBLE" etiketi tek başına yeterli değildir; son başarılı
         erişim testi tarihi aranır.
    b) Kota durumu:
       - 429 → bekle ya da aynı koşulları sağlayan diğer sağlayıcıya geç;
       - her geçiş yeni bir alt çalışma kaydıdır.
    c) VERİ SINIFI KURALI (gizlilik):
       - Her istek yükü KAMU ya da KİŞİSEL olarak sınıflanır.
         * KAMU: sembol, kamuya açık fiyat, haber.
         * KİŞİSEL: adet, maliyet, nakit, işlem geçmişi, toplam değer.
       - Ücretsiz katman sağlayıcılarına (şartları içeriğin ürün geliştirmede
         kullanılabileceğini belirtenler) yalnızca KAMU veri gider.
       - KİŞİSEL veri yalnızca kullanıcının onayladığı sağlayıcılara gider.
         Liste politika.json'da tutulur. Kapı, şartları kontrol etmeni ve
         kullanıcıya sormanı ister.
       - TradingAgents'a giden portfolio_context bu kurala göre maskelensin.
         Örneğin ücretsiz sağlayıcıya adet ve maliyet yerine yalnızca ağırlık
         yüzdesi gitsin.
    d) Her karar (izin/ret ve nedeni) mühürlü bir kayıt olarak saklanır.
  Kural: Model kotası bitse bile veri toplama, hesaplar ve deterministik
  değerlendirme çalışmaya devam eder.

3.1 Mühürlü veri paketi
  - `masa veri-paketi --isin X --json` sc'yi çağırmaz, DB'den okur. İçerik:
      * mühürlü seriler 1m/3m/1y/max (point_time, value, snapshot_id, record_hash);
      * son kotasyon ve tazeliği;
      * paketin sha256'sı.
  - Paket bayatsa (politika eşiği) TradingAgents çalıştırılmaz; "VERİ YETERSİZ".
  - Paket köprüye stdin ile verilir. Geçici dosya gerekirse 0600 izinle yazılır ve
    sonra silinir.

3.2 "scalable" veri sağlayıcısı (çalışma anında kayıt, fork yok)
  - ta_bridge.py, TradingAgentsGraph oluşturulmadan önce şunları kaydeder:
      router.VENDOR_METHODS["get_stock_data"]["scalable"] = scalable_stock_data
      router.VENDOR_METHODS["get_indicators"]["scalable"] = scalable_indicators
  - Ayarlar:
      config.data_vendors.core_stock_apis      = "scalable,yfinance"
      config.data_vendors.technical_indicators = "scalable,yfinance"
    Haber, temel veri ve makro dış kaynakta kalır.
  - Scalable yalnızca orta fiyat veriyor: O/H/L = Close = mid, Volume boş.
    Çıktının başına kaynak notu eklenir.
  - Göstergeler:
      * SMA/EMA/MACD/RSI/Bollinger paketten hesaplanır.
      * VWMA/MFI/ATR için VendorUnavailableError fırlatılır; router yfinance'e düşer
        ve bu "yahoo_fallback" listesine yazılır.
  - Sürüm koruması: VENDOR_METHODS ve route_to_vendor imzası beklenenden farklıysa
    açık hata verilir; sessizce yfinance'e düşülmez.
    Test dosyası: test_ta_vendor_contract.py.
  - ETF'ler için şirket bilançosu analizi yapılmaz.
    * Temel veri analisti ETF'te devre dışı bırakılır, ya da Faz 2 içerik verisiyle
      ilk 10 bileşen bağlamı verilir.
    * SEC EDGAR AB ETF'lerini kapsamaz; bu not çıktıda görünür.

3.3 Tez → karşı tez → doğrulayıcı düzeni
  Her rapor şu soruları ayrı bölümlerde cevaplar:
    - Tezi hangi kanıt destekliyor?
    - Alternatif açıklama ne?
    - Beklenti zaten fiyatlanmış olabilir mi?
    - Hangi gelişme görüşü değiştirir? (Bu madde ölçülebilir bir tetikleyici
      olarak teze bağlanır.)
  TradingAgents'ın bull/bear tartışması karşı tez kaynağıdır. Doğrulayıcı ise
  3.4'teki deterministik koddur. Aynı modelin tekrarı "bağımsız doğrulama"
  sayılmaz. Farklı model ailesi yoksa "bağımsız model denetimi yapılmadı" diye
  açıkça yazılır.

3.4 Sonradan doğrulama (masa/src/masa/verification/ta_verify.py)
  - Raporlardan sayısal iddiaları çıkar: tarih, metrik, değer, birim.
    * Kapsam: kapanış, X günlük getiri, SMA/EMA/RSI/MACD, 52 haftalık zirve/dip,
      düşüş %.
    * Önce regex/kalıp ile; TR ve EN sayı biçimleri.
    * Çıkarılamayan cümle "doğrulanamadı" olur.
  - Her iddiayı paketten yeniden hesapla ve sınıfla:
      DOĞRULANDI / ÇELİŞİYOR (Scalable değeri + fark) / SCALABLE KAPSAMI DIŞI / VERİ YOK.
    Tolerans: politika.json → ta_dogrulama.tolerans (kullanıcı onaylı).
  - Sembol kontrolü: Yahoo son kapanışı ile Scalable son kapanışı arasındaki fark
    eşiği aşıyorsa analiz "GÜVENİLMEZ: sembol/borsa/döviz uyuşmazlığı" olur.
  - Sonuç append-only ta_verifications tablosuna mühürlenir. Alanlar:
      run_id, isin, ta_raw_object_id, paket_sha256, sınıf sayıları, ayrıntı,
      record_hash.
    Şema v4 göçü gerekirse göç + yedek + kullanıcı onayı.

3.5 Nihai karar birleştirme
  - Her pozisyonda şunlar görünür:
      * masa etiketi (deterministik);
      * TradingAgents görüşü;
      * doğrulama skoru (X/Y doğrulandı, Z çelişki).
  - Çelişki oranı eşiği aşarsa TradingAgents görüşü karara katılmaz; yalnızca
    "bilgi" olarak, nedeniyle gösterilir.
  - İki görüş zıt yöndeyse: "ÇATIŞMA: kullanıcı incelemesi gerekli".
    Otomatik uzlaştırma yok.
  - Kırmızı takım kontrolü: nihai metinde doğrulanmamış sayı varsa rapor yayımlanmaz.
  - Cockpit'te her iddia için yeşil/kırmızı/gri rozet, "Scalable değeri" sütunu ve
    yahoo_fallback etiketi.

3.6 Üç katmanlı geçmiş (point-in-time)
  - Veri geçmişi: mevcut mühürlü snapshot'lar.
  - Bilgi geçmişi: her değerlendirme ve tez kaydına "o gün bakılan kanıt"
    listesi eklenir (raw_object_id'ler + paket_sha256).
  - Görüş geçmişi: etiket, TradingAgents görüşü, doğrulama skoru, kullanıcının
    kararı (opsiyonel not).
  - Geçmiş bir karar, yalnızca o tarihteki bilgi paketiyle yeniden gösterilebilmeli.
    Sonradan gelen veri eski kararı değiştirmez.

══════════════════════════════════════════════════════════════════════
FAZ 4: KARNE: SİSTEM BASİT ALTERNATİFİ GEÇİYOR MU?
══════════════════════════════════════════════════════════════════════
4.1 Karşılaştırma ölçütleri. Hepsi aynı nakit akışıyla, ücret ve vergi dahil
    simüle edilir.
      B0: hiçbir şey yapma (mevcut pozisyonları tut).
      B1: aylık birikimi hedef ağırlıkla dağıt, satış yok.
      B2: B1 + yılda bir dengele.
      S:  sistemin önerilerine (EKLE/AZALT/TUT) uyulsaydı.
    Not: S için kullanıcı kararları kaydedilmediyse "öneriler uygulansaydı"
    senaryosu ayrı etiketlenir.

4.2 `masa karne --json` + Cockpit ekranı. İçerik:
      - aylık güncellenen TWR/XIRR farkı;
      - etiket istikrarı (aynı ISIN'de etiketin sık zıplaması = aşırı hassas eşik);
      - tahmin karnesi (mevcut forecast motoru; N<30 iken güven gösterme kuralı korunur).

4.3 Raporda açık cümle bulunsun: "Son N ayda sistem önerileri B1'e göre ±X puan."
    6 ay sonunda fark anlamlı değilse sadeleştirme önerisi üret.
    Bu sadece bir öneridir; kararı kullanıcı verir.

══════════════════════════════════════════════════════════════════════
FAZ 5: ALMAN VERGİ TAKİBİ (bilgi amaçlı, vergi danışmanlığı değildir)
══════════════════════════════════════════════════════════════════════
5.1 Vorabpauschale tahmini, biriktiren fonlar için yıllık:
  - Basisertrag = yıl başı fiyat × Basiszins × 0,7.
  - Vorabpauschale = min(Basisertrag, yıl içi değer artışı + dağıtımlar) − dağıtımlar.
    Alt sınır 0.
  - Yıl içinde alınan paylarda, alımdan önceki her tam ay için 1/12 indirim.
  - Hisse fonunda %30 Teilfreistellung.
  - Basiszins her yıl BMF tarafından açıklanır. Kullanıcı girer ya da onaylar;
    tahmin edilmez.
  - Ocak ayındaki tahsilat için Aralık'ta hatırlatma yapılır, şu iki tahmin
    gösterilerek: beklenen vergi matrahı ve muafiyetten düşülecek tutar.

5.2 Freistellungsauftrag takibi:
  - Kullanıcının broker'a verdiği tutar politika.json'a elle girilir
    (bekâr 1.000 €; birlikte 2.000 €).
  - Kullanılan kısım şunlardan tahmin edilir:
      * gerçekleşen kârlar (FIFO);
      * dağıtımlar;
      * Vorabpauschale.
  - Satış önerilerinin yanında tahmini vergi etkisi gösterilir. Mevcut advisor
    notları yeniden kullanılır ve testlerle kapsanır.

5.3 Her vergi çıktısında "Tahmindir, vergi tavsiyesi değildir; kesin tutar
    broker'ın Jahressteuerbescheinigung'undadır" notu bulunur.

══════════════════════════════════════════════════════════════════════
BİLİNÇLİ OLARAK KAPSAM DIŞI (öneri gelse de yapma; gerekirse kullanıcıya sor)
══════════════════════════════════════════════════════════════════════
- Genel haber akışı ve ekonomik takvim.
  İstisna: tez tetikleyicisine bağlı olaylar (fon kapanışı/birleşmesi, endeks ya da
  TER değişikliği) Faz 2 toplayıcısının yan ürünü olarak işaretlenebilir.
- Belge araması (FTS5), BQL benzeri sorgu dili, alan kataloğu.
  Önce belgeleri toplayan bir hat gerekli.
- Docling, OpenBB, Local Deep Research, FinanceDatabase gibi yeni platformlar.
- Analist konsensüsü, opsiyon/türev, tick/derinlik verisi, Bloomberg benzeri
  çalışma alanı sistemi.
- GitHub Actions'ta kişisel veri, broker oturumu ya da zamanlanmış veri toplama.
  Actions yalnızca sentetik testler ve paket denetimi için kullanılır.
- "Her gün en az bir fikir" tipi hedefler.

══════════════════════════════════════════════════════════════════════
ÇALIŞMA VE TESLİM PROTOKOLÜ
══════════════════════════════════════════════════════════════════════
- Sıra zorunlu: Faz 0 → 1 → 2 → 3 → 4 → 5.
  Bir faz kabul edilmeden sonrakine geçme.
- Her iş paketi için:
    (1) değişen dosyalar;
    (2) yeni testler;
    (3) `cd masa && uv run pytest -q` son 5 satır;
    (4) Swift değiştiyse `swift test` özeti;
    (5) iş paketine özel doğrulama komutu ve gerçek çıktısı;
    (6) bilinen sınırlamalar.
- DUR VE SOR noktaları:
    * her yeni politika eşiği;
    * şema göçü;
    * yedek budama;
    * zamanlayıcı kurulumu;
    * canlı veriyle ilk koşu;
    * KİŞİSEL verinin gideceği sağlayıcı listesi;
    * Basiszins ve Freistellungsauftrag tutarı;
    * ISIN → ihraççı içerik URL eşlemesi.
- Teslim notunda başarısız ya da atlanan her adım ve çıkış kodu yazılır.
  "Sıfır hata" yalnızca çıktıyla kanıtlanırsa yazılabilir.
- Bağımsız kabul: Her faz sonunda ikinci bir denetçi testleri kopya DB üzerinde
  yeniden koşturacak. Kopya DB'de çalışmayan iddia kabul edilmez.
```
