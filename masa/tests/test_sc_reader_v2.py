"""Hardening tests for the read-only Scalable CLI wrapper (audit Y1 / orta-5)."""

import pytest

from masa.ingestion.exceptions import ScalableSecurityViolation
from masa.ingestion.sc_reader import ScalableReader, resolve_sc_binary


def _recording_runner(stdout='{"ok": true, "data": {"result": {"items": [], "count": 0}}}'):
    calls = []

    def runner(cmd, timeout):
        calls.append(cmd)
        return 0, stdout, ""
    return runner, calls


def test_binary_is_absolute_and_not_from_path(monkeypatch):
    monkeypatch.delenv("MASA_SC_BIN", raising=False)
    monkeypatch.setenv("PATH", "/tmp/evil")
    assert resolve_sc_binary().startswith("/")
    with pytest.raises(ScalableSecurityViolation):
        resolve_sc_binary("sc")


def test_cursor_containing_write_word_substring_is_accepted():
    runner, calls = _recording_runner()
    reader = ScalableReader(binary_path="/opt/homebrew/bin/sc", runner=runner)
    reader.get_history(cursor="eyJwdXQiOiJvcmRlcmx5In0=")  # contains 'put'/'order' only as substrings
    reader.get_history(cursor="abcputrmpost")
    reader.get_history(cursor="1788164469710|kdkpPZnvnmAFttYUBarHnc")  # real sc 1.0.0 cursor shape
    assert calls[-1][-2:] == ["--cursor", "1788164469710|kdkpPZnvnmAFttYUBarHnc"]


@pytest.mark.parametrize("bad", ["--evil", "-x", "a b", "x;rm"])
def test_bad_cursor_rejected(bad):
    runner, _ = _recording_runner()
    reader = ScalableReader(binary_path="/opt/homebrew/bin/sc", runner=runner)
    with pytest.raises(ScalableSecurityViolation):
        reader.get_history(cursor=bad)


def test_page_size_not_sent_by_default():
    runner, calls = _recording_runner()
    ScalableReader(binary_path="/opt/homebrew/bin/sc", runner=runner).get_history()
    assert calls[-1] == ["/opt/homebrew/bin/sc", "broker", "transactions", "--json"]


@pytest.mark.parametrize("args", [["--confirm", "abc"], ["--isin", "IE00B3YLTY66", "--amount", "5"],
                                  ["--venue", "xetra"], ["--isin"]])
def test_unknown_or_write_flags_rejected(args):
    reader = ScalableReader(binary_path="/opt/homebrew/bin/sc", runner=_recording_runner()[0])
    with pytest.raises(ScalableSecurityViolation):
        reader._validate_command_safety("quote", extra_args=args)


def test_read_only_argv_shapes():
    runner, calls = _recording_runner('{"ok": true, "data": {}}')
    reader = ScalableReader(binary_path="/opt/homebrew/bin/sc", runner=runner)
    reader.get_whoami()
    reader.get_context()
    for tf in ("1y", "ytd"):
        try:
            reader.get_chart("IE00B3YLTY66", tf)
        except Exception:
            pass  # empty fixture -> parse error; argv is what matters here
    assert calls == [
        ["/opt/homebrew/bin/sc", "whoami", "--json"],
        ["/opt/homebrew/bin/sc", "broker", "context", "show", "--json"],
        ["/opt/homebrew/bin/sc", "broker", "chart", "--json", "--timeframe", "1y", "--isin", "IE00B3YLTY66"],
        ["/opt/homebrew/bin/sc", "broker", "chart", "--json", "--timeframe", "ytd", "--isin", "IE00B3YLTY66"],
    ]
    with pytest.raises(ScalableSecurityViolation):
        reader.get_chart("IE00B3YLTY66", "2y")


def test_every_executed_argv_is_free_of_write_verbs():
    runner, calls = _recording_runner('{"ok": true, "data": {}}')
    reader = ScalableReader(binary_path="/opt/homebrew/bin/sc", runner=runner)
    reader.get_whoami(); reader.get_context()
    try:
        reader.get_chart("IE00B3YLTY66", "1m")
    except Exception:
        pass
    for argv in calls:
        assert not {"trade", "buy", "sell", "cancel", "savings-plans", "add", "remove",
                    "select", "--confirm", "login", "logout"} & set(argv)
