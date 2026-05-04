"""Python-native LLM detection and inference.

Scans the current Python environment for installed LLM packages using
importlib.metadata, then dispatches inference through the appropriate adapter.
No Ollama or external daemon required.
"""
from __future__ import annotations

import importlib
import importlib.metadata
import json
import logging
import re
from pathlib import Path
from typing import Any
import os
import platform
import subprocess
import hashlib

_log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
REGISTRY_FILE = ROOT / "backend" / "model_providers" / "python_local_models.json"
TRIANGULATION_DIR = ROOT / "models"
DISCOVERY_CONFIG_FILE = ROOT / "backend" / "model_providers" / "python_local_discovery.json"

# ---------------------------------------------------------------------------
# Known LLM packages: pattern → (importable_module, display_name, adapter_key)
# ---------------------------------------------------------------------------
_KNOWN_PACKAGES: list[tuple[re.Pattern, str, str, str]] = [
    # (pkg name pattern,  module to import,  display label,  adapter key)
    (re.compile(r"^llama[_-]cpp[_-]python$", re.I), "llama_cpp",      "llama.cpp",        "llama_cpp"),
    (re.compile(r"^llama[_-]cpp$",            re.I), "llama_cpp",      "llama.cpp",        "llama_cpp"),
    (re.compile(r"^gpt4all$",                 re.I), "gpt4all",        "GPT4All",          "gpt4all"),
    (re.compile(r"^transformers$",            re.I), "transformers",   "HuggingFace",      "transformers"),
    (re.compile(r"^qwen[_-]?",               re.I), "qwen",           "Qwen",             "qwen"),
    (re.compile(r"^ctransformers$",           re.I), "ctransformers",  "CTransformers",    "ctransformers"),
    (re.compile(r"^mlx[_-]lm$",              re.I), "mlx_lm",         "MLX-LM (Apple)",   "mlx_lm"),
    (re.compile(r"^openllm$",                re.I), "openllm",        "OpenLLM",          "openllm"),
    (re.compile(r"^ollama$",                 re.I), "ollama",         "Ollama (Python)",  "ollama_py"),
    (re.compile(r"^mistral[_-]?",            re.I), "mistral",        "Mistral",          "generic"),
    (re.compile(r"^phi[_-]?",               re.I), "phi",            "Phi",              "generic"),
]


_ADAPTER_ALIASES: dict[str, str] = {
    "mistral": "generic",
    "phi": "generic",
    "openllm": "openllm",
}

_RUNNABLE_ADAPTERS: set[str] = {
    "llama_cpp",
    "gpt4all",
    "transformers",
    "qwen",
    "ctransformers",
    "mlx_lm",
    "ollama_py",
    "openllm",
    "generic",
    "custom",
    "triangulation",
}

_INFERENCE_DISPATCHABLE_ADAPTERS: set[str] = {
    "llama_cpp",
    "gpt4all",
    "transformers",
    "qwen",
    "ctransformers",
    "mlx_lm",
    "ollama_py",
    "openllm",
    "generic",
    "custom",
}

# ---------------------------------------------------------------------------
# Package scanning
# ---------------------------------------------------------------------------

def _normalize_pkg_name(name: str) -> str:
    return re.sub(r"[-_]+", "-", name).lower()


def scan_installed_llm_packages() -> list[dict[str, str]]:
    """Return list of installed LLM packages found in this Python environment."""
    found: list[dict[str, str]] = []
    seen: set[str] = set()

    try:
        dists = list(importlib.metadata.distributions())
    except Exception:
        return found

    for dist in dists:
        raw_name: str = dist.metadata.get("Name", "") or ""
        if not raw_name:
            continue
        norm = _normalize_pkg_name(raw_name)
        if norm in seen:
            continue

        for pattern, module, display, adapter in _KNOWN_PACKAGES:
            if pattern.search(norm):
                # Verify the module is actually importable
                try:
                    importlib.import_module(module)
                    importable = True
                except ImportError:
                    # Try dash→underscore variant
                    alt = norm.replace("-", "_")
                    try:
                        importlib.import_module(alt)
                        module = alt
                        importable = True
                    except ImportError:
                        importable = False

                seen.add(norm)
                version = dist.metadata.get("Version", "")
                found.append({
                    "name": norm,
                    "model_id": norm,
                    "module": module,
                    "display": f"{display} ({raw_name} {version})".strip(),
                    "adapter": adapter,
                    "importable": "true" if importable else "false",
                    "reason_unusable": "" if importable else f"{module}_not_importable",
                    "version": version,
                })
                break

    return found


