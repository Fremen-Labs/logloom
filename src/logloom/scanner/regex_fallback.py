import re
from pathlib import Path
from .base import LogCallSite

LOG_CALL_RE = re.compile(
    r'(?:logger|log|logging|self\.log(?:ger)?)\s*\.\s*'
    r'(debug|info|warning|error|critical|exception|fatal|log)'
    r'\s*\(\s*(?:f?["\'])(.+?)(?:["\'])',
    re.VERBOSE | re.MULTILINE | re.IGNORECASE
)

def regex_fallback_scan(file_path: Path) -> list[LogCallSite]:
    if not file_path.suffix == ".py":
        return []
    with open(file_path, encoding="utf-8") as f:
        content = f.read()
    
    sites = []
    for match in LOG_CALL_RE.finditer(content):
        level = match.group(1).lower()
        message = match.group(2)
        sites.append(LogCallSite(
            file_path=str(file_path),
            module_path="unknown",
            class_name=None,
            function_name="unknown",
            log_level=level,
            message_template=message,
            line=content[:match.start()].count("\n") + 1,
            column=0,
        ))
    return sites