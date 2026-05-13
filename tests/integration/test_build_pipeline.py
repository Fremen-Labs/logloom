import pytest
from pathlib import Path
from logloom.graph.builder import GraphBuilder

DUMMY_APP_CONTENT = """
import logging

def do_login(user_id: int):
    try:
        logging.info(f"User {user_id} attempting login")
        if user_id < 0:
            logging.error("Invalid user " + str(user_id))
    except Exception as e:
        logging.exception(f"Login failed for {user_id}")

class AuthService:
    def authenticate(self, token):
        self.log.debug("Authenticating token")
"""

def test_graph_builder_pipeline(tmp_path: Path):
    app_file = tmp_path / "app.py"
    app_file.write_text(DUMMY_APP_CONTENT)
    
    builder = GraphBuilder()
    graph = builder.build([app_file])
    
    assert len(graph.nodes) == 4
    
    # Verify the f-string interpolation replacing
    node_messages = {node.message_template for node in graph.nodes.values()}
    
    assert "User {} attempting login" in node_messages
    assert "Invalid user {}" in node_messages
    assert "Login failed for {}" in node_messages
    assert "Authenticating token" in node_messages

    # Verify lexical contexts
    for node in graph.nodes.values():
        if node.message_template == "Login failed for {}":
            assert node.function == "do_login"
            assert "do_login" in node.lexical_parents
            assert "error" in node.semantic_tags # exception maps to error tag? wait
        if node.message_template == "Authenticating token":
            assert node.function == "authenticate"
            assert node.module.endswith("app") # Since it's in tmp_path/app.py
