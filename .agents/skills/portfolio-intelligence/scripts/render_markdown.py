"""Turkish reports from the same source bundle as the HTML dashboard."""
from datetime import datetime
from engine import run_all_engines


def fmt_num(value, places=2):
    if value is None:
        return "—"
    return f"{value:,.{places}f}".replace(",", "_").replace(".", ",").replace("_", ".")


def fmt_cur(value, currency="EUR"):
    return "—" if value is None else ("€" if currency == "EUR" else currency + " ") + fmt_num(value)


def fmt_change(quote, key):
    value = quote.get("changes", {}).get(key)
    if value is None:
        return "—"
    return ("+" if value > 0 else "") + fmt_num(value) + " " + quote.get("change_unit", "")


def text(value):
    return str(value or "—").replace("|", "\\|").replace("\n", " ")


def render_portfolio(data):
    p = data["portfolio"]
    lines = ["## Kaydedilen portföy", "",
             f"**Ekranda görünen toplam: {fmt_cur(p['snapshot_total'], p['currency'])}.** "
             "Bu, gönderilen görüntünün kaydıdır; güncel portföy değeri hesaplanmadı.", "",
             f"Kayıt tarihi: {p['registered_on'] or 'bilinmiyor'} · Görüntünün fiyat zamanı: {p['observed_at'] or 'bilinmiyor'}.", "",
             "| Fon | ISIN | Yaklaşık ekran tutarı | Görünen fonlar içindeki pay |",
             "|---|---|---:|---:|"]
    for pos in p["positions"]:
        lines.append(f"| {text(pos['fund_name'])} | {text(pos['isin'])} | "
                     f"{fmt_cur(pos['snapshot_value'], p['currency'])} | {fmt_num(pos['snapshot_weight'])} % |")
    lines.extend(["", f"Yuvarlanmış satırların toplamı: {fmt_cur(p['visible_sum'], p['currency'])}; "
                  f"ekran başlığıyla fark: {fmt_cur(p['rounding_difference'], p['currency'])}. "
                  "Ağırlıklar bu satır toplamından hesaplanır; nakit oranı bilinmiyor.", "",
                  "ISIN'ler fon adı ve birikimli sınıfla eşleştirildi. Broker belgesiyle teyit bekliyor. "
                  "Hedef dağılım veya yeniden dengeleme kuralı belirlenmedi.", ""])
    return "\n".join(lines)


def render_verified_funds(data):
    lines = ["## Kaynaklı Fon Bilgileri", "",
             "Alanlar fon bilgi kaydından okunur; boş alan bilinmiyor demektir. "
             "Referans kotasyonlar kullanıcının işlem borsası değildir.", "",
             "| Fon Adı | ISIN | İzlenen Endeks | Gider Oranı (TER) | Replikasyon / Dağıtım | Kur / Hedge | Resmi Kaynak |",
             "|---|---|---|---:|---|---|---|"]
    for pos in data["portfolio"]["positions"]:
        v = pos.get("verified", {})
        ter_str = f"%{fmt_num(v.get('ter_percent'))}" if v.get("ter_percent") is not None else "—"
        repl_dist = f"{text(v.get('replication_method'))} · {text(v.get('distribution_policy'))}"
        fx_hedge = f"{text(v.get('base_currency'))} · {text(v.get('hedge_status_tr'))}"
        lines.append(f"| {text(v.get('legal_name', pos['fund_name']))} | {text(pos['isin'])} | "
                     f"{text(v.get('benchmark_index', '—'))} | {ter_str} | {text(repl_dist)} | "
                     f"{text(fx_hedge)} | [Kaynak]({v.get('source_url') or pos['source_url']}) |")
    for pos in data["portfolio"]["positions"]:
        v = pos.get("verified", {})
        if v:
            lines.extend(["", f"- {pos['isin']} · Belge tarihi: {v.get('document_date') or 'belirtilmemiş'} · "
                          f"erişim: {v.get('retrieved_at') or 'bilinmiyor'}."])
        if v.get("verification_note"):
            lines.append("  " + text(v["verification_note"]))
    return "\n".join(lines)


