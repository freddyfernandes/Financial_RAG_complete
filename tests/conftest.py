import os
import sys
import pathlib
import importlib
import hashlib
from dataclasses import dataclass
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from langchain_core.embeddings import Embeddings


ROOT = Path(__file__).resolve().parents[1]


# -----------------------
# Temporary directories
# -----------------------
@dataclass
class TmpDirs:
    workdir: Path
    sessions_dir: Path
    uploads_dir: Path
    index_dir: Path


@pytest.fixture
def tmp_dirs(tmp_path: Path) -> TmpDirs:
    """
    Provides an isolated temp workspace + common dirs.
    Also chdirs into the workspace so relative paths like `faiss_index/test`
    resolve inside tmp_path (matches your unit tests).
    """
    cwd = Path.cwd()
    workdir = tmp_path

    # Common dirs your code/tests may use
    sessions_dir = workdir / "sessions"
    uploads_dir = workdir / "uploads"
    index_dir = workdir / "index"

    sessions_dir.mkdir(parents=True, exist_ok=True)
    uploads_dir.mkdir(parents=True, exist_ok=True)
    index_dir.mkdir(parents=True, exist_ok=True)

    # Also create the dirs your app writes to by default
    (workdir / "data").mkdir(parents=True, exist_ok=True)
    (workdir / "faiss_index").mkdir(parents=True, exist_ok=True)

    try:
        os.chdir(workdir)
        yield TmpDirs(
            workdir=workdir,
            sessions_dir=sessions_dir,
            uploads_dir=uploads_dir,
            index_dir=index_dir,
        )
    finally:
        os.chdir(cwd)


# -----------------------
# Global test environment
# -----------------------
@pytest.fixture(autouse=True)
def _test_env(monkeypatch):
    """Ensure tests never depend on real API keys/env."""
    monkeypatch.setenv("GROQ_API_KEY", "dummy")
    monkeypatch.setenv("GOOGLE_API_KEY", "dummy")
    monkeypatch.setenv("LLM_PROVIDER", "google")
    yield


@pytest.fixture(autouse=True)
def _ensure_repo_root_on_path():
    """Make `import main` and `import multi_doc_chat...` reliable in local + CI."""
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    yield


@pytest.fixture
def tmp_workdir(tmp_path: pathlib.Path):
    """
    (Used by integration/app tests) Run in an isolated working directory.
    """
    cwd = pathlib.Path.cwd()
    try:
        os.chdir(tmp_path)
        (tmp_path / "data").mkdir(parents=True, exist_ok=True)
        (tmp_path / "faiss_index").mkdir(parents=True, exist_ok=True)
        yield tmp_path
    finally:
        os.chdir(cwd)


# -----------------------
# Stubs
# -----------------------
class StubEmbeddings(Embeddings):
    """Deterministic tiny embeddings for tests (FAISS expects an Embeddings object)."""

    def __init__(self, size: int = 8):
        self.size = size

    def _vec(self, text: str) -> list[float]:
        h = hashlib.sha256(text.encode("utf-8")).digest()
        return [b / 255.0 for b in h[: self.size]]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._vec(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vec(text)


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
            # IMPORTANT: return an Embeddings instance (not a callable object)
            return StubEmbeddings(size=8)

        def load_llm(self):
            return _StubLLM()

    # Patch at the source module
    monkeypatch.setattr(ml_mod, "ApiKeyManager", FakeApiKeyMgr, raising=True)
    monkeypatch.setattr(ml_mod, "ModelLoader", FakeModelLoader, raising=True)

    # Patch any modules that imported ModelLoader already
    import multi_doc_chat.src.document_ingestion.data_ingestion as di
    import multi_doc_chat.src.document_chat.retrieval as r

    monkeypatch.setattr(di, "ModelLoader", FakeModelLoader, raising=True)
    monkeypatch.setattr(r, "ModelLoader", FakeModelLoader, raising=True)

    yield FakeModelLoader


# -----------------------
# App + client fixtures
# -----------------------
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

    if hasattr(main, "SESSIONS"):
        main.SESSIONS.clear()

    return main.app


@pytest.fixture
def client(app):
    return TestClient(app)


@pytest.fixture
def clear_sessions():
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
