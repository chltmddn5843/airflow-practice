import requests
from bs4 import BeautifulSoup
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

case_id = '64441'
LEGAL_API_BASE = 'https://www.law.go.kr/LSW/precInfoP.do?precSeq={id}&mode=0&vSct=*'
url = LEGAL_API_BASE.format(id=case_id)
headers = {'User-Agent': 'Mozilla/5.0'}

try:
    response = requests.get(url, headers=headers, timeout=10)
    print(f"✓ Status: {response.status_code}")
    print(f"✓ Content length: {len(response.text)} bytes")
    
    # BeautifulSoup으로 파싱
    soup = BeautifulSoup(response.text, 'lxml-xml')
    
    # 판시사항 찾기
    precepts = soup.find('판시사항')
    if precepts:
        text = precepts.get_text()[:200]
        print(f"✓ 판시사항 found: {text}")
    else:
        print("⚠ 판시사항 not found")
        
    # 모든 태그 확인
    tags = [tag.name for tag in soup.find_all()]
    unique_tags = set(tags)
    print(f"✓ Unique XML tags: {sorted(list(unique_tags))[:10]}")
    
    # HTML 인지 XML 인지 확인
    if soup.find('html'):
        print("⚠ HTML format detected, not XML!")
    
except Exception as e:
    print(f"✗ Error: {type(e).__name__}: {e}")
