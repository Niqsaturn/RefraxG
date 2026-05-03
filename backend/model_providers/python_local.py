"""Python-native model discovery and inference.

Searches common local paths for GGUF, ONNX, HuggingFace, and sklearn models.
Supports llama-cpp-python, transformers, and the project's own triangulation
baseline JSON models as inference backends.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

_log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
REGISTRY_FILE = ROOT / "backend" / "model_providers" / "python_local_models.json"
MODEL_DIR = ROOT / "backend" / "models"
TRIANGULATION_DIR = ROOT / "models"

_GGUF_SEARCH_PATHS = [
    Path.home() / "models",
    Path.home() / ".local" / "share" / "models",
    Path.home() / ".local" / "share" / "nomic.ai" / "GPT4All",
    Path("/opt/models"),
    Path("/models"),
    ROOT / "models",
    ROOT / "backend" / "models",
]

_HUGGINGFACE_CACHE = Path.home() / ".cache" / "huggingface" / "hub"


def _check_llama_cpp() -> bool:
    try:
        import llama_cpp  # noqa: F401
        return True
    except ImportError:
        return False


def _check_transformers() -> bool:
    try:
        import transformers  # noqa: F401
        return True
    except ImportError:
        return False


def _find_gguf_models() -> list[dict[str, str]]:
    """Scan common paths for .gguf model files."""
    found: list[dict[str, str]] = []
    seen: set[str] = set()
    for search_dir in _GGUF_SEARCH_PATHS:
        if not search_dir.exists():
            continue
        for gguf_file in search_dir.rglob("*.gguf"):
            if str(gguf_file) in seen:
                continue
            seen.add(str(gguf_file))
            found.append({"name": gguf_file.stem, "path": str(gguf_file), "backend": "llama_cpp"})
    return found


def _find_hf_models() -> list[dict[str, str]]:
    """Scan HuggingFace cache for locally downloaded models."""
    if not _HUGGINGFACE_CACHE.exists():
        return []
    models = []
    for model_dir in _HUGGINGFACE_CACHE.iterdir():
        if model_dir.is_dir() and model_dir.name.startswith("models--"):
            model_name = model_dir.name.removeprefix("models--").replace("--", "/")
            models.append({"name": model_name, "path": str(model_dir), "backend": "transformers"})
    return models


def _find_triangulation_models() -> list[dict[str, str]]:
    """Return the single most recent triangulation baseline model."""
    if not TRIANGULATION_DIR.exists():
        return []
    files = sorted(TRIANGULATION_DIR.glob("single_triangulation_baseline_*.json"))
    if not files:
        return []
    latest = files[-1]
    return [{"name": "triangulation-baseline", "path": str(latest), "backend": "python_triangulation",
             "display": "Triangulation Baseline (latest)"}]


def _load_registry() -> list[dict[str, str]]:
    """Load user-defined model registry if it exists."""
    if not REGISTRY_FILE.exists():
        return []
    try:
        payload = json.loads(REGISTRY_FILE.read_text(encoding="utf-8"))
        entries = payload.get("models", payload) if isinstance(payload, dict) else payload
        result = []
        for entry in entries:
            if isinstance(entry, str):
                result.append({"name": entry, "path": "", "backend": "custom"})
            elif isinstance(entry, dict) and entry.get("name"):
                result.append({
                    "name": str(entry["name"]),
                    "path": str(entry.get("path", "")),
                    "backend": str(entry.get("backend", "custom")),
                })
        return result
    except (json.JSONDecodeError, OSError):
        return []


def discover_python_local_models() -> list[str]:
    """Legacy: return list of model name strings for backward compatibility."""
    return [m["name"] for m in discover_models_detailed()]


def discover_models_detailed() -> list[dict[str, str]]:
    """Return rich model entries with name, path, backend, and optional display label.

    Entry format:
        {name, path, backend, display?}
    where backend is one of: llama_cpp | transformers | python_triangulation | custom
    """
    models: list[dict[str, str]] = []

    # Registry entries take priority
    models.extend(_load_registry())

    # GGUF models (llama-cpp-python backend)
    if _check_llama_cpp() or True:  # always scan — user might install later
        models.extend(_find_gguf_models())

    # HuggingFace models
    if _check_transformers() or True:
        models.extend(_find_hf_models())

    # Other artifact types in the backend/models dir
    if MODEL_DIR.exists():
        for artifact in MODEL_DIR.iterdir():
            if artifact.suffix.lower() in {".pt", ".pth", ".onnx", ".pkl", ".joblib"}:
                models.append({"name": artifact.stem, "path": str(artifact), "backend": "custom"})

    # Project's own triangulation baseline
    models.extend(_find_triangulation_models())

    # Deduplicate by name
    seen: set[str] = set()
    unique: list[dict[str, str]] = []
    for m in models:
        if m["name"] not in seen:
            seen.add(m["name"])
            unique.append(m)
    return unique


def infer_with_gguf(model_path: str, prompt: str, max_tokens: int = 512) -> str:
    """Run inference via llama-cpp-python on a GGUF model file."""
    try:
        from llama_cpp import Llama  # type: ignore[import]
        llm = Llama(model_path=model_path, n_ctx=2048, verbose=False)
        output = llm(prompt, max_tokens=max_tokens, stop=["</s>", "\n\n"])
        return output["choices"][0]["text"].strip()
    except ImportError:
        raise RuntimeError("llama-cpp-python is not installed. Run: pip install llama-cpp-python")
    except Exception as exc:
        raise RuntimeError(f"GGUF inference failed: {exc}") from exc


def infer_with_transformers(model_name_or_path: str, prompt: str, max_new_tokens: int = 256) -> str:
    """Run inference via HuggingFace transformers."""
    try:
        from transformers import pipeline  # type: ignore[import]
        pipe = pipeline("text-generation", model=model_name_or_path, max_new_tokens=max_new_tokens)
        results = pipe(prompt)
        return results[0]["generated_text"][len(prompt):].strip()
    except ImportError:
        raise RuntimeError("transformers is not installed. Run: pip install transformers")
    except Exception as exc:
        raise RuntimeError(f"Transformers inference failed: {exc}") from exc
