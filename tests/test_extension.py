import json
from pathlib import Path
from types import SimpleNamespace

from docutils import nodes

from sphinxcontrib.webmcp.extension import (
    DEFAULT_CONFIG,
    _build_manifest,
    _doctree_summary,
    _public_search_config,
    _register_assets,
    _title,
    _write_manifest,
    normalize_config,
    setup,
)


STATIC_SCRIPT = (
    Path(__file__).parents[1]
    / "src"
    / "sphinxcontrib"
    / "webmcp"
    / "static"
    / "webmcp.js"
)


def _document_tree():
    document = nodes.document("", "")
    outer = nodes.section(ids=["outer"])
    outer += nodes.title("", "Outer")
    inner = nodes.section(ids=["inner"])
    inner += nodes.title("", "Inner")
    outer += inner
    document += outer
    return document


def test_normalize_config_merges_nested_values_without_mutating_defaults():
    config = normalize_config(
        {
            "search": {
                "docindex": {
                    "enabled": True,
                    "meilisearch": {"enabled": True, "url": "https://search.test"},
                }
            }
        }
    )

    assert config["search"]["native"] is True
    assert config["search"]["docindex"]["enabled"] is True
    assert config["search"]["docindex"]["meilisearch"]["url"] == "https://search.test"
    assert DEFAULT_CONFIG["search"]["docindex"].get("enabled") is None


def test_public_search_config_keeps_public_fields_and_drops_private_key():
    config = _public_search_config(
        {
            "search": {
                "native": False,
                "docindex": {
                    "enabled": True,
                    "index": "docs",
                    "meilisearch": {
                        "enabled": True,
                        "url": "https://search.test",
                        "api_key": "private",
                        "public_api_key": "public",
                    },
                },
            }
        }
    )

    assert config["native"]["enabled"] is False
    assert config["docindex"]["index"] == "docs"
    assert config["docindex"]["meilisearch"]["public_api_key"] == "public"
    assert "api_key" not in config["docindex"]["meilisearch"]


def test_doctree_summary_reports_nested_heading_levels_and_ids():
    summary = _doctree_summary(_document_tree())

    assert summary == {
        "headings": [
            {"title": "Outer", "ids": ["outer"], "level": 1},
            {"title": "Inner", "ids": ["inner"], "level": 2},
        ]
    }
    assert _title(_document_tree(), "fallback") == "Outer"
    assert _title(nodes.document("", ""), "fallback") == "fallback"


def test_build_manifest_contains_pages_navigation_and_public_search_config():
    tree = _document_tree()
    app = SimpleNamespace(
        env=SimpleNamespace(
            found_docs={"index"},
            toctree_includes={"index": ["guide"]},
            get_doctree=lambda docname: tree,
            doc2path=lambda docname, base=False: "index.md",
        ),
        builder=SimpleNamespace(
            name="html",
            get_target_uri=lambda docname: f"{docname}.html",
            searchindex_filename="searchindex.js",
        ),
        config=SimpleNamespace(
            docindex_webmcp={
                "search": {
                    "native": True,
                    "docindex": {
                        "enabled": True,
                        "meilisearch": {
                            "enabled": True,
                            "url": "https://search.test",
                            "api_key": "private",
                        },
                    },
                }
            },
            project="Example",
            version="1.0",
            master_doc="index",
        ),
    )

    manifest = _build_manifest(app)

    assert manifest["project"] == "Example"
    assert manifest["pages"][0]["source"] == "index.md"
    assert manifest["navigation"] == {"root": "index", "children": ["guide"]}
    assert manifest["artifacts"]["search_index"] == "searchindex.js"
    assert '"api_key"' not in json.dumps(manifest)


def test_write_manifest_is_atomic_and_skips_failed_build(tmp_path):
    output = tmp_path / "site"
    output.mkdir()
    app = SimpleNamespace(
        outdir=str(output),
        builder=SimpleNamespace(name="html"),
        config=SimpleNamespace(docindex_webmcp={"manifest": "webmcp.json"}),
    )

    original = __import__("sphinxcontrib.webmcp.extension", fromlist=["_build_manifest"])
    original_manifest_builder = original._build_manifest
    original._build_manifest = lambda current_app: {"schema_version": 1}
    try:
        _write_manifest(app, None)
        _write_manifest(app, RuntimeError("failed"))
    finally:
        original._build_manifest = original_manifest_builder

    manifest_path = output / "webmcp.json"
    assert json.loads(manifest_path.read_text(encoding="utf-8")) == {"schema_version": 1}
    assert not (output / "webmcp.json.tmp").exists()


def test_register_assets_only_for_enabled_html_builder():
    calls = []

    class App:
        def __init__(self, enabled, builder_name="html"):
            self.config = SimpleNamespace(docindex_webmcp_enabled=enabled)
            self.builder = SimpleNamespace(name=builder_name)

        def add_static_dir(self, path):
            calls.append(("static", path.name))

        def add_js_file(self, name, **kwargs):
            calls.append(("js", name, kwargs))

    _register_assets(App(True))
    _register_assets(App(False))
    _register_assets(App(True, "dummy"))

    assert calls == [("static", "static"), ("js", "webmcp.js", {"loading_method": "defer"})]


def test_setup_registers_configuration_and_events():
    config_values = {}
    events = []

    class App:
        def add_config_value(self, name, default, rebuild, types):
            config_values[name] = (default, rebuild, types)

        def connect(self, event, callback):
            events.append((event, callback.__name__))

    metadata = setup(App())

    assert config_values["docindex_webmcp_enabled"][2] == frozenset({bool})
    assert config_values["docindex_webmcp"][2] == frozenset({dict})
    assert {event for event, _ in events} == {"builder-inited", "build-finished"}
    assert metadata["parallel_read_safe"] is True


def test_webmcp_script_declares_tools_and_feature_detection():
    script = STATIC_SCRIPT.read_text(encoding="utf-8")

    assert "document.modelContext" in script
    for tool_name in (
        "sphinx.get_page_context",
        "sphinx.list_navigation",
        "sphinx.get_documentation_metadata",
        "sphinx.search",
        "sphinx.navigate",
    ):
        assert tool_name in script
