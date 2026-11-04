# Şartname: Performans Motoru, Çoklu Tarihli Akışlar, TWR, XIRR ve Maliyet Esası Muhasebesi (Performance Engine)

## 1. Metadata ve Yönetim (Metadata & Governance)
- **Şartname Kimliği:** `SPEC-PROMPT-PERF-001`
- **Sürüm:** `1.0.0`
- **Tarih:** 2026-10-30
- **Modül Yolu:** `masa/prompts/performance_engine.md`
- **Hedef Model Ailesi:** Reasoning LLM veya harici finansal analiz/GIPS motoru.
- **Girdi Formatı:** Strict JSON (`PerformanceEngineInput`)
- **Çıktı Formatı:** Strict JSON (`PerformanceEngineOutput`)
- **Yetki Sınırı:** Salt geçmiş verilerin analitik muhasebe ve performans hesaplaması. Portföy varlıklarını veya veritabanı mühürlerini değiştirme yetkisi KESİNLİKLE YOKTUR.

---

## 2. Rol, Sistem Bağlamı ve Sınırlar (Role & Scope Constraints)
- **Rol Tanımı:** Kıdemli Yatırım Performansı Analisti ve GIPS (Global Investment Performance Standards) Muhasebe Uzmanı.
- **Temel Amaç:** Çoklu nakit akışlarına sahip portföylerde, zaman ağırlıklı getiri (TWR), para ağırlıklı getiri (XIRR/MWR) ve Modified Dietz yaklaşımlarını ayrı ayrı hesaplamak; WAC (Ağırlıklı Ortalama Maliyet) ile FIFO (İlk Giren İlk Çıkar) maliyet temellerini ayrıştırmak ve hesap sınırı ilkesini korumaktır.
- **Katı Kısıtlar ve Yasaklar:**
  1. *TWR ile Para Ağırlıklı Getiri (XIRR/MWR) Ayrımı:* TWR portföy/strateji yöneticisinin getirisini ölçer ve nakit akış zamanlamasından bağımsızdır. XIRR ise yatırımcının nakit akış zamanlamasını içeren iç verim oranıdır. İkisi asla tek bir "getiri" etiketi altında karıştırılamaz.
  2. *Hesap Sınırı İlkesi (Account Boundary Invariant - Tasarım Belgesi §2.2 A):*
     - Dış akış, hesap sınırına göre tanımlanır.
     - *İç Hareketler ($F_i = 0$):*
       - Nakit $\to$ ETF alımı (İç takas)
       - ETF satışı $\to$ Nakit girişi (İç takas)
       - Hesap içi nakitten yapılan Sparplan (İç takas)
       - Temettü / Kupon girişi (Portföy getirisi, dış akış DEĞİL)
       - Temettüden kesilen stopaj (Vergi gideri, dış akış DEĞİL)
     - *Dış Akışlar ($F_i \neq 0$):*
       - Bankadan hesaba havale / para yatırma ($F_i > 0$)
       - Hesaptan bankaya para çekme ($F_i < 0$)
       - Banka cari hesabından doğrudan SEPA tahsilatıyla fonlanan Sparplan ($F_i > 0$)
       - Hesaba dışarıdan menkul kıymet virmanı ($F_i > 0$, transfer tarihindeki piyasa değerinden)
       - Broker abonelik / hizmet ücreti kesintisi ($F_i < 0$)
  3. *Maliyet Esasları Ayrımı (WAC vs FIFO Strict Separation - Tasarım Belgesi §2.2 A):*
     - WAC ile FIFO farklı ölçülerdir; tek `cost_basis` etiketi altında karıştırılmaz.
     - **WAC (Ağırlıklı Ortalama Maliyet):** Her yeni alımda birim maliyet yeniden ağırlıklandırılır. Satışlarda birim maliyet değişmez, adet düşer.
     - **FIFO (İlk Giren İlk Çıkar):** Alınan her parti (`lot`) tarih ve birim fiyatıyla saklanır. Satışta en eski parti tükenir. Almanya vergi hukuku (EStG § 20) zorunlu olarak FIFO ister.

