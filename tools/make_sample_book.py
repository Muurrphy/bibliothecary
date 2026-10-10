"""Rebuild the sample book: Seneca, On the Shortness of Life, from Standard Ebooks.

    python tools/make_sample_book.py

Standard Ebooks' text is public domain and its own work is dedicated to the public domain (CC0),
so the one dialogue can be taken out of their "Dialogues" and shipped with this project.
"""

import re
import sys
import urllib.request
import zipfile
from io import BytesIO
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from bibliothecary import bookfile  # noqa: E402

URL = ("https://standardebooks.org/ebooks/seneca/dialogues/aubrey-stewart/downloads/"
       "seneca_dialogues_aubrey-stewart.epub?source=download")
OUT = ROOT / "src" / "bibliothecary" / "samples" / "seneca-on-the-shortness-of-life.epub"
RIGHTS = ("Seneca, On the Shortness of Life, translated by Aubrey Stewart (1900): public domain. "
          "Ebook text from Standard Ebooks (standardebooks.org), whose work is dedicated to the public domain "
          "under CC0 1.0. This file was made from it by Bibliothecary and is also dedicated to the public domain.")


def main() -> None:
    req = urllib.request.Request(URL, headers={"User-Agent": "Bibliothecary sample builder"})
    data = urllib.request.urlopen(req, timeout=120).read()
    with zipfile.ZipFile(BytesIO(data)) as z:
        markup = z.read("epub/text/on-the-shortness-of-life.xhtml").decode("utf-8")
    markup = re.sub(r"<header>[\s\S]*?</header>", "", markup)                 # title and "To Paulinus." note
    markup = re.sub(r'<a [^>]*epub:type="noteref"[^>]*>[\s\S]*?</a>', "", markup)
    chapters = bookfile.chapters_from_html(markup, level="h3")
    parsed = bookfile.Parsed("On the Shortness of Life", "Seneca", "en-GB", chapters)
    bookfile.write_epub(OUT, parsed, rights=RIGHTS,
                        source="https://standardebooks.org/ebooks/seneca/dialogues/aubrey-stewart")
    print(f"{OUT.relative_to(ROOT)}: {len(chapters)} chapters, {sum(c.size for c in chapters)} characters")


if __name__ == "__main__":
    main()
