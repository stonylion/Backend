import json, os, re, asyncio, tempfile
import redis
import aiofiles
from django.conf import settings
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from channels.db import database_sync_to_async
from rest_framework_simplejwt.tokens import AccessToken
from django.contrib.auth import get_user_model
from openai import AsyncOpenAI
from dotenv import load_dotenv
from urllib.parse import parse_qs

User = get_user_model()

# Load env
load_dotenv(settings.BASE_DIR / ".env")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
client = AsyncOpenAI(api_key=OPENAI_API_KEY)


class DraftConsumer(AsyncJsonWebsocketConsumer):

    # -------------------------------
    # 🔐 JWT → User
    # -------------------------------
    @database_sync_to_async
    def get_user_from_token(self, user_id):
        try:
            return User.objects.get(id=user_id)
        except User.DoesNotExist:
            return None

    # -------------------------------
    # 🔌 CONNECT
    # -------------------------------
    async def connect(self):
        try:
            # 1) Query 파싱
            qs = parse_qs(self.scope["query_string"].decode())
            token = qs.get("token", [None])[0]
            if not token:
                raise ValueError("NO_TOKEN")

            # 2) JWT 인증
            access = AccessToken(token)
            user_id = access["user_id"]
            user = await self.get_user_from_token(user_id)
            if not user:
                raise ValueError("INVALID_USER")
            self.scope["user"] = user
            self.user = user

            # 3) Redis 연결
            self.redis = redis.StrictRedis(
                host=settings.REDIS_HOST,
                port=settings.REDIS_PORT,
                db=0,
                decode_responses=True,
                ssl=settings.REDIS_SSL,
                ssl_cert_reqs=None if settings.REDIS_SSL else None
            )
            self.redis_draft_key = f"draft:{user.id}"

            # ⭐ 4) 모든 검증 완료 후에 accept()
            await self.accept()

            # 5) 이제 메시지 전송 가능
            await self.send_json({"message": "🟢 STT 연결 성공"})

        except Exception as e:
            # handshake 중에는 메시지 보내면 안되므로 바로 close()
            await self.close()



    async def disconnect(self, close_code):
        pass


    # -------------------------------
    # 🎧 RECEIVE
    # -------------------------------
    async def receive(self, bytes_data=None, text_data=None):
        try:
            # 텍스트 메시지 처리
            if text_data:
                data = json.loads(text_data)
                cmd = data.get("command")

                if cmd == "pause":
                    self.paused = True
                    await self.send_json({"status": "🟡 일시정지"})
                    return

                elif cmd == "resume":
                    self.paused = False
                    await self.send_json({"status": "🟢 재개"})
                    return

                elif cmd == "stop":
                    await self.send_json({"status": "🛑 녹음완료"})
                    return

                elif cmd == "switch_to_text":
                    current = self.redis.get(self.redis_draft_key) or ""
                    await self.send_json({
                        "status": "text_mode",
                        "draft_text": current
                    })
                    return

                elif cmd == "switch_to_voice":
                    text = data.get("draft_text", "")
                    self._update_draft(text)
                    last = self._get_last_sentences(1)
                    await self.send_json({
                        "status": "voice_mode",
                        "recent_text": last
                    })
                    return

                elif cmd == "save_text":
                    text = data.get("draft_text", "")
                    self._update_draft(text)
                    await self.send_json({"status": "text_saved"})
                    return

            # -------------------------------
            # 🎤 음성 chunk 수신 (async Whisper)
            # -------------------------------
            if bytes_data and not self.paused:

                temp_path = await self._save_temp_audio(bytes_data)

                try:
                    text = await self.transcribe_audio_async(temp_path)
                    clean = self._normalize_text(text)

                    if clean:
                        self._append_to_draft(clean)
                        await self.send_json({
                            "type": "transcription",
                            "text": clean
                        })

                except Exception as e:
                    await self.send_json({"error": f"STT 오류: {str(e)}"})

                finally:
                    try:
                        os.remove(temp_path)
                    except:
                        pass

        except Exception as e:
            await self.send_json({
                "error_message": f"메시지 처리 중 오류 발생: {str(e)}"
            })


    # -------------------------------
    # 🧠 Whisper STT (완전 async-await 방식)
    # -------------------------------
    async def transcribe_audio_async(self, filepath):
        with open(filepath, "rb") as f:
            result = await client.audio.transcriptions.create(
                model="whisper-1",
                file=f,
                language="ko",
            )
        return result.text.strip()


    # -------------------------------
    # 📝 Draft 관리
    # -------------------------------
    def _append_to_draft(self, new_text):
        existing = self.redis.get(self.redis_draft_key) or ""
        if existing and not existing.endswith((".", "?", "!")):
            existing += ". "

        updated = (existing + " " + new_text).strip()
        self.redis.set(self.redis_draft_key, updated)

    def _update_draft(self, text):
        clean = self._normalize_text(text) if text else ""
        self.redis.set(self.redis_draft_key, clean)

    def _normalize_text(self, text):
        text = re.sub(r"\s+", " ", text)
        if not re.search(r"[.!?]$", text):
            text += "."
        return text.strip()

    def _get_last_sentences(self, n):
        full = self.redis.get(self.redis_draft_key) or ""
        sentences = re.split(r'(?<=[.!?])\s+', full)
        return " ".join(sentences[-n:]).strip()


    # -------------------------------
    # 🔊 TEMP AUDIO SAVE
    # -------------------------------
    async def _save_temp_audio(self, chunk_bytes):
        fd, temp_path = tempfile.mkstemp(suffix=".webm")
        os.close(fd)

        async with aiofiles.open(temp_path, "wb") as f:
            await f.write(chunk_bytes)

        return temp_path
