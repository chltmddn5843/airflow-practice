try:
    from pymilvus import connections, Collection, FieldSchema, CollectionSchema, DataType, db
    from sentence_transformers import SentenceTransformer
    MILVUS_AVAILABLE = True
except ImportError:
    MILVUS_AVAILABLE = False

from airflow.providers.postgres.hooks.postgres import PostgresHook
import pandas as pd
import logging

logger = logging.getLogger(__name__)

def load_from_postgres_and_chunk():
    """PostgreSQL에서 법률 데이터를 가져와서 청킹"""
    
    print("\n" + "="*60)
    print("📚 PostgreSQL에서 데이터 로드 시작")
    print("="*60)
    
    try:
        pg_hook = PostgresHook(postgres_conn_id='postgres_default')
        
        # 1. 법률 마스터 데이터 확인
        print("\n1️⃣  법률 마스터 데이터 조회...")
        master_sql = "SELECT case_id, case_name, full_text FROM case_master LIMIT 10"
        master_df = pg_hook.get_pandas_df(master_sql)
        print(f"✓ 조회된 법률 {len(master_df)}개:")
        print(master_df[['case_id', 'case_name']].to_string())
        
        # 2. 청크 데이터 확인
        print("\n2️⃣  청크 데이터 조회...")
        chunk_sql = """
            SELECT id, case_id, level, content 
            FROM case_chunks 
            LIMIT 20
        """
        chunk_df = pg_hook.get_pandas_df(chunk_sql)
        print(f"✓ 조회된 청크 총 {len(chunk_df)}개:")
        print(f"  - 조 단위: {len(chunk_df[chunk_df['level']=='조'])}개")
        print(f"  - 항/호 단위: {len(chunk_df[chunk_df['level']=='항/호'])}개")
        
        if len(chunk_df) > 0:
            print("\n📄 샘플 청크 데이터:")
            for idx, row in chunk_df.head(3).iterrows():
                print(f"\n   [{row['level']}] Case {row['case_id']} - ID {row['id']}")
                print(f"   내용: {row['content'][:100]}...")
        
        return master_df, chunk_df
    
    except Exception as e:
        print(f"✗ PostgreSQL 로드 실패: {e}")
        return None, None

def initialize_milvus_collection():
    """Milvus Collection 초기화"""
    
    print("\n" + "="*60)
    print("🔌 Milvus Collection 초기화")
    print("="*60)
    
    try:
        # Milvus 연결
        print("\n1️⃣  Milvus 연결 (192.168.1.222:19530)...")
        connections.connect(
            alias="default",
            host="192.168.1.222",
            port=19530,
            pool_size=10
        )
        print("✓ Milvus 연결 성공")
        
        # 데이터베이스 생성
        print("\n2️⃣  legal_db 데이터베이스 확인...")
        try:
            db.create_database("legal_db")
            print("✓ legal_db 데이터베이스 생성 완료")
        except:
            print("✓ legal_db 데이터베이스 이미 존재")
        
        db.using_database("legal_db")
        
        # Collection 확인/생성
        print("\n3️⃣  legal_chunks_v1 Collection 확인...")
        collection_name = "legal_chunks_v1"
        
        if collection_name in db.list_collections():
            print(f"✓ {collection_name} Collection 이미 존재")
            collection = Collection(name=collection_name)
        else:
            # 새 Collection 생성
            fields = [
                FieldSchema(name="id", dtype=DataType.INT64, is_primary=True, auto_id=True),
                FieldSchema(name="chunk_id", dtype=DataType.VARCHAR, max_length=256),
                FieldSchema(name="case_id", dtype=DataType.INT64),
                FieldSchema(name="level", dtype=DataType.VARCHAR, max_length=32),
                FieldSchema(name="content", dtype=DataType.VARCHAR, max_length=8192),
                FieldSchema(name="embedding", dtype=DataType.FLOAT_VECTOR, dim=384)
            ]
            schema = CollectionSchema(fields, description="Legal Document Chunks")
            collection = Collection(name=collection_name, schema=schema)
            
            # 인덱스 생성
            index_params = {
                "metric_type": "L2",
                "index_type": "IVF_FLAT",
                "params": {"nlist": 128}
            }
            collection.create_index(field_name="embedding", index_params=index_params)
            print(f"✓ {collection_name} Collection 생성 완료")
        
        return collection
    
    except Exception as e:
        print(f"✗ Milvus 초기화 실패: {e}")
        return None

