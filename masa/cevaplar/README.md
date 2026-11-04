# Harici Yapay Zeka Cevapları ve Kod Teslim Klasörü

Bu klasör, `masa/prompts/` altındaki şartnameleri başka bir yapay zekaya (Claude 3.5 Sonnet, OpenAI o1 vb.) ilettiğinizde aldığınız **kodları ve yanıtları yapıştırmanız için** hazırlanmıştır.

## Nasıl Kullanacaksınız?

1. `masa/prompts/` klasöründeki ilgili promptu (örneğin `performance_engine.md`) açıp yapay zekaya verin.
2. Yapay zekanın ürettiği Python kodunu veya açıklamalı yanıtı buradaki ilgili dosyaya yapıştırıp kaydedin:
   - `1_performance_engine.md` ➔ `performance_engine.md` promptunun yanıtı
   - `2_etf_lookthrough.md` ➔ `etf_lookthrough.md` promptunun yanıtı
   - `3_portfolio_optimization.md` ➔ `portfolio_optimization.md` promptunun yanıtı
   - `4_rebalancing.md` ➔ `rebalancing.md` promptunun yanıtı
   - `5_factor_and_valuation_models.md` ➔ `factor_and_valuation_models.md` promptunun yanıtı
   - `6_red_team_critic.md` ➔ `red_team_critic.md` promptunun yanıtı
   - `7_llm_research_agent.md` ➔ `llm_research_agent.md` promptunun yanıtı
3. Dosyayı kaydettikten sonra sohbette bana:
   > *"1_performance_engine.md dosyasına cevabı yapıştırdım"*
   demeniz yeterlidir.
4. Ben dosyayı okuyup içindeki Python kodunu doğrudan `masa/src/masa/...` altındaki ilgili modüle entegre edeceğim, birim testlerini çalıştırıp sonucu size raporlayacağım.

*(Dilerseniz dosyaya yapıştırmak yerine doğrudan sohbet mesajı olarak da buraya atabilirsiniz, ikisi de tamamen uygundur.)*
