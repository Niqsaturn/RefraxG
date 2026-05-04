import backend.main as main
import backend.model_providers.python_local as py_local


def test_models_discover_detailed_schema(monkeypatch):
    monkeypatch.setattr(
        py_local,
        "discover_models_detailed",
        lambda: [
            {"name": "m1", "display": "M1", "adapter": "llama_cpp", "importable": "true", "path": "/tmp/m1.gguf"},
            {"name": "m2", "display": "M2", "adapter": "transformers", "importable": "false", "model_id": "org/m2", "reason_unusable": "missing_runtime_requirements"},
        ],
    )
    payload = main.discover_available_models()
    assert payload["runnable_count"] == 1
    assert payload["unusable_count"] == 1
    assert set(payload["python_local_detailed"][0].keys()) >= {"name", "display", "adapter", "importable"}


def test_discover_models_normalizes_importable_locator(monkeypatch):
    monkeypatch.setattr(py_local, "_load_registry", lambda: [{"name": "pkg-only", "display": "Pkg", "adapter": "generic", "importable": "true"}])
    monkeypatch.setattr(py_local, "scan_installed_llm_packages", lambda: [])
    monkeypatch.setattr(py_local, "_find_gguf_files", lambda: [])
    monkeypatch.setattr(py_local, "_find_hf_cache", lambda: [])
    monkeypatch.setattr(py_local, "_find_triangulation_model", lambda: None)
    discovered = py_local.discover_models_detailed()
    assert discovered[0]["model_id"] == "pkg-only"


def test_run_inference_valid_model_hits_adapter(monkeypatch):
    monkeypatch.setattr(
        py_local,
        "discover_models_detailed",
        lambda: [{"name": "ok", "display": "OK", "adapter": "llama_cpp", "importable": "true", "path": "/tmp/ok.gguf"}],
    )
    monkeypatch.setattr(py_local, "run_llm_inference", lambda entry, prompt: "adapter-hit")
    out = main.run_inference("python_local", "ok", {"prompt": "hello"})
    assert out["response"] == "adapter-hit"


def test_run_inference_unknown_model_explicit_error(monkeypatch):
    monkeypatch.setattr(py_local, "discover_models_detailed", lambda: [])
    out = main.run_inference("python_local", "missing", {"prompt": "x"})
    assert out["error_code"] == "not_found"


def test_run_inference_unusable_model_explicit_error(monkeypatch):
    monkeypatch.setattr(
        py_local,
        "discover_models_detailed",
        lambda: [{"name": "bad", "display": "Bad", "adapter": "llama_cpp", "importable": "false", "path": "/tmp/bad.gguf", "reason_unusable": "llama_cpp_not_importable"}],
    )
    out = main.run_inference("python_local", "bad", {"prompt": "x"})
    assert out["error_code"] == "unusable"
