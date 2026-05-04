import backend.main as main
import backend.model_providers.python_local as py_local


def test_models_discover_detailed_schema(monkeypatch):
    monkeypatch.setattr(
        py_local,
        "discover_models_with_metadata",
        lambda: {
            "models": [
                {"name": "m1", "display": "M1", "adapter": "llama_cpp", "importable": "true", "path": "/tmp/m1.gguf"},
                {"name": "m2", "display": "M2", "adapter": "transformers", "importable": "false", "model_id": "org/m2", "reason_unusable": "missing_runtime_requirements"},
            ],
            "searched_paths": [],
            "source_counts": {},
        },
    )
    payload = main.discover_available_models()
    assert payload["runnable_count"] == 1
    assert payload["unusable_count"] == 1
    assert set(payload["python_local_detailed"][0].keys()) >= {"name", "display", "adapter", "importable"}


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


def test_env_configured_search_paths(monkeypatch, tmp_path):
    model_root = tmp_path / "models"
    model_root.mkdir()
    (model_root / "outside.gguf").write_text("x", encoding="utf-8")
    monkeypatch.setenv("ANTENNAMAP_MODEL_SEARCH_PATHS", str(model_root))
    monkeypatch.setattr(py_local, "_module_available", lambda m: m == "llama_cpp")
    results = py_local.discover_models_with_metadata()
    assert str(model_root) in results["searched_paths"]
    assert any(m.get("path", "").endswith("outside.gguf") for m in results["models"])


def test_non_default_hf_cache_dirs(monkeypatch, tmp_path):
    hf_home = tmp_path / "hf"
    hub = hf_home / "hub"
    (hub / "models--org--demo").mkdir(parents=True)
    monkeypatch.setenv("HF_HOME", str(hf_home))
    monkeypatch.setattr(py_local, "_module_available", lambda m: m == "transformers")
    models = py_local._find_hf_cache()
    assert any(m["model_id"] == "org/demo" for m in models)


def test_discovery_outside_hardcoded_dirs(monkeypatch, tmp_path):
    anywhere = tmp_path / "anywhere"
    anywhere.mkdir()
    (anywhere / "m.safetensors").write_text("x", encoding="utf-8")
    monkeypatch.setenv("ANTENNAMAP_MODEL_SEARCH_PATHS", str(anywhere))
    monkeypatch.setattr(py_local, "_module_available", lambda m: False)
    discovered = py_local._find_model_files([anywhere])
    assert any(item["path"].endswith("m.safetensors") for item in discovered)
    assert any(item["adapter"] == "custom" and item["reason_unusable"] for item in discovered)


def test_discovered_record_schema_stable(monkeypatch, tmp_path):
    model_root = tmp_path / "schema"
    model_root.mkdir()
    (model_root / "x.gguf").write_text("x", encoding="utf-8")
    monkeypatch.setenv("ANTENNAMAP_MODEL_SEARCH_PATHS", str(model_root))
    monkeypatch.setattr(py_local, "_module_available", lambda m: True if m in {"llama_cpp", "transformers"} else False)
    payload = py_local.discover_models_with_metadata()
    required = {"name", "display", "adapter", "importable"}
    for record in payload["models"]:
        assert required.issubset(set(record.keys()))
        assert record["importable"] in {"true", "false"}
