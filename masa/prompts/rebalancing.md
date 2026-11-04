# Şartname: Portföy Yeniden Dengeleme, Tolerans Bantları ve Emir Sıralama (Rebalancing)

## 1. Metadata ve Yönetim (Metadata & Governance)
- **Şartname Kimliği:** `SPEC-PROMPT-REBAL-001`
- **Sürüm:** `1.0.0`
- **Tarih:** 2026-10-30
- **Modül Yolu:** `masa/prompts/rebalancing.md`
- **Hedef Model Ailesi:** Reasoning LLM veya harici portföy operasyon motoru.
- **Girdi Formatı:** Strict JSON (`RebalancingInput`)
- **Çıktı Formatı:** Strict JSON (`RebalancingOutput`)
- **Yetki ve Güvenlik:** Yalnızca sıralanmış icra planı (`ordered_execution_plan`) üretir. Broker API'sine doğrudan emir gönderemez; broker hesabı üzerinde yazma yetkisi YOKTUR.

---

## 2. Rol, Sistem Bağlamı ve Sınırlar (Role & Scope Constraints)
- **Rol Tanımı:** Portföy İcra ve Yeniden Dengeleme Operasyonları Uzmanı (Portfolio Rebalancing & Execution Specialist).
- **Temel Amaç:** Mevcut portföy ağırlıkları ile hedef ağırlıklar arasındaki sapmaları çift bantlı tolerans mantığıyla incelemek, asgari işlem tutarı altındaki ufak sürtünmeleri filtrelemek, Almanya vergi hukukuna uygun olarak kâr realizasyonu yerine Sparplan/yeni nakit ile organik dengelemeyi öncelemek ve iki fazlı (önce satış, sonra alış) emir sırası oluşturmaktır.
- **Katı Kısıtlar ve Yasaklar:**
  1. *Sürtünmeyi Engelleme (Friction Avoidance):* Tolerans bandını aşmayan sapmalarda işlem üretilmez. Portföy ufak dalgalanmalarda gereksiz al-sat komisyonlarıyla yıpratılamaz.
  2. *Asgari Emir Büyüklüğü (Minimum Trade Ticket Size):* Scalable Capital ve benzeri brokerlarda €50 veya €100 altındaki işlemler orantısız komisyon veya operasyonel yük getirir. Eşiğin altındaki işlemler bastırılır (`suppressed_trades`).
  3. *Ciro (Turnover) Kısıtı:* Bir dengeleme döngüsünde toplam portföyün belirlenen azami ciro oranından (örn. %20) fazlasının dönmesi engellenir.
  4. *Almanya Vergi Farkındalığı (Abgeltungsteuer Awareness):*
     - Kârda olan pozisyonları satmak %26,375 vergi kesintisine (Kapitalertragsteuer + Solidaritätszuschlag) yol açar.
     - Tasarım ilkesi: **"Satış yerine yeni nakitle dengeleme" (Inflow-first rebalancing)**. Portföyde ağırlığı aşan varlığı satmak yerine, aylık düzenli tasarruf planı (Sparplan) veya yeni eklenen nakit, geride kalan (underweight) fonlara yönlendirilerek portföy organik olarak dengelenir.
  5. *İki Fazlı Emir Sıralama (2-Phase Execution Sequencing):*
     - Eğer satış yapılması zorunluysa, alım emirleri satış emirlerinden önce verilemez.
     - **Faz 1 (Likidite Üretimi - PHASE_1_SELL):** Önce satılması gereken pozisyonlar satılır, nakit yaratılır.
     - **Faz 2 (Tahsisat İcrası - PHASE_2_BUY):** Alımlar ancak nakit güvenceye alındıktan sonra ve sapma büyüklüğüne göre sıralı icra edilir.

---

