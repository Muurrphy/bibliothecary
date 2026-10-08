import datetime as dt
import json
from pathlib import Path

import pytest

from bibliothecary import library, search, telegram
from margin import llm
from margin.ingest import from_pdf, load_article
from margin.lesson import Lesson

ROOT = Path(__file__).resolve().parents[1]
ME = 111

OPENALEX = {"results": [
    {"title": "Cyclic alternation of quiet and active sleep states in the octopus", "publication_year": 2021,
     "cited_by_count": 120, "doi": "https://doi.org/10.1016/j.isci.2021.102223",
     "best_oa_location": {"pdf_url": "https://www.cell.com/article/S2589-0042(21)00191-5/pdf"},
     "primary_location": {"source": {"display_name": "iScience"}},
     "abstract_inverted_index": {"Octopuses": [0], "sleep": [1], "twice": [2]}},
    {"title": "No address at all", "publication_year": 2020},
]}

ARXIV = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry><id>http://arxiv.org/abs/2401.00001v1</id><title>Active sleep
   in cephalopods</title><published>2024-01-02T00:00:00Z</published><summary>We study sleep.</summary></entry>
</feed>"""


def test_openalex_results_and_filters():
    asked = []

    def get(url):
        asked.append(url)
        return json.dumps(OPENALEX).encode()

    found = search.openalex("octopus sleep", "classic", today=dt.date(2026, 10, 8), get=get)
    assert found == [{"title": "Cyclic alternation of quiet and active sleep states in the octopus", "year": 2021,
                      "venue": "iScience", "cited": 120,
                      "url": "https://www.cell.com/article/S2589-0042(21)00191-5/pdf", "about": "Octopuses sleep twice"}]
    assert "sort=cited_by_count%3Adesc" in asked[0] and "to_publication_date%3A2021-12-31" in asked[0]
    assert "open_access.is_oa%3Atrue" in asked[0]
    search.openalex("octopus sleep", "new", today=dt.date(2026, 10, 8), get=get)
    assert "from_publication_date%3A2025-10-08" in asked[1]


def test_papers_fall_back_to_arxiv():
    def get(url):
        if "openalex" in url:
            raise search.SearchError("429 from api.openalex.org")
        return ARXIV

    found = search.papers("octopus sleep", "new", get=get)
    assert found[0]["title"] == "Active sleep in cephalopods" and found[0]["url"] == "http://arxiv.org/pdf/2401.00001v1"
    assert "Active sleep in cephalopods (2024, arXiv)" in search.describe(found)


def test_web_search_reads_the_cited_pages(monkeypatch):
    client = llm.OpenAICompatible(api_key="k", model="gpt-4.1-mini")
    sent = []
    reply = {"output": [{"type": "web_search_call"}, {"type": "message", "content": [
        {"type": "output_text", "text": "Two good pieces.", "annotations": [
            {"type": "url_citation", "url": "https://www.quantamagazine.org/octopus-sleep", "title": "Octopus sleep"},
            {"type": "url_citation", "url": "https://www.quantamagazine.org/octopus-sleep", "title": "again"}]}]}]}

    def post(path, body, kind):
        sent.append((path, json.loads(body)))
        if json.loads(body)["tools"][0]["type"] == "web_search":
            raise llm.APIError("400 from /responses: unknown tool")     # an older account
        return json.dumps(reply).encode()

    monkeypatch.setattr(client, "_post", post)
    found = search.web(client, "octopus sleep long read")
    assert found == [{"title": "Octopus sleep", "url": "https://www.quantamagazine.org/octopus-sleep",
                      "about": "Two good pieces."}]
    assert [b["tools"][0]["type"] for _, b in sent] == ["web_search", "web_search_preview"]
    other = llm.OpenAICompatible(api_key="k", base_url="https://api.deepseek.com/v1")
    with pytest.raises(llm.APIError, match="needs the OpenAI API"):
        other.web_search("x")


def test_pdf_papers_are_read_without_their_references(tmp_path):
    raw = (ROOT / "tests" / "fixtures" / "paper.pdf").read_bytes()
    title, text = from_pdf(raw)
    assert title == "Sleep in Octopuses"
    assert "otherwise used for camouflage" in text                    # the hyphenated word is joined again
    assert text.count("\n\n") == 1 and "Medeiros" not in text          # two paragraphs, no references
    (tmp_path / "p.pdf").write_bytes(raw)
    assert load_article(str(tmp_path / "p.pdf"))[0] == "Sleep in Octopuses"


class ScriptedClient:
    """Answers the chat with the replies given, in order."""

    def __init__(self, *replies):
        self.replies, self.prompts = list(replies), []

    def chat_json(self, system, user, **_):
        self.prompts.append((system, user))
        return self.replies.pop(0)


class FakeBot:
    def __init__(self):
        self.sent = []

    def send(self, chat, text):
        self.sent.append(text)

    def typing(self, chat):
        pass


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("BIBLIOTHECARY_HOME", str(tmp_path / "lib"))
    return tmp_path / "lib"


def librarian(client, prepared):
    bot = FakeBot()
    def prepare(url):
        prepared.append(url)
        return library.new_reading(Lesson.load(ROOT / "examples" / "octopus.lesson.json"))

    lib = telegram.Librarian(bot, client, explain="Simplified Chinese", prepare=prepare)
    lib.handle({"message": {"chat": {"id": ME}, "text": f"/start {lib.pairing_code()}"}})
    bot.sent.clear()
    return lib, bot


def test_the_librarian_searches_before_suggesting(home, monkeypatch):
    found = [{"title": "Cyclic alternation of quiet and active sleep", "year": 2021, "venue": "iScience",
              "cited": 120, "url": "https://example.org/octopus.pdf", "about": ""}]
    asked = []
    monkeypatch.setattr(search, "papers", lambda q, prefer="any": (asked.append((q, prefer)), found)[1])
    client = ScriptedClient({"search": {"where": "papers", "query": "octopus sleep", "prefer": "classic"}},
                            {"reply": "1. 《Cyclic alternation…》2021，被引 120 次 https://example.org/octopus.pdf"},
                            {"reply": "好，就读这篇，我去备课。", "prepare": "https://example.org/octopus.pdf"})
    prepared = []
    lib, bot = librarian(client, prepared)
    lib.handle({"message": {"chat": {"id": ME}, "text": "帮我找一篇章鱼睡觉的经典论文"}})
    assert asked == [("octopus sleep", "classic")]
    assert "https://example.org/octopus.pdf" in client.prompts[1][1]           # the results reach the model
    assert "OpenAlex" in client.prompts[0][0] and "never invent one" in client.prompts[0][0]
    assert bot.sent[-1].startswith("1. 《Cyclic")
    lib.handle({"message": {"chat": {"id": ME}, "text": "就第一篇"}})
    for job in lib.jobs:
        job.join(5)
    assert bot.sent[-2] == "好，就读这篇，我去备课。" and prepared == ["https://example.org/octopus.pdf"]
    assert bot.sent[-1].startswith("备好了")


def test_an_invented_link_is_never_prepared(home):
    client = ScriptedClient({"reply": "读这个吧", "prepare": "https://made-up.example/paper"})
    prepared = []
    lib, bot = librarian(client, prepared)
    lib.handle({"message": {"chat": {"id": ME}, "text": "随便推荐一篇"}})
    assert prepared == [] and bot.sent[-1] == "读这个吧"


def test_searching_stops_after_the_limit(home, monkeypatch):
    monkeypatch.setattr(search, "web", lambda client, q: [])
    client = ScriptedClient(*[{"search": {"where": "web", "query": "x"}}] * 3, {"reply": "没找到合适的。"})
    lib, bot = librarian(client, [])
    lib.handle({"message": {"chat": {"id": ME}, "text": "找点散文"}})
    assert bot.sent[-1] == "没找到合适的。" and "No more searches" in client.prompts[-1][0]
    assert library.home() == home


def test_only_the_shelf_sites_are_searched_and_kept(home):
    class Client:
        def web_search(self, query, domains=None):
            self.domains = domains
            return {"text": "x", "sources": [
                {"title": "诺贝尔奖揭晓 股市", "url": "https://finance.sina.com.cn/stock/nobel.shtml"},
                {"title": "Popular information", "url": "https://www.nobelprize.org/prizes/physics/2025/popular-information/"},
                {"title": "lookalike", "url": "https://nobelprize.org.evil.example/x"}]}

    client = Client()
    found = search.web(client, "2025 Nobel Prize in Physics explained", "science")
    assert [r["url"] for r in found] == ["https://www.nobelprize.org/prizes/physics/2025/popular-information/"]
    assert "nobelprize.org" in client.domains and "quantamagazine.org" in client.domains
    assert not any("sina" in d for name in search.shelves() for d in search.shelves()[name]["sites"])
    with pytest.raises(search.SearchError, match="no shelf"):
        search.web(client, "x", "gossip")


def test_the_reader_can_change_the_collection(home):
    home.mkdir(parents=True)
    (home / "shelves.toml").write_text('[science]\nadd = ["sciencenews.org"]\nremove = ["newscientist.com"]\n\n'
                                       '[poetry]\nabout = "Poems"\nsites = ["poetryfoundation.org"]\n\n'
                                       '[books]\nsites = ["standardebooks.org"]\n', encoding="utf-8")
    shelves = search.shelves()
    assert "sciencenews.org" in shelves["science"]["sites"] and "newscientist.com" not in shelves["science"]["sites"]
    assert shelves["poetry"] == {"about": "Poems", "sites": ["poetryfoundation.org"]}
    assert shelves["books"]["sites"] == ["standardebooks.org"]


def test_web_search_sends_the_allowed_sites(monkeypatch):
    client = llm.OpenAICompatible(api_key="k", model="gpt-4.1-mini")
    sent = []
    monkeypatch.setattr(client, "_post", lambda path, body, kind: (sent.append(json.loads(body)), b'{"output": []}')[1])
    client.web_search("q", domains=["nobelprize.org"])
    assert sent[0]["tools"] == [{"type": "web_search", "filters": {"allowed_domains": ["nobelprize.org"]}}]


def test_classic_papers_must_be_well_cited():
    asked = []
    search.openalex("nobel", "classic", today=dt.date(2026, 10, 8),
                    get=lambda url: (asked.append(url), b'{"results": []}')[1])
    assert "cited_by_count%3A%3E99" in asked[0]


def test_the_chat_knows_the_shelves_and_searches_one(home, monkeypatch):
    shelves_seen = []
    monkeypatch.setattr(search, "web", lambda client, q, shelf: (shelves_seen.append(shelf), [])[1])
    client = ScriptedClient({"search": {"where": "web", "shelf": "science", "query": "Nobel Prize physics 2025"}},
                            {"reply": "没找到够好的，换个方向？"})
    lib, _bot = librarian(client, [])
    lib.handle({"message": {"chat": {"id": ME}, "text": "我对诺贝尔奖感兴趣"}})
    assert shelves_seen == ["science"]
    system = client.prompts[0][0]
    assert "science: Science explained well" in system and "nobelprize.org's popular" in system
    assert "finance" in system                                     # told what never to offer
