#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Hierarchical Chunking 테스트
마크다운을 부모-자식 구조로 청킹
"""

import os
import sys
from pathlib import Path

# UTF-8 인코딩 강제
if sys.stdout.encoding != 'utf-8':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# 경로 설정
local_pdf_path = r"C:\Users\미소정보기술\airflow-practice\test\법률test.pdf"
local_output_dir = r"C:\Users\미소정보기술\airflow-practice\output"
local_md_path = os.path.join(local_output_dir, "markdown", "법률test.md")

print("\n" + "="*70)
print("Hierarchical Chunking 테스트")
print("="*70 + "\n")

# 1. 마크다운 파일 로드
print("[1/3] 마크다운 파일 로드...")
if not os.path.exists(local_md_path):
    print(f"  ✗ 마크다운 파일 없음: {local_md_path}")
    print("  💡 먼저 test_simple.py를 실행하세요")
    sys.exit(1)

with open(local_md_path, 'r', encoding='utf-8-sig') as f:
    md_content = f.read()

print(f"  ✓ 마크다운 로드 완료: {len(md_content)} 문자")
print(f"  - 파일: {local_md_path}")

# 2. 계층적 청킹 수행
print("\n[2/3] 계층적 청킹 수행...")

# 마크다운 파서
import re

def chunk_markdown_hierarchically(md_text):
    """
    마크다운을 계층적으로 청킹
    - Level 1 (Parent): # 제목
    - Level 2 (Child): ## 조항들
    """
    chunks = []
    
    lines = md_text.split('\n')
    current_parent = None
    current_child = []
    
    for line in lines:
        if line.startswith('# '):
            # 부모 시작
            if current_parent:
                chunks.append(current_parent)
            current_parent = {
                'level': '부모',
                'title': line.replace('# ', '').strip(),
                'content': [],
                'children': 0
            }
        elif line.startswith('## '):
            # 자식 시작
            if current_child:
                if current_parent:
                    current_parent['children'] += 1
                    current_parent['content'].append({
                        'level': '자식',
                        'title': current_child[0].replace('## ', '').strip(),
                        'content': '\n'.join(current_child[1:]).strip()
                    })
            current_child = [line]
        else:
            if current_child:
                current_child.append(line)
    
    # 마지막 청크 추가
    if current_child and current_parent:
        current_parent['children'] += 1
        current_parent['content'].append({
            'level': '자식',
            'title': current_child[0].replace('## ', '').strip(),
            'content': '\n'.join(current_child[1:]).strip()
        })
    
    if current_parent:
        chunks.append(current_parent)
    
    return chunks

chunks = chunk_markdown_hierarchically(md_content)
print(f"  ✓ 청킹 완료: {len(chunks)} 부모 청크")

# 3. 청킹 결과 분석
print("\n[3/3] 청킹 결과 분석...")
total_children = sum(c['children'] for c in chunks)
print(f"  ✓ 총 자식 청크: {total_children}")

# 상세 정보
print(f"\n📊 청킹 구조:")
print(f"  {'-'*50}")

for i, parent in enumerate(chunks, 1):
    parent_title = parent['title'][:50] + "..." if len(parent['title']) > 50 else parent['title']
    print(f"\n  [{i}] 부모: {parent_title}")
    print(f"      자식 개수: {parent['children']}")
    
    for j, child in enumerate(parent['content'][:3], 1):  # 처음 3개만
        child_title = child['title'][:40] + "..." if len(child['title']) > 40 else child['title']
        child_len = len(child['content'])
        print(f"        └─ [{j}] {child_title} ({child_len} 문자)")
    
    if parent['children'] > 3:
        print(f"        └─ ... 외 {parent['children'] - 3}개")

# JSON 저장
print(f"\n[4/3] 결과 JSON 저장...")
import json

output_json = os.path.join(local_output_dir, "json", "hierarchical_chunks.json")
os.makedirs(os.path.dirname(output_json), exist_ok=True)

# JSON 직렬화
json_data = []
for parent in chunks:
    parent_record = {
        'parent_title': parent['title'],
        'children': []
    }
    for child in parent['content']:
        parent_record['children'].append({
            'child_title': child['title'],
            'content_length': len(child['content']),
            'preview': child['content'][:100] + "..." if len(child['content']) > 100 else child['content']
        })
    json_data.append(parent_record)

with open(output_json, 'w', encoding='utf-8-sig') as f:
    json.dump(json_data, f, ensure_ascii=False, indent=2)

print(f"  ✓ JSON 저장 완료: {output_json}")
print(f"    - 파일 크기: {os.path.getsize(output_json) / 1024:.1f} KB")

# 통계
print(f"\n📈 통계:")
total_content = sum(sum(len(c['content']) for c in p['content']) for p in chunks)
print(f"  - 총 컨텐츠 크기: {total_content} 문자")
print(f"  - 평균 자식 크기: {total_content // total_children if total_children > 0 else 0} 문자")

print("\n" + "="*70)
print("✅ 계층적 청킹 테스트 완료!")
print("="*70 + "\n")
