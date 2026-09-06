from builtins import Exception
import importlib.util
import os
import re
import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
import uuid
import json

def install_missing_packages():
    packages = {
        "discord": "discord.py",
        "openpyxl": "openpyxl",
        "pandas": "pandas",
        "openai": "openai",
        "dotenv": "python-dotenv",
        "chromadb" : "chromadb",
    }
    missing = [package for module, package in packages.items()
               if importlib.util.find_spec(module) is None]
    if missing:
        subprocess.check_call([sys.executable, "-m", "pip", "install", *missing])


import subprocess
install_missing_packages()

import discord
from discord.ext import commands
import chromadb
import openpyxl
import pandas as pd
from openai import AsyncOpenAI
from dotenv import load_dotenv

#########################################################################################

load_dotenv()
DISCORD_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
AI_KEY = os.getenv("AI_API_KEY")
API_URL = os.getenv("API_URL")

ai_client = AsyncOpenAI(
    api_key=AI_KEY,
    base_url=API_URL
)

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

sessionStartChannelId = None
player_turn = -1
player_discord_ids = []
player_names = []
gameStart = False
last_narrative = "เพิ่งเริ่มเกม ทุกคนเพิ่งมาถึงสถาบันเวทมนตร์"
active_npcs = {}

selectedModel = "gemini-3.7-flash"
SESSION_FILE_PATH = "session1.xlsx"
# Memory for AI
# สร้าง Local Vector DB เก็บไว้ในโฟลเดอร์ ./dnd_memory 
chroma_client = chromadb.PersistentClient(path="./dnd_memory")
memory_collection = chroma_client.get_or_create_collection(name="campaign_logs")


try:
    with open("InstructionForAI.txt", "r", encoding="utf-8") as f:
        narrator_rule = f.read()
except FileNotFoundError:
    narrator_rule = "You are a classic fantasy D&D Game Master."

@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f"Logged in as {bot.user.name} (ID: {bot.user.id})")
    print("Slash commands ready.")
    
async def send_long_message(destination, text: str):
    #ฟังก์ชันแบ่งส่งข้อความหากยาวเกิน 1900 ตัวอักษร
    chunk_size = 1900
    # ตรวจสอบว่า destination รองรับคำสั่ง typing หรือไม่ (เช่น interaction.channel หรือ TextChannel)
    if hasattr(destination, "typing"):
        async with destination.typing():
            for i in range(0, len(text), chunk_size):
                await destination.send(text[i:i + chunk_size])
    else:
        # กรณีเป็น interaction.followup หรือ object ที่ไม่มี context manager ของ typing
        for i in range(0, len(text), chunk_size):
            await destination.send(text[i:i + chunk_size])

################################## Bot Command ###################################################################

@bot.tree.command(name="start_game", description="เริ่มเล่นเกม D&D")
async def start_game(interaction: discord.Interaction):
    global gameStart, sessionStartChannelId, player_names, player_discord_ids, player_turn, last_narrative,active_npcs
    last_narrative = "เพิ่งเริ่มเกม ทุกคนเพิ่งมาถึงสถาบันเวทมนตร์"
    active_npcs = {}

    await interaction.response.send_message("เริ่มตั้งค่าเกม! มีผู้เล่นทั้งหมดกี่คน? (1-4)")
    
    def check_author(m):
        return m.author == interaction.user and m.channel == interaction.channel
    
    def check_join(m):
        return (
            m.channel == interaction.channel 
            and m.content.strip().lower() == "join" 
            and m.author.id not in player_discord_ids
            and not m.author.bot
        )

    try:
        msg = await bot.wait_for('message', check=check_author, timeout=60.0)
        player_count = int(msg.content.strip())
        if player_count < 1 or player_count > 4:
            raise ValueError()
    except Exception:
        await interaction.followup.send("ข้อมูลไม่ถูกต้อง หรือหมดเวลาตอบ ยกเลิกการเริ่มเกม")
        return

    player_discord_ids = []

    for i in range(1, player_count + 1):
        await interaction.channel.send(f"โปรดพิมพ์คำว่า \"join\" เพื่อเข้าร่วมเกม:")
        try:
            join_msg = await bot.wait_for('message', check=check_join, timeout=60.0)
            player_discord_ids.append(join_msg.author.id) # หรือปรับให้แท็กเพื่อน
            player_names.append(join_msg.author.name)
            await interaction.channel.send(f"เพิ่มผู้เล่นคนที่ {i}: **{join_msg.author.display_name}** เข้าร่วมปาร์ตี้แล้ว")
        except Exception:
            await interaction.channel.send(f"หมดเวลาไม่ก็มีข้อผิดพลาด ผู้เล่นคนที่ {i} ไม่ได้เข้าร่วมเกม ยกเลิกการเริ่มเกม")
            return

    gameStart = True
    sessionStartChannelId = interaction.channel.id
    player_turn = -1

    await interaction.followup.send("เริ่มเกม D&D แล้ววว!")
    
    # ส่งให้ AI เกริ่นเริ่มเรื่อง
    intro_text, _ = await narratorResponse(SESSION_FILE_PATH, narrator_rule, "Please provide an introduction to the D&D stlye game session.")
    await send_long_message(interaction.channel, intro_text)
    
    await calloutnextplayer(interaction)
    
    
