"""Import user-supplied quote tables without executing their shell commands."""
import argparse
import csv
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import re

NUMBER = r"\d+(?:\.\d+)?"
ROW = re.compile(rf"^\s*(\S+)\s+([A-Z]{{2}}[A-Z0-9]{{10}})\s+"
                 rf"({NUMBER})\s+([A-Z]{{3}})\s+({NUMBER})\s+([A-Z]{{3}})\s+"
                 rf"({NUMBER})\s+([A-Z]{{3}})\s+({NUMBER})\s+({NUMBER})%\s+"
                 r"(N/A|true|false)\s+(\S+)\s*$")


def parse_quote_text(body):
    names = {isin: name for _, isin, name in re.findall(r'"([^"|]+)\|([^"|]+)\|([^"\n]+)"', body)}
    records, pending, batch = [], [], 0
    for line in body.splitlines():
        if re.match(r"^\s*TICKER\s+ISIN\s+BID", line):
            batch += 1
        match = ROW.match(line)
        if match:
            alias, isin, bid, bc, ask, ac, mid, mc, spread, spread_pct, outdated, stamp = match.groups()
            if len({bc, ac, mc}) != 1:
                raise ValueError("Kotasyon para birimleri uyuşmuyor")
            bid, ask, mid = Decimal(bid), Decimal(ask), Decimal(mid)
            if bid <= 0 or ask < bid or mid <= 0:
                raise ValueError("Kotasyon fiyatları geçersiz")
            observed = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
            if observed.tzinfo is None:
                raise ValueError("Kotasyon saat dilimi eksik")
            calculated_mid = (bid + ask) / 2
            record = {
                "batch": batch, "alias": alias, "isin": isin,
                "name_from_user_text": names.get(isin), "currency": bc,
                "bid": float(bid), "ask": float(ask), "provider_mid": float(mid),
                "computed_mid": float(calculated_mid), "mid_matches_book": mid == calculated_mid,
                "spread": float(ask-bid), "spread_pct_of_mid": float((ask-bid)/calculated_mid*100),
                "reported_spread": float(spread), "reported_spread_pct": float(spread_pct),
                "quote_at": observed.isoformat(timespec="milliseconds"),
                "quote_is_outdated": {"true": True, "false": False}.get(outdated),
                "outdated_flag_raw": outdated, "false_may_have_been_lost": outdated == "N/A",
                "snapshot_at": None, "quote_age_seconds": None, "exchange": None,
                "source_type": "user_supplied_console_quote", "source_command_label": "sc broker quote",
                "ownership_confirmed": False,
            }
            records.append(record)
            pending.append(record)
        if line.startswith("Snapshot UTC:"):
            value = line.split(":", 1)[1].strip()
            snapshot = datetime.strptime(value, "%Y-%m-%d %H:%M:%S UTC").replace(tzinfo=timezone.utc)
            for record in pending:
                quote = datetime.fromisoformat(record["quote_at"])
                age = (snapshot-quote).total_seconds()
                if age < 0:
                    raise ValueError("Kotasyon snapshot zamanının ilerisinde")
                record.update(snapshot_at=snapshot.isoformat(), quote_age_seconds=age)
            pending = []
    if not records:
        raise ValueError("Okunabilir fiyat/makas satırı yok")
    return records


def import_file(input_path, output_dir):
    input_path, output_dir = Path(input_path), Path(output_dir)
    raw = input_path.read_bytes()
    records = parse_quote_text(raw.decode("utf-8"))
    dates = sorted({r["quote_at"][:10] for r in records})
    prefix = f"fiyat-makas-{dates[0]}_{dates[-1]}"
    output_dir.mkdir(parents=True, exist_ok=True)
    result = {
        "schema_version": 1, "source_file": str(input_path),
        "source_sha256": hashlib.sha256(raw).hexdigest(),
        "imported_at": datetime.now(timezone.utc).isoformat(),
        "scope": "Tarihsel araştırma kotasyonları; portföy veya gerçekleşmiş işlemler değil",
        "source_limitations": [
            "İşlem borsası ve kaynak CLI'nin sağlayıcı kimliği bu metinden doğrulanmadı.",
            "Özgün kod jq // kullandığı için N/A, false değerinin kaybolduğu anlamına da gelebilir.",
            "Snapshot saati ile her satırın kotasyon saati farklıdır; güncellik bilinmiyorsa null kalır.",
            "Mid değişimi kapanış veya toplam getiri değildir; aynı anda gerçekleşebilir fiyat garantisi yoktur.",
        ],
        "records": records,
    }
    json_path = output_dir / (prefix + ".json")
    csv_path = output_dir / (prefix + ".csv")
    if json_path.exists() or csv_path.exists():
        raise FileExistsError("Mevcut tarihsel kayıt korunuyor; yeni çıktı klasörü seçin")
    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    with csv_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(records[0]))
        writer.writeheader()
        writer.writerows(records)
    return json_path, csv_path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--out-dir", required=True, type=Path)
    args = parser.parse_args()
    for path in import_file(args.input, args.out_dir):
        print(path)