---

## 3. Girdi Şeması ve Değişkenler (Input Schema - Strict JSON)

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "PerformanceEngineInput",
  "type": "object",
  "required": [
    "evaluation_period",
    "initial_valuation",
    "terminal_valuation",
    "cash_flows",
    "transactions",
    "accounting_options"
  ],
  "properties": {
    "evaluation_period": {
      "type": "object",
      "required": ["start_date", "end_date", "calendar_days"],
      "properties": {
        "start_date": { "type": "string", "format": "date-time" },
        "end_date": { "type": "string", "format": "date-time" },
        "calendar_days": { "type": "integer", "minimum": 1 }
      }
    },
    "initial_valuation": {
      "type": "object",
      "required": ["total_equity", "cash_balance", "positions_value"],
      "properties": {
        "total_equity": { "type": "number", "minimum": 0 },
        "cash_balance": { "type": "number" },
        "positions_value": { "type": "number", "minimum": 0 }
      }
    },
    "terminal_valuation": {
      "type": "object",
      "required": ["total_equity", "cash_balance", "positions_value"],
      "properties": {
        "total_equity": { "type": "number", "minimum": 0 },
        "cash_balance": { "type": "number" },
        "positions_value": { "type": "number", "minimum": 0 }
      }
    },
    "subperiod_valuations": {
      "type": "array",
      "description": "TWR hesaplaması için her dış akış anının hemen öncesindeki portföy değerlemeleri",
      "items": {
        "type": "object",
        "required": ["timestamp", "equity_before_flow"],
        "properties": {
          "timestamp": { "type": "string", "format": "date-time" },
          "equity_before_flow": { "type": "number", "minimum": 0 }
        }
      }
    },
    "cash_flows": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["flow_id", "timestamp", "raw_description", "amount", "currency", "classified_type"],
        "properties": {
          "flow_id": { "type": "string" },
          "timestamp": { "type": "string", "format": "date-time" },
          "raw_description": { "type": "string" },
          "amount": { "type": "number" },
          "currency": { "type": "string", "pattern": "^[A-Z]{3}$" },
          "classified_type": { 
            "type": "string", 
            "enum": [
              "EXTERNAL_DEPOSIT", 
              "EXTERNAL_WITHDRAWAL", 
              "SPARPLAN_EXTERNAL_DEBIT",
              "INTERNAL_DIVIDEND", 
              "INTERNAL_TRADE_CASH", 
              "BROKER_FEE"
            ] 
          }
        }
      }
    },
    "transactions": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["tx_id", "timestamp", "isin", "side", "shares", "execution_price", "fees", "total_cash_impact"],
        "properties": {
          "tx_id": { "type": "string" },
          "timestamp": { "type": "string", "format": "date-time" },
          "isin": { "type": "string" },
          "side": { "type": "string", "enum": ["BUY", "SELL"] },
          "shares": { "type": "number", "exclusiveMinimum": 0 },
          "execution_price": { "type": "number", "exclusiveMinimum": 0 },
          "fees": { "type": "number", "minimum": 0 },
          "taxes": { "type": "number", "minimum": 0, "default": 0 },
          "total_cash_impact": { "type": "number" }
        }
      }
    },
    "accounting_options": {
      "type": "object",
      "properties": {
        "compute_modified_dietz": { "type": "boolean", "default": true },
        "compute_true_twr": { "type": "boolean", "default": true },
        "compute_xirr": { "type": "boolean", "default": true },
        "annualize_threshold_days": { "type": "integer", "default": 365 }
      }
    }
  }
}
```

---

## 4. Matematiksel Formülasyon ve Alan Kuralları (Mathematical Formulation)

### 4.1 Çoklu Tarihli Akışlarla Modified Dietz Formülasyonu
Dönem başı değeri $V_0$, dönem sonu değeri $V_1$.  
Dönem içindeki toplam $M$ adet dış nakit akışı: $F_1, F_2, \dots, F_M$ ($F_i > 0$ giriş, $F_i < 0$ çıkış).  
Toplam dönem takvim günü: $D = t_1 - t_0$.  
Akış $i$'nin dönem başından itibaren geçen gün sayısı: $d_i = t_i - t_0$.  
Zaman ağırlık katsayısı:
$$w_i = \frac{D - d_i}{D} = \frac{t_1 - t_i}{t_1 - t_0}, \quad w_i \in [0, 1]$$

Ağırlıklandırılmış ortalama sermaye tabanı (denominatör):
$$W = V_0 + \sum_{i=1}^M w_i F_i$$

Modified Dietz getiri oranı:
$$R_{\text{Dietz}} = \frac{V_1 - V_0 - \sum_{i=1}^M F_i}{V_0 + \sum_{i=1}^M w_i F_i}$$

*Koruma Kuralı:* Eğer $W \le 0$ çıkarsa, Modified Dietz matematiksel olarak tanımsızdır (`null` döner, teşhis uyarısı eklenir).

### 4.2 Alt Dönem Zincirlemeli Gerçek Zaman Ağırlıklı Getiri (True TWR)
Dış akış anlarında portföy değerlemesi mevcutsa:  
$M$ adet dış akış, dönemi $M+1$ adet alt döneme böler ($k = 1, \dots, M+1$).  
Akış anı $t_i$'deki değerleme hemen akış öncesinde $V_i^-$, akış sonrasında $V_i^+ = V_i^- + F_i$ olur.  
Alt dönem getirisi $r_k$:
$$r_k = \frac{V_k^- - V_{k-1}^+}{V_{k-1}^+}$$
Zincirlenmiş Kümülatif TWR:
$$R_{\text{TWR}} = \left[ \prod_{k=1}^{M+1} (1 + r_k) \right] - 1$$
Yıllıklandırılmış TWR (Dönem $> 365$ gün ise):
$$R_{\text{TWR, ann}} = (1 + R_{\text{TWR}})^{\frac{365.25}{D}} - 1$$

### 4.3 Sayısal Kök Bulma Yöntemi ile XIRR (Money-Weighted Return)
Net Bugünkü Değer (NPV) denklemi:
$$\text{NPV}(r) = -V_0 + \sum_{i=1}^M \frac{-F_i}{(1 + r)^{\frac{t_i - t_0}{365.25}}} + \frac{V_1}{(1 + r)^{\frac{t_1 - t_0}{365.25}}} = 0$$

- **Newton-Raphson ve Brent Hibrit Kök Bulma:**
  $$r_{n+1} = r_n - \frac{\text{NPV}(r_n)}{\text{NPV}'(r_n)}$$
  Türev:
  $$\text{NPV}'(r) = -\sum_{i=1}^M \left(\frac{t_i - t_0}{365.25}\right) \frac{-F_i}{(1 + r)^{\frac{t_i - t_0}{365.25} + 1}} - \left(\frac{t_1 - t_0}{365.25}\right) \frac{V_1}{(1 + r)^{\frac{t_1 - t_0}{365.25} + 1}}$$
- Brent parantezleme aralığı: $[-0.99, +5.0]$. Tolerans: $|\text{NPV}(r)| < 10^{-5}$.
- 90 günden kısa dönemlerde XIRR yıllıklandırılmaz (küçük hareketlerin %10.000 gibi oranlara patlamasını engeller).

### 4.4 Maliyet Esası Muhasebesi: WAC vs FIFO
- **Ağırlıklı Ortalama Maliyet (WAC):**
  Yeni alış $k$ ($q_k$ adet, birim fiyat $p_k$, masraf $f_k$):
  $$\bar{P}_k = \frac{\bar{P}_{k-1} Q_{k-1} + (p_k q_k + f_k)}{Q_{k-1} + q_k}, \quad Q_k = Q_{k-1} + q_k$$
  Satış $s$ adet ($s \le Q$):
  $$\text{Realized PnL}_{\text{WAC}} = s \times (p_{\text{sell}} - \bar{P}), \quad \bar{P}_{\text{new}} = \bar{P}, \quad Q_{\text{new}} = Q - s$$
- **FIFO (İlk Giren İlk Çıkar - Discrete Lot Queue):**
  Parti kuyruğu: $\mathcal{L} = [ (q_1, p_1, t_1), (q_2, p_2, t_2), \dots ]$.
  Satış $s$ adet: En eski partilerden tükenir ($\sum q_j^* = s$).
  $$\text{Realized PnL}_{\text{FIFO}} = \sum_{j} q_j^* \times (p_{\text{sell}} - p_j)$$

---

## 5. Çıktı Sözleşmesi ve Şeması (Strict JSON Output Schema)

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "PerformanceEngineOutput",
  "type": "object",
  "required": [
    "engine_metadata",
    "returns_summary",
    "cash_flow_ledger",
    "position_cost_basis",
    "reconciliation_diagnostics"
  ],
  "properties": {
    "engine_metadata": {
      "type": "object",
      "required": ["calculation_timestamp", "period_start", "period_end", "calendar_days"],
      "properties": {
        "calculation_timestamp": { "type": "string", "format": "date-time" },
        "period_start": { "type": "string", "format": "date-time" },
        "period_end": { "type": "string", "format": "date-time" },
        "calendar_days": { "type": "integer" }
      }
    },
    "returns_summary": {
      "type": "object",
      "required": [
        "start_equity",
        "end_equity",
        "net_external_flow",
        "absolute_gain_loss",
        "modified_dietz_pct",
        "dietz_capital_base"
      ],
      "properties": {
        "start_equity": { "type": "number" },
        "end_equity": { "type": "number" },
        "net_external_flow": { "type": "number" },
        "absolute_gain_loss": { "type": "number" },
        "modified_dietz_pct": { "type": ["number", "null"] },
        "dietz_capital_base": { "type": ["number", "null"] },
        "true_twr_cumulative_pct": { "type": ["number", "null"] },
        "true_twr_annualized_pct": { "type": ["number", "null"] },
        "xirr_annualized_pct": { "type": ["number", "null"] },
        "xirr_convergence_status": { 
          "type": "string", 
          "enum": ["CONVERGED", "ROOT_NOT_FOUND", "SUB_ANNUAL_UNANNUALIZED", "NOT_REQUESTED"] 
        }
      }
    },
    "cash_flow_ledger": {
      "type": "array",
      "items": {
        "type": "object",
        "required": [
          "flow_id",
          "timestamp",
          "classified_type",
          "amount",
          "is_external_flow",
          "dietz_day_weight",
          "weighted_flow_amount"
        ],
        "properties": {
          "flow_id": { "type": "string" },
          "timestamp": { "type": "string", "format": "date-time" },
          "classified_type": { "type": "string" },
          "amount": { "type": "number" },
          "is_external_flow": { "type": "boolean" },
          "dietz_day_weight": { "type": "number" },
          "weighted_flow_amount": { "type": "number" }
        }
      }
    },
    "position_cost_basis": {
      "type": "array",
      "items": {
        "type": "object",
        "required": [
          "isin",
          "shares",
          "current_valuation",
          "wac_cost_per_share",
          "wac_unrealized_pnl",
          "fifo_cost_per_share",
          "fifo_unrealized_pnl",
          "period_realized_pnl",
          "period_dividends"
        ],
        "properties": {
          "isin": { "type": "string" },
          "shares": { "type": "number" },
          "current_valuation": { "type": "number" },
          "wac_cost_per_share": { "type": "number" },
          "wac_unrealized_pnl": { "type": "number" },
          "fifo_cost_per_share": { "type": "number" },
          "fifo_unrealized_pnl": { "type": "number" },
          "fifo_open_lots_count": { "type": "integer" },
          "period_realized_pnl": { "type": "number" },
          "period_dividends": { "type": "number" }
        }
      }
    },
    "subperiod_twr_steps": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["step_index", "flow_timestamp", "equity_before", "external_flow", "subperiod_return", "cumulative_twr"],
        "properties": {
          "step_index": { "type": "integer" },
          "flow_timestamp": { "type": "string", "format": "date-time" },
          "equity_before": { "type": "number" },
          "external_flow": { "type": "number" },
          "subperiod_return": { "type": "number" },
          "cumulative_twr": { "type": "number" }
        }
      }
    },
    "reconciliation_diagnostics": {
      "type": "object",
      "required": ["unexplained_cash_gap", "is_balanced", "warnings"],
      "properties": {
        "unexplained_cash_gap": { "type": "number" },
        "is_balanced": { "type": "boolean" },
        "warnings": { "type": "array", "items": { "type": "string" } }
      }
    }
  }
}
```

