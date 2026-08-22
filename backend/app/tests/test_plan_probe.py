import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts import plan_probe


def test_build_extraction_messages_use_research_paper_content():
    paper_text = "Title: Deep Residual Learning for Image Recognition\nAuthors: Kaiming He, Xiangyu Zhang"

    messages = plan_probe.build_extraction_messages(paper_text)

    assert messages[0]["role"] == "system"
    assert "structured data extraction" in messages[0]["content"]
    assert "research paper" in messages[0]["content"]
    assert messages[1] == {"role": "user", "content": paper_text}


def test_research_paper_extraction_model_matches_official_example_shape():
    schema = plan_probe.ResearchPaperExtraction.model_json_schema()

    assert set(schema["properties"]) == {"title", "authors", "abstract", "keywords"}
    assert schema["properties"]["authors"]["items"]["type"] == "string"
    assert schema["properties"]["keywords"]["items"]["type"] == "string"


def test_load_dotenv_reads_api_keys_without_overriding_existing_env(tmp_path, monkeypatch):
    env_path = tmp_path / ".env"
    env_path.write_text("API_KEY=from-file\nAPI_URL=http://example.test/v1\nAPI_MODEL=test-model\n", encoding="utf-8")
    monkeypatch.setenv("API_KEY", "from-env")
    monkeypatch.delenv("API_URL", raising=False)
    monkeypatch.delenv("API_MODEL", raising=False)

    plan_probe.load_dotenv(env_path)

    assert plan_probe.os.environ["API_KEY"] == "from-env"
    assert plan_probe.os.environ["API_URL"] == "http://example.test/v1"
    assert plan_probe.os.environ["API_MODEL"] == "test-model"
