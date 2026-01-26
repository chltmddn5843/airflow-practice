#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Milvus 연결 및 데이터 검증 테스트
회사 IP의 Milvus에 연결하여 데이터를 확인합니다
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

# Milvus 연결 정보 설정
# 【회사 네트워크】
MILVUS_HOST = "192.168.5.102"  # 회사 Milvus IP
MILVUS_PORT = 19530            # Milvus gRPC 포트
MILVUS_API_PORT = 8000         # Milvus REST API 포트
MILVUS_DB = "default"          # Milvus Database

# Milvus 인증 정보
MILVUS_USERNAME = "root"       # 회사 제공 username
MILVUS_PASSWORD = "Milvus"     # 회사 제공 password

# 연결 방식 선택
USE_REST_API = False  # True로 변경하면 REST API 사용, False면 gRPC 사용

print("\n" + "="*70)
print("Milvus 데이터 확인 테스트")
print("="*70 + "\n")

# 1. pymilvus 설치 확인
print("[1/5] pymilvus 패키지 확인...")
try:
    from pymilvus import connections, Collection
    print(f"  ✓ pymilvus 설치됨")
except ImportError as e:
    print(f"  ✗ pymilvus 설치 필요: pip install pymilvus")
    print(f"     오류: {str(e)}")
    sys.exit(1)

# 2. Milvus 연결
print(f"\n[2/5] Milvus 연결 시도...")
print(f"      Host: {MILVUS_HOST}:{MILVUS_PORT}")
print(f"      연결 방식: {'REST API' if USE_REST_API else 'gRPC'}")

try:
    # 이미 연결된 경우 해제
    try:
        connections.disconnect(alias="default")
    except:
        pass
    
    # gRPC 연결 (인증 포함)
    if not USE_REST_API:
        connections.connect(
            alias="default",
            host=MILVUS_HOST,
            port=MILVUS_PORT,
            db_name=MILVUS_DB,
            user=MILVUS_USERNAME,
            password=MILVUS_PASSWORD,
            timeout=10,
            secure=False
        )
    else:
        # REST API 연결
        import requests
        response = requests.get(
            f"http://{MILVUS_HOST}:{MILVUS_API_PORT}/v1/collectioninfo",
            timeout=10
        )
        if response.status_code != 200:
            raise Exception(f"REST API 연결 실패: {response.status_code}")
    
    print(f"  ✓ Milvus 연결 성공!")
    
except Exception as e:
    print(f"  ✗ Milvus 연결 실패!")
    print(f"     오류: {str(e)}")
    print(f"\n  💡 해결 방법:")
    print(f"     1. gRPC 연결 시도: MILVUS_USERNAME/PASSWORD 확인")
    print(f"     2. REST API 연결 시도: USE_REST_API = True로 변경")
    print(f"     3. 방화벽 설정 확인")
    print(f"\n     회사 Milvus 인증 정보:")
    print(f"     - Username: {MILVUS_USERNAME}")
    print(f"     - Password: {MILVUS_PASSWORD}")
    print(f"\n     올바르지 않으면 위의 값을 수정하세요")
    sys.exit(1)

# 3. 컬렉션 목록 조회
print("\n[3/5] Milvus 컬렉션 목록 조회...")
try:
    from pymilvus import list_collections
    
    collections = list_collections()
    print(f"  ✓ 총 {len(collections)}개 컬렉션 찾음")
    
    if collections:
        print(f"\n  📊 컬렉션 목록:")
        for collection_name in collections:
            print(f"    └─ {collection_name}")
    else:
        print(f"  ⚠ Milvus에 컬렉션이 없습니다")
    
except Exception as e:
    print(f"  ✗ 컬렉션 조회 실패: {str(e)}")
    connections.disconnect(alias="default")
    sys.exit(1)

# 4. 컬렉션 상세 정보
if collections:
    print("\n[4/5] 컬렉션 상세 정보...")
    
    for collection_name in collections:
        try:
            collection = Collection(name=collection_name)
            collection.load()
            
            num_entities = collection.num_entities
            
            print(f"\n  📈 {collection_name}:")
            print(f"      엔티티 개수: {num_entities}")
            print(f"      필드: {collection.schema.to_dict()}")
            
            # 샘플 데이터 조회
            if num_entities > 0:
                data = collection.query(
                    expr="",
                    output_fields=["*"],
                    limit=min(3, num_entities)
                )
                print(f"      샘플 데이터 ({min(3, num_entities)}개):")
                for idx, item in enumerate(data, 1):
                    print(f"        [{idx}] {item}")
            
        except Exception as e:
            print(f"  ⚠ {collection_name} 조회 실패: {str(e)}")

else:
    print("\n[4/5] 컬렉션이 없으므로 스킵합니다")

# 5. 연결 종료
print("\n[5/5] Milvus 연결 종료...")
try:
    connections.disconnect(alias="default")
    print(f"  ✓ 연결 종료 완료")
except Exception as e:
    print(f"  ⚠ 연결 종료 중 오류: {str(e)}")

print("\n" + "="*70)
print("✅ 테스트 완료!")
print("="*70 + "\n")

# 설정 방법 안내
print("📝 Milvus 연결 설정 방법:")
print("""
1. 이 스크립트의 상단에서 MILVUS_HOST를 회사 IP로 변경하세요
   예: MILVUS_HOST = "192.168.0.100"

2. 필요시 MILVUS_PORT도 변경하세요 (기본값: 19530)

3. 다시 실행하면 Milvus에 연결됩니다

회사 네트워크 Milvus 정보:
- Host: ___________________  (회사에서 확인)
- Port: ___________________  (회사에서 확인)
""")
