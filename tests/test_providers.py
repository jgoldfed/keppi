"""Tests for embedding providers (Ollama + OpenAI)."""
from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

from keppi.parser.config import Config


def _make_config(provider="ollama", model="nomic-embed-text", dimension=768, api_key_env="", base_url=""):
    config = Config()
    config.embed.provider = provider
    config.embed.model = model
    config.embed.dimension = dimension
    config.embed.api_key_env = api_key_env
    config.embed.base_url = base_url
    return config


class TestOllamaProvider:
    def test_embed_calls_correct_url(self):
        from keppi.search.providers import OllamaProvider

        config = _make_config()
        provider = OllamaProvider(config)

        mock_response = MagicMock()
        mock_response.json.return_value = {"embedding": [0.1, 0.2, 0.3]}
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.post", return_value=mock_response) as mock_post:
            result = provider.embed("hello world")
            mock_post.assert_called_once()
            call_args = mock_post.call_args
            assert call_args[0][0] == "http://localhost:11434/api/embeddings"
            assert call_args[1]["json"]["model"] == "nomic-embed-text"
            assert call_args[1]["json"]["prompt"] == "hello world"

        assert result == [0.1, 0.2, 0.3]

    def test_embed_uses_custom_base_url(self):
        from keppi.search.providers import OllamaProvider

        config = _make_config(base_url="http://my-ollama:11434")
        provider = OllamaProvider(config)

        mock_response = MagicMock()
        mock_response.json.return_value = {"embedding": [0.1]}
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.post", return_value=mock_response) as mock_post:
            provider.embed("test")
            url = mock_post.call_args[0][0]
            assert url.startswith("http://my-ollama:11434")

    def test_connect_error_raises_runtime_error(self):
        import httpx

        from keppi.search.providers import OllamaProvider

        config = _make_config()
        provider = OllamaProvider(config)

        with patch("httpx.post", side_effect=httpx.ConnectError("refused")):
            with pytest.raises(RuntimeError, match="Ollama"):
                provider.embed("test")


class TestOpenAIProvider:
    def test_embed_sends_auth_header(self):
        from keppi.search.providers import OpenAIProvider

        config = _make_config(
            provider="openai",
            model="text-embedding-3-small",
            dimension=1536,
            api_key_env="OPENAI_API_KEY",
        )
        provider = OpenAIProvider(config)

        mock_response = MagicMock()
        mock_response.json.return_value = {"data": [{"embedding": [0.5, 0.6]}]}
        mock_response.raise_for_status = MagicMock()

        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test-key"}):
            with patch("httpx.post", return_value=mock_response) as mock_post:
                result = provider.embed("hello")
                headers = mock_post.call_args[1]["headers"]
                assert headers["Authorization"] == "Bearer sk-test-key"

        assert result == [0.5, 0.6]

    def test_openai_parses_data_array_correctly(self):
        from keppi.search.providers import OpenAIProvider

        config = _make_config(
            provider="openai",
            model="text-embedding-3-small",
            dimension=1536,
            api_key_env="OPENAI_API_KEY",
        )
        provider = OpenAIProvider(config)

        # Response shape is data[0].embedding (list), not data.embedding
        mock_response = MagicMock()
        expected_vec = list(range(10))
        mock_response.json.return_value = {"data": [{"embedding": expected_vec}]}
        mock_response.raise_for_status = MagicMock()

        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-key"}):
            with patch("httpx.post", return_value=mock_response):
                result = provider.embed("test")

        assert result == expected_vec

    def test_missing_api_key_raises_env_error(self):
        from keppi.search.providers import OpenAIProvider

        config = _make_config(
            provider="openai",
            api_key_env="OPENAI_API_KEY",
        )
        provider = OpenAIProvider(config)

        # Ensure env var is absent
        env = {k: v for k, v in os.environ.items() if k != "OPENAI_API_KEY"}
        with patch.dict(os.environ, env, clear=True):
            with pytest.raises(EnvironmentError, match="OPENAI_API_KEY"):
                provider.embed("test")


class TestGetProvider:
    def test_unknown_provider_raises_value_error(self):
        from keppi.search.providers import get_provider

        config = _make_config(provider="unknown_provider")
        with pytest.raises(ValueError, match="unknown_provider"):
            get_provider(config)

    def test_ollama_factory(self):
        from keppi.search.providers import OllamaProvider, get_provider

        config = _make_config(provider="ollama")
        provider = get_provider(config)
        assert isinstance(provider, OllamaProvider)

    def test_openai_factory(self):
        from keppi.search.providers import OpenAIProvider, get_provider

        config = _make_config(provider="openai")
        provider = get_provider(config)
        assert isinstance(provider, OpenAIProvider)
