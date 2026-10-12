"""
Log analysis, LLM root-cause diagnosis, and pip-audit vulnerability patching.
"""
import json
import re
from pathlib import Path
from typing import Callable, Optional

from module_auto_healer.models import (
    DiagnosisResult,
    FailureContext,
    VulnerabilityFix,
)
from module_auto_healer.validator import is_safe_target_path

FILE_REF_PATTERN = re.compile(
    r'(?:File\s+"|in\s+)([a-zA-Z0-9_./\\-]+\.py)'
)


def extract_error_snippet(raw_log: str, max_chars: int = 4000) -> str:
    """
    Extracts the most relevant error/traceback tail from a GitHub Actions log.
    """
    if not raw_log:
        return ""

    tb_idx = raw_log.rfind("Traceback (most recent call last):")
    if tb_idx != -1:
        snippet = raw_log[tb_idx:]
        return snippet[:max_chars]

    lines = [
        line for line in raw_log.splitlines()
        if any(k in line.lower() for k in ("error", "exception", "fatal", "failed", "traceback"))
    ]
    if lines:
        joined = "\n".join(lines[-40:])
        return joined[-max_chars:]

    return raw_log[-max_chars:]


def extract_referenced_files(
    error_snippet: str,
    project_root: str,
) -> tuple[tuple[str, str], ...]:
    """
    Finds allowed project Python files referenced in the traceback and reads their contents.
    Returns an immutable tuple of (relative_path, file_content).
    """
    matches = FILE_REF_PATTERN.findall(error_snippet)
    seen: set[str] = set()
    results: list[tuple[str, str]] = []
    root_path = Path(project_root).resolve()

    for match in matches:
        normalized = match.replace("\\", "/").lstrip("./")
        # Also handle when workflow ran `cd module_distributor` so traceback says `File "orchestrator.py"`
        candidates = [
            normalized,
            f"module_distributor/{normalized}",
            f"module_noc_alerts/{normalized}",
        ]
        for candidate in candidates:
            if candidate in seen:
                continue
            if is_safe_target_path(candidate, project_root):
                full_path = root_path / candidate
                if full_path.is_file():
                    seen.add(candidate)
                    content = full_path.read_text(encoding="utf-8")
                    results.append((candidate, content))
                    break

    return tuple(results)


def _default_llm_responder(
    system_prompt: str,
    user_prompt: str,
    api_key: str,
    base_url: str = "https://api.deepseek.com",
    model: str = "deepseek-chat",
) -> str:
    """Calls OpenAI-compatible (DeepSeek) API and returns raw JSON text."""
    import openai

    client = openai.OpenAI(api_key=api_key, base_url=base_url)
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        response_format={"type": "json_object"},
        max_tokens=4096,
        temperature=0.1,
    )
    return (response.choices[0].message.content or "{}").strip()


