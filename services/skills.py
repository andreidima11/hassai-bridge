"""
HASSAI Bridge — Skills engine.

Discovers, loads, executes, and manages skills stored as Python files.
Built-in skills live in  data/skills/*.py
Generated skills live in data/skills/generated/*.py
"""

import importlib.util
import logging
import os
import re
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

log = logging.getLogger("hassai.skills")

SKILLS_DIR = Path(__file__).parent.parent / "data" / "skills"
GENERATED_DIR = SKILLS_DIR / "generated"

# ── In-memory registry (lazy-loaded, thread-safe) ──
_registry: Optional[List[Dict[str, Any]]] = None
_registry_lock = threading.Lock()


def _load_skill_module(path: str):
    """Dynamically import a skill .py and return the first class with execute()."""
    try:
        spec = importlib.util.spec_from_file_location("skill_mod", path)
        if spec is None or spec.loader is None:
            return None
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        # Find the first class with an execute() method
        for attr_name in dir(mod):
            obj = getattr(mod, attr_name)
            if isinstance(obj, type) and hasattr(obj, "execute") and callable(getattr(obj, "execute")):
                return obj
    except Exception as e:
        log.warning(f"Failed to load skill {path}: {e}")
    return None


def _scan_skills() -> List[Dict[str, Any]]:
    """Scan skills directories and build the registry."""
    registry: List[Dict[str, Any]] = []
    for base_dir, generated in [(SKILLS_DIR, False), (GENERATED_DIR, True)]:
        if not base_dir.exists():
            continue
        for f in sorted(os.listdir(base_dir)):
            if not f.endswith(".py") or f.startswith("_") or f == "template.py":
                continue
            path = str(base_dir / f)
            cls = _load_skill_module(path)
            if cls is None:
                continue
            name = getattr(cls, "name", os.path.splitext(f)[0])
            desc = getattr(cls, "description", "")
            registry.append({
                "name": name,
                "description": desc,
                "path": path,
                "cls": cls,
                "generated": generated,
            })
    return registry


def _get_registry() -> List[Dict[str, Any]]:
    """Get the skill registry, scanning if needed."""
    global _registry
    with _registry_lock:
        if _registry is None:
            _registry = _scan_skills()
            log.info(f"Skills loaded: {[s['name'] for s in _registry]}")
        return _registry


def reload_registry():
    """Force a rescan of skills (after create/update/delete)."""
    global _registry
    with _registry_lock:
        _registry = None
    _get_registry()


# ═══════════════════════════════════════════════
# Public API
# ═══════════════════════════════════════════════

def get_skill_registry() -> List[Dict[str, Any]]:
    """List all available skills (without cls reference)."""
    return [
        {"name": s["name"], "description": s["description"], "path": s["path"], "generated": s["generated"]}
        for s in _get_registry()
    ]


def get_skill_source(skill_name: str) -> Optional[str]:
    """Read the source code of a skill by name."""
    for s in _get_registry():
        if s["name"] == skill_name:
            try:
                return Path(s["path"]).read_text(encoding="utf-8")
            except OSError:
                return None
    return None


def run_skill(skill_name: str, input_data: Dict[str, Any], timeout: int = 30) -> Dict[str, Any]:
    """Execute a skill by name with the given inputs."""
    for s in _get_registry():
        if s["name"] == skill_name:
            cls = s["cls"]
            if cls is None:
                return {"success": False, "message": f"Skill '{skill_name}' failed to load"}
            try:
                result = cls.execute(input_data)
                if not isinstance(result, dict):
                    return {"success": False, "message": f"Skill returned non-dict: {type(result).__name__}"}
                return result
            except Exception as e:
                log.error(f"Skill '{skill_name}' execution error: {e}")
                return {"success": False, "message": f"Skill error: {e}"}
    return {"success": False, "message": f"Skill '{skill_name}' not found"}


def create_skill(name: str, source: str) -> Tuple[bool, str]:
    """Create a new generated skill from source code."""
    ok, msg = _validate_skill_code(source)
    if not ok:
        return False, msg

    # Sanitize filename
    safe_name = re.sub(r"[^a-z0-9_]", "_", name.lower().strip())
    if not safe_name:
        return False, "Invalid skill name"

    dest = GENERATED_DIR / f"{safe_name}.py"
    if dest.exists():
        return False, f"Skill '{safe_name}' already exists. Use update instead."

    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    dest.write_text(source, encoding="utf-8")
    reload_registry()
    log.info(f"Created skill: {safe_name}")
    return True, f"Skill '{safe_name}' created successfully"


def update_skill_source(skill_name: str, source: str) -> Tuple[bool, str]:
    """Update an existing skill's source code."""
    ok, msg = _validate_skill_code(source)
    if not ok:
        return False, msg

    for s in _get_registry():
        if s["name"] == skill_name:
            try:
                Path(s["path"]).write_text(source, encoding="utf-8")
                reload_registry()
                log.info(f"Updated skill: {skill_name}")
                return True, f"Skill '{skill_name}' updated"
            except OSError as e:
                return False, str(e)
    return False, f"Skill '{skill_name}' not found"


def delete_skill(skill_name: str) -> Tuple[bool, str]:
    """Delete a generated skill. Built-in skills cannot be deleted."""
    for s in _get_registry():
        if s["name"] == skill_name:
            if not s["generated"]:
                return False, f"Cannot delete built-in skill '{skill_name}'"
            try:
                os.remove(s["path"])
                reload_registry()
                log.info(f"Deleted skill: {skill_name}")
                return True, f"Skill '{skill_name}' deleted"
            except OSError as e:
                return False, str(e)
    return False, f"Skill '{skill_name}' not found"


def get_template_source() -> str:
    """Return the skill template source code."""
    tpl = SKILLS_DIR / "template.py"
    if tpl.exists():
        return tpl.read_text(encoding="utf-8")
    return ""


# ═══════════════════════════════════════════════
# Security validation
# ═══════════════════════════════════════════════

_BLOCKED_IMPORTS = {
    "os", "subprocess", "sys", "shutil", "socket", "ctypes",
    "multiprocessing", "threading", "importlib", "pickle",
    "signal", "pty", "resource", "fcntl", "termios",
    "code", "codeop", "compileall", "py_compile",
}

_BLOCKED_BUILTINS = [
    (r"\b__import__\b", "__import__"),
    (r"(?<!\w)exec\s*\(", "exec"),
    (r"(?<!\w)eval\s*\(", "eval"),
    (r"(?<!\w)getattr\s*\(", "getattr"),
    (r"(?<!\w)open\s*\(", "open"),
    (r"(?<!\w)compile\s*\(", "compile"),
]


def _validate_skill_code(code: str) -> Tuple[bool, str]:
    """Basic security checks on skill source code."""
    if "class " not in code or "def execute" not in code:
        return False, "Skill must define a class with an execute() method"

    for line in code.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        m = re.match(r"(?:from\s+(\S+)|import\s+(\S+))", stripped)
        if m:
            mod = (m.group(1) or m.group(2)).split(".")[0]
            if mod in _BLOCKED_IMPORTS:
                return False, f"Import of '{mod}' is not allowed for security reasons"

    for pattern, label in _BLOCKED_BUILTINS:
        if re.search(pattern, code):
            return False, f"Use of '{label}' is not allowed for security reasons"

    return True, ""
