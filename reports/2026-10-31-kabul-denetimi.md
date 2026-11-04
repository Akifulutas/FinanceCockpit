# Kabul Denetimi — "13 İş Paketi Tamam" Beyanının Bağımsız Kontrolü (31.10.2026)

**Yöntem:** Kod okundu. 751 masa testi ve 34 eski test, ayrı bir Python 3.13 ortamında 4 parça hâlinde yeniden çalıştırıldı. Canlı `masa.db`, yedekler ve geri yükleme öncesi kopyalar salt-okunur incelendi. Ana akış (`baslat`), gerçek `sc` çıktı biçimleriyle (sahte `sc`) denendi. Canlı veriye ve koda dokunulmadı.

## Doğrulananlar
- Testler: **750/751 geçti**. Tek başarısız test gitleaks/ortam bağımlı; bu testin Mac'te geçip geçmediği doğrulanamadı. Eski testler 34/34 geçti. `uv lock --check` tutarlı (yeni bağımlılık: openpyxl, SPDR XLSX için).
- Broker güvenliği yerinde: yalnız okuma komutları kullanılıyor (`capabilities` ve `watchlist` okuma eklendi, bayraksız), `shell=False`, kodda `DROP TRIGGER` yok.
- Şema v3: 26 tabloda 78 tetikleyici var. Zincir doğrulaması çalışıyor.
- `.env`'den yalnız `TRADINGAGENTS_*` satırları okunuyor; API anahtarı okunmuyor.
- Ana akış `baslat` hâlâ çalışıyor.

## Bulgular
1. **KRİTİK — Canlı veritabanında gerçek veri yok.**
   - Canlı `masa.db`'de 0 snapshot, 0 ham kayıt, 0 işlem var.
   - 30.10 18:22 çalışması (4 pozisyon, 614 işlem) yalnız `masa.db.pre-restore-20261030_200055.bak` ve 19:15–19:20 yedeklerinde duruyor.
   - Canlı DB'ye 7 kez geri yükleme (restore) yapılmış. ~20:00'de boş bir DB'yle değiştirilmiş, v3'e geçiş de bu boş DB üzerinde yapılmış.
   - **Zincir ucu kütüğü bunu yakalamadı:** kütük, 30 mühürlü durumdan boş DB'ye gerilemeyi sorunsuz kaydetti ve `dogrula` "GEÇERLİ" diyor. İP-1'in amacı (zincir yeniden yazımını saptamak) karşılanmıyor.
   - Kütük monoton olmalı: yeni uç, önceki bütün uçları içermiyorsa KRİTİK uyarı verilmeli.
2. **KRİTİK — Testler canlı veritabanına yazıyor.**
   - `integrations/tradingagents.run_routed()`, `ModelRegistryManager()` ile varsayılan DB'ye yazıyor.
   - Test çalıştırmaları canlı append-only DB'ye 56 sahte `model_runs` kaydı (sembol A, B, C, D, LIMIT) ve 2 sahte model (`mod_google_g`, `mod_chatgpt_c`) ekledi. Bunlar artık silinemez.
   - Her yazma yolu, DB'yi parametre olarak almalı. Testler `MASA_DB_PATH`/tmp kullanmalı ve canlı yolu yasaklayan bir fixture olmalı.
3. **YÜKSEK — Günlük tahmin motoru bir tahmin değil ve gerçek akışta çalışmıyor.**
   - **Hedef fiyat:** son iki seri noktası arasındaki değişimin yarısı. Seri yoksa tarih+ISIN'in MD5 özetinden üretilen ±%1,5'lik sözde-rastgele bir sayı. Güven %65 sabit.
   - **Normal akışta:** taze DB'de `tahmin uret` → "FOREIGN KEY constraint failed" (havuzdaki hisseler `instruments`'ta yok). Canlı DB'de → "Quote not found".
   - **Zamanlanmış işler:** 09:30 ve 17:40 işleri yeni fiyat çekmiyor. Referans ve "kapanış" aynı eski kotasyon olur, gerçek hareket 0 çıkar ve karne anlamsızlaşır.
   - **Saat hatası:** Xetra 17:30'da kapanıyor, sistemdeki 17:00 hatalı.
4. **YÜKSEK — UCITS 5/10/40 kişisel portföye uygulanmış.**
   - Her raporda 4 ETF için 8 "UCITS uyarısı" çıkıyor (örn. %42,2 > %10).
   - Bu kural fon yöneticisi içindir; kişisel ETF portföyünde anlamsız. Şartname kararı kullanıcıya bırakmıştı.
   - Hatalar `except: pass` ile yutuluyor.
5. **ORTA — Model kaydı ve değerlendirme simülasyon.**
   - "Şampiyon" `mod_local_deterministic`; değerlendirmeler hiçbir modeli çağırmıyor.
   - `gemini-1.5-pro` "Google AI Pro aboneliği / EU_COMPLIANT / eligible" olarak doğrulanmadan kaydedilmiş (`last_verified_at` boş).
   - Özetteki "PRO-FIRST / useAiCredits" ilkesi sistem kodunda yok; o, yazan yapay zekanın kendi çalışma ayarı.
6. **ORTA — Özellikler var ama sizin sisteminizde verisi yok.**
   - Sepet (holdings) 0, tez 0, tahmin 0, mutabakat 0.
   - "Üretime hazır" ifadesi, "kod ve testler var" anlamında doğru; çalışır durumdaki bir sistem anlamında değil.
   - Şartnamenin "karar gerekli" maddeleri sorulmadan geçilmiş.

## Kurtarma önerisi
- Önce 1–4 düzeltilmeli.
- Ardından mevcut canlı DB arşive alınmalı (içinde test kirliliği var) ve `./etf-masa baslat` ile taze başlanmalı. Broker'daki her şey yeniden çekilebilir.
- 30.10 çalışması `.bak` dosyasında arşiv olarak durur; istenirse v2→v3 geçişiyle ayrı bir dosyada doğrulanabilir.
