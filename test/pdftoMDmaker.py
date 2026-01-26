import fitz  # PyMuPDF
import re
import logging
import json
import os
import sys
from datetime import datetime
from uuid import uuid4
from typing import List, Dict, Optional
from pathlib import Path

# UTF-8 인코딩 강제
if sys.stdout.encoding != 'utf-8':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# Database imports
import psycopg2
from psycopg2.extras import execute_batch
try:
    from pymilvus import Collection, connections, MilvusException
except ImportError:
    MilvusException = Exception  # Fallback

# LangChain imports
try:
    from langchain.text_splitter import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter
    from langchain.embeddings import OpenAIEmbeddings  # 또는 다른 임베딩 모델
except ImportError as e:
    logger_init = logging.getLogger(__name__)
    logger_init.warning(f"⚠ LangChain import 실패: {str(e)}")

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


def pdf_to_markdown(pdf_path):
    """
    PDF 파일을 마크다운 형식으로 정규화합니다.
    
    Args:
        pdf_path (str): PDF 파일 경로
        
    Returns:
        tuple: (마크다운 텍스트, 메타데이터)
    """
    import sys
    import locale
    
    try:
        doc = fitz.open(pdf_path)
    except Exception as e:
        logger.error(f"✗ PDF 열기 실패: {str(e)}")
        return None, None
    
    md_text = ""
    metadata = {
        "file_path": pdf_path,
        "total_pages": len(doc),
        "extraction_time": datetime.now().isoformat(),
    }
    
    # Debug: 인코딩 정보
    logger.info(f"📋 System encoding: {sys.getdefaultencoding()}, Locale: {locale.getpreferredencoding()}")
    
    # 1. 전체 텍스트 추출 (UTF-8 강제)
    full_content = ""
    for page_num, page in enumerate(doc):
        text = page.get_text(output='text')  # 명시적 텍스트 모드
        # 인코딩 보정
        try:
            if isinstance(text, bytes):
                text = text.decode('utf-8', errors='replace')
        except:
            pass
        full_content += text
    
    # 2. 법률명을 대제목(#)으로 변환
    lines = full_content.split('\n')
    title = lines[0].strip() if lines else "법률명 미정"
    md_text += f"# {title}\n\n"
    metadata["document_title"] = title
    
    # 3. '제N조' 패턴을 찾아 중제목(##)으로 변환
    content_body = '\n'.join(lines[1:])
    processed_body = re.sub(r'(제\d+조\([^)]*\))', r'\n## \1\n', content_body)
    
    # 4. 번호 매김 목록 정규화
    processed_body = re.sub(r'\n(\d+\.)', r'\n- \1', processed_body)
    
    # 5. 공백 정규화 (여러 개 줄바꿈 → 2개로 통일)
    processed_body = re.sub(r'\n\n+', r'\n\n', processed_body)
    
    md_text += processed_body
    
    logger.info(f"✓ PDF → Markdown 변환 완료: {title} ({len(doc)} 페이지)")
    
    return md_text, metadata


def save_markdown_to_file(md_text: str, output_dir: str = "./output", filename: str = None) -> Optional[str]:
    """
    마크다운 텍스트를 파일로 저장합니다.
    
    Args:
        md_text (str): 마크다운 텍스트
        output_dir (str): 저장 디렉터리
        filename (str): 파일명 (기본값: timestamp 기반)
        
    Returns:
        str: 저장된 파일 경로, 실패 시 None
    """
    try:
        # 디렉터리 생성
        Path(output_dir).mkdir(parents=True, exist_ok=True)
        
        # 파일명 결정
        if not filename:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"document_{timestamp}.md"
        else:
            if not filename.endswith('.md'):
                filename += '.md'
        
        # 전체 경로
        file_path = os.path.join(output_dir, filename)
        
        # 파일 저장 (UTF-8-sig 사용: BOM 포함)
        with open(file_path, 'w', encoding='utf-8-sig') as f:
            f.write(md_text)
        
        file_size = os.path.getsize(file_path)
        logger.info(f"✓ 마크다운 파일 저장 (UTF-8-sig): {file_path} ({file_size} bytes)")
        return file_path
        
    except IOError as e:
        logger.error(f"✗ 파일 저장 실패: {str(e)}")
        return None
    except Exception as e:
        logger.error(f"✗ 예기치 않은 오류: {str(e)}")
        return None


