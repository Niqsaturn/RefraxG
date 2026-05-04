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


def test_default_selection_prefers_bundled_qwen_when_runnable():
    model, reason = main._resolve_default_python_local_model([
        {"name": "other", "importable": "true", "adapter": "llama_cpp", "path": "/tmp/other.gguf"},
        {"name": "qwen3.5-4b-bundled", "importable": "true", "adapter": "llama_cpp", "path": "models/qwen3_5_4b/qwen3_5_4b.gguf"},
    ])
    assert model == "qwen3.5-4b-bundled"
    assert reason == "bundled_qwen_runnable"


def test_default_selection_skips_unusable_qwen():
    model, reason = main._resolve_default_python_local_model([
        {"name": "qwen3.5-4b-bundled", "importable": "false", "reason_unusable": "llama_cpp_not_importable"},
        {"name": "other", "importable": "true", "adapter": "llama_cpp", "path": "/tmp/other.gguf"},
    ])
    assert model == "other"
    assert reason == "next_runnable"


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


def test_map_windows_script_findings_to_normalized(monkeypatch):
    monkeypatch.setattr(py_local, "_module_available", lambda m: m in {"llama_cpp", "transformers"})
    payload = {
        "findings": [
            {"name": "m1", "path": "C:/models/m1.gguf", "kind": "gguf", "confidence": 0.9, "detector": "extension_scan", "details": {}},
            {"name": "org/demo", "path": "C:/hf/models--org--demo", "kind": "metadata_dir", "confidence": 0.8, "detector": "metadata_scan", "details": {}},
        ]
    }
    out = py_local._map_windows_script_findings(payload)
    assert out[0]["adapter"] == "llama_cpp"
    assert out[0]["importable"] == "true"
    assert out[1]["adapter"] == "transformers"

def test_translate_external_record_to_normalized(monkeypatch):
    monkeypatch.setattr(py_local, "_module_available", lambda m: m == "llama_cpp")
    record = {
        "Name": "Llama 3 8B",
        "Path": "C:/models/llama3.gguf",
        "Kind": "gguf",
        "Confidence": 0.93,
        "Detector": "extension_scan",
        "SizeGB": 4.2,
        "Details": {"x": 1},
    }
    out = py_local._translate_external_record(record, used_names=set())
    assert out is not None
    assert out["name"] == "llama-3-8b"
    assert out["adapter"] == "llama_cpp"
    assert out["importable"] == "true"
    assert out["display"] == "Llama 3 8B (gguf)"


def test_merge_models_dedup_prefers_first_runnable():
    merged = py_local._merge_models_preserve_first_runnable([
        {"name": "a", "path": "/x.gguf", "adapter": "llama_cpp", "importable": "false", "reason_unusable": "llama_cpp_not_importable"},
        {"name": "a", "path": "/x.gguf", "adapter": "llama_cpp", "importable": "true"},
        {"name": "b", "path": "/y.gguf", "adapter": "llama_cpp", "importable": "true"},
    ])
    assert len(merged) == 2
    assert merged[0]["importable"] == "true"

def test_merge_models_dedup_by_canonical_path_then_name():
    merged = py_local._merge_models_preserve_first_runnable([
        {"name": "alpha", "path": "C:/MODELS/A.GGUF", "adapter": "llama_cpp", "importable": "false", "reason_unusable": "llama_cpp_not_importable"},
        {"name": "beta", "path": "c:/models/a.gguf", "adapter": "llama_cpp", "importable": "true"},
        {"name": "gamma", "path": "c:/models/b.gguf", "adapter": "llama_cpp", "importable": "false", "reason_unusable": "llama_cpp_not_importable"},
    ])
    assert len(merged) == 2
    assert merged[0]["importable"] == "true"
    assert merged[0]["name"] == "beta"


def test_unsupported_kind_maps_reason_unusable():
    out = py_local._translate_external_record(
        {"Name": "x", "Path": "C:/models/x.unknown", "Kind": "unknown_kind", "Confidence": 0.2, "Detector": "x", "SizeGB": 1, "Details": {}},
        used_names=set(),
    )
    assert out is not None
    assert out["importable"] == "false"
    assert out["reason_unusable"] == "unsupported_kind:unknown_kind"


