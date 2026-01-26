# PDF → Markdown → DB 파이프라인 코드 검토 리포트

## 📋 개요
`pdftoMDmaker.py`는 PDF를 마크다운으로 정규화한 후, 부모-자식 구조로 분리하여 PostgreSQL/Milvus에 저장하는 통합 파이프라인입니다.

---

## ✅ 코드 구조 및 검토 결과

### 1️⃣ PDF → Markdown 정규화 (`pdf_to_markdown`)

**기능:**
- PDF 파일 읽기 (PyMuPDF)
- 텍스트 추출
- 법률명을 `# (대제목)`으로 변환
- 조항(`제N조`)을 `## (중제목)`으로 변환
- 번호 매김 목록(`1.`) → 마크다운 목록(`-`)으로 정규화
- 메타데이터 추출 (제목, 페이지 수, 추출 시간)

**개선 사항:**
- ✅ 에러 핸들링 추가 (PDF 열기 실패 시)
- ✅ 메타데이터 반환 (마크다운 텍스트와 함께)
- ✅ 공백 정규화 (여러 줄바꿈 → 2줄로 통일)
- ✅ 정규식 개선 (`(제\d+조\([^)]*\))` → 괄호 내용 안전 처리)

**출력 예:**
```markdown
# 민법(일부개정)

## 제1조(목적)
이 법은 민법의 목적을 규정한다.

## 제2조(정의)
- 1. 용어의 정의
- 2. 특수한 용어
```

---

### 2️⃣ 계층적 청킹 (`chunk_markdown_hierarchically`)

**구조:**
```
문서 (Document)
├── 부모 (Parent) - 조항 단위 (##)
│   ├── 자식 (Child) - 문장 단위 (300자 이내)
│   ├── 자식 (Child)
│   └── 자식 (Child)
├── 부모 (Parent)
│   └── ...
```

