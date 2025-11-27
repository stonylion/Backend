import math
from collections import Counter
from datetime import timedelta
from django.utils import timezone

from AI.models import Message, ExtendMessage


# -----------------------------------------------------
# STOPWORDS
# -----------------------------------------------------
KOREAN_STOPWORDS = {
    '이', '가', '을', '를', '은', '는', '도', '만', '에게', '한테', '와', '과', '랑',
    '처럼', '에서', '으로', '로', '하고', '있어요', '했어요', '이에요', '예요',
    '합니다', '한다', '했다', '것', '할', '수', '수도', '것을', '것이', '그',
    '이것', '저것', '다시', '근데', '너무', '아주', '많이', '되었어요', '돼요',
}


# -----------------------------------------------------
# LEVEL DEFINITION
# -----------------------------------------------------
NDW_LEVELS = [
    {
        "level": 3,
        "threshold": 65,
        "title": "다채로운 스토리텔러",
        "description": "또래의 어휘 활용 경향을 뛰어넘는 폭넓은 표현력을 보입니다. 다양한 단어를 자유롭게 사용해요."
    },
    {
        "level": 2,
        "threshold": 55,
        "title": "노력하는 이야기꾼",
        "description": "이야기 주제에 맞는 내용어를 안정적으로 사용하며, 또래와 유사한 수준입니다."
    },
    {
        "level": 1,
        "threshold": 0,
        "title": "초보 이야기 정원사",
        "description": "주요 단어 반복이 잦으며, 친숙한 어휘를 기반으로 표현하고 있어요."
    },
]


# -----------------------------------------------------
# TOKENIZE
# -----------------------------------------------------
def tokenize_and_filter(text):
    raw_tokens = [w.strip() for w in text.split() if w.strip()]
    filtered = []

    for t in raw_tokens:
        if t in KOREAN_STOPWORDS:
            continue

        # 조사/어미 제거
        token = (
            t.removesuffix("가요").removesuffix("이요")
             .removesuffix("어요").removesuffix("에요")
             .removesuffix("은").removesuffix("는")
             .removesuffix("이").removesuffix("가")
        )

        if token and token not in KOREAN_STOPWORDS:
            filtered.append(token.lower())

    return filtered


# -----------------------------------------------------
# GET LEVEL — MONTHLY
# -----------------------------------------------------
def get_level_info_monthly(avg_ndw):
    month_adjust = 0.95  # 월간은 조금 더 완화

    for lvl in NDW_LEVELS:
        if avg_ndw >= math.ceil(lvl["threshold"] * month_adjust):
            return {
                "title": lvl["title"],
                "level_number": f"Level {lvl['level']}",
                "description": lvl["description"]
            }

    # 안전장치
    return {
        "title": NDW_LEVELS[-1]["title"],
        "level_number": f"Level {NDW_LEVELS[-1]['level']}",
        "description": NDW_LEVELS[-1]["description"]
    }


# -----------------------------------------------------
# GET LEVEL — STORY
# -----------------------------------------------------
def get_level_info_story(ndw_score):
    for lvl in NDW_LEVELS:
        if ndw_score >= lvl["threshold"]:
            return {
                "title": lvl["title"],
                "level_number": f"Level {lvl['level']}",
                "description": lvl["description"]
            }

    return {
        "title": NDW_LEVELS[-1]["title"],
        "level_number": f"Level {NDW_LEVELS[-1]['level']}",
        "description": NDW_LEVELS[-1]["description"]
    }


# -----------------------------------------------------
# MONTHLY NDW
# -----------------------------------------------------
def calculate_ndw_for_month(user, days=30):
    now = timezone.now()
    start_date = now - timedelta(days=days)

    # 기본 메시지
    base_msgs = Message.objects.filter(
        sender="user",
        timestamp__gte=start_date,
        story__user=user
    ).values_list("text", flat=True)

    # 확장 메시지
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

    # 레벨 계산
    level_info = get_level_info_monthly(ndw_score)

    return {
        "period": {
            "start": start_date.date().isoformat(),
            "end": now.date().isoformat(),
            "days": days,
            "total_user_messages": len(utterances),
        },
        "stats": {
            "avg_total_tokens": token_count,
            "avg_ndw": ndw_score,
        },
        "top_words": token_freq.most_common(5),
        "level": level_info
    }


# -----------------------------------------------------
# STORY NDW
# -----------------------------------------------------
def calculate_ndw_for_story(user, story_id):
    base_msgs = Message.objects.filter(
        sender="user",
        story_id=story_id,
        story__user=user
    ).values_list("text", flat=True)

    extend_msgs = ExtendMessage.objects.filter(
        role="user",
        chat__story_id=story_id,
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

    level_info = get_level_info_story(ndw_score)

    return {
        "stats": {
            "total_tokens": token_count,
            "ndw": ndw_score,
        },
        "top_words": token_freq.most_common(5),
        "level": level_info,
        "utterance_count": len(utterances)
    }
