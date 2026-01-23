# Legal-Link: Airflow 기반 법령/판례 RAG 챗봇 시스템

Legal-Link: Airflow 기반 법령/판례 RAG 챗봇 시스템본 프로젝트는 국가법령정보센터의 법령 및 판례 데이터를 Airflow를 통해 자동 수집(ETL)하고, 이를 **계층적 구조(조, 항, 문)**로 청킹하여 MariaDB와 Vector DB에 저장한 뒤, Claude 3.5를 이용해 정확한 법률 상담을 제공하는 자율형 RAG 시스템입니다.

## 시스템 아키텍처 (Workflow)Data Pipeline (Airflow)
 법령 및 판례 XML 데이터를 주기적으로 수집 및 정제.Structural Storage (MariaDB): 계층적 메타데이터(조/항/문)를 포함한 관계형 데이터 저장.Retrieval Strategy (Parent-Document Retrieval): 자식 청크(문 단위)로 검색하고 부모 컨텍스트(조 단위)로 답변 생성.Chat Interface: 스트리밍 응답을 지원하는 법률 특화 챗봇 UI.

## 🚀 주요 기능 (Key Features)
1. 지능형 ETL 프로세스 (Airflow)Extract: 국가법령정보센터 API 및 웹 크롤링을 통한 실시간 데이터 수집.Transform: 정규표현식을 활용하여 비정형 XML에서 [조] > [항] > [문] 단위의 계층 구조 추출.Load: MariaDB(메타데이터) 및 ChromaDB(벡터 데이터)에 동시 적재.
2. 계층적 데이터 모델링 (Hierarchy Chunking)Parent-Child Mapping: 법령의 최소 단위인 '문(Sentence)'을 검색용(Child)으로, '조(Article)'를 답변 생성용(Parent) 컨텍스트로 매핑하여 검색 정확도 향상.Metadata Tagging: 각 데이터 조각에 사건번호, 선고일자, 참조조문 등의 정보를 태깅하여 정교한 필터링 지원.
3. 고성능 RAG 엔진 (Claude 3.5 & Stream)Prompt Engineering: 법률 전문가 페르소나를 부여하고, 제공된 컨텍스트 내에서만 답변하도록 가드레일 설정.Streaming UI: 답변 생성 과정을 실시간 스트리밍으로 제공하여 사용자 체감 대기 시간 단축.Source Citation: 답변의 근거가 되는 법령 조항 및 판례 일련번호를 함께 출력하여 신뢰도 확보.

## 🛠 Tech
- StackCategoryTech 
- StackOrchestrationApache
- AirflowDatabaseMariaDB (Metadata)
- ChromaDB (Vector)
- LLMAnthropic Claude 3.5 SonnetFrameworkLangChain
- FastAPI / Streamlit
- **Language : Python 3.10+**
## 📂 데이터베이스 스키마 설계
### 1. LEGAL_MASTER (부모 테이블)
판례나 법령의 전체 정보를 저장하는 마스터 테이블입니다.

| 컬럼명 | 타입 | 제약 조건 | 설명 |
| :--- | :--- | :--- | :--- |
| **CASE_ID** | VARCHAR | PRIMARY KEY | 판례/법령 고유 번호 |
| **TITLE** | VARCHAR | NOT NULL | 사건명 또는 법령명 |
| **FULL_TEXT** | TEXT | - | 원문 전체 데이터 |

### 2. LEGAL_CHUNKS (자식 테이블)
계층별로 분할된 텍스트 데이터를 저장하는 테이블입니다.

| 컬럼명 | 타입 | 제약 조건 | 설명 |
| :--- | :--- | :--- | :--- |
| **CHUNK_ID** | VARCHAR | PRIMARY KEY | 청크 고유 식별자 |
| **PARENT_ID** | VARCHAR | FOREIGN KEY | MASTER 테이블 참조 (CASE_ID) |
| **LEVEL** | VARCHAR | - | 계층 구분 (조/항/문) |
| **CONTENT** | TEXT | NOT NULL | 실제 텍스트 내용 |

## 📈 실행 예시 (Usage)
1. ETL 실행: Airflow 가동을 통해 법령 데이터 로컬 DB 적재 
2. 임베딩: 수집된 데이터를 벡터화하여 Vector Store 구축.
3. 챗봇 질의:Q: "임대차 계약 해지 시 보증금 반환 시점은 언제인가요?"

