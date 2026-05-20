# LogLoom

```
      ____________________
     /                    \
    |     L O G L O O M    |
    |   Wooden Log Loom    |
     \____________________/
           ||   ||   ||
          /||\ /||\ /||\     ← Warp (Code)
         / ||  ||  ||  ||\
        ==================   ← Weft (Log)
             ll:abc123def
       "The Log becomes the Loom"
```

**Weave your codebase into every log line.**  
*Like a 90s BBS sysop who actually knew where the packets were dropping.*

Turn flat, human friendly logs into a **queryable execution graph** machines can understand, all with zero developer friction.  
Build-time AST magic meets runtime enlightenment — perfect for humans, agentic debuggers, and Elasticsearch wranglers alike.

## Why LogLoom? (The Real Talk)

Modern logs are like 90s AOL chat: humans can read them, but good luck getting an AI to understand the *intent* behind the code.  

LogLoom fixes that by:
- Scanning your source **at build time** across languages like Python, Go, TypeScript/JavaScript with no runtime tax
- Building a stable semantic knowledge graph
- Injecting tiny, permanent `ll:` node references into every log line
- Shipping directly to Elasticsearch and OpenTelemetry with native bridges
- Giving your observability stack instant causal superpowers

All while your human logs stay clean. No more "where the heck was this log called?" detective work at 3am.

## Quick Start (Dial-up Fast)

```bash
pip install logloom
```

```python
# 1. In CI / build pipeline (do this once per deploy)
logloom build --source .

# 2. In your code — works exactly like structlog or logging
from logloom import get_logger

logger = get_logger(__name__)

logger.info("User login failed", user_id=123, reason="token_expired")
```

That’s it. Your logs now carry the DNA of the code that wrote them.

## What Actually Happens Under the Hood

### Build Time (`logloom build`)
Creates `logloom-graph.json` — your app’s **living source map** (Schema Version `1.2`):

```json
{
  "schema_version": "1.2",
  "project": "my-auth-service",
  "nodes": {
    "ll:abc123def456": {
      "node_id": "ll:abc123def456",
      "file": "src/auth/service.py",
      "module": "app.auth.service",
      "function": "authenticate",
      "level": "error",
      "message_template": "User login failed",
      "line": 42,
      "semantic_tags": ["auth", "security"],
      "lexical_parents": ["try:refresh_token", "AuthService"],
      "call_parents": ["ll:d1e2f3g4"],
      "call_children": ["ll:h5i6j7k8"],
      "call_parent_names": ["refresh_session"],
      "call_child_names": ["verify_credentials"],
      "signature": {
        "parameters": [
          {"name": "username", "type_hint": "str", "default": null},
          {"name": "password", "type_hint": "str", "default": null}
        ],
        "return_type": "bool",
        "is_async": true,
        "decorators": ["rate_limited"]
      }
    }
  }
}
```

### Runtime Output (Enriched but Still Human-Friendly)

```json
{
  "event": "User login failed",
  "user_id": 123,
  "reason": "token_expired",
  "ll_node": "ll:abc123def456",
  "ll_module": "app.auth.service",
  "ll_function": "authenticate",
  "ll_tags": ["auth", "security"],
  "ll_call_parent_names": ["refresh_session"],
  "ll_call_child_names": ["verify_credentials"],
  "ll_signature": {
    "parameters": [
      {"name": "username", "type_hint": "str"},
      {"name": "password", "type_hint": "str"}
    ],
    "return_type": "bool",
    "is_async": true,
    "decorators": ["rate_limited"]
  }
}
```

Now your Elastic queries and AI agents can say things like:  
*"Show me every failure in the auth retry path in the last hour"*  
or *"Find all error logs inside async functions that accept a username"*  
and actually get meaningful answers.

## Core Features

