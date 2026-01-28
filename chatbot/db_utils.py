import os
import psycopg2
from datetime import datetime

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
