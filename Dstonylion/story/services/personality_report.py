NARRATIVE = {
    "E": {
        "사회성": "또래와 함께하는 활동을 즐기고 상호작용에서 에너지를 얻는 모습이 나타납니다.",
        "지배성": "상황을 주도하거나 자기 의견을 표현하려는 경향이 보입니다.",
        "자극추구": "새로운 자극과 흥미로운 활동에 적극적으로 참여하려는 모습이 있습니다."
    },
    "O": {
        "창의성": "상상력과 창의적 표현이 자주 나타나며 새로운 아이디어를 즐깁니다.",
        "정서성": "정서적 자극에 민감하고 아름다움·감정 표현에 반응합니다.",
        "사고유연성": "이유 제시·예시·추론 등 유연한 사고 경향이 확인됩니다."
    },
    "A": {
        "온정성": "타인을 돕거나 배려하는 표현이 자주 나타납니다.",
        "신뢰성": "타인을 긍정적으로 해석하고 신뢰하려는 경향이 있습니다.",
        "관용성": "상대의 실수를 이해하고 넘어가려는 태도가 관찰됩니다."
    },
    "C": {
        "유능감": "‘할 수 있어’, ‘해냈어’ 등의 자기 효능감이 표현됩니다.",
        "조직성": "순서·계획·정리 등 체계적 수행 경향이 보입니다.",
        "책임감": "약속·숙제·책임 관련 표현이 꾸준히 나타납니다."
    },
    "N": {
        "불안": "불안·걱정이 적어 정서적 안정성이 나타납니다.",
        "적대감": "감정 조절이 잘 이루어지고 부정적 표현이 적습니다.",
        "우울": "슬픔·외로움보다 긍정 표현이 많아 정서 회복력이 있습니다.",
        "충동성": "충동적 행동보다 조절과 기다림이 관찰됩니다.",
        "사회적위축": "사회적 상황을 편안히 받아들이는 태도가 보입니다.",
        "정서충격": "부정적 자기평가 표현이 적어 자존감 안정이 나타납니다."
    }
}


def generate_personality_report(result, rationale):
    """
    GUI에서 필요로 하는 구조화된 JSON 형태의 리포트 생성
    (문단 텍스트가 아니라 factor별 verdict + subs 리스트 구조)
    """

    report = {}

    for factor in ["E", "O", "A", "C", "N"]:
        verdict = result[factor]
        subs_raw = rationale[factor]["하위요인_판정"]

        factor_data = {
            "verdict": verdict,
            "subs": []
        }

        # 하위요인 리스트 생성
        for sub_name, sub_verdict in subs_raw.items():
            narrative = None

            # E/O/A/C → "높다"일 때만 narrative 사용
            if factor in ["E", "O", "A", "C"] and verdict == "높다" and sub_verdict != "판정유보":
                narrative = NARRATIVE.get(factor, {}).get(sub_name)

            # N → "낮다"일 때만 narrative 사용
            if factor == "N" and verdict == "낮다" and sub_verdict != "판정유보":
                narrative = NARRATIVE.get(factor, {}).get(sub_name)

            factor_data["subs"].append({
                "name": sub_name,
                "verdict": sub_verdict,
                "narrative": narrative  # 판정유보이면 None
            })

        report[factor] = factor_data

    return report
