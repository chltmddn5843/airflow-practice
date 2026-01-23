# 📚 법률 문서 청킹 가이드

## 🎯 목표
PostgreSQL에 저장된 법률 데이터를 **청킹** → **임베딩** → **Milvus 벡터 DB에 저장**

---

## 📊 파이프라인 흐름

```
PostgreSQL (case_master, case_chunks)
    ↓
Chunking (청킹 - 이미 수행됨)
    ↓
Embedding (임베딩 - sentence-transformers)
    ↓
Milvus (legal_db.legal_chunks_v1)
    ↓
Attu UI (검색 및 시각화)
```

---

## 🚀 실행 방법

### **방법 1: Airflow DAG으로 실행 (권장)**

#### 1️⃣ 먼저 PDF ETL 파이프라인 실행
```bash
# Airflow UI 접속
http://localhost:8080

# DAG: pdf_legal_etl_v1
# → Trigger DAG 클릭
# → PostgreSQL에 데이터 저장 완료 대기
```

#### 2️⃣ 청킹 DAG 실행
```bash
# DAG: legal_chunking_milvus_v1
# → Trigger DAG 클릭
# → 실행 로그에서 진행 상황 확인
```

---

### **방법 2: 터미널에서 직접 실행**

#### 1️⃣ PostgreSQL이 비어있는 경우
먼저 데이터 생성:
```bash
# PDF ETL 파이프라인 수동 실행
python dags/pdf_to_postgres_etl.py
```

#### 2️⃣ 청킹 실행
```bash
# 필요한 패키지 설치 (처음 1회)
pip install pymilvus sentence-transformers pandas psycopg2-binary

# 청킹 스크립트 실행
cd c:\Users\미소정보기술\airflow-practice
python dags/chunking.py
```

**또는 Docker 컨테이너 내에서:**
```bash
docker-compose exec airflow-webserver python /opt/airflow/dags/chunking.py
```

---

## 📝 PostgreSQL 데이터 확인

### 테이블 구조

#### 1️⃣ **case_master** (법률 마스터 정보)
```sql
SELECT case_id, case_name, LENGTH(full_text) as text_length 
FROM case_master;

-- 결과 예시:
-- case_id | case_name | text_length
-- 19592   | 10.27법난... | 1245
```

#### 2️⃣ **case_chunks** (청킹된 데이터)
```sql
SELECT id, case_id, level, LENGTH(content) as content_length
FROM case_chunks
ORDER BY level, id
LIMIT 10;

-- 결과 예시:
-- id | case_id | level  | content_length
-- 1  | 19592   | 조     | 234
-- 2  | 19592   | 조     | 189
-- 3  | 19592   | 항/호  | 45
```

---

## 🔍 Milvus 벡터 DB 확인

### Attu UI 접속
```
URL: http://localhost:8000
```

### 확인 항목
1. **Database 선택**: `legal_db`
2. **Collection 선택**: `legal_chunks_v1`
3. **데이터 확인**:
   - 총 청크 수
   - 임베딩 벡터 (384차원)
   - 수준별 분포 (조/항호)

### 벡터 검색 예시
```python
from pymilvus import connections, Collection

connections.connect(host="192.168.1.222", port=19530)
from pymilvus import db
db.using_database("legal_db")

collection = Collection("legal_chunks_v1")

# 유사한 법률 조항 검색
query_text = "피해자의 명예 회복"
```

---

## 📊 출력 예시

청킹 스크립트 실행 결과:
```
🚀🚀🚀🚀🚀🚀🚀🚀🚀🚀🚀🚀🚀🚀🚀🚀🚀🚀🚀🚀🚀🚀🚀🚀🚀🚀🚀🚀🚀🚀
📚 법률 문서 청킹 파이프라인 시작
🚀🚀🚀🚀🚀🚀🚀🚀🚀🚀🚀🚀🚀🚀🚀🚀🚀🚀🚀🚀🚀🚀🚀🚀🚀🚀🚀🚀🚀🚀

============================================================
📚 PostgreSQL에서 데이터 로드 시작
============================================================

1️⃣  법률 마스터 데이터 조회...
✓ 조회된 법률 1개:
  case_id   case_name
  19592     10.27법난 피해자의 명예회복 등에 관한 법률

2️⃣  청크 데이터 조회...
✓ 조회된 청크 총 3개:
  - 조 단위: 2개
  - 항/호 단위: 1개

...

============================================================
🧠 임베딩 생성 및 Milvus 저장
============================================================

1️⃣  임베딩 모델 로드 중... (all-MiniLM-L6-v2)
✓ 모델 로드 완료 (384차원)

2️⃣  3개 청크의 임베딩 생성 중...
✓ 임베딩 생성 완료: (3, 384)

4️⃣  Milvus Collection에 데이터 삽입...
✓ 데이터 삽입 완료!
  - 삽입된 행: 3
  - Primary Keys (샘플): [1, 2, 3]

✨✨✨✨✨✨✨✨✨✨✨✨✨✨✨✨✨✨✨✨✨✨✨✨✨✨✨✨✨✨
✅ 청킹 파이프라인 완료!
✨✨✨✨✨✨✨✨✨✨✨✨✨✨✨✨✨✨✨✨✨✨✨✨✨✨✨✨✨✨

📊 다음 단계:
  1. Attu UI 접속: http://localhost:8000
  2. Database: legal_db 선택
  3. Collection: legal_chunks_v1 클릭
  4. 벡터 검색으로 유사한 법률 조항 검색
```

---

## 🔧 트러블슈팅

### ❌ 문제: "Milvus 연결 실패"
```
✗ Milvus 연결 실패: Connection refused
```

**해결책:**
- Milvus 서버가 실행 중인지 확인
- IP/포트 확인: `192.168.1.222:19530`
- 방화벽 확인

### ❌ 문제: "PostgreSQL 데이터 없음"
```
✗ 처리할 데이터가 없습니다. 먼저 PDF ETL 파이프라인을 실행하세요.
```

**해결책:**
- 먼저 `pdf_legal_etl_v1` DAG 실행
- PostgreSQL에 `case_chunks` 테이블 확인

### ❌ 문제: "임베딩 생성 실패"
```
✗ 임베딩 생성/저장 실패: ModuleNotFoundError: No module named 'sentence_transformers'
```

**해결책:**
```bash
pip install sentence-transformers torch
```

---

## 📈 성능 및 최적화

| 항목 | 값 |
|------|-----|
| 임베딩 모델 | all-MiniLM-L6-v2 |
| 임베딩 차원 | 384 |
| Milvus 인덱스 | IVF_FLAT (nlist=128) |
| 거리 메트릭 | L2 |
| 데이터베이스 | legal_db |

---

## 📚 관련 파일

- **청킹 스크립트**: `dags/chunking.py`
- **PDF ETL**: `dags/pdf_to_postgres_etl.py`
- **DAG 등록**: `dags/legal_etl_pipeline.py`

---

## 🎓 다음 단계

1. ✅ PDF ETL 파이프라인 실행 (데이터 수집)
2. ✅ 청킹 파이프라인 실행 (벡터 생성)
3. ⏳ 벡터 검색 API 개발
4. ⏳ LLM 통합 (Claude + RAG)
5. ⏳ 웹 UI 구축 (Streamlit/FastAPI)
