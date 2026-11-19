"""Map file paths to highlight.js languages and recognise generated files."""
import os
import re

GENERATED_PATTERNS = [
    r"(^|/)package-lock\.json$", r"(^|/)yarn\.lock$", r"(^|/)pnpm-lock\.yaml$",
    r"(^|/)Gemfile\.lock$", r"(^|/)Cargo\.lock$", r"(^|/)poetry\.lock$",
    r"(^|/)composer\.lock$", r"(^|/)go\.sum$", r"(^|/)Pipfile\.lock$",
    r"(^|/)uv\.lock$", r"(^|/)bun\.lockb?$", r"(^|/)mix\.lock$", r"(^|/)Podfile\.lock$",
    r"\.min\.(js|css)$", r"\.map$", r"(^|/)dist/", r"(^|/)build/", r"(^|/)vendor/",
    r"(^|/)node_modules/", r"\.snap$", r"\.pb\.go$", r"_pb2\.py$", r"\.generated\.",
    r"(^|/)db/schema\.rb$", r"(^|/)structure\.sql$",
]

LANG_BY_EXT = {
    "py": "python", "rb": "ruby", "rake": "ruby", "js": "javascript", "mjs": "javascript",
    "cjs": "javascript", "jsx": "javascript", "ts": "typescript", "tsx": "typescript",
    "vue": "xml", "svelte": "xml", "html": "xml", "htm": "xml", "xml": "xml", "erb": "erb",
    "css": "css", "scss": "scss", "sass": "scss", "less": "less", "go": "go", "rs": "rust",
    "java": "java", "kt": "kotlin", "kts": "kotlin", "scala": "scala", "swift": "swift",
    "m": "objectivec", "mm": "objectivec", "c": "c", "h": "c", "cc": "cpp", "cpp": "cpp",
    "cxx": "cpp", "hpp": "cpp", "cs": "csharp", "fs": "fsharp", "php": "php", "pl": "perl",
    "sh": "bash", "bash": "bash", "zsh": "bash", "ps1": "powershell", "sql": "sql",
    "json": "json", "yml": "yaml", "yaml": "yaml", "toml": "ini", "ini": "ini", "md": "markdown",
    "dart": "dart", "ex": "elixir", "exs": "elixir", "erl": "erlang", "hs": "haskell",
    "clj": "clojure", "lua": "lua", "r": "r", "jl": "julia", "tf": "hcl", "hcl": "hcl",
    "graphql": "graphql", "gql": "graphql", "proto": "protobuf", "gradle": "gradle",
    "groovy": "groovy", "dockerfile": "dockerfile", "makefile": "makefile", "cmake": "cmake",
}

_SPECIAL_NAMES = {"dockerfile": "dockerfile", "makefile": "makefile", "gemfile": "ruby", "rakefile": "ruby"}


def language_for(path):
    base = os.path.basename(path or "").lower()
    if base in _SPECIAL_NAMES:
        return _SPECIAL_NAMES[base]
    ext = base.rsplit(".", 1)[-1] if "." in base else ""
    return LANG_BY_EXT.get(ext, "")


def is_generated(path):
    return any(re.search(p, path or "") for p in GENERATED_PATTERNS)
