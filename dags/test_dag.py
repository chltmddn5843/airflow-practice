from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.providers.mysql.hooks.mysql import MySqlHook # Airflow에서 제공하는 Hook
from datetime import datetime
import pandas as pd

def extract_from_maria():
    # 1. Airflow UI에 등록한 'my_mariadb' 설정을 불러옵니다.
    mysql_hook = MySqlHook(mysql_conn_id='my_mariadb')
    
    # 2. 실제 SQL 쿼리 실행
    # (테이블 이름을 모르니 일단 현재 시간을 출력하는 쿼리로 테스트해봅니다.)
    sql = "SELECT NOW() as current_time;"
    
    # 만약 특정 테이블이 있다면 아래처럼 쓰세요.
    # sql = "SELECT * FROM 테이블명 LIMIT 10;"
    
    connection = mysql_hook.get_sqlalchemy_engine()
    df = pd.read_sql(sql, connection)
    
    print("--- DB 접속 성공! 데이터 출력 ---")
    print(df)
    print("-------------------------------")

with DAG(
    dag_id='mariadb_extraction_test',
    start_date=datetime(2025, 1, 1),
    schedule_interval=None,
    catchup=False
) as dag:

    task_extract = PythonOperator(
        task_id='extract_data',
        python_callable=extract_from_maria
    )