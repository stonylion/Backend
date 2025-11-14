#생성된 동화를 페이지별로 나누는 공통 로직
import re

def split_into_pages(text: str, sentences_per_page: int = 3):
    if not text:
        return []

    sentences = re.split(r'(?<=[.!?])\s+', text.strip())

    pages = []
    buffer = []

    for s in sentences:
        if not s:
            continue

        buffer.append(s.strip())

        if len(buffer) == sentences_per_page:
            pages.append(" ".join(buffer))
            buffer = []

    if buffer:
        pages.append(" ".join(buffer))

    return pages
