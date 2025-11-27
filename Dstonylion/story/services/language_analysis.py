# story/services/language_analysis.py
import math
from collections import Counter
from datetime import timedelta
from django.utils import timezone

from AI.models import Message, ExtendMessage


KOREAN_STOPWORDS = {
    '이', '가', '을', '를', '은', '는', '도', '만', '에게', '한테', '와', '과', '랑',
    '처럼', '에서', '으로', '로', '하고', '있어요', '했어요', '이에요', '예요',
    '합니다', '한다', '했다', '것', '할', '수', '수도', '것을', '것이', '그',
    '이것', '저것', '다시', '근데', '너무', '아주', '많이', '되었어요', '돼요',
}


NDW_LEVELS = [
    (65, "다채로운 스토리텔러",
     "또래의 어휘 활용 경향을 뛰어넘는 폭넓은 표현력을 보입니다. 다양한 단어를 자유롭게 사용해요."),
    (55, "노력하는 이야기꾼",
     "이야기 주제에 맞는 내용어를 안정적으로 사용하며, 또래와 유사한 수준입니다."),
    (0, "초보 이야기 정원사",
     "주요 단어 반복이 잦으며, 친숙한 어휘를 기반으로 표현하고 있어요."),
]


def tokenize_and_filter(text):
    """토큰화 + 기능어 필터링."""
    raw_tokens = [w.strip() for w in text.split() if w.strip()]
    filtered = []

    for t in raw_tokens:
        if t in KOREAN_STOPWORDS:
            continue

        # 어미/조사 제거
        token = (
            t.removesuffix("가요").removesuffix("이요")
             .removesuffix("어요").removesuffix("에요")
             .removesuffix("은").removesuffix("는")
             .removesuffix("이").removesuffix("가")
        )

        if token and token not in KOREAN_STOPWORDS:
            filtered.append(token.lower())

    return filtered


def calculate_ndw_for_month(user, days=30):
    """
    최근 days일 동안 user 메시지를 모두 모아 NDW 계산.
    """

    now = timezone.now()
    start_date = now - timedelta(days=days)

    # Message(sender="user")
    base_msgs = Message.objects.filter(
        sender="user",
        timestamp__gte=start_date,
        story__user=user
    ).values_list("text", flat=True)

    # ExtendMessage(role="user")
    extend_msgs = ExtendMessage.objects.filter(
        role="user",
        created_at__gte=start_date,
        chat__user=user
    ).values_list("content", flat=True)

    utterances = list(base_msgs) + list(extend_msgs)

    if not utterances:
        return None

    full_text = " ".join(utterances)

    tokens = tokenize_and_filter(full_text)
    token_count = len(tokens)
    ndw_score = len(set(tokens))

    token_freq = Counter(tokens)

    avg_tokens = token_count  # 월 전체 기준 → “평균”은 세션 수 없으니 그대로 반환
    avg_ndw = ndw_score

    # 레벨 적용
    month_adjust = 0.95
    for threshold, title, desc in NDW_LEVELS:
        if avg_ndw >= math.ceil(threshold * month_adjust):
            level_info = {
                "title": title,
                "level_number": f"Level {NDW_LEVELS.index((threshold, title, desc)) + 1}",
                "description": desc
            }
            break

    return {
        "period": {
            "start": start_date.date().isoformat(),
            "end": now.date().isoformat(),
            "days": days,
            "total_user_messages": len(utterances),
        },
        "stats": {
            "avg_total_tokens": token_count,
            "avg_ndw": avg_ndw,
        },
        "top_words": token_freq.most_common(5),
        "level": level_info
    }

def calculate_ndw_for_story(user, story_id):
    """
    특정 동화(story_id)에 대한 내용어 기반 NDW 분석.
    """
    # 1) Message(sender=user)
    base_msgs = Message.objects.filter(
        sender="user",
        story_id=story_id,
        story__user=user
    ).values_list("text", flat=True)

    # 2) ExtendMessage(role=user, chat__story_id=story_id)
    extend_msgs = ExtendMessage.objects.filter(
        role="user",
        chat__story_id=story_id,
        chat__user=user
    ).values_list("content", flat=True)

    utterances = list(base_msgs) + list(extend_msgs)

    if not utterances:
        return None

    # 전체 텍스트 합치기
    full_text = " ".join(utterances)

    tokens = tokenize_and_filter(full_text)
    token_count = len(tokens)
    ndw_score = len(set(tokens))
    token_freq = Counter(tokens)

    # 레벨 분류 → session 기준 (monthly와 약간 다르게 조정 없이)
    for threshold, title, desc in NDW_LEVELS:
        if ndw_score >= threshold:
            level_info = {
                "title": title,
                "level_number": f"Level {NDW_LEVELS.index((threshold, title, desc)) + 1}",
                "description": desc
            }
            break

    return {
        "stats": {
            "total_tokens": token_count,
            "ndw": ndw_score,
        },
        "top_words": token_freq.most_common(5),
        "level": level_info,
        "utterance_count": len(utterances)
    }