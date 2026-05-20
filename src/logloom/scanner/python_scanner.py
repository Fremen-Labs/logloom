import tree_sitter_python as tspython
from tree_sitter import Language, Parser, Query
try:
    from tree_sitter import QueryCursor
except ImportError:
    QueryCursor = None
from pathlib import Path
from typing import List, Optional
from .base import LogCallSite
from .queries.python_logs import PYTHON_LOGS_QUERY

# Tree-sitter predicates (#match?) are NOT enforced by py-tree-sitter's
# QueryCursor — they are informational only. We must filter manually.
_VALID_LOG_METHODS = frozenset({
    "debug", "info", "warning", "error", "critical",
    "exception", "fatal", "log",
})


class PythonScanner:
    def __init__(self):
        try:
            self.language = Language(tspython.language())
        except TypeError:
            self.language = Language(tspython.language(), "python")
        self.parser = Parser(self.language)
        self.query = Query(self.language, PYTHON_LOGS_QUERY)

    def scan_file(self, file_path: Path) -> List[LogCallSite]:
        if not file_path.suffix == ".py":
            return []
        
        with open(file_path, "rb") as f:
            source = f.read()

        tree = self.parser.parse(source)
        if QueryCursor is not None:
            cursor = QueryCursor(self.query)
            matches = cursor.matches(tree.root_node)
        else:
            matches = self.query.matches(tree.root_node)

        sites = []
        for match in matches:
            # match is (pattern_index, dict_mapping_tag_to_nodes)
            captures_dict = match[1]
            
            log_method_nodes = captures_dict.get("log_method", [])
            first_arg_nodes = captures_dict.get("first_arg", [])
            
            if not log_method_nodes or not first_arg_nodes:
                continue
                
            log_method_node = log_method_nodes[0]
            first_arg_node = first_arg_nodes[0]
            
            level = log_method_node.text.decode("utf-8")

            # Manual predicate enforcement: skip non-log methods
            if level not in _VALID_LOG_METHODS:
                continue
            
            # Extract string content from first_arg_node (handling f-strings and concats)
            message = self._extract_string(first_arg_node, source)
            
            # Lexical context traversal
            enclosing_func, class_name, in_try, in_if, in_loop, decorators, func_node = self._get_lexical_context(log_method_node)

            # Phase B: Extract function signature from the enclosing function node
            sig = self._extract_signature(func_node, decorators) if func_node else None

            sites.append(LogCallSite(
                file_path=str(file_path),
                module_path=self._get_module_path(file_path),
                class_name=class_name,
                function_name=enclosing_func or "<module>",
                log_level=level,
                message_template=message,
                line=log_method_node.start_point.row + 1,
                column=log_method_node.start_point.column,
                lexical_context={
                    "enclosing_function": enclosing_func,
                    "in_try_except": in_try,
                    "in_if_block": in_if,
                    "in_loop": in_loop,
                    "decorators": decorators
                },
                signature=sig,
            ))

        return sites

    def _extract_string(self, node, source: bytes) -> str:
        """Robustly extract a message template from a string, f-string, or binary concat."""
        if node.type == "string":
            # For standard strings, we can just strip quotes.
            # But tree-sitter parses f-strings as a string containing:
            # string_start, string_content, interpolation, string_end
            parts = []
            has_interpolation = False
            for child in node.children:
                if child.type == "string_content":
                    parts.append(child.text.decode("utf-8"))
                elif child.type == "interpolation":
                    parts.append("{}")
                    has_interpolation = True
            
            if has_interpolation or parts:
                return "".join(parts)
            
            # Fallback for plain strings without child nodes in older parser versions
            text = node.text.decode("utf-8")
            if text.startswith('f"') or text.startswith("f'") or text.startswith('r"') or text.startswith("r'"):
                return text[2:-1]
            elif text.startswith('"') or text.startswith("'"):
                return text[1:-1]
            return text

        if node.type == "binary_operator":
            # Handle concats like: "Invalid user " + str(user_id)
            left = node.child_by_field_name("left")
            right = node.child_by_field_name("right")
            if left and right:
                return self._extract_string(left, source) + self._extract_string(right, source)

        # If it is not a string or binary concat (e.g. a variable, a call like str(user)),
        # replace it with a template placeholder {} so it behaves like f-strings.
        if node.type not in ("string", "binary_operator"):
            # Only do this if it's inside a binary_operator we are unwrapping,
            # but since we are called recursively, this handles the `right` branch of `left + right`.
            return "{}"

        # Absolute fallback
        text = node.text.decode("utf-8")
        if text.startswith('f"') or text.startswith("f'"):
            return text[2:-1]
        elif text.startswith('"') or text.startswith("'"):
            return text[1:-1]
        return text

    def _get_lexical_context(self, node):
        enclosing_func = None
        func_node = None  # Phase B: keep reference to the function AST node
        class_name = None
        in_try = False
        in_if = False
        in_loop = False
        decorators = []
        
        parent = node.parent
        while parent:
            if parent.type == "function_definition":
                if not enclosing_func: # Only grab the innermost function
                    func_node = parent  # Phase B: save the AST node
                    name_node = parent.child_by_field_name("name")
                    if name_node:
                        enclosing_func = name_node.text.decode("utf-8")
                    
                    # Grab decorators if any
                    for child in parent.children:
                        if child.type == "decorator":
                            decorators.append(child.text.decode("utf-8").lstrip("@"))
            
            elif parent.type == "class_definition":
                if not class_name: # Innermost class
                    name_node = parent.child_by_field_name("name")
                    if name_node:
                        class_name = name_node.text.decode("utf-8")
            
            elif parent.type == "try_statement":
                in_try = True
            elif parent.type == "if_statement":
                in_if = True
            elif parent.type in ["for_statement", "while_statement"]:
                in_loop = True
                
            parent = parent.parent
            
        return enclosing_func, class_name, in_try, in_if, in_loop, decorators, func_node

    # ── Phase B: Function signature extraction ────────────────────────────────

    def _extract_signature(self, func_node, decorators: list) -> dict:
        """Extract function signature from a function_definition AST node.

        Returns a dict matching the FunctionSignature schema:
          {"parameters": [...], "return_type": str|None,
           "is_async": bool, "decorators": [...]}

        tree-sitter Python AST for: async def foo(x: int, y: str = 'bar') -> bool:
          function_definition
            name: identifier "foo"
            parameters: parameters
              identifier "x"         (or typed_parameter for x: int)
              default_parameter      (for y: str = 'bar')
            return_type: type         (-> bool)
        """
        params = []
        return_type = None
        is_async = False

        if not func_node:
            return {"parameters": params, "return_type": return_type,
                    "is_async": is_async, "decorators": decorators}

        # Check for async keyword
        for child in func_node.children:
            if child.type == "async":
                is_async = True
                break

        # Extract parameters
        params_node = func_node.child_by_field_name("parameters")
        if params_node:
            for child in params_node.children:
                param = self._extract_param(child)
                if param:
                    params.append(param)

        # Extract return type annotation
        ret_node = func_node.child_by_field_name("return_type")
        if ret_node:
            return_type = ret_node.text.decode("utf-8").strip()

        return {
            "parameters": params,
            "return_type": return_type,
            "is_async": is_async,
            "decorators": decorators,
        }

    def _extract_param(self, node) -> Optional[dict]:
        """Extract a single parameter from the AST.

        Handles:
          - identifier: plain param (no type hint)
          - typed_parameter: param with type annotation (x: int)
          - default_parameter: param with default (x=5 or x: int = 5)
          - typed_default_parameter: typed with default
          - list_splat_pattern / dictionary_splat_pattern: *args, **kwargs
        """
        if node.type in ("(", ")", ","):
            return None

        if node.type == "identifier":
            name = node.text.decode("utf-8")
            if name == "self" or name == "cls":
                return None  # Skip self/cls — not useful for API understanding
            return {"name": name, "type_hint": None, "default": None}

        if node.type == "typed_parameter":
            name_node = node.children[0] if node.children else None
            type_node = node.child_by_field_name("type")
            name = name_node.text.decode("utf-8") if name_node else "?"
            if name in ("self", "cls"):
                return None
            type_hint = type_node.text.decode("utf-8") if type_node else None
            return {"name": name, "type_hint": type_hint, "default": None}

        if node.type == "default_parameter":
            name_node = node.child_by_field_name("name")
            value_node = node.child_by_field_name("value")
            name = name_node.text.decode("utf-8") if name_node else "?"
            if name in ("self", "cls"):
                return None
            default = value_node.text.decode("utf-8") if value_node else None
            return {"name": name, "type_hint": None, "default": default}

        if node.type == "typed_default_parameter":
            name_node = node.child_by_field_name("name")
            type_node = node.child_by_field_name("type")
            value_node = node.child_by_field_name("value")
            name = name_node.text.decode("utf-8") if name_node else "?"
            if name in ("self", "cls"):
                return None
            type_hint = type_node.text.decode("utf-8") if type_node else None
            default = value_node.text.decode("utf-8") if value_node else None
            return {"name": name, "type_hint": type_hint, "default": default}

        if node.type == "list_splat_pattern":
            name = "*" + (node.children[1].text.decode("utf-8") if len(node.children) > 1 else "args")
            return {"name": name, "type_hint": None, "default": None}

        if node.type == "dictionary_splat_pattern":
            name = "**" + (node.children[1].text.decode("utf-8") if len(node.children) > 1 else "kwargs")
            return {"name": name, "type_hint": None, "default": None}

        return None

    def _get_module_path(self, file_path: Path) -> str:
        parts = list(file_path.with_suffix("").parts)
        if "src" in parts:
            idx = parts.index("src")
            return ".".join(parts[idx+1:])
        return ".".join(parts[-3:])