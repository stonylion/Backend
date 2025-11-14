import json, os, re
import redis
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.contrib.auth import get_user_model
from django.conf import settings
from dotenv import load_dotenv
import aiofiles
import tempfile
import openai
import asyncio
from rest_framework_simplejwt.tokens import AccessToken

load_dotenv(settings.BASE_DIR/ ".env")
openai.api_key = os.getenv("OPENAI_API_KEY")
User = get_user_model()

class DraftConsumer(AsyncWebsocketConsumer):
    
    @database_sync_to_async
    def get_user_from_token(self, user_id):
        try:
            return User.objects.get(id=user_id)
        except User.DoesNotExist:
            return None

    async def connect(self):
        try:
            headers = dict(self.scope['headers'])
            auth_header = headers.get(b'authorization')

            if not auth_header:
                await self.close(code=4001)
                return

            token_str = auth_header.decode().split(" ")[1]

            token = AccessToken(token_str)
            user_id = token["user_id"]

            self.scope["user"] = await self.get_user_from_token(user_id)

            if not self.scope["user"]:
                await self.close(code=4002)
                return

        except Exception as e:
            print("WebSocket JWT Auth Error:", e)
            await self.close(code=4003)
            return
        
        self.user = self.scope["user"]
        if not self.user.is_authenticated:
            await self.close()
            return

        self.redis = redis.StrictRedis(
            host=getattr(settings, "REDIS_HOST", "localhost"),
            port=getattr(settings, "REDIS_PORT", 6379),
            db=0,
            decode_responses=True,
        )
        self.redis_key = f"story_draft:{self.user.id}"

        self.paused = False
        await self.accept()
        await self.send(json.dumps({"message": "STT 연결 완료"}))

    async def receive(self, bytes_data=None, text_data=None):
        if text_data:
            data = json.loads(text_data)
            cmd = data.get("command")

            if cmd == "pause":
                self.paused = True
                await self.send(json.dumps({"status": "일시정지"}))
                return

            elif cmd == "resume":
                self.paused = False
                await self.send(json.dumps({"status": "이어말하기"}))
                return

            elif cmd == "stop":
                await self.send(json.dumps({"status": "녹음완료"}))
                await self.close()
                return

        if bytes_data and not self.paused:
            # Whisper는 파일 단위이므로, 수신된 bytes를 임시 파일로 저장
            async with aiofiles.tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as temp_audio:
                await temp_audio.write(bytes_data)
                temp_path = temp_audio.name

            try:
                loop = asyncio.get_event_loop()
                text = await loop.run_in_executor(None, self.transcribe_audio, temp_path)

                clean_text = self._normalize_text(text)

                if clean_text:
                    existing = self.redis.get(self.redis_key) or ""
                    new_text = self._merge_sentences(existing, clean_text)
                    self.redis.set(self.redis_key, new_text)

                    await self.send(json.dumps({
                        "type": "transcription",
                        "text": clean_text.strip()
                    }))

            except Exception as e:
                await self.send(json.dumps({"error": f"STT 오류: {str(e)}"}))
            finally:
                try:
                    os.remove(temp_path)
                except FileNotFoundError:
                    pass

    def transcribe_audio(self, filepath):
        with open(filepath, "rb") as f:
            result = openai.Audio.transcriptions.create(
                model="whisper-1",
                file=f,
                language="ko"
            )
        return result.text.strip()

    def _normalize_text(self, text: str) -> str:
        text = re.sub(r"\s+", " ", text)
        if not re.search(r"[.!?]$", text):
            text += "."
        return text.strip()

    def _merge_sentences(self, existing: str, new_text: str) -> str:
        existing = existing.strip()
        new_text = new_text.strip()

        if existing and not existing.endswith((".", "?", "!")):
            existing += "."

        return (existing + " " + new_text).strip()

    async def disconnect(self, close_code):
        await self.send(json.dumps({"message": "STT 연결 종료"}))
