"""Sphinx integration for the WebMCP ModelContext API."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from docutils import nodes
from sphinx.application import Sphinx


DEFAULT_CONFIG: dict[str, Any] = {
    "manifest": "webmcp.json",
    "exposed_to": [],
    "search": {
        "native": True,
        "mode": "native",
        "docindex": {
            "index": "all",
            "oxirs": {"enabled": False, "url": ""},
            "meilisearch": {"enabled": False, "url": "", "public_api_key": ""},
        },
    },
    "tools": {
        "page_context": True,
        "navigation": True,
        "metadata": True,
        "search": True,
        "navigate": True,
    },
}


def _merge_dicts(base: dict[str, Any], override: object) -> dict[str, Any]:
    result = dict(base)
    if not isinstance(override, dict):
        return result
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _merge_dicts(result[key], value)
        else:
            result[key] = value
    return result


def normalize_config(config: object) -> dict[str, Any]:
    return _merge_dicts(DEFAULT_CONFIG, config)


def _title(doctree: nodes.document, fallback: str) -> str:
    title = doctree.next_node(nodes.title)
    return title.astext() if title is not None else fallback


def _doctree_summary(doctree: nodes.document) -> dict[str, Any]:
    headings = []
    for section in doctree.findall(nodes.section):
        title = section.next_node(nodes.title)
        if title is None:
            continue
        level = 1
        parent = section.parent
        while parent is not None:
            if isinstance(parent, nodes.section):
                level += 1
            parent = parent.parent
        headings.append(
            {
                "title": title.astext(),
                "ids": list(section.get("ids", [])),
                "level": level,
            }
        )
    return {"headings": headings}


def _public_search_config(config: dict[str, Any]) -> dict[str, Any]:
    search = config.get("search", {})
    docindex = search.get("docindex", {}) if isinstance(search, dict) else {}
    result: dict[str, Any] = {
        "native": {
            "enabled": bool(search.get("native", True))
            if isinstance(search, dict)
            else True
        },
        "mode": search.get("mode", "native") if isinstance(search, dict) else "native",
        "docindex": {
            "enabled": bool(docindex.get("enabled", False)),
            "index": docindex.get("index", "all"),
        },
    }
    for backend_name in ("oxirs", "meilisearch"):
        backend = docindex.get(backend_name, {})
        if not isinstance(backend, dict):
            backend = {}
        public_backend = {
            key: backend[key]
            for key in (
                "enabled",
                "url",
                "query_url",
                "search_url",
                "index",
                "graph",
                "limit",
                "public_api_key",
            )
            if key in backend
        }
        public_backend.setdefault("enabled", False)
        public_backend.setdefault("url", "")
        result["docindex"][backend_name] = public_backend
    return result


def _page_record(app: Sphinx, docname: str) -> dict[str, Any]:
    doctree = app.env.get_doctree(docname)
    source = str(app.env.doc2path(docname, base=False))
    return {
        "docname": docname,
        "title": _title(doctree, docname),
        "url": app.builder.get_target_uri(docname),
        "source": source,
        "doctree": _doctree_summary(doctree),
        "children": sorted(app.env.toctree_includes.get(docname, [])),
    }


def _build_manifest(app: Sphinx) -> dict[str, Any]:
    config = normalize_config(app.config.docindex_webmcp)
    pages = [_page_record(app, docname) for docname in sorted(app.env.found_docs)]
    return {
        "schema_version": 1,
        "builder": app.builder.name,
        "project": app.config.project,
        "version": app.config.version,
        "search": _public_search_config(config),
        "webmcp": {
            "exposed_to": config.get("exposed_to", []),
            "tools": config.get("tools", {}),
        },
        "pages": pages,
        "navigation": {
            "root": app.config.master_doc,
            "children": sorted(app.env.toctree_includes.get(app.config.master_doc, [])),
        },
        "artifacts": {
            "search_page": app.builder.get_target_uri("search"),
            "search_index": getattr(app.builder, "searchindex_filename", "searchindex.js"),
            "doctree_schema": {
                "headings": "list[{title, ids, level}]",
                "source": "relative source path",
            },
        },
    }


def _write_manifest(app: Sphinx, exception: Exception | None) -> None:
    if exception is not None or app.builder.name != "html":
        return
    config = normalize_config(app.config.docindex_webmcp)
    output = Path(app.outdir) / config["manifest"]
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f"{output.name}.tmp")
    temporary.write_text(json.dumps(_build_manifest(app), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(output)


def _register_assets(app: Sphinx) -> None:
    if app.config.docindex_webmcp_enabled and app.builder.name == "html":
        app.add_static_dir(Path(__file__).parent / "static")
        app.add_js_file("webmcp.js", loading_method="defer")


def setup(app: Sphinx) -> dict[str, Any]:
    app.add_config_value("docindex_webmcp_enabled", False, "html", types=frozenset({bool}))
    app.add_config_value("docindex_webmcp", DEFAULT_CONFIG, "html", types=frozenset({dict}))
    app.connect("builder-inited", _register_assets)
    app.connect("build-finished", _write_manifest)
    return {
        "version": "0.1.0",
        "parallel_read_safe": True,
        "parallel_write_safe": True,
    }
