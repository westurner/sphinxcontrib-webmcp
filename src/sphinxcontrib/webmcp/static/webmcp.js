"use strict";

(function () {
  if (!document.modelContext || typeof document.modelContext.registerTool !== "function") {
    return;
  }

  function manifestURL() {
    var contentRoot = document.documentElement.getAttribute("data-content_root");
    if (contentRoot) {
      return new URL(contentRoot + "webmcp.json", document.baseURI);
    }
    var scripts = Array.from(document.scripts);
    var script = scripts.find(function (item) {
      return /(?:^|\/)webmcp\.js(?:[?#]|$)/.test(item.src);
    });
    if (script) {
      var scriptURL = new URL(script.src, document.baseURI);
      var staticMarker = scriptURL.pathname.lastIndexOf("/_static/");
      if (staticMarker >= 0) {
        return new URL(
          scriptURL.pathname.slice(0, staticMarker + 1) + "webmcp.json",
          scriptURL.origin
        );
      }
    }
    return new URL("webmcp.json", document.baseURI);
  }

  function currentPath() {
    return window.location.href.split("#", 1)[0];
  }

  function findPage(manifest, requestedPath) {
    var path = requestedPath;
    return (manifest.pages || []).find(function (page) {
      if (path) {
        return page.url === path || page.docname === path.replace(/\.html$/, "");
      }
      return new URL(page.url, document.baseURI).href === currentPath();
    }) || null;
  }

  function absoluteURL(path) {
    return new URL(path, document.baseURI);
  }

  function searchMeilisearch(config, query, index) {
    var base = (config.url || "").replace(/\/$/, "");
    var endpoint = config.search_url || base + "/indexes/" +
      encodeURIComponent(config.index || index || "all") + "/search";
    var headers = {"Content-Type": "application/json"};
    if (config.public_api_key) {
      headers.Authorization = "Bearer " + config.public_api_key;
    }
    return fetch(endpoint, {
      method: "POST",
      headers: headers,
      body: JSON.stringify({q: query, limit: config.limit || 20})
    }).then(function (response) {
      if (!response.ok) throw new Error("Meilisearch returned " + response.status);
      return response.json();
    });
  }

  function searchOxirs(config, query, index) {
    var terms = query.trim().split(/\s+/).filter(Boolean).map(function (term) {
      var escaped = term.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
      return '(regex(str(?content), ' + JSON.stringify(escaped) + ', "i") || ' +
        'regex(str(?title), ' + JSON.stringify(escaped) + ', "i"))';
    });
    var graph = config.graph || config.index || index || "all";
    var namespace = "http://westurner.github.io/sustainablefactory/docindex/#";
    var queryText = "PREFIX docindex: <" + namespace + ">\n" +
      "SELECT ?id ?type ?title ?url ?sourceUri ?content ?filename WHERE { GRAPH <" +
      "http://westurner.github.io/sustainablefactory/docindex/graph/" + graph +
      "> { ?subject docindex:id ?id ; docindex:type ?type ; docindex:title ?title ; " +
      "docindex:content ?content ; docindex:filename ?filename . " +
      "OPTIONAL { ?subject docindex:url ?url } OPTIONAL { ?subject docindex:sourceUri ?sourceUri } " +
      (terms.length ? "FILTER (" + terms.join(" && ") + ") " : "") +
      "} } LIMIT " + (config.limit || 20);
    return fetch(config.query_url || config.url, {
      method: "POST",
      headers: {
        "Content-Type": "application/x-www-form-urlencoded",
        Accept: "application/sparql-results+json"
      },
      body: new URLSearchParams({query: queryText})
    }).then(function (response) {
      if (!response.ok) throw new Error("OxiRS returned " + response.status);
      return response.json();
    });
  }

  function extractResults(payload) {
    if (Array.isArray(payload)) return payload;
    if (payload && Array.isArray(payload.hits)) return payload.hits;
    if (payload && payload.results && Array.isArray(payload.results.bindings)) {
      return payload.results.bindings.map(function (binding) {
        return Object.keys(binding).reduce(function (result, key) {
          result[key] = binding[key] && binding[key].value;
          return result;
        }, {});
      });
    }
    return [];
  }

  function configuredBackends(manifest) {
    var docindex = (manifest.search || {}).docindex || {};
    return ["oxirs", "meilisearch"].filter(function (name) {
      return docindex[name] && docindex[name].enabled && docindex[name].url;
    });
  }

  function search(manifest, query, mode) {
    var searchConfig = manifest.search || {};
    mode = mode || searchConfig.mode || "native";
    if (mode === "auto") {
      mode = searchConfig.docindex && searchConfig.docindex.enabled ? "docindex" : "native";
    }
    if (mode === "native") {
      var nativePage = absoluteURL(manifest.artifacts.search_page || "search.html");
      nativePage.searchParams.set("q", query);
      window.location.assign(nativePage.href);
      return Promise.resolve({mode: "native", query: query, url: nativePage.href});
    }

    var docindex = searchConfig.docindex || {};
    if (!docindex.enabled) {
      return Promise.resolve({mode: "docindex", query: query, results: [], disabled: true});
    }
    var names = mode === "docindex" ? configuredBackends(manifest) : [mode];
    return Promise.all(names.map(function (name) {
      var config = docindex[name];
      if (!config || !config.enabled || !config.url) {
        return {backend: name, results: [], disabled: true};
      }
      var request = name === "oxirs"
        ? searchOxirs(config, query, docindex.index)
        : searchMeilisearch(config, query, docindex.index);
      return request.then(function (payload) {
        return {backend: name, results: extractResults(payload)};
      });
    })).then(function (results) {
      return {mode: mode || "docindex", query: query, results: results};
    });
  }

  function register(manifest) {
    var exposedTo = Array.isArray((manifest.webmcp || {}).exposed_to)
      ? (manifest.webmcp || {}).exposed_to : [];
    var options = exposedTo.length ? {exposedTo: exposedTo} : undefined;
    var annotations = {readOnlyHint: true, untrustedContentHint: true};
    var enabledTools = (manifest.webmcp || {}).tools || {};
    var tools = [];
    function addTool(key, tool) {
      if (enabledTools[key] !== false) tools.push(tool);
    }

    addTool("page_context", {
      name: "sphinx.get_page_context",
      title: "Get documentation page context",
      description: "Return the current or requested Sphinx page title, URL, headings, source path, and navigation children.",
      inputSchema: {type: "object", properties: {path: {type: "string"}}},
      annotations: annotations,
      execute: function (input) {
        return Promise.resolve(findPage(manifest, input && input.path) || {
          found: false, path: input && input.path
        });
      }
    });

    addTool("navigation", {
      name: "sphinx.list_navigation",
      title: "List documentation navigation",
      description: "Return the Sphinx documentation root and its resolved navigation children.",
      inputSchema: {type: "object"},
      annotations: annotations,
      execute: function () { return Promise.resolve(manifest.navigation); }
    });

    addTool("metadata", {
      name: "sphinx.get_documentation_metadata",
      title: "Get documentation metadata",
      description: "Return public build, search, artifact, and doctree schema metadata for this Sphinx site.",
      inputSchema: {type: "object"},
      annotations: annotations,
      execute: function () {
        return Promise.resolve({
          schema_version: manifest.schema_version,
          project: manifest.project,
          version: manifest.version,
          builder: manifest.builder,
          search: manifest.search,
          artifacts: manifest.artifacts
        });
      }
    });

    addTool("search", {
      name: "sphinx.search",
      title: "Search documentation",
      description: "Search documentation using native Sphinx search or configured DocIndex OxiRS and Meilisearch backends.",
      inputSchema: {
        type: "object",
        properties: {
          query: {type: "string", minLength: 1},
          mode: {type: "string", enum: ["native", "docindex", "oxirs", "meilisearch"]}
        },
        required: ["query"]
      },
      annotations: annotations,
      execute: function (input) {
        if (!input || typeof input.query !== "string" || !input.query.trim()) {
          return Promise.reject(new TypeError("query must be a non-empty string"));
        }
        return search(manifest, input.query.trim(), input.mode || "native");
      }
    });

    addTool("navigate", {
      name: "sphinx.navigate",
      title: "Navigate documentation",
      description: "Navigate the current documentation tab to a same-origin Sphinx page.",
      inputSchema: {
        type: "object",
        properties: {path: {type: "string", minLength: 1}},
        required: ["path"]
      },
      execute: function (input) {
        var target = absoluteURL(input.path);
        if (target.origin !== window.location.origin) {
          return Promise.reject(new TypeError("navigation is restricted to this origin"));
        }
        window.location.assign(target.href);
        return Promise.resolve({url: target.href});
      }
    });

    return Promise.all(tools.map(function (tool) {
      return document.modelContext.registerTool(tool, options);
    }));
  }

  fetch(manifestURL(), {credentials: "same-origin"})
    .then(function (response) {
      if (!response.ok) throw new Error("WebMCP manifest returned " + response.status);
      return response.json();
    })
    .then(register)
    .catch(function (error) {
      console.warn("sphinxcontrib-webmcp could not register tools:", error);
    });
}());
