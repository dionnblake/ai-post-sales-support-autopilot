"""Small, inspectable lexical RAG over original Markdown sections."""
import hashlib
import math
import re
from collections import Counter
from pathlib import Path

STOP = set("a an and are as at be been but by can could do does for from have how i if in is it me my of on or our please so that the their there these this to us we what when where which with would you your help support need want get".split())


def tokens(text):
    return [word[:-1] if len(word) > 4 and word.endswith("s") else word
            for word in re.findall(r"[a-z0-9]+", text.lower()) if word not in STOP]


class KnowledgeError(ValueError):
    pass


class KnowledgeBase:
    def __init__(self, directory):
        self.directory = Path(directory).resolve()
        self.chunks = []
        digest = hashlib.sha256()
        for path in sorted(self.directory.glob("*.md")):
            if path.is_symlink() or not path.resolve().is_relative_to(self.directory):
                raise KnowledgeError("Knowledge files must remain within the KB directory")
            raw = path.read_bytes()
            if len(raw) > 100_000:
                raise KnowledgeError("Knowledge document exceeds the demo size limit")
            digest.update(path.name.encode() + b"\0" + raw)
            sections = re.split(r"^## ", raw.decode("utf-8"), flags=re.MULTILINE)[1:]
            for index, section in enumerate(sections, 1):
                title, _, text = section.partition("\n")
                if text.strip():
                    self.chunks.append({"id": f"{path.stem}-{index}", "source": path.name,
                                        "title": title.strip(), "text": text.strip()})
        if not self.chunks:
            raise KnowledgeError("No Markdown knowledge sections found")
        self.digest = digest.hexdigest()

    def search(self, query, limit=3):
        query_terms = set(tokens(query))
        if not query_terms:
            return []
        documents = [Counter(tokens(chunk["title"] + " " + chunk["text"])) for chunk in self.chunks]
        ranked = []
        for chunk, terms in zip(self.chunks, documents):
            matches = query_terms & terms.keys()
            if len(matches) < min(2, len(query_terms)):
                continue
            score = sum((1 + math.log(terms[word])) * math.log(1 + len(documents) /
                        (1 + sum(word in doc for doc in documents))) for word in matches)
            ranked.append(dict(chunk, score=round(score, 4)))
        return sorted(ranked, key=lambda item: (-item["score"], item["id"]))[:max(0, min(limit, 3))]
