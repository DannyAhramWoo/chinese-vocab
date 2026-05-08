"""
우지언 중국어 단어 자동 추출기
- photos/학원/ 또는 photos/학교/ 에 올라온 새 사진을 Claude AI로 분석
- data.js에 자동으로 단어 세션 추가
- photos/processed.txt 로 처리된 사진 추적 (중복 방지)
"""

import anthropic
import base64
import json
import os
import re
import sys
from pathlib import Path
from datetime import datetime

PROCESSED_FILE = Path('photos/processed.txt')

# ── 처리된 사진 목록 로드 ──
def load_processed():
    if PROCESSED_FILE.exists():
        lines = PROCESSED_FILE.read_text(encoding='utf-8').splitlines()
        return set(line.strip() for line in lines if line.strip())
    return set()

# ── 처리 완료된 사진 기록 ──
def mark_processed(photo_path_str):
    processed = load_processed()
    processed.add(photo_path_str)
    PROCESSED_FILE.write_text('\n'.join(sorted(processed)) + '\n', encoding='utf-8')

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

사진에서 모든 중국어 학습 내용을 추출해주세요.

다음 JSON 형식으로만 응답해주세요 (다른 텍스트 없이):

{
  "lesson": "레슨명 (예: T1L09-1, 听写五, 없으면 Unknown)",
  "groups": [
    {
      "name": "그룹명",
      "words": [
        {
          "hanzi": "한자 단어 또는 문장 전체",
          "pinyin": "pinyin (성조 포함, 예: shí hào)",
          "korean": "한국어 뜻 또는 번역",
          "chinese_def": "중국어 설명 (단어만 해당, 문장이면 빈 문자열)",
          "type": "word 또는 sentence"
        }
      ]
    }
  ]
}

📘 단어 목록인 경우 (习写词语, 认读词语, 词语解释 등):
- 각 단어를 type: "word"로 추출
- group name: "习写词语 · 쓰기 단어" / "认读词语 · 읽기 단어" / "词语解释 · 단어 해설" 등
- chinese_def는 해당 단어의 중국어 설명

📋 选择填写(선택 빈칸 채우기) 형식인 경우:
- "选择适当的词语" 또는 "词语填写" 제목이 있거나, 빈칸 채우기 문제에 단어 보기가 제공된 경우
- 표/문장 속 빈칸은 무시하고, 보기로 제공된 단어 목록만 추출하세요
- 각 보기 단어를 type: "word"로 추출
- group name: "词语填写 · 선택 단어"

📝 听写(받아쓰기 시험) 형식인 경우:
- 사진에 "听写" 제목이 있거나 번호가 매겨진 문장들로 구성된 시트
- 각 문장 전체를 hanzi에 입력하고 type: "sentence"로 표시
- 밑줄 친 부분이 있어도 문장 전체를 추출 (빈칸 없이 완성된 문장)
- pinyin은 문장 전체의 pinyin
- korean은 문장 전체의 한국어 번역
- chinese_def는 빈 문자열
- group name: "听写句子 · 받아쓰기 문장"

