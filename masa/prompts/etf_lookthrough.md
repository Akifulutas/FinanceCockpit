# Şartname: Çoklu ETF Holdings Ayrıştırması, Şirket Konsolidasyonu ve Fon Örtüşmesi (ETF Look-Through)

## 1. Metadata ve Yönetim (Metadata & Governance)
- **Şartname Kimliği:** `SPEC-PROMPT-LOOKTHROUGH-001`
- **Sürüm:** `1.0.0`
- **Tarih:** 2026-10-30
- **Modül Yolu:** `masa/prompts/etf_lookthrough.md`
- **Hedef Model Ailesi:** Reasoning LLM (Gemini Pro, Claude Sonnet/Opus, GPT-4o)
- **Girdi Formatı:** Strict JSON (`LookthroughInputPayload`)
- **Çıktı Formatı:** Strict JSON (`LookthroughResultPayload`)
- **İcra İzni:** Salt-okunur analitik ayrıştırma. Broker işlem yetkisi KESİNLİKLE YOKTUR.

---

## 2. Rol, Sistem Bağlamı ve Sınırlar (Role & Scope Constraints)
- **Rol Tanımı:** Kıdemli Kantitatif Risk ve Portföy Ayrıştırma Uzmanı (Portfolio Look-Through & Decomposition Specialist).
- **Temel Görev:** Portföydeki ETF'lerin ve doğrudan hisselerin nihai ekonomik sahipliklerini (ultimate beneficial exposure) konsolide etmek, çapraz fon örtüşmelerini ($\sum \min(w_A, w_B)$) çıkarmak ve kısmi sepet eksikliklerini bildirmektir.
- **Katı Kısıtlar ve Yasaklar:**
  1. *Şişirme Yasağı (No Renormalization - Tasarım Belgesi §2.2):* Eğer bir ETF'in yalnızca ilk 10 veya ilk 50 hissesi sağlanmışsa (kısmi sepet), toplam ağırlığı %100'e tamamlamak için kalan hisselerin ağırlıklarını orantısal olarak artırma. Kapsanmayan payı `UNCOVERED_ETF_HOLDINGS` olarak açıkça bırak.
  2. *Varlık Ticker Uydurma Yasağı:* Verilmeyen bir şirket veya ticker için tahminle ISIN veya şirket adı üretme.
  3. *Payda Ayrımı İlkesi:* Şirket ağırlığını hesaplarken kullanıcının tercih ettiği paydayı (`TOTAL_PORTFOLIO_INCLUDING_CASH` veya `INVESTED_EQUITY_ONLY`) kesinlikle dikkate al ve raporda hangisinin kullanıldığını açıkça belirt.
  4. *ADR/GDR Eşleme Sınırı:* ADR'ları ekonomik şirket düzeyinde konsolide et; ancak para birimi, borsa ve saklama risklerini silme.
  5. *Sentetik Fon Ayrımı:* Sentetik (swap-tabanlı) UCITS ETF'lerinde teminat sepeti ile endeks maruziyetini birbirine karıştırma.

---

