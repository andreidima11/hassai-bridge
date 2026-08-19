from services.providers import normalize_model_entry, normalize_model_list


def test_normalize_model_entry_variants():
    assert normalize_model_entry("gpt-4o-mini") == {"id": "gpt-4o-mini", "name": "gpt-4o-mini"}
    assert normalize_model_entry({"id": "gpt-4o"}) == {"id": "gpt-4o", "name": "gpt-4o"}
    assert normalize_model_entry({"model": "llama3", "name": "Llama 3"}) == {
        "id": "llama3",
        "name": "Llama 3",
    }
    assert normalize_model_entry({}) is None


def test_normalize_model_list_dedupes_and_sorts():
    payload = {
        "data": [
            {"model": "z-model"},
            {"id": "a-model"},
            {"id": "a-model"},
            "b-model",
        ]
    }
    rows = normalize_model_list(payload)
    assert [row["id"] for row in rows] == ["a-model", "b-model", "z-model"]
