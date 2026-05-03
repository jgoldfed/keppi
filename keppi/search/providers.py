"""Ollama and OpenAI embedding providers for Keppi semantic search."""
from __future__ import annotations

import os
import struct
from abc import ABC, abstractmethod


class ContextLengthError(RuntimeError):
    """Input text exceeds the model's context window — must be split further."""
    pass


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
        """Embed a single text. Raises RuntimeError on failure."""
        ...

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed multiple texts. Default: sequential calls to embed().

        Providers that support batch embedding should override this
        for better performance.
        """
        return [self.embed(t) for t in texts]

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
    """Local Ollama embedding via HTTP API. No API key required.

    Uses /api/embed (batch) endpoint for embed_batch(), which is
    significantly faster than one-at-a-time /api/embeddings calls.
    Falls back to /api/embeddings for single embed() calls.
    """

    # Batch size for /api/embed calls — Ollama processes all inputs
    # in one model load, so larger batches amortize the startup cost.
    # Memory-bound: nomic-embed-text is ~560MB, so even 64 texts
    # at 8K chars each fits comfortably in RAM.
    BATCH_SIZE = 32

    def __init__(self, config):
        super().__init__(config)
        self._model_warmed_up = False

    def _ensure_model_loaded(self, base: str, log) -> None:
        """Pre-load the model via /api/embeddings with num_ctx=8192.

        Some Ollama builds validate input length in /api/embed against the
        already-loaded model's context window rather than the options in the
        request. By warming up via /api/embeddings (which does honor options)
        we ensure the model is resident in Ollama's memory with num_ctx=8192
        before any /api/embed batch call touches it.
        """
        import httpx

        if self._model_warmed_up:
            return
        self._model_warmed_up = True
        try:
            httpx.post(
                f"{base}/api/embeddings",
                json={
                    "model": self.config.embed.model,
                    "prompt": " ",
                    "options": {"num_ctx": 8192},
                    "keep_alive": "60m",
                },
                timeout=60.0,
            )
            log.debug("Warmed up %s with num_ctx=8192", self.config.embed.model)
        except Exception as exc:
            log.debug("Model warmup failed (non-fatal): %s", exc)

    def embed(self, text: str) -> list[float]:
        """Embed a single text via /api/embeddings (legacy single endpoint)."""
        import logging
        import time

        import httpx

        base = self._base_url("http://localhost:11434")
        url = f"{base}/api/embeddings"
        log = logging.getLogger("keppi.embed")

        last_exc: Exception | None = None
        for attempt in range(4):
            if attempt:
                time.sleep(min(2 ** attempt, 8))
            try:
                resp = httpx.post(
                    url,
                    json={
                        "model": self.config.embed.model,
                        "prompt": text,
                        "options": {"num_ctx": 8192},
                    },
                    timeout=30.0,
                )
                if resp.status_code == 500:
                    body = resp.text
                    log.debug("Ollama 500 (attempt %d/4): %s", attempt + 1, body)
                    if "context length" in body:
                        raise ContextLengthError(
                            f"Chunk too long for model context: {body[:80]}"
                        )
                    last_exc = RuntimeError(f"Ollama 500: {body[:120]}")
                    continue
                resp.raise_for_status()
                return resp.json()["embedding"]
            except httpx.ConnectError:
                raise RuntimeError(
                    f"Could not reach Ollama at {base} — "
                    f"is Ollama running? Try: ollama serve"
                )
            except RuntimeError:
                raise
            except Exception as e:
                last_exc = e

        raise RuntimeError(f"Ollama embedding failed after 4 attempts: {last_exc}")

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed multiple texts via /api/embed (batch endpoint).

        Sends texts in batches of BATCH_SIZE for efficient processing.
        Ollama loads the model once per batch, amortizing the startup cost
        across all texts in the batch — much faster than one-at-a-time.
        """
        import logging
        import time

        import httpx

        if not texts:
            return []

        base = self._base_url("http://localhost:11434")
        url = f"{base}/api/embed"
        log = logging.getLogger("keppi.embed")

        # Pre-load the model with num_ctx=8192 so /api/embed batches reuse it.
        # Some Ollama builds ignore options in /api/embed but respect the
        # context of an already-loaded model.
        self._ensure_model_loaded(base, log)

        results: list[list[float]] = [None] * len(texts)  # type: ignore
        batch_size = self.BATCH_SIZE

        for batch_start in range(0, len(texts), batch_size):
            batch = texts[batch_start:batch_start + batch_size]
            batch_indices = list(range(batch_start, batch_start + len(batch)))

            last_exc: Exception | None = None
            for attempt in range(4):
                if attempt:
                    time.sleep(min(2 ** attempt, 8))
                try:
                    resp = httpx.post(
                        url,
                        json={
                            "model": self.config.embed.model,
                            "input": batch,
                            "options": {"num_ctx": 8192},
                        },
                        timeout=max(120.0, len(batch) * 15.0),
                    )

                    if resp.status_code == 400:
                        body = resp.text
                        if "context" in body or "input length" in body:
                            # Input exceeds the model's context window.
                            # /api/embed doesn't always honor options before this
                            # check; fall back to /api/embeddings which does.
                            log.debug(
                                "Batch context-length 400 (batch %d-%d), "
                                "falling back to individual embeds: %s",
                                batch_start, batch_start + len(batch) - 1, body[:200],
                            )
                            for i, text in zip(batch_indices, batch):
                                try:
                                    results[i] = self.embed(text)
                                except ContextLengthError:
                                    results[i] = None
                            break
                        last_exc = RuntimeError(f"Ollama batch 400: {body[:120]}")
                        continue

                    if resp.status_code == 500:
                        body = resp.text
                        log.debug(
                            "Ollama batch 500 (attempt %d/4, batch %d-%d): %s",
                            attempt + 1, batch_start, batch_start + len(batch) - 1,
                            body[:120],
                        )
                        if "context length" in body:
                            # One chunk is too long — fall back to individual
                            log.debug("Context length error in batch, falling back to individual embeds")
                            for i, text in zip(batch_indices, batch):
                                try:
                                    results[i] = self.embed(text)
                                except ContextLengthError:
                                    results[i] = None  # Will be handled by bisection
                                    log.debug("Context length error for chunk %d", i)
                            break  # Don't retry batch, already handled individually
                        last_exc = RuntimeError(f"Ollama batch 500: {body[:120]}")
                        continue
                    resp.raise_for_status()
                    data = resp.json()
                    embeddings = data.get("embeddings", [])
                    if len(embeddings) != len(batch):
                        # Ollama returned fewer embeddings than inputs — fall back
                        log.warning(
                            "Ollama batch returned %d embeddings for %d inputs, falling back",
                            len(embeddings), len(batch),
                        )
                        for i, text in zip(batch_indices, batch):
                            try:
                                results[i] = self.embed(text)
                            except Exception:
                                results[i] = None
                        break
                    for i, emb in zip(batch_indices, embeddings):
                        results[i] = emb
                    break  # Success, move to next batch
                except httpx.ConnectError:
                    raise RuntimeError(
                        f"Could not reach Ollama at {base} — "
                        f"is Ollama running? Try: ollama serve"
                    )
                except RuntimeError:
                    raise
                except Exception as e:
                    last_exc = e
            else:
                # All retries exhausted for this batch
                log.error(
                    "Ollama batch embed failed after 4 attempts for batch %d-%d: %s",
                    batch_start, batch_start + len(batch) - 1, last_exc,
                )
                # Fall back to individual embeds for this batch
                for i, text in zip(batch_indices, batch):
                    try:
                        results[i] = self.embed(text)
                    except Exception:
                        results[i] = None

        # Replace any None results with empty list (will be handled by caller)
        return [r if r is not None else [] for r in results]


