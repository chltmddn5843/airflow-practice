#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PDF → Markdown 변환 테스트 (간단한 버전)
"""

import os
import sys
from pathlib import Path

# UTF-8 인코딩 강제
if sys.stdout.encoding != 'utf-8':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# PDF 경로
pdf_path = "/root/airflow/pdf/법률test.pdf"
output_dir = "/root/airflow/output/markdown"

# 로컬 경로로 변경 (Windows)
local_pdf_path = r"C:\Users\미소정보기술\airflow-practice\test\법률test.pdf"
local_output_dir = r"C:\Users\미소정보기술\airflow-practice\output\markdown"

print("\n" + "="*70)
print("PDF → Markdown 변환 테스트")
print("="*70 + "\n")

# 1. 필수 패키지 확인
print("[1/3] 필수 패키지 확인...")
try:
    import fitz
    print("  ✓ PyMuPDF 설치됨")
except ImportError:
    print("  ✗ PyMuPDF 미설치 - pip install PyMuPDF 실행하세요")
    sys.exit(1)

try:
    from langchain.text_splitter import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter
    print("  ✓ LangChain 설치됨")
    HAS_LANGCHAIN = True
except ImportError:
    print("  ⚠ LangChain 미설치 - 기본 분할 사용")
    HAS_LANGCHAIN = False

# 2. PDF 파일 확인
print("\n[2/3] PDF 파일 확인...")

if not os.path.exists(local_pdf_path):
    print(f"  ✗ PDF 파일 없음: {local_pdf_path}")
    sys.exit(1)

file_size = os.path.getsize(local_pdf_path) / 1024
print(f"  ✓ PDF 파일 발견: ({file_size:.1f} KB)")

# 3. PDF → Markdown 변환
print("\n[3/3] PDF → Markdown 변환...")
try:
    doc = fitz.open(local_pdf_path)
    full_text = ""
    
    for page_num, page in enumerate(doc):
        text = page.get_text()
        full_text += text
        print(f"  - 페이지 {page_num + 1}: {len(text)} 문자")
    
    print(f"\n✓ 전체 추출 완료: {len(full_text)} 문자")
    
    # 마크다운 정규화
    import re
    lines = full_text.split('\n')
    md_text = f"# {lines[0].strip() if lines else '법률문서'}\n\n"
    
    content = '\n'.join(lines[1:])
    content = re.sub(r'(제\d+조\([^)]*\))', r'\n## \1\n', content)
    content = re.sub(r'\n(\d+\.)', r'\n- \1', content)
    content = re.sub(r'\n\n+', r'\n\n', content)
    
    md_text += content
    
    # 저장
    os.makedirs(local_output_dir, exist_ok=True)
    md_file = os.path.join(local_output_dir, "법률test.md")
    
    with open(md_file, 'w', encoding='utf-8-sig') as f:
        f.write(md_text)
    
    print(f"\n✓ 마크다운 저장 완료 (UTF-8-sig): {md_file}")
    print(f"  - 파일 크기: {os.path.getsize(md_file) / 1024:.1f} KB")
    
    # 미리보기
    preview = md_text[:500]
    print(f"\n📝 마크다운 미리보기:\n{'-'*50}\n{preview}\n{'-'*50}")
    
except Exception as e:
    print(f"✗ 오류 발생: {str(e)}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

print("\n" + "="*70)
print("✅ 테스트 완료!")
print("="*70)
