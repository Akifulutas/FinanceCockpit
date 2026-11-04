"""A local, self-contained ETF dashboard. No embedded market fiction."""
from html import escape
from pathlib import Path
from urllib.parse import urlsplit
from engine import WORKSPACE_DIR, run_all_engines
from render_markdown import fmt_num, fmt_cur, fmt_change


def safe_url(value):
    parts = urlsplit(value or "")
    return escape(value, quote=True) if parts.scheme in {"https", "http"} and parts.netloc else "#"


def e(value):
    return escape(str(value if value is not None else "—"), quote=True)


def render_document(data):
    p = data["portfolio"]
    colors = ["#51dbc6", "#81a6ff", "#dab0f5", "#e8c17b"]
    funds, bars, sources, market = [], [], [], []
    for i, pos in enumerate(p["positions"]):
        color = colors[i % len(colors)]
        weight = pos["snapshot_weight"]
        width = min(100, max(0, weight or 0))
        funds.append(f'''<tr><td><span class="dot" style="background:{color}"></span><strong>{e(pos['fund_name'])}</strong>
            <small>{e(pos['theme'])}</small></td><td class="mono">{e(pos['isin'])}<small>İsimden eşleşme · broker teyidi bekliyor</small></td>
            <td class="num">{e(fmt_cur(pos['snapshot_value'], p['currency']))}</td><td class="num">{e(fmt_num(weight))}%</td></tr>''')
        bars.append(f'<div style="width:{width:.8f}%;background:{color}" title="{e(pos["fund_name"])}: {e(fmt_num(weight))}%"></div>')
        sources.append(f'''<a class="source" href="{safe_url(pos['source_url'])}" target="_blank" rel="noopener noreferrer">
            <span>{e(pos['fund_name'])}<small class="mono">{e(pos['isin'])}</small></span><span aria-hidden="true">↗</span></a>''')

    # Verified funds table rows
    verified_rows = []
    for pos in p["positions"]:
        v = pos.get("verified", {})
        ter_str = f"%{fmt_num(v.get('ter_percent'))}" if v.get("ter_percent") is not None else "—"
        ter_note = f"<small class=\"note-text\">{e(v.get('ter_note', ''))}</small>" if v.get("ter_note") else ""
        listings = v.get("reference_exchange_listings", [])
        listings_str = " · ".join(f"{l.get('ticker')} ({l.get('exchange')})" for l in listings[:3]) if listings else "—"
        verified_rows.append(f'''<tr>
            <td class="col-name"><strong>{e(v.get('legal_name', pos['fund_name']))}</strong><small>{e(v.get('issuer', 'İhraççı'))} · {e(pos['theme'])}</small></td>
            <td class="col-isin mono">{e(pos['isin'])}<small>{e(v.get('share_class', 'Pay sınıfı'))}</small></td>
            <td class="col-bench">{e(v.get('benchmark_index', '—'))}</td>
            <td class="col-ter"><span class="mono ter-value"><strong>{e(ter_str)}</strong></span>{ter_note}</td>
            <td class="col-repl">{e(v.get('replication_method'))}<small>{e(v.get('distribution_policy'))}</small></td>
            <td class="col-fx">{e(v.get('base_currency'))}<small>{e(v.get('hedge_status_tr'))}</small></td>
            <td class="col-ref"><small>{e(listings_str)}</small><a href="{safe_url(v.get('source_url') or pos['source_url'])}" target="_blank" rel="noopener noreferrer" class="link-pill">Kaynak ↗</a>
            <small>Belge: {e(v.get('document_date') or 'tarih belirtilmemiş')}<br>Erişim: {e(v.get('retrieved_at') or 'bilinmiyor')}</small>
            <small>{e(v.get('verification_note') or '')}</small></td>
        </tr>''')

    # Research section cards
    res = data.get("research", {})
    res_state = res.get("state", "Araştırma kaydı güncellenemedi")
    res_date = res.get("date") or "Tarih yok"
    res_data = res.get("data")
    research_html = []
    if res_data:
        research_html.append(f'<p class="note">{e(res.get("verification_label", "İçerik doğrulaması kayıtlı değil"))}: {e(res_data.get("verification_note") or "Kayıt tarihi içeriğin doğrulandığı anlamına gelmez.")}</p>')
        macro = res_data.get("macro_summary", {})
        if macro:
            facts_list = "".join(f"<li><strong>Olgu:</strong> {e(fact)}</li>" for fact in macro.get("facts", []))
            inference_p = f'<div class="macro-inference"><strong>Ekonomik Çıkarım:</strong> {e(macro.get("economic_inference"))}</div>' if macro.get("economic_inference") else ""
            macro_sources = "".join(f'<a class="source-tag" href="{safe_url(s["url"])}" target="_blank" rel="noopener noreferrer">{e(s.get("title"))} · yayın: {e(s.get("published_at") or s.get("date") or "belirtilmemiş")} · erişim: {e(s.get("retrieved_at") or "bilinmiyor")}</a>' for s in macro.get("sources", []))
            research_html.append(f'''<article class="research-summary-card">
                <div class="eyebrow">MAKRO DURUM VE GÖZLEMLER</div>
                <h3>{e(macro.get('headline', 'Genel Görünüm'))}</h3>
                <small class="meta-date">Gözlem dönemleri: {e(macro.get('observation_dates', '—'))}</small>
                <ul class="facts-list">{facts_list}</ul>
                {inference_p}
                <div class="research-sources">{macro_sources}</div>
            </article>''')
        funds_research = res_data.get("funds", [])
        cards_html = []
        for rf in funds_research:
            sources_pills = "".join(f'<a href="{safe_url(s.get("url"))}" target="_blank" rel="noopener noreferrer" class="source-tag">{e(s.get("title"))} · yayın: {e(s.get("published_at") or s.get("date") or "belirtilmemiş")} · erişim: {e(s.get("retrieved_at") or "bilinmiyor")} ↗</a>' for s in rf.get("sources", []))
            cards_html.append(f'''<article class="fund-research-card">
                <div class="card-head">
                    <div>
                        <h4>{e(rf.get('fund_name'))}</h4>
                        <span class="mono tag">{e(rf.get('isin'))}</span> <span class="tag">{e(rf.get('reference_ticker'))}</span>
                    </div>
                </div>
                <div class="research-row">
                    <span class="label">Ne değişti?</span>
                    <p>{e(rf.get('what_changed'))}</p>
                </div>
                <div class="research-row">
                    <span class="label">Ekonomik aktarım mekanizması:</span>
                    <p>{e(rf.get('economic_transmission'))}</p>
                </div>
                <div class="research-row warning-box">
                    <span class="label">En güçlü karşı kanıt:</span>
                    <p>{e(rf.get('counter_evidence'))}</p>
                </div>
                <div class="research-row check-box">
                    <span class="label">Sonraki kontrol koşulu:</span>
                    <p>{e(rf.get('next_check'))}</p>
                </div>
                <div class="research-sources">{sources_pills}</div>
            </article>''')
        research_html.append(f'<div class="research-grid">{"".join(cards_html)}</div>')
        if res_data.get("disclaimer"):
            research_html.append(f'<p class="note" style="margin-top:16px;"><em>{e(res_data.get("disclaimer"))}</em></p>')
    else:
        research_html.append(f'''<div class="empty-research">
            <p><strong>Araştırma kaydı henüz güncellenmedi veya okunamadı ({e(res_state)}).</strong></p>
            <p>Dört fonun maruziyetlerine ilişkin kaynaklı günlük özet hazırlamak için terminalden veya sohbetten:<br>
            <code>$etf-yatirim-masasi Bugünkü ETF özetini hazırla</code> çağrısını yapabilirsiniz.</p>
        </div>''')

    for item in data["market"]:
        q = item["quote"]
        if q:
            value = fmt_num(q["price"], 4 if item["kind"] == "fx" else 2)
            change = q.get("changes", {}).get("1d")
            cls = "up" if change is not None and change > 0 else "down" if change is not None and change < 0 else ""
            market.append(f'''<article class="market-card"><div class="eyebrow">{e(item['name'])}</div>
                <div class="quote">{e(value)} <span>{e(item['unit'])}</span></div>
                <div class="change {cls}">{e(fmt_change(q, '1d'))} <span>1 seans</span></div>
                <p>5 seans: {e(fmt_change(q, '5d'))}</p>
                <div class="divider"></div><small>Kapanış: {e(q['bar_date'])}<br>{e(item['state'])}<br>
                Çekim: {e(q['retrieved_at'])}<br>{e(q['exchange_timezone'])}</small>
                <a href="{safe_url(q['source_url'])}" target="_blank" rel="noopener noreferrer">Yahoo Finance ↗</a></article>''')
        else:
            market.append(f'''<article class="market-card empty"><div class="eyebrow">{e(item['name'])}</div>
                <div class="quote">—</div><p>Tarihli veri yok</p>
                <small>{'Son veri isteği başarısız.' if item.get('error') else 'İsteğe bağlı piyasa güncellemesiyle görünür.'}</small></article>''')
    fetch = data["fetch"]
    fetch_note = (f"Son indirme: {fetch['success']}/{fetch['requested']} gösterge · {fetch['at']}"
                  if fetch else "Piyasa göstergeleri henüz doğrulanmış bir kayıt içermiyor.")
    warnings = "".join(f"<p>{e(warning)}</p>" for warning in data["warnings"])
    missing = "".join(f"<div><strong>{e(name)}</strong><p>{e(reason)}</p></div>" for name, reason in data["missing"])
    return '''<!doctype html><html lang="tr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="icon" href="data:,">
<title>ETF Yatırım Masası</title>
<style>
:root{color-scheme:dark;--bg:#0b1016;--panel:#121b24;--line:#253341;--text:#eef4fa;--muted:#a2b1c0;--accent:#51dbc6;--warn:#ffb454;--danger:#ff8077}
*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;background:var(--bg);color:var(--text);font:15px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;overflow-wrap:break-word}
a{color:var(--accent);text-decoration:none}a:hover{text-decoration:underline}a:focus-visible,button:focus-visible{outline:2px solid var(--accent);outline-offset:3px}
.wrap{max-width:1240px;margin:auto;padding:0 32px}header{border-bottom:1px solid var(--line);background:#0d151e;position:sticky;top:0;z-index:10}
.top{display:flex;align-items:center;justify-content:space-between;padding-top:16px;padding-bottom:16px;gap:20px}.brand{font-size:18px;font-weight:700}.brand span{color:var(--accent);padding-right:10px}
.badge{display:inline-block;border:1px solid #34524e;border-radius:30px;color:#9aebdc;padding:5px 12px;font-size:11px;letter-spacing:.06em;font-weight:600}
.badge-warn{border-color:#5c4424;color:#ffcf87;background:#24180d}
nav{display:flex;gap:20px;flex-wrap:wrap;padding-bottom:12px;border-top:1px solid #1a2530;padding-top:10px}nav a{font-size:13px;color:var(--muted);font-weight:500}nav a:hover{color:var(--text)}main{padding:30px 0 50px}
.eyebrow{font-size:11px;letter-spacing:.09em;text-transform:uppercase;font-weight:650;color:var(--muted)}h1{font-size:32px;line-height:1.2;margin:8px 0 10px;letter-spacing:-.025em}h2{font-size:20px;margin:0 0 5px;letter-spacing:-.02em}h3{font-size:16px;margin:0 0 8px}h4{font-size:15px;margin:0 0 4px}p{margin:0 0 12px}.intro{max-width:780px;color:var(--muted);font-size:14px}
.summary{display:grid;grid-template-columns:1.5fr 1fr 1fr;gap:16px;margin:24px 0}.card{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:22px}.total{background:linear-gradient(115deg,#173b3a,#14232d);border-color:#2c5755}.big{font-size:38px;font-weight:650;letter-spacing:-.04em;line-height:1.2;margin:8px 0}.subbig{font-size:24px;font-weight:600;margin:12px 0}.card p,.card small{font-size:12px;color:var(--muted)}
.section-head{display:flex;justify-content:space-between;gap:16px;align-items:flex-start;margin-bottom:18px}.section-head p{color:var(--muted);font-size:13px;margin:2px 0 0}.panel{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:24px;margin-top:24px;scroll-margin-top:70px}
.distribution{height:8px;border-radius:8px;overflow:hidden;display:flex;margin-bottom:20px}.distribution div+div{border-left:2px solid var(--panel)}
.table-wrap{overflow-x:auto;-webkit-overflow-scrolling:touch;width:100%;margin-bottom:8px}table{width:100%;border-collapse:collapse;min-width:720px}th{text-align:left;font-size:10px;letter-spacing:.07em;color:var(--muted);text-transform:uppercase;padding:0 10px 12px;white-space:nowrap}td{border-top:1px solid var(--line);padding:14px 10px;font-size:13px;vertical-align:middle}td strong{font-weight:600}td small{display:block;color:var(--muted);font-size:11px}.num{text-align:right;white-space:nowrap;font-variant-numeric:tabular-nums}.mono{font-family:ui-monospace,SFMono-Regular,Consolas,monospace}.dot{display:inline-block;width:7px;height:7px;border-radius:50%;margin-right:8px;vertical-align:2px}
.col-name{min-width:180px;max-width:260px}.col-isin{min-width:120px;max-width:150px}.col-bench{min-width:160px;max-width:240px}
.col-ter{min-width:130px;max-width:220px;white-space:normal;text-align:right}.ter-value{display:block;font-size:14px}.note-text{white-space:normal;line-height:1.35;margin-top:4px}
.col-repl{min-width:140px;max-width:190px}.col-fx{min-width:110px;max-width:150px}.col-ref{min-width:150px;max-width:220px}
.link-pill{display:inline-block;font-size:11px;padding:3px 8px;border:1px solid var(--line);border-radius:6px;margin-top:4px;color:var(--accent)}
.link-pill:hover{border-color:var(--accent)}
.note{font-size:12px;color:var(--muted);padding-top:12px;line-height:1.5}
.market-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px}.market-card{background:#0e1620;border:1px solid var(--line);border-radius:12px;padding:18px}.market-card .eyebrow{min-height:30px}.quote{font-size:26px;font-weight:600;font-variant-numeric:tabular-nums}.quote span{font-size:11px;font-weight:400;color:var(--muted)}.change{font-size:14px;margin:6px 0}.change span{font-size:11px;color:var(--muted);font-weight:400}.market-card p{font-size:12px;color:var(--muted);margin-bottom:0}.market-card a{font-size:11px;display:inline-block;margin-top:10px}.up{color:#67ddbb}.down{color:#ff9c96}.divider{border-top:1px solid var(--line);margin:10px 0}.empty .quote{color:#688196}.empty{min-height:160px}
.research-summary-card{background:#0d1620;border:1px solid #233446;border-radius:12px;padding:20px;margin-bottom:20px}
.facts-list{margin:10px 0 12px 18px;padding:0;font-size:13px}.facts-list li{margin-bottom:6px;color:var(--text)}
.meta-date{display:block;color:var(--muted);font-size:11px;margin-bottom:12px}
.macro-inference{background:#13222e;border-left:3px solid var(--accent);padding:10px 14px;font-size:13px;border-radius:0 8px 8px 0;margin-top:10px}
.research-grid{display:grid;grid-template-columns:1fr 1fr;gap:18px}.fund-research-card{background:#0e1722;border:1px solid var(--line);border-radius:12px;padding:18px;display:flex;flex-direction:column;gap:12px}
.card-head{display:flex;justify-content:space-between;align-items:flex-start;border-bottom:1px solid var(--line);padding-bottom:10px}
.tag{display:inline-block;font-size:10px;padding:2px 6px;border-radius:4px;background:#182533;color:#89a8c7;margin-left:4px}
.research-row{font-size:12.5px}.research-row .label{display:block;font-size:10.5px;letter-spacing:.05em;text-transform:uppercase;color:var(--muted);font-weight:600;margin-bottom:3px}.research-row p{margin:0;line-height:1.5}
.warning-box{background:#23190e;border-left:3px solid var(--warn);padding:8px 12px;border-radius:0 6px 6px 0}.warning-box .label{color:#ffcf87}
.check-box{background:#112028;border-left:3px solid #6cd5c2;padding:8px 12px;border-radius:0 6px 6px 0}.check-box .label{color:#9be9db}
.research-sources{display:flex;flex-wrap:wrap;gap:8px;padding-top:8px;border-top:1px solid #1a2734;margin-top:auto}
.source-tag{font-size:11px;padding:3px 8px;border-radius:5px;background:#152230;color:var(--accent);display:inline-block}
.source-tag:hover{background:#1e3245}
.empty-research{background:#0e1620;border:1px dashed var(--line);padding:24px;border-radius:12px;text-align:center;font-size:13px;color:var(--muted)}
.lower{display:grid;grid-template-columns:1.1fr 1fr;gap:20px;margin-top:24px}
.missing>div{border-bottom:1px solid var(--line);padding:14px 0}.missing>div:last-child{border:0}.missing strong{font-size:13px}.missing p{font-size:12px;color:var(--muted);margin:2px 0 0}
.source{display:flex;justify-content:space-between;gap:15px;align-items:center;padding:12px 0;border-bottom:1px solid var(--line);font-size:12px;color:var(--text)}.source:last-of-type{border:0}.source small{margin-top:4px}
footer{display:flex;justify-content:space-between;gap:20px;align-items:center;color:var(--muted);font-size:11px;margin-top:34px;padding-top:20px;border-top:1px solid var(--line)}
button{border:1px solid var(--line);background:var(--panel);color:var(--text);border-radius:7px;padding:7px 14px;cursor:pointer;font-size:12px;font-weight:500}button:hover{border-color:var(--accent);background:#1a2736}
@media(max-width:980px){.summary{grid-template-columns:1fr 1fr}.total{grid-column:1/-1}.research-grid{grid-template-columns:1fr}.market-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.lower{grid-template-columns:1fr}}
@media(max-width:560px){.wrap{padding:0 16px}.top{align-items:flex-start;flex-direction:column;gap:8px}h1{font-size:26px}.summary{grid-template-columns:1fr}.total{grid-column:auto}.panel,.card{padding:16px}.market-grid{grid-template-columns:1fr}.section-head,footer{flex-direction:column;align-items:flex-start}.big{font-size:32px}.table-wrap table{min-width:620px}}
@media print{
  :root{color-scheme:light;--bg:#ffffff;--panel:#ffffff;--line:#cbd1d7;--text:#152331;--muted:#4c5966;--accent:#087365;--warn:#8f5b00}
  body{background:#fff;color:#152331;font-size:12px;line-height:1.45}
  header{background:#fff;position:static;border-bottom:2px solid #152331}
  .wrap{padding:0;max-width:none}
  main{padding-top:12px;padding-bottom:12px}
  nav,button{display:none}
  .total,.card,.panel,.market-card,.fund-research-card,.research-summary-card{background:#fff!important;border:1px solid #cbd1d7!important;box-shadow:none!important}
  .summary{gap:10px;margin:14px 0}
  .big{font-size:26px;color:#152331}
  .subbig{font-size:18px;color:#152331}
  .panel{break-inside:auto;margin-top:16px;padding:14px}
  .market-card,.missing>div,tr,.source,.fund-research-card,.research-summary-card{break-inside:avoid;page-break-inside:avoid}
  .lower{display:block}
  .badge{color:#087365;border-color:#087365}
  .up,.down{color:var(--text)}
  a{color:var(--text);text-decoration:none}
  .tag,.source-tag,.link-pill{border:1px solid #cbd1d7;background:#f6f8fa;color:#152331}
  .warning-box{background:#fff8ee;border-left:3px solid #b87800}
  .check-box{background:#f0faf7;border-left:3px solid #087365}
  .macro-inference{background:#f4f7f9;border-left:3px solid #087365}
}
</style></head><body>
''' + f'''<header><div class="wrap"><div class="top"><div class="brand"><span>◈</span>ETF Yatırım Masası</div><div class="badge">ETF · UZUN VADELİ ARAŞTIRMA</div></div>
<nav aria-label="Bölümler">
<a href="#portfoy">Portföy kaydı</a>
<a href="#dogrulanmis-fonlar">Fon bilgi kaydı</a>
<a href="#arastirma">Günlük ETF araştırması</a>
<a href="#piyasa">Piyasa bağlamı</a>
<a href="#kayit">Eksik kayıtlar</a>
<a href="#kaynaklar">Fon kaynakları</a>
</nav></div></header>
<div class="wrap"><main><div class="eyebrow">KİŞİSEL ETF MASAN</div><h1>Önce kayıt, sonra yorum.</h1>
<p class="intro">Fon bilgi kayıtları, gönderdiğin ekran kaydı, tarihli piyasa göstergeleri ve kapsamı belirtilmiş maruziyet araştırması. Portföy tutarları gönderdiğin ekran görüntüsüne dayanır; güncel piyasa değeri ve getiri hesaplanmamıştır.</p>
<div class="summary"><article class="card total"><div class="eyebrow">EKRANDA GÖRÜNEN TOPLAM</div><div class="big">{e(fmt_cur(p['snapshot_total'], p['currency']))}</div><p>Gönderilen görüntünün kaydı · güncel değer hesaplanmadı</p></article>
<article class="card"><div class="eyebrow">KAYITLI ETF</div><div class="subbig">{len(p['positions'])} fon</div><p>Resmi ihraççı ve birikimli pay sınıfıyla doğrulanmış</p></article>
<article class="card"><div class="eyebrow">PORTFÖY GETİRİSİ</div><div class="subbig">Henüz hesaplanamıyor</div><p>Adet, maliyet ve tarihli hareketler eksik</p></article></div>

<section class="panel" id="portfoy"><div class="section-head"><div><h2>Kaydedilen portföy ekranı</h2><p>Yaklaşık ekran tutarları ve görünen fonlar içindeki payları</p></div><span class="badge">EKRAN KAYDI</span></div>
<div class="distribution" aria-hidden="true">{''.join(bars)}</div><div class="table-wrap"><table><thead><tr><th>Fon / maruziyet</th><th>Fon kimliği</th><th class="num">Ekran tutarı ≈</th><th class="num">Pay ≈</th></tr></thead><tbody>{''.join(funds)}</tbody></table></div>
<p class="note">Yuvarlanmış satır toplamı {e(fmt_cur(p['visible_sum'], p['currency']))}; ekran başlığıyla fark {e(fmt_cur(p['rounding_difference'], p['currency']))}. Paylar satır toplamından hesaplanır. Nakit oranı bilinmiyor. Hedef dağılım ve yeniden dengeleme kuralı belirlenmedi.</p></section>

<section class="panel" id="dogrulanmis-fonlar"><div class="section-head"><div><h2>Kaynaklı fon bilgi kaydı</h2><p>Alanlar kaynak kaydından okunur; boş alanlar bilinmiyor demektir</p></div><span class="badge">ÜRÜN BİLGİLERİ</span></div>
<div class="table-wrap"><table><thead><tr><th>Fon adı / ihraççı</th><th>ISIN / pay sınıfı</th><th>İzlenen endeks</th><th class="num">TER p.a.</th><th>Replikasyon / dağıtım</th><th>Baz döviz / hedge</th><th>Referans işlem hatları</th></tr></thead><tbody>{''.join(verified_rows)}</tbody></table></div>
<p class="note">Referans borsa ve işlem kodları kullanıcının brokerdaki işlem hattını doğrulamaz. Baz para birimi, işlem para birimi ve hedge durumu ayrı alanlardır. Belge ve erişim tarihleri her fonun kaynağında gösterilir.</p></section>

<section class="panel" id="arastirma"><div class="section-head"><div><h2>Günlük ETF araştırması</h2><p>Tarih: {e(res_date)} · Maruziyetler, ekonomik aktarım kanalları ve karşı kanıtlar</p></div><span class="badge {'' if res_state == 'Güncel araştırma kaydı' and res.get('verification_status') == 'reviewed' else 'badge-warn'}">{e(res_state.upper())}</span></div>
{''.join(research_html)}
</section>

<section class="panel" id="piyasa"><div class="section-head"><div><h2>Piyasa bağlamı</h2><p>Önceki seans günlük verileri · portföy performansından ayrı</p></div></div><div class="market-grid">{''.join(market)}</div>
<p class="note">{e(fetch_note)}</p><p class="note">İçinde bulunulan seansın günlük mumu dışarıda bırakılır; canlı fiyat gösterilmez. Endeks ve kur değişimleri dağıtımsız fiyat değişimidir. Faiz farkları baz puan (bp), VIX farkları puandır. 5 seans, son 6 günlük gözlemden hesaplanır. Bu göstergeler portföyüne atanmış bir benchmark değildir.</p>{warnings}</section>

<div class="lower"><section class="panel" id="kayit"><h2>Hesap için eksik kayıtlar</h2><div class="missing">{missing}</div><p class="note">İlk gerekli bilgiler: brokerda görünen ISIN, işlem borsası ve gerçek adet. Mevcut kayıt bu bilgiler gelene kadar ekran görüntüsü olarak korunur.</p></section>
<section class="panel" id="kaynaklar"><h2>Resmi fon kaynakları</h2><p class="note">Doğrulanmış ürün sayfaları ve ihraççı kütüphaneleri</p>{''.join(sources)}<p class="note">Kaynak bağlantıları güncel haber taraması anlamına gelmez. Haber ve tez araştırması ETF Yatırım Masası promptuyla veya kayıtlı araştırma dosyalarıyla yürütülür.</p></section></div>
<footer><div>Rapor üretimi: {e(data['generated_at'])} · {e(data['timezone'])}<br>Ekran kaydı: {e(p['registered_on'])} · Görüntüdeki fiyat zamanı: {e(p['observed_at'] or 'bilinmiyor')} · Araştırma kaydı: {e(res_date)}</div><button type="button" onclick="window.print()">Yazdır / PDF</button></footer>
</main></div></body></html>'''


def render_html_dashboard(root=None, data=None):
    root = Path(root or WORKSPACE_DIR)
    data = data or run_all_engines(root=root)
    reports = root / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    document = render_document(data)
    (reports / f"dashboard-{data['date']}.html").write_text(document, encoding="utf-8")
    (reports / "index.html").write_text(document, encoding="utf-8")
    return reports / "index.html"
