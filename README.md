# sphinxcontrib-webmcp

A theme-independent Sphinx extension that exposes documentation navigation,
page context, native search references, and optional DocIndex search through
the WebMCP `document.modelContext` API.

Enable it in `conf.py`:

```python
extensions = ["sphinxcontrib.webmcp"]
docindex_webmcp_enabled = True
docindex_webmcp = {
    "exposed_to": [],
    "search": {
        "native": True,
        "docindex": {
            "index": "all",
            "oxirs": {"url": "https://search.example/query"},
            "meilisearch": {
                "url": "https://search.example",
                "public_api_key": "",
            },
        },
    },
}
```

The extension adds one static JavaScript file to every HTML page and emits
`webmcp.json` in the HTML output directory. The JSON artifact contains a
stable page/navigation manifest and a compact, JSON-serializable doctree
summary. The manifest's `artifacts.doctree_schema` documents the summary shape
for agents that need structured page context. It does not expose server-side
credentials or raw Sphinx pickle files.

The registered read-only tools are `sphinx.get_page_context`,
`sphinx.list_navigation`, `sphinx.get_documentation_metadata`, and
`sphinx.search`. `sphinx.navigate` is a same-origin navigation tool and is
therefore not marked read-only. Search supports `native`, `docindex`, `oxirs`,
and `meilisearch` modes; native search navigates to Sphinx's generated search
page, while DocIndex modes query their configured public endpoints.

WebMCP is an optional browser API. Sites continue to work normally when
`document.modelContext` is unavailable, the page is not a secure context, or
the `tools` permissions policy is disabled.