####################################


@bot.tree.command(name="act", description="กระทำแอ็กชันในเกม D&D")
async def act(interaction: discord.Interaction, action: str):
    if not gameStart:
        return await interaction.response.send_message("เกมยังไม่ได้เริ่ม กรุณาใช้ /start_game ก่อนครับ", ephemeral=True)
    if interaction.channel.id != sessionStartChannelId:
        return await interaction.response.send_message("คำสั่งนี้ใช้ได้เฉพาะในห้องที่เริ่มเกมเท่านั้นครับ", ephemeral=True)
    if interaction.user.id != player_discord_ids[player_turn]:
        return await interaction.response.send_message("ยังไม่ถึงเทิร์นของคุณ โปรดรอสักครู่ครับ", ephemeral=True)

    # Defer ไว้ก่อนเพราะ AI และ Excel อาจใช้เวลาเกิน 3 วินาที
    await interaction.response.defer()

    current_player = player_names[player_turn]
    narrator_res, has_bonus_turn = await narratorResponse(
        SESSION_FILE_PATH, 
        narrator_rule, 
        f"Player {current_player} performs the action: {action}"
    )
    
    await send_long_message(interaction.followup,f"Player {current_player} performs the action: {action}")
    #await send_long_message(interaction.followup, narrator_res)
    await send_long_message(interaction.channel, narrator_res)
    
    # ถ้าสร้างไม่ผ่าน หรือ ได้โบนัสเทิร์นแจกสกิล ให้คนเดิมเล่นต่อ
    if "สร้างตัวละครไม่สำเร็จ" in narrator_res or has_bonus_turn:
        await calloutnextplayer(interaction, forced_player_index=player_turn)
    else:
        await calloutnextplayer(interaction)
        
##############################
        
@bot.tree.command(name="reset_game", description="ล้างข้อมูลความจำและรีเซ็ตเกม")
async def reset_game(interaction: discord.Interaction):
    global memory_collection , last_narrative,active_npcs
    # ลบคอลเลกชันเดิมทิ้งแล้วสร้างใหม่
    chroma_client.delete_collection(name="campaign_logs")
    memory_collection = chroma_client.get_or_create_collection(name="campaign_logs")
    last_narrative = "เพิ่งเริ่มเกม ทุกคนเพิ่งมาถึงสถาบันเวทมนตร์"
    active_npcs = {}

    await interaction.response.send_message("ล้างความจำในระบบและรีเซ็ตแคมเปญเรียบร้อยแล้ว")
        
##############################