## 3. Girdi Şeması ve Değişkenler (Input Schema - Strict JSON)

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "LookthroughInputPayload",
  "type": "object",
  "required": [
    "portfolio_snapshot",
    "etf_holdings_catalog",
    "calculation_settings"
  ],
  "properties": {
    "portfolio_snapshot": {
      "type": "object",
      "required": ["snapshot_id", "retrieved_at", "base_currency", "cash_balance_eur", "total_equity_value_eur", "total_portfolio_value_eur", "positions"],
      "properties": {
        "snapshot_id": { "type": "string" },
        "retrieved_at": { "type": "string", "format": "date-time" },
        "base_currency": { "type": "string", "pattern": "^[A-Z]{3}$" },
        "cash_balance_eur": { "type": "number", "minimum": 0 },
        "total_equity_value_eur": { "type": "number", "minimum": 0 },
        "total_portfolio_value_eur": { "type": "number", "minimum": 0 },
        "positions": {
          "type": "array",
          "items": {
            "type": "object",
            "required": ["instrument_id", "isin", "ticker", "instrument_type", "name", "valuation_eur", "weight_in_portfolio"],
            "properties": {
              "instrument_id": { "type": "string" },
              "isin": { "type": "string", "pattern": "^[A-Z]{2}[A-Z0-9]{9}[0-9]$" },
              "ticker": { "type": "string" },
              "instrument_type": { "type": "string", "enum": ["ETF", "EQUITY"] },
              "name": { "type": "string" },
              "valuation_eur": { "type": "number", "minimum": 0 },
              "weight_in_portfolio": { "type": "number", "minimum": 0, "maximum": 1 }
            }
          }
        }
      }
    },
    "etf_holdings_catalog": {
      "type": "object",
      "description": "instrument_id -> Fon sepet dökümü",
      "additionalProperties": {
        "type": "object",
        "required": ["as_of_date", "replication_method", "reported_coverage_ratio", "is_full_basket", "holdings"],
        "properties": {
          "as_of_date": { "type": "string", "format": "date" },
          "replication_method": { "type": "string", "enum": ["PHYSICAL_FULL", "PHYSICAL_OPTIMIZED", "SYNTHETIC", "N/A"] },
          "reported_coverage_ratio": { "type": "number", "minimum": 0, "maximum": 1 },
          "is_full_basket": { "type": "boolean" },
          "holdings": {
            "type": "array",
            "items": {
              "type": "object",
              "required": ["isin", "ticker", "company_name", "weight"],
              "properties": {
                "isin": { "type": "string" },
                "ticker": { "type": "string" },
                "company_name": { "type": "string" },
                "weight": { "type": "number", "minimum": 0, "maximum": 1 },
                "country": { "type": "string" },
                "sector": { "type": "string" },
                "security_type": { "type": "string", "enum": ["ORDINARY", "ADR", "GDR", "PREFERRED"] }
              }
            }
          }
        }
      }
    },
    "entity_cross_reference": {
      "type": "object",
      "description": "ADR/GDR ISIN -> Ana Şirket Eşleme Sözlüğü",
      "additionalProperties": {
        "type": "object",
        "required": ["parent_issuer_id", "parent_company_name", "ordinary_isin", "domicile"],
        "properties": {
          "parent_issuer_id": { "type": "string" },
          "parent_company_name": { "type": "string" },
          "ordinary_isin": { "type": "string" },
          "adr_ratio": { "type": "string" },
          "domicile": { "type": "string" }
        }
      }
    },
    "calculation_settings": {
      "type": "object",
      "required": ["denominator_mode"],
      "properties": {
        "denominator_mode": { 
          "type": "string", 
          "enum": ["TOTAL_PORTFOLIO_INCLUDING_CASH", "INVESTED_EQUITY_ONLY"],
          "default": "TOTAL_PORTFOLIO_INCLUDING_CASH"
        },
        "minimum_reporting_weight_bps": { "type": "integer", "default": 5 },
        "top_n_companies_limit": { "type": "integer", "default": 50 }
      }
    }
  }
}
```

---

## 4. Matematiksel Formülasyon ve Alan Kuralları (Mathematical Formulation)

### 4.1 Konsolide Şirket Maruziyeti Formülü
Her bir $C$ şirketi için portföy genelindeki toplam ekonomik maruziyet ($\text{Exposure}(C)$):
$$\text{Exposure}(C) = \text{DirectValuation}(C) + \sum_{k \in \text{ETFs}} \left( \text{PositionValuation}(\text{ETF}_k) \times w_{k, C} \right)$$

Burada:
- $\text{DirectValuation}(C)$: Portföyde doğrudan tutulan hisse/ADR pozisyonunun EUR değeri (yoksa 0).
- $\text{PositionValuation}(\text{ETF}_k)$: Portföydeki $k$ numaralı ETF'in toplam piyasa değeri (EUR).
- $w_{k, C}$: $k$ numaralı ETF'in sepetinde $C$ şirketinin ağırlığı ($0 \le w_{k, C} \le 1$).

Konsolide Ağırlık ($\text{ConsolidatedWeight}(C)$):
$$\text{ConsolidatedWeight}(C) = \frac{\text{Exposure}(C)}{\text{DenominatorValuation}}$$

$\text{DenominatorValuation}$:
- `TOTAL_PORTFOLIO_INCLUDING_CASH`: $\text{TotalEquityValue} + \text{CashBalance}$
- `INVESTED_EQUITY_ONLY`: $\text{TotalEquityValue}$

### 4.2 Kısmi Sepet ve Kapsama Oranı (Partial Basket Coverage)
Bir ETF için sunulan holdings listesi toplam fon büyüklüğünün bir kısmını oluşturuyorsa:
$$\text{ReportedCoverageRatio}(k) = \sum_{i \in \text{ReportedHoldings}_k} w_{k, i}$$
$$\text{UncoveredFundShare}(k) = 1.0 - \text{ReportedCoverageRatio}(k)$$

Portföy seviyesinde kapsanmayan toplam fon payı:
$$\text{PortfolioUncoveredValue} = \sum_{k \in \text{ETFs}} \left( \text{PositionValuation}(\text{ETF}_k) \times \text{UncoveredFundShare}(k) \right)$$
$$\text{PortfolioUncoveredWeight} = \frac{\text{PortfolioUncoveredValue}}{\text{DenominatorValuation}}$$

*Kural:* Bilinen şirketlerin ağırlıkları asla $\frac{w_{k, C}}{\text{ReportedCoverageRatio}(k)}$ şeklinde yukarı ölçeklenemez (re-normalization yasaktır). Kapsanmayan pay raporda ayrı bir maruziyet kalemi olarak gösterilmelidir.

### 4.3 Fonlar Arası İkili Örtüşme Formülü (Fund Overlap)
İki fon ($A$ ve $B$) arasındaki bileşen örtüşmesi:
$$\text{Overlap}(A, B) = \sum_{i \in (H_A \cap H_B)} \min(w_{A, i}, w_{B, i})$$

Burada $H_A$ ve $H_B$ sırasıyla $A$ ve $B$ fonlarının raporlanan varlık kümeleridir.
- $\text{Overlap}(A, B) \in [0.0, 1.0]$.
- Eğer $A$ ve $B$ tamamen aynı endeksi aynı ağırlıklarla takip ediyorsa $\text{Overlap}(A, B) = \min(\text{Coverage}_A, \text{Coverage}_B)$.
- İki fonun hiçbir ortak hissesi yoksa $\text{Overlap}(A, B) = 0.0$.

### 4.4 ADR ve Çift Sınıflı Hisse Eşleme Kuralları
- **Çift Sınıflı Hisseler (Dual-Class):** Alphabet Inc. Class A (`GOOGL`, US02079K3059) ve Class C (`GOOG`, US02079K1079) nihai ekonomik şirket seviyesinde `Alphabet Inc.` altında birleştirilir; ancak oy hakkı ve menkul kıymet ayrımı alt dökümde saklanır.
- **ADR / GDR Konsolidasyonu:** TSM ADR (US8740391003) ile TSMC Ordinary (TW0002330008) aynı ekonomik şirket altında konsolide edilir; ancak saklama ve borsa riski notu eklenir.

---

## 5. Çıktı Sözleşmesi ve Şeması (Strict JSON Output Schema)

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "LookthroughResultPayload",
  "type": "object",
  "required": [
    "metadata",
    "consolidated_companies",
    "uncovered_exposure",
    "pairwise_fund_overlap",
    "sector_breakdown",
    "geographic_breakdown",
    "concentration_metrics",
    "synthesis_notes"
  ],
  "properties": {
    "metadata": {
      "type": "object",
      "required": ["snapshot_id", "execution_timestamp", "denominator_mode", "total_valuation_eur", "total_uncovered_weight_pct"],
      "properties": {
        "snapshot_id": {"type": "string"},
        "execution_timestamp": {"type": "string", "format": "date-time"},
        "denominator_mode": {"type": "string", "enum": ["TOTAL_PORTFOLIO_INCLUDING_CASH", "INVESTED_EQUITY_ONLY"]},
        "total_valuation_eur": {"type": "number"},
        "total_uncovered_weight_pct": {"type": "number"}
      }
    },
    "consolidated_companies": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["rank", "issuer_id", "company_name", "total_exposure_eur", "portfolio_weight_pct", "sources_breakdown"],
        "properties": {
          "rank": {"type": "integer"},
          "issuer_id": {"type": "string"},
          "company_name": {"type": "string"},
          "primary_country": {"type": "string"},
          "primary_sector": {"type": "string"},
          "direct_holding_eur": {"type": "number"},
          "etf_derived_eur": {"type": "number"},
          "total_exposure_eur": {"type": "number"},
          "portfolio_weight_pct": {"type": "number"},
          "sources_breakdown": {
            "type": "array",
            "items": {
              "type": "object",
              "required": ["source_instrument_id", "source_ticker", "contribution_eur", "weight_in_source_fund"],
              "properties": {
                "source_instrument_id": {"type": "string"},
                "source_ticker": {"type": "string"},
                "contribution_eur": {"type": "number"},
                "weight_in_source_fund": {"type": "number"}
              }
            }
          }
        }
      }
    },
    "uncovered_exposure": {
      "type": "object",
      "required": ["total_uncovered_eur", "total_uncovered_pct", "by_fund"],
      "properties": {
        "total_uncovered_eur": {"type": "number"},
        "total_uncovered_pct": {"type": "number"},
        "by_fund": {
          "type": "array",
          "items": {
            "type": "object",
            "required": ["instrument_id", "ticker", "fund_uncovered_ratio", "uncovered_value_eur"],
            "properties": {
              "instrument_id": {"type": "string"},
              "ticker": {"type": "string"},
              "fund_uncovered_ratio": {"type": "number"},
              "uncovered_value_eur": {"type": "number"}
            }
          }
        }
      }
    },
    "pairwise_fund_overlap": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["fund_a_ticker", "fund_b_ticker", "overlap_score", "shared_holdings_count", "top_shared_holdings"],
        "properties": {
          "fund_a_ticker": {"type": "string"},
          "fund_b_ticker": {"type": "string"},
          "overlap_score": {"type": "number", "minimum": 0, "maximum": 1},
          "shared_holdings_count": {"type": "integer"},
          "top_shared_holdings": {
            "type": "array",
            "items": {
              "type": "object",
              "properties": {
                "company_name": {"type": "string"},
                "weight_in_a": {"type": "number"},
                "weight_in_b": {"type": "number"},
                "min_weight": {"type": "number"}
              }
            }
          }
        }
      }
    },
    "sector_breakdown": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["sector", "total_value_eur", "weight_pct"],
        "properties": {
          "sector": {"type": "string"},
          "total_value_eur": {"type": "number"},
          "weight_pct": {"type": "number"}
        }
      }
    },
    "geographic_breakdown": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["country", "total_value_eur", "weight_pct"],
        "properties": {
          "country": {"type": "string"},
          "total_value_eur": {"type": "number"},
          "weight_pct": {"type": "number"}
        }
      }
    },
    "concentration_metrics": {
      "type": "object",
      "required": ["top_5_weight_pct", "top_10_weight_pct", "herfindahl_hirschman_index"],
      "properties": {
        "top_5_weight_pct": {"type": "number"},
        "top_10_weight_pct": {"type": "number"},
        "herfindahl_hirschman_index": {"type": "number"}
      }
    },
    "synthesis_notes": {
      "type": "array",
      "items": {"type": "string"}
    }
  }
}
```

