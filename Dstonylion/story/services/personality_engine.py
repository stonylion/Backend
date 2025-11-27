import re
from datetime import timedelta
from django.utils import timezone
from AI.models import Message, ExtendMessage

# ---------------------------
# 1) LEXICON
# ---------------------------

LEXICON = {
    "E": {
        "사회성_high": ["친구", "같이", "함께", "우리", "사람들", "놀자", "이야기했어"],
        "사회성_low": ["혼자", "조용히", "혼자 있고 싶어", "말 안 해"],

        "지배성_high": ["내가 할게", "내가 먼저", "이끌어", "주도", "결정했어"],
        "지배성_low": ["네가 해", "따라갈게", "맡길게", "안 나설래"],

        "자극추구_high": ["재밌어", "신나", "우와", "모험", "더 해보자"],
        "자극추구_low": ["그냥", "지루해", "무서워", "안 할래"]
    },

    "O": {
        "창의성_high": ["상상", "아이디어", "새로운", "다르게", "이야기 만들어"],
        "창의성_low": ["그냥 그대로", "몰라", "똑같아"],

        "정서성_high": ["감동", "설레", "예뻐", "기뻐", "따뜻해"],
        "정서성_low": ["재미없어", "별로", "심심"],

        "사고유연성_high": ["왜냐하면", "그래서", "혹시", "예를 들면"],
        "사고유연성_low": ["그냥 그래", "싫어", "안 돼", "무조건"]
    },

    "A": {
        "온정성_high": ["도와줄게", "괜찮아", "힘내", "고마워", "같이 하자"],
        "온정성_low": ["싫어", "안 도와줘", "내 거야"],

        "신뢰성_high": ["믿어", "착해", "괜찮아 그럴 수 있어"],
        "신뢰성_low": ["거짓말", "못 믿어", "수상해"],

        "관용성_high": ["용서해", "실수야", "넘어가자"],
        "관용성_low": ["용서 못 해", "왜 그랬어", "화나"]
    },

    "C": {
        "유능감_high": ["할 수 있어", "됐다", "해냈어", "자신 있어"],
        "유능감_low": ["못하겠어", "어려워", "자신 없어"],

        "조직성_high": ["먼저", "그다음", "정리해", "순서", "차근차근"],
        "조직성_low": ["대충", "아무렇게나", "귀찮아"],

        "책임감_high": ["약속", "지켜야 해", "숙제", "책임"],
        "책임감_low": ["까먹었어", "미뤘어", "나중에"]
    },

    "N": {
        "불안_high": ["무서워", "걱정돼", "불안해", "초조해"],
        "불안_low": ["괜찮아", "안 무서워", "침착해"],

        "적대감_high": ["싫어", "짜증", "미워", "화나"],
        "적대감_low": ["괜찮아", "참을 수 있어"],

        "우울_high": ["우울해", "슬퍼", "외로워"],
        "우울_low": ["행복해", "좋아", "기뻐"],

        "충동성_high": ["갑자기", "막", "확"],
        "충동성_low": ["천천히", "기다릴게", "생각하고"],

        "사회적위축_high": ["부끄러워", "어색해", "불편해", "말 못해"],
        "사회적위축_low": ["편해", "친해지고 싶어"],

        "정서충격_high": ["못해", "쓸모없어", "가치 없어"],
        "정서충격_low": ["나는 소중해", "괜찮아", "할 수 있어"]
    }
}

PER100_THRESHOLD = 5.0
DIFF_RATIO_THRESHOLD = 0.3


# ---------------------------
# 2) 유틸
# ---------------------------

def tokenize_korean(text: str):
    return re.findall(r"[가-힣A-Za-z0-9]+", text)


def per100(count: int, total: int):
    return count / max(1, total / 100.0)


def count_occ(text: str, words: list[str]):
    c = 0
    for w in words:
        c += text.count(w)
    return c


# ---------------------------
# 3) NEO 성격 분석 메인 함수
# ---------------------------

def predict_personality_with_adjustment(utterances: list[str]):
    text = "\n".join(utterances)
    tokens = tokenize_korean(text)
    total_tokens = len(tokens)

    result = {}
    rationale = {}

    for factor, lex in LEXICON.items():
        sub_names = sorted(set(k.split("_")[0] for k in lex.keys()))
        sub_verdicts = {}
        sub_stats = {}

        for sub in sub_names:
            high_words = lex.get(f"{sub}_high", [])
            low_words = lex.get(f"{sub}_low", [])

            high_count = count_occ(text, high_words)
            low_count = count_occ(text, low_words)

            high_per = per100(high_count, total_tokens)
            low_per = per100(low_count, total_tokens)

            # -------------------
            # 하위요인 판정
            # -------------------
            if high_per < PER100_THRESHOLD and low_per < PER100_THRESHOLD:
                verdict_sub = "판정유보"

            elif high_per >= PER100_THRESHOLD and low_per >= PER100_THRESHOLD:
                if high_per >= low_per * (1 + DIFF_RATIO_THRESHOLD):
                    verdict_sub = "높다"
                elif low_per >= high_per * (1 + DIFF_RATIO_THRESHOLD):
                    verdict_sub = "낮다"
                else:
                    verdict_sub = "판정유보"

            elif high_per >= PER100_THRESHOLD:
                verdict_sub = "높다"
            elif low_per >= PER100_THRESHOLD:
                verdict_sub = "낮다"
            else:
                verdict_sub = "판정유보"

            sub_verdicts[sub] = verdict_sub
            sub_stats[sub] = {
                "high_per100": round(high_per, 2),
                "low_per100": round(low_per, 2),
                "high_count": high_count,
                "low_count": low_count
            }

        # -------------------
        # 상위요인 판정
        # -------------------
        num_high = sum(1 for v in sub_verdicts.values() if v == "높다")
        num_low = sum(1 for v in sub_verdicts.values() if v == "낮다")
        num_valid = num_high + num_low

        if num_valid == 0:
            factor_verdict = "판정유보"
        else:
            if factor == "N":
                if num_high >= 4:
                    factor_verdict = "높다"
                elif num_low >= 4:
                    factor_verdict = "낮다"
                else:
                    factor_verdict = "판정유보"
            else:
                if num_high >= 2:
                    factor_verdict = "높다"
                elif num_low >= 2:
                    factor_verdict = "낮다"
                else:
                    factor_verdict = "판정유보"

        result[factor] = factor_verdict
        rationale[factor] = {
            "하위요인_판정": sub_verdicts,
            "하위요인별_100토큰당_비율": {
                sub: {"high": s["high_per100"], "low": s["low_per100"]}
                for sub, s in sub_stats.items()
            },
            "하위요인별_카운트": {
                sub: {"high": s["high_count"], "low": s["low_count"]}
                for sub, s in sub_stats.items()
            }
        }

    return result, rationale
