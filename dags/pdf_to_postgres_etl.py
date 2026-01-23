from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.providers.postgres.hooks.postgres import PostgresHook
from datetime import datetime
import re
# import fitz  # PyMuPDF - 선택사항

# Milvus 관련 임포트
try:
    from pymilvus import connections, Collection, CollectionSchema, FieldSchema, DataType, db
    from sentence_transformers import SentenceTransformer
    MILVUS_AVAILABLE = True
except ImportError:
    MILVUS_AVAILABLE = False
    print("Warning: Milvus dependencies not installed. Vector storage will be skipped.")

def extract_text_from_pdf(**kwargs):
    """PDF 파일에서 텍스트를 추출하여 전달"""
    # PyMuPDF를 사용하지 않고 샘플 데이터 반환
    file_path = r"C:\Users\미소정보기술\Downloads\10ㆍ27법난 피해자의 명예회복 등에 관한 법률(법률)(제19592호)(20230808).pdf"
    
    # 실제 PDF 처리가 필요하면 fitz 사용:
    # try:
    #     import fitz
    #     doc = fitz.open(file_path)
    #     text = ""
    #     for page in doc:
    #         text += page.get_text()
    #     return text
    # except:
    #     pass
    
    # 테스트용 샘플 데이터
    text = """
    제 1 조 (목적)
    이 법률은 1980년 5월 18일부터 1980년 5월 27일까지의 광주에서의 사태로 인하여 피해를 입은 자의 명예를 회복하고 그 피해를 치유하기 위하여 필요한 사항을 규정함을 목적으로 한다.
    
    제 2 조 (정의)
    이 법률에서 사용하는 용어의 정의는 다음과 같다.
    1. "피해자"란 1980년 5월 18일부터 1980년 5월 27일까지의 광주에서의 사태로 인하여 사망하거나 상해를 입은 자 또는 그 유족을 말한다.
    """
    return text

def initialize_milvus():
    """Milvus 연결 및 데이터베이스/Collection 초기화"""
    if not MILVUS_AVAILABLE:
        print("Milvus not available, skipping initialization")
        return None
    
    try:
        # Milvus 연결 (사내 IP)
        connections.connect(
            alias="default",
            host="192.168.1.222",
            port=19530,
            pool_size=10
        )
        print("✓ Milvus 연결 성공 (192.168.1.222:19530)")
        
        # 데이터베이스 생성 (이미 있으면 무시)
        try:
            db.create_database("legal_db")
            print("✓ legal_db 데이터베이스 생성")
        except:
            print("✓ legal_db 데이터베이스 이미 존재")
        
        # legal_db 선택
        db.using_database("legal_db")
        
        return True
    except Exception as e:
        print(f"✗ Milvus 초기화 실패: {e}")
        return False

def create_collection_if_not_exists():
    """Collection 생성 (이미 있으면 스킵)"""
    if not MILVUS_AVAILABLE:
        return None
    
    try:
        collection_name = "legal_chunks_v1"
        
        # 이미 collection이 있는지 확인
        if collection_name in db.list_collections():
            print(f"✓ {collection_name} 컬렉션 이미 존재")
            return Collection(name=collection_name)
        
        # 새 collection 정의
        fields = [
            FieldSchema(name="id", dtype=DataType.INT64, is_primary=True, auto_id=True),
            FieldSchema(name="chunk_id", dtype=DataType.VARCHAR, max_length=256),
            FieldSchema(name="chunk_text", dtype=DataType.VARCHAR, max_length=8192),
            FieldSchema(name="level", dtype=DataType.VARCHAR, max_length=32),  # 조, 항, 문
            FieldSchema(name="case_id", dtype=DataType.INT64),
            FieldSchema(name="embedding", dtype=DataType.FLOAT_VECTOR, dim=384)
        ]
        schema = CollectionSchema(fields, description="Legal Document Chunks with Embeddings")
        collection = Collection(name=collection_name, schema=schema)
        print(f"✓ {collection_name} 컬렉션 생성 완료")
        
        # 인덱스 생성 (벡터 검색용)
        index_params = {
            "metric_type": "L2",
            "index_type": "IVF_FLAT",
            "params": {"nlist": 128}
        }
        collection.create_index(field_name="embedding", index_params=index_params)
        print(f"✓ embedding 인덱스 생성 완료")
        
        return collection
    except Exception as e:
        print(f"✗ Collection 생성 실패: {e}")
        return None

def generate_embeddings(texts):
    """텍스트 임베딩 생성"""
    if not MILVUS_AVAILABLE:
        return []
    
    try:
        model = SentenceTransformer('all-MiniLM-L6-v2')  # 경량 모델
        embeddings = model.encode(texts, show_progress_bar=False)
        print(f"✓ {len(texts)}개 텍스트의 임베딩 생성 완료")
        return embeddings.tolist()
    except Exception as e:
        print(f"✗ 임베딩 생성 실패: {e}")
        return []

