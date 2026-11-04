# Harici Yapay Zeka Karar ve Algoritma Prompt Şartnameleri (External AI Prompts)

Bu dizin, ETF Yatırım Masası'nın **R4 mimari şartı** ("Karar ve Algoritma Bileşenleri İçin Şartname/Prompt Üretimi") ve nihai sistem tasarım belgesi (§2.2) uyarınca oluşturulmuş 7 temel harici yapay zeka şartname dokümanını içerir.

---

## 1. Mimari İlke (R4 Architectural Principle)

> **Kod ile Veri ve Mühür, Harici AI ile Senaryo ve Optimizasyon:**  
> Sistem çekirdeği (Python 3.13) yalnızca veri çeker, doğrular, mühürler ve SQLite veritabanına ekler.  
> Finansal optimizasyon, karar mantığı, portföy rebalansı, değerleme senaryoları ve derin araştırma mantığı **Python kodu ile değil**, harici akıl yürütme yapay zekasına (Reasoning LLM: Gemini Pro, Claude Sonnet/Opus, GPT-4o) sunulmak üzere bu dizindeki yapılandırılmış şartnamelerle yönetilir.
> 
> Python tarafında yalnızca bu belgeleri diskten okuyan, SHA-256 özetini alan ve şablon değişkenlerini dolduran `masa.prompts.loader.PromptLoader` modülü yer alır. `loader.py` içerisinde **sıfır finansal veya karar kodu** bulunmaktadır.

---

## 2. Standart 7 Bölümlü Mühendislik Çerçevesi

Dizindeki her şartname dokümanı istisnasız aşağıdaki 7 standart bölümü içerir:

1. **Metadata ve Yönetim (Metadata & Governance):** Şartname ID, sürüm, hedef model ailesi, girdi/çıktı sözleşmesi, yetki sınırı.
2. **Rol, Sistem Bağlamı ve Sınırlar (Role & Scope Constraints):** Model persona, broker izolasyonu, halüsinasyon yasağı, nakit kuralları.
3. **Girdi Şeması ve Değişkenler (Input Schema - Strict JSON):** Beklenen JSON girdi sözleşmesi ve tipleri.
4. **Matematiksel Formülasyon ve Alan Kuralları (Mathematical Formulation):** Amaç fonksiyonları, kısıt denklemleri, maliyet cezaları, kök bulma algoritmaları.
5. **Çıktı Sözleşmesi ve Şeması (Strict JSON Output Schema):** Katı JSON çıktısı, alan tanımları (serbest metin veya markdown sohbeti yasaktır).
6. **Uç Durumlar ve Çekişmeli Örnekler (Edge Cases & Fallbacks):** Tekil kovaryans, yetersiz nakit, geniş spread, vergi kilidi çözümleri.
7. **Kabul Kriterleri ve Doğrulama Listesi (Acceptance Criteria):** Ağırlık toplamı testi, negatif bakiye denetimi, mutlak tutarlılık kuralları.

---

## 3. Şartname Kataloğu

| Dosya Adı | Şartname ID | Hedef Model | Açıklama ve Temel Yetenekler |
|---|---|---|---|
| `portfolio_optimization.md` | `SPEC-PROMPT-OPT-001` | Reasoning LLM | Mean-Variance, Risk Parity, Black-Litterman; tek yönlü makas maliyeti ((ask-mid)/mid, (mid-bid)/mid); nakit kaynağı ve payda etkisi (`EXISTING_CASH`, `EXTERNAL_INFLOW`, `EXTERNAL_OUTFLOW`); UCITS 5/10/40 kontrolü. |
| `rebalancing.md` | `SPEC-PROMPT-REBAL-001` | Reasoning LLM | Çift bantlı tolerans tetikleme mantığı, portföy ciro (turnover) tavanı, asgari işlem bileti büyüklüğü (€50/€100), Almanya vergi farkındalığı (%26,375) ve Sparplan organik dengeleme (`INFLOW_ONLY`), iki fazlı emir sıralama (PHASE_1_SELL -> PHASE_2_BUY). |
| `performance_engine.md` | `SPEC-PROMPT-PERF-001` | Reasoning LLM / GIPS | Çoklu tarihli nakit akışlarıyla Modified Dietz, alt dönem zincirlemeli True TWR, sayısal kök bulma (Newton-Raphson + Brent) ile XIRR, WAC vs FIFO maliyet muhasebesi ayrımı, hesap sınırı dış akış kuralı. |
| `etf_lookthrough.md` | `SPEC-PROMPT-LOOKTHROUGH-001` | Reasoning LLM | Çoklu ETF holdings ayrıştırması, konsolide nihai şirket/ihraççı maruziyeti, kısmi sepet kapsam oranı (suni %100 re-normalizasyon yasağı, `UNCOVERED_ETF_HOLDINGS`), fonlar arası ikili örtüşme ($\sum \min(w_A, w_B)$), ADR/GDR ekonomik eşlemesi. |
| `factor_and_valuation_models.md` | `SPEC-PROMPT-FACTOR-VAL-001` | Reasoning LLM | Fama-French 5 Faktör + Momentum + Düşük Volatilite regresyonları (beta, t-stat, p-value, $R^2$), DCF (WACC, terminal büyüme tavanı $g \le 3.0\%$), DDM (temettü ödemeyen şirket kısıtı), Çarpanlar ve olasılık ağırlıklı Boğa/Taban/Ayı senaryo bantları. |
| `red_team_critic.md` | `SPEC-PROMPT-CRITIC-001` | Bağımsız Model Ailesi | Adli denetim (Forensic Audit), halüsinasyon ürünü sahte korelasyon tespiti ($|\rho_{\text{claimed}} - \rho_{\text{empirical}}| > 0.20$), dayanağı olmayan makro iddialar, matematiksel tutarsızlıklar, hata taksonomisi (`FATAL_DEFECT` -> `REJECT`, `MATERIAL_WARNING` -> `REVISE_REQUIRED`, `OBSERVATIONAL_NOTE` -> `APPROVE`), yanlış alarm kalibrasyonu. |
| `llm_research_agent.md` | `SPEC-PROMPT-RESEARCH-001` | Reasoning LLM | Yapılandırılmış kanıt paketi (`EvidenceBundleInput`) alımı, 5'li iddia sınıflandırması (`[fact \| sourced_estimate \| computation \| inference \| unknown]`), anlamsal atıf etiketleri (`[[source:ID#sec]]`, `[[metric:ID]]`, `[[quote:ID]]`), prompt enjeksiyonu savunması, zorunlu karşı-tez ve falsifikasyon tetikleyicileri. |

---

## 4. Kullanım ve Şablon Yükleme Kılavuzu

Python tarafından prompt dokümanlarını güvenle yüklemek ve SHA-256 özetini denetim zincirine kaydetmek için:

```python
from masa.prompts.loader import PromptLoader

loader = PromptLoader()

# 1. Zorunlu tüm prompt belgelerinin varlığını ve bütünlüğünü doğrula
verified_prompts = loader.validate_required_prompts()

# 2. Belirli bir promptu yükle
prompt = loader.load_prompt("llm_research_agent")
print(f"Loaded: {prompt.metadata.name}, SHA-256: {prompt.metadata.sha256}")

# 3. Güvenli değişken yerleştirmesi yap (JSON süslü parantezlerini bozmaz)
rendered = prompt.render({
    "EVIDENCE_BUNDLE_JSON": "{\"bundle_id\": \"BND-01\"}",
}, allow_missing=True)

# 4. Denetim manifestosunu al (audit_events için)
manifest = loader.get_audit_manifest()
```
