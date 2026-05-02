"""Config parser for keppi.toml with sensible defaults (zero-config mode)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Union

try:
    import toml
except ImportError:
    toml = None  # type: ignore[assignment]


@dataclass
class VaultConfig:
    path: str = "."
    file_extensions: list[str] = field(default_factory=lambda: [".md"])
    exclude_dirs: list[str] = field(default_factory=lambda: [".obsidian", ".git", "templates", ".trash"])
    exclude_patterns: list[str] = field(default_factory=lambda: ["*.excalidraw.md"])


@dataclass
class FrontmatterConfig:
    type_field: Union[str, bool] = "type"
    subtype_field: Union[str, bool] = "subtype"
    status_field: Union[str, bool] = "status"
    updated_field: Union[str, bool] = "updated"
    tags_field: Union[str, bool] = "tags"
    aliases_field: Union[str, bool] = "aliases"
    related_field: Union[str, bool] = "related_to"
    sources_field: Union[str, bool] = "sources"
    url_field: Union[str, bool] = "url"


@dataclass
class LinksConfig:
    resolve_strategy: str = "title"
    case_sensitive: bool = False


@dataclass
class TagsConfig:
    inline_tags: bool = True
    frontmatter_tags: bool = True
    nested_separator: str = "/"


@dataclass
class GraphConfig:
    wikilink_weight: float = 1.0
    embed_weight: float = 1.5
    related_to_weight: float = 2.0
    tag_overlap_weight: float = 0.5
    folder_proximity_weight: float = 0.3
    community_algorithm: str = "louvain"
    min_community_size: int = 3
    default_depth: int = 2
    relevance_threshold: float = 0.3


@dataclass
class StorageConfig:
    graph_db: str = "~/.keppi/graphs/{vault_hash}.db"
    content_cache: bool = True
    cache_max_age_days: int = 30


@dataclass
class WatchConfig:
    enabled: bool = True
    debounce_ms: int = 2000
    ignore_patterns: list[str] = field(default_factory=lambda: [".obsidian/*"])


@dataclass
class EmbedConfig:
    provider: str = "ollama"
    # Supported in Phase 1: ollama | openai
    model: str = "nomic-embed-text"
    dimension: int = 768
    # Dimensions:
    #   ollama nomic-embed-text       → 768
    #   openai text-embedding-3-small → 1536
    #   openai text-embedding-3-large → 3072
    api_key_env: str = ""
    # Name of env var holding the API key (e.g. "OPENAI_API_KEY")
    # Leave empty for Ollama (no key needed)
    base_url: str = ""
    # Override default endpoint. Defaults:
    #   ollama → http://localhost:11434
    #   openai → https://api.openai.com
    auto_embed: bool = True
    # If True, keppi build and the file watcher automatically embed new/changed notes


@dataclass
class Config:
    vault: VaultConfig = field(default_factory=VaultConfig)
    frontmatter: FrontmatterConfig = field(default_factory=FrontmatterConfig)
    links: LinksConfig = field(default_factory=LinksConfig)
    tags: TagsConfig = field(default_factory=TagsConfig)
    graph: GraphConfig = field(default_factory=GraphConfig)
    storage: StorageConfig = field(default_factory=StorageConfig)
    watch: WatchConfig = field(default_factory=WatchConfig)
    embed: EmbedConfig = field(default_factory=EmbedConfig)
    config_path: Path | None = None

    def vault_root(self) -> Path:
        """Resolve vault path relative to config file or cwd."""
        vault_path = Path(self.vault.path)
        if not vault_path.is_absolute() and self.config_path:
            vault_path = self.config_path.parent / vault_path
        return vault_path.resolve()

    def db_path(self, vault_hash: str) -> Path:
        """Resolve the SQLite DB path."""
        template = self.storage.graph_db
        resolved = template.replace("{vault_hash}", vault_hash)
        return Path(os.path.expanduser(resolved))


def load_config(start_dir: Path | None = None) -> Config:
    """Load keppi.toml from start_dir or cwd, returning defaults if not found."""
    search_dir = start_dir or Path.cwd()
    config_file = _find_config(search_dir)

    if config_file is None:
        return Config()

    return _parse_config_file(config_file)


def _find_config(start: Path) -> Path | None:
    # Search order: (1) ~/.keppi/keppi.toml (canonical), (2) walk up from start (legacy vault-root fallback).
    home_config = Path.home() / ".keppi" / "keppi.toml"
    if home_config.exists():
        return home_config

    current = start.resolve()
    for _ in range(10):
        candidate = current / "keppi.toml"
        if candidate.exists():
            return candidate
        parent = current.parent
        if parent == current:
            break
        current = parent
    return None


def _parse_config_file(path: Path) -> Config:
    if toml is None:
        raise ImportError("toml package required — run: uv add toml")

    raw = toml.loads(path.read_text(encoding="utf-8"))
    config = Config(config_path=path)

    if "vault" in raw:
        v = raw["vault"]
        config.vault.path = v.get("path", config.vault.path)
        config.vault.file_extensions = v.get("file_extensions", config.vault.file_extensions)
        config.vault.exclude_dirs = v.get("exclude_dirs", config.vault.exclude_dirs)
        config.vault.exclude_patterns = v.get("exclude_patterns", config.vault.exclude_patterns)

    if "frontmatter" in raw:
        fm = raw["frontmatter"]
        for attr in vars(config.frontmatter):
            if attr in fm:
                setattr(config.frontmatter, attr, fm[attr])

    if "links" in raw:
        lk = raw["links"]
        config.links.resolve_strategy = lk.get("resolve_strategy", config.links.resolve_strategy)
        config.links.case_sensitive = lk.get("case_sensitive", config.links.case_sensitive)

    if "tags" in raw:
        tg = raw["tags"]
        config.tags.inline_tags = tg.get("inline_tags", config.tags.inline_tags)
        config.tags.frontmatter_tags = tg.get("frontmatter_tags", config.tags.frontmatter_tags)
        config.tags.nested_separator = tg.get("nested_separator", config.tags.nested_separator)

    if "graph" in raw:
        gr = raw["graph"]
        for attr in vars(config.graph):
            if attr in gr:
                setattr(config.graph, attr, gr[attr])

    if "storage" in raw:
        st = raw["storage"]
        config.storage.graph_db = st.get("graph_db", config.storage.graph_db)
        config.storage.content_cache = st.get("content_cache", config.storage.content_cache)
        config.storage.cache_max_age_days = st.get("cache_max_age_days", config.storage.cache_max_age_days)

    if "watch" in raw:
        wt = raw["watch"]
        config.watch.enabled = wt.get("enabled", config.watch.enabled)
        config.watch.debounce_ms = wt.get("debounce_ms", config.watch.debounce_ms)
        config.watch.ignore_patterns = wt.get("ignore_patterns", config.watch.ignore_patterns)

    if "embed" in raw:
        em = raw["embed"]
        config.embed.provider = em.get("provider", config.embed.provider)
        config.embed.model = em.get("model", config.embed.model)
        config.embed.dimension = em.get("dimension", config.embed.dimension)
        config.embed.api_key_env = em.get("api_key_env", config.embed.api_key_env)
        config.embed.base_url = em.get("base_url", config.embed.base_url)
        config.embed.auto_embed = em.get("auto_embed", config.embed.auto_embed)

    return config


DEFAULT_CONFIG_TOML = """\
# keppi.toml — Knowledge Graph Context Engine configuration

[vault]
path = "."
file_extensions = [".md"]
exclude_dirs = [".obsidian", ".git", "templates", ".trash"]
exclude_patterns = ["*.excalidraw.md"]

[frontmatter]
type_field = "type"
subtype_field = "subtype"
status_field = "status"
updated_field = "updated"
tags_field = "tags"
aliases_field = "aliases"
related_field = "related_to"
sources_field = "sources"
url_field = "url"

[links]
resolve_strategy = "title"
case_sensitive = false

[tags]
inline_tags = true
frontmatter_tags = true
nested_separator = "/"

[graph]
wikilink_weight = 1.0
embed_weight = 1.5
related_to_weight = 2.0
tag_overlap_weight = 0.5
folder_proximity_weight = 0.3
default_depth = 2
relevance_threshold = 0.3

[storage]
graph_db = "~/.keppi/graphs/{vault_hash}.db"
content_cache = true
cache_max_age_days = 30

[watch]
enabled = true
debounce_ms = 2000
ignore_patterns = [".obsidian/*"]
"""
