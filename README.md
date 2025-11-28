# 📚Stony Web Service - "Backend"
스토니: 부모의 목소리와 경험담으로 만드는 동화 + 스토리텔링 기반의 육아 콘텐츠 서비스

<img width="1920" height="1080" alt="0" src="https://github.com/user-attachments/assets/85397872-a85c-46c1-b3d7-3c66959833a0" />

## MVP

<img width="1920" height="1080" alt="8" src="https://github.com/user-attachments/assets/871476d9-a206-4105-bd0b-0e6641a04a80" />

## 부모의 목소리와 에피소드로 만드는 동화

<img width="1920" height="1080" alt="9" src="https://github.com/user-attachments/assets/34f594b6-57ab-42a7-950d-66cc1708f6d9" />

## 명작 동화 결말 확장

<img width="1920" height="1080" alt="10" src="https://github.com/user-attachments/assets/1e8c7ecd-b76e-4894-969b-7440974a74d4" />

## 아이 분석 리포트

<img width="1920" height="1080" alt="11" src="https://github.com/user-attachments/assets/f683d47e-331b-4571-9321-0fdf7d49e00f" />

## 경쟁사 분석(Competitve Analysis)

<img width="1920" height="1080" alt="12" src="https://github.com/user-attachments/assets/96587045-7626-463e-8934-35d6bb4942d9" />

## 비즈니스 모델(BM)

<img width="1920" height="1080" alt="14" src="https://github.com/user-attachments/assets/ce8165a6-b518-4e19-bf24-1df4cf4cd865" />


### 배포 URL

https://frontend-puof.vercel.app/

### 기능 구현 분담
<a href="https://github.com/2ewyeonwoo3"><img src="https://github.com/2ewyeonwoo3.png" width="40" height="40" /></a>
2ewyeonwoo3
<a href="https://github.com/zziminally"><img src="https://github.com/zziminally.png" width="40" height="40" /></a>
zziminally

| 기능                     | 담당자         | 구현 내용                                                      | 사용 기술                          |
| ------------------------ | -------------- | -------------------------------------------------------------- | ---------------------------------- |
| 동화 생성 API   | 2ewyeonwoo3 & zziminally| OpenAI 기반 스토리 생성, 페이지 단위 분리, 동적 스토리 구조화 | OpenAI API, Prompt Engineering, Redis |
| 삽화 생성 API           | zziminally | 이미지 생성 파이프라인 구축, 페이지별 일러스트 생성 및 결과 저장 | OpenAI Image API, S3       |
| 음성 클로닝 & TTS       | 2ewyeonwoo3  | 사용자 맞춤 음성 클로닝, 성우 목소리 변환, TTS 변환 처리       | OpenVoice/MeloTTS,  Redis   |
| STT 음성 입력        | 	zziminally  | 음성 → 텍스트 변환, Whisper 기반 전처리 및 추론 파이프라인 구성 |    Whisper           |
| 아이 분석 리포트        | 2ewyeonwoo3  | 아동 언어발화 기반 NDW·언어지표 계산, 성격 분석 모델 적용     | NLP 분석, OpenAI API, Redis        |
| 확장 동화 생성 및 채팅 | 	zziminally| 챗봇-아동 대화 기반 이어쓰기 스크립트 생성, Dramatica 구조 적용 | OpenAI API, Narrative Engine Logic, Chat Pipeline |
| 배포 (AWS S3)        | zziminally  | 정적 파일·이미지 저장 버킷 구성, S3 업로드/권한 관리            | AWS S3, boto3                |
| 배포 (AWS EC2, Redis, RDS)|2ewyeonwoo3 | 백엔드 서버 EC2 배포, RDS(MySQL) 구성, Redis 캐시 |AWS EC2, RDS(MySQL), Redis, Nginx, Gunicorn, Docker |