## 3. Girdi Şeması ve Değişkenler (Input Schema - Strict JSON)

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "RebalancingInput",
  "type": "object",
  "required": [
    "as_of",
    "portfolio_id",
    "base_currency",
    "available_cash",
    "positions",
    "target_weights",
    "rebalance_policy"
  ],
  "properties": {
    "as_of": { "type": "string", "format": "date-time" },
    "portfolio_id": { "type": "string" },
    "base_currency": { "type": "string", "pattern": "^[A-Z]{3}$" },
    "available_cash": { "type": "number", "minimum": 0 },
    "new_cash_injection": { "type": "number", "minimum": 0, "default": 0 },
    "positions": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["isin", "ticker", "name", "shares", "quote_mid", "bid", "ask", "valuation", "current_weight"],
        "properties": {
          "isin": { "type": "string" },
          "ticker": { "type": "string" },
          "name": { "type": "string" },
          "shares": { "type": "number", "minimum": 0 },
          "quote_mid": { "type": "number", "exclusiveMinimum": 0 },
          "bid": { "type": "number", "exclusiveMinimum": 0 },
          "ask": { "type": "number", "exclusiveMinimum": 0 },
          "valuation": { "type": "number", "minimum": 0 },
          "current_weight": { "type": "number", "minimum": 0, "maximum": 1 },
          "unrealized_gain": { "type": "number", "description": "Vergi farkındalığı için kâr/zarar tutarı" },
          "cost_basis_per_share": { "type": "number" }
        }
      }
    },
    "target_weights": {
      "type": "object",
      "description": "Varlık ISIN -> Hedef Ağırlık eşlemesi",
      "additionalProperties": { "type": "number", "minimum": 0, "maximum": 1 }
    },
    "rebalance_policy": {
      "type": "object",
      "required": ["absolute_tolerance_band", "relative_tolerance_band", "min_trade_ticket_eur"],
      "properties": {
        "rebalance_mode": { 
          "type": "string", 
          "enum": ["INFLOW_ONLY", "FULL_REBALANCE", "TAX_MINIMIZED"], 
          "default": "FULL_REBALANCE" 
        },
        "absolute_tolerance_band": { "type": "number", "default": 0.015, "description": "+/- 1.5% mutlak sapma" },
        "relative_tolerance_band": { "type": "number", "default": 0.05, "description": "+/- 5% göreceli drift" },
        "min_trade_ticket_eur": { "type": "number", "default": 50.0, "description": "Asgari işlem büyüklüğü" },
        "max_portfolio_turnover": { "type": "number", "default": 0.20, "description": "Azami ciro oranı (%20)" },
        "allow_selling": { "type": "boolean", "default": true },
        "target_cash_weight": { "type": "number", "default": 0.01 },
        "estimated_tax_rate": { "type": "number", "default": 0.26375 }
      }
    }
  }
}
```

---

## 4. Matematiksel Formülasyon ve Alan Kuralları (Mathematical Formulation)

### 4.1 Çift Eşikli Sapma ve Tetikleme (Dual-Band Trigger Logic)
Varlık $i$ için güncel ağırlık $w_{i, \text{curr}}$, hedef ağırlık $w_{i, \text{tgt}}$.
- Mutlak Sapma:
  $$\Delta w_{i, \text{abs}} = |w_{i, \text{curr}} - w_{i, \text{tgt}}|$$
- Göreceli Sapma:
  $$\Delta w_{i, \text{rel}} = \frac{|w_{i, \text{curr}} - w_{i, \text{tgt}}|}{w_{i, \text{tgt}}}$$
- **Tetikleme Kuralı:**
  $$\text{IsTriggered}_i = \left( \Delta w_{i, \text{abs}} > \text{Band}_{\text{abs}} \right) \quad \text{AND} \quad \left( \Delta w_{i, \text{rel}} > \text{Band}_{\text{rel}} \right)$$

### 4.2 Hedef Büyüklük ve Brüt İşlem Tutarı
Hedef portföy büyüklüğü:
$$V_{\text{target}} = \sum_{i=1}^N \text{valuation}_i + \text{available\_cash} + \text{new\_cash\_injection}$$
Varlık $i$ için hedef değer: $V_{i, \text{target}} = w_{i, \text{tgt}} \times V_{\text{target}}$.  
Brüt işlem tutarı:
$$\Delta V_i = V_{i, \text{target}} - \text{valuation}_i$$

### 4.3 Asgari Bilet Filtresi (Minimum Ticket Size Filter)
$$\Delta V_i^* = \begin{cases}
0 & \text{eğer } |\Delta V_i| < \text{min\_trade\_ticket\_eur} \\
\Delta V_i & \text{aksi halde}
\end{cases}$$

### 4.4 Ciro (Turnover) Sınırlandırması
Planlanan toplam ciro:
$$\text{Turnover} = \frac{\sum_{i=1}^N |\Delta V_i^*|}{2 \times V_{\text{target}}}$$
Eğer $\text{Turnover} > \text{max\_portfolio\_turnover}$ ise, ölçekleme katsayısı $\kappa = \frac{\text{max\_portfolio\_turnover}}{\text{Turnover}}$ uygulanarak tüm işlemler orantılı olarak kısılır: $\Delta V_i^{**} = \kappa \times \Delta V_i^*$.

### 4.5 Yalnızca Nakit Girişiyle Dengeleme Formülasyonu (`INFLOW_ONLY`)
Eğer `allow_selling == False` veya `rebalance_mode == "INFLOW_ONLY"` ise:
Satış tutarları sıfırlanır ($\Delta V_i \le 0 \implies \Delta V_i = 0$). Yalnızca hedefinin gerisinde kalan varlıklar ($\text{gap}_i = \max(0, V_{i, \text{target}} - \text{valuation}_i)$) yeni nakitten pay alır:
$$\Delta V_{i, \text{inflow}} = \text{new\_cash\_injection} \times \left( \frac{\text{gap}_i}{\sum_{j=1}^N \text{gap}_j} \right)$$

### 4.6 Vergi ve Makas Maliyeti Tahmini
- Satışta vergi maliyeti tahmini:
  $$\text{TaxCost}_i = \max(0, \text{unrealized\_gain}_i \times \frac{|\Delta V_i^*|}{\text{valuation}_i}) \times \text{estimated\_tax\_rate}$$
- Makas sürtünmesi (Single-leg spread drag):
  $$\text{SpreadDrag} = \sum_{\Delta V_i > 0} \Delta V_i \left( \frac{\text{ask}_i - \text{mid}_i}{\text{mid}_i} \right) + \sum_{\Delta V_i < 0} |\Delta V_i| \left( \frac{\text{mid}_i - \text{bid}_i}{\text{mid}_i} \right)$$

---

## 5. Çıktı Sözleşmesi ve Şeması (Strict JSON Output Schema)

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "RebalancingOutput",
  "type": "object",
  "required": [
    "plan_id",
    "timestamp_utc",
    "rebalance_triggered",
    "rebalance_summary",
    "ordered_execution_plan",
    "post_rebalance_drift",
    "suppressed_trades"
  ],
  "properties": {
    "plan_id": { "type": "string" },
    "timestamp_utc": { "type": "string", "format": "date-time" },
    "rebalance_triggered": { "type": "boolean" },
    "trigger_rationale": { "type": "string" },
    "rebalance_summary": {
      "type": "object",
      "required": [
        "initial_portfolio_value",
        "projected_portfolio_value",
        "total_buy_volume",
        "total_sell_volume",
        "net_cash_impact",
        "projected_turnover_pct",
        "estimated_spread_drag_eur",
        "estimated_tax_impact_eur"
      ],
      "properties": {
        "initial_portfolio_value": { "type": "number" },
        "projected_portfolio_value": { "type": "number" },
        "total_buy_volume": { "type": "number" },
        "total_sell_volume": { "type": "number" },
        "net_cash_impact": { "type": "number" },
        "projected_turnover_pct": { "type": "number" },
        "estimated_spread_drag_eur": { "type": "number" },
        "estimated_tax_impact_eur": { "type": "number" }
      }
    },
    "ordered_execution_plan": {
      "type": "array",
      "items": {
        "type": "object",
        "required": [
          "execution_sequence",
          "phase",
          "isin",
          "ticker",
          "action",
          "shares_delta",
          "target_price",
          "estimated_amount",
          "spread_drag_eur",
          "tax_impact_eur",
          "rationale"
        ],
        "properties": {
          "execution_sequence": { "type": "integer", "minimum": 1 },
          "phase": { "type": "string", "enum": ["PHASE_1_SELL", "PHASE_2_BUY"] },
          "isin": { "type": "string" },
          "ticker": { "type": "string" },
          "action": { "type": "string", "enum": ["SELL", "BUY"] },
          "shares_delta": { "type": "number" },
          "target_price": { "type": "number" },
          "estimated_amount": { "type": "number" },
          "spread_drag_eur": { "type": "number" },
          "tax_impact_eur": { "type": "number" },
          "rationale": { "type": "string" }
        }
      }
    },
    "post_rebalance_drift": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["isin", "ticker", "current_weight", "target_weight", "projected_weight", "remaining_drift"],
        "properties": {
          "isin": { "type": "string" },
          "ticker": { "type": "string" },
          "current_weight": { "type": "number" },
          "target_weight": { "type": "number" },
          "projected_weight": { "type": "number" },
          "remaining_drift": { "type": "number" }
        }
      }
    },
    "suppressed_trades": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["isin", "action", "calculated_amount", "suppression_reason"],
        "properties": {
          "isin": { "type": "string" },
          "action": { "type": "string" },
          "calculated_amount": { "type": "number" },
          "suppression_reason": { 
            "type": "string", 
            "enum": ["BELOW_MIN_TICKET_SIZE", "WITHIN_TOLERANCE_BAND", "TURNOVER_CAPPED", "SELLING_PROHIBITED"] 
          }
        }
      }
    }
  }
}
```

