"""Ollama and OpenAI embedding providers for Keppi semantic search."""
from __future__ import annotations

import os
import struct
from abc import ABC, abstractmethod


def serialize_vector(vec: list[float]) -> bytes:
    """Pack float list to little-endian binary for sqlite-vec (float32)."""
    return struct.pack(f"{len(vec)}f", *vec)


def get_provider(config) -> "EmbedProvider":
    """Factory: return provider for config.embed.provider. Raises on unknown."""
    name = config.embed.provider.lower()
    if name == "ollama":
        return OllamaProvider(config)
    elif name == "openai":
        return OpenAIProvider(config)
    else:
        raise ValueError(
            f"Unknown embed provider: {name!r}. "
            f"Phase 1 supports: ollama, openai"
        )


class EmbedProvider(ABC):
    def __init__(self, config):
        self.config = config

    @abstractmethod
    def embed(self, text: str) -> list[float]:
        """Embed text. Raises RuntimeError on failure."""
        ...

    def _api_key(self) -> str:
        env_var = self.config.embed.api_key_env
        if not env_var:
            return ""
        key = os.environ.get(env_var, "")
        if not key:
            raise EnvironmentError(
                f"API key env var '{env_var}' is not set. "
                f"Export it first: export {env_var}=your_key"
            )
        return key

    def _base_url(self, default: str) -> str:
        return self.config.embed.base_url or default


class OllamaProvider(EmbedProvider):
    """Local Ollama embedding via HTTP API. No API key required."""

    def embed(self, text: str) -> list[float]:
        import httpx
        base = self._base_url("http://localhost:11434")
        url = f"{base}/api/embeddings"
        try:
            resp = httpx.post(
                url,
                json={"model": self.config.embed.model, "prompt": text},
                timeout=30.0,
            )
            resp.raise_for_status()
            return resp.json()["embedding"]
        except httpx.ConnectError:
            raise RuntimeError(
                f"Could not reach Ollama at {base} — "
                f"is Ollama running? Try: ollama serve"
            )
        except Exception as e:
            raise RuntimeError(f"Ollama embedding failed: {e}")


class OpenAIProvider(EmbedProvider):
    """OpenAI Embeddings API."""

    def embed(self, text: str) -> list[float]:
        import httpx
        base = self._base_url("https://api.openai.com")
        url = f"{base}/v1/embeddings"
        key = self._api_key()
        try:
            resp = httpx.post(
                url,
                headers={"Authorization": f"Bearer {key}"},
                json={"model": self.config.embed.model, "input": text},
                timeout=60.0,
            )
            resp.raise_for_status()
            return resp.json()["data"][0]["embedding"]
        except EnvironmentError:
            raise
        except Exception as e:
            raise RuntimeError(
                f"OpenAI embedding failed: {e} — "
                f"check your {self.config.embed.api_key_env} env var"
            )