class OpenAIProvider(EmbedProvider):
    """OpenAI Embeddings API."""

    # OpenAI supports batch embedding natively via the input array
    BATCH_SIZE = 64  # OpenAI handles larger batches efficiently

    def embed(self, text: str) -> list[float]:
        """Embed a single text via OpenAI API."""
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

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed multiple texts via OpenAI batch API."""
        import httpx

        if not texts:
            return []

        base = self._base_url("https://api.openai.com")
        url = f"{base}/v1/embeddings"
        key = self._api_key()

        results: list[list[float]] = [None] * len(texts)  # type: ignore
        batch_size = self.BATCH_SIZE

        for batch_start in range(0, len(texts), batch_size):
            batch = texts[batch_start:batch_start + batch_size]
            batch_indices = list(range(batch_start, batch_start + len(batch)))

            try:
                resp = httpx.post(
                    url,
                    headers={"Authorization": f"Bearer {key}"},
                    json={"model": self.config.embed.model, "input": batch},
                    timeout=120.0,
                )
                resp.raise_for_status()
                data = resp.json()["data"]
                # OpenAI returns results sorted by index
                for item in data:
                    idx = item["index"]
                    results[batch_indices[idx]] = item["embedding"]
            except EnvironmentError:
                raise
            except Exception as e:
                raise RuntimeError(
                    f"OpenAI batch embedding failed: {e} — "
                    f"check your {self.config.embed.api_key_env} env var"
                )

        return [r if r is not None else [] for r in results]
