"""
Legal ETL Pipeline for Korean Law & Court Precedent RAG System

이 DAG는 국가법령정보센터에서 판례 XML 데이터를 수집하여
PostgreSQL에 계층적 구조(조/항/문)로 저장합니다.

Data Flow:
  Extract (크롤링) → Transform (파싱) → Load (DB 저장) → Verify (검증)

Hierarchical Structure:
  Parent (조/Article): 판시사항 [1], [2] 등의 주요 항목
  Child (문/Sentence): 각 조를 200자씩 분할한 문장 단위
"""

from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.providers.postgres.hooks.postgres import PostgresHook
from datetime import datetime
import requests
from bs4 import BeautifulSoup
import re
import logging
import pandas as pd

logger = logging.getLogger(__name__)

# ============================================================================
# Configuration
# ============================================================================
LEGAL_API_BASE = 'https://www.law.go.kr/LSW/precInfoP.do?precSeq={id}&mode=0&vSct=*'
DEFAULT_CASE_IDS = ['64441']  # 예시용 판례 ID
CHUNK_SENTENCE_SIZE = 200     # 문 단위 청크 크기

# 테스트용 샘플 데이터 (실제 API 대신 사용)
SAMPLE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<판례>
    <판례정보일련번호>64441</판례정보일련번호>
    <사건명>사건명 테스트</사건명>
    <판례내용>
        <판시사항>
            [1] 민법상 배우자는 법률혼 배우자를 의미한다는 점에서 혼인이 유효하게 성립하지 않으면 법률상 배우자가 아니라는 것을 의미한다.
            [2] 구 민법 제835조 제1항이 정한 친생자의 요건은 첫째, 부모가 혼인 중에 있어야 하고, 둘째, 자녀가 혼인 중에 태어나야 한다는 것이다.
        </판시사항>
    </판례내용>
