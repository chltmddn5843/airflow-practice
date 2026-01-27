import os
from pymilvus import connections, Collection
import numpy as np

# Milvus 연결 정보 (회사망 예시)
MILVUS_HOST = os.getenv("MILVUS_HOST", "127.0.0.1")
MILVUS_PORT = 19530
MILVUS_USER = os.getenv("MILVUS_USER", "root")
MILVUS_PASSWORD = os.getenv("MILVUS_PASSWORD", "Milvus")
MILVUS_DB = os.getenv("MILVUS_DB", "default")
MILVUS_COLLECTION = os.getenv("MILVUS_COLLECTION", "legal_chunks")  # 실제 컬렉션명으로 변경

# Milvus 연결 정보 (환경변수 우선, 없으면 로컬 기본값)
# - 도커 컨테이너에서 접속 시 반드시 호스트의 실제 IP 사용
# - 로컬 파이썬에서 접속 시 "127.0.0.1" 또는 "localhost" 사용

connections.connect(
    alias="default",
    host="localhost",
    port=19530,
    timeout=5
)
print("Milvus 연결 성공!")

def connect_milvus():
	connections.connect(
		alias="default",
		host=MILVUS_HOST,
		port=MILVUS_PORT,
		user=MILVUS_USER,
		password=MILVUS_PASSWORD,
		db_name=MILVUS_DB,
		timeout=10,
		secure=False
	)

# 예시: OpenAI 임베딩 API (실제 사용시 키/모델명 확인)
def get_embedding(text):
	api_key = os.getenv("OPENAI_API_KEY")
	client = openai.OpenAI(api_key=api_key)
	response = client.embeddings.create(
		model="text-embedding-ada-002",
		input=text
	)
	return response.data[0].embedding

# Milvus에서 유사 청킹 top-k 검색
def search_milvus(query, top_k=7):
	connect_milvus()
	embedding = get_embedding(query)
	collection = Collection(MILVUS_COLLECTION)
	collection.load()
	# 필드명은 실제 스키마에 맞게 수정 필요
	results = collection.search(
		data=[embedding],
		anns_field="embedding",  # 벡터 필드명
		param={"metric_type": "IP", "params": {"nprobe": 8}},
		limit=top_k,
		output_fields=["chunk_id", "content", "parent_id"]
	)
	# 결과 정리
	hits = []
	for hit in results[0]:
		hits.append({
			"chunk_id": hit.entity.get("chunk_id"),
			"content": hit.entity.get("content"),
			"parent_id": hit.entity.get("parent_id"),
			"score": hit.distance
		})
	return hits

# RAG 프롬프트 조립
def build_rag_prompt(user_input, retrieved_chunks):
	context = "\n\n".join([f"근거: {c['content']}" for c in retrieved_chunks])
	prompt = f"다음 질문에 답변하세요.\n질문: {user_input}\n\n{context}\n답변:"
	return prompt
def show_recent_logs(limit=10):
	try:
		conn = get_pg_conn()
		cur = conn.cursor()
		cur.execute("SELECT id, question, answer, created_at FROM chatbot_logs ORDER BY id DESC LIMIT %s", (limit,))
		rows = cur.fetchall()
		print(f"\n최근 {limit}개 대화 로그:")
		for row in rows:
			print(f"[{row[0]}] {row[3]}\nQ: {row[1]}\nA: {row[2]}\n---")
		cur.close()
		conn.close()
	except Exception as e:
		print("DB 조회 오류:", e)


import os
import openai
from dotenv import load_dotenv
import psycopg2
from psycopg2 import sql
from datetime import datetime

load_dotenv()
api_key = os.getenv("API_KEY")
# 1. API 키 설정 (채점관 LLM용)
os.environ["OPENAI_API_KEY"] = api_key

# PostgreSQL 연결 정보
PG_HOST = os.getenv("PG_HOST", "localhost")
PG_PORT = int(os.getenv("PG_PORT", 5432))
PG_USER = os.getenv("PG_USER", "airflow")
PG_PASSWORD = os.getenv("PG_PASSWORD", "airflow")
PG_DATABASE = os.getenv("PG_DATABASE", "airflow")

def get_pg_conn():
	return psycopg2.connect(
		host=PG_HOST,
		port=PG_PORT,
		user=PG_USER,
		password=PG_PASSWORD,
		database=PG_DATABASE
	)

def ensure_chatbot_logs_table():
	conn = get_pg_conn()
	cur = conn.cursor()
	cur.execute('''
		CREATE TABLE IF NOT EXISTS chatbot_logs (
			id SERIAL PRIMARY KEY,
			question TEXT NOT NULL,
			answer TEXT NOT NULL,
			file_name TEXT,
			similarity_score FLOAT,
			chunk_id TEXT,
			parent_id TEXT,
			created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
		);
	''')
	conn.commit()
	cur.close()
	conn.close()

def save_chat_log(question, answer, retrieved_chunks=None):
	conn = get_pg_conn()
	cur = conn.cursor()
	# 여러 근거가 있을 경우 가장 높은 유사도(최상위)만 기록, 파일명/청킹id/parent_id도 함께
	if retrieved_chunks and len(retrieved_chunks) > 0:
		top = retrieved_chunks[0]
		file_name = top.get('file_name', None)
		similarity_score = float(top.get('score', 0.0))
		chunk_id = str(top.get('chunk_id'))
		parent_id = str(top.get('parent_id'))
	else:
		file_name = None
		similarity_score = None
		chunk_id = None
		parent_id = None
	cur.execute(
		"""
		INSERT INTO chatbot_logs (question, answer, file_name, similarity_score, chunk_id, parent_id, created_at)
		VALUES (%s, %s, %s, %s, %s, %s, %s)
		""",
		(question, answer, file_name, similarity_score, chunk_id, parent_id, datetime.now())
	)
	conn.commit()
	cur.close()
	conn.close()



# 기존 LLM 호출 함수 (RAG용으로 확장)
def ask_openai(prompt):
	api_key = os.getenv("OPENAI_API_KEY")
	client = openai.OpenAI(api_key=api_key)
	response = client.chat.completions.create(
		model="gpt-3.5-turbo",
		messages=[{"role": "user", "content": prompt}]
	)
	return response.choices[0].message.content.strip()


if __name__ == "__main__":
	ensure_chatbot_logs_table()
	print("챗봇에 오신 것을 환영합니다! 종료하려면 'exit'를 입력하세요.")
	while True:
		user_input = input("You: ")
		if user_input.lower() == "exit":
			print("챗봇을 종료합니다.")
			break
		if user_input.lower() == "show":
			show_recent_logs()
			continue
		try:
			# 1. Milvus에서 근거 검색
			retrieved_chunks = search_milvus(user_input, top_k=3)
			print("\n[근거 청킹 결과]")
			for idx, c in enumerate(retrieved_chunks, 1):
				print(f"근거 {idx}: chunk_id={c.get('chunk_id')}, parent_id={c.get('parent_id')}, score={c.get('score'):.4f}")
				print(f"내용: {c.get('content')[:120]}{'...' if len(c.get('content',''))>120 else ''}\n---")
			# 2. RAG 프롬프트 조립
			rag_prompt = build_rag_prompt(user_input, retrieved_chunks)
			# 3. LLM 호출
			answer = ask_openai(rag_prompt)
			print("AI:", answer)
			# 4. DB 저장 (질문/답변/근거)
			save_chat_log(user_input, answer, retrieved_chunks)
		except Exception as e:
			print("오류:", e)
