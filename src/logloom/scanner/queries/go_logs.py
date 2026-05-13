from pathlib import Path

_query_path = Path(__file__).parent / "go_logs.scm"
GO_LOGS_QUERY = _query_path.read_text(encoding="utf-8")