</판례>
"""

# ============================================================================
# Helper Functions
# ============================================================================

def parse_xml_to_master(soup):
    """XML에서 판례 마스터 정보를 추출합니다."""
    # 다양한 태그명 시도
    case_id_elem = (soup.find('판례정보일련번호') or 
                    soup.find('procSeq') or 
                    soup.find('id'))
    
    if not case_id_elem or not case_id_elem.text:
        logger.warning("⚠ case_id not found - parsing HTML structure")
        # HTML에서 추출 시도
        case_id = 'UNKNOWN'
    else:
        case_id = case_id_elem.text.strip()
    
    title_elem = soup.find('사건명') or soup.find('caseNm')
    title = title_elem.text.strip() if title_elem else "N/A"
    
    content_elem = soup.find('판례내용') or soup.find('prec')
    content = content_elem.get_text() if content_elem else ""
    
    logger.info(f"→ Parsed: case_id={case_id}, title={title[:50] if title else 'N/A'}...")
    
    if not content or len(content) < 10:
        logger.warning(f"⚠ Minimal content found: {len(content)} bytes")
    
    return {
        'case_id': case_id if case_id != 'UNKNOWN' else f"case_{id(soup)}",
        'title': title,
        'full_text': content,
    } if content and len(content) > 10 else None


def split_into_chunks(article_text, parent_chunk_id, case_id):
    """조 단위 텍스트를 조/문 단위로 분할합니다."""
    # 부모 청크 (조)
    yield (parent_chunk_id, case_id, '조', article_text, case_id)
    
    # 자식 청크 (문)
    sentences = [
        article_text[i:i+CHUNK_SENTENCE_SIZE]
        for i in range(0, len(article_text), CHUNK_SENTENCE_SIZE)
    ]
    
    for sent_idx, sentence in enumerate(sentences):
        if sentence.strip():
            sentence_chunk_id = f"{parent_chunk_id}_문_{sent_idx+1}"
            yield (sentence_chunk_id, case_id, '문', sentence.strip(), parent_chunk_id)

# ============================================================================
# Task Functions
# ============================================================================

def setup_database():
    """PostgreSQL 테이블을 생성합니다."""
    pg_hook = PostgresHook(postgres_conn_id='postgres_default')
    connection = pg_hook.get_sqlalchemy_engine()
    
    with connection.begin() as conn:
        # Master table
        master_sql = """
        CREATE TABLE IF NOT EXISTS legal_master (
            case_id VARCHAR(50) PRIMARY KEY,
            title VARCHAR(500),
            full_text TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """
        
        # Chunks table
        chunks_sql = """
        CREATE TABLE IF NOT EXISTS legal_chunks (
            chunk_id VARCHAR(100) PRIMARY KEY,
            case_id VARCHAR(50) NOT NULL REFERENCES legal_master(case_id) ON DELETE CASCADE,
            level VARCHAR(20) NOT NULL,
            content TEXT NOT NULL,
            parent_id VARCHAR(100),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_legal_chunks_case ON legal_chunks(case_id);
        CREATE INDEX IF NOT EXISTS idx_legal_chunks_level ON legal_chunks(level);
        """
        
        conn.execute(master_sql)
        conn.execute(chunks_sql)
        logger.info("✓ Tables created successfully")


def extract_legal_data(**kwargs):
    """국가법령정보센터에서 판례 XML을 크롤링합니다."""
    raw_xml_list = []
    headers = {'User-Agent': 'Mozilla/5.0'}
    ti = kwargs['ti']
    
    logger.info(f"⏳ Starting extraction for {len(DEFAULT_CASE_IDS)} case IDs...")
    
    for case_id in DEFAULT_CASE_IDS:
        try:
            url = LEGAL_API_BASE.format(id=case_id)
            logger.info(f"→ Fetching: {url}")
            response = requests.get(url, headers=headers, timeout=10)
            
            if response.status_code == 200:
                response.encoding = 'utf-8'
                content = response.text
                raw_xml_list.append(content)
                logger.info(f"✓ Extracted: {case_id} ({len(content)} bytes)")
            else:
                logger.warning(f"✗ Failed {case_id}: HTTP {response.status_code}")
        except Exception as e:
            logger.error(f"✗ Error extracting {case_id}: {type(e).__name__}: {str(e)}")
    
    # 테스트용: 실제 데이터가 없으면 샘플 사용
    if not raw_xml_list:
        logger.warning("⚠ No data extracted from API! Using SAMPLE_XML for testing...")
        raw_xml_list = [SAMPLE_XML]
    
    # 모든 경우에 XCom에 저장
    logger.info(f"📊 Pushing {len(raw_xml_list)} documents to XCom...")
    ti.xcom_push(key='xml_data', value=raw_xml_list)
    logger.info(f"✓ XCom push successful ({len(raw_xml_list)} items)")
    return len(raw_xml_list)


def transform_and_load(**kwargs):
    """XML을 파싱하여 PostgreSQL에 저장합니다."""
    pg_hook = PostgresHook(postgres_conn_id='postgres_default')
    ti = kwargs['ti']
    raw_xmls = ti.xcom_pull(task_ids='extract', key='xml_data')
    
    logger.info(f"📥 XCom pull result: {type(raw_xmls)} - {len(raw_xmls) if raw_xmls else 0} items")

    if not raw_xmls:
        logger.warning("⚠ No data to process! XCom pull returned None or empty list.")
        return

    logger.info(f"⏳ Processing {len(raw_xmls)} documents...")
    connection = pg_hook.get_sqlalchemy_engine()
    inserted_masters = 0
    inserted_chunks = 0

    for idx, xml_content in enumerate(raw_xmls):
        try:
            if not xml_content or len(xml_content) < 10:
                logger.warning(f"⚠ Document {idx}: Empty or too short ({len(xml_content)} bytes)")
                continue
                
            soup = BeautifulSoup(xml_content, 'lxml-xml')
            master_info = parse_xml_to_master(soup)
            
            if not master_info:
                logger.warning(f"⚠ Document {idx}: Missing case_id or parsing failed")
                continue
            
            case_id = master_info['case_id']
            logger.info(f"→ Processing case: {case_id}")
            
            with connection.begin() as conn:
                # Master table insert
                master_sql = """
                INSERT INTO legal_master (case_id, title, full_text)
                VALUES (%s, %s, %s)
                ON CONFLICT (case_id) DO UPDATE SET title = EXCLUDED.title;
                """
                conn.execute(master_sql, (case_id, master_info['title'], master_info['full_text']))
                inserted_masters += 1
                logger.info(f"✓ Inserted master: {case_id}")

                # Chunks table insert
                precepts_elem = soup.find('판시사항')
                if precepts_elem:
                    precepts_text = precepts_elem.get_text()
                    articles = re.findall(r'(\[\d+\].+?)(?=\[\d+\]|$)', precepts_text, re.DOTALL)
                    
                    chunk_sql = """
                    INSERT INTO legal_chunks (chunk_id, case_id, level, content, parent_id)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (chunk_id) DO UPDATE SET content = EXCLUDED.content;
                    """
                    
                    for art_idx, article in enumerate(articles):
                        article_clean = article.strip()
                        if not article_clean:
                            continue
                        
                        parent_chunk_id = f"{case_id}_조_{art_idx+1}"
                        
                        for chunk_data in split_into_chunks(article_clean, parent_chunk_id, case_id):
                            conn.execute(chunk_sql, chunk_data)
                            inserted_chunks += 1
                        
                        logger.info(f"✓ Inserted chunks for article {art_idx+1}")
                else:
                    logger.warning(f"⚠ No 판시사항 found in case {case_id}")
                    
        except Exception as e:
            logger.error(f"✗ Error processing document {idx}: {type(e).__name__}: {str(e)}")
            continue
    
    logger.info(f"📊 Summary: {inserted_masters} masters, {inserted_chunks} chunks inserted")


def verify_data():
    """DB 저장 결과를 검증합니다."""
    pg_hook = PostgresHook(postgres_conn_id='postgres_default')
    connection = pg_hook.get_sqlalchemy_engine()
    
    with connection.begin() as conn:
        master_count = pd.read_sql("SELECT COUNT(*) as cnt FROM legal_master;", conn)
        chunks_count = pd.read_sql("SELECT COUNT(*) as cnt FROM legal_chunks;", conn)
        level_dist = pd.read_sql("SELECT level, COUNT(*) as cnt FROM legal_chunks GROUP BY level ORDER BY level;", conn)
        
        logger.info(f"✓ Master records: {master_count['cnt'].values[0]}")
        logger.info(f"✓ Total chunks: {chunks_count['cnt'].values[0]}")
        logger.info(f"✓ Level distribution:\n{level_dist.to_string(index=False)}")

# ============================================================================
# DAG Definition
# ============================================================================

with DAG(
    dag_id='legal_etl_pipeline_v1',
    description='Legal-Link: 법령/판례 RAG 시스템 ETL 파이프라인',
    start_date=datetime(2025, 1, 1),
    schedule_interval=None,
    catchup=False,
    tags=['legal', 'rag', 'etl'],
) as dag:

    setup_task = PythonOperator(
        task_id='setup',
        python_callable=setup_database,
        retries=1,
        doc="PostgreSQL 테이블 초기화",
    )
    
    extract_task = PythonOperator(
        task_id='extract',
        python_callable=extract_legal_data,
        retries=2,
        doc="국가법령정보센터에서 판례 XML 크롤링",
    )

    load_task = PythonOperator(
        task_id='load',
        python_callable=transform_and_load,
        retries=1,
        doc="XML 파싱 및 PostgreSQL 저장",
    )

    verify_task = PythonOperator(
        task_id='verify',
        python_callable=verify_data,
        doc="데이터 검증 및 통계",
    )

    setup_task >> extract_task >> load_task >> verify_task
