import json
import base64
import torch
import tempfile
from faster_whisper import WhisperModel
from channels.generic.websocket import AsyncWebsocketConsumer
from asgiref.sync import sync_to_async

# Whisper 모델 로드 (서버 시작 시 1회 로드)
model = WhisperModel("base", device="cpu")

class AudioTranscriptionConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        await self.accept()
        self.sequence_counter = 0
        print("🟢 WebSocket connected")

    async def disconnect(self, close_code):
        print("🔴 WebSocket disconnected")

    async def receive(self, text_data):
        try:
            data = json.loads(text_data)
            event = data.get("event")

            if event == "audio_chunk":
                await self.handle_audio_chunk(data)

            elif event == "stop":
                await self.handle_stop()

            else:
                await self.send(json.dumps({
                    "event": "error",
                    "message": "Invalid event type"
                }))
        except Exception as e:
            await self.send(json.dumps({
                "event": "error",
                "message": str(e)
            }))

    async def handle_audio_chunk(self, data):
        """
        Client → Server: audio_chunk 이벤트
        base64 인코딩된 오디오를 Whisper로 변환
        """
        audio_base64 = data.get("data")
        sequence = data.get("sequence", 0)

        if not audio_base64:
            await self.send(json.dumps({
                "event": "error",
                "message": "Missing audio data"
            }))
            return

        try:
            # base64 → wav 파일
            audio_bytes = base64.b64decode(audio_base64)
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                tmp.write(audio_bytes)
                tmp.flush()

                # 변환 수행 (비동기)
                segments, info = model.transcribe(tmp.name, language="ko")

                transcript = " ".join([segment.text.strip() for segment in segments])

            await self.send(json.dumps({
                "event": "partial_transcript",
                "text": transcript,
                "sequence": sequence
            }))

        except Exception as e:
            await self.send(json.dumps({
                "event": "error",
                "message": f"Failed to process audio: {str(e)}"
            }))

    async def handle_stop(self):
        """
        Client → Server: stop 이벤트
        최종 결과 전송 후 연결 종료
        """
        await self.send(json.dumps({
            "event": "final_transcript",
            "text": "옛날 옛적에 여우와 두루미가 살았어요."
        }))
        await self.close()
