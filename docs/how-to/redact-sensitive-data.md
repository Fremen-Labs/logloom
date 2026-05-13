# How to Redact Sensitive Data

When scanning a large enterprise codebase, developers sometimes hardcode log messages that shouldn't be exposed globally or indexed into Elasticsearch. LogLoom provides a build-time redaction engine to aggressively sanitize your knowledge graph.

## The `--redact-patterns` Flag

You can pass a comma-separated list of sensitive keywords to the `logloom build` CLI. If the AST scanner detects any of these keywords in a log message template, the entire template is replaced with `[REDACTED]`.

### Example

Imagine the following code:
```python
logger.info("Setting admin password to hunter2")
logger.debug("Stripe secret key loaded")
```

Run the build command with the redaction flag:

```bash
logloom build --source src/ --redact-patterns "password,secret"
```

### Resulting Graph

When you inspect `logloom-graph.json`, the sensitive content never makes it to disk:

```json
{
  "nodes": {
    "ll:3d9b8a1c22f0": {
      "message_template": "[REDACTED]",
      "level": "info",
      "function": "<module>"
    },
    "ll:f8b2a3c1e4d9": {
      "message_template": "[REDACTED]",
      "level": "debug",
      "function": "<module>"
    }
  }
}
```

### Important Notes
*   **Build-Time Only**: This redaction only applies to the static `logloom-graph.json` knowledge graph. It prevents sensitive string structures from being mapped in the global registry.
*   **Runtime Logging**: This feature does **not** mask runtime variables. For runtime masking, you should utilize standard `structlog` processors or Elasticsearch ingest pipelines.