# ---------------------------------------------------------------------------
# Triangulation baseline
# ---------------------------------------------------------------------------

def _find_triangulation_model() -> dict[str, str] | None:
    if not TRIANGULATION_DIR.exists():
        return None
    files = sorted(TRIANGULATION_DIR.glob("single_triangulation_baseline_*.json"))
    if not files:
        return None
    return {
        "name": "triangulation-baseline",
        "path": str(files[-1]),
        "backend": "python_triangulation",
        "display": "Triangulation Baseline (built-in, no LLM)",
        "adapter": "triangulation",
        "importable": "true",
    }


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

def _load_registry() -> list[dict[str, str]]:
    if not REGISTRY_FILE.exists():
        return []
    try:
        payload = json.loads(REGISTRY_FILE.read_text(encoding="utf-8"))
        entries = payload.get("models", payload) if isinstance(payload, dict) else payload
        result = []
        for entry in entries:
            if isinstance(entry, str):
                result.append({"name": entry, "adapter": "custom", "display": entry})
            elif isinstance(entry, dict) and entry.get("name"):
                result.append({k: str(v) for k, v in entry.items()})
        return result
    except (json.JSONDecodeError, OSError):
        return []



def _normalize_adapter_key(adapter: str) -> str:
    return _ADAPTER_ALIASES.get(adapter, adapter)


def _resolve_adapter(entry: dict[str, str]) -> tuple[str, str | None]:
    adapter = _normalize_adapter_key(entry.get("adapter", "custom"))
    module = entry.get("module", "")
    if adapter == "openllm":
        if not module:
            module = "openllm"
            entry["module"] = module
        if not _module_available(module):
            return adapter, f"{module}_not_importable"
    if adapter not in _RUNNABLE_ADAPTERS:
        return adapter, f"unsupported_adapter:{adapter}"
    return adapter, None


def validate_discovered_adapters(models: list[dict[str, str]] | None = None) -> list[tuple[str, str]]:
    models = models if models is not None else discover_models_detailed()
    mismatches: list[tuple[str, str]] = []
    for model in models:
        adapter = _normalize_adapter_key(model.get("adapter", "custom"))
        importable = model.get("importable", "false") == "true"
        reason = (model.get("reason_unusable", "") or "").strip()
        dispatchable = adapter in _INFERENCE_DISPATCHABLE_ADAPTERS
        if adapter not in _RUNNABLE_ADAPTERS:
            mismatches.append((model.get("name", ""), model.get("adapter", "")))
            continue
        if importable and (not dispatchable) and not reason:
            mismatches.append((model.get("name", ""), model.get("adapter", "")))
    if mismatches:
        _log.warning("Discovered adapter keys are not runnable: %s", mismatches)
    return mismatches

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def _normalize_entry(entry: dict[str, Any]) -> dict[str, str]:
    normalized = {k: str(v) for k, v in entry.items() if v is not None}
    normalized.setdefault("name", "")
    normalized.setdefault("display", normalized["name"])
    normalized.setdefault("adapter", "custom")
    normalized["adapter"] = _normalize_adapter_key(normalized["adapter"])
    normalized.setdefault("importable", "false")
    if normalized.get("importable") not in ("true", "false"):
        normalized["importable"] = "false"
    if normalized["importable"] == "false" and not normalized.get("reason_unusable"):
        normalized["reason_unusable"] = "missing_runtime_requirements"
    adapter, adapter_reason = _resolve_adapter(normalized)
    normalized["adapter"] = adapter
    if adapter_reason:
        normalized["importable"] = "false"
        normalized["reason_unusable"] = adapter_reason
    if normalized.get("importable") == "true" and adapter not in _INFERENCE_DISPATCHABLE_ADAPTERS:
        normalized["importable"] = "false"
        normalized["reason_unusable"] = f"non_dispatchable_adapter:{adapter}"
    has_locator = bool(normalized.get("path") or normalized.get("model_id"))
    if normalized.get("adapter") in ("triangulation", "generic") and not has_locator:
        has_locator = True
    if not has_locator and not normalized.get("reason_unusable"):
        normalized["reason_unusable"] = "missing_locator"
    return normalized