async def narratorResponse(file_path, rules, player_action):
    global last_narrative, active_npcs
    # อ่าน Excel แปลงเป็น Markdown ให้ AI
    try:
        # ข้อมูลตัวละครผู้เล่น (Sheet1)
        df_players = pd.read_excel(file_path, sheet_name="Sheet1", usecols="A:V", nrows=4).fillna("-")
        session_text = df_players.to_markdown(index=False)
        
    except Exception as e:
        session_text = "No character sheet data available." 
        
    # สร้างข้อความบอก AI ว่าตอนนี้ใครยืนอยู่ในฉากบ้าง
    if active_npcs:
        npc_scene_text = "\n".join([f"- **{name}**: {desc}" for name, desc in active_npcs.items()])
    else:
        npc_scene_text = "ไม่มี NPC พิเศษอยู่ในฉากขณะนี้ (มีเพียงคนทั่วไปรอบๆ)"
        
    current_turn_name = player_names[player_turn] if player_turn >= 0 and player_names else "Prologue / Setting Scene"
    current_p_num = (player_turn + 1) if player_turn >= 0 else 1

    #relevant_memories = retrieve_relevant_memories(player_action, top_k=5)
    relevant_memories = query_relevant_memories(player_action, current_player_num=current_p_num, top_k=5)

    system_content = (
       f"""You are Game Master (GM) for a Dungeons & Dragons (D&D) style game. Answer in Thai language only.

        --- DM RULES ---
        {rules}

        --- PLAYER DATA ---
        {session_text}
        
        --- CURRENT NPCS IN THE SCENE (NPC ที่กำลังยืนอยู่ในฉากขณะนี้ - ห้ามให้ตัวละครเหล่านี้หายไปเฉยๆ ตราบใดที่ยังไม่ได้เดินจากไป) ---
        {npc_scene_text}
        
        --- LAST SCENE NARRATION (ฉากและเหตุการณ์ที่เพิ่งเกิดขึ้นล่าสุดในเทิร์นที่แล้ว - ต้องดำเนินเรื่องต่อจากฉากนี้ ห้ามเปลี่ยนบริบทหรือลบสิ่งที่เกิดขึ้นไปแล้ว) ---
        {last_narrative}
        
        --- RELEVANT PAST MEMORIES ---
        {relevant_memories}

        --- Player Amount: {len(player_names)} ---
        --- Player Turn: {current_turn_name} ---
        """+"""
        ทุกครั้งที่ตอบ ให้ส่งกลับมาในรูปแบบ JSON ตามโครงสร้างนี้เท่านั้น (ห้ามใส่ Markdown backticks ครอบ):
        {
            "narrative": "ข้อความบรรยายเนื้อเรื่องภาษาไทยสำหรับส่งให้ผู้เล่นอ่านใน Discord",
            "excel_updates": [
                {
                    "sheet": "Sheet1",
                    "player": 1,
                    "column": "gold",
                    "value_change": -50,
                    "value": null
                }
            ],
            "event_log": {
                "date": "Day 1 - Morning",
                "event": "Player 1 ซื้อโพชั่นรักษาไป 50 gold"
            },
            "npc_updates": [
                {
                "player": 1,
                "npc_name": "Mira",
                "description": "พบกันหน้าโต๊ะทะเบียน เริ่มคุยกันเรื่องวิชาเลือก ท่าทางเป็นมิตร"
                }
            ],"present_npcs": [
            {
                "name": "ชื่อ NPC",
                "role": "นักเรียนห้อง x-x"
                "status": "ยังอยู่ในฉาก / เดินจากไปแล้ว",
                "description": "คำอธิบายสั้นๆ เช่น ยืนถือตำราเวทขวางประตูอยู่"
            }
        ]
            "fail_create_character": false,
            "bonus_turn_for_giving_skill" : null
        }
        กฎเพิ่มเติม:
        -story of every player is connected
        - หากเป็นการกำหนดค่าใหม่ (เช่น ชื่อ, คลาส) ให้ใส่ใน key "value" แทน "value_change"
        - หากไม่มีข้อมูลต้องอัปเดต ให้ใส่ "excel_updates": [] และ "event_log": null
        - ถ้าผู้เล่นทำผิดกฎสร้างตัวละคร ให้ใส่คำเตือนใน narrative ว่า"ผู้เล่นทำผิดกฎสร้างตัวละคร" และตั้ง "fail_create_character": true พร้อมไม่แก้ Excel
        - เมื่อผู้เล่นเลือกstatเสร็จแล้วถูกต้อง ให้บอกplayerในnarrativeว่า"ผู้เล่นได้สกิลใหม่" และ ตั้ง"bonus_turn_for_giving_skill" : random/pick/null เพื่อทำการมอบสกิลตามstatให้ผู้เล่นก่อน
        - การเพิ่มหรือปรับปรุงไอเทมในกระเป๋า ให้ระบุ "column": "inventory" พร้อมระบุรายการสิ่งของทั้งหมดที่ถืออยู่ลงใน "value" เช่น "Staff, Health Potion x1"
        - หากbonus_turn_for_giving_skillทำงานระหว่างสร้างตัวละครแปลว่าให้ผู้เล่นเลือก1สกิลจาก7สกิลโดยอิงตามstat
    """
    )

    response = await ai_client.chat.completions.create(
        model=selectedModel,
        messages=[
            {"role": "system", "content": system_content},
            {"role": "user", "content": player_action}
        ]
    )

    ai_output = response.choices[0].message.content
    
    # --- ใส่ Print ดูผลลัพธ์ตรงนี้ ---
    print("\n" + "="*40)
    print("[DEBUG AI OUTPUT]:")
    try:
        print(ai_output)
    except UnicodeEncodeError:
        print(ai_output.encode(sys.stdout.encoding or "utf-8", errors="replace").decode(sys.stdout.encoding or "utf-8"))
    print("="*40 + "\n")
    # -----------------------------
    
    clean_output = ai_output.strip()
    if clean_output.startswith("```json"):
        clean_output = clean_output[7:]
    elif clean_output.startswith("```"):
        clean_output = clean_output[3:]
    if clean_output.endswith("```"):
        clean_output = clean_output[:-3]
    clean_output = clean_output.strip()
    
    try:
        data = json.loads(clean_output)
    except Exception:
        # ถ้า parse ล้มเหลว ให้ใช้ Regex ค้นหาและดึงเฉพาะข้อความในคีย์ narrative ออกมา
        match = re.search(r'"narrative"\s*:\s*"(.*?)(?:"\s*,\s*"[a-zA-Z_]+"|"\s*\}|$)', clean_output, re.DOTALL)
        if match:
            extracted_text = match.group(1)
            # แปลง escape characters เช่น \n หรือ \" ให้กลับเป็นตัวอักษรปกติ
            extracted_text = extracted_text.encode('utf-8').decode('unicode_escape', errors='replace')
            data["narrative"] = extracted_text
        else:
            # หากดึงไม่ได้จริง ให้ตัดปีกกาและชื่อคีย์ narrative ทิ้ง
            cleaned_text = clean_output.replace('{\n  "narrative": "', '').replace('{\n "narrative": "', '')
            data["narrative"] = cleaned_text.replace('\\n', '\n').replace('\\"', '"')

    if data.get("fail_create_character"):
        warning_msg = data.get("narrative", "ผู้เล่นทำผิดกฎสร้างตัวละคร")
        msg = f"**สร้างตัวละครไม่สำเร็จ:**\n{warning_msg}\n* ไม่สามารถสร้างตัวละครได้ โปรดอ่านกฎให้ดีและลองใหม่อีกครั้ง"
        return msg, False  # คืนค่า 2 ตัว
    
    apply_ai_updates_to_excel(file_path, data)

    bonus_type = data.get("bonus_turn_for_giving_skill")
    narrative = data.get("narrative", ai_output)
    
    # เซฟข้อความที่ AI เพิ่งบรรยาย เพื่อใช้เป็นบริบทส่งต่อให้เทิร์นถัดไป
    if narrative and narrative != ai_output:
        last_narrative = narrative
    
    # ถ้า narrative ว่าง หรือ AI ส่งมาแค่ {}
    if not narrative or str(narrative).strip() in ["{}", ""]:
        narrative = ai_output

    if bonus_type in ["random", "pick"]:
        return narrative, True  # ส่ง True บอกว่าได้เทิร์นเพิ่ม

    return narrative, False

