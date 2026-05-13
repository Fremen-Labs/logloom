import tree_sitter_python as tspython
from tree_sitter import Language, Parser
lang = Language(tspython.language())
parser = Parser(lang)
tree = parser.parse(b"logger.info('test')")
query = lang.query("(call function: (attribute) @log_method arguments: (_) @first_arg) @log_call")
print(query.captures(tree.root_node))
try:
    print(query.matches(tree.root_node))
except Exception as e:
    print("matches error:", e)
