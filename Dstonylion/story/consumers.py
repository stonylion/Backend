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
            await self.accept()

            # QUERY STRING 파싱
            query_string = self.scope["query_string"].decode()
            qs = parse_qs(query_string)
            token_list = qs.get("token", [])

            if not token_list:
                raise ValueError("토큰 없음")

            token_str = token_list[0]
            access = AccessToken(token_str)
            user_id = access["user_id"]

            # User 객체 로드
            self.scope["user"] = await self.get_user_from_token(user_id)
            if not self.scope["user"]:
                raise ValueError("유효하지 않은 사용자")

            self.user = self.scope["user"]

            # Redis 연결
            self.redis = redis.StrictRedis(
                host=settings.REDIS_HOST,
                port=settings.REDIS_PORT,
                db=0,
                decode_responses=True,
            )
            self.redis_draft_key = f"draft:{self.user.id}"

            # 상태
            self.paused = False

            await self.send_json({"message": "🟢 STT 연결 성공"})

        except Exception as e:
            await self.send_json({'error_message': f"인증 오류: {str(e)}"})
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
        fd, temp_path = tempfile.mkstemp(suffix=".wav")
        os.close(fd)

        async with aiofiles.open(temp_path, "wb") as f:
            await f.write(chunk_bytes)

        return temp_path