def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _windows_script_timeout_seconds() -> float:
    try:
        return float(os.getenv("ANTENNAMAP_DISCOVERY_TIMEOUT_SECONDS", "15"))
    except ValueError:
        return 15.0


def _as_confidence(value: Any, default: float = 0.5) -> str:
    try:
        score = float(value)
    except (TypeError, ValueError):
        score = default
    if score < 0:
        score = 0
    if score > 1:
        score = 1
    return f"{score:.2f}"

def _slugify_name(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "discovered-model"


def _path_hash_suffix(path: str) -> str:
    digest = hashlib.sha1(path.encode("utf-8")).hexdigest()
    return digest[:8]


def _adapter_from_external_kind(kind: str, path: str) -> tuple[str, bool]:
    kind_l = kind.lower()
    path_l = path.lower()
    if path.startswith("ollama:") or kind_l in {"ollama", "ollama_blob"}:
        return "ollama_py", True
    if path_l.endswith(".gguf") or kind_l == "gguf":
        return "llama_cpp", True
    if kind_l in {"metadata_dir", "safetensors"} or "models--" in path_l:
        return "transformers", True
    if kind_l in {"weights", "bin"}:
        return "generic", True
    return "generic", False


def _translate_external_record(item: dict[str, Any], used_names: set[str] | None = None) -> dict[str, str] | None:
    name = str(item.get("Name", "")).strip()
    path = str(item.get("Path", "")).strip()
    kind = str(item.get("Kind", "")).strip()
    if not name or not path:
        return None
    detector = str(item.get("Detector", "external_scanner")).strip() or "external_scanner"
    details = item.get("Details", {})
    adapter, kind_supported = _adapter_from_external_kind(kind, path)
    locator_model_id = ""
    locator_path = path
    if path.startswith("ollama:"):
        locator_model_id = path.split(":", 1)[1]
        locator_path = ""
    import_module = {"llama_cpp": "llama_cpp", "transformers": "transformers", "ollama_py": "ollama"}.get(adapter)
    module_ok = _module_available(import_module) if import_module else True
    importable = "true" if module_ok else "false"
    reason = ""
    if not kind_supported:
        importable = "false"
        reason = f"unsupported_kind:{kind or 'unknown'}"
    elif adapter not in _INFERENCE_DISPATCHABLE_ADAPTERS:
        importable = "false"
        reason = f"unsupported_kind:{kind or 'unknown'}"
    elif importable == "false":
        reason = f"{import_module}_not_importable" if import_module else "missing_runtime_requirements"
    base = _slugify_name(name)
    candidate = base
    if used_names is not None and candidate in used_names:
        candidate = f"{base}-{_path_hash_suffix(path)}"
    if used_names is not None:
        used_names.add(candidate)
    entry = {
        "name": candidate,
        "display": f"{name} ({kind or 'unknown'})",
        "adapter": adapter,
        "importable": importable,
        "reason_unusable": reason,
        "source": "windows_powershell_external",
        "source_detail": detector,
        "kind": kind,
        "confidence": _as_confidence(item.get("Confidence", 0.5)),
        "size_gb": str(item.get("SizeGB", "")),
        "details": json.dumps(details, sort_keys=True) if isinstance(details, (dict, list)) else str(details),
    }
    if locator_model_id:
        entry["model_id"] = locator_model_id
    else:
        entry["path"] = locator_path
    return entry


def _load_external_discovery_results() -> dict[str, Any]:
    diagnostics: dict[str, Any] = {"source": "windows_powershell_external", "count": 0, "searched_paths": [], "error": ""}
    if platform.system().lower() != "windows":
        diagnostics["error"] = "not_windows"
        return {"models": [], "diagnostics": diagnostics}
    script = ROOT / "scripts" / "Find-Any-Local-LLM-Models.ps1"
    if not script.exists():
        diagnostics["error"] = "script_missing"
        return {"models": [], "diagnostics": diagnostics}
    cmd = [os.getenv("ANTENNAMAP_POWERSHELL_BIN", "powershell"), "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script), "-EmitJson"]
    if _env_flag("ANTENNAMAP_DISCOVERY_DEEP_SCAN", False):
        cmd.append("-DeepScan")
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=_windows_script_timeout_seconds(), check=False)
    except subprocess.TimeoutExpired:
        diagnostics["error"] = "timeout"
        return {"models": [], "diagnostics": diagnostics}
    except OSError as exc:
        diagnostics["error"] = f"invoke_error:{exc}"
        return {"models": [], "diagnostics": diagnostics}
    if proc.returncode != 0:
        diagnostics["error"] = f"exit_{proc.returncode}"
        return {"models": [], "diagnostics": diagnostics}
    try:
        records = json.loads(proc.stdout.strip() or "[]")
    except json.JSONDecodeError:
        diagnostics["error"] = "invalid_json"
        return {"models": [], "diagnostics": diagnostics}
    used_names: set[str] = set()
    out: list[dict[str, str]] = []
    for item in records if isinstance(records, list) else []:
        if not isinstance(item, dict):
            continue
        translated = _translate_external_record(item, used_names=used_names)
        if translated:
            out.append(translated)
    diagnostics["count"] = len(out)
    return {"models": out, "diagnostics": diagnostics}

def _map_windows_script_findings(payload: dict[str, Any]) -> list[dict[str, str]]:
    findings = payload.get("findings", []) if isinstance(payload, dict) else []
    models: list[dict[str, str]] = []
    llama_available = _module_available("llama_cpp")
    transformers_available = _module_available("transformers")
    for item in findings:
        if not isinstance(item, dict):
            continue
        path = str(item.get("path", ""))
        name = str(item.get("name", "")).strip()
        kind = str(item.get("kind", ""))
        detector = str(item.get("detector", "powershell"))
        details = item.get("details", {})
        confidence = str(item.get("confidence", ""))

        adapter = "custom"
        importable = "false"
        reason = "custom_runtime_adapter_missing"
        model_id = ""

        if path.startswith("ollama:") or kind == "ollama":
            adapter = "ollama_py"
            importable = "true" if _module_available("ollama") else "false"
            reason = "" if importable == "true" else "ollama_not_importable"
            model_id = path.replace("ollama:", "") or name
        elif path.lower().endswith(".gguf") or kind == "gguf":
            adapter = "llama_cpp"
            importable = "true" if llama_available else "false"
            reason = "" if importable == "true" else "llama_cpp_not_importable"
        elif kind == "metadata_dir" or "models--" in path:
            adapter = "transformers"
            importable = "true" if transformers_available else "false"
            reason = "" if importable == "true" else "transformers_not_importable"

        entry = {
            "name": name or f"file:{Path(path).stem}",
            "display": f"Windows discovered: {name or Path(path).name}",
            "adapter": adapter,
            "importable": importable,
            "reason_unusable": reason,
            "source": "windows_powershell",
            "source_detail": detector or "powershell",
            "kind": kind,
            "confidence": _as_confidence(confidence),
            "details": json.dumps(details, sort_keys=True) if isinstance(details, (dict, list)) else str(details),
        }
        if model_id:
            entry["model_id"] = model_id
        else:
            entry["path"] = path
        models.append(entry)
    return models


def _discover_windows_with_script() -> dict[str, Any]:
    diagnostics: dict[str, Any] = {"source": "windows_powershell", "count": 0, "searched_paths": [], "error": ""}
    if platform.system().lower() != "windows":
        diagnostics["error"] = "not_windows"
        return {"models": [], "diagnostics": diagnostics}
    script = ROOT / "scripts" / "find_any_local_llm_models.ps1"
    if not script.exists():
        diagnostics["error"] = "script_missing"
        return {"models": [], "diagnostics": diagnostics}
    shell_cmd = os.getenv("ANTENNAMAP_POWERSHELL_BIN", "powershell")
    cmd = [shell_cmd, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script), "-EmitJson"]
    if _env_flag("ANTENNAMAP_DISCOVERY_DEEP_SCAN", False):
        cmd.append("-DeepScan")
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=_windows_script_timeout_seconds(), check=False)
    except subprocess.TimeoutExpired:
        diagnostics["error"] = "timeout"
        return {"models": [], "diagnostics": diagnostics}
    except OSError as exc:
        diagnostics["error"] = f"invoke_error:{exc}"
        return {"models": [], "diagnostics": diagnostics}
    if proc.returncode != 0:
        diagnostics["error"] = f"exit_{proc.returncode}"
        return {"models": [], "diagnostics": diagnostics}
    try:
        payload = json.loads(proc.stdout.strip() or "{}")
    except json.JSONDecodeError:
        diagnostics["error"] = "invalid_json"
        return {"models": [], "diagnostics": diagnostics}
    diagnostics["searched_paths"] = payload.get("searched_paths", []) if isinstance(payload, dict) else []
    models = _map_windows_script_findings(payload if isinstance(payload, dict) else {})
    diagnostics["count"] = len(models)
    return {"models": models, "diagnostics": diagnostics}


