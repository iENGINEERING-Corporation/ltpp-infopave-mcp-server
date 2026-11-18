# Evaluations

Evaluation scripts live in [`local/`](local/) (our own workbook-based
runner) and [`databricks/`](databricks/README.md).

The quality of an MCP server is not how many tools it has, but how well an LLM
with no other context can use those tools to answer realistic, difficult questions.
The `mcp-builder` skill (`.agents/skills/mcp-builder/`) covers Phase 4, writing the
gold questions used for evaluation.