def test_windows_script_timeout_failure_does_not_crash(monkeypatch):
    monkeypatch.setenv("ANTENNAMAP_DISCOVERY_USE_POWERSHELL", "1")
    monkeypatch.setattr(py_local.platform, "system", lambda: "Windows")

    class DummyTimeout:
        def __call__(self, *args, **kwargs):
            raise py_local.subprocess.TimeoutExpired(cmd="x", timeout=1)

    monkeypatch.setattr(py_local.subprocess, "run", DummyTimeout())
    monkeypatch.setattr(py_local, "_load_registry", lambda: [])
    monkeypatch.setattr(py_local, "scan_installed_llm_packages", lambda: [])
    monkeypatch.setattr(py_local, "_find_model_files", lambda roots: [])
    monkeypatch.setattr(py_local, "_find_hf_cache", lambda: [])
    monkeypatch.setattr(py_local, "_find_triangulation_model", lambda: None)
    payload = py_local.discover_models_with_metadata()
    assert payload["models"] == []
    assert payload["discovery_sources"]["windows_powershell"]["error"] == "timeout"


def test_env_cache_roots_are_included_in_search(monkeypatch, tmp_path):
    ollama = tmp_path / "ollama_models"
    ollama.mkdir()
    monkeypatch.setenv("OLLAMA_MODELS", str(ollama))
    roots = py_local._configured_search_roots()
    assert any(str(r) == str(ollama) for r in roots)


def test_discovery_paths_can_be_overridden(monkeypatch, tmp_path):
    only = tmp_path / "only_here"
    only.mkdir()
    (only / "alpha.gguf").write_text("x", encoding="utf-8")
    monkeypatch.setenv("ANTENNAMAP_MODEL_SEARCH_PATHS", str(only))
    monkeypatch.setattr(py_local, "_module_available", lambda m: m == "llama_cpp")
    monkeypatch.setattr(py_local, "_load_registry", lambda: [])
    monkeypatch.setattr(py_local, "scan_installed_llm_packages", lambda: [])
    monkeypatch.setattr(py_local, "_find_hf_cache", lambda: [])
    monkeypatch.setattr(py_local, "_find_triangulation_model", lambda: None)
    payload = py_local.discover_models_with_metadata()
    assert any(m.get("path", "").endswith("alpha.gguf") for m in payload["models"])
    assert str(only) in payload["searched_paths"]


def test_merge_preserves_source_and_confidence_fields():
    merged = py_local._merge_models_preserve_first_runnable([
        {"name": "z", "path": "/m.gguf", "adapter": "llama_cpp", "importable": "false", "reason_unusable": "llama_cpp_not_importable", "source": "filesystem", "confidence": "0.40"},
        {"name": "z", "path": "/m.gguf", "adapter": "llama_cpp", "importable": "true", "source": "windows_powershell", "confidence": "0.90"},
    ])
    assert merged[0]["importable"] == "true"
    assert merged[0]["source"] == "windows_powershell"
    assert merged[0]["confidence"] == "0.90"

def test_metadata_folders_are_detected_as_models(monkeypatch, tmp_path):
    model_dir = tmp_path / "meta_model"
    model_dir.mkdir()
    (model_dir / "config.json").write_text("{}", encoding="utf-8")
    (model_dir / "tokenizer.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(py_local, "_module_available", lambda m: m == "transformers")
    out = py_local._find_model_files([tmp_path])
    hit = next((m for m in out if m.get("path") == str(model_dir)), None)
    assert hit is not None
    assert hit["adapter"] == "transformers"
    assert hit["importable"] == "true"


def test_discovery_exposes_search_root_metadata(monkeypatch, tmp_path):
    cache_root = tmp_path / "ollama"
    cache_root.mkdir()
    monkeypatch.setenv("OLLAMA_MODELS", str(cache_root))
    monkeypatch.setattr(py_local, "_load_registry", lambda: [])
    monkeypatch.setattr(py_local, "scan_installed_llm_packages", lambda: [])
    monkeypatch.setattr(py_local, "_find_model_files", lambda roots: [])
    monkeypatch.setattr(py_local, "_find_hf_cache", lambda: [])
    monkeypatch.setattr(py_local, "_find_triangulation_model", lambda: None)
    payload = py_local.discover_models_with_metadata()
    assert str(cache_root) in payload["env_cache_paths"]
    assert str(cache_root) in payload["search_roots"]
