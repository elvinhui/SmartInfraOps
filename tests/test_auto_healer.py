import os
import json
import pytest
from pathlib import Path

from module_auto_healer.models import (
    FailureContext,
    DiagnosisResult,
    VulnerabilityFix,
)
from module_auto_healer.validator import (
    is_safe_target_path,
    contains_hardcoded_secrets,
    validate_python_syntax,
    validate_patch,
)
from module_auto_healer.analyzer import (
    extract_error_snippet,
    extract_referenced_files,
    diagnose_failure,
    apply_vulnerability_fixes,
)
from module_auto_healer.healer import (
    build_heal_webhook_payload,
    execute_heal_workflow,
    send_noc_notification,
    main as healer_main,
)


# ──────────────────────────────────────────────────────────────────────────────
# 1. Immutability & Models Tests
# ──────────────────────────────────────────────────────────────────────────────

def test_models_are_immutable():
    ctx = FailureContext(
        run_id="12345",
        workflow_name="Content Auto Distributor",
        log_excerpt="Traceback...",
        failed_files=(("module_distributor/orchestrator.py", "print('hi')"),),
    )
    with pytest.raises(Exception):
        ctx.run_id = "99999"  # type: ignore

    diag = DiagnosisResult(
        category="TRANSIENT",
        root_cause="Network timeout",
        target_file=None,
        patched_content=None,
        secret_name=None,
    )
    with pytest.raises(Exception):
        diag.category = "CODE_FIX"  # type: ignore


# ──────────────────────────────────────────────────────────────────────────────
# 2. Security & Validator Guardrail Tests
# ──────────────────────────────────────────────────────────────────────────────

def test_is_safe_target_path(tmp_path: Path):
    (tmp_path / "module_distributor").mkdir()
    (tmp_path / "module_noc_alerts").mkdir()
    (tmp_path / ".github" / "workflows").mkdir(parents=True)

    assert is_safe_target_path("module_distributor/orchestrator.py", str(tmp_path)) is True
    assert is_safe_target_path("module_noc_alerts/main.py", str(tmp_path)) is True
    assert is_safe_target_path("module_distributor/requirements.txt", str(tmp_path)) is True

    # Disallowed paths (traversal, workflows, root files, auth json, empty)
    assert is_safe_target_path("", str(tmp_path)) is False
    assert is_safe_target_path("../secrets.py", str(tmp_path)) is False
    assert is_safe_target_path(".github/workflows/auto_healer.yml", str(tmp_path)) is False
    assert is_safe_target_path("module_distributor/medium_auth.json", str(tmp_path)) is False
    assert is_safe_target_path("/etc/passwd", str(tmp_path)) is False


def test_contains_hardcoded_secrets():
    assert contains_hardcoded_secrets("") is False
    safe_code = 'API_KEY = os.getenv("DEEPSEEK_API_KEY")\nprint(API_KEY)\n'
    assert contains_hardcoded_secrets(safe_code) is False

    leaked_openai = 'key = "sk-proj-1234567890abcdef1234567890abcdef"\n'
    assert contains_hardcoded_secrets(leaked_openai) is True

    leaked_gh = 'token = "ghp_1234567890abcdefghijklmnopqrstuvwx"\n'
    assert contains_hardcoded_secrets(leaked_gh) is True

    leaked_google = 'gemini = "AIzaSyA1234567890abcdef1234567890abc"\n'
    assert contains_hardcoded_secrets(leaked_google) is True


def test_validate_python_syntax():
    ok, msg = validate_python_syntax("def foo():\n    return 42\n")
    assert ok is True
    assert msg == ""

    ok_bad, msg_bad = validate_python_syntax("def foo(\n    return 42")
    assert ok_bad is False
    assert "SyntaxError" in msg_bad


def test_validate_patch_guardrails(tmp_path: Path):
    mod_dir = tmp_path / "module_distributor"
    mod_dir.mkdir()
    orig = "\n".join([f"line_{i} = {i}" for i in range(20)]) + "\n"
    patched = orig.replace("line_5 = 5", "line_5 = 500")

    ok, reason = validate_patch(
        "module_distributor/sample.py", orig, patched, str(tmp_path)
    )
    assert ok is True
    assert reason == "OK"

    # Reject disallowed path
    ok_path, _ = validate_patch("evil.py", orig, patched, str(tmp_path))
    assert ok_path is False

    # Reject empty content
    ok_empty, _ = validate_patch("module_distributor/sample.py", orig, "   ", str(tmp_path))
    assert ok_empty is False

    # Reject identical content
    ok_same, reason_same = validate_patch(
        "module_distributor/sample.py", orig, orig, str(tmp_path)
    )
    assert ok_same is False
    assert "identical" in reason_same.lower()

    # Reject destructive wipe (>50% lines deleted)
    ok_wipe, reason_wipe = validate_patch(
        "module_distributor/sample.py", orig, "line_0 = 0\n", str(tmp_path)
    )
    assert ok_wipe is False
    assert "shrink" in reason_wipe.lower() or "destructive" in reason_wipe.lower()

    # Reject secret leak
    ok_secret, reason_secret = validate_patch(
        "module_distributor/sample.py",
        orig,
        orig + 'KEY = "sk-1234567890abcdef1234567890abcdef"\n',
        str(tmp_path),
    )
    assert ok_secret is False
    assert "secret" in reason_secret.lower()

    # Reject invalid syntax
    ok_syn, reason_syn = validate_patch(
        "module_distributor/sample.py",
        orig,
        orig + "def broken(\n",
        str(tmp_path),
    )
    assert ok_syn is False
    assert "SyntaxError" in reason_syn