공통 규칙:
- pinyin은 정확한 성조 포함 (예: nǐ hǎo)
- 그룹이 여러 개면 groups 배열에 모두 포함
- JSON만 반환, 설명 없이
- ⚠️ 손글씨 무시: 빨간색 또는 손으로 쓴 pinyin/메모/수정 내용은 무시하고, 인쇄된 중국어 단어만 추출하세요
- ⚠️ 중요: 문장 안에 큰따옴표(")가 있으면 반드시 \"로 이스케이프하거나, 중국어 인용 부호「」로 대체하세요
  예: 说："你好" → 说：「你好」 또는 说：\"你好\""""

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4000,
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

# ── JSON 안전 파싱 (AI 응답의 제어문자 자동 수정) ──
def safe_parse_json(raw):
    raw = re.sub(r'^```json\s*', '', raw.strip())
    raw = re.sub(r'\s*```$', '', raw.strip())
    raw = raw.strip()

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    # trailing comma 제거 (예: {"key": "val",} 또는 [...,])
    raw = re.sub(r',\s*([}\]])', r'\1', raw)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    # 문자열 안의 이스케이프되지 않은 개행/탭 문자 수정
    result = []
    in_string = False
    i = 0
    while i < len(raw):
        c = raw[i]
        if c == '\\' and in_string:
            result.append(c)
            i += 1
            if i < len(raw):
                result.append(raw[i])
            i += 1
            continue
        if c == '"':
            in_string = not in_string
            result.append(c)
            i += 1
            continue
        if in_string and c in '\n\r\t':
            escape_map = {'\n': '\\n', '\r': '\\r', '\t': '\\t'}
            result.append(escape_map[c])
            i += 1
            continue
        result.append(c)
        i += 1

    fixed = ''.join(result)
    # trailing comma 재처리 (개행 수정 후)
    fixed = re.sub(r',\s*([}\]])', r'\1', fixed)
    try:
        return json.loads(fixed)
    except json.JSONDecodeError as e:
        pos = e.pos
        snippet = repr(fixed[max(0, pos-80):pos+80])
        print(f"  → 파싱 실패 상세: char {pos} 주변: {snippet}")
        raise

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

# ── 메인 ──
def main():
    api_key = os.environ.get('ANTHROPIC_API_KEY')
    if not api_key:
        print("ERROR: ANTHROPIC_API_KEY 환경변수가 설정되지 않았습니다")
        sys.exit(1)

    image_extensions = {'.jpg', '.jpeg', '.png', '.heic', '.heif', '.webp'}

    # 처리 완료된 사진 목록 로드
    processed = load_processed()
    if processed:
        print(f"이미 처리된 사진 {len(processed)}개 건너뜀")

    # 변경된 파일 목록 가져오기
    changed_files_env = os.environ.get('CHANGED_FILES', '')
    changed_files = [f.strip() for f in changed_files_env.split('\n') if f.strip()]

    if changed_files:
        # 자동 실행: push로 추가된 사진 중 미처리된 것만
        photo_files = [
            f for f in changed_files
            if f.startswith('photos/') and Path(f).suffix.lower() in image_extensions
            and Path(f).exists()
            and f not in processed
        ]
    else:
        # 수동 실행(workflow_dispatch): 미처리 사진만 스캔
        print("수동 실행: 미처리 사진을 스캔합니다")
        photo_files = [
            str(p) for p in Path('photos').rglob('*')
            if p.suffix.lower() in image_extensions
            and p.is_file()
            and not p.name.startswith('.')
            and str(p) not in processed
        ]

    if not photo_files:
        print("처리할 새 사진이 없습니다")
        return

    print(f"처리할 새 사진 {len(photo_files)}개 발견")

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
            extracted = safe_parse_json(raw)
        except Exception as e:
            print(f"  → ERROR: 단어 추출 실패 ({e})")
            continue

        lesson = extracted.get('lesson', photo.stem)
        lesson_slug = re.sub(r'[^a-zA-Z0-9]', '', lesson) or photo.stem
        session_id = f"{'hakwon' if source == '학원' else 'hakgyo'}_{date_str.replace('-', '')}_{lesson_slug}"

        session = {
            "id": session_id,
            "source": source,
            "date": date_str,
            "lesson": lesson,
            "groups": extracted.get("groups", [])
        }

        item_count = sum(len(g.get('words', [])) for g in session['groups'])
        print(f"  → {source} / {lesson} / {item_count}개 항목 추출 완료")

        if update_data_js(session, data_js_path):
            print(f"  → data.js 업데이트 완료 ✅")
            mark_processed(photo_path_str)  # 성공 시 처리 완료 기록
        else:
            print(f"  → data.js 업데이트 실패 ❌")

if __name__ == '__main__':
    main()