**기능:**
- 마크다운 헤더 기반 부모 분할 (##)
- RecursiveCharacterTextSplitter로 자식 분할
- UUID 기반 ID 생성 (자동 추적성)
- 메타데이터 추가 (생성 시간, 문자 수, 수열 번호)

**데이터 구조:**
```json
{
  "id": "12345-parent_0",
  "doc_id": "uuid-1234",
  "type": "parent",
  "level": "조",
  "title": "제1조(목적)",
  "content": "이 법은 민법의 목적을 규정한다.",
  "char_count": 25,
  "created_at": "2026-01-23T12:34:56",
  "children": [
    {
      "id": "12345-parent_0_child_0",
      "parent_id": "12345-parent_0",
      "doc_id": "uuid-1234",
      "type": "child",
      "level": "문",
      "sequence": 1,
      "content": "이 법은 민법의 목적을...",
      "char_count": 300,
      "created_at": "2026-01-23T12:34:56"
    }
  ]
}
```

**개선 사항:**
- ✅ 에러 핸들링 (청킹 실패 시 폴백)
- ✅ 타입 힌팅 추가 (List[Dict] 등)
- ✅ 로깅 개선 (각 단계별 진행 상황)

---

### 3️⃣ PostgreSQL 저장소 (`PostgreSQLStorage`)

**테이블 스키마:**

```sql
-- 1. 문서 메타데이터
pdf_documents (
  doc_id VARCHAR(36) PRIMARY KEY,
  title VARCHAR(500),
  file_path TEXT,
  total_pages INTEGER,
  created_at TIMESTAMP,
  updated_at TIMESTAMP
)

-- 2. 부모 청크 (조항)
parent_chunks (
  id VARCHAR(255) PRIMARY KEY,
  doc_id VARCHAR(36) FK → pdf_documents,
  title VARCHAR(500),
  content TEXT,
  char_count INTEGER,
  created_at TIMESTAMP
)

-- 3. 자식 청크 (문장)
child_chunks (
  id VARCHAR(255) PRIMARY KEY,
  parent_id VARCHAR(255) FK → parent_chunks,
  doc_id VARCHAR(36) FK → pdf_documents,
  sequence INTEGER,
  content TEXT,
  char_count INTEGER,
  created_at TIMESTAMP
)
```

**기능:**
- 연결 관리 (connect/close)
- 자동 테이블 생성
- 계층적 데이터 저장 (부모+자식)
- 인덱스 생성 (검색 성능 최적화)
- 중복 처리 (ON CONFLICT DO UPDATE)

**개선 사항:**
- ✅ 트랜잭션 관리 (자동 롤백)
- ✅ 배치 삽입 (`execute_batch` - 성능 최적화)
- ✅ 외래 키 제약 (데이터 무결성)
- ✅ 상세한 로깅

**저장 로직:**
```
1. 문서 메타데이터 → pdf_documents
2. 부모 청크들 → parent_chunks
3. 자식 청크들 → child_chunks (parent_id 관계 유지)
```

---

### 4️⃣ Milvus 저장소 (`MilvusStorage`)

**기능:**
- Milvus 벡터 DB 연결
- 컬렉션 생성 (스키마 정의)
- 벡터 임베딩 삽입

**컬렉션 스키마:**
```
legal_chunks
├── id (VARCHAR, PRIMARY KEY)
├── doc_id (VARCHAR)
├── parent_id (VARCHAR)
├── content (VARCHAR)
└── embedding (FLOAT_VECTOR, dim=1536)
```

**개선 사항:**
- ✅ MilvusException 핸들링
- ✅ 유연한 설정 (호스트/포트)
- ✅ 더미 임베딩으로 테스트 가능
- ⚠️ **주의:** 실제 임베딩은 외부 모델 필요 (OpenAI, Sentence-BERT 등)

---

### 5️⃣ 통합 파이프라인 (`process_pdf_to_db`)

**실행 순서:**
```
1️⃣ PDF → Markdown 변환
   └─ metadata 추출
2️⃣ 계층적 청킹
   ├─ 부모 분할 (조항)
   └─ 자식 분할 (문장)
3️⃣ PostgreSQL 저장
   ├─ 연결
   ├─ 테이블 생성
   └─ 데이터 저장
4️⃣ Milvus 연결 (선택사항)
   ├─ 컬렉션 생성
   └─ 벡터 삽입
5️⃣ 완료
```

---

## 🔍 잠재적 이슈 및 개선 제안

### 높은 우선순위

| 이슈 | 현황 | 해결책 |
|-----|------|--------|
| **실제 임베딩 미생성** | Milvus에 더미 벡터(0.0) 저장 | OpenAI/BERT 모델로 실제 임베딩 생성 |
| **대용량 PDF 처리** | 메모리 누적 위험 | 스트리밍/배치 처리 또는 페이지 단위 처리 |
| **Milvus 연결 실패 시 처리** | 로그만 출력 | PostgreSQL 데이터는 저장되지만 벡터 검색 불가 |
| **PDF 인코딩 문제** | UTF-8 고정 | 자동 인코딩 감지 또는 사용자 지정 옵션 |

### 중간 우선순위

| 개선 | 현황 | 제안 |
|-----|------|-----|
| **트랜잭션 일관성** | PostgreSQL만 트랜잭션 | PostgreSQL + Milvus 함께 롤백 메커니즘 |
| **재처리 시나리오** | 없음 | 문서 버전 관리 또는 타임스탬프 기반 삭제 |
| **성능 모니터링** | 없음 | 처리 시간 측정, 청크 통계 로깅 |
| **데이터 유효성 검사** | 최소한 | 콘텐츠 길이/형식 검증 |

### 낮은 우선순위

- [ ] 부분 청킹 재처리
- [ ] 다국어 지원 (현재 한국어 기준)
- [ ] 메타데이터 확장 (저자, 카테고리 등)

---

## 🛠️ 사용 예제

```python
# 1. 기본 사용
postgres_config = {
    "host": "localhost",
    "port": 5432,
    "database": "airflow",
    "user": "airflow",
    "password": "airflow"
}

result = process_pdf_to_db(
    pdf_path="sample.pdf",
    postgres_config=postgres_config,
    milvus_host="localhost",
    milvus_port=19530
)

# 2. 개별 함수 사용
md_text, metadata = pdf_to_markdown("sample.pdf")
hierarchical_data = chunk_markdown_hierarchically(md_text)

pg_storage = PostgreSQLStorage(postgres_config)
pg_storage.connect()
pg_storage.create_tables()
pg_storage.save_hierarchical_data("doc_123", "제목", "path", hierarchical_data)
pg_storage.close()
```

---

## 📊 DB 조회 예제

```sql
-- 모든 조항 조회
SELECT * FROM parent_chunks WHERE doc_id = 'uuid-123';

-- 특정 조항의 모든 문장
SELECT * FROM child_chunks 
WHERE parent_id = 'uuid-123_parent_0'
ORDER BY sequence;

-- 문서별 통계
SELECT 
  d.title,
  COUNT(DISTINCT p.id) as parent_count,
  COUNT(DISTINCT c.id) as child_count,
  SUM(c.char_count) as total_chars
FROM pdf_documents d
LEFT JOIN parent_chunks p ON d.doc_id = p.doc_id
LEFT JOIN child_chunks c ON p.id = c.parent_id
GROUP BY d.doc_id;
```

---

## ✨ 최종 평가

| 항목 | 평가 | 점수 |
|-----|------|------|
| 코드 구조 | 명확한 함수 분리, 책임 명확 | ⭐⭐⭐⭐⭐ |
| 에러 핸들링 | Try-catch 추가, 로깅 상세 | ⭐⭐⭐⭐ |
| DB 설계 | 정규화된 스키마, 관계성 명확 | ⭐⭐⭐⭐⭐ |
| 문서화 | 주석 충분, 타입 힌팅 추가 | ⭐⭐⭐⭐ |
| 임베딩 | **TODO**: 실제 모델 연동 필요 | ⭐⭐⭐ |
| **전체** | **프로덕션 준비 상태: 80%** | ⭐⭐⭐⭐ |

---

## 🎯 다음 단계

1. **임베딩 모델 통합**
   - OpenAI API 또는 Sentence-BERT 연동
   - 벡터 생성 및 정규화

2. **성능 최적화**
   - 배치 임베딩 처리
   - 데이터베이스 쿼리 최적화

3. **테스트 및 배포**
   - 단위 테스트 작성
   - Docker 컨테이너화
   - Airflow DAG 통합