def _merge_models_preserve_first_runnable(models: list[dict[str, str]]) -> list[dict[str, str]]:
    merged: list[dict[str, str]] = []
    key_to_idx: dict[str, int] = {}
    for m in models:
        normalized = _normalize_entry(m)
        if not normalized.get("name"):
            continue
        canonical_locator = normalized.get("path", "").strip().lower() or normalized.get("model_id", "").strip().lower()
        name_key = normalized.get("name", "").strip().lower()
        stable_keys = [f"locator:{canonical_locator}"] if canonical_locator else []
        stable_keys.append(f"name:{name_key}")
        existing_idx = next((key_to_idx[k] for k in stable_keys if k in key_to_idx), None)
        if existing_idx is None:
            idx = len(merged)
            merged.append(normalized)
            for key in stable_keys:
                key_to_idx[key] = idx
            continue
        current = merged[existing_idx]
        current_runnable = current.get("importable") == "true" and not current.get("reason_unusable")
        incoming_runnable = normalized.get("importable") == "true" and not normalized.get("reason_unusable")
        if (not current_runnable) and incoming_runnable:
            merged[existing_idx] = normalized
        for key in stable_keys:
            key_to_idx[key] = existing_idx
    return merged

def discover_models_detailed() -> list[dict[str, str]]:
    return discover_models_with_metadata()["models"]


