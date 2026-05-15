import json
import urllib.request
from src.logloom.elasticsearch.mapping import generate_enrich_policy, generate_enrich_pipeline

ES_URL = "http://localhost:9205"

# 1. Create Index template
req = urllib.request.Request(f"{ES_URL}/_index_template/logloom-enrichment", method="PUT")
req.add_header("Content-Type", "application/json")
template = {
    "index_patterns": ["logloom-enrichment*"],
    "template": {
        "mappings": {
            "properties": {
                "logloom": {
                    "properties": {
                        "node_id": {"type": "keyword"},
                        "file": {"type": "keyword"},
                        "module": {"type": "keyword"},
                        "function": {"type": "keyword"},
                        "message_template": {"type": "keyword"},
                        "level": {"type": "keyword"},
                        "line": {"type": "integer"},
                        "semantic_tags": {"type": "keyword"},
                        "call_parents": {"type": "keyword"},
                        "call_children": {"type": "keyword"},
                        "commit_sha": {"type": "keyword"}
                    }
                }
            }
        }
    }
}
urllib.request.urlopen(urllib.request.Request(f"{ES_URL}/_index_template/logloom-enrichment", data=json.dumps(template).encode(), headers={'Content-Type': 'application/json'}, method='PUT'))

# Create dummy index so policy can be created
urllib.request.urlopen(urllib.request.Request(f"{ES_URL}/logloom-enrichment", method='PUT'))

# 2. Create Enrich policy
policy = generate_enrich_policy()
urllib.request.urlopen(urllib.request.Request(f"{ES_URL}/_enrich/policy/logloom-enrich", data=json.dumps(policy).encode(), headers={'Content-Type': 'application/json'}, method='PUT'))

# Execute Enrich policy
urllib.request.urlopen(urllib.request.Request(f"{ES_URL}/_enrich/policy/logloom-enrich/_execute", method='POST'))

# 3. Create Ingest pipeline
pipeline = generate_enrich_pipeline()
urllib.request.urlopen(urllib.request.Request(f"{ES_URL}/_ingest/pipeline/logloom-pipeline", data=json.dumps(pipeline).encode(), headers={'Content-Type': 'application/json'}, method='PUT'))

print("Successfully deployed pipeline!")
