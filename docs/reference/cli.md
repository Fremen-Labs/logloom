# CLI Reference

LogLoom ships with an intuitive, `click`-based command line interface for managing your project's knowledge graph.

## `logloom init`

Initializes LogLoom within the current directory.

**Usage:**
```bash
logloom init [OPTIONS]
```

**Options:**
*   `--force`: Overwrite existing `.logloomrc.toml` and `.logloomignore` files if they are already present.

**Behavior:**
*   Prompts interactively for the project name.
*   Scaffolds default configuration files.

---

## `logloom build`

Scans your repository using the Tree-sitter AST and Regex fallback engines, deterministically hashes node IDs, and generates `logloom-graph.json`.

**Usage:**
```bash
logloom build [OPTIONS]
```

**Options:**
*   `--source PATH`: The directory to scan. Defaults to the current working directory (`.`).
*   `--output PATH`: The destination to write the JSON graph. Defaults to `logloom-graph.json` in the current directory.
*   `--redact-patterns TEXT`: A comma-separated list of substrings to censor. Any log message template containing a match will be scrubbed and replaced with `[REDACTED]`.

**Examples:**
```bash
# Basic build targeting the src directory
logloom build --source src/

# Build with sensitive data redaction
logloom build --source app/ --redact-patterns "password,token,secret"
```
