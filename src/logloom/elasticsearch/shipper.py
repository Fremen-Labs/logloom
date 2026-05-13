"""Issue #21 — Graph-to-ES shipper.

Ships the LogLoom graph as enrichment documents to an Elasticsearch cluster.
Supports two modes:
  1. Bulk indexing via the ``elasticsearch-py`` client (optional dependency)
  2. NDJSON export for offline ingestion via ``curl`` / ``_bulk`` API
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..graph.model import LogLoomGraph
from .mapping import generate_enrichment_documents, generate_index_template


def export_ndjson(
    graph: LogLoomGraph,
    index_name: str = "logloom-enrichment",
    output_path: Optional[Path] = None,
) -> str:
    """Export graph nodes as NDJSON suitable for the ``_bulk`` API.

    Returns the NDJSON string. If ``output_path`` is provided, also writes
    it to disk.

    Usage with curl::

        curl -s -XPOST "http://localhost:9200/_bulk" \\
             -H "Content-Type: application/x-ndjson" \\
             --data-binary @logloom-enrichment.ndjson
    """
    docs = generate_enrichment_documents(graph)
    lines: List[str] = []

    for doc in docs:
        action = {"index": {"_index": index_name, "_id": doc["_id"]}}
        body = doc.copy()
        body.pop("_id", None)
        lines.append(json.dumps(action))
        lines.append(json.dumps(body))

    # Bulk API requires a trailing newline
    ndjson = "\n".join(lines) + "\n"

    if output_path:
        output_path.write_text(ndjson, encoding="utf-8")

    return ndjson


def ship_to_elasticsearch(
    graph: LogLoomGraph,
    es_url: str = "http://localhost:9200",
    index_name: str = "logloom-enrichment",
    api_key: Optional[str] = None,
    username: Optional[str] = None,
    password: Optional[str] = None,
    verify_certs: bool = True,
    create_index: bool = True,
) -> Dict[str, Any]:
    """Ship graph enrichment documents to Elasticsearch via the official client.

    Requires ``elasticsearch>=8.0`` to be installed. Returns a summary dict
    with ``success_count``, ``error_count``, and any errors.

    Args:
        graph: The LogLoomGraph to ship.
        es_url: Elasticsearch base URL.
        index_name: Target index for enrichment documents.
        api_key: Elasticsearch API key (preferred over user/pass).
        username: Basic auth username.
        password: Basic auth password.
        verify_certs: Whether to verify TLS certificates.
        create_index: If True, create the index template before shipping.
    """
    try:
        from elasticsearch import Elasticsearch
        from elasticsearch.helpers import bulk
    except ImportError:
        raise ImportError(
            "The 'elasticsearch' package is required for direct shipping. "
            "Install it with: pip install 'logloom[elasticsearch]'\n"
            "Alternatively, use export_ndjson() for offline ingestion."
        )

    # Build client
    client_kwargs: Dict[str, Any] = {"hosts": [es_url], "verify_certs": verify_certs}
    if api_key:
        client_kwargs["api_key"] = api_key
    elif username and password:
        client_kwargs["basic_auth"] = (username, password)

    es = Elasticsearch(**client_kwargs)

    # Optionally create the index with the LogLoom template
    if create_index:
        template = generate_index_template(
            template_name=index_name,
            index_patterns=[f"{index_name}*"],
        )
        if not es.indices.exists(index=index_name):
            es.indices.create(
                index=index_name,
                body={
                    "settings": template["template"]["settings"],
                    "mappings": template["template"]["mappings"],
                },
            )

    # Prepare bulk actions
    docs = generate_enrichment_documents(graph)
    actions = []
    for doc in docs:
        actions.append({
            "_index": index_name,
            "_id": doc["_id"],
            "_source": {k: v for k, v in doc.items() if k != "_id"},
        })

    success, errors = bulk(es, actions, raise_on_error=False, stats_only=False)

    error_list = []
    if isinstance(errors, list):
        for err in errors:
            error_list.append(str(err))

    return {
        "success_count": success if isinstance(success, int) else len(actions),
        "error_count": len(error_list),
        "errors": error_list,
        "index": index_name,
        "total_docs": len(docs),
    }
