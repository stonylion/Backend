#생성된 동화를 페이지별로 나누는 공통 로직
import re

def split_into_pages_classic(text: str):
    if not text:
        return []

    sentences = re.split(r'\n+', text.strip())
    sentences = [s.strip() for s in sentences if s.strip()]

    pages = []
    buffer = []
    idx = 0

    while idx < len(sentences):
        candidates = sentences[idx:idx+3]

        placed = False
        for count in [3, 2, 1]:
            if len(candidates) >= count:
                chunk = " ".join(candidates[:count])
                if len(chunk) <= 70:
                    pages.append(chunk)
                    idx += count
                    placed = True
                    break

        if not placed:
            pages.append(candidates[0])
            idx += 1

    return pages

def split_into_pages(text: str):
    if not text:
        return []

    sentences = re.split(r'(?<=[.!?"]) +', text.strip())
    sentences = [s.strip() for s in sentences if s.strip()]

    pages = []
    idx = 0
    max_len = 70

    while idx < len(sentences):
        candidates = sentences[idx:idx+3]
        placed = False

        for count in [3, 2, 1]:
            if len(candidates) >= count:
                chunk = " ".join(candidates[:count])

                if len(chunk) <= max_len:
                    pages.append(chunk)
                    idx += count
                    placed = True
                    break

        if not placed:
            single = candidates[0]
            pages.append(single)
            idx += 1

    return pages