def diagnose_failure(
    context: FailureContext,
    api_key: str,
    llm_responder: Optional[Callable[[str, str], str]] = None,
) -> DiagnosisResult:
    """
    Diagnoses a workflow failure using LLM and returns an immutable DiagnosisResult.
    """
    if not api_key and llm_responder is None:
        return DiagnosisResult(
            category="UNFIXABLE",
            root_cause="Missing LLM API key for autonomous diagnosis.",
        )

    system_prompt = (
        "You are an autonomous DevSecOps Self-Healing Agent for SmartInfraOps.\n"
        "Analyze the GitHub Actions failure log and referenced source files.\n"
        "Output ONLY a valid JSON object with these keys:\n"
        '- "category": One of ["TRANSIENT", "CODE_FIX", "CREDENTIALS_EXPIRED", "UNFIXABLE"]\n'
        '- "root_cause": Concise 1-2 sentence explanation of why the workflow failed.\n'
        '- "target_file": Relative path (e.g. "module_distributor/orchestrator.py") if category is "CODE_FIX", else null.\n'
        '- "patched_content": Full, complete replacement file content if category is "CODE_FIX", else null.\n'
        '- "secret_name": Name of the expired GitHub Secret (e.g. "MEDIUM_AUTH_JSON_BASE64", "X_AUTH_JSON_BASE64") '
        'if category is "CREDENTIALS_EXPIRED", else null.\n'
        "Rules:\n"
        "1. Never hardcode secrets or tokens.\n"
        "2. Preserve all existing functions and logic not related to the bug.\n"
        "3. Use category 'TRANSIENT' for network timeouts, 502/503 HTTP errors, or temporary rate limits."
    )

    files_section = "\n\n".join(
        f"--- FILE: {rel_path} ---\n{content}"
        for rel_path, content in context.failed_files
    )
    user_prompt = (
        f"Workflow: {context.workflow_name} (Run ID: {context.run_id})\n\n"
        f"=== ERROR LOG EXCERPT ===\n{context.log_excerpt}\n\n"
        f"=== REFERENCED SOURCE FILES ===\n{files_section or 'No local files referenced in traceback.'}"
    )

    try:
        raw_response = (
            llm_responder(system_prompt, user_prompt)
            if llm_responder is not None
            else _default_llm_responder(system_prompt, user_prompt, api_key)
        )
        parsed = json.loads(raw_response)
        category = str(parsed.get("category", "UNFIXABLE")).upper()
        if category not in {"TRANSIENT", "CODE_FIX", "CREDENTIALS_EXPIRED", "UNFIXABLE"}:
            category = "UNFIXABLE"

        return DiagnosisResult(
            category=category,
            root_cause=str(parsed.get("root_cause", "Unknown failure")),
            target_file=parsed.get("target_file"),
            patched_content=parsed.get("patched_content"),
            secret_name=parsed.get("secret_name"),
        )
    except Exception as exc:
        return DiagnosisResult(
            category="UNFIXABLE",
            root_cause=f"Autonomous diagnosis failed: {exc}",
        )


def _pick_highest_version(versions: list[str]) -> str:
    """Picks the highest semantic version string from a list of fix_versions."""
    def _version_key(v: str) -> tuple[int, ...]:
        nums = re.findall(r"\d+", v)
        return tuple(int(n) for n in nums)

    return sorted(versions, key=_version_key)[-1]


def apply_vulnerability_fixes(
    req_content: str,
    audit_json: str,
    requirements_file: str = "",
) -> tuple[str, tuple[VulnerabilityFix, ...]]:
    """
    Parses `pip-audit --format=json` output and returns a new requirements.txt
    content string with vulnerable packages upgraded to their fixed versions,
    along with an immutable tuple of VulnerabilityFix records.
    """
    try:
        data = json.loads(audit_json)
    except Exception:
        return req_content, ()

    dependencies = data.get("dependencies", []) if isinstance(data, dict) else []
    upgrade_map: dict[str, VulnerabilityFix] = {}

    for dep in dependencies:
        pkg_name = str(dep.get("name", "")).strip()
        current_ver = str(dep.get("version", "")).strip()
        vulns = dep.get("vulns") or []
        all_fix_versions: list[str] = []
        for vuln in vulns:
            all_fix_versions.extend(vuln.get("fix_versions") or [])
        if pkg_name and all_fix_versions:
            best_fix = _pick_highest_version(all_fix_versions)
            upgrade_map[pkg_name.lower()] = VulnerabilityFix(
                package_name=pkg_name,
                current_version=current_ver,
                fixed_version=best_fix,
                requirements_file=requirements_file,
            )

    if not upgrade_map:
        return req_content, ()

    applied_fixes: list[VulnerabilityFix] = []
    new_lines: list[str] = []

    for line in req_content.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            new_lines.append(line)
            continue

        match = re.match(r"^([a-zA-Z0-9_.-]+)\s*([><=~!]+.*)?$", stripped)
        if not match:
            new_lines.append(line)
            continue

        pkg_raw = match.group(1)
        pkg_norm = pkg_raw.lower().replace("_", "-")
        fix_obj = upgrade_map.get(pkg_norm) or upgrade_map.get(pkg_raw.lower())
        if fix_obj:
            new_lines.append(f"{pkg_raw}>={fix_obj.fixed_version}")
            applied_fixes.append(fix_obj)
        else:
            new_lines.append(line)

    trailing = "\n" if req_content.endswith("\n") else ""
    return "\n".join(new_lines) + trailing, tuple(applied_fixes)