def chunk_markdown_hierarchically(md_text: str, doc_id: str = None) -> List[Dict]:
    """
    마크다운을 계층적으로 청킹합니다.
    
    구조:
    - Parent: 조항 단위 (##)
    - Child: 문장/항 단위 (300자 이내)
    
    Args:
        md_text (str): 마크다운 형식 텍스트
        doc_id (str): 문서 ID (기본값: 자동 생성)
        
    Returns:
        List[Dict]: 계층적 청크 리스트
    """
    if not doc_id:
        doc_id = str(uuid4())
    
    # 부모 단위 분할: ## (제N조) 기준
    headers_to_split_on = [("##", "Article")]
    md_splitter = MarkdownHeaderTextSplitter(headers_to_split_on=headers_to_split_on)
    
    try:
        parent_docs = md_splitter.split_text(md_text)
    except Exception as e:
        logger.error(f"✗ 부모 청크 생성 실패: {str(e)}")
        return []

    # 자식 단위 분할: 각 조문을 더 잘게 쪼갬
    child_splitter = RecursiveCharacterTextSplitter(
        chunk_size=300,
        chunk_overlap=50,
        separators=["\n- ", "\n\n", "\n", ". ", " "]
    )

    hierarchical_data = []
    
    for parent_idx, parent in enumerate(parent_docs):
        # 부모의 메타데이터에서 조항 정보 추출
        article_title = parent.metadata.get("Article", f"Article_{parent_idx}")
        parent_id = f"{doc_id}_parent_{parent_idx}"
        
        # 자식 청크 생성
        try:
            child_chunks = child_splitter.split_text(parent.page_content)
        except Exception as e:
            logger.warning(f"⚠ 자식 청크 생성 실패 ({article_title}): {str(e)}")
            child_chunks = [parent.page_content]
        
        # 부모 항목 생성
        parent_entry = {
            "id": parent_id,
            "doc_id": doc_id,
            "type": "parent",
            "level": "조",
            "title": article_title,
            "content": parent.page_content,
            "char_count": len(parent.page_content),
            "created_at": datetime.now().isoformat(),
            "children": []
        }
        
        # 자식 항목 생성
        for child_idx, child_content in enumerate(child_chunks):
            child_id = f"{parent_id}_child_{child_idx}"
            parent_entry["children"].append({
                "id": child_id,
                "parent_id": parent_id,
                "doc_id": doc_id,
                "type": "child",
                "level": "문",
                "sequence": child_idx + 1,
                "content": child_content,
                "char_count": len(child_content),
                "created_at": datetime.now().isoformat(),
            })
        
        hierarchical_data.append(parent_entry)
        logger.info(f"✓ 조항 청킹 완료: {article_title} ({len(parent_entry['children'])} 자식 청크)")
    
    logger.info(f"✓ 전체 계층적 청킹 완료: {len(hierarchical_data)} 부모 항목")
    return hierarchical_data


# ============================================================================
# PostgreSQL 저장소
# ============================================================================

