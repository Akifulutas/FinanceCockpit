# Çalışma dosyaları ve yardımcı hesaplar

## Değiştirilebilir çalışma kökü

İlk tercih kullanıcının gösterdiği klasördür. Bu kurulumda çalışma kökü `Yatirim-Masasi/`, veri dizini `veri/` olarak hazırlanmıştır. Skill başka yere taşındığında bu yapıyı geçerli klasörde ara; eski bilgisayara ait mutlak yol kullanma.

- `veri/ayarlar.json`: Kullanıcının kesinleşmiş kapsamı ve açıkça etiketlenen çalışma varsayımları.
- `veri/izleme-listesi.csv`: Fon kimlikleri. Boş dosya, izlenecek fon bilinmediği anlamına gelir.
- `veri/portfoy.csv`: İsteğe bağlı pozisyon verisi. Güncel çalışma klasöründeki kullanıcı kayıtlarını oku; taşınabilir başlangıç paketinde boş olabilir.
- `veri/tezler.json`: Başlangıçta boş, kullanıcıya ait olduğu doğrulanan tezler.

Çıktıları gerektiğinde `raporlar/YYYY-MM-DD-mod.md` altında oluştur. Aynı adlı rapor varsa saati veya sıra numarasını ekle; önceki raporu ezme. Kaynak ve kanıt kayıtları gerektiğinde `kayitlar/kaynaklar.jsonl` ve `kayitlar/tez-guncellemeleri.jsonl` altında eklenebilir. Dosyayı değiştirmeden önce mevcut içeriği oku. Skill'in kurulu klasörüne portföy verisi yazma.

Genel fırsat araştırması kayıtlarını kullanıcı tezlerinden ayır: örneğin `kayitlar/arastirma-kanitlari.jsonl` içinde `record_type`, `research_horizon`, `candidate_isins`, `source_ids`, beklenti farkı, karşı kanıt, senaryo kabulleri ve sonraki kontrol tutulabilir. Aday ISIN'i, yalnız araştırmada geçti diye `portfoy.csv` veya kalıcı kullanıcı izleme listesine ekleme. Birleşik promptun kopyalanabilir sürümünde kişisel tutarları veya ekran görüntülerini gömme.

Her çalıştırma bitiminde taşınabilir devam özeti:

```text
Araştırma tarihi ve veri kesimi:
İncelenen ISIN'ler / ekonomik maruziyet:
Temel tez ve benchmark:
Önceki görüşten değişim:
En önemli olumlu / olumsuz kanıt:
Eksik veri ve kapsam:
Sonraki kontrol koşulu / tarihi:
Kaynaklar / kayıt dosyası:
```

Sohbet geçmişi veya dosya yazma özelliği yoksa bu bloğu bir sonraki çalıştırmada kullanıcı aktarabilir. Kalıcı bellek varmış gibi davranma. Yalnız açık talepte otomasyon kurulumuna geç; aynı skill'i kullanmak zamanlama değildir.

## etf_math.py

Bu bilgisayarda ayrıca çalışma kökünün bir üstündeki `./etf` komutu yerel panoyu üretir. Etkin portföy kaydı yine yukarıdaki CSV ve ayarlardır; kökteki `holdings.yaml` bağımsız veri kaynağı değildir. Yerel pano araştırma skill'inden ayrıdır: günlük veriyi indirmesi veya HTML oluşturması haber/tez araştırması yapıldığı anlamına gelmez. `./etf open` ekran kaydını ve varsa tarihli piyasa bağlamını gösterir; `./etf fetch` yalnız genel piyasa göstergelerini günceller. Gerçek adet/borsa, maliyet ve nakit hareketleri olmadan portföy getirisi hesaplanmaz. Pano başka bilgisayarda bulunmuyorsa bu komutların var olduğunu varsayma.

Python standart kütüphanesiyle yerel, salt okunur giriş hesapları; ağ/broker erişimi yoktur. Çıktı JSON'dur. Para birimi dönüşümü veya fiyat indirme yapmaz.

### Örtüşme

İki CSV: `security_id,weight_percent`. Kimlikler normalize edilmiş şirket/menkul kıymet kimliği olmalı; eşleştirilmemiş ticker kullanma. Ağırlıklar 0–100 yüzde biriminde. Çift kayıtlar birleştirilir. Her dosyada isteğe bağlı `as_of` sütunu aynı tarihi taşımalıdır. Tarihler farklıysa çıktı uyarır. Tarih verilmemişse çıktı bunu belirtir.

```text
python3 scripts/etf_math.py overlap --a fon-a.csv --b fon-b.csv
```

Bu komutu skill klasöründen çalıştır veya scriptin gerçek yolunu kullan. %100'e ulaşmayan dosyalarda çıktı kapsanan ağırlığı ve yalnız gözlenen ortak ağırlığın alt sınırını gösterir. %100'ü aşan dosyaları script reddeder; yuvarlama, çift kayıt veya türev maruziyetini analist çözmelidir. %100 toplam bile teminat sepetinin gerçek ekonomik maruziyet olduğunu kanıtlamaz; analist yapı kontrolünü ayrıca yapar.

### Snapshot denetimi

```json
{
  "currency": "EUR",
  "period_start": "2026-10-22T16:30:00+02:00",
  "period_end": "2026-10-23T16:30:00+02:00",
  "previous_equity": 1000,
  "current_equity": 1120,
  "positions_value": 1020,
  "cash": 100,
  "external_flow": 100,
  "flow_timing": "end",
  "reported_pnl": 20
}
```

```text
python3 scripts/etf_math.py snapshot snapshot.json
```

Tüm tutarlar aynı baz para biriminde ve aynı hesap kapsamındadır. ISO dönem sınırları saat dilimi taşımalıdır. `external_flow` eksik/null ise kazanç ve yüzde getiri hesaplanmaz. Sıfır gerçekten akış olmadığı doğrulandığında yazılır. `flow_timing` yalnız `none`, `start`, `end`, `mixed`, `unknown` olabilir; başta/sonda netleştirme yalnız bütün dış akışlar gerçekten o sınırdaysa uygundur. Dönem içi karşıt akışların net sıfır olması `none` değildir; `mixed` kullan. `mixed`/`unknown` yüzde getiri üretmez.

`positions_value` ile `cash` birlikte verilirse toplam mutabakatı yapılır. Model bu yalın şemada ilave varlık/yükümlülük içermez; bunlar varsa önce kapsamı doğru bir özete dönüştür veya daha uygun hesap kullan. Çelişki varsa çıktı durumu `needs_review` olur. Bu denetim fiyatların doğruluğunu veya tamamlanmış portföyü kanıtlamaz.
