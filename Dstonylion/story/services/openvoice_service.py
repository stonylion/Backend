# openvoice_service.py
import os
from django.conf import settings

_device = None

def get_device():
    global _device
    if _device is None:
        import torch
        _device = "cuda:0" if torch.cuda.is_available() else "cpu"
    return _device


# -------------------------------------------------------------------
# ① 공용 경로 설정
# -------------------------------------------------------------------
BASE_DIR = settings.BASE_DIR
_CONVERTER_DIR = os.path.join(BASE_DIR, "checkpoints_v2", "converter")


# -------------------------------------------------------------------
# ② Lazy Loader – 필요한 순간에만 초기화함
# -------------------------------------------------------------------
_tts_cache = {}
_tone_converter = None


def clone_voice(source_audio_path, reference_audio_path, base_speaker_se_path, output_path):
    from openvoice import se_extractor
    import torch

    device = get_device()

    # ToneColorConverter 로드
    converter = get_tone_converter()

    # reference audio → target SE
    target_se, _ = se_extractor.get_se(reference_audio_path, converter, vad=True)

    # base speaker SE 로드
    source_se = torch.load(base_speaker_se_path, map_location=device)

    # 변환 수행
    converter.convert(
        audio_src_path=source_audio_path,
        src_se=source_se,
        tgt_se=target_se,
        output_path=output_path,
        message="@MyShell"
    )

    return output_path, target_se


def get_tts(language: str):
    """TTS 모델을 1번만 로드해서 캐싱."""
    from melo.api import TTS
    device = get_device()
    if language not in _tts_cache:
        _tts_cache[language] = TTS(language=language, device=device)
    return _tts_cache[language]


def get_tone_converter():
    """ToneColorConverter 모델을 전역에서 1번만 로드."""
    global _tone_converter
    if _tone_converter is None:
        from openvoice.api import ToneColorConverter
        device = get_device()

        config = os.path.join(_CONVERTER_DIR, "config.json")
        ckpt = os.path.join(_CONVERTER_DIR, "checkpoint.pth")

        converter = ToneColorConverter(config, device=device)
        converter.load_ckpt(ckpt)
        _tone_converter = converter

    return _tone_converter


# -------------------------------------------------------------------
# ③ 기본 TTS (기본 화자 음성)
# -------------------------------------------------------------------
def generate_tts(language: str, text: str, output_path: str, speed: float = 1.0):
    model = get_tts(language)
    speaker_ids = model.hps.data.spk2id
    speaker_id = list(speaker_ids.values())[0]

    model.tts_to_file(text, speaker_id, output_path, speed=speed)
    return output_path


# -------------------------------------------------------------------
# ④ 사용자 음색 적용 (Voice Cloning)
# -------------------------------------------------------------------
def convert_voice(base_audio_path, target_se, output_path, base_se):
    converter = get_tone_converter()

    converter.convert(
        audio_src_path=base_audio_path,
        src_se=base_se,
        tgt_se=target_se,
        output_path=output_path,
        message="@MyShell"
    )
    return output_path


def extract_se(reference_audio_path, base_se_path):
    """
    사용자 참고 음성에서 SE 벡터 추출
    """
    from openvoice import se_extractor
    import torch

    device = get_device()
    converter = get_tone_converter()

    target_se, _ = se_extractor.get_se(reference_audio_path, converter, vad=True)
    base_se = torch.load(base_se_path, map_location=device)
    
    return target_se, base_se
