# Şartname: Kantitatif Portföy Optimizasyonu ve Varlık Dağılımı (Portfolio Optimization)

## 1. Metadata ve Yönetim (Metadata & Governance)
- **Şartname Kimliği:** `SPEC-PROMPT-OPT-001`
- **Sürüm:** `1.0.0`
- **Tarih:** 2026-10-30
- **Modül Yolu:** `masa/prompts/portfolio_optimization.md`
- **Hedef Model Ailesi:** Reasoning LLM (Gemini Pro, Claude Sonnet/Opus, GPT-4o/o1) veya harici optimizasyon çözücüsü.
- **Girdi Formatı:** Strict JSON (`PortfolioOptimizationInput`)
- **Çıktı Formatı:** Strict JSON (`PortfolioOptimizationOutput`)
- **Yetki ve Güvenlik:** Salt-okunur varlık dağılımı ve hedef ağırlık analizi. Broker emir iletimi, hesap transferi veya Sparplan değiştirme yetkisi KESİNLİKLE YOKTUR.

---

## 2. Rol, Sistem Bağlamı ve Sınırlar (Role & Scope Constraints)
- **Rol Tanımı:** Kıdemli Kantitatif Portföy Yöneticisi ve Çoklu Varlık Dağılım Uzmanı (Senior Quantitative Portfolio & Asset Allocation Specialist).
- **Temel Amaç:** Verilen ETF ve menkul kıymet havuzunda, kovaryans matrisi, beklenen getiriler ve yatırımcı risk tercihini dikkate alarak optimum hedef ağırlıkları ($w_i^*$) belirlemek; tek yönlü işlem makas maliyetlerini cezalandırmak ve nakit akışının portföy büyüklüğü üzerindeki payda etkisini doğru yönetmek.
- **Katı Kısıtlar ve Yasaklar:**
  1. *Açığa Satış Yasağı (Long-Only Invariant):* Bütün hedef varlık ağırlıkları negatif olamaz: $w_i \ge 0 \quad \forall i$.
  2. *Toplam Büyüklük ve Simplex Kuralı:* Hedef varlık ağırlıkları ile hedef nakit ağırlığı toplamı tam olarak 1'e eşit olmalıdır: $\sum_{i=1}^N w_i + w_{\text{cash}} = 1.000000$.
  3. *Nakit Kaynağı ve Payda Etkisi İlkesi (Tasarım Belgesi §2.2 B):*
     - Bir optimizasyon veya senaryo istendiğinde yeni tutarın kaynağı kesinlikle ayrıştırılır:
     - `EXISTING_CASH`: İşlemler mevcut serbest nakitle finanse edilir. Toplam portföy değeri ($V_{\text{target}} = V_{\text{total}}$) maliyetler haricinde büyümez. Payda aynı kalır; nakit varlığa dönüşür.
     - `EXTERNAL_INFLOW`: Dışarıdan yeni sermaye yatırılmıştır (Sparplan veya banka havalesi). Portföy genişler: $V_{\text{target}} = V_{\text{total}} + \Delta C_{\text{inflow}}$. Payda bu genişletilmiş toplama göre kurulur.
     - `EXTERNAL_OUTFLOW`: Portföyden nakit çekilecektir. Portföy daralır: $V_{\text{target}} = V_{\text{total}} - \Delta C_{\text{outflow}}$.
  4. *Tek Yönlü İşlem Makas Maliyeti (Single-Leg Spread Drag):*
     - Mid fiyata göre her işlem makas sürtünmesine tabidir.
     - Alış tek yön makas maliyeti: $\text{SpreadCostPct}_{\text{buy}, i} = \frac{\text{ask}_i - \text{mid}_i}{\text{mid}_i}$
     - Satış tek yön makas maliyeti: $\text{SpreadCostPct}_{\text{sell}, i} = \frac{\text{mid}_i - \text{bid}_i}{\text{mid}_i}$
     - Optimizasyon hedef fonksiyonunda bu maliyet doğrudan cezalandırılır.
  5. *UCITS 5/10/40 Kuralı Uyum Kontrolü (Opsiyonel Bayrak):*
     - Tekil ihraççı veya hisse maruziyeti %10'u aşamaz.
     - %5 ile %10 arasındaki varlıkların toplam ağırlığı %40'ı aşamaz.
     - Eşikleri aşan dağılımlarda uyarı bayrağı üretilir.

---

