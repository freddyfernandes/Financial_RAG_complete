import os
import sys
import pathlib
import importlib
import pytest
from fastapi.testclient import TestClient

ROOT = pathlib.Path(__file__).resolve().parents[1]


# --- Global, consistent environment for all tests ---
@pytest.fixture(autouse=True)
def _test_env(monkeypatch):
    """
    Ensures tests never depend on real API keys or developer machine env.
    """
    monkeypatch.setenv("GROQ_API_KEY", "dummy")
    monkeypatch.setenv("GOOGLE_API_KEY", "dummy")

    # Default provider for your app config loader
    monkeypatch.setenv("LLM_PROVIDER", "google")

    # If you have config path logic in your code, you can set it here too:
    # monkeypatch.setenv("CONFIG_PATH", str(ROOT / "multi_doc_chat" / "config" / "config.yaml"))

    yield


@pytest.fixture(autouse=True)
def _ensure_repo_root_on_path():
    """
    Makes `import main` and `import multi_doc_chat...` reliable in local + CI.
    """
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    yield


@pytest.fixture
def tmp_workdir(tmp_path: pathlib.Path):
    """
    Run tests in an isolated working directory.
    Useful because your code writes to ./data and ./faiss_index.
    """
    cwd = pathlib.Path.cwd()
    try:
        os.chdir(tmp_path)
        (tmp_path / "data").mkdir(parents=True, exist_ok=True)
        (tmp_path / "faiss_index").mkdir(parents=True, exist_ok=True)
        yield tmp_path
    finally:
        os.chdir(cwd)


# ---- Stubs ----
class _StubEmbeddings:
    def embed_query(self, text: str):
        return [0.0, 0.1, 0.2]

    def embed_documents(self, texts):
        return [[0.0, 0.1, 0.2] for _ in texts]


class _StubLLM:
    def invoke(self, input):
        return "stubbed answer"


@pytest.fixture
def stub_model_loader(monkeypatch):
    """
    Replace ModelLoader + ApiKeyManager everywhere they are used
    so we never call external APIs in tests.
    """
    import multi_doc_chat.utils.model_loader as ml_mod

    class FakeApiKeyMgr:
        def __init__(self):
            self.api_keys = {"GROQ_API_KEY": "x", "GOOGLE_API_KEY": "y"}

        def get(self, key: str) -> str:
            return self.api_keys[key]

    class FakeModelLoader:
        def __init__(self):
            self.api_key_mgr = FakeApiKeyMgr()
            self.config = {
                "embedding_model": {"model_name": "fake-embed"},
                "llm": {
                    "google": {
                        "provider": "google",
                        "model_name": "fake-llm",
                        "temperature": 0.0,
                        "max_output_tokens": 128,
                    }
                },
            }

        def load_embeddings(self):
            return _StubEmbeddings()

        def load_llm(self):
            return _StubLLM()

    # Patch at the source
    monkeypatch.setattr(ml_mod, "ApiKeyManager", FakeApiKeyMgr, raising=True)
    monkeypatch.setattr(ml_mod, "ModelLoader", FakeModelLoader, raising=True)

    # Patch any modules that imported ModelLoader already
    import multi_doc_chat.src.document_ingestion.data_ingestion as di
    import multi_doc_chat.src.document_chat.retrieval as r
    monkeypatch.setattr(di, "ModelLoader", FakeModelLoader, raising=True)
    monkeypatch.setattr(r, "ModelLoader", FakeModelLoader, raising=True)

    yield FakeModelLoader


@pytest.fixture
def app(stub_model_loader, tmp_workdir):
    """
    Import (or reload) `main` after stubs are installed,
    so app startup uses the stubs.
    """
    if "main" in sys.modules:
        main = importlib.reload(sys.modules["main"])
    else:
        main = importlib.import_module("main")

    # Ensure clean state each test
    if hasattr(main, "SESSIONS"):
        main.SESSIONS.clear()

    return main.app


@pytest.fixture
def client(app):
    return TestClient(app)


@pytest.fixture
def clear_sessions():
    """
    Useful if you import main somewhere else and want to ensure clean session state.
    """
    import main
    main.SESSIONS.clear()
    yield
    main.SESSIONS.clear()


@pytest.fixture
def stub_ingestor(monkeypatch):
    import main
    import multi_doc_chat.src.document_ingestion.data_ingestion as di

    class FakeIngestor:
        def __init__(self, use_session_dirs=True, **kwargs):
            self.session_id = "sess_test"

        def built_retriver(self, uploaded_files, **kwargs):
            return None

    monkeypatch.setattr(di, "ChatIngestor", FakeIngestor, raising=True)
    monkeypatch.setattr(main, "ChatIngestor", FakeIngestor, raising=True)
    yield FakeIngestor


@pytest.fixture
def stub_rag(monkeypatch):
    import main
    import multi_doc_chat.src.document_chat.retrieval as r

    class FakeRAG:
        def __init__(self, session_id=None, retriever=None):
            self.session_id = session_id
            self.retriever = retriever

        def load_retriever_from_faiss(self, index_path, **kwargs):
            return None

        def invoke(self, user_input, chat_history=None):
            return "stubbed answer"

    monkeypatch.setattr(r, "ConversationalRAG", FakeRAG, raising=True)
    monkeypatch.setattr(main, "ConversationalRAG", FakeRAG, raising=True)
    yield FakeRAG
