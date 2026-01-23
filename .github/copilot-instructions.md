# Copilot Instructions: Legal-Link RAG System

## Architecture Overview

This is an **Airflow-based ETL pipeline** for a legal RAG (Retrieval-Augmented Generation) chatbot that processes Korean law and court precedent data. The system uses a **hierarchical document chunking strategy** with parent-document retrieval pattern.

### Key Components
- **Orchestration**: Apache Airflow 2.7.1 (CeleryExecutor with PostgreSQL + Redis)
- **Storage**: MariaDB (hierarchical metadata), ChromaDB (vector embeddings)
- **LLM**: Claude 3.5 Sonnet via LangChain
- **Data**: Hierarchical legal documents chunked at three levels: 조(Article) > 항(Section) > 문(Sentence)

### Critical Data Flow
1. **Extract**: Korean legal data center API/XML → Airflow DAG
2. **Transform**: Regex-based parsing of XML into hierarchical chunks (조/항/문)
3. **Load**: Parent chunks (조) → MariaDB; child chunks (문) + embeddings → ChromaDB
4. **Retrieve**: Search by child (문), retrieve parent context (조) for LLM
5. **Generate**: Claude generates answers with source citations (precedent ID, article reference)

## Airflow Development Patterns

### DAG Structure (`dags/`)
- DAGs use **functional composition** with `with DAG():` context manager (not class-based)
- All DAG files are auto-discovered from `/dags/` directory
- Key dependencies: `PythonOperator`, `MySqlHook`, task dependencies via `>>` syntax
- Connection IDs are configured in Airflow UI (e.g., `my_mariadb` for MySQL connections)

### Example DAG Pattern
```python
from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.providers.mysql.hooks.mysql import MySqlHook
from datetime import datetime

def extract_data():
    hook = MySqlHook(mysql_conn_id='my_mariadb')  # UI-configured connection
    connection = hook.get_sqlalchemy_engine()
    # Use pandas.read_sql() for queries

with DAG(
    dag_id='unique_dag_name',
    start_date=datetime(2025, 1, 1),
    schedule_interval=None,  # Manual trigger or cron string
    catchup=False
) as dag:
    task1 = PythonOperator(task_id='task_name', python_callable=extract_data)
```

### Task Communication
- Use **XCom** (cross-communication) to pass data between tasks
- Use `task_instance.xcom_push()` to store values, `xcom_pull()` to retrieve
- Never share state via module-level variables

### Database Hooks
- Use `MySqlHook(mysql_conn_id=...)` for MariaDB operations
- Connection credentials managed in Airflow UI, not code
- Support libraries: `pandas`, `sqlalchemy`, `psycopg2-binary`, `pymysql`

## Project-Specific Conventions

### Hierarchical Data Model (Critical!)
Always respect the three-tier chunking:
- **Parent (조/Article)**: Stored in MariaDB `LEGAL_MASTER` table
- **Child (문/Sentence)**: Stored in `LEGAL_CHUNKS` with `LEVEL='문'`
- **Metadata**: `CASE_ID`, `CHUNK_ID`, `PARENT_ID` relationships for parent-document retrieval

### Column Naming
- `CASE_ID`: Primary key for source document (law/precedent)
- `CHUNK_ID`: Primary key for individual chunks
- `PARENT_ID`: Foreign key reference (CASE_ID for hierarchy)
- `LEVEL`: Hierarchical level ('조', '항', '문')
- `CONTENT`: The actual text chunk

### Regex Parsing Convention
- Use regex to extract Korean legal structure: `조(Article) > 항(Section) > 문(Sentence)`
- Pattern typically: Article numbers (조 XX) → Sections (항 X) → Sentences (문)
- Preserve original article/section numbers as metadata for legal citation

## Environment & Deployment

### Docker Setup
- Run `docker-compose up -d` to start: Postgres, Redis, Airflow webserver/scheduler/workers/triggerer
- Default Airflow UI: `http://localhost:8080` (user: `airflow`/`airflow`)
- Airflow config persists via volume mounts: `dags/`, `logs/`, `config/`, `plugins/`
- Worker uses CeleryExecutor → tasks can run in parallel on distributed workers

### Required PIP Packages
Add to docker-compose `_PIP_ADDITIONAL_REQUIREMENTS`:
- `beautifulsoup4` (web scraping)
- `pandas` (data manipulation)
- `matplotlib` (visualization)
- `sqlalchemy` (ORM queries)
- `psycopg2-binary` (PostgreSQL)
- `pymysql` (MariaDB)

### Connection Configuration
All database connections must be created in Airflow UI:
- Admin → Connections
- Example: `my_mariadb` → MySQL → host, user, password, database
- Never hardcode credentials in DAG code

## Testing & Debugging

### Common Patterns
- **DAG Validation**: Use `airflow dags list` to verify DAG discovery
- **Task Logs**: View in Airflow UI or `logs/dag_id=.../run_id=.../task_id=.../` directories
- **XCom Inspection**: Use Airflow UI to view pushed values between tasks
- **Database Validation**: Connect to MariaDB via CLI to verify loaded chunks

### Debug Tips
1. Use `PythonOperator` with `print()` statements; logs appear in UI
2. Test SQL queries outside Airflow first (mysql CLI)
3. Check task dependencies with graph view in Airflow UI
4. Verify connection IDs exist before deploying DAGs

## File Organization

```
.
├── dags/                    # Auto-discovered DAG files (Python)
├── logs/                    # Task execution logs (generated)
├── config/                  # Airflow configuration (currently empty)
├── plugins/                 # Custom Airflow plugins (if any)
├── docker-compose.yaml      # CeleryExecutor setup (Postgres + Redis)
└── README.md                # System architecture (legal data flow)
```

## Next Steps for Expansion

- **Graph Database (Neo4j)**: Visualize law-to-law citation relationships
- **Intent Classification**: Add user question intent detection before retrieval
- **Streaming UI**: FastAPI/Streamlit for real-time Claude response streaming
- **Vector Embeddings**: Implement ChromaDB storage for semantic search on child chunks

---

**Update this file when adding new DAG patterns, database schemas, or external integrations (e.g., legal data source APIs).**
