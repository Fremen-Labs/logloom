# Graph Schema Reference

The knowledge graph produced by `logloom build` adheres to a strict JSON schema that maps the static semantic context of your codebase.

## Root Object

| Field | Type | Description |
| :--- | :--- | :--- |
| `schema_version` | String | The version of the LogLoom schema (currently `"1"`). |
| `project` | String | The name of the project configured in `.logloomrc.toml`. |
| `built_at` | String (ISO 8601) | The UTC timestamp when the graph was generated. |
| `commit_sha` | String (Optional) | The Git commit hash at the time of the build. |
| `redacted_patterns` | Array of Strings | List of redaction patterns applied during the build. |
| `nodes` | Object | A map where the keys are the `ll:` node IDs and the values are `GraphNode` objects. |

## GraphNode Object

| Field | Type | Description |
| :--- | :--- | :--- |
| `node_id` | String | The deterministic `ll:` identifier. |
| `file` | String | The relative file path to the log statement. |
| `module` | String | The Python module path (e.g., `app.services.auth`). |
| `function` | String | The innermost enclosing function name (or `<module>`). |
| `level` | String | The logging severity level (e.g., `info`, `error`). |
| `message_template` | String | The extracted template string (with `f-string` interpolations replaced by `{}`). |
| `line` | Integer | The 1-indexed line number in the source file. |
| `semantic_tags` | Array of Strings | Inferred tags based on context (e.g., `["error"]`). |
| `lexical_parents` | Array of Strings | The structural scopes containing the log statement. |
| `call_parents` | Array of Strings | (Milestone 2) Nodes that call this scope. |
| `call_children` | Array of Strings | (Milestone 2) Nodes called by this scope. |
