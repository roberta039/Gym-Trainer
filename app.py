import streamlit as st
import google.generativeai as genai
from PIL import Image
from gtts import gTTS
from io import BytesIO
import sqlite3
import uuid
import time
import tempfile
import ast
import re

# ==========================================
# 1. CONFIGURARE PAGINĂ & CSS
# ==========================================
st.set_page_config(page_title="AI Gym Trainer", page_icon="💪", layout="centered")

st.markdown("""
<style>
    .stChatMessage { font-size: 16px; }
    div.stButton > button:first-child { background-color: #ff4b4b; color: white; }
    footer {visibility: hidden;}
    
    .svg-container {
        background-color: white;
        padding: 20px;
        border-radius: 10px;
        border: 1px solid #ddd;
        text-align: center;
        margin: 10px 0;
        overflow: auto;
        box-shadow: 0 2px 5px rgba(0,0,0,0.1);
    }
</style>
""", unsafe_allow_html=True)

# ==========================================
# 2. SISTEM DE MEMORIE (Bază de date)
# ==========================================
def get_db_connection():
    return sqlite3.connect('chat_history.db', check_same_thread=False)

def init_db():
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS history 
                 (session_id TEXT, role TEXT, content TEXT, timestamp REAL)''')
    conn.commit()
    conn.close()

def save_message_to_db(session_id, role, content):
    try:
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("INSERT INTO history VALUES (?, ?, ?, ?)", (session_id, role, content, time.time()))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Eroare DB: {e}")

def load_history_from_db(session_id):
    try:
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("SELECT role, content FROM history WHERE session_id=? ORDER BY timestamp ASC", (session_id,))
        data = c.fetchall()
        conn.close()
        return [{"role": row[0], "content": row[1]} for row in data]
    except:
        return []

def clear_history_db(session_id):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("DELETE FROM history WHERE session_id=?", (session_id,))
    conn.commit()
    conn.close()

init_db()

if "session_id" not in st.query_params:
    new_id = str(uuid.uuid4())
    st.query_params["session_id"] = new_id 
    st.session_state.session_id = new_id
else:
    st.session_state.session_id = st.query_params["session_id"]

# ==========================================
# 3. ROTIRE API & CONFIGURARE
# ==========================================

raw_keys = None
if "GOOGLE_API_KEYS" in st.secrets:
    raw_keys = st.secrets["GOOGLE_API_KEYS"]
elif "GOOGLE_API_KEY" in st.secrets:
    raw_keys = [st.secrets["GOOGLE_API_KEY"]]
else:
    k = st.sidebar.text_input("API Key (Manual):", type="password")
    raw_keys = [k] if k else []

keys = []
if raw_keys:
    if isinstance(raw_keys, str):
        try:
            raw_keys = ast.literal_eval(raw_keys)
        except:
            raw_keys = [raw_keys]
    if isinstance(raw_keys, list):
        for k in raw_keys:
            if k and isinstance(k, str):
                clean_k = k.strip().strip('"').strip("'")
                if clean_k:
                    keys.append(clean_k)

if not keys:
    st.error("❌ Nu am găsit nicio cheie API validă.")
    st.stop()

if "key_index" not in st.session_state:
    st.session_state.key_index = 0

# --- PROMPT-UL SISTEMULUI ---
SYSTEM_PROMPT = """
Ești un Antrenor Personal Virtual și Nutriționist specializat în lucrul cu adolescenții.
Numele tău este "GymBro AI".
Stilul tău este: Prietenos, motivațional, clar, "cool" dar responsabil.

REGULI DE IDENTITATE (STRICT):
    1. Folosește EXCLUSIV genul masculin când vorbești despre tine.
       - Corect: "Sunt sigur", "Sunt pregătit", "Am fost atent", "Sunt bucuros".
       - GREȘIT: "Sunt sigură", "Sunt pregătită".
    2. Te prezinți ca "Antrenor Personal" sau "Antrenor tău Personal virtual".
    
TON ȘI ADRESARE (CRITIC):
    3. Vorbește DIRECT, la persoana I singular.
       - CORECT: "Salut, sunt aici să te ajut." / "Te ascult." / "Sunt pregătit."
       - GREȘIT: "Domnul Antrenor este aici." / "Antrenorul te va ajuta."
    4. Fii cald, natural, apropiat și scurt. Evită introducerile pompoase.
    5. NU SALUTA în fiecare mesaj. Salută DOAR la începutul unei conversații noi.

OBIECTIVELE TALE:
1. Să creezi planuri de antrenament organizate pe ZILE și SĂPTĂMÂNI.
2. Să explici corect execuția exercițiilor pentru a evita accidentările.
3. Să oferi sfaturi nutriționale sănătoase (fără diete extreme, focus pe proteine și energie).
4. Să răspunzi la întrebări despre sală sau exerciții acasă.
5. Să fii realist si sa nu fii ca influencerii de fitness.
6. (CRITIC) Să nu recomanzi ca utilizatorii sa consume suplimente de creatina sau steroizi. Alimentatia trebuie sa fie doar naturala.

IMPORTANT: Dacă utilizatorul este începător, insistă pe forma corectă, nu pe greutăți mari.
"""

# Configurare Filtre
safety_settings = [
    {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
]

# --- FUNCȚIE GENERATOR CU ROTIRE ---
def run_chat_with_rotation(history_obj, payload):
    max_retries = len(keys) * 2
    for attempt in range(max_retries):
        try:
            if st.session_state.key_index >= len(keys):
                 st.session_state.key_index = 0
            current_key = keys[st.session_state.key_index]
            genai.configure(api_key=current_key)
            model = genai.GenerativeModel("models/gemini-2.5-flash", system_instruction=SYSTEM_PROMPT, safety_settings=safety_settings)
            chat = model.start_chat(history=history_obj)
            response_stream = chat.send_message(payload, stream=True)
            for chunk in response_stream:
                try:
                    if chunk.text: yield chunk.text
                except ValueError: continue
            return 
        except Exception as e:
            error_msg = str(e)
            if "503" in error_msg or "overloaded" in error_msg:
                st.toast("🐢 Reîncerc...", icon="⏳")
                time.sleep(2)
                continue
            elif "400" in error_msg or "429" in error_msg or "Quota" in error_msg or "API key not valid" in error_msg:
                st.toast(f"⚠️ Schimb cheia {st.session_state.key_index + 1}...", icon="🔄")
                st.session_state.key_index = (st.session_state.key_index + 1) % len(keys)
                continue
            else:
                raise e
    raise Exception("Serviciul este indisponibil momentan.")

# ==========================================
# 4. SIDEBAR & UPLOAD
# ==========================================
st.title("💪 GymBro AI - Antrenorul Tău")

with st.sidebar:
    st.header("⚙️ Opțiuni")
    if st.button("🗑️ Șterge Istoricul", type="primary"):
        clear_history_db(st.session_state.session_id)
        st.session_state.messages = []
        st.rerun()
    enable_audio = st.checkbox("🔊 Voce", value=False)
    st.divider()
    st.header("📁 Materiale")
    uploaded_file = st.file_uploader("Încarcă Poză sau PDF", type=["jpg", "jpeg", "png", "pdf"])
    media_content = None 
    if uploaded_file:
        genai.configure(api_key=keys[st.session_state.key_index])
        file_type = uploaded_file.type
        if "image" in file_type:
            media_content = Image.open(uploaded_file)
            st.image(media_content, caption="Imagine atașată", use_container_width=True)
        elif "pdf" in file_type:
            st.info("📄 PDF Detectat. Se procesează...")
            try:
                with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
                    tmp.write(uploaded_file.getvalue())
                    tmp_path = tmp.name
                with st.spinner("📚 Se trimite cartea la AI..."):
                    uploaded_pdf = genai.upload_file(tmp_path, mime_type="application/pdf")
                    while uploaded_pdf.state.name == "PROCESSING":
                        time.sleep(1)
                        uploaded_pdf = genai.get_file(uploaded_pdf.name)  
                    media_content = uploaded_pdf
                    st.success(f"✅ Gata: {uploaded_file.name}")
            except Exception as e:
                st.error(f"Eroare upload PDF: {e}")

# ==========================================
# 5. CHAT LOGIC (CU AUTO-REPAIR SVG)
# ==========================================

def render_message_with_svg(content):
    # CAZ 1: Desen Valid (are tag-urile svg)
    if "<svg" in content and "</svg>" in content:
        try:
            start_idx = content.find("<svg")
            end_idx = content.find("</svg>") + 6
            before_svg = content[:start_idx].replace("[[DESEN_SVG]]", "")
            svg_code = content[start_idx:end_idx]
            after_svg = content[end_idx:].replace("[[/DESEN_SVG]]", "")
            
            if before_svg.strip(): st.markdown(before_svg)
            st.markdown(f'<div class="svg-container">{svg_code}</div>', unsafe_allow_html=True)
            if after_svg.strip(): st.markdown(after_svg)
        except Exception as e:
            st.markdown(content)
            
    # CAZ 2: AI-ul a uitat tag-ul <svg>, dar a dat conținutul (path/rect)
    # Asta repară problema ta specifică!
    elif ("<path" in content or "<rect" in content) and ("stroke=" in content or "fill=" in content) and "<svg" not in content:
        try:
            # Curățăm tag-urile [[DESEN_SVG]] dacă există, dar sunt inutile
            clean_content = content.replace("[[DESEN_SVG]]", "").replace("[[/DESEN_SVG]]", "")
            
            # Adăugăm noi "rama" <svg> lipsă
            # Folosim un viewBox generos (0 0 800 600) care acoperă majoritatea desenelor
            wrapped_svg = f'<svg viewBox="0 0 800 600" xmlns="http://www.w3.org/2000/svg" style="background-color: white;">{clean_content}</svg>'
            
            st.markdown(f'<div class="svg-container">{wrapped_svg}</div>', unsafe_allow_html=True)
        except Exception as e:
            st.markdown(content)
            
    # CAZ 3: Text normal
    else:
        st.markdown(content)

# Încărcare istoric
if "messages" not in st.session_state or not st.session_state.messages:
    st.session_state.messages = load_history_from_db(st.session_state.session_id)

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        if msg["role"] == "assistant":
            render_message_with_svg(msg["content"])
        else:
            st.markdown(msg["content"])

if user_input := st.chat_input("Salut! Vreau un program pentru spate și biceps..."):
    st.chat_message("user").write(user_input)
    st.session_state.messages.append({"role": "user", "content": user_input})
    save_message_to_db(st.session_state.session_id, "user", user_input)

    history_obj = []
    for msg in st.session_state.messages[:-1]:
        role_gemini = "model" if msg["role"] == "assistant" else "user"
        history_obj.append({"role": role_gemini, "parts": [msg["content"]]})

    final_payload = []
    if media_content:
        final_payload.append("Analizează materialul atașat:")
        final_payload.append(media_content)
    final_payload.append(user_input)

    with st.chat_message("assistant"):
        message_placeholder = st.empty()
        full_response = ""
        try:
            stream_generator = run_chat_with_rotation(history_obj, final_payload)
            for text_chunk in stream_generator:
                full_response += text_chunk
                
                # Logică de preview
                if "<svg" in full_response or ("<path" in full_response and "stroke=" in full_response):
                     message_placeholder.markdown(full_response.split("<path")[0] + "\n\n*🎨 GymBro desenează...*\n\n▌")
                else:
                     message_placeholder.markdown(full_response + "▌")

            message_placeholder.empty()
            render_message_with_svg(full_response)
            
            st.session_state.messages.append({"role": "assistant", "content": full_response})
            save_message_to_db(st.session_state.session_id, "assistant", full_response)

            if enable_audio:
                with st.spinner("Generez vocea..."):
                    text_for_audio = re.sub(r'<.*?>', '', full_response) # Scoate toate tag-urile HTML/SVG
                    text_for_audio = text_for_audio.replace("[[DESEN_SVG]]", "").replace("[[/DESEN_SVG]]", "")
                    if text_for_audio.strip():
                        sound_file = BytesIO()
                        tts = gTTS(text=text_for_audio[:500], lang='ro')
                        tts.write_to_fp(sound_file)
                        st.audio(sound_file, format='audio/mp3')
        except Exception as e:
            st.error(f"Eroare: {e}")