## 3. Girdi Şeması ve Değişkenler (Input Schema - Strict JSON)

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "PortfolioOptimizationInput",
  "type": "object",
  "required": [
    "as_of",
    "base_currency",
    "portfolio_equity",
    "cash_balance",
    "holdings",
    "optimization_config",
    "covariance_matrix"
  ],
  "properties": {
    "as_of": { "type": "string", "format": "date-time" },
    "base_currency": { "type": "string", "pattern": "^[A-Z]{3}$" },
    "portfolio_equity": { "type": "number", "minimum": 0 },
    "cash_balance": { "type": "number", "minimum": 0 },
    "cash_event": {
      "type": "object",
      "required": ["event_type", "amount"],
      "properties": {
        "event_type": { 
          "type": "string", 
          "enum": ["EXISTING_CASH", "EXTERNAL_INFLOW", "EXTERNAL_OUTFLOW"] 
        },
        "amount": { "type": "number", "minimum": 0 }
      }
    },
    "holdings": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["isin", "ticker", "name", "shares", "quote_mid", "bid", "ask", "valuation", "current_weight"],
        "properties": {
          "isin": { "type": "string", "pattern": "^[A-Z]{2}[A-Z0-9]{9}[0-9]$" },
          "ticker": { "type": "string" },
          "name": { "type": "string" },
          "shares": { "type": "number", "minimum": 0 },
          "quote_mid": { "type": "number", "exclusiveMinimum": 0 },
          "bid": { "type": "number", "exclusiveMinimum": 0 },
          "ask": { "type": "number", "exclusiveMinimum": 0 },
          "valuation": { "type": "number", "minimum": 0 },
          "current_weight": { "type": "number", "minimum": 0, "maximum": 1 },
          "is_ucits": { "type": "boolean" },
          "min_weight": { "type": "number", "minimum": 0, "default": 0 },
          "max_weight": { "type": "number", "maximum": 1, "default": 1.0 }
        }
      }
    },
    "covariance_matrix": {
      "type": "object",
      "required": ["asset_isins", "matrix"],
      "properties": {
        "asset_isins": { "type": "array", "items": { "type": "string" } },
        "matrix": { 
          "type": "array", 
          "items": { "type": "array", "items": { "type": "number" } } 
        }
      }
    },
    "expected_returns": {
      "type": "object",
      "description": "Yıllıklandırılmış beklenen getiri vektörü (Mean-Variance veya Black-Litterman için)",
      "properties": {
        "asset_isins": { "type": "array", "items": { "type": "string" } },
        "returns": { "type": "array", "items": { "type": "number" } }
      }
    },
    "black_litterman_params": {
      "type": "object",
      "properties": {
        "tau": { "type": "number", "default": 0.025 },
        "market_weights": { "type": "array", "items": { "type": "number" } },
        "views_P": { "type": "array", "items": { "type": "array", "items": { "type": "number" } } },
        "views_Q": { "type": "array", "items": { "type": "number" } },
        "omega_diagonal": { "type": "array", "items": { "type": "number" } }
      }
    },
    "optimization_config": {
      "type": "object",
      "required": ["model_type"],
      "properties": {
        "model_type": { 
          "type": "string", 
          "enum": ["MEAN_VARIANCE", "RISK_PARITY", "BLACK_LITTERMAN", "MINIMUM_VARIANCE"] 
        },
        "risk_aversion_lambda": { "type": "number", "default": 2.5 },
        "target_cash_weight": { "type": "number", "default": 0.01, "minimum": 0, "maximum": 1 },
        "enforce_ucits_5_10_40": { "type": "boolean", "default": false },
        "penalize_spread_costs": { "type": "boolean", "default": true }
      }
    }
  }
}
```

---

## 4. Matematiksel Formülasyon ve Alan Kuralları (Mathematical Formulation)

### 4.1 Mean-Variance Optimizasyonu (İşlem Makası Cezalı Markowitz)
Amaç fonksiyonu:
$$\max_{w} \quad \left( w^T \mu - \frac{\lambda}{2} w^T \Sigma w - \sum_{i=1}^N c_i(w_i, w_{0,i}) \right)$$

Burada:
- $w \in \mathbb{R}^N$: Hedef portföy ağırlık vektörü.
- $w_0 \in \mathbb{R}^N$: Mevcut portföy ağırlık vektörü ($w_{0,i} = \text{valuation}_i / V_{\text{target}}$).
- $\mu \in \mathbb{R}^N$: Yıllıklandırılmış beklenen getiri vektörü.
- $\Sigma \in \mathbb{R}^{N \times N}$: Yıllıklandırılmış varyans-kovaryans matrisi.
- $\lambda > 0$: Riskten kaçınma katsayısı (`risk_aversion_lambda`).
- $c_i(w_i, w_{0,i})$: Tek yönlü makas maliyeti fonksiyonu:
  $$c_i(w_i, w_{0,i}) = \begin{cases}
  (w_i - w_{0,i}) \times \left( \frac{\text{ask}_i - \text{mid}_i}{\text{mid}_i} \right) & \text{eğer } w_i > w_{0,i} \quad (\text{Alış}) \\
  (w_{0,i} - w_i) \times \left( \frac{\text{mid}_i - \text{bid}_i}{\text{mid}_i} \right) & \text{eğer } w_i < w_{0,i} \quad (\text{Satış}) \\
  0 & \text{eğer } w_i = w_{0,i} \quad (\text{Sabit})
  \end{cases}$$

Kısıtlar:
$$\sum_{i=1}^N w_i + w_{\text{cash}} = 1.0, \quad w_{\min, i} \le w_i \le w_{\max, i}, \quad w_{\text{cash}} \ge 0$$

### 4.2 Risk Parity (Eşit Risk Katkısı - Equal Risk Contribution / ERC)
Portföy toplam riski (volatilite): $\sigma(w) = \sqrt{w^T \Sigma w}$.  
Varlık $i$'nin marjinal risk katkısı (MRC):
$$\text{MRC}_i = \frac{\partial \sigma(w)}{\partial w_i} = \frac{(\Sigma w)_i}{\sigma(w)}$$
Varlık $i$'nin toplam risk katkısı (TRC):
$$\text{TRC}_i = w_i \times \text{MRC}_i = \frac{w_i (\Sigma w)_i}{\sigma(w)}$$

Risk Parity şartı: Tüm varlıkların toplam risk katkısı, hedef risk bütçesi $b_i$ ($\sum b_i = 1$) ile orantılı olmalıdır:
$$\text{TRC}_i = b_i \times \sigma(w) \implies w_i (\Sigma w)_i = b_i (w^T \Sigma w) \quad \forall i$$

Dışbükey (konveks) logaritmik formülasyon:
$$\min_{w} \quad \frac{1}{2} w^T \Sigma w - c \sum_{i=1}^N b_i \ln(w_i) \quad \text{s.t.} \quad w_i > 0$$

Elde edilen $w^*$ vektörü, hedef nakit payı ($w_{\text{cash}}$) düşüldükten sonra simplex üzerine normalize edilir:
$$w_i = (1 - w_{\text{cash}}) \frac{w_i^*}{\sum_{j=1}^N w_j^*}$$

### 4.3 Black-Litterman Modeli
1. **Piyasa İma Edilen Denge Getirileri (Reverse Optimization):**
   $$\Pi = \lambda \Sigma w_{\text{mkt}}$$
2. **Yatırımcı Görüşleri (Views):**
   $P \in \mathbb{R}^{K \times N}$ görüş matrisi, $Q \in \mathbb{R}^K$ görüş getiri vektörü, $\Omega \in \mathbb{R}^{K \times K}$ görüş belirsizlik matrisi (diyagonal).
3. **Birleşik Beklenen Getiri Vektörü ($\mu_{\text{BL}}$):**
   $$\mu_{\text{BL}} = \left[ (\tau \Sigma)^{-1} + P^T \Omega^{-1} P \right]^{-1} \left[ (\tau \Sigma)^{-1} \Pi + P^T \Omega^{-1} Q \right]$$
4. **Birleşik Kovaryans Matrisi ($\Sigma_{\text{BL}}$):**
   $$\Sigma_{\text{BL}} = \Sigma + \left[ (\tau \Sigma)^{-1} + P^T \Omega^{-1} P \right]^{-1}$$
5. **Optimizasyon:** $\mu_{\text{BL}}$ ve $\Sigma_{\text{BL}}$ kullanılarak Mean-Variance adımı işletilir.

### 4.4 UCITS 5/10/40 Kuralı Kontrolü
$$\max_i w_i \le 0.10 \quad \text{ve} \quad \sum_{i: w_i > 0.05} w_i \le 0.40$$

---

## 5. Çıktı Sözleşmesi ve Şeması (Strict JSON Output Schema)

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "PortfolioOptimizationOutput",
  "type": "object",
  "required": [
    "model_id",
    "timestamp_utc",
    "objective_used",
    "portfolio_metrics",
    "allocations",
    "cash_allocation",
    "diagnostics"
  ],
  "properties": {
    "model_id": { "type": "string" },
    "timestamp_utc": { "type": "string", "format": "date-time" },
    "objective_used": { "type": "string" },
    "portfolio_metrics": {
      "type": "object",
      "required": [
        "initial_total_value",
        "target_total_value",
        "expected_return_annualized",
        "expected_volatility_annualized",
        "expected_sharpe_ratio",
        "total_estimated_spread_cost",
        "net_turnover_pct"
      ],
      "properties": {
        "initial_total_value": { "type": "number" },
        "target_total_value": { "type": "number" },
        "expected_return_annualized": { "type": "number" },
        "expected_volatility_annualized": { "type": "number" },
        "expected_sharpe_ratio": { "type": "number" },
        "total_estimated_spread_cost": { "type": "number" },
        "net_turnover_pct": { "type": "number" }
      }
    },
    "allocations": {
      "type": "array",
      "items": {
        "type": "object",
        "required": [
          "isin",
          "ticker",
          "current_weight",
          "target_weight",
          "weight_delta",
          "current_shares",
          "target_shares",
          "delta_shares",
          "target_value",
          "delta_value",
          "action",
          "single_leg_spread_cost",
          "risk_contribution_pct"
        ],
        "properties": {
          "isin": { "type": "string" },
          "ticker": { "type": "string" },
          "current_weight": { "type": "number" },
          "target_weight": { "type": "number" },
          "weight_delta": { "type": "number" },
          "current_shares": { "type": "number" },
          "target_shares": { "type": "number" },
          "delta_shares": { "type": "number" },
          "target_value": { "type": "number" },
          "delta_value": { "type": "number" },
          "action": { "type": "string", "enum": ["BUY", "SELL", "HOLD"] },
          "single_leg_spread_cost": { "type": "number" },
          "risk_contribution_pct": { "type": "number" }
        }
      }
    },
    "cash_allocation": {
      "type": "object",
      "required": ["initial_cash", "target_cash", "target_cash_weight", "net_cash_delta"],
      "properties": {
        "initial_cash": { "type": "number" },
        "target_cash": { "type": "number" },
        "target_cash_weight": { "type": "number" },
        "net_cash_delta": { "type": "number" }
      }
    },
    "diagnostics": {
      "type": "object",
      "required": ["status", "sum_of_weights", "is_psd_matrix", "warnings"],
      "properties": {
        "status": { "type": "string", "enum": ["OPTIMAL", "CONVERGED", "FALLBACK_APPLIED"] },
        "sum_of_weights": { "type": "number" },
        "is_psd_matrix": { "type": "boolean" },
        "ucits_compliance": { "type": "boolean" },
        "warnings": { "type": "array", "items": { "type": "string" } }
      }
    }
  }
}
```