# ──────────────────────────────────────────────────────────────────────────────
# 3. Analyzer & Vulnerability Auto-Patcher Tests
# ──────────────────────────────────────────────────────────────────────────────

def test_extract_error_snippet_and_referenced_files(tmp_path: Path):
    assert extract_error_snippet("") == ""
    assert "FATAL: connection reset" in extract_error_snippet("step 1\nFATAL: connection reset\n")
    assert "plain log line" in extract_error_snippet("plain log line")

    mod_dir = tmp_path / "module_noc_alerts"
    mod_dir.mkdir()
    target_py = mod_dir / "main.py"
    target_py.write_text("import requests\nprint('hello')\n", encoding="utf-8")

    raw_log = (
        "2026-10-12T00:00:01Z Installing dependencies...\n"
        "Traceback (most recent call last):\n"
        '  File "module_noc_alerts/main.py", line 2, in <module>\n'
        '  File "module_noc_alerts/main.py", line 3, in <module>\n'
        "    raise ValueError('Invalid selector')\n"
        "ValueError: Invalid selector\n"
    )
    snippet = extract_error_snippet(raw_log)
    assert "Traceback" in snippet
    assert "ValueError: Invalid selector" in snippet

    files = extract_referenced_files(snippet, str(tmp_path))
    assert len(files) == 1
    assert files[0][0] == "module_noc_alerts/main.py"
    assert "import requests" in files[0][1]


def test_apply_vulnerability_fixes():
    req_txt = "# Core deps\nrequests>=2.31.0\nplaywright>=1.44.0\n"
    audit_payload = json.dumps({
        "dependencies": [
            {
                "name": "requests",
                "version": "2.31.0",
                "vulns": [
                    {
                        "id": "CVE-2024-35195",
                        "fix_versions": ["2.32.0", "2.32.3"],
                    }
                ],
            },
            {
                "name": "playwright",
                "version": "1.44.0",
                "vulns": [],
            },
        ]
    })

    new_req, fixes = apply_vulnerability_fixes(req_txt, audit_payload)
    assert len(fixes) == 1
    assert fixes[0] == VulnerabilityFix(
        package_name="requests",
        current_version="2.31.0",
        fixed_version="2.32.3",
        requirements_file="",
    )
    assert "requests>=2.32.3" in new_req
    assert "playwright>=1.44.0" in new_req

    # Invalid JSON or no vulns
    unchanged, empty_fixes = apply_vulnerability_fixes(req_txt, "not-json")
    assert unchanged == req_txt
    assert empty_fixes == ()

    unchanged2, empty_fixes2 = apply_vulnerability_fixes(req_txt, json.dumps({"dependencies": []}))
    assert unchanged2 == req_txt
    assert empty_fixes2 == ()


def test_diagnose_failure_branches():
    ctx = FailureContext(
        run_id="99",
        workflow_name="NOC ChatOps Alert Engine",
        log_excerpt='File "module_noc_alerts/main.py", line 10\nTimeoutError: read timed out',
        failed_files=(("module_noc_alerts/main.py", "import os\n"),),
    )

    # Missing key & no responder
    no_key_res = diagnose_failure(ctx, api_key="")
    assert no_key_res.category == "UNFIXABLE"

    # Unknown category coerced to UNFIXABLE
    weird_res = diagnose_failure(
        ctx,
        api_key="k",
        llm_responder=lambda _s, _u: json.dumps({"category": "MAGIC", "root_cause": "weird"}),
    )
    assert weird_res.category == "UNFIXABLE"

    # Exception in responder
    err_res = diagnose_failure(
        ctx,
        api_key="k",
        llm_responder=lambda _s, _u: "invalid json {",
    )
    assert err_res.category == "UNFIXABLE"


# ──────────────────────────────────────────────────────────────────────────────
# 4. End-to-End Healer Execution & CLI Tests
# ──────────────────────────────────────────────────────────────────────────────

