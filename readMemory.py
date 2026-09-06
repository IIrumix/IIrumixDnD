import chromadb

# ชี้ไปที่โฟลเดอร์ db เดิมที่บอทบันทึกไว้
chroma_client = chromadb.PersistentClient(path="./dnd_memory")
collection = chroma_client.get_or_create_collection(name="campaign_logs")

# ดึงข้อมูลทั้งหมดออกมา
data = collection.get()

total_count = len(data["ids"])
print(f"\n===== บันทึกความจำทั้งหมดใน ChromaDB ({total_count} รายการ) =====\n")

if total_count == 0:
    print("ยังไม่มีข้อมูลความจำถูกบันทึก")
else:
    for idx, (doc_id, doc_text, meta) in enumerate(zip(data["ids"], data["documents"], data["metadatas"]), start=1):
        player = meta.get("player", "-")
        day = meta.get("day", "-")
        m_type = meta.get("type", "event")
        npc = meta.get("npc_name", "-")
        
        print(f"[{idx}] ID: {doc_id[:8]}... | Type: {m_type}")
        print(f"    Player: {player} | Day: {day} | NPC: {npc}")
        print(f"    Content: {doc_text}")
        print("-" * 50)