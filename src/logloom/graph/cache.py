import json
import hashlib
from pathlib import Path
from typing import Dict, List, Any, Optional
from ..scanner.base import LogCallSite

class BuildCache:
    def __init__(self, cache_path: Path):
        self.cache_path = cache_path
        self.data = {"files": {}}
        self.load()

    def load(self):
        if self.cache_path.exists():
            try:
                with open(self.cache_path, "r", encoding="utf-8") as f:
                    self.data = json.load(f)
            except Exception:
                self.data = {"files": {}}

    def save(self):
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.cache_path, "w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=2)
        except Exception:
            pass

    def get_file_entry(self, file_path: Path) -> Optional[Dict[str, Any]]:
        key = str(file_path.resolve())
        return self.data.get("files", {}).get(key)

    def set_file_entry(
        self,
        file_path: Path,
        file_hash: str,
        sites: List[LogCallSite],
        models: List[Any],
        imports: List[str],
        defined_functions: List[str],
    ):
        key = str(file_path.resolve())
        
        # Serialize sites
        serialized_sites = []
        for s in sites:
            serialized_sites.append({
                "file_path": s.file_path,
                "module_path": s.module_path,
                "class_name": s.class_name,
                "function_name": s.function_name,
                "log_level": s.log_level,
                "message_template": s.message_template,
                "line": s.line,
                "column": s.column,
                "lexical_context": s.lexical_context,
                "signature": s.signature,
            })

        # Serialize models
        serialized_models = [m.model_dump() for m in models]

        self.data.setdefault("files", {})[key] = {
            "hash": file_hash,
            "sites": serialized_sites,
            "models": serialized_models,
            "imports": imports,
            "defined_functions": defined_functions,
        }

    def clean_unused_entries(self, active_files: List[Path]):
        active_keys = {str(f.resolve()) for f in active_files}
        current_keys = list(self.data.get("files", {}).keys())
        for k in current_keys:
            if k not in active_keys:
                self.data["files"].pop(k, None)


def calculate_file_hash(path: Path) -> str:
    try:
        content = path.read_bytes()
        return hashlib.sha256(content).hexdigest()
    except Exception:
        return ""
