import hashlib
import json
import inspect
from datetime import datetime
from typing import Dict

class LogLoomGraph:
    def __init__(self):
        self.nodes: Dict[str, Dict] = {}
    
    def register_log_site(self, file_path: str, line: int, func_name: str, message: str):
        key = f"{file_path}:{line}:{func_name}:{message}"
        node_id = "ll:" + hashlib.sha256(key.encode()).hexdigest()[:16]
        
        self.nodes[node_id] = {
            "id": node_id,
            "file": file_path,
            "line": line,
            "function": func_name,
            "message_template": message,
            "semantic_tags": ["auth", "error"] if "login" in message.lower() else [],
            "parent_nodes": ["ll:parent-auth-check"]
        }
        return node_id

class LogLoomLogger:
    def __init__(self):
        self.graph = LogLoomGraph()
    
    def info(self, message: str, **kwargs):
        frame = inspect.currentframe().f_back
        file = frame.f_code.co_filename
        line = frame.f_lineno
        func = frame.f_code.co_name
        
        node_id = self.graph.register_log_site(file, line, func, message)
        
        log_entry = {
            "@timestamp": datetime.utcnow().isoformat() + "Z",
            "log.level": "INFO",
            "message": message,
            **kwargs,
            "logloom.node_id": node_id,
            "logloom.traversal": self.graph.nodes.get(node_id, {}).get("parent_nodes", []),
            "service.version": "0.1.0"
        }
        
        print("📝 HUMAN LOG:", message, kwargs)
        print("🔗 FOR ELASTIC:", json.dumps(log_entry, indent=2))
        return log_entry

if __name__ == "__main__":
    logger = LogLoomLogger()
    logger.info("User login failed", user_id=123, reason="token_expired")