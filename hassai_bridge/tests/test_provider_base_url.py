from services.providers import normalize_provider_base_url


def test_normalize_provider_base_url_strips_chat_path():
    assert normalize_provider_base_url("https://api.x.ai/v1/chat/completions") == "https://api.x.ai/v1"
    assert normalize_provider_base_url("https://api.deepseek.com/chat/completions") == "https://api.deepseek.com"
    assert normalize_provider_base_url("https://api.openai.com/v1") == "https://api.openai.com/v1"
