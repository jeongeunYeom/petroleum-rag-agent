from __future__ import annotations

from scripts.run_python_tool_heldout_v3r1 import digest, load_frozen, make_request


def test_frozen_manifest_and_off_on_requests() -> None:
    benchmark, manifest = load_frozen()
    assert manifest["freeze_commit_sha"] == "25f198b08c1e5125e4f82701fed097c2d350a359"
    assert manifest["preflight_status"] == "PASS"
    assert len(benchmark["tasks"]) == 12
    off, on = [make_request(benchmark["tasks"][0], condition, manifest["model_settings"])
               for condition in manifest["conditions"]]
    assert not off.allow_python_execution and not off.python_execution_approved
    assert on.allow_python_execution and on.python_execution_approved
    assert off.model == on.model == "qwen3:8b"
    assert off.temperature == on.temperature == 0
    assert off.seed == on.seed == 42
    assert not off.use_external and not on.use_external
    assert off.max_iterations == on.max_iterations == 4
    assert off.no_progress_patience == on.no_progress_patience == 2
    assert off.model_dump(exclude={"allow_python_execution", "python_execution_approved"}) == on.model_dump(
        exclude={"allow_python_execution", "python_execution_approved"}
    )


def test_frozen_hash_is_checkout_line_ending_independent(tmp_path) -> None:
    lf = tmp_path / "lf.json"
    crlf = tmp_path / "crlf.json"
    lf.write_bytes(b'{\n  "x": 1\n}\n')
    crlf.write_bytes(b'{\r\n  "x": 1\r\n}\r\n')
    assert digest(lf) == digest(crlf)
