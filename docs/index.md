# LogLoom Documentation

Welcome to the LogLoom documentation. We follow the [Diátaxis framework](https://diataxis.fr/), which organizes our documentation into four distinct quadrants, ensuring you find exactly the kind of help you need.

## 🎓 Tutorials
*Learning-oriented material aimed at beginners.*
- [Getting Started](tutorials/getting-started.md): Your first steps with LogLoom—from installation to executing your first graph build.

## 🛠 How-To Guides
*Problem-oriented guides for achieving specific goals.*
- [How to Redact Sensitive Data](how-to/redact-sensitive-data.md): Prevent PII, passwords, and sensitive keys from ever hitting your knowledge graph.
- [How to Deploy in Production](how-to/deploy-in-production.md): Managing your `logloom-graph.json` via environment variables and Docker containers.
- [How to Integrate with Elastic Beats & OTEL](how-to/elastic-integrations.md): Learn how LogLoom integrates seamlessly with every Elastic data collection path.

## 📖 Reference
*Information-oriented material for quick lookup.*
- [CLI Reference](reference/cli.md): Exhaustive list of commands, flags, and options for the `logloom` CLI.
- [Graph Schema](reference/graph-schema.md): Detailed specification of the `LogLoomGraph` JSON structure.

## 🧠 Explanation
*Understanding-oriented material to deepen your knowledge.*
- [How AST Scanning Works](explanation/ast-scanning.md): Understand the magic behind our Tree-sitter engine and the resilient Regex fallback.
- [Hybrid Hashing & Collision Disambiguation](explanation/hybrid-hashing.md): Learn why our `ll:` node IDs are mathematically stable across code refactors.
