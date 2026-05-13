from logloom.logger.resolver import NodeResolver
from logloom.graph.model import LogLoomGraph, GraphNode

def test_node_resolver():
    graph = LogLoomGraph(
        project="test",
        built_at="2026",
        nodes={
            "ll:123": GraphNode(
                node_id="ll:123",
                file="a.py",
                module="app.a",
                function="do_a",
                level="info",
                message_template="Doing A",
                line=10
            )
        }
    )
    
    resolver = NodeResolver(graph)
    
    # Exact match
    assert resolver.resolve("app.a", "do_a", "Doing A") == "ll:123"
    
    # Fuzzy match (wrong module, right function/message)
    assert resolver.resolve("app.b", "do_a", "Doing A") == "ll:123"
    
    # No match
    assert resolver.resolve("app.a", "do_b", "Doing A") is None