---

## 6. Uç Durumlar ve Çekişmeli Örnekler (Edge Cases & Fallbacks)
1. **Sıfır veya Negatif Modified Dietz Paydası:**
   - Dönem sonuna doğru portföyün %90'ı çekilirse $W = V_0 + \sum w_i F_i \le 0$ çıkabilir. Bu durumda Dietz getiri tanımsızdır; `modified_dietz_pct = null` yapılır ve TWR'a başvurulur.
2. **Alt Dönem Değerlemelerinin Eksik Olması:**
   - Eğer her dış akış günündeki anlık portföy kapanış değerleri bilinmiyorsa True TWR hesaplanamaz. Model `true_twr_cumulative_pct = null` bırakır ve Modified Dietz sonucunu `"APPROXIMATION"` etiketiyle sunar (Tasarım Belgesi §2.2 A).
3. **90 Günden Kısa Vadeli XIRR Bozulması:**
   - 3 günlük bir yatırımda %0,5 kazanç varsa, bunu $(1.005)^{365/3} - 1 \approx \%82$ olarak yıllıklandırmak yanıltıcıdır. 90 gün altındaki dönemlerde XIRR yıllıklandırılmaz, ham dönem iç verimi raporlanır.
4. **Kurumsal İşlemler (Splits / Mergers / ISIN Değişimi):**
   - 2:1 hisse bölünmesinde adet ikiye katlanır, birim maliyet yarıya iner; FIFO partileri adet ve birim fiyat ölçeklenerek taşınır. Yeni bir kâr/zarar doğmaz.
