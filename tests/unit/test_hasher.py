from logloom.graph.hasher import NodeHasher

def test_hasher_deterministic():
    hasher = NodeHasher()
    id1 = hasher.generate_node_id("app.main", "App", "run", "Starting app", "src/app/main.py", "")
    
    # Another instance with same inputs should generate the same ID
    hasher2 = NodeHasher()
    id2 = hasher2.generate_node_id("app.main", "App", "run", "Starting app", "src/app/main.py", "")
    
    assert id1 == id2
    assert id1.startswith("ll:")
    assert len(id1) == 15 # "ll:" + 12 chars

def test_hasher_collision_disambiguation():
    hasher = NodeHasher()
    # First call
    id1 = hasher.generate_node_id("app.auth", None, "login", "Failed", "auth.py", "try_block")
    
    # Second call identical primary details, should get a collision suffix
    id2 = hasher.generate_node_id("app.auth", None, "login", "Failed", "auth.py", "except_block")
    
    assert id1 != id2
    assert ":" in id2[3:] # suffix appended
