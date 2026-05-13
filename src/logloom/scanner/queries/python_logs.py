from pathlib import Path

_query_path = Path(__file__).parent / "python_logs.scm"
PYTHON_LOGS_QUERY = _query_path.read_text(encoding="utf-8")
