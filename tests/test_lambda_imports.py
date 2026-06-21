import importlib.util
import os
import sys

# Mock required environment variables before any Lambda module is imported
os.environ.setdefault("DB_CLUSTER_ARN", "arn:aws:rds:us-east-1:123456789012:cluster:test")
os.environ.setdefault("DB_SECRET_ARN", "arn:aws:secretsmanager:us-east-1:123456789012:secret:test")
os.environ.setdefault("QUOTE_JOBS_QUEUE_URL", "https://sqs.us-east-1.amazonaws.com/123456789012/test")
os.environ.setdefault("QUOTE_RESULTS_TABLE", "iqg-quote-results")
os.environ.setdefault("CHAT_HISTORY_TABLE", "iqg-chat-history")
os.environ.setdefault("WS_CONNECTIONS_TABLE", "iqg-ws-connections")
os.environ.setdefault("IDEMPOTENCY_TABLE", "iqg-idempotency-keys")
os.environ.setdefault("AUDIT_BUCKET", "iqg-audit-test")
os.environ.setdefault("REGION", "us-east-1")
os.environ.setdefault("BEDROCK_MODEL_ID", "us.anthropic.claude-sonnet-4-6")
os.environ.setdefault("USER_POOL_ID", "us-east-1_testpool")
os.environ.setdefault("WS_ENDPOINT", "https://test.execute-api.us-east-1.amazonaws.com/v1")

LAMBDA_HANDLERS = [
    ("lambda/ingestion_api/ingestion_api.py", "ingestion_api"),
    ("lambda/quote_worker/quote_worker.py", "quote_worker"),
    ("lambda/chat_conversation/chat_conversation.py", "chat_conversation"),
    ("lambda/ws_connect/ws_connect.py", "ws_connect"),
    ("lambda/ws_disconnect/ws_disconnect.py", "ws_disconnect"),
    ("lambda/ws_chat/ws_chat.py", "ws_chat"),
    ("lambda/ws_authorizer/ws_authorizer.py", "ws_authorizer"),
]

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_module(rel_path, module_name):
    abs_path = os.path.join(REPO_ROOT, rel_path)
    # Add the lambda directory to sys.path so relative imports work
    lambda_dir = os.path.dirname(abs_path)
    if lambda_dir not in sys.path:
        sys.path.insert(0, lambda_dir)
    spec = importlib.util.spec_from_file_location(module_name, abs_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_ingestion_api_has_handler():
    mod = load_module("lambda/ingestion_api/ingestion_api.py", "ingestion_api")
    assert hasattr(mod, "handler"), "ingestion_api.py must define a handler function"
    assert callable(mod.handler)


def test_quote_worker_has_handler():
    mod = load_module("lambda/quote_worker/quote_worker.py", "quote_worker")
    assert hasattr(mod, "handler"), "quote_worker.py must define a handler function"
    assert callable(mod.handler)


def test_chat_conversation_has_handler():
    mod = load_module("lambda/chat_conversation/chat_conversation.py", "chat_conversation")
    assert hasattr(mod, "handler"), "chat_conversation.py must define a handler function"
    assert callable(mod.handler)


def test_ws_connect_has_handler():
    mod = load_module("lambda/ws_connect/ws_connect.py", "ws_connect")
    assert hasattr(mod, "handler"), "ws_connect.py must define a handler function"
    assert callable(mod.handler)


def test_ws_disconnect_has_handler():
    mod = load_module("lambda/ws_disconnect/ws_disconnect.py", "ws_disconnect")
    assert hasattr(mod, "handler"), "ws_disconnect.py must define a handler function"
    assert callable(mod.handler)


def test_ws_chat_has_handler():
    mod = load_module("lambda/ws_chat/ws_chat.py", "ws_chat")
    assert hasattr(mod, "handler"), "ws_chat.py must define a handler function"
    assert callable(mod.handler)


def test_ws_authorizer_has_handler():
    mod = load_module("lambda/ws_authorizer/ws_authorizer.py", "ws_authorizer")
    assert hasattr(mod, "handler"), "ws_authorizer.py must define a handler function"
    assert callable(mod.handler)
