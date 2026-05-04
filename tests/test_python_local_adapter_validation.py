import backend.model_providers.python_local as py_local


def test_discovered_unknown_adapter_is_marked_unusable():
    model = py_local._normalize_entry(
        {"name": "m1", "display": "M1", "adapter": "mystery", "importable": "true", "model_id": "x"}
    )
    assert model["importable"] == "false"
    assert model["reason_unusable"] == "unsupported_adapter:mystery"


def test_alias_adapters_are_normalized_to_runnable():
    model = py_local._normalize_entry(
        {"name": "m2", "display": "M2", "adapter": "phi", "importable": "true", "model_id": "x"}
    )
    assert model["adapter"] == "generic"
    assert "reason_unusable" not in model


def test_validate_discovered_adapters_catches_mismatch():
    mismatches = py_local.validate_discovered_adapters(
        [
            {"name": "ok", "adapter": "llama_cpp"},
            {"name": "bad", "adapter": "unknown_adapter"},
        ]
    )
    assert mismatches == [("bad", "unknown_adapter")]


def test_openllm_entry_is_deterministically_unusable_when_module_missing(monkeypatch):
    monkeypatch.setattr(py_local, "_module_available", lambda module: False)
    model = py_local._normalize_entry(
        {"name": "m3", "display": "M3", "adapter": "openllm", "importable": "true", "model_id": "x"}
    )
    assert model["importable"] == "false"
    assert model["reason_unusable"] == "openllm_not_importable"
