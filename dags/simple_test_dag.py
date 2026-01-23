"""
Simple Test DAG - XCom and Database 테스트
"""

from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.providers.postgres.hooks.postgres import PostgresHook
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

def task_push_xcom(**kwargs):
    """샘플 데이터를 XCom에 저장"""
    ti = kwargs['ti']
    test_data = ['test_value_1', 'test_value_2', 'test_value_3']
    ti.xcom_push(key='test_key', value=test_data)
    logger.info(f"✓ Pushed to XCom: {test_data}")
    return len(test_data)

def task_pull_xcom(**kwargs):
    """XCom에서 데이터를 가져와서 DB에 저장"""
    ti = kwargs['ti']
    data = ti.xcom_pull(task_ids='push_xcom', key='test_key')
    logger.info(f"✓ Pulled from XCom: {data}")
    
    if not data:
        logger.warning("⚠ No data from XCom!")
        return
    
    pg_hook = PostgresHook(postgres_conn_id='postgres_default')
    connection = pg_hook.get_sqlalchemy_engine()
    
    with connection.begin() as conn:
        for item in data:
            sql = "INSERT INTO test_table (name) VALUES (%s)"
            conn.execute(sql, (item,))
            logger.info(f"✓ Inserted: {item}")

def task_verify():
    """데이터 검증"""
    pg_hook = PostgresHook(postgres_conn_id='postgres_default')
    connection = pg_hook.get_sqlalchemy_engine()
    
    with connection.begin() as conn:
        result = conn.execute("SELECT COUNT(*) FROM test_table").scalar()
        logger.info(f"✓ Total records in test_table: {result}")

with DAG(
    dag_id='simple_test_dag',
    start_date=datetime(2025, 1, 1),
    schedule_interval=None,
    catchup=False,
) as dag:
    
    push_task = PythonOperator(
        task_id='push_xcom',
        python_callable=task_push_xcom,
    )
    
    pull_task = PythonOperator(
        task_id='pull_xcom',
        python_callable=task_pull_xcom,
    )
    
    verify_task = PythonOperator(
        task_id='verify',
        python_callable=task_verify,
    )
    
    push_task >> pull_task >> verify_task
