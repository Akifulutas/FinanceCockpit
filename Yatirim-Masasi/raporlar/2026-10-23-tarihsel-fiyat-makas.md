# Tarihsel ETF fiyat / makas kaydı — 7–21 Ekim 2026

Kullanıcının gönderdiği konsol çıktısından 77 satır; 11 ISIN ve 7 gözlem grubu ayrıştırıldı. Son kotasyon: 2026-10-21T09:38:57.780+00:00. Güncel fiyat değildir; pozisyon veya gerçekleşmiş işlem kaydı sayılmaz.

Üç başlık metinde ayrıca geçiyor: Insurance, Clean Edge Smart Grid Infrastructure ve Semiconductor. Bunlardan hedef ağırlık, yatırım kararı veya sahiplik sonucu çıkarılmadı.

| Kullanıcı etiketi | ISIN | Son gönderilen mid (EUR) | Son makas / mid (%) | Son fiyat zamanı (UTC) |
|---|---|---:|---:|---|
| EXH5 | DE000A0H08K7 | 54.9150 | 0.055 | 2026-10-21T09:38:49.047+00:00 |
| GRID | IE000J80JTL1 | 52.6700 | 0.114 | 2026-10-21T09:38:52.371+00:00 |
| XDWH | IE00BM67HK77 | 58.1050 | 0.052 | 2026-10-21T09:38:45.336+00:00 |
| EXV1 | DE000A0F5UJ7 | 38.8000 | 0.052 | 2026-10-21T09:38:57.780+00:00 |
| VVSM | IE00BMC38736 | 91.0650 | 0.033 | 2026-10-21T09:38:52.529+00:00 |
| SEC0 | IE000I8KRLL9 | 16.8930 | 0.036 | 2026-10-21T09:38:56.681+00:00 |
| JAPAN | IE00B4L5YX21 | 73.2300 | 0.082 | 2026-10-21T09:38:54.781+00:00 |
| VALUE | IE00BP3QZB59 | 70.6250 | 0.042 | 2026-10-21T09:38:55.011+00:00 |
| COPPER | IE0003Z9E2Y3 | 54.6200 | 0.073 | 2026-10-21T09:38:56.849+00:00 |
| DEFENCE | IE0002Y8CX98 | 31.0900 | 0.032 | 2026-10-21T09:38:46.691+00:00 |
| ROBOTICS | IE00BYZK4552 | 19.0830 | 0.073 | 2026-10-21T09:38:53.520+00:00 |

## Okuma sınırları

- Ticker sütunu kullanıcı etiketidir; borsa ve resmi işlem hattı bu çıktıyla doğrulanmadı.
- Fiyatlar kapanış/NAV değildir. Farklı gün ve saatlerdeki mid değerleri kişisel veya toplam getiri hesabına çevrilmedi.
- En büyük gözlem yaşı: GRID, 59.30 dakika. Satır fiyat zamanı ile snapshot zamanı ayrı tutuldu.
- N/A, fiyatın güncel veya eski olduğunu kanıtlamıyor: özgün jq // işleci false değerini de alternatif metne çevirir. Kayıtlarda bilinmeyen bayrak null bırakıldı.
- Gün içi dar makas ile akşam geniş makas farklı piyasa koşulları ve eski kotasyonlar içeriyor; bu küçük örneklemden kalıcı işlem saati veya alım talimatı çıkarılmadı.

## Özgün koddaki bayrak okumasının düzeltmesi

Bu ifade false değerini korur; yalnız null/eksik alanda N/A üretir. Broker komutu bu aktarımda çalıştırılmadı.

```bash
OUTDATED=$(echo "$JSON" | jq -r '.data.result.quote_is_outdated | if . == null then "N/A" else . end')
```

Kaynak metnin SHA-256 özeti ve satır düzeyindeki zamanlar aynı adlı JSON dosyasında; tablo verileri CSV dosyasındadır. Etkin portföy ve kalıcı izleme listesine yeni fon eklenmedi.