def test_execute_heal_workflow_all_outcomes(tmp_path: Path):
    mod_dir = tmp_path / "module_noc_alerts"
    mod_dir.mkdir()
    f_path = mod_dir / "main.py"
    orig_code = "\n".join([f"x_{i} = {i}" for i in range(15)]) + "\n"
    f_path.write_text(orig_code, encoding="utf-8")

    patched_code = orig_code.replace("x_0 = 0", "x_0 = 100")

    raw_log = (
        "Traceback (most recent call last):\n"
        '  File "module_noc_alerts/main.py", line 1, in <module>\n'
        "AssertionError: x_0 should be 100\n"
    )

    # 1. CODE_FIX valid
    outcome = execute_heal_workflow(
        run_id="555",
        workflow_name="NOC ChatOps Alert Engine",
        raw_log=raw_log,
        project_root=str(tmp_path),
        api_key="dummy-key",
        llm_responder=lambda _s, _u: json.dumps({
            "category": "CODE_FIX",
            "root_cause": "Updated x_0 constant to 100",
            "target_file": "module_noc_alerts/main.py",
            "patched_content": patched_code,
            "secret_name": None,
        }),
    )
    assert outcome["action"] == "CODE_FIXED"
    assert f_path.read_text(encoding="utf-8") == patched_code

    # 2. CODE_FIX rejected by guardrail (syntax error)
    outcome_rejected = execute_heal_workflow(
        run_id="556",
        workflow_name="NOC ChatOps Alert Engine",
        raw_log=raw_log,
        project_root=str(tmp_path),
        api_key="dummy-key",
        llm_responder=lambda _s, _u: json.dumps({
            "category": "CODE_FIX",
            "root_cause": "Bad syntax patch",
            "target_file": "module_noc_alerts/main.py",
            "patched_content": "def broken(\n",
            "secret_name": None,
        }),
    )
    assert outcome_rejected["action"] == "UNFIXABLE"
    assert "guardrail" in outcome_rejected["root_cause"]

    # 3. TRANSIENT
    outcome_trans = execute_heal_workflow(
        run_id="557",
        workflow_name="NOC ChatOps Alert Engine",
        raw_log=raw_log,
        project_root=str(tmp_path),
        api_key="dummy-key",
        llm_responder=lambda _s, _u: json.dumps({
            "category": "TRANSIENT",
            "root_cause": "503 Service Unavailable",
        }),
    )
    assert outcome_trans["action"] == "TRANSIENT_RERUN"

    # 4. CREDENTIALS_EXPIRED
    outcome_cred = execute_heal_workflow(
        run_id="558",
        workflow_name="Content Auto Distributor",
        raw_log=raw_log,
        project_root=str(tmp_path),
        api_key="dummy-key",
        llm_responder=lambda _s, _u: json.dumps({
            "category": "CREDENTIALS_EXPIRED",
            "root_cause": "Medium session cookie expired",
            "secret_name": "MEDIUM_AUTH_JSON_BASE64",
        }),
    )
    assert outcome_cred["action"] == "CREDENTIALS_EXPIRED"
    payload = build_heal_webhook_payload("Content Auto Distributor", outcome_cred)
    assert "MEDIUM_AUTH_JSON_BASE64" in json.dumps(payload)


def test_cli_main_audit_fix_and_heal_run(tmp_path: Path, monkeypatch):
    gh_out = tmp_path / "github_output.txt"
    monkeypatch.setenv("GITHUB_OUTPUT", str(gh_out))
    monkeypatch.setenv("NOC_WEBHOOK_URL", "")

    req_file = tmp_path / "requirements.txt"
    req_file.write_text("requests>=2.31.0\n", encoding="utf-8")
    audit_file = tmp_path / "audit.json"
    audit_file.write_text(
        json.dumps({
            "dependencies": [
                {
                    "name": "requests",
                    "version": "2.31.0",
                    "vulns": [{"id": "CVE-1", "fix_versions": ["2.32.3"]}],
                }
            ]
        }),
        encoding="utf-8",
    )

    rc = healer_main([
        "--mode", "audit-fix",
        "--requirements-file", str(req_file),
        "--audit-json-file", str(audit_file),
    ])
    assert rc == 0
    assert "requests>=2.32.3" in req_file.read_text(encoding="utf-8")
    assert "vuln_fixed=true" in gh_out.read_text(encoding="utf-8")

    # Test heal-run CLI mode
    log_file = tmp_path / "fail.log"
    log_file.write_text("Error: something failed", encoding="utf-8")
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    rc2 = healer_main([
        "--mode", "heal-run",
        "--run-id", "101",
        "--workflow-name", "TestFlow",
        "--log-file", str(log_file),
        "--project-root", str(tmp_path),
    ])
    assert rc2 == 0
    assert "action=UNFIXABLE" in gh_out.read_text(encoding="utf-8")
    assert send_noc_notification("", {}) is False
