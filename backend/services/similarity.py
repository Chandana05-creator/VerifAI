"""VerifAI — backend/services/similarity.py
Text-overlap helpers used by the plagiarism checker (word w-shingling + containment)."""
import re

_WORD = re.compile(r"[a-z0-9\u0900-\u097f\u0c80-\u0cff']+")      # Latin, Devanagari and Kannada letters
_SENT_END = re.compile(r"(?<=[.!?\u0964])\s+|\n{2,}")            # . ! ? । or a blank line
SHINGLE_N = 5


def tokens(text: str) -> list[str]:
    return _WORD.findall(text.lower())


def shingles(toks: list[str], n: int = SHINGLE_N) -> set[tuple]:
    if len(toks) < n:
        return set()
    return {tuple(toks[i:i + n]) for i in range(len(toks) - n + 1)}


def containment(chunk_tokens: list[str], doc_shingles: set[tuple], n: int = SHINGLE_N) -> float:
    """Fraction of the chunk's n-word sequences that also appear in the document (0..1)."""
    chunk_sh = shingles(chunk_tokens, n)
    if not chunk_sh or not doc_shingles:
        return 0.0
    return len(chunk_sh & doc_shingles) / len(chunk_sh)


def sentence_spans(text: str) -> list[tuple[int, int]]:
    """Character spans (start, end) of the sentences in `text`, covering all non-blank text."""
    spans, pos = [], 0
    for m in _SENT_END.finditer(text):
        if text[pos:m.start()].strip():
            spans.append((pos, m.start()))
        pos = m.end()
    if text[pos:].strip():
        spans.append((pos, len(text)))
    return spans


def make_chunks(text: str, min_words: int = 18, max_words: int = 45) -> list[dict]:
    """Group consecutive sentences into passages of roughly min_words..max_words words."""
    chunks, cur_start, cur_end, cur_words = [], None, None, 0
    for s, e in sentence_spans(text):
        w = len(tokens(text[s:e]))
        if cur_start is None:
            cur_start, cur_end, cur_words = s, e, w
        elif cur_words < min_words and cur_words + w <= max_words:
            cur_end, cur_words = e, cur_words + w
        else:
            chunks.append({"start": cur_start, "end": cur_end, "words": cur_words})
            cur_start, cur_end, cur_words = s, e, w
    if cur_start is not None:
        chunks.append({"start": cur_start, "end": cur_end, "words": cur_words})
    for c in chunks:
        c["text"] = text[c["start"]:c["end"]]
    return chunks
