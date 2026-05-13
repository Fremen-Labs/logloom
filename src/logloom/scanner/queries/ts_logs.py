from pathlib import Path

_query_path = Path(__file__).parent / "ts_logs.scm"
TS_LOGS_QUERY = _query_path.read_text(encoding="utf-8")
