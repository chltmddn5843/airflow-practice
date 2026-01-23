# Legal ETL DAG 코드 점검 보고서

**파일**: `dags/legal_etl_full.py`  
**상태**: ✅ PostgreSQL로 변경 완료  
**DAG 이름**: `legal_full_etl_v1`

---

## 🔴 발견된 주요 오류 (수정됨)

### 1. **데이터베이스 시스템 불일치** ⚠️
| 문제 | 원본 | 변경됨 |
|------|------|-------|
| Hook | `MySqlHook('my_mariadb')` | `PostgresHook('postgres_default')` |
| 테이블명 | 대문자 (MariaDB) | 소문자 (PostgreSQL 스타일) |
| INSERT 문법 | `ON DUPLICATE KEY UPDATE` | `ON CONFLICT ... DO UPDATE` |

### 2. **None 체크 누락** ✅ 수정됨
```python
# Before: XML 파싱 후 즉시 .text 호출 → NoneType 오류
case_id = int(soup.find('판례정보일련번호').text)

# After: None 안전성 확보
case_id_elem = soup.find('판례정보일련번호')
if not case_id_elem or not case_id_elem.text:
    logger.warning(f"Missing case_id in document {idx}")
    continue
```

### 3. **계층 구조 분류 개선** ✅ 수정됨
```python
# 기존: 모든 chunk를 '조'로만 분류
for item in items:
    chunk_sql = "INSERT INTO case_chunks (case_id, level, content) VALUES (%s, %s, %s)"
    pg_hook.run(chunk_sql, parameters=(case_id, '조', item.strip()))

# 개선된 버전:
# - 부모 청크 (조): [1], [2] 단위로 추출
# - 자식 청크 (문): 각 조를 200자씩 분할하여 문 단위 생성
# - parent_id로 계층 관계 유지
```

### 4. **에러 처리 추가** ✅
- 네트워크 타임아웃: `timeout=10`
- 크롤링 실패 로깅: 상태 코드별 경고
- XML 파싱 예외: try-except로 안전하게 처리

---

## ✅ 현재 DAG 구조

### Tasks 흐름도
```
setup_db → extract_step → load_step → verify_data
```

### 각 Task 설명

| Task | 기능 | 재시도 |
|------|------|--------|
| `setup_db` | PostgreSQL 테이블 생성 (legal_master, legal_chunks) | 1회 |
| `extract_step` | 국가법령정보센터에서 XML 크롤링 | 2회 |
| `load_step` | XML 파싱 후 DB에 적재 | 1회 |
| `verify_data` | 적재 결과 통계 출력 | 0회 |

---

## 📊 데이터베이스 스키마

### legal_master (부모 테이블)
```
case_id (VARCHAR 50)      → 판례정보일련번호 (Primary Key)
title (VARCHAR 500)        → 사건명
full_text (TEXT)          → 판례내용 전문
created_at (TIMESTAMP)    → 기록 시간
```

### legal_chunks (자식 테이블 - 계층 구조)
```
chunk_id (VARCHAR 100)    → 청크 고유 ID (조_1, 조_1_문_1 등)
case_id (VARCHAR 50)      → FK to legal_master
level (VARCHAR 20)        → '조' 또는 '문' (Parent-Document Retrieval 용)
content (TEXT)            → 실제 텍스트
parent_id (VARCHAR 100)   → 부모 청크 참조 (null이면 root)
created_at (TIMESTAMP)    → 기록 시간

인덱스:
- idx_legal_chunks_case (case_id) → 판례별 검색 고속화
- idx_legal_chunks_level (level)  → 레벨별 검색 고속화
```

---

## 🔍 DB 저장 검증 방법

### 1. 직접 PostgreSQL 접근 (Docker)
```bash
docker exec airflow-practice-postgres-1 psql -U airflow -d airflow -c \
  "SELECT case_id, title FROM legal_master LIMIT 5;"
```

### 2. Airflow UI에서 확인
- Airflow 웹: http://localhost:8080
- DAG: `legal_full_etl_v1` 클릭
- Task `verify_data` 로그 확인 → 레벨별 청크 통계 출력

### 3. 계층 구조 검증
```bash
docker exec airflow-practice-postgres-1 psql -U airflow -d airflow -c \
  "SELECT level, COUNT(*) FROM legal_chunks GROUP BY level;"
```

**예상 결과**:
```
 level | count
-------+-------
 조    |   5
 문    |  25
```

---

## 🚀 실행 방법

### 방법 1: Airflow UI에서 수동 실행
1. http://localhost:8080 접속
2. `legal_full_etl_v1` DAG 검색
3. "Trigger DAG" 클릭
4. 몇 초 후 Tasks 상태 업데이트 확인

### 방법 2: CLI에서 실행
```bash
docker exec airflow-practice-airflow-scheduler-1 \
  airflow dags trigger legal_full_etl_v1
```

### 방법 3: 로그 실시간 확인
```bash
docker exec airflow-practice-airflow-scheduler-1 \
  airflow tasks log legal_full_etl_v1 verify_data
```

---

## ⚠️ 알려진 제한사항

1. **Single Record 테스트**
   - `target_ids = ['64441']` → 고정값
   - 추후 DB 쿼리나 API 검색 결과로 확장 권장

2. **문 단위 분할 로직**
   - 현재: 조(Article)를 200자씩 분할 → 문(Sentence) 생성
   - 개선 필요: 온점(。), 줄바꿈 등 의미 단위 분할

3. **네트워크 의존성**
   - law.go.kr 접근 불가 시 DAG 실패
   - Fallback 데이터소스 고려 필요

4. **XCom 크기 제한**
   - 대량 XML 데이터 전달 시 문제 가능 (기본 48MB)
   - 향후 S3/MinIO 같은 외부 스토리지 사용 권장

---

## 📋 다음 단계

### 즉시 확인
- [ ] Airflow UI에서 DAG 실행
- [ ] `verify_data` 로그에서 결과 확인
- [ ] PostgreSQL에 데이터 정상 저장 확인

### 단기 개선
- [ ] 여러 판례 ID 다중 실행
- [ ] 문 단위 분할 정규식 개선
- [ ] 크롤링 속도 최적화 (비동기 처리)

### 장기 로드맵
- [ ] Vector DB (ChromaDB) 임베딩 통합
- [ ] 의도 분류 모델 추가
- [ ] FastAPI/Streamlit UI 구현

---

**수정 완료**: 2026-01-23  
**상태**: ✅ PostgreSQL 호환 및 오류 처리 완료