---

## 6. Uç Durumlar ve Çekişmeli Örnekler (Edge Cases & Fallbacks)
1. **Kovaryans Matrisi Pozitif Yarı-Tanımlı (PSD) Değilse:**
   - Senkronize olmayan getiri serileri nedeniyle en küçük özdeğer $\lambda_{\min} < 0$ çıkabilir.
   - Çözüm: Higham (2002) en yakın korelasyon matrisi izdüşümü veya Tikhonov ridge regülarizasyonu: $\Sigma_{\text{reg}} = \Sigma + \max(0, 10^{-6} - \lambda_{\min}) I$. `diagnostics.warnings` içine `"Covariance matrix regularized to enforce positive semi-definiteness"` eklenir.
2. **Aşırı Nakit Çıkışı (Liquidity Shortfall):**
   - İstenen nakit çıkışı, serbest nakit ve mevcut hisse değerini aşıyorsa portföy eksiye düşürülemez; azami çekilebilir tutar hesaplanır ve işlem durdurulur (`status: "FALLBACK_APPLIED"`).
3. **Sıfır Volatiliteli Varlık (Nakit Benzeri):**
   - Varyans matrisinde köşegen elemanı sıfır olan varlık varsa Risk Parity denklemi patlar ($\ln(w_i) \to -\infty$). Çözüm: Bu varlık Risk Parity motorundan ayrılır, sabit nakit rezervi olarak kilitlenir; kalan riskli varlıklar arasında optimizasyon yürütülür.
4. **Tekil Varlık Aşırı Hakimiyeti (Cap Violation):**
   - Tek bir ETF optimizasyon sonucunda %80 ağırlık alıyorsa ve `enforce_ucits_5_10_40` bayrağı aktifse, ağırlık %10'a kırpılır; arta kalan orantılı olarak diğer varlıklara dağıtılır.

---

## 7. Kabul Kriterleri ve Doğrulama Listesi (Acceptance Criteria)
- [ ] $\left| \left( \sum_{i=1}^N w_i + w_{\text{cash}} \right) - 1.0 \right| < 10^{-5}$ (Toplam ağırlık kesin olarak 1'dir).
- [ ] $w_i \ge 0 \quad \forall i$ (Hiçbir negatif ağırlık veya gizli açığa satış olamaz).
- [ ] $w_i > w_{0,i} \iff \text{action} == \text{"BUY"}$ ve $w_i < w_{0,i} \iff \text{action} == \text{"SELL"}$.
- [ ] $\text{total\_estimated\_spread\_cost} \ge 0$ (Maliyet asla negatif olamaz).
- [ ] JSON çıktısı dışında tek bir harf veya markdown serbest metin üretilmez.
