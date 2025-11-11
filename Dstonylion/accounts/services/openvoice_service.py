import os
import torch
from openvoice import se_extractor
from openvoice.api import ToneColorConverter
from melo.api import TTS
import uuid

class OpenVoiceService:
    def __init__(self):
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.ckpt_path = "checkpoints_v2"
        self.speaker_encoder = se_extractor.get_model(
            model_path=os.path.join(self.ckpt_path, "base_speaker_encoder.pth")
        )
        self.converter = ToneColorConverter(
            os.path.join(self.ckpt_path, "converter.pth"),
            device=self.device
        )
        self.tts = TTS(language="KO", device=self.device)

    def clone_and_tts(self, source_path: str, text: str, output_dir="media/voices", emotion="calm", language="ko"):
        """
        1. 업로드된 음성의 tone color 추출
        2. 추출된 tone color로 TTS 생성
        """
        os.makedirs(output_dir, exist_ok=True)
        output_path = os.path.join(output_dir, f"cloned_{uuid.uuid4().hex[:6]}.wav")

        # 음색 정보 추출
        tone_color = self.speaker_encoder.extract(source_path)

        # TTS 실행
        self.tts.tts_to_file(
            text,
            file_path=output_path,
            speaker=tone_color,
            emotion=emotion,
            language=language.upper()
        )

        return output_path