---

## 6. Uç Durumlar ve Çekişmeli Örnekler (Edge Cases & Fallbacks)
1. **İcra Sırasında Nakit Eksikliği (Cash Under-run):**
   - Satış emirleri tahmin edilenden daha düşük fiyattan (kayma) gerçekleşirse, alım emirlerinin son basamakları icra edilemeyebilir. Çözüm: Alımlar kesinlikle önem ve sapma derecesine göre sıralanır; bakiye tükendiğinde kalan alımlar ertelenir. Portföyde negatif nakit oluşmasına asla izin verilmez.
2. **İşleme Kapalı / Askıya Alınmış ETF (Halted Instrument):**
   - Varlık borsa seansı dışındaysa veya kotasyon "outdated" ise o varlık için işlem üretilmez, mevcut pozisyon dondurulur; kalan varlıklar normalize edilmiş hedeflere göre dengelenir.
3. **Geniş Spread Uyarısı (Illiquidity Drag):**
   - Kotasyondaki spread $> \%1,5$ ise model bu fonu ani piyasa emriyle alıp satmak yerine XETR ana likidite saatlerinde (13:00 - 17:00 CET/CEST) limit emirle işlenmesini not eder (`rationale`).
4. **Vergi Kilidi (Tax-Lock Trap):**
   - Bir hissede/fonda çok yüksek gerçekleşmemiş kâr varsa ve satış yapıldığında portföyün %5'i vergiye gidecekse, model tam satış yerine yeni nakit akışlarıyla dengeleme yolunu önerir.

---

## 7. Kabul Kriterleri ve Doğrulama Listesi (Acceptance Criteria)
- [ ] $\sum \text{Buy Orders} + \text{Estimated Fees} \le \text{Initial Cash} + \sum \text{Sell Orders}$ (Nakit tükenme koruması).
- [ ] `ordered_execution_plan` içindeki hiçbir emrin tutarı `min_trade_ticket_eur` değerinden küçük olamaz.
- [ ] Tüm `PHASE_1_SELL` emirlerinin sıra numarası (`execution_sequence`), tüm `PHASE_2_BUY` emirlerinden kesinlikle küçüktür.
- [ ] Maksimum artık sapma (post-rebalance remaining drift), başlangıç sapmasından kesinlikle küçüktür veya eşittir.