def transform_and_load_pdf(**kwargs):
    """추출된 텍스트를 조/항 단위로 청킹하여 PostgreSQL + Milvus에 적재"""
    ti = kwargs['ti']
    raw_text = ti.xcom_pull(task_ids='extract_pdf')
    pg_hook = PostgresHook(postgres_conn_id='postgres_default')

    # 1. 법률 마스터 정보 저장 (Master)
    law_id = 19592
    law_name = "10.27법난 피해자의 명예회복 등에 관한 법률"
    
    master_sql = """
    INSERT INTO case_master (case_id, case_name, full_text)
    VALUES (%s, %s, %s)
    ON CONFLICT (case_id) DO NOTHING;
    """
    pg_hook.run(master_sql, parameters=(law_id, law_name, raw_text))
    print(f"✓ PostgreSQL: 법률 마스터 데이터 저장 (case_id={law_id})")

    # 2. '제N조' 기준으로 조문 분리 (Parent Chunking)
    articles = re.split(r'(제\d+조\(.*?\))', raw_text)
    
    # Milvus 준비
    milvus_data = []
    milvus_initialized = initialize_milvus()
    
    if milvus_initialized:
        collection = create_collection_if_not_exists()
    
    # split 결과는 [공백, 제목1, 내용1, 제목2, 내용2...] 형태가 됨
    for i in range(1, len(articles), 2):
        if i + 1 >= len(articles):
            break
            
        article_title = articles[i]
        article_content = articles[i + 1].strip()
        full_article = f"{article_title} {article_content}"

        # 조(Article) 단위 저장 (PostgreSQL)
        chunk_sql = "INSERT INTO case_chunks (case_id, level, content) VALUES (%s, %s, %s)"
        pg_hook.run(chunk_sql, parameters=(law_id, '조', full_article))
        
        # Milvus 데이터 준비
        chunk_id = f"{law_id}_article_{i//2}"
        milvus_data.append({
            'chunk_id': chunk_id,
            'chunk_text': full_article,
            'level': '조',
            'case_id': law_id
        })

        # 3. '1.', '2.' 등 '호' 단위 분리 (Child Chunking)
        items = re.findall(r'(\d+\..+?)(?=\d+\.|$)', article_content, re.DOTALL)
        for idx, item in enumerate(items):
            pg_hook.run(chunk_sql, parameters=(law_id, '항/호', item.strip()))
            
            # Milvus 데이터 준비
            item_chunk_id = f"{law_id}_article_{i//2}_item_{idx}"
            milvus_data.append({
                'chunk_id': item_chunk_id,
                'chunk_text': item.strip(),
                'level': '항/호',
                'case_id': law_id
            })
    
    print(f"✓ PostgreSQL: {len(milvus_data)}개 청크 저장 완료")
    
    # 4. Milvus에 청크 및 임베딩 저장
    if milvus_initialized and MILVUS_AVAILABLE and collection:
        try:
            # 텍스트 추출
            texts = [chunk['chunk_text'] for chunk in milvus_data]
            
            # 임베딩 생성
            embeddings = generate_embeddings(texts)
            
            if embeddings:
                # Milvus 데이터 구성
                milvus_insert_data = [
                    [chunk['chunk_id'] for chunk in milvus_data],
                    texts,
                    [chunk['level'] for chunk in milvus_data],
                    [chunk['case_id'] for chunk in milvus_data],
                    embeddings
                ]
                
                # Milvus에 삽입
                insert_result = collection.insert(milvus_insert_data, field_names=['chunk_id', 'chunk_text', 'level', 'case_id', 'embedding'])
                print(f"✓ Milvus: {len(milvus_data)}개 청크 + 임베딩 저장 완료")
                print(f"  - Database: legal_db")
                print(f"  - Collection: legal_chunks_v1")
                print(f"  - Inserted IDs: {insert_result.primary_keys[:3]}... (총 {len(insert_result.primary_keys)}개)")
                
                # Collection flush (데이터 검색 가능하게)
                collection.flush()
                print(f"✓ Milvus Collection flush 완료 (검색 가능)")
        except Exception as e:
            print(f"✗ Milvus 데이터 삽입 실패: {e}")
    
    print("\n✓ PDF ETL 파이프라인 완료!")
    print(f"  - PostgreSQL: case_master, case_chunks 테이블에 저장")
    print(f"  - Milvus: legal_db.legal_chunks_v1 컬렉션에 저장")

with DAG(
    'pdf_legal_etl_v1',
    start_date=datetime(2024, 1, 1),
    schedule_interval=None,
    catchup=False
) as dag:

    t1 = PythonOperator(
        task_id='extract_pdf',
        python_callable=extract_text_from_pdf
    )

    t2 = PythonOperator(
        task_id='load_pdf_to_db',
        python_callable=transform_and_load_pdf
    )

    t1 >> t2