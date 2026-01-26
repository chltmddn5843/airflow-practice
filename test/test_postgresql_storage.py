#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PostgreSQL 저장 테스트
계층적 청킹 데이터를 PostgreSQL에 저장
"""

import os
import sys
import json
from pathlib import Path

# UTF-8 인코딩 강제
if sys.stdout.encoding != 'utf-8':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# PostgreSQL 경로 설정
local_json_path = r"C:\Users\미소정보기술\airflow-practice\output\json\hierarchical_chunks.json"

print("\n" + "="*70)
print("PostgreSQL 저장 테스트")
print("="*70 + "\n")

# 1. JSON 데이터 로드
print("[1/4] JSON 데이터 로드...")
if not os.path.exists(local_json_path):
    print(f"  ✗ JSON 파일 없음: {local_json_path}")
    sys.exit(1)

with open(local_json_path, 'r', encoding='utf-8-sig') as f:
    chunks_data = json.load(f)

print(f"  ✓ JSON 로드 완료: {len(chunks_data)} 부모 청크")

# 2. PostgreSQL 연결 시도
print("\n[2/4] PostgreSQL 연결 시도...")
try:
    import psycopg2
    print("  ✓ psycopg2 라이브러리 로드됨")
except ImportError:
    print("  ⚠ psycopg2 미설치 - 데이터 구조만 검증")

try:
    import psycopg2
    
    # PostgreSQL 연결 정보 (Airflow 기본값)
    conn = psycopg2.connect(
        host="localhost",
        user="airflow",
        password="airflow",
        database="airflow",
        port=5432
    )
    cursor = conn.cursor()
    print("  ✓ PostgreSQL 연결 성공!")
    
    # 3. 테이블 생성
    print("\n[3/4] 테이블 생성...")
    
    # 부모 테이블
    create_parent_table = """
    CREATE TABLE IF NOT EXISTS legal_documents (
        doc_id SERIAL PRIMARY KEY,
        title VARCHAR(255) NOT NULL,
        parent_title VARCHAR(255),
        total_children INT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """
    
    # 자식 테이블
    create_child_table = """
    CREATE TABLE IF NOT EXISTS legal_document_chunks (
        chunk_id SERIAL PRIMARY KEY,
        doc_id INT NOT NULL REFERENCES legal_documents(doc_id) ON DELETE CASCADE,
        chunk_title VARCHAR(255) NOT NULL,
        content TEXT,
        content_length INT,
        chunk_order INT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(doc_id) REFERENCES legal_documents(doc_id)
    );
    """
    
    # 인덱스
    create_indexes = """
    CREATE INDEX IF NOT EXISTS idx_legal_documents_parent_title 
    ON legal_documents(parent_title);
    
    CREATE INDEX IF NOT EXISTS idx_legal_document_chunks_doc_id 
    ON legal_document_chunks(doc_id);
    """
    
    cursor.execute(create_parent_table)
    cursor.execute(create_child_table)
    cursor.execute(create_indexes)
    conn.commit()
    print("  ✓ 테이블 생성/확인 완료")
    
    # 4. 데이터 삽입
    print("\n[4/4] 데이터 삽입...")
    
    total_children_inserted = 0
    
    for parent_idx, parent_chunk in enumerate(chunks_data, 1):
        parent_title = parent_chunk.get('parent_title', '미정')
        children = parent_chunk.get('children', [])
        
        # 부모 레코드 삽입
        insert_parent = """
        INSERT INTO legal_documents (title, parent_title, total_children)
        VALUES (%s, %s, %s)
        RETURNING doc_id;
        """
        
        cursor.execute(insert_parent, (
            f"Document_{parent_idx}",
            parent_title,
            len(children)
        ))
        doc_id = cursor.fetchone()[0]
        print(f"  ✓ 부모 삽입: doc_id={doc_id}, children={len(children)}")
        
        # 자식 레코드 삽입
        insert_child = """
        INSERT INTO legal_document_chunks 
        (doc_id, chunk_title, content, content_length, chunk_order)
        VALUES (%s, %s, %s, %s, %s);
        """
        
        for child_idx, child_chunk in enumerate(children, 1):
            cursor.execute(insert_child, (
                doc_id,
                child_chunk.get('child_title', '미정'),
                child_chunk.get('preview', ''),
                child_chunk.get('content_length', 0),
                child_idx
            ))
            total_children_inserted += 1
        
        conn.commit()
    
    print(f"\n  ✓ 데이터 삽입 완료: {total_children_inserted} 자식 청크")
    
    # 5. 검증 쿼리
    print("\n[검증] 저장된 데이터 조회...")
    
    # 부모 조회
    cursor.execute("SELECT doc_id, parent_title, total_children FROM legal_documents;")
    parents = cursor.fetchall()
    print(f"\n  📊 부모 레코드: {len(parents)}개")
    for doc_id, parent_title, total_children in parents:
        print(f"    └─ doc_id={doc_id}, children={total_children}, title={parent_title[:40]}...")
    
    # 자식 조회
    cursor.execute("SELECT COUNT(*) FROM legal_document_chunks;")
    total_children_in_db = cursor.fetchone()[0]
    print(f"\n  📊 자식 레코드: {total_children_in_db}개")
    
    # 샘플 자식 데이터
    cursor.execute("""
    SELECT chunk_id, doc_id, chunk_title, content_length 
    FROM legal_document_chunks 
    LIMIT 3;
    """)
    samples = cursor.fetchall()
    for chunk_id, doc_id, chunk_title, content_length in samples:
        print(f"    └─ chunk_id={chunk_id}, doc_id={doc_id}, title={chunk_title}, length={content_length}")
    
    cursor.close()
    conn.close()
    
    print("\n" + "="*70)
    print("✅ PostgreSQL 저장 테스트 완료!")
    print("="*70 + "\n")
    
except psycopg2.OperationalError as e:
    print(f"  ⚠ PostgreSQL 연결 실패: {str(e)}")
    print("  💡 PostgreSQL이 실행 중인지 확인하세요")
    print("\n  가상 검증 (데이터 구조만 확인)...")
    
    # 데이터 구조 검증만 수행
    print(f"\n  📊 JSON 구조 검증:")
    for idx, parent in enumerate(chunks_data, 1):
        print(f"    [{idx}] 부모: {parent.get('parent_title', '미정')[:40]}...")
        print(f"        자식 개수: {len(parent.get('children', []))}")
        for cidx, child in enumerate(parent.get('children', [])[:2], 1):
            print(f"          └─ [{cidx}] {child.get('child_title', '미정')}")
    
    print("\n" + "="*70)
    print("✅ 데이터 구조 검증 완료 (DB 연결 없음)")
    print("="*70 + "\n")

except Exception as e:
    print(f"  ✗ 예기치 않은 오류: {str(e)}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