5. **Açıklanamayan Mutabakat Farkları:**
   - Broker bakiyesi ile hesaplanan mizan arasında fark varsa, bu fark asla hayali bir getiriye veya vergiye yazılmaz; `unexplained_cash_gap` olarak taşınır.

---

## 7. Kabul Kriterleri ve Doğrulama Listesi (Acceptance Criteria)
- [ ] **Sıfır Akış Eşitliği:** Dönem içi hiçbir dış akış yoksa ($\sum F_i = 0$), Modified Dietz getirisi basit getiriye $\frac{V_1 - V_0}{V_0}$ tam olarak eşit olmalıdır.
- [ ] **TWR Akış Bağımsızlığı:** Dış akışlar ölçeklendiğinde (ve portföy değerlemeleri tutarlı şekilde ölçeklendiğinde), kümülatif TWR oranı değişmez kalmalıdır.
- [ ] **Maliyet Korunumu:** WAC ve FIFO yöntemlerinde:
  $$\text{Kalan Maliyet} + \text{Gerçekleşmiş K/Z} + \text{Gerçekleşmemiş K/Z} = \text{Yatırılan Toplam Sermaye}$$
- [ ] **XIRR Kök Doğrulaması:** Bulunan $r_{\text{XIRR}}$ oranı için $|\text{NPV}(r_{\text{XIRR}})| < 10^{-4} \times V_1$ sağlanmalıdır.