#############################

async def calloutnextplayer(interaction: discord.Interaction, forced_player_index: int = None):
    global player_turn
    if forced_player_index is not None:
        player_turn = forced_player_index
    else:
        player_turn = (player_turn + 1) % len(player_names)

    next_player = player_names[player_turn]
    target_user_id = player_discord_ids[player_turn]
    
    await interaction.channel.send(f"<@{target_user_id}> Turn: ถึงตาของ (**{next_player}**) แล้ว! พิมพ์ `/act` เพื่อดำเนินการ")

#################### Memory Management for Ai and player to read ##############################

def save_memory_to_chroma(text: str, player_num: int, current_day: str = "-", npc_name: str = None):
    #บันทึกเหตุการณ์หรือความสัมพันธ์ลง ChromaDB พร้อม Metadata
    meta = {
        "player": int(player_num),
        "day": str(current_day)
    }
    if npc_name:
        meta["npc_name"] = str(npc_name).strip().lower()
        meta["type"] = "npc_relationship"
    else:
        meta["type"] = "event"

    memory_collection.add(
        documents=[text],
        metadatas=[meta],
        ids=[str(uuid.uuid4())]
    )

def query_relevant_memories(player_action: str, current_player_num: int, top_k: int = 5) -> str:
    #ค้นหาความทรงจำในอดีตของผู้เล่นคนนั้นที่เกี่ยวข้องกับการกระทำปัจจุบัน
    if memory_collection.count() == 0:
        return "ไม่มีบันทึกอดีตที่เกี่ยวข้อง"

    try:
        results = memory_collection.query(
            query_texts=[player_action],
            n_results=min(top_k, memory_collection.count()),
        )
        docs = results.get("documents", [[]])[0]
        if not docs:
            return "ไม่มีบันทึกอดีตที่เกี่ยวข้อง"
        return "\n".join([f"- {d}" for d in docs])
    except Exception:
        return "ไม่มีบันทึกอดีตที่เกี่ยวข้อง"

