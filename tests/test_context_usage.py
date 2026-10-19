"""Card detail ctx% (plan 2026-10-19-card-context-usage): parser, session lookup and route."""

import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_reset_gen import env, write_log  # noqa: E402,F401

import projects as pj  # noqa: E402
import usage_reader as ur  # noqa: E402

SID = "0b6c1f2e-1111-4222-8333-444455556666"


def jl(path, *rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        for r in rows:
            f.write((r if isinstance(r, str) else json.dumps(r)) + "\n")
    return path


def asst(inp, cr=0, cc=0, model="claude-opus-5-5", side=False):
    return {"type": "assistant", "isSidechain": side,
            "message": {"model": model, "usage": {"input_tokens": inp, "cache_read_input_tokens": cr,
                                                  "cache_creation_input_tokens": cc, "output_tokens": 9}}}


def codex_tc(inp, window=None):
    info = {"last_token_usage": {"input_tokens": inp, "output_tokens": 5}}
    if window is not None:
        info["model_context_window"] = window
    return {"type": "event_msg", "payload": {"type": "token_count", "info": info}}


def step_end(i, cr=0, cw=0):
    return {"type": "status", "phase": "step_end",
            "usage": {"inputTokens": i, "outputTokens": 3, "cacheReadTokens": cr, "cacheWriteTokens": cw}}


def init(model):
    return {"type": "system", "subtype": "init", "model": model}


# ── Parser ────────────────────────────────────────────────────────────────────

def test_claude_newest_main_thread_wins(tmp_path):
    f = jl(tmp_path / "t.jsonl", asst(10, 1000, 0), asst(2, 40_000, 2_000))
    assert ur.context_usage("claude", f) == {"used": 42_002, "window": 200_000, "pct": 21}


def test_claude_skips_sidechain_and_synthetic(tmp_path):
    f = jl(tmp_path / "t.jsonl", asst(5, 20_000), asst(1, 90_000, side=True), asst(0, model="<synthetic>"))
    assert ur.context_usage("claude", f)["used"] == 20_005


def test_claude_1m_marker_under_200k(tmp_path):
    f = jl(tmp_path / "t.jsonl", asst(0, 180_000))
    assert ur.context_usage("claude", f, "claude-opus-5-5[1m]") == {"used": 180_000, "window": 1_000_000, "pct": 18}


def test_claude_unmarked_over_200k_is_1m(tmp_path):
    f = jl(tmp_path / "t.jsonl", asst(0, 250_000))
    assert ur.context_usage("claude", f, "claude-opus-5-5")["window"] == 1_000_000


def test_claude_unmarked_under_200k_is_200k(tmp_path):
    f = jl(tmp_path / "t.jsonl", asst(0, 190_000))
    assert ur.context_usage("claude", f, "claude-sonnet-4-6") == {"used": 190_000, "window": 200_000, "pct": 95}


def test_codex_reported_window(tmp_path):
    f = jl(tmp_path / "r.jsonl", codex_tc(149_601, 475_000))
    assert ur.context_usage("codex", f) == {"used": 149_601, "window": 475_000, "pct": 31}


def test_codex_missing_window_keeps_used(tmp_path):
    f = jl(tmp_path / "r.jsonl", codex_tc(5_000))
    assert ur.context_usage("codex", f) == {"used": 5_000, "window": None, "pct": None}


def test_dsh_step_end(tmp_path):
    f = jl(tmp_path / "s.jsonl", step_end(537, 12_032, 11))
    assert ur.context_usage("dsh", f) == {"used": 12_580, "window": 1_000_000, "pct": 1, "approx": True}


def test_dsh_retried_step_is_marked_upper_bound(tmp_path):
    # a step whose rejected attempt reported usage: dsh sums both attempts into step_end (CTX-009)
    f = jl(tmp_path / "s.jsonl", step_end(400_000), step_end(800_000))
    c = ur.context_usage("dsh", f)
    assert c["used"] == 800_000 and c["approx"] is True


def test_no_usage_missing_file_malformed(tmp_path):
    assert ur.context_usage("claude", jl(tmp_path / "a.jsonl", {"type": "user"})) is None
    assert ur.context_usage("claude", tmp_path / "nope.jsonl") is None
    f = jl(tmp_path / "b.jsonl", asst(0, 7_000), "{not json", "[1,2]")
    assert ur.context_usage("claude", f)["used"] == 7_000


def test_non_int_token_falls_through(tmp_path):
    bad = asst(0, 9)
    bad["message"]["usage"]["cache_read_input_tokens"] = "lots"
    neg = asst(-1)
    f = jl(tmp_path / "t.jsonl", asst(0, 3_000), bad, neg)
    assert ur.context_usage("claude", f)["used"] == 3_000


def test_tail_limit_and_partial_line(tmp_path, monkeypatch):
    monkeypatch.setattr(ur, "CTX_TAIL_BYTES", 2_000)
    f = jl(tmp_path / "t.jsonl", asst(0, 5_000), *([{"type": "user", "pad": "x" * 100}] * 40))
    assert ur.context_usage("claude", f) is None  # usage line is beyond the tail
    lines = ur._tail_lines(f, 150)
    assert all(json.loads(x) for x in lines)  # the partial first line was dropped


def test_tail_starting_exactly_on_a_line_keeps_it(tmp_path):
    first = json.dumps(asst(0, 4_000)) + "\n"
    f = jl(tmp_path / "t.jsonl", {"type": "user", "pad": "p" * 50}, asst(0, 4_000), {"type": "user"})
    limit = f.stat().st_size - len(json.dumps({"type": "user", "pad": "p" * 50}) + "\n")
    assert ur._tail_lines(f, limit)[-1] == first.strip()  # the tail begins on a whole usage line
    lines = ur._tail_lines(f, limit - 1)
    assert json.loads(lines[-1]) == {"type": "user"}  # one byte less: that line is partial and dropped


def test_unicode_line_separators_inside_json_text(tmp_path):
    newest = asst(0, 77_000)
    newest["message"]["content"] = [{"type": "text", "text": "a\u2028b\u2029c\u0085d"}]
    f = tmp_path / "t.jsonl"
    f.write_text(json.dumps(asst(0, 1_000)) + "\n" + json.dumps(newest, ensure_ascii=False) + "\n", encoding="utf-8")
    assert ur.context_usage("claude", f)["used"] == 77_000


# ── stream_model ──────────────────────────────────────────────────────────────

def test_stream_model_newest_init_and_far_back(tmp_path):
    ur._STREAM_MODELS.clear()
    f = jl(tmp_path / "s.jsonl", init("claude-sonnet-4-6"), init("claude-opus-5-5[1m]"))
    jl(f, *([{"type": "user", "pad": "y" * 1000}] * 2100))  # > 2 MB after the init lines
    assert f.stat().st_size > ur.CTX_TAIL_BYTES
    assert ur.stream_model(f) == "claude-opus-5-5[1m]"


def test_stream_model_incremental_and_reset(tmp_path):
    ur._STREAM_MODELS.clear()
    f = jl(tmp_path / "s.jsonl", init("m1"))
    assert ur.stream_model(f) == "m1"
    off = ur._STREAM_MODELS[str(f)][1]
    jl(f, {"type": "user"}, init("m2"))
    assert ur.stream_model(f) == "m2" and ur._STREAM_MODELS[str(f)][1] > off
    with f.open("a") as h:
        h.write('{"type":"system","subtype":"init","model":"half')  # partial last line: not consumed
    assert ur.stream_model(f) == "m2"
    f.write_text(json.dumps(init("m3")) + "\n")  # truncated below the cached offset
    assert ur.stream_model(f) == "m3"
    g = tmp_path / "g.jsonl"
    jl(g, {"type": "user"}, {"type": "user"}, {"type": "user"}, init("m4"))
    os.replace(g, f)  # replaced file (new inode), larger than the old offset
    assert ur.stream_model(f) == "m4"


# ── session_file ──────────────────────────────────────────────────────────────

def test_session_file_claude_path_only(monkeypatch):
    t = jl(pj.CLAUDE_PROJECTS / "-x-proj" / f"{SID}.jsonl", asst(0, 1))
    monkeypatch.setattr(pj, "_claude_summary", lambda *a: pytest.fail("must not scan the transcript"))
    assert pj.session_file("claude", SID) == t


def test_session_file_duplicate_id_newest_copy_wins():
    old = jl(pj.CLAUDE_PROJECTS / "-a-old-checkout" / f"{SID}.jsonl", asst(0, 240_000))
    new = jl(pj.CLAUDE_PROJECTS / "-b-new-checkout" / f"{SID}.jsonl", asst(0, 62_000))
    os.utime(old, (1_000_000, 1_000_000))
    assert pj.session_file("claude", SID) == new
    os.utime(new, (500_000, 500_000))
    assert pj.session_file("claude", SID) == old


def test_session_file_refuses_symlink(tmp_path):
    real = jl(tmp_path / "real.jsonl", asst(0, 1))
    d = pj.CLAUDE_PROJECTS / "-x-proj"
    d.mkdir(parents=True)
    (d / f"{SID}.jsonl").symlink_to(real)
    assert pj.session_file("claude", SID) is None


def test_session_file_refuses_invalid_sid():
    (pj.CLAUDE_PROJECTS / "-x-proj").mkdir(parents=True)
    assert pj.session_file("claude", "../etc/passwd") is None
    assert pj.session_file("claude", "") is None


# ── Route ─────────────────────────────────────────────────────────────────────

@pytest.fixture
def ctx(env, monkeypatch):
    app_mod = env[0]
    monkeypatch.setattr(app_mod, "_running_jobs", {})
    monkeypatch.setattr(app_mod, "_SESSION_CLAIMS", {})
    monkeypatch.setattr(app_mod, "_OBSERVED_MODELS", {})
    ur._STREAM_MODELS.clear()
    return env


def get_ctx(client, rid):
    r = client.get(f"/api/runs/{rid}/context")
    assert r.status_code == 200
    return r.get_json()["context"]


def test_route_completed_claude_record(ctx):
    app_mod, _, client, log, *_ = ctx
    jl(pj.CLAUDE_PROJECTS / "-x-proj" / f"{SID}.jsonl", asst(0, 50_000))
    write_log(log, {"run_id": "r1", "status": "done", "agent": "claude", "agent_session_id": SID,
                    "model": "claude-opus-5-5"})
    assert get_ctx(client, "r1") == {"used": 50_000, "window": 200_000, "pct": 25}


def test_route_running_observed_1m(ctx):
    app_mod, _, client, *_ = ctx
    jl(pj.CLAUDE_PROJECTS / "-x-proj" / f"{SID}.jsonl", asst(0, 150_000))
    app_mod._running_jobs["r2"] = {"agent": "claude", "agent_session_id": SID}
    app_mod._OBSERVED_MODELS["r2"] = "claude-opus-5-5[1m]"
    assert get_ctx(client, "r2")["pct"] == 15


def test_route_project_run_far_init(ctx):
    app_mod, _, client, *_ = ctx
    jl(pj.CLAUDE_PROJECTS / "-x-proj" / f"{SID}.jsonl", asst(0, 180_000))
    s = jl(app_mod._claude_stream_log_path("r3"), init("claude-opus-5-5[1m]"),
           *([{"type": "user", "pad": "z" * 1000}] * 2100))
    assert s.stat().st_size > ur.CTX_TAIL_BYTES and not app_mod._run_progress_path("r3").exists()
    app_mod._running_jobs["r3"] = {"agent": "claude", "agent_session_id": SID}  # project jobs: no model
    assert get_ctx(client, "r3") == {"used": 180_000, "window": 1_000_000, "pct": 18}


def test_route_project_dsh_deterministic_stream(ctx):
    app_mod, _, client, log, *_ = ctx
    jl(app_mod._claude_stream_log_path("r4"), step_end(100, 900))
    write_log(log, {"run_id": "r4", "status": "done", "agent": "deepseek"})  # legacy id -> dsh
    assert get_ctx(client, "r4") == {"used": 1_000, "window": 1_000_000, "pct": 0, "approx": True}


def test_route_error_is_null(ctx, monkeypatch):
    app_mod, _, client, log, *_ = ctx
    write_log(log, {"run_id": "r5", "status": "done", "agent": "claude", "agent_session_id": SID})
    jl(pj.CLAUDE_PROJECTS / "-x-proj" / f"{SID}.jsonl", asst(0, 1))
    monkeypatch.setattr(ur, "context_usage", lambda *a, **k: 1 / 0)
    assert get_ctx(client, "r5") is None


def test_route_unknown_run(ctx):
    assert get_ctx(ctx[2], "nope") is None
