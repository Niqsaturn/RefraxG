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
        if _normalize_adapter_key(model.get("adapter", "custom")) not in _RUNNABLE_ADAPTERS:
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
    has_locator = bool(normalized.get("path") or normalized.get("model_id"))
    if normalized.get("adapter") in ("triangulation", "generic") and not has_locator:
        has_locator = True
    if not has_locator and not normalized.get("reason_unusable"):
        normalized["reason_unusable"] = "missing_locator"
    return normalized


def discover_models_detailed() -> list[dict[str, str]]:
    return discover_models_with_metadata()["models"]


def discover_models_with_metadata() -> dict[str, Any]:
    """Return all discoverable local Python LLM models and discovery metadata."""
    models: list[dict[str, str]] = []
    sources = {"registry": 0, "packages": 0, "filesystem": 0, "huggingface_cache": 0, "triangulation": 0}
    search_roots = _configured_search_roots()

    # 1. Registry overrides first
    reg = _load_registry()
    models.extend(reg)
    sources["registry"] = len(reg)

    # 2. Installed LLM Python packages
    pkgs = scan_installed_llm_packages()
    models.extend(pkgs)
    sources["packages"] = len(pkgs)

    # 3. File-based models in configured locations
    files = _find_model_files(search_roots)
    models.extend(files)
    sources["filesystem"] = len(files)

    # 4. HuggingFace cached models
    hf = _find_hf_cache()
    models.extend(hf)
    sources["huggingface_cache"] = len(hf)

    # 5. Built-in triangulation baseline
    tri = _find_triangulation_model()
    if tri:
        models.append(tri)
        sources["triangulation"] = 1

    # Deduplicate by name
    seen: set[str] = set()
    unique: list[dict[str, str]] = []
    for m in models:
        normalized = _normalize_entry(m)
        if not normalized["name"]:
            continue
        if normalized["name"] not in seen:
            seen.add(normalized["name"])
            unique.append(normalized)
    return {
        "models": unique,
        "searched_paths": [str(p) for p in search_roots] + [str(p) for p in _hf_cache_roots()],
        "source_counts": sources,
    }


def discover_python_local_models() -> list[str]:
    """Legacy: list of model names for backward compatibility."""
    return [m["name"] for m in discover_models_detailed()]


# ---------------------------------------------------------------------------
# File-based model discovery helpers
# ---------------------------------------------------------------------------

_MODEL_EXTENSIONS = (".gguf", ".bin", ".safetensors")


def _configured_search_roots() -> list[Path]:
    defaults = [Path("/workspace"), Path.home(), ROOT, Path("/models"), Path("/opt/models")]
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
    return found


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


def _hf_cache_roots() -> list[Path]:
    candidates = [
        os.getenv("HUGGINGFACE_HUB_CACHE", ""),
        os.getenv("TRANSFORMERS_CACHE", ""),
        os.getenv("HF_HOME", ""),
        str(Path.home() / ".cache" / "huggingface" / "hub"),
    ]
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
