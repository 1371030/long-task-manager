import json
import os
import sys
from argparse import ArgumentParser, Namespace
from pathlib import Path

from openai import OpenAI
from pydantic import BaseModel


BASE_URL = "http://v3.imx365.net:8317/v1"
DEFAULT_MODEL = "gpt-5.4"
ENV_PATH = Path(__file__).resolve().parents[1] / ".env"
DEFAULT_PAPER_TEXT = "..."


class ResearchPaperExtraction(BaseModel):
    title: str
    authors: list[str]
    abstract: str
    keywords: list[str]


def build_extraction_messages(paper_text: str) -> list[dict[str, str]]:
    return [
        {
            "role": "system",
            "content": "You are an expert at structured data extraction. You will be given unstructured text from a research paper and should convert it into the given structure.",
        },
        {"role": "user", "content": paper_text.strip()},
    ]


def load_dotenv(path: Path = ENV_PATH) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


def parse_args(argv: list[str]) -> Namespace:
    parser = ArgumentParser(description="Extract structured fields from research paper text.")
    parser.add_argument("paper_text", nargs="*", help="Research paper text to extract from.")
    parser.add_argument("--content-file", type=Path, help="Path to a UTF-8 file containing research paper text.")
    return parser.parse_args(argv)


def read_paper_text(argv: list[str]) -> str:
    args = parse_args(argv)

    if args.content_file:
        return args.content_file.read_text(encoding="utf-8").strip()
    if args.paper_text:
        return " ".join(args.paper_text).strip()
    if not sys.stdin.isatty():
        piped_content = sys.stdin.read().strip()
        if piped_content:
            return piped_content
    return DEFAULT_PAPER_TEXT


def main() -> None:
    load_dotenv()
    api_key = os.getenv("IMX_API_KEY") or os.getenv("API_KEY")
    if not api_key:
        raise SystemExit("IMX_API_KEY or API_KEY must be set")
    paper_text = read_paper_text(sys.argv[1:])

    client = OpenAI(
        api_key=api_key,
        base_url=os.getenv("IMX_API_URL") or os.getenv("API_URL") or BASE_URL,
    )

    model = os.getenv("IMX_API_MODEL") or os.getenv("API_MODEL") or DEFAULT_MODEL
    response = client.responses.parse(
        model=model,
        input=build_extraction_messages(paper_text),
        text_format=ResearchPaperExtraction,
    )
    result = response.output_parsed.model_dump()

    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