#######################################

def apply_ai_updates_to_excel(excel_path: str, update_data: dict):
    try:
        wb = openpyxl.load_workbook(excel_path)
    except Exception as e:
        print(f"Error opening Excel: {e}")
        return

    # 1. ปรับปรุงข้อมูลตัวละครผู้เล่น (Sheet1)
    if "Sheet1" in wb.sheetnames and update_data.get("excel_updates"):
        ws1 = wb["Sheet1"]
        headers = {str(cell.value).strip().lower(): idx + 1 for idx, cell in enumerate(ws1[1]) if cell.value is not None}

        for item in update_data["excel_updates"]:
            player_num = item.get("player")
            target_col = str(item.get("column", "")).strip().lower()
            
            if target_col in headers and player_num is not None:
                col_idx = headers[target_col]
                row_idx = player_num + 1

                if item.get("value_change") is not None:
                    current_val = ws1.cell(row=row_idx, column=col_idx).value
                    try:
                        current_val = int(current_val) if current_val is not None else 0
                        ws1.cell(row=row_idx, column=col_idx, value=current_val + int(item["value_change"]))
                    except (ValueError, TypeError):
                        pass
                elif item.get("value") is not None:
                    # รองรับทั้ง inventory, lover_name, สกิล และคลาส
                    new_val = str(item["value"])
                    
                    # ถ้าเป็นการเพิ่มไอเทมใน inventory และต้องการต่อท้ายของเดิม (Optional)
                    if target_col == "inventory" and item.get("append", False):
                        old_inv = ws1.cell(row=row_idx, column=col_idx).value
                        if old_inv and str(old_inv).strip() not in ["-", "None", ""]:
                            new_val = f"{old_inv}, {new_val}"
                    
                    ws1.cell(row=row_idx, column=col_idx, value=new_val)

    # 2. จัดการ Event Log ลง Sheet2 และ ChromaDB
    if "Sheet2" in wb.sheetnames:
        ws2 = wb["Sheet2"]

        if update_data.get("event_log"):
            event_info = update_data["event_log"]
            next_row = 3
            while ws2.cell(row=next_row, column=1).value is not None:
                next_row += 1
                
            date_val = event_info.get("date", "-")
            event_val = event_info.get("event", "-")
            ws2.cell(row=next_row, column=1, value=date_val)
            ws2.cell(row=next_row, column=2, value=event_val)
            
            # บันทึกเหตุการณ์ลง ChromaDB
            current_p = (player_turn + 1) if player_turn >= 0 else 1
            save_memory_to_chroma(event_val, player_num=current_p, current_day=date_val)

    # 3. บันทึกความสัมพันธ์ NPC ตรงลง ChromaDB
    if update_data.get("npc_updates"):
        for npc in update_data["npc_updates"]:
            p_num = npc.get("player") or ((player_turn + 1) if player_turn >= 0 else 1)
            npc_name = str(npc.get("npc_name", "")).strip()
            desc = npc.get("description", "-")

            if not npc_name:
                continue

            save_memory_to_chroma(
                text=f"ความสัมพันธ์กับ {npc_name}: {desc}",
                player_num=p_num,
                npc_name=npc_name
            )

    try:
        wb.save(excel_path)
    except PermissionError:
        print("บันทึกไม่สำเร็จ: กรุณาปิดโปรแกรม Excel บนคอมพิวเตอร์ก่อน")
    except Exception as e:
        print(f"Error saving Excel: {e}")
        
###############################################################################################################
    
bot.run(DISCORD_TOKEN)