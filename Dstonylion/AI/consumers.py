from channels.generic.websocket import AsyncJsonWebsocketConsumer
from channels.db import database_sync_to_async
from .models import ChatRoom, Message
from story.models import *
from django.conf import settings
import os, asyncio, json
from openai import AsyncOpenAI
from dotenv import load_dotenv

from rest_framework_simplejwt.tokens import AccessToken
from django.contrib.auth import get_user_model
User = get_user_model()

load_dotenv(settings.BASE_DIR/ ".env")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
client = AsyncOpenAI(api_key=OPENAI_API_KEY)

class ChatConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        try:
            # 헤더에서 Authorization 추출
            headers = dict(self.scope['headers'])
            auth_header = headers.get(b'authorization')

            if not auth_header:
                raise ValueError("인증 헤더 없음")

            # Bearer 제거
            token_str = auth_header.decode().split(" ")[1]
            token = AccessToken(token_str)
            self.scope['user'] = await self.get_user_from_token(token['user_id'])

            self.room_id = self.scope['url_route']['kwargs']['room_id']

            if not await self.check_room_exists(self.room_id):
                raise ValueError('채팅방 없음')
            
            self.group_name = self.get_group_name(self.room_id)

            await self.channel_layer.group_add(self.group_name, self.channel_name)
            await self.accept() #WebSocket 연결 수락

        except ValueError as e: #값 오류가 있을 경우 연결 종료
            await self.send_json({'error_message':str(e)})
            await self.close()

    async def disconnect(self, closed_code):
        try:            
            group_name = self.get_group_name(self.room_id)
            await self.channel_layer.group_discard(group_name, self.channel_name) #현재 채널을 그룹에서 삭제

            if hasattr(self, 'room_id'):
                await self.delete_chat_data(self.room_id)

        except Exception as e: #일반 예외 처리
            pass


    conversation_state = {}
    async def receive_json(self, content):
        
        try:
            story_title = content['story_title']
            message = content['message']
            print("받은 메시지:", message)
            room = await self.get_or_create_room(story_title)
            #self.room_id = str(room.id)
            #self.group_name = self.get_group_name(self.room_id)
            print("group_name:", self.group_name)

            if self.room_id not in self.conversation_state:
                self.conversation_state[self.room_id] = {
                    "mode": "normal",
                    "phase": "initial",
                    "round_count": 0
                }
            state = self.conversation_state[self.room_id]

            if state["mode"] == "ending":
                if message == "true":
                    await self.ending_extension(room)
                    self.conversation_state[self.room_id] = {"mode": "done", "phase": "done", "round_count": 0}

                    await self.send(text_data=json.dumps({
                        "sender": "ai",
                        "message": "이야기를 완성했어요! 대화를 종료할게요 :)"
                    }, ensure_ascii=False))
                    await self.close()
                    return
                elif message == "false":
                    await self.send(text_data=json.dumps({
                        "sender": "ai",
                        "message": "그럼 조금 더 이야기해보자!"
                    }, ensure_ascii=False))
                    self.conversation_state[self.room_id] = {"mode": "normal", "phase": "extended", "round_count": 0}
                    return
                else:
                    await self.send(text_data=json.dumps({
                        "sender": "ai",
                        "message": "true혹은 false를 입력해야 합니다"
                    }, ensure_ascii=False))
                    return

            await self.save_message(room, message, sender='user')
            asked_count = await self.count_ai_questions(room)

            if state["phase"] == "initial" and asked_count >= 10:
                self.conversation_state[self.room_id] = {"mode": "ending", "phase": "initial", "round_count": 0}
                ai_response = "좋아! 이제 결말을 확장해도 될까?"
                await self.save_message(room, ai_response, sender="ai")
                await self.channel_layer.group_send(self.group_name, {
                    "type": "chat_message",
                    "sender": "ai",
                    "message": ai_response,
                })
                return
            
            if state["phase"] == "extended":
                self.conversation_state[self.room_id]["round_count"] += 1
                round_count = self.conversation_state[self.room_id]["round_count"]

                if round_count % 3 == 0:
                    self.conversation_state[self.room_id]["mode"] = "ending"
                    ai_response = "이제 결말을 확장해도 될까?"
                    await self.save_message(room, ai_response, sender="ai")
                    await self.channel_layer.group_send(self.group_name, {
                        "type": "chat_message",
                        "sender": "ai",
                        "message": ai_response,
                    })
                    return

            prompt_content = await self.ai_prompt(room, message)
            #final_ai_message = await self.stream_ai_response(prompt_content)
            print("Prompt 생성 완료")
            ai_response = await self.get_ai_response(prompt_content)
            #await self.save_message(room, ai_response, sender='ai')
            print("AI 응답:", ai_response)
            await self.save_message(room, ai_response ,sender='ai', prompt=prompt_content)

            await self.channel_layer.group_send(self.group_name, {
                'type': 'chat_message',
                'sender':'ai',
                'message':ai_response
            })

            await self.channel_layer.group_send(self.group_name, {
                'type':'chat_stream_end'
            })
            
        except ValueError as e:
            await self.send_json({'error':str(e)})
        except Exception as e:
            import traceback
            print("ChatConsumer Error:", e)
            traceback.print_exc()
            await self.send_json({'error': f'메시지 처리 중 오류 발생: {str(e)}'})



    async def chat_message(self, event):
        try:
            await self.send(text_data=json.dumps({
                'sender':event['sender'],
                'message':event['message']}, ensure_ascii=False))
        except Exception as e:
            await self.send_json({'error_message': '메시지 전송 실패'})
    
    async def chat_stream(self, event):
        await self.send_json({
            'sender':'ai',
            'delta':event.get('delta', '')
        })
    
    async def chat_stream_end(self, event):
        await self.send_json({
            'sender':'ai',
            'end':True
        })


    @database_sync_to_async
    def create_extended_story(self, base_story, user, extended_text):
        full_content = (base_story.content or "") + "\n" + extended_text
        new_story = Story.objects.create(
            user=user,
            child=base_story.child,
            voice=base_story.voice,
            title=f"{base_story.title} - 확장편",
            content=full_content.strip(),
            page_count=0,
            age_group=base_story.age_group,
            moral=base_story.moral,
            status="extended",
            category="extended",
        )

        sentences = [s.strip() for s in full_content.split("\n") if s.strip()]
        for i, sentence in enumerate(sentences, start=1):
            StoryPage.objects.create(
                story=new_story,
                page_number=i,
                text=sentence
            )
        new_story.page_count = len(sentences)
        new_story.save()
        return new_story

    async def ending_extension(self, room: ChatRoom):
        messages = await self.get_all_messages(room)
        conversation_text = "\n".join([f"{m.sender}:{m.text}" for m in messages])

        prompt = f"""
[역할]
너는 어린이가 참여한 대화를 바탕으로 동화의 결말을 새롭게 완성하는 작가야.

[이전 대화]
{conversation_text}

[지시]
- 대화에서 나온 아이의 상상력을 반영해 결말 부분을 새롭게 작성해.
- 기존 동화의 분위기와 교훈을 유지하되 따뜻하고 여운 있는 결말로 완성해.
- 문장은 8문장 이내, 각 문장은 한 줄에 하나씩 써.
"""

        extended_ending = await self.get_ai_response(prompt)
        await self.save_message(room, extended_ending, sender='ai')

        extended_story = await self.create_extended_story(
            base_story=room.story,
            user=self.scope["user"],
            extended_text=extended_ending
        )

        await self.channel_layer.group_send(self.group_name, {
            'type': 'chat_message',
            'sender': 'ai',
            'message': f"새로운 확장 동화가 생성되었어요! (id: {extended_story.id})"
        })


    @staticmethod
    def get_group_name(room_id):
        return f"chat_room_{room_id}"
        
    @database_sync_to_async
    def get_or_create_room(self, story_title: str) -> ChatRoom: #(story.user, story)로 ChatRoom 확보
        user = self.scope["user"]
        if not user.is_authenticated:
            raise ValueError("로그인한 사용자만 방을 생성할 수 있습니다.")

        story, _ = Story.objects.get_or_create(title=story_title, defaults={'user':user})
        room, _ = ChatRoom.objects.get_or_create(story=story, user=story.user)
        return room
    
    @database_sync_to_async
    def save_message(self, room:ChatRoom, text, sender='user', prompt=None):
        Message.objects.create(
            room=room,
            story=room.story,
            text=text,
            sender=sender,
            prompt=prompt
        )

    @database_sync_to_async
    def delete_chat_data(self, room_id):
        try:
            room = ChatRoom.objects.get(id=room_id)
            Message.objects.filter(room=room).delete()
            #room.delete() 
        except ChatRoom.DoesNotExist:
            pass
        except Exception as e:
            print(f"채팅 데이터 삭제 중 오류 발생: {e}")

    @database_sync_to_async
    def get_recent_messages(self, room, limit=100):
        return list(Message.objects.filter(room=room).order_by('-timestamp')[:limit])

    @database_sync_to_async
    def get_all_messages(self, room):
        return list(Message.objects.filter(room=room).order_by("timestamp"))
    
    @database_sync_to_async
    def count_ai_questions(self, room):
        return Message.objects.filter(room=room, sender="ai", text__contains="?").count()

    async def ai_prompt(self, room:ChatRoom, latest_user_message):
        recent_messages = await self.get_recent_messages(room)
        story_content = (room.story.content or "").strip()
        story_long = story_content[:1000]

        history = []
        for m in reversed(recent_messages):
            role = "사용자" if m.sender == "user" else "AI"
            history.append(f"{role}:{m.text}")

        history_text="\n".join(history).replace("\r", "")

        asked_count = await self.count_ai_questions(room)

        question_list = (
            f"{room.story.title}에서 어떤 장면이 가장 기억에 남아?\n"
            "왜 그렇게 생각했어?\n"
            "네가 주인공이라면 그 장면에서 어떻게 행동했을 것 같아?\n"
            "새로운 등장인물이 있다면 어떤 인물이었으면 좋겠어?\n"
            "결말의 분위기는 밝아야할까, 어두워야 할까? 선택했다면 그 이유도 함께 말해줘.\n"
        )

        prompt = f"""
        [시스템 역할]
        너는 어린이가 동화를 읽고 직접 사고를 하며 이야기를 확장할 수 있도록 도와주는 안내자야.
        친근하지만 어른스럽게 상상력을 이끌어내야 해. 과한 이모지는 지양하고, 답은 3문장 이내로 해.

        [동화 내용]
        {story_long}

        [이전 대화]
        {history_text}

        [사용자 최신 발화]
        {latest_user_message}

        [필수 질문 목록]
        {question_list}

        [현재까지 질문한 필수 질문 개수]
        {asked_count}개

        [지시]
        - 위 정보를 바탕으로 자연스럽게 반말로 대화하고, 필수 질문 목록에서 이미 질문한 {asked_count}개 이후의 질문을 우선적으로 해야 해.
        - 질문을 한 번에 물어보지 말고, 발화 한 번 당 질문 1개만 해야 해.
        - {asked_count}가 10이 됐을 때 다음 질문으로 반드시 "이제 결말을 확장해도 될까?"를 물어봐.  
        """
        print("Prompt length:", len(prompt))
        print("question count: ", asked_count)

        return prompt.strip()
    
    async def stream_ai_response(self, prompt_content):
        final_text_parts = []
        stream = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role":"user", "content":prompt_content}],
            stream=True,
        )

        async for chunk in stream:
            try:
                delta = chunk.choices[0].delta.content or ""
            except Exception:
                delta = ""
            
            if delta:
                final_text_parts.append(delta)
                await self.channel_layer.group_send(self.group_name, {
                    'type': 'chat_stream',
                    'delta': delta,
                })

                await asyncio.sleep(0)
            
        return "".join(final_text_parts)

    async def get_ai_response(self, prompt_content):
        try:
            response = await client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role":"user", "content":prompt_content}]
            )
            print("AI 응답 수신 완료")
            print(response.choices[0].message.content)
            return response.choices[0].message.content.strip()
        except Exception as e:
            import traceback
            print("OpenAI API Error:", e)
            traceback.print_exc()
            return "AI 응답 생성 중 오류가 발생했습니다."



    @database_sync_to_async
    def get_user_from_token(self, user_id):
        return User.objects.get(id=user_id)

    @database_sync_to_async
    def check_room_exists(self, room_id):
        return ChatRoom.objects.filter(id=room_id).exists()