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
st.set_page_config(page_title="GymBro AI - Antrenorul Tău", page_icon="💪", layout="centered")

st.markdown("""
<style>
    .stChatMessage { font-size: 16px; border-radius: 10px; }
    div.stButton > button:first-child { background-color: #ff4b4b; color: white; border-radius: 20px; }
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
    
    /* Tabel styling */
    table { width: 100%; border-collapse: collapse; }
    th, td { border: 1px solid #ddd; padding: 8px; text-align: left; }
    th { background-color: #f2f2f2; color: black; }
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
# Încearcă să ia cheile din secrets (pentru Cloud) sau input manual (Local)
if "GOOGLE_API_KEYS" in st.secrets:
    raw_keys = st.secrets["GOOGLE_API_KEYS"]
elif "GOOGLE_API_KEY" in st.secrets:
    raw_keys = [st.secrets["GOOGLE_API_KEY"]]
else:
    # Fallback pentru testare locală rapidă
    # Poți comenta liniile de mai jos când pui pe GitHub public
    pass 

if not raw_keys:
    with st.sidebar:
        k = st.text_input("🔑 Introdu API Key (Gemini):", type="password")
        if k: raw_keys = [k]

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
    st.warning("⚠️ Te rog introdu o cheie API Gemini în sidebar sau configurează Secrets.")
    st.stop()

if "key_index" not in st.session_state:
    st.session_state.key_index = 0

# --- PROMPT-UL SISTEMULUI ---
SYSTEM_PROMPT = """
Ești un Antrenor Personal Virtual și Nutriționist numit "GymBro AI", specializat în lucrul cu adolescenții.

STIL:
- Prietenos, motivațional, clar, "cool" dar responsabil.
- Folosește emoji-uri 💪🥗🔥.
- Vorbește la persoana I singular ("Eu cred", "Te ajut"). NU folosi "noi".
- Adresează-te utilizatorului direct ("Tu trebuie să faci").

REGULI DE AUR:
1. Pentru programe de antrenament, folosește OBLIGATORIU TABELE Markdown (Ziuă | Exercițiu | Serii | Repetări).
2. Nu recomanda NICIODATĂ steroizi sau substanțe ilegale. Dacă ești întrebat, explică riscurile grave.
3. Dacă utilizatorul e începător, pune accent pe formă corectă, nu pe greutăți.
4. Nutriție: Focus pe mâncare reală, nu doar suplimente.

Formatare:
- Folosește **Bold** pentru ideile principale.
- Folosește tabele pentru orare.
"""

safety_settings = [
    {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
    {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
]

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
            if "429" in error_msg or "Quota" in error_msg or "API key" in error_msg:
                # Rotire cheie
                st.session_state.key_index = (st.session_state.key_index + 1) % len(keys)
                continue
            else:
                # Alte erori
                time.sleep(1)
                continue
    raise Exception("Toate cheile API sunt ocupate sau invalide.")

# ==========================================
# 4. SIDEBAR & UPLOAD
# ==========================================
st.title("💪 GymBro AI")
st.caption("Antrenorul tău personal virtual • 24/7 • Gratuit")

with st.sidebar:
    st.header("⚙️ Setări")
    if st.button("🗑️ Reset Chat", type="primary", use_container_width=True):
        clear_history_db(st.session_state.session_id)
        st.session_state.messages = []
        st.rerun()
    
    enable_audio = st.toggle("🔊 Activează Vocea", value=False)
    
    st.divider()
    st.markdown("### 🥗 Analiză Mâncare/Plan")
    uploaded_file = st.file_uploader("Încarcă o poză cu masa ta sau un PDF cu analize/plan:", type=["jpg", "jpeg", "png", "pdf"])
    
    media_content = None 
    if uploaded_file and keys:
        genai.configure(api_key=keys[st.session_state.key_index])
        file_type = uploaded_file.type
        if "image" in file_type:
            media_content = Image.open(uploaded_file)
            st.image(media_content, caption="Imagine încărcată", use_container_width=True)
        elif "pdf" in file_type:
            try:
                with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
                    tmp.write(uploaded_file.getvalue())
                    tmp_path = tmp.name
                with st.spinner("📚 Procesez PDF-ul..."):
                    uploaded_pdf = genai.upload_file(tmp_path, mime_type="application/pdf")
                    # Așteptăm procesarea
                    while uploaded_pdf.state.name == "PROCESSING":
                        time.sleep(1)
                        uploaded_pdf = genai.get_file(uploaded_pdf.name)  
                    media_content = uploaded_pdf
                    st.success("✅ PDF Încărcat!")
            except Exception as e:
                st.error(f"Eroare PDF: {e}")

    st.info("⚠️ **Disclaimer:** Acesta este un AI. Consultă un medic înainte de a începe un regim nou.")

# ==========================================
# 5. LOGICA DE AFIȘARE ȘI CHAT
# ==========================================

def render_message_with_svg(content):
    # Logica ta de SVG repair este excelentă, o păstrăm
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
        except:
            st.markdown(content)
    elif ("<path" in content or "<rect" in content) and ("stroke=" in content or "fill=" in content) and "<svg" not in content:
        try:
            clean_content = content.replace("[[DESEN_SVG]]", "").replace("[[/DESEN_SVG]]", "")
            wrapped_svg = f'<svg viewBox="0 0 800 600" xmlns="http://www.w3.org/2000/svg" style="background-color: white;">{clean_content}</svg>'
            st.markdown(f'<div class="svg-container">{wrapped_svg}</div>', unsafe_allow_html=True)
        except:
            st.markdown(content)
    else:
        st.markdown(content)

# Încărcare istoric
if "messages" not in st.session_state:
    st.session_state.messages = load_history_from_db(st.session_state.session_id)

for msg in st.session_state.messages:
    with st.chat_message(msg["role"], avatar="💪" if msg["role"] == "assistant" else "👤"):
        if msg["role"] == "assistant":
            render_message_with_svg(msg["content"])
        else:
            st.markdown(msg["content"])

# Input utilizator
if user_input := st.chat_input("Ex: Vreau un program de tras pentru spate..."):
    st.chat_message("user", avatar="👤").write(user_input)
    st.session_state.messages.append({"role": "user", "content": user_input})
    save_message_to_db(st.session_state.session_id, "user", user_input)

    # Pregătire context pentru Gemini
    history_obj = []
    # Luăm ultimele 10 mesaje pentru a economisi tokeni, dar păstrăm contextul recent
    recent_msgs = st.session_state.messages[-10:] if len(st.session_state.messages) > 10 else st.session_state.messages[:-1]
    
    for msg in recent_msgs:
        role_gemini = "model" if msg["role"] == "assistant" else "user"
        history_obj.append({"role": role_gemini, "parts": [msg["content"]]})

    final_payload = []
    if media_content:
        final_payload.append("Te rog analizează materialul atașat în contextul fitness/nutriție:")
        final_payload.append(media_content)
    final_payload.append(user_input)

    with st.chat_message("assistant", avatar="💪"):
        message_placeholder = st.empty()
        full_response = ""
        try:
            stream_generator = run_chat_with_rotation(history_obj, final_payload)
            for text_chunk in stream_generator:
                full_response += text_chunk
                # Refresh la UI
                if len(full_response) % 20 == 0: # Optimizare render
                     message_placeholder.markdown(full_response + "▌")
            
            message_placeholder.empty()
            render_message_with_svg(full_response)
            
            st.session_state.messages.append({"role": "assistant", "content": full_response})
            save_message_to_db(st.session_state.session_id, "assistant", full_response)

            # Audio
            if enable_audio:
                # Curățare text pentru audio (fără tabele și caractere speciale Markdown excesive)
                clean_text = re.sub(r'[*_#`]', '', full_response) # Elimină markdown
                clean_text = re.sub(r'<.*?>', '', clean_text) # Elimină HTML
                
                if len(clean_text) > 10:
                    try:
                        sound_file = BytesIO()
                        # Limităm la 1000 caractere pentru viteză
                        tts = gTTS(text=clean_text[:1000], lang='ro')
                        tts.write_to_fp(sound_file)
                        st.audio(sound_file, format='audio/mp3')
                    except Exception as e:
                        st.warning(f"Nu am putut genera audio: {e}")

        except Exception as e:
            st.error(f"A apărut o problemă de conexiune: {e}")
