from pymilvus import utility
print("Milvus 연결 성공!", connections.has_connection("default"))
print("컬렉션 목록:", utility.list_collections())