- **Zero runtime overhead** when graph is missing (graceful fallback)
- **Stable node IDs** that survive refactors
- **Multi-language Scanners**: A nifty Tree-sitter AST parsing for Python (structlog, logging), Go (stdlib log, slog, zap, logrus, zerolog), and TypeScript/JavaScript (console, winston, pino, bunyan, NestJS Logger, log4js).
- **Native OpenTelemetry Bridge**: Plug-and-play like a Game Boy cartridge. Slap it in and your spans are magically annotated.
- **Elasticsearch Shipper & Mappings**: Auto-generates ECS-compliant component templates and ships your graph directly into Elasticsearch via `_bulk`.
- **GitHub Action Native**: Just `uses: fremenlabs/logloom@v0.3.0` in your CI pipeline.
- **Redaction support** (`--redact-patterns "password,token"`)
- Works great with structlog (and stdlib logging via wrapper)

## Installation

```bash
# For normal runtime use
pip install logloom

# For building graphs includes Tree-sitter binaries
pip install "logloom[build]"

# For Elastic and OTEL ecosystem power-ups
pip install "logloom[elasticsearch,otel]"
```

## Milestone 4: Deep Context & Quality Gates (v0.4.0)

- **Function Signatures**: Complete parsing of parameter names, type hints, defaults, and return type definitions of enclosing functions.
- **Data Model Extraction**: Extracts structured attributes, type definitions, defaults, and inheritance hierarchies for classes, structs, and interfaces (Python, Go, TypeScript).
- **Import Dependency Graph**: Scans module-to-module dependencies across Python, Go, and TypeScript with relative resolution and noise-filtering (only internal imports by default, customizable via `--external-imports`).
- **Quality Gates & CI Enforcements**: Fail CI/CD builds if log coverage falls below threshold using the `--min-coverage <percentage>` CLI option.
- **Log Coverage Metrics & Stats**: Added coverage percentage, instrumented functions count, and uninstrumented function lists to `logloom graph stats` output.

## Milestone 3: Ecosystem (v0.3.0)

We just dialed into the mainframe and dropped the Ecosystem update:

- **Production Go & TS Scanners**: Handles complex method chains, anonymous closures, try/catch blocks, and asynchronous flow control. 
- **`logloom es map`**: Generates massive, beautiful Elasticsearch index templates with our `logloom.*` ECS namespace.
- **`logloom es export`**: NDJSON shipper that blasts your graph into an Elasticsearch enrichment index.
- **OTEL Log Processor**: `LogLoomProcessor` intercepts standard OpenTelemetry LogRecords and injects semantic tags and graph provenance before export.
- **GitHub Action**: Ready for your CI/CD pipelines right out of the box.

## Milestone 2: Intelligence (v0.2.0)

- **Semantic tag inference** — auto-detects `auth`, `error`, `db`, etc.
- **Inter-function call-graph** — tracks caller/callee relationships
- **`logloom graph stats`** — quick insights into your graph:

```text
╭───────────────────────────────╮
│ logloom-project  •  schema v1 │
╰── Built 2026-05-13T16:01:30 ──╯
          Graph Overview           
┌──────────────────┬──────────────┐
│ Log sites        │           16 │
│ Functions        │            6 │
│ Call-graph edges │           23 │
│ Commit           │ bba435c380b4 │
└──────────────────┴──────────────┘
```

- **`logloom graph show`** — explore the graph as a rich tree
- **`logloom graph find`** — search for a node by message or location
- **`logloom lint`** — catches untracked log sites
- **`logloom diff`** — detect graph regressions in CI

Run `logloom --help` to explore!

## Next Level Stuff

- [Architecture Guide](docs/architecture.md): The full technical deep dive
- [Elastic Integrations](docs/how-to/elastic-integrations.md): How to use LogLoom with Filebeat, Elastic Agent, Logstash, and OpenTelemetry
- [Roadmap](https://github.com/Fremen-Labs/logloom/issues): See what’s coming next

---

**License**  
MIT — because sharing is caring, even in the 90s.

---
