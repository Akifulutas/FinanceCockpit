"""test_cockpit_argv_extracted.py — Swift kaynak kodundan otomatik çıkarılan tüm argv'lerin sözleşme testi.

ETFCockpit (Swift) kaynak kodunda bulunan tüm statik ve dinamik CLI argüman dizilerini
tarar ve Python `masa` argparse ayrıştırıcısına karşı doğrular.
Hiçbir komut `SystemExit` vermemeli (parse hatası vermemeli).
"""

from pathlib import Path
import re
import pytest

from masa.cli import build_parser


def test_cockpit_extracted_argv_parseable():
    swift_sources_dir = Path(__file__).resolve().parent.parent.parent / "macos" / "Sources"
    assert swift_sources_dir.exists(), f"Swift sources not found at: {swift_sources_dir}"

    literal_pat = re.compile(r'arguments:\s*\[((?:\s*"[^"]*"\s*,?)+)\]')
    found_commands = set()

    for swift_file in swift_sources_dir.rglob("*.swift"):
        content = swift_file.read_text(encoding="utf-8")
        for match in literal_pat.finditer(content):
            raw_items = match.group(1)
            args = tuple(re.findall(r'"([^"]*)"', raw_items))
            if args:
                found_commands.add((args, swift_file.name))

    # Add dynamically constructed commands (picker tags, enum values, subactions)
    # 1. arastir with all picker tags (uzun, orta, firsat, LONG_TERM, MEDIUM_TERM, SHORT_TERM)
    vade_tags = ["uzun", "orta", "firsat", "LONG_TERM", "MEDIUM_TERM", "SHORT_TERM"]
    for v in vade_tags:
        found_commands.add((("arastir", "IE00B3YLTY66", "--vade", v), "ResearchEvidenceView.swift (dynamic)"))

    # 2. zamanla with all valid actions (kur, kaldir, durum)
    for act in ["kur", "kaldir", "durum"]:
        found_commands.add((("zamanla", act), "SchedulerAutomationViewModel.swift (dynamic)"))

    # 3. ayar yaz with all files (portfoy, politika, havuz)
    for f in ["portfoy", "politika", "havuz"]:
        found_commands.add((("ayar", "yaz", "--dosya", f, "--json", "-"), "SystemConfigurationViewModel.swift (dynamic)"))

    # 4. tez ekle full argv and stdin JSON
    found_commands.add(((
        "tez", "ekle",
        "--isin", "IE00B3YLTY66",
        "--baslik", "Test Tezi",
        "--ozet", "Genis Dunya Endeksi",
        "--gerekce", "Dunya pazarina esit ve dengeli dagilim saglar",
        "--kategori", "CEKIRDEK",
        "--vade", "STRATEJIK_UZUN",
        "--tetikleyiciler", "TRIGGER_1", "TRIGGER_2",
        "--kanitlar", "EVIDENCE_1",
        "--karsi-gorus", "Risk faktoru",
        "--hedef-agirlik", "0.45",
        "--sonraki-kontrol", "2026-12-01"
    ), "ThesisManagementViewModel.swift (dynamic)"))
    found_commands.add((("tez", "ekle", "--girdi-json", "-"), "ThesisManagementViewModel.swift"))

    # 5. tahmin gecmis-simule
    found_commands.add((("tahmin", "gecmis-simule", "--gun", "30"), "CLIProcessRunner.swift (dynamic)"))

    parser = build_parser()
    failed = []

    for argv, source_file in sorted(found_commands):
        try:
            parser.parse_args(list(argv))
        except SystemExit as exc:
            failed.append((argv, source_file, str(exc)))

    assert not failed, f"Found {len(failed)} unparseable commands from Swift:\n" + "\n".join(
        f"  - {src}: {' '.join(cmd)}" for cmd, src, _ in failed
    )
