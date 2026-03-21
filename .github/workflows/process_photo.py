"""
우지언 중국어 단어 자동 추출기
- photos/학원/ 또는 photos/학교/ 에 올라온 새 사진을 Claude AI로 분석
- data.js에 자동으로 단어 세션 추가
"""

import anthropic
import base64
import json
import os
import re
import sys
from pathlib import Path
from datetime import datetime

# ── 이미지 → base64 변환 ──
def encode_image(image_path):
    with open(image_path, 'rb') as f:
        return base64.standard_b64encode(f.read()).decode('utf-8')

# ── HEIC 파일을 JPEG로 변환 ──
def convert_to_jpeg_if_needed(image_path):
    path = Path(image_path)
    if path.suffix.lower() in ['.heic', '.heif']:
        try:
            import pillow_heif
            from PIL import Image
            pillow_heif.register_heif_opener()
            img = Image.open(image_path)
            jpeg_path = path.with_suffix('.jpg')
            img.save(jpeg_path, 'JPEG', quality=90)
            print(f"  → HEIC → JPEG 변환 완료: {jpeg_path}")
            return str(jpeg_path)
        except Exception as e:
            print(f"  → HEIC 변환 실패: {e}")
            return image_path
    return image_path

# ── Claude API로 단어 추출 ──
def extract_words_from_image(client, image_path):
    media_type = 'image/jpeg' if Path(image_path).suffix.lower() in ['.jpg', '.jpeg', '.heic', '.heif'] else 'image/png'
    image_data = encode_image(image_path)

    prompt = """이 사진은 싱가포르 초등학교 중국어 수업 숙제 시트입니다.

사진에서 중국어 단어(词语)들을 모두 추출해주세요.

다음 JSON 형식으로만 응답해주세요 (다른 텍스트 없이):

{
  "lesson": "레슨명 (예: T1L09-1, 없으면 Unknown)",
  "groups": [
    {
      "name": "그룹명 (习写词语 · 쓰기 단어 / 认读词语 · 읽기 단어 / 词语解释 · 단어 해설 중 해당하는 것)",
      "words": [
        {
          "hanzi": "한자",
          "pinyin": "pinyin (성조 포함, 예: shí hào)",
          "korean": "한국어 뜻 (간결하게)",
          "chinese_def": "중국어 뜻 (간단하게)"
        }
      ]
    }
  ]
}

규칙:
- 단어만 추출 (문장, 예문, 설명 제외)
- pinyin은 정확한 성조 포함 (예: nǐ hǎo)
- 한국어 뜻은 핵심만 간결하게
- 그룹이 여러 개면 groups 배열에 모두 포함
- JSON만 반환, 설명 없이"""

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2000,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": media_type,
                            "data": image_data,
                        },
                    },
                    {
                        "type": "text",
                        "text": prompt
                    }
                ],
            }
        ],
    )

    return response.content[0].text

# ── data.js에 새 세션 추가 ──
def update_data_js(new_session, data_js_path):
    content = Path(data_js_path).read_text(encoding='utf-8')

    session_str = json.dumps(new_session, ensure_ascii=False, indent=2)
    session_indented = '\n'.join('  ' + line for line in session_str.split('\n'))

    # data.js 마지막의 ]; 앞에 새 세션 삽입
    idx = content.rfind('];')
    if idx == -1:
        print("ERROR: data.js 형식이 올바르지 않습니다 (]; 를 찾을 수 없음)")
        return False

    new_content = content[:idx].rstrip() + ',\n' + session_indented + '\n];\n'
    Path(data_js_path).write_text(new_content, encoding='utf-8')
    return True

# ── 중복 세션 확인 ──
def session_exists(session_id, data_js_path):
    content = Path(data_js_path).read_text(encoding='utf-8')
    return f'"{session_id}"' in content

# ── 메인 ──
def main():
    api_key = os.environ.get('ANTHROPIC_API_KEY')
    if not api_key:
        print("ERROR: ANTHROPIC_API_KEY 환경변수가 설정되지 않았습니다")
        sys.exit(1)

    # 변경된 파일 목록 가져오기
    changed_files_env = os.environ.get('CHANGED_FILES', '')
    changed_files = [f.strip() for f in changed_files_env.split('\n') if f.strip()]

    image_extensions = {'.jpg', '.jpeg', '.png', '.heic', '.heif', '.webp'}
    photo_files = [
        f for f in changed_files
        if f.startswith('photos/') and Path(f).suffix.lower() in image_extensions
    ]

    # 실제로 존재하는 파일만 처리
    photo_files = [f for f in photo_files if Path(f).exists()]

    if not photo_files:
        print("처리할 새 사진이 없습니다")
        return

    client = anthropic.Anthropic(api_key=api_key)
    data_js_path = Path('data.js')

    for photo_path_str in photo_files:
        photo = Path(photo_path_str)
        print(f"\n📸 처리 중: {photo_path_str}")

        # 학원 / 학교 구분 (폴더명으로)
        source = '학원'
        for part in photo.parts:
            if part == '학교':
                source = '학교'
                break
            elif part == '학원':
                source = '학원'
                break

        # 날짜 추출 (파일명에서, 없으면 오늘)
        date_str = datetime.now().strftime('%Y-%m-%d')
        date_match = re.search(r'(\d{4}-\d{2}-\d{2})', photo.stem)
        if date_match:
            date_str = date_match.group(1)

        # HEIC 변환
        processed_path = convert_to_jpeg_if_needed(photo_path_str)

        # Claude API 호출
        try:
            raw = extract_words_from_image(client, processed_path)
            raw = re.sub(r'^```json\s*', '', raw.strip())
            raw = re.sub(r'\s*```$', '', raw.strip())
            extracted = json.loads(raw)
        except Exception as e:
            print(f"  → ERROR: 단어 추출 실패 ({e})")
            continue

        lesson = extracted.get('lesson', photo.stem)
        session_id = f"{'hakwon' if source == '학원' else 'hakgyo'}_{date_str.replace('-', '')}_{re.sub(r'[^a-zA-Z0-9]', '', lesson)}"

        # 중복 확인
        if session_exists(session_id, data_js_path):
            print(f"  → 이미 존재하는 세션 건너뜀: {session_id}")
            continue

        session = {
            "id": session_id,
            "source": source,
            "date": date_str,
            "lesson": lesson,
            "groups": extracted.get("groups", [])
        }

        word_count = sum(len(g.get('words', [])) for g in session['groups'])
        print(f"  → {source} / {lesson} / {word_count}개 단어 추출 완료")

        if update_data_js(session, data_js_path):
            print(f"  → data.js 업데이트 완료 ✅")
        else:
            print(f"  → data.js 업데이트 실패 ❌")

if __name__ == '__main__':
    main()