class PostgreSQLStorage:
    """PostgreSQL 저장소 관리"""
    
    def __init__(self, db_config: Dict):
        """
        Args:
            db_config (Dict): DB 연결 설정
        """
        self.db_config = db_config
        self.conn = None
        
    def connect(self):
        """PostgreSQL 연결"""
        try:
            self.conn = psycopg2.connect(**self.db_config)
            logger.info("✓ PostgreSQL 연결 성공")
            return True
        except psycopg2.Error as e:
            logger.error(f"✗ PostgreSQL 연결 실패: {str(e)}")
            return False
    
    def close(self):
        """연결 종료"""
        if self.conn:
            self.conn.close()
            logger.info("✓ PostgreSQL 연결 종료")
    
    def create_tables(self):
        """필요한 테이블 생성"""
        if not self.conn:
            logger.error("✗ 먼저 connect()를 호출하세요")
            return False
        
        cursor = self.conn.cursor()
        
        try:
            # 문서 메타데이터 테이블
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS pdf_documents (
                    doc_id VARCHAR(36) PRIMARY KEY,
                    title VARCHAR(500) NOT NULL,
                    file_path TEXT NOT NULL,
                    total_pages INTEGER,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            
            # 부모 청크 테이블 (조항 단위)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS parent_chunks (
                    id VARCHAR(255) PRIMARY KEY,
                    doc_id VARCHAR(36) NOT NULL REFERENCES pdf_documents(doc_id) ON DELETE CASCADE,
                    title VARCHAR(500),
                    content TEXT NOT NULL,
                    char_count INTEGER,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            
            # 자식 청크 테이블 (문장 단위)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS child_chunks (
                    id VARCHAR(255) PRIMARY KEY,
                    parent_id VARCHAR(255) NOT NULL REFERENCES parent_chunks(id) ON DELETE CASCADE,
                    doc_id VARCHAR(36) NOT NULL REFERENCES pdf_documents(doc_id) ON DELETE CASCADE,
                    sequence INTEGER,
                    content TEXT NOT NULL,
                    char_count INTEGER,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            
            # 인덱스 생성
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_parent_doc_id ON parent_chunks(doc_id);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_child_parent_id ON child_chunks(parent_id);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_child_doc_id ON child_chunks(doc_id);")
            
            self.conn.commit()
            logger.info("✓ PostgreSQL 테이블 생성 완료")
            return True
            
        except psycopg2.Error as e:
            logger.error(f"✗ 테이블 생성 실패: {str(e)}")
            self.conn.rollback()
            return False
        finally:
            cursor.close()
    
    def save_hierarchical_data(self, doc_id: str, title: str, file_path: str, hierarchical_data: List[Dict]) -> bool:
        """계층적 데이터 저장"""
        if not self.conn:
            logger.error("✗ 먼저 connect()를 호출하세요")
            return False
        
        cursor = self.conn.cursor()
        
        try:
            # 1. 문서 메타데이터 저장
            cursor.execute("""
                INSERT INTO pdf_documents (doc_id, title, file_path, total_pages)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (doc_id) DO UPDATE SET updated_at = CURRENT_TIMESTAMP;
            """, (doc_id, title, file_path, len(hierarchical_data)))
            
            # 2. 부모 청크 저장
            parent_data = [
                (item["id"], doc_id, item["title"], item["content"], item["char_count"])
                for item in hierarchical_data
            ]
            
            execute_batch(cursor, """
                INSERT INTO parent_chunks (id, doc_id, title, content, char_count)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET content = EXCLUDED.content;
            """, parent_data)
            
            # 3. 자식 청크 저장
            child_data = []
            for parent in hierarchical_data:
                for child in parent["children"]:
                    child_data.append((
                        child["id"],
                        child["parent_id"],
                        child["doc_id"],
                        child["sequence"],
                        child["content"],
                        child["char_count"]
                    ))
            
            if child_data:
                execute_batch(cursor, """
                    INSERT INTO child_chunks (id, parent_id, doc_id, sequence, content, char_count)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO UPDATE SET content = EXCLUDED.content;
                """, child_data)
            
            self.conn.commit()
            logger.info(f"✓ PostgreSQL 저장: {len(parent_data)} 부모, {len(child_data)} 자식")
            return True
            
        except psycopg2.Error as e:
            logger.error(f"✗ 데이터 저장 실패: {str(e)}")
            self.conn.rollback()
            return False
        finally:
            cursor.close()


# ============================================================================
# Milvus 저장소 (벡터 임베딩)
# ============================================================================

class MilvusStorage:
    """Milvus 벡터 데이터베이스 관리"""
    
    def __init__(self, milvus_host: str = "localhost", milvus_port: int = 19530):
        """
        Args:
            milvus_host (str): Milvus 호스트
            milvus_port (int): Milvus 포트
        """
        self.host = milvus_host
        self.port = milvus_port
        self.collection = None
        self.embeddings_model = None
        
    def connect(self):
        """Milvus 연결"""
        try:
            connections.connect(host=self.host, port=self.port)
            logger.info(f"✓ Milvus 연결 성공 ({self.host}:{self.port})")
            return True
        except MilvusException as e:
            logger.error(f"✗ Milvus 연결 실패: {str(e)}")
            return False
    
    def create_collection(self, collection_name: str = "legal_chunks"):
        """컬렉션 생성"""
        try:
            from pymilvus import FieldSchema, CollectionSchema, DataType
            
            fields = [
                FieldSchema(name="id", dtype=DataType.VARCHAR, max_length=255, is_primary=True),
                FieldSchema(name="doc_id", dtype=DataType.VARCHAR, max_length=36),
                FieldSchema(name="parent_id", dtype=DataType.VARCHAR, max_length=255),
                FieldSchema(name="content", dtype=DataType.VARCHAR, max_length=10000),
                FieldSchema(name="embedding", dtype=DataType.FLOAT_VECTOR, dim=1536),
            ]
            
            schema = CollectionSchema(fields, description="Legal document chunks")
            self.collection = Collection(name=collection_name, schema=schema)
            
            logger.info(f"✓ Milvus 컬렉션 생성: {collection_name}")
            return True
            
        except MilvusException as e:
            logger.error(f"✗ 컬렉션 생성 실패: {str(e)}")
            return False
    
    def insert_embeddings(self, hierarchical_data: List[Dict]) -> bool:
        """
        벡터 임베딩을 Milvus에 삽입
        
        Note: 실제 임베딩은 별도의 모델(OpenAI, BERT 등)이 필요합니다.
        """
        if not self.collection:
            logger.error("✗ 먼저 create_collection()을 호출하세요")
            return False
        
        try:
            entities = []
            
            for parent in hierarchical_data:
                for child in parent["children"]:
                    # TODO: 실제 임베딩 생성 (OpenAI API, Sentence-BERT 등)
                    # embedding = self.embeddings_model.embed_query(child["content"])
                    
                    # 테스트용 더미 임베딩
                    dummy_embedding = [0.0] * 1536
                    
                    entities.append({
                        "id": child["id"],
                        "doc_id": child["doc_id"],
                        "parent_id": child["parent_id"],
                        "content": child["content"],
                        "embedding": dummy_embedding
                    })
            
            if entities:
                self.collection.insert([
                    [e["id"] for e in entities],
                    [e["doc_id"] for e in entities],
                    [e["parent_id"] for e in entities],
                    [e["content"] for e in entities],
                    [e["embedding"] for e in entities]
                ])
                
                self.collection.flush()
                logger.info(f"✓ Milvus 삽입: {len(entities)} 벡터")
                return True
                
        except MilvusException as e:
            logger.error(f"✗ 벡터 삽입 실패: {str(e)}")
            return False
        
        return False


# ============================================================================
# 통합 파이프라인
# ============================================================================

def process_pdf_to_db(
    pdf_path: str,
    postgres_config: Dict,
    milvus_host: str = "localhost",
    milvus_port: int = 19530
) -> bool:
    """
    PDF → Markdown → 계층적 청킹 → DB 저장 (PostgreSQL + Milvus)
    
    Args:
        pdf_path (str): PDF 파일 경로
        postgres_config (Dict): PostgreSQL 연결 설정
        milvus_host (str): Milvus 호스트
        milvus_port (int): Milvus 포트
        
    Returns:
        bool: 성공 여부
    """
    
    # 1. PDF → Markdown
    logger.info(f"[1/5] PDF 변환 중: {pdf_path}")
    md_text, metadata = pdf_to_markdown(pdf_path)
    if not md_text:
        logger.error("✗ PDF 변환 실패")
        return False
    
    # 2. 계층적 청킹
    logger.info("[2/5] 계층적 청킹 중...")
    doc_id = str(uuid4())
    hierarchical_data = chunk_markdown_hierarchically(md_text, doc_id)
    if not hierarchical_data:
        logger.error("✗ 청킹 실패")
        return False
    
    # 3. PostgreSQL 저장
    logger.info("[3/5] PostgreSQL 저장 중...")
    pg_storage = PostgreSQLStorage(postgres_config)
    if not pg_storage.connect():
        return False
    
    if not pg_storage.create_tables():
        pg_storage.close()
        return False
    
    if not pg_storage.save_hierarchical_data(doc_id, metadata["document_title"], pdf_path, hierarchical_data):
        pg_storage.close()
        return False
    
    pg_storage.close()
    
    # 4. Milvus 연결 (선택사항)
    logger.info("[4/5] Milvus 연결 중...")
    milvus_storage = MilvusStorage(milvus_host, milvus_port)
    if milvus_storage.connect():
        if milvus_storage.create_collection():
            logger.info("[5/5] 벡터 임베딩 삽입 중...")
            milvus_storage.insert_embeddings(hierarchical_data)
    else:
        logger.warning("⚠ Milvus 연결 실패, PostgreSQL만 사용합니다.")
    
    logger.info("✓ 전체 파이프라인 완료!")
    return True


# ============================================================================
# 테스트 코드
# ============================================================================

if __name__ == "__main__":
    import sys
    
    # 테스트 PDF 경로
    pdf_path = r"C:\Users\미소정보기술\airflow-practice\test\법률test.pdf"
    output_md_dir = r"C:\Users\미소정보기술\airflow-practice\output\markdown"
    
    print("\n" + "="*70)
    print("PDF → Markdown → DB 파이프라인 테스트")
    print("="*70 + "\n")
    
    # 1. PDF 파일 존재 확인
    print("[1/4] PDF 파일 확인...")
    if not os.path.exists(pdf_path):
        logger.error(f"✗ PDF 파일 없음: {pdf_path}")
        sys.exit(1)
    else:
        file_size = os.path.getsize(pdf_path) / 1024
        logger.info(f"✓ PDF 파일 발견: {pdf_path} ({file_size:.1f} KB)")
    
    # 2. PDF → Markdown 변환
    print("\n[2/4] PDF → Markdown 변환...")
    try:
        md_text, metadata = pdf_to_markdown(pdf_path)
        if not md_text:
            logger.error("✗ 마크다운 변환 실패")
            sys.exit(1)
        
        logger.info(f"✓ 변환 완료: {len(md_text)} 문자")
        logger.info(f"  - 제목: {metadata['document_title']}")
        logger.info(f"  - 페이지: {metadata['total_pages']}")
        
    except Exception as e:
        logger.error(f"✗ PDF 변환 중 오류: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    
    # 3. 마크다운을 파일로 저장
    print("\n[3/4] 마크다운 파일 저장...")
    try:
        base_filename = Path(pdf_path).stem
        md_file_path = save_markdown_to_file(
            md_text,
            output_dir=output_md_dir,
            filename=f"{base_filename}.md"
        )
        if not md_file_path:
            logger.warning("⚠ 마크다운 파일 저장 실패 (계속 진행)")
        else:
            # 저장된 파일 미리보기
            with open(md_file_path, 'r', encoding='utf-8') as f:
                preview = f.read(500)
            logger.info(f"\n📝 마크다운 미리보기:\n{'-'*50}\n{preview}\n{'-'*50}")
        
    except Exception as e:
        logger.error(f"✗ 파일 저장 중 오류: {str(e)}")
        import traceback
        traceback.print_exc()
    
    # 4. 계층적 청킹
    print("\n[4/4] 계층적 청킹...")
    try:
        doc_id = str(uuid4())
        hierarchical_data = chunk_markdown_hierarchically(md_text, doc_id)
        
        if not hierarchical_data:
            logger.error("✗ 청킹 실패")
            sys.exit(1)
        
        logger.info(f"✓ 청킹 완료: {len(hierarchical_data)} 부모 항목")
        
        # 청킹 결과 통계
        total_children = sum(len(p["children"]) for p in hierarchical_data)
        total_chars = sum(p["char_count"] for p in hierarchical_data)
        
        logger.info(f"  - 총 부모 청크: {len(hierarchical_data)}")
        logger.info(f"  - 총 자식 청크: {total_children}")
        logger.info(f"  - 총 문자 수: {total_chars}")
        
        # JSON으로 저장 (참고용)
        json_output_dir = r"C:\Users\미소정보기술\airflow-practice\output\json"
        Path(json_output_dir).mkdir(parents=True, exist_ok=True)
        json_file = os.path.join(json_output_dir, f"{Path(pdf_path).stem}_chunks.json")
        
        with open(json_file, 'w', encoding='utf-8') as f:
            # JSON 직렬화 (datetime 처리)
            json_data = json.dumps(hierarchical_data, ensure_ascii=False, indent=2)
            f.write(json_data)
        
        logger.info(f"✓ 청킹 결과 저장: {json_file}")
        
        # PostgreSQL 저장 (선택사항)
        print("\n[추가] PostgreSQL 저장 시도...")
        postgres_config = {
            "host": "localhost",
            "port": 5432,
            "database": "airflow",
            "user": "airflow",
            "password": "airflow"
        }
        
        try:
            pg_storage = PostgreSQLStorage(postgres_config)
            if pg_storage.connect():
                if pg_storage.create_tables():
                    if pg_storage.save_hierarchical_data(
                        doc_id,
                        metadata["document_title"],
                        pdf_path,
                        hierarchical_data
                    ):
                        logger.info("✓ PostgreSQL 저장 성공")
                    else:
                        logger.warning("⚠ PostgreSQL 저장 실패")
                else:
                    logger.warning("⚠ PostgreSQL 테이블 생성 실패")
                pg_storage.close()
            else:
                logger.warning("⚠ PostgreSQL 연결 실패 (DB 확인 필요)")
        except Exception as e:
            logger.warning(f"⚠ PostgreSQL 저장 중 오류 (계속 진행): {str(e)}")
        
        print("\n" + "="*70)
        print("✅ 테스트 완료!")
        print("="*70)
        
    except Exception as e:
        logger.error(f"✗ 청킹 중 오류: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)