def discover_models_with_metadata() -> dict[str, Any]:
    """Return all discoverable local Python LLM models and discovery metadata."""
    models: list[dict[str, str]] = []
    sources = {"registry": 0, "packages": 0, "filesystem": 0, "huggingface_cache": 0, "triangulation": 0, "windows_powershell": 0}
    diagnostics: dict[str, Any] = {"windows_powershell": {"enabled": False, "error": "disabled", "searched_paths": []}}
    search_roots = _configured_search_roots()

    reg = _load_registry(); models.extend(reg); sources["registry"] = len(reg)
    pkgs = scan_installed_llm_packages(); models.extend(pkgs); sources["packages"] = len(pkgs)
    files = _find_model_files(search_roots); models.extend(files); sources["filesystem"] = len(files)
    hf = _find_hf_cache(); models.extend(hf); sources["huggingface_cache"] = len(hf)
    tri = _find_triangulation_model()
    if tri: models.append(tri); sources["triangulation"] = 1

    if _env_flag("ANTENNAMAP_DISCOVERY_USE_POWERSHELL", False):
        win = _load_external_discovery_results()
        win_models = win.get("models", [])
        models.extend(win_models)
        sources["windows_powershell"] = len(win_models)
        diag = win.get("diagnostics", {}) if isinstance(win, dict) else {}
        diag["enabled"] = True
        diagnostics["windows_powershell"] = diag

    unique = _merge_models_preserve_first_runnable(models)
    searched_paths = [str(p) for p in search_roots] + [str(p) for p in _hf_cache_roots()]
    win_paths = diagnostics.get("windows_powershell", {}).get("searched_paths", [])
    for path in win_paths:
        if path not in searched_paths:
            searched_paths.append(path)

    return {
        "models": unique,
        "searched_paths": searched_paths,
        "search_roots": [str(p) for p in search_roots],
        "env_cache_paths": [str(p) for p in _env_cache_roots()],
        "hf_cache_paths": [str(p) for p in _hf_cache_roots()],
        "source_counts": sources,
        "discovery_sources": diagnostics,
        "external_source_used": diagnostics.get("windows_powershell", {}).get("enabled", False),
        "external_entries_total": sources.get("windows_powershell", 0),
        "external_entries_runnable": sum(1 for m in unique if m.get("source") == "windows_powershell_external" and m.get("importable") == "true" and not m.get("reason_unusable")),
    }

def discover_python_local_models() -> list[str]:
    """Legacy: list of model names for backward compatibility."""
    return [m["name"] for m in discover_models_detailed()]


# ---------------------------------------------------------------------------
# File-based model discovery helpers
# ---------------------------------------------------------------------------

_MODEL_EXTENSIONS = (".gguf", ".bin", ".safetensors")
_METADATA_FILENAMES = {"config.json", "tokenizer.json", "tokenizer_config.json", "adapter_config.json"}