def generate_and_store_embeddings(chunk_df, collection):
    """청크 데이터의 임베딩을 생성하고 Milvus에 저장"""
    
    print("\n" + "="*60)
    print("🧠 임베딩 생성 및 Milvus 저장")
    print("="*60)
    
    try:
        # 1. 임베딩 모델 로드
        print("\n1️⃣  임베딩 모델 로드 중... (all-MiniLM-L6-v2)")
        model = SentenceTransformer('all-MiniLM-L6-v2')
        print("✓ 모델 로드 완료 (384차원)")
        
        # 2. 텍스트 임베딩 생성
        print(f"\n2️⃣  {len(chunk_df)}개 청크의 임베딩 생성 중...")
        contents = chunk_df['content'].tolist()
        embeddings = model.encode(contents, show_progress_bar=True)
        print(f"✓ 임베딩 생성 완료: {embeddings.shape}")
        
        # 3. Milvus에 데이터 준비
        print("\n3️⃣  Milvus 삽입 데이터 준비 중...")
        milvus_data = [
            [f"{row['case_id']}_chunk_{row['id']}" for _, row in chunk_df.iterrows()],
            chunk_df['case_id'].tolist(),
            chunk_df['level'].tolist(),
            contents,
            embeddings.tolist()
        ]
        print("✓ 데이터 준비 완료")
        
        # 4. Milvus에 삽입
        print("\n4️⃣  Milvus Collection에 데이터 삽입...")
        insert_result = collection.insert(
            milvus_data,
            field_names=['chunk_id', 'case_id', 'level', 'content', 'embedding']
        )
        
        print(f"✓ 데이터 삽입 완료!")
        print(f"  - 삽입된 행: {len(insert_result.primary_keys)}")
        print(f"  - Primary Keys (샘플): {insert_result.primary_keys[:5]}")
        
        # 5. Collection flush
        print("\n5️⃣  Collection flush (검색 가능하게 만들기)...")
        collection.flush()
        print("✓ Flush 완료")
        
        # 6. 통계 정보 출력
        print("\n6️⃣  Collection 통계:")
        print(f"  - Database: legal_db")
        print(f"  - Collection: legal_chunks_v1")
        print(f"  - 총 청크 수: {collection.num_entities}")
        print(f"  - 수준별 분포:")
        for level in chunk_df['level'].unique():
            count = len(chunk_df[chunk_df['level'] == level])
            print(f"    • {level}: {count}개")
        
        return True
    
    except Exception as e:
        print(f"✗ 임베딩 생성/저장 실패: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    """메인 함수: PostgreSQL → Chunking → Milvus"""
    
    if not MILVUS_AVAILABLE:
        print("✗ Milvus 의존성이 설치되지 않았습니다.")
        print("  설치: pip install pymilvus sentence-transformers")
        return False
    
    print("\n" + "🚀"*30)
    print("📚 법률 문서 청킹 파이프라인 시작")
    print("🚀"*30)
    
    # 1단계: PostgreSQL에서 데이터 로드
    master_df, chunk_df = load_from_postgres_and_chunk()
    
    if chunk_df is None or len(chunk_df) == 0:
        print("\n✗ 처리할 데이터가 없습니다. 먼저 PDF ETL 파이프라인을 실행하세요.")
        return False
    
    # 2단계: Milvus Collection 초기화
    collection = initialize_milvus_collection()
    
    if collection is None:
        print("\n✗ Milvus Collection 초기화 실패")
        return False
    
    # 3단계: 임베딩 생성 및 저장
    success = generate_and_store_embeddings(chunk_df, collection)
    
    if success:
        print("\n" + "✨"*30)
        print("✅ 청킹 파이프라인 완료!")
        print("✨"*30)
        print("\n📊 다음 단계:")
        print("  1. Attu UI 접속: http://localhost:8000")
        print("  2. Database: legal_db 선택")
        print("  3. Collection: legal_chunks_v1 클릭")
        print("  4. 벡터 검색으로 유사한 법률 조항 검색")
        return True
    else:
        print("\n✗ 청킹 파이프라인 실패")
        return False

if __name__ == "__main__":
    main()

# ============================================================
# Airflow DAG 정의
# ============================================================

from airflow import DAG
from airflow.operators.python import PythonOperator
from datetime import datetime

def chunk_data_task(**kwargs):
    """Airflow 태스크로 사용할 청킹 함수"""
    main()

if MILVUS_AVAILABLE:
    with DAG(
        dag_id='legal_chunking_milvus_v1',
        description='PostgreSQL의 법률 데이터를 Milvus로 청킹',
        start_date=datetime(2024, 1, 1),
        schedule_interval=None,  # 수동 트리거
        catchup=False,
        tags=['legal', 'chunking', 'milvus']
    ) as dag:
        
        chunking_task = PythonOperator(
            task_id='chunk_legal_documents',
            python_callable=chunk_data_task,
            op_kwargs={},
            provide_context=True
        )
else:
    logger.warning("청킹 DAG 로드 실패: Milvus 의존성 누락 (pymilvus, sentence-transformers)")
    dag = None