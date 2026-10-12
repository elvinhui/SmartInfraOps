"""
Security and code-quality guardrails for validating AI-generated patches
before writing to disk or committing to a fix branch.
"""
import ast
import os
import re
from pathlib import Path

ALLOWED_MODULE_DIRS = frozenset({
    "module_distributor",
    "module_noc_alerts",
    "module_analytics",
})

ALLOWED_FILENAMES_OR_EXTS = frozenset({".py", "requirements.txt"})

SECRET_PATTERNS = (
    re.compile(r"sk-[a-zA-Z0-9_-]{20,}"),
    re.compile(r"ghp_[a-zA-Z0-9]{20,}"),
    re.compile(r"github_pat_[a-zA-Z0-9_]{20,}"),
    re.compile(r"AIza[0-9A-Za-z_-]{25,}"),
    re.compile(r"eyJ[a-zA-Z0-9_-]{20,}\.[a-zA-Z0-9_-]{20,}\."),
)


def is_safe_target_path(rel_path: str, project_root: str) -> bool:
    """
    Validates that `rel_path` is strictly inside an allowed module directory,
    does not traverse outside `project_root`, and is a `.py` or `requirements.txt` file.
    """
    if not rel_path or os.path.isabs(rel_path):
        return False

    normalized = rel_path.replace("\\", "/").strip("/")
    parts = normalized.split("/")
    if len(parts) != 2 or ".." in parts:
        return False

    module_dir, filename = parts[0], parts[1]
    if module_dir not in ALLOWED_MODULE_DIRS:
        return False

    is_allowed_file = filename == "requirements.txt" or filename.endswith(".py")
    if not is_allowed_file:
        return False

    root_resolved = Path(project_root).resolve()
    target_resolved = (root_resolved / normalized).resolve()
    try:
        target_resolved.relative_to(root_resolved)
    except ValueError:
        return False

    return True


def contains_hardcoded_secrets(content: str) -> bool:
    """Scans code content for accidentally hardcoded API keys or tokens."""
    if not content:
        return False
    return any(pattern.search(content) for pattern in SECRET_PATTERNS)


def validate_python_syntax(content: str) -> tuple[bool, str]:
    """Parses Python source into an AST to guarantee valid syntax."""
    try:
        ast.parse(content)
        return True, ""
    except SyntaxError as exc:
        return False, f"SyntaxError at line {exc.lineno}: {exc.msg}"


def validate_patch(
    rel_path: str,
    original_content: str,
    patched_content: str,
    project_root: str,
) -> tuple[bool, str]:
    """
    Runs all security and quality guardrails on a proposed file patch.
    Returns (is_valid, reason).
    """
    if not is_safe_target_path(rel_path, project_root):
        return False, f"Target path '{rel_path}' is outside the allowed module allowlist."

    if not patched_content or not patched_content.strip():
        return False, "Patched content is empty."

    if original_content.strip() == patched_content.strip():
        return False, "Patched content is identical to original content."

    if contains_hardcoded_secrets(patched_content):
        return False, "Patched content contains a potential hardcoded secret or token."

    orig_lines = original_content.strip().splitlines()
    new_lines = patched_content.strip().splitlines()
    if len(orig_lines) >= 10 and len(new_lines) < len(orig_lines) * 0.5:
        return (
            False,
            f"Destructive shrink detected: original had {len(orig_lines)} lines, "
            f"patch has only {len(new_lines)} lines.",
        )

    if rel_path.endswith(".py"):
        syntax_ok, syntax_err = validate_python_syntax(patched_content)
        if not syntax_ok:
            return False, syntax_err

    return True, "OK"