def render_research(data):
    res = data.get("research", {})
    state = res.get("state", "Araştırma kaydı güncellenemedi")
    date_str = res.get("date") or "Tarih yok"
    content = res.get("data")
    lines = [f"## Günlük ETF Araştırması ({date_str}) — {state}", "",
             res.get("verification_label", "İçerik doğrulaması kayıtlı değil"), ""]
    if not content:
        lines.append(f"Araştırma verisi henüz güncellenmedi veya okunamadı ({state}). "
                     "Kaynaklı güncel araştırma için `$etf-yatirim-masasi Bugünkü ETF özetini hazırla` çağrısı yapılabilir.")
        return "\n".join(lines)
    if content.get("verification_note"):
        lines.extend([text(content["verification_note"]), ""])
    macro = content.get("macro_summary", {})
    if macro:
        lines.append(f"### Makro Durum: {macro.get('headline', '—')}")
        lines.append(f"*Gözlem dönemleri: {macro.get('observation_dates', '—')}*")
        lines.append("")
        for fact in macro.get("facts", []):
            lines.append(f"- **Olgu:** {fact}")
        for source in macro.get("sources", []):
            lines.append(f"- [Kaynak: {text(source.get('title'))}]({source['url']}) · "
                         f"yayın: {source.get('published_at') or source.get('date') or 'belirtilmemiş'} · "
                         f"erişim: {source.get('retrieved_at') or 'bilinmiyor'}")
        if macro.get("economic_inference"):
            lines.append("")
            lines.append(f"**Ekonomik Çıkarım:** {macro['economic_inference']}")
        lines.append("")
    funds = content.get("funds", [])
    if funds:
        lines.append("### Fon Bazında Ekonomik Aktarım ve Karşı Kanıtlar")
        lines.append("")
        for f in funds:
            lines.append(f"#### {f.get('fund_name')} ({f.get('isin')})")
            lines.append(f"- **Ne değişti:** {f.get('what_changed', '—')}")
            lines.append(f"- **Ekonomik aktarım mekanizması:** {f.get('economic_transmission', '—')}")
            lines.append(f"- **En güçlü karşı kanıt:** {f.get('counter_evidence', '—')}")
            lines.append(f"- **Sonraki kontrol koşulu:** {f.get('next_check', '—')}")
            sources_md = ", ".join(f"[{text(s.get('title'))}]({s['url']}) "
                                    f"(yayın: {s.get('published_at') or s.get('date') or 'belirtilmemiş'}; "
                                    f"erişim: {s.get('retrieved_at') or 'bilinmiyor'})" for s in f.get("sources", []))
            lines.append(f"- **Kaynaklar:** {sources_md}")
            lines.append("")
    if content.get("disclaimer"):
        lines.append(f"*{content['disclaimer']}*")
    return "\n".join(lines)


def render_macro(data):
    lines = ["## Piyasa bağlamı", "",
             "Bunlar genel piyasa göstergeleridir; portföy getirisi veya atanmış benchmark değildir. "
             "İçinde bulunulan seansın günlük mumu dışarıda bırakılır; canlı fiyat gösterilmez. "
             "Değişimler dağıtım içermeyen fiyat değişimidir. Faiz değişimi baz puan, VIX değişimi puandır.", "",
             "| Gösterge | Değer / birim | 1 seans | 5 seans | Kapanış tarihi | Durum |",
             "|---|---:|---:|---:|---|---|"]
    sources = []
    for item in data["market"]:
        q = item["quote"]
        if q:
            lines.append(f"| [{item['name']}]({q['source_url']}) | {fmt_num(q['price'], 4 if item['kind']=='fx' else 2)} {item['unit']} | "
                         f"{fmt_change(q, '1d')} | {fmt_change(q, '5d')} | {q['bar_date']} | {item['state']} |")
            sources.append(f"- {item['symbol']} · {q['source']} · çekim: {q['retrieved_at']} · borsa saati: {q['exchange_timezone']}.")
        else:
            lines.append(f"| {item['name']} | — | — | — | — | {item['state']} |")
    lines.extend(["", *sources])
    if data["fetch"]:
        fetch = data["fetch"]
        lines.extend(["", f"Son indirme: {fetch['success']}/{fetch['requested']} gösterge; {fetch['at']}."])
    failures = [m for m in data["market"] if m.get("error")]
    if failures:
        lines.extend(["", "Kaynak erişimi başarısız: " + ", ".join(m["symbol"] for m in failures) +
                      ". Varsa önceki tarihli kayıt korunur ve eski olarak işaretlenir."])
    return "\n".join(lines)


def render_funds(data):
    lines = ["## Fon kapsamı ve kaynaklar", "",
             "Maruziyetler fon adlarının tanımıdır; güncel sepet örtüşmesi ölçülmedi. "
             "Resmi kaynaklar kendiliğinden güncellenmiş haber sayılmaz.", ""]
    for pos in data["portfolio"]["positions"]:
        lines.append(f"- **{text(pos['fund_name'])}** — {text(pos['theme'])}. "
                     f"[Fon kaynağı]({pos['source_url']}) · {pos['isin']}")
    lines.extend(["", "Kaynaklı güncel haber veya tez araştırması için: "
                  "`$etf-yatirim-masasi Bugünkü ETF özetini hazırla`. "
                  "Yerel pano kendi başına haber araştırması yapmaz."])
    return "\n".join(lines)


def render_report(mode="daily", data=None, root=None):
    data = data or run_all_engines(root=root)
    heading = f"# ETF Yatırım Masası\n\nRapor üretimi: {data['generated_at']} ({data['timezone']}).\n"
    if mode == "macro":
        return heading + "\n" + render_macro(data)
    if mode == "research":
        return heading + "\n" + render_research(data)
    if mode in {"themes", "news"}:
        return heading + "\n" + render_funds(data)
    sections = [
        heading,
        render_portfolio(data),
        render_verified_funds(data),
        render_research(data),
        render_macro(data),
        render_funds(data),
        "## Eksik kayıtlar\n\n" + "\n".join(f"- {name}: {reason}" for name, reason in data["missing"])
    ]
    if data["warnings"]:
        sections.append("\n".join("- " + warning for warning in data["warnings"]))
    return "\n\n".join(sections)
