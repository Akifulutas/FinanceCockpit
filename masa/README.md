# ETF Yatırım Masası (`masa`)

Scalable CLI'den **salt okunan** veriyi mühürleyen, analiz eden ve karar desteği üreten
yerel sistem. Broker'a yazma yolu yoktur; hiçbir komut emir, Sparplan veya izleme
listesi değişikliği yapmaz.

## Günlük kullanım

```bash
cd ~/Documents/ETF
./etf-masa baslat            # tam akış (aşağıda)
./etf-masa baslat --derin    # + TradingAgents çok ajanlı LLM görüşü (API ücreti; onay sorar)
```

`baslat` sırası:

1. **Oturum kontrolü** — `sc whoami`. Oturum yoksa ya da süresi dolduysa sizi
   `sc login --local-read-only` ile girişe yönlendirir, Enter'a basınca tekrar dener.
2. **Başlangıç verisi** — pozisyonlar, nakit, her ISIN için kotasyon (`veri`), sonra
   1 yıllık ve azami fiyat serileri ile tüm işlem geçmişi (`gecmis`). Her şey ham
   haliyle `masa/var/private/masa.db`'ye yazılır ve SHA-256 zinciriyle mühürlenir.
3. **Fırsat taraması** — `config/havuz.json`'daki ETF ve hisseler Scalable verisiyle
   ölçülür ve sıralanır.
4. **TradingAgents** (yalnız `--derin`) — elinizdeki fonlar ve taramanın en iyi
   adayları için çok ajanlı analiz (`~/TradingAgents`, kendi `.env`'i).
5. **Rapor** — portföy, fiyat performansı, risk (quantstats), korelasyon, işlem
   geçmişinden gerçekleşmiş getiri (TWR / Modified Dietz / XIRR), tut-ekle-azalt
   değerlendirmesi, plan, tarama, red-team denetimi ve gerçek bütünlük kontrolleri.
   Dosya: `masa/var/reports/masa-rapor-<tarih>.md`
6. **Yorum paketi** — yöntem dosyalarınız + rapor + TradingAgents çıktıları, Claude'a
   yapıştırılmaya hazır prompt: `masa/var/reports/yorum-paketi-<tarih>.md`

## Tek tek komutlar

| Komut | İş |
|---|---|
| `kontrol` | sc, oturum, paketler, TradingAgents, DB ve ayar kontrolü |
| `giris` | Oturumu kontrol eder, gerekirse giriş yönlendirmesi |
| `veri` / `gecmis` | Canlı veri / geçmiş serileri ve işlemleri mühürler |
| `dogrula` | Mühür ve denetim zincirlerini **alan düzeyinde** yeniden hesaplar |
| `portfoy` | Son mühürden portföy |
| `rapor [--nakit 150]` | Son mühürden tam rapor |
| `degerlendir` | Yalnız tut/ekle/azalt değerlendirmesi |
| `tarama` | Havuz taraması |
| `plan --nakit 150` | Hedef ağırlıklara göre yeniden dengeleme planı (emir değil) |
| `tradingagents [ISIN…] [--evet]` | Seçilen ISIN'ler için TradingAgents |
| `yorum` | Prompt + kanıt paketi |

## Ayarlar (`masa/config/`)

- `portfoy.json` — her ISIN'in rolü, Yahoo sembolü (yalnız TradingAgents için) ve
  **isteğe bağlı** `hedef_agirliklar`. Hedef yazılmadıkça plan üretilmez.
- `politika.json` — tut/sat eşikleri. Varsayılanlar **TASLAK**; onaylamak için
  `"durum": "ONAYLANDI"` yapın.
- `havuz.json` — tarama havuzu (ISIN ekleyip çıkarabilirsiniz).
- `modeller.json` — TradingAgents model dağılımı: hızlı katman (çağrıların ~%90'ı) sembol
  bazında Google Gemini ve ChatGPT aboneliği arasında ağırlıklı sırayla paylaştırılır,
  derin katman ChatGPT'dedir; limit/kota hatasında sembol bir kez diğer sağlayıcıyla denenir.

## Güvenlik ve veri sınırları

- `sc` sabit yoldan çağrılır (`/opt/homebrew/bin/sc` veya `MASA_SC_BIN`), `shell=False`,
  komut ve bayrak beyaz listesi, değer doğrulaması. Okunan komutlar: `whoami`,
  `broker context show|holdings|cash-breakdown|quote|transactions|chart`.
- Önerilen: oturumu `sc login --local-read-only` ile açın (CLI'nin kendi yerel
  salt-okuma kilidi; sunucu yetkisini daraltmaz).
- Mühürler: her kayıt tüm alanlarıyla özetlenir; `dogrula` özetleri yeniden hesaplar.
  `UPDATE/DELETE` ve üzerine yazan `INSERT OR REPLACE` tetikleyicilerle engellenir.
- TradingAgents ayrı süreçte, kendi ortamında çalışır; ona yalnız sembol, tarih ve
  portföy özeti (adet, ortalama maliyet, nakit) gider. Çıktısı "harici görüş" olarak
  saklanır, çekirdek fiyat/hesaplara karışmaz.
- Vergi hesaplanmaz (modül pasif). Rapor yatırım veya vergi danışmanlığı değildir.

## Geliştirici

```bash
cd ~/Documents/ETF/masa && uv run pytest -q       # 125 test
./scripts/sc_probe.sh                                  # sc çıktı biçimi örnekleri (salt okuma)
```

Şema v2 (2026-10-30). Eski v1 veritabanı `var/private/masa_legacy_v1_20261030.db`
olarak arşivlendi; yeni zincire karıştırılmaz.
