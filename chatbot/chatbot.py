import os
import torch
import numpy as np
from transformers import AutoTokenizer, AutoModel
from openai import OpenAI
from pymilvus import connections, Collection, utility
from dotenv import load_dotenv
os.environ["CUDA_VISIBLE_DEVICES"] = "-1"  # GPU를 물리적으로 차단
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE" # 라이브러리 충돌 방지
# 1. 환경 설정 및 API 키 로드
load_dotenv()
ai_api_key = os.getenv("API_KEY")
client = OpenAI(api_key=ai_api_key)

# Milvus 설정
MILVUS_HOST = os.getenv("MILVUS_HOST", "127.0.0.1") 
MILVUS_PORT = 19530
MILVUS_COLLECTION = "col_1"

# 2. Nomic 임베딩 모델 로드 (전역 로드하여 성능 최적화)
device = "cuda" if torch.cuda.is_available() else "cpu"
model_name = "nomic-ai/nomic-embed-text-v2-moe"
tokenizer = AutoTokenizer.from_pretrained(model_name, trust_remote_code=True)
model = AutoModel.from_pretrained(model_name, trust_remote_code=True).to(device)
model.eval()

# 3. Milvus 연결 함수
def connect_milvus():
    if not connections.has_connection("default"):
        connections.connect(
            alias="default",
            host=MILVUS_HOST,
            port=MILVUS_PORT
        )
        print(f"✅ Milvus 연결 성공! (Collections: {utility.list_collections()})")

# 4. 텍스트 임베딩 생성 (L2 검색을 위해 정규화 없이 원본 벡터 사용 권장)
def get_embedding(text):
    input_text = f"search_query: {text}"
    inputs = tokenizer(input_text, return_tensors="pt", padding=True, truncation=True, max_length=512).to(device)
    
    with torch.no_grad():
        outputs = model(**inputs)
        last_hidden = outputs.last_hidden_state
        attention_mask = inputs["attention_mask"]
        
        # Mean Pooling
        mask = attention_mask.unsqueeze(-1).expand(last_hidden.size()).float()
        masked_hidden = last_hidden * mask
        summed = torch.sum(masked_hidden, 1)
        counts = torch.clamp(mask.sum(1), min=1e-9)
        mean_pooled = summed / counts
        
        # L2 검색 시에는 강제 정규화(p=2)를 하지 않는 것이 모델 본연의 거리 계산에 더 정확할 수 있습니다.
        embedding = mean_pooled[0].cpu().numpy()
        
    return embedding.tolist()

# 5. Milvus 유사도 검색 (L2 설정 적용)
def search_milvus(query, top_k=5):
    connect_milvus()
    
    collection = Collection(MILVUS_COLLECTION)
    collection.load()

    query_vector = get_embedding(query)
    
    # [변경] metric_type을 L2로 설정
    # L2는 거리가 '작을수록' 유사하므로 Milvus가 내부적으로 오름차순 정렬을 수행합니다.
    search_params = {"metric_type": "L2", "params": {"nprobe": 10}}
    
    results = collection.search(
        data=[query_vector],
        anns_field="dense", 
        param=search_params,
        limit=top_k,
        output_fields=["pk", "source", "file_hash", "page", "row"]
    )

    hits = []
    for hit in results[0]:
        hits.append({
            "chunk_id": hit.entity.get("pk"),
            "content": hit.entity.get("source"),
            "parent_id": hit.entity.get("file_hash"),
            "page": hit.entity.get("page"),
            "row": hit.entity.get("row"),
            "score": hit.distance # L2 거리가 출력됨 (0에 가까울수록 유사)
        })
    return hits

# 6. 답변 생성
def ask_legal_expert(user_input, retrieved_chunks):
    context_text = "\n\n".join([f"근거: {c['content']}" for c in retrieved_chunks])
    
    system_prompt = """당신은 법률 지식을 전달하는 **'법률 데이터 검증 전문가'**입니다... (중략) ..."""

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"[Context]\n{context_text}\n\n[Question]\n{user_input}"}
    ]

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=messages,
        temperature=0
    )
    
    return response.choices[0].message.content.strip()

# 7. 실행부
if __name__ == "__main__":
    while True:
        query = input("\n질문을 입력하세요 (exit 종료): ")
        if query.lower() == "exit": break
        
        try:
            hits = search_milvus(query, top_k=5)
            answer = ask_legal_expert(query, hits)
            print("\n" + "-"*30 + " AI 응답 " + "-"*30)
            print(answer)
        except Exception as e:
            print(f"에러 발생: {e}")