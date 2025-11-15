import os
import torch
from melo.api import TTS
from openvoice import se_extractor
from openvoice.api import ToneColorConverter


device = "cuda:0" if torch.cuda.is_available() else "cpu"

# Dstonylion 기준이 아니라 Backend 기준으로 BASE_DIR 지정
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
_ckpt_converter = os.path.join(BASE_DIR, "checkpoints_v2", "converter")

print("Converter path:", _ckpt_converter)

tone_color_converter = ToneColorConverter(
    os.path.join(_ckpt_converter, "config.json"),
    device=device
)
tone_color_converter.load_ckpt(os.path.join(_ckpt_converter, "checkpoint.pth"))


def generate_tts(language: str, text: str, output_path: str, speed: float = 1.0):
    """
    텍스트를 지정한 언어의 기본 화자 목소리로 TTS 변환.
    """
    device = "cuda:0" if torch.cuda.is_available() else "cpu"
    model = TTS(language=language, device=device)
    speaker_ids = model.hps.data.spk2id

    # 기본 화자 선택 (첫 번째)
    first_speaker = list(speaker_ids.keys())[0]
    speaker_id = speaker_ids[first_speaker]

    # 음성 합성
    model.tts_to_file(text, speaker_id, output_path, speed=speed)

    return output_path


def clone_voice(source_audio_path, reference_audio_path, base_speaker_se_path, output_path):
    target_se, _ = se_extractor.get_se(reference_audio_path, tone_color_converter, vad=True)
    source_se = torch.load(base_speaker_se_path, map_location=device)

    tone_color_converter.convert(
        audio_src_path=source_audio_path,
        src_se=source_se,
        tgt_se=target_se,
        output_path=output_path,
        message="@MyShell"
    )
    return output_path, target_se 