---

## 6. Uç Durumlar ve Çekişmeli Örnekler (Edge Cases & Fallbacks)
1. **Holding Dosyası Bulunamayan ETF:** Eğer portföydeki bir ETF'in holdings kataloğu boşsa veya temin edilememişse, o ETF'i portföyden silme. Kapsama oranını 0.0 kabul et ve pozisyon tutarını doğrudan `UNCOVERED_ETF_HOLDINGS` hanesine yaz.
2. **Negatif Ağırlıklı Türev / Nakit Bileşenleri:** Bazı ETF factsheet'lerinde vadeli işlem teminatı veya döviz hedgesi nedeniyle negatif ağırlıklar (`-0.02%`) yer alabilir. Bu değerleri sıfırlama veya mutlak değere çevirme; matematiksel toplamda netleştirmeye dahil et.
3. **Nakit Dahil vs Hariç Payda:** Kullanıcı toplam portföyü (nakit dahil) seçtiğinde toplam ağırlıklar toplamı `(Hisseler + Kapsanmayan Fon + Nakit)` %100 olmalıdır. Yatırılmış hisse seçildiğinde nakit hariç tutulur.
4. **Sentetik UCITS Takas Sepeti (Substitute Basket):** Xtrackers veya Amundi swap-tabanlı fonlarda holding listesi Japon veya ABD hisselerinden oluşurken endeks MSCI EM olabilir. Girdide `replication_method == "SYNTHETIC"` ise konsolidasyon tablosunda "Teminat Sepeti Maruziyeti" ile "Ekonomik Endeks Hedefi" arasındaki farkı `synthesis_notes` içinde açıkça belirt.

---

## 7. Kabul Kriterleri ve Doğrulama Listesi (Acceptance Criteria)
- [ ] Konsolide şirket değerleri + Kapsanmayan fon değeri + Nakit (eğer nakit modu seçildiyse) = Portföy Toplam Değeri ($\pm 0.01$ EUR tolerans).
- [ ] Bütün $\text{Overlap}(A, B)$ skorları $[0.0, 1.0]$ aralığında ve $\text{Overlap}(A, B) = \text{Overlap}(B, A)$.
- [ ] Hiçbir kısmi fon sepeti re-normalize edilerek %100'e tamamlanmamış.
- [ ] Çıktı geçerli bir JSON belgesi olup JSON şemasını %100 doğrulamaktadır.
