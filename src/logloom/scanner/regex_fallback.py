import re
from pathlib import Path
from typing import List
from .base import LogCallSite

LOG_CALL_RE = re.compile(
    r'(?:logger|log|logging|self\.log(?:ger)?)\s*\.\s*'
    r'(debug|info|warning|error|critical|exception|fatal|log)'
    r'\s*\(\s*(?:f?["\'])(.+?)(?:["\'])',
    re.VERBOSE | re.MULTILINE | re.IGNORECASE
)

def regex_fallback_scan(file_path: Path) -> List[LogCallSite]:
    if not file_path.suffix == ".py":
        return []
    with open(file_path, encoding="utf-8") as f:
        content = f.read()
    
    sites = []
    for match in LOG_CALL_RE.finditer(content):
        level = match.group(1).lower()
        message = match.group(2)
        
        # We can't easily get full lexical context from regex, so we leave it minimal
        line = content[:match.start()].count("\n") + 1
        
        sites.append(LogCallSite(
            file_path=str(file_path),
            module_path=_get_module_path(file_path),
            class_name=None,
            function_name="unknown",
            log_level=level,
            message_template=message,
            line=line,
            column=0,
            lexical_context={
                "enclosing_function": None,
                "in_try_except": False,
                "in_if_block": False,
                "in_loop": False,
                "decorators": []
            }
        ))
    return sites

def _get_module_path(file_path: Path) -> str:
    parts = list(file_path.with_suffix("").parts)
    if "src" in parts:
        idx = parts.index("src")
        return ".".join(parts[idx+1:])
    return ".".join(parts[-3:])