def _configured_search_roots() -> list[Path]:
    defaults = [Path("/workspace"), Path.home(), ROOT, Path("/models"), Path("/opt/models")]
    defaults.extend(_env_cache_roots())
    configured: list[str] = []
    raw_env = os.getenv("ANTENNAMAP_MODEL_SEARCH_PATHS", "")
    if raw_env.strip():
        configured.extend([part.strip() for part in raw_env.split(os.pathsep) if part.strip()])
    if DISCOVERY_CONFIG_FILE.exists():
        try:
            payload = json.loads(DISCOVERY_CONFIG_FILE.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                value = payload.get("model_search_paths", [])
                if isinstance(value, list):
                    configured.extend([str(item) for item in value if str(item).strip()])
        except (json.JSONDecodeError, OSError):
            pass
    paths = [Path(item).expanduser() for item in configured] + defaults
    unique: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        normalized = str(path.resolve()) if path.exists() else str(path)
        if normalized not in seen:
            seen.add(normalized)
            unique.append(path)
    return unique


def _find_model_files(search_roots: list[Path]) -> list[dict[str, str]]:
    found = []
    seen: set[str] = set()
    llama_available = _module_available("llama_cpp")
    transformers_available = _module_available("transformers")
    for d in search_roots:
        if not d.exists():
            continue
        for f in d.rglob("*"):
            if not f.is_file():
                continue
            if f.suffix.lower() not in _MODEL_EXTENSIONS:
                continue
            if str(f) in seen:
                continue
            seen.add(str(f))
            adapter = "llama_cpp" if f.suffix.lower() == ".gguf" else "custom"
            runtime_available = llama_available if adapter == "llama_cpp" else False
            reason = "" if runtime_available else (f"{adapter}_not_importable" if adapter == "llama_cpp" else "custom_runtime_adapter_missing")
            found.append({
                "name": f"file:{f.stem}",
                "path": str(f),
                "adapter": adapter,
                "display": f"Local file: {f.name}",
                "importable": "true" if runtime_available else "false",
                "reason_unusable": reason,
            })

        for meta_dir in _find_metadata_model_dirs(d):
            meta_key = str(meta_dir)
            if meta_key in seen:
                continue
            seen.add(meta_key)
            model_id = _infer_model_id_from_path(meta_dir)
            found.append({
                "name": f"meta:{model_id}",
                "path": str(meta_dir),
                "model_id": model_id,
                "adapter": "transformers",
                "display": f"Metadata model: {meta_dir.name}",
                "importable": "true" if transformers_available else "false",
                "reason_unusable": "" if transformers_available else "transformers_not_importable",
                "detector": "metadata_scan",
            })
    return found


def _find_metadata_model_dirs(root: Path) -> list[Path]:
    dirs: list[Path] = []
    for marker in _METADATA_FILENAMES:
        for marker_path in root.rglob(marker):
            parent = marker_path.parent
            if parent not in dirs:
                dirs.append(parent)
    return dirs


def _infer_model_id_from_path(path: Path) -> str:
    name = path.name
    if name.startswith("models--"):
        return name.removeprefix("models--").replace("--", "/")
    return name


def _find_hf_cache() -> list[dict[str, str]]:
    found = []
    transformers_available = _module_available("transformers")
    for hf_hub in _hf_cache_roots():
        if not hf_hub.exists():
            continue
        for d in hf_hub.iterdir():
            if d.is_dir() and d.name.startswith("models--"):
                model_id = d.name.removeprefix("models--").replace("--", "/")
                found.append({
                    "name": f"hf:{model_id}",
                    "path": str(d),
                    "model_id": model_id,
                    "adapter": "transformers",
                    "display": f"HuggingFace: {model_id}",
                    "importable": "true" if transformers_available else "false",
                    "reason_unusable": "" if transformers_available else "transformers_not_importable",
                })
    return found


def _env_cache_roots() -> list[Path]:
    candidates = [
        os.getenv("HUGGINGFACE_HUB_CACHE", ""),
        os.getenv("TRANSFORMERS_CACHE", ""),
        os.getenv("HF_HOME", ""),
        os.getenv("OLLAMA_MODELS", ""),
        os.getenv("GPT4ALL_MODEL_PATH", ""),
        os.getenv("LLAMA_CPP_MODELS", ""),
        os.getenv("XDG_CACHE_HOME", ""),
    ]
    roots: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        if not candidate:
            continue
        path = Path(candidate).expanduser()
        if candidate == os.getenv("HF_HOME", "") and path.name != "hub":
            path = path / "hub"
        key = str(path)
        if key not in seen:
            seen.add(key)
            roots.append(path)
    return roots


def _hf_cache_roots() -> list[Path]:
    candidates = [str(p) for p in _env_cache_roots()] + [str(Path.home() / ".cache" / "huggingface" / "hub")]
    roots: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        if not candidate:
            continue
        path = Path(candidate).expanduser()
        if path.name != "hub" and candidate == os.getenv("HF_HOME", ""):
            path = path / "hub"
        key = str(path)
        if key not in seen:
            seen.add(key)
            roots.append(path)
    return roots


def _module_available(module: str) -> bool:
    try:
        importlib.import_module(module)
        return True
    except ImportError:
        return False


# ---------------------------------------------------------------------------
# Inference adapters
# ---------------------------------------------------------------------------

def run_llm_inference(model_entry: dict[str, str], prompt: str, system_prompt: str = "") -> str:
    """Dispatch inference to the appropriate adapter based on model_entry['adapter']."""
    adapter = _normalize_adapter_key(model_entry.get("adapter", "generic"))

    if adapter == "llama_cpp":
        return _infer_llama_cpp(model_entry, prompt, system_prompt)
    if adapter == "gpt4all":
        return _infer_gpt4all(model_entry, prompt)
    if adapter == "transformers":
        return _infer_transformers(model_entry, prompt, system_prompt)
    if adapter == "qwen":
        return _infer_qwen(model_entry, prompt, system_prompt)
    if adapter == "ctransformers":
        return _infer_ctransformers(model_entry, prompt)
    if adapter == "mlx_lm":
        return _infer_mlx_lm(model_entry, prompt, system_prompt)
    if adapter == "ollama_py":
        return _infer_ollama_py(model_entry, prompt, system_prompt)
    if adapter == "openllm":
        return _infer_openllm(model_entry, prompt, system_prompt)
    if adapter in ("generic", "custom"):
        return _infer_generic(model_entry, prompt, system_prompt)
    raise RuntimeError(f"No adapter for: {adapter}")


def _infer_llama_cpp(entry: dict, prompt: str, system: str) -> str:
    from llama_cpp import Llama  # type: ignore[import]
    path = entry.get("path", entry["name"])
    llm = Llama(model_path=path, n_ctx=4096, verbose=False)
    full = f"<|system|>\n{system}\n<|user|>\n{prompt}\n<|assistant|>\n" if system else prompt
    out = llm(full, max_tokens=1024, stop=["<|user|>", "</s>"])
    return out["choices"][0]["text"].strip()


def _infer_gpt4all(entry: dict, prompt: str) -> str:
    from gpt4all import GPT4All  # type: ignore[import]
    model_name = entry.get("name", entry.get("path", ""))
    m = GPT4All(model_name)
    return m.generate(prompt, max_tokens=1024)


def _infer_transformers(entry: dict, prompt: str, system: str) -> str:
    from transformers import pipeline  # type: ignore[import]
    model_id = entry.get("path", entry.get("name", ""))
    if model_id.startswith("hf:"):
        model_id = model_id[3:]
    pipe = pipeline("text-generation", model=model_id, max_new_tokens=512)
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    result = pipe(messages)
    generated = result[0].get("generated_text", "")
    if isinstance(generated, list):
        return generated[-1].get("content", "")
    return generated[len(prompt):].strip() if generated.startswith(prompt) else generated


def _infer_qwen(entry: dict, prompt: str, system: str) -> str:
    """Adapter for Qwen packages (qwen, qwen2, qwen3, qwen-agent variants)."""
    module_name = entry.get("module", "qwen")

    # Try qwen_agent style
    try:
        mod = importlib.import_module(module_name)
        # Many Qwen packages expose a simple chat function
        if hasattr(mod, "chat"):
            return str(mod.chat(prompt))
        if hasattr(mod, "generate"):
            return str(mod.generate(prompt))
        # Try model class pattern
        for cls_name in ("Model", "Qwen", "QwenModel", "LLM"):
            if hasattr(mod, cls_name):
                instance = getattr(mod, cls_name)()
                for method in ("chat", "generate", "__call__"):
                    if hasattr(instance, method):
                        return str(getattr(instance, method)(prompt))
    except Exception as exc:
        _log.debug("Qwen direct API failed: %s", exc)

    # Fallback: try via transformers (Qwen models are HF-compatible)
    try:
        from transformers import AutoModelForCausalLM, AutoTokenizer  # type: ignore[import]
        import torch  # type: ignore[import]
        model_id = entry.get("name", "Qwen/Qwen2.5-0.5B-Instruct")
        # Strip qwen- prefix if it looks like a package name not a model ID
        if "/" not in model_id:
            model_id = f"Qwen/{model_id}"
        tok = AutoTokenizer.from_pretrained(model_id)
        model = AutoModelForCausalLM.from_pretrained(model_id, torch_dtype="auto")
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        text = tok.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        inputs = tok([text], return_tensors="pt")
        out = model.generate(**inputs, max_new_tokens=512)
        generated = tok.decode(out[0][inputs.input_ids.shape[1]:], skip_special_tokens=True)
        return generated.strip()
    except Exception as exc:
        raise RuntimeError(f"Qwen inference failed: {exc}") from exc


def _infer_ctransformers(entry: dict, prompt: str) -> str:
    from ctransformers import AutoModelForCausalLM  # type: ignore[import]
    path = entry.get("path", entry["name"])
    llm = AutoModelForCausalLM.from_pretrained(path)
    return llm(prompt)


def _infer_mlx_lm(entry: dict, prompt: str, system: str) -> str:
    from mlx_lm import load, generate  # type: ignore[import]
    model_id = entry.get("path", entry.get("name", ""))
    model, tokenizer = load(model_id)
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    formatted = tokenizer.apply_chat_template(messages, add_generation_prompt=True)
    return generate(model, tokenizer, prompt=formatted, max_tokens=512, verbose=False)


def _infer_ollama_py(entry: dict, prompt: str, system: str) -> str:
    """Use the ollama Python library (not the daemon HTTP API)."""
    import ollama  # type: ignore[import]
    model_id = entry.get("name", "").replace("ollama:", "")
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    resp = ollama.chat(model=model_id, messages=messages)
    return resp["message"]["content"]


def _infer_openllm(entry: dict, prompt: str, system: str) -> str:
    """Use OpenLLM client APIs when available, with generic fallback."""
    try:
        import openllm  # type: ignore[import]
    except ImportError as exc:
        raise RuntimeError(f"Cannot import openllm: {exc}") from exc

    model_id = entry.get("model_id") or entry.get("name", "")
    full_prompt = f"{system}\n\n{prompt}" if system else prompt

    if hasattr(openllm, "LLM"):
        try:
            llm = openllm.LLM(model_id) if model_id else openllm.LLM()
            for method in ("generate", "__call__"):
                if callable(getattr(llm, method, None)):
                    return str(getattr(llm, method)(full_prompt))
        except Exception as exc:
            _log.debug("OpenLLM LLM path failed: %s", exc)

    if hasattr(openllm, "client"):
        try:
            client = openllm.client.HTTPClient()
            if hasattr(client, "generate"):
                return str(client.generate(full_prompt))
        except Exception as exc:
            _log.debug("OpenLLM client path failed: %s", exc)

    return _infer_generic(entry, prompt, system)


def _infer_generic(entry: dict, prompt: str, system: str) -> str:
    """Try common inference patterns for unknown LLM packages."""
    module_name = entry.get("module", entry.get("name", ""))
    try:
        mod = importlib.import_module(module_name)
    except ImportError as exc:
        raise RuntimeError(f"Cannot import {module_name}: {exc}") from exc

    full_prompt = f"{system}\n\n{prompt}" if system else prompt

    # Try top-level functions
    for fn_name in ("chat", "generate", "complete", "run", "ask"):
        if callable(getattr(mod, fn_name, None)):
            return str(getattr(mod, fn_name)(full_prompt))

    # Try instantiating a class
    for cls_name in ("Model", "LLM", "Chat", "Assistant"):
        cls = getattr(mod, cls_name, None)
        if cls is None:
            continue
        try:
            instance = cls()
            for method in ("chat", "generate", "complete", "__call__"):
                if callable(getattr(instance, method, None)):
                    return str(getattr(instance, method)(full_prompt))
        except Exception:
            continue

    raise RuntimeError(f"No known inference API found in {module_name}")
