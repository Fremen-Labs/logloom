"""Issue #20 — Elasticsearch index template + mapping generator.

Generates ECS-compatible component and index templates that map LogLoom's
semantic fields (`logloom.node_id`, `logloom.tags`, etc.) into Elasticsearch.

Two output modes:
  1. JSON dict — suitable for `PUT _index_template` or `PUT _component_template`
  2. CLI command — ready-to-paste curl / Dev Tools body
"""

from __future__ import annotations

import json
from typing import Any, Dict, Optional

from ..graph.model import LogLoomGraph


# ── LogLoom ECS field mapping ─────────────────────────────────────────────────
# Follows Elastic Common Schema (ECS) conventions:
#   - Custom fields live under a custom namespace: "logloom.*"
#   - Keyword types for cardinality-friendly aggregation
#   - "text" sub-field only where full-text search is useful

LOGLOOM_FIELD_MAPPING: Dict[str, Any] = {
    "logloom": {
        "properties": {
            "node_id": {
                "type": "keyword",
                "ignore_above": 64,
            },
            "traversal": {
                "type": "keyword",
            },
            "module": {
                "type": "keyword",
            },
            "function": {
                "type": "keyword",
            },
            "file": {
                "type": "keyword",
            },
            "line": {
                "type": "integer",
            },
            "tags": {
                "type": "keyword",
            },
            "level": {
                "type": "keyword",
            },
            "message_template": {
                "type": "keyword",
                "fields": {
                    "text": {
                        "type": "text",
                        "analyzer": "standard",
                    }
                },
            },
            "call_parents": {
                "type": "keyword",
            },
            "call_children": {
                "type": "keyword",
            },
            "graph_version": {
                "type": "keyword",
            },
            "commit_sha": {
                "type": "keyword",
            },
            "branch": {
                "type": "keyword",
            },
        }
    }
}


def generate_component_template(
    template_name: str = "logloom",
    priority: int = 200,
) -> Dict[str, Any]:
    """Generate an Elasticsearch component template for LogLoom fields.

    This template can be composed into any index template via the
    ``composed_of`` array, making it easy to add LogLoom enrichment
    to existing pipelines without touching their core mappings.
    """
    return {
        "template": {
            "mappings": {
                "properties": LOGLOOM_FIELD_MAPPING,
            },
        },
        "version": 1,
        "_meta": {
            "description": "LogLoom semantic provenance fields (ECS-compatible)",
            "managed_by": "logloom",
        },
    }


def generate_index_template(
    template_name: str = "logloom-logs",
    index_patterns: list[str] | None = None,
    priority: int = 200,
    number_of_shards: int = 1,
    number_of_replicas: int = 1,
    ilm_policy: Optional[str] = None,
) -> Dict[str, Any]:
    """Generate a standalone index template with LogLoom mappings.

    Includes sensible defaults for a log-oriented data stream or index.
    """
    if index_patterns is None:
        index_patterns = ["logloom-*", "logs-logloom-*"]

    settings: Dict[str, Any] = {
        "number_of_shards": number_of_shards,
        "number_of_replicas": number_of_replicas,
    }
    if ilm_policy:
        settings["index.lifecycle.name"] = ilm_policy

    return {
        "index_patterns": index_patterns,
        "priority": priority,
        "template": {
            "settings": settings,
            "mappings": {
                "properties": {
                    # Standard ECS fields
                    "@timestamp": {"type": "date"},
                    "message": {"type": "text"},
                    "log.level": {"type": "keyword"},
                    "log.logger": {"type": "keyword"},
                    # LogLoom semantic namespace
                    **LOGLOOM_FIELD_MAPPING,
                },
            },
        },
        "version": 1,
        "_meta": {
            "description": f"LogLoom index template — {template_name}",
            "managed_by": "logloom",
        },
    }


def generate_enrichment_documents(
    graph: LogLoomGraph,
) -> list[Dict[str, Any]]:
    """Convert graph nodes into ES-ready enrichment documents.

    Each document is indexed by ``node_id`` and contains the full
    semantic context. These docs power runtime enrichment via
    enrich processors or Kibana lookup fields.
    """
    docs = []
    for node in graph.nodes.values():
        docs.append({
            "_id": node.node_id,
            "logloom": {
                "node_id": node.node_id,
                "module": node.module,
                "function": node.function,
                "file": node.file,
                "line": node.line,
                "level": node.level,
                "tags": node.semantic_tags,
                "message_template": node.message_template,
                "call_parents": node.call_parents,
                "call_children": node.call_children,
                "graph_version": graph.built_at,
                "commit_sha": graph.commit_sha,
                "branch": graph.branch,
            },
        })
    return docs


def render_mapping_json(template_type: str = "component", **kwargs) -> str:
    """Convenience: return the template as pretty-printed JSON."""
    if template_type == "component":
        return json.dumps(generate_component_template(**kwargs), indent=2)
    return json.dumps(generate_index_template(**kwargs), indent=2)
