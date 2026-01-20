import streamlit as st
import sqlite3
import google.generativeai as genai
import uuid
from datetime import datetime

# --- CONFIGURARE PAGINĂ ---
st.set_page_config(page_title="AI Gym Trainer", page_icon="💪", layout="centered")

# --- CONFIGURARE GEMINI API ---
# Cheia API trebuie să fie în Streamlit Secrets (vezi instrucțiunile de jos)
try:
    genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
except KeyError:
    st.error("Te rog adaugă GEMINI_API_KEY în Streamlit Secrets!")
    st.stop()

# Modelul Gemini
model = genai.GenerativeModel('gemini-1.5-flash')

# --- CONFIGURARE SYSTEM PROMPT ---
# Aici definim personalitatea AI-ului
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

IMPORTANT: Dacă utilizatorul este începător, insistă pe forma corectă, nu pe greutăți mari.
"""

# --- GESTIONARE DATABASE (SQLite) ---
DB_FILE = "chat_history.db"

def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT,
            role TEXT,
            content TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()

def save_message(session_id, role, content):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('INSERT INTO messages (session_id, role, content) VALUES (?, ?, ?)', 
              (session_id, role, content))
    conn.commit()
    conn.close()

def get_history(session_id):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('SELECT role, content FROM messages WHERE session_id = ? ORDER BY id ASC', (session_id,))
    rows = c.fetchall()
    conn.close()
    return [{"role": row[0], "parts": [row[1]]} for row in rows]

def clear_history(session_id):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('DELETE FROM messages WHERE session_id = ?', (session_id,))
    conn.commit()
    conn.close()

# Inițializăm baza de date la pornire
init_db()

# --- GESTIONARE ID SESIUNE (URL) ---
# Verificăm dacă există un ID în URL
query_params = st.query_params
if "session_id" not in query_params:
    # Generăm un ID nou și îl punem în URL
    new_id = str(uuid.uuid4())
    st.query_params["session_id"] = new_id
    session_id = new_id
else:
    # Luăm ID-ul existent
    session_id = query_params["session_id"]

# --- INTERFAȚA UTILIZATOR ---

st.title("💪 GymBro AI - Antrenorul Tău")
st.markdown(f"**ID Sesiune:** `{session_id}`")
st.caption("Salvează link-ul din browser pentru a reveni exact la această conversație!")

# Încărcăm istoricul din baza de date
history_db = get_history(session_id)

# Afișăm istoricul în interfață
for msg in history_db:
    role_label = "AI" if msg["role"] == "model" else "Tu"
    avatar = "🤖" if msg["role"] == "model" else "😎"
    with st.chat_message(role_label, avatar=avatar):
        st.markdown(msg["parts"][0])

# --- LOGICA DE CHAT ---
if prompt := st.chat_input("Salut! Vreau un program pentru spate și biceps..."):
    # 1. Afișăm mesajul utilizatorului
    with st.chat_message("Tu", avatar="😎"):
        st.markdown(prompt)
    
    # 2. Salvăm mesajul utilizatorului în DB
    save_message(session_id, "user", prompt)

    # 3. Construim contextul pentru Gemini
    # Începem cu promptul de sistem, apoi adăugăm istoricul
    full_conversation = [{"role": "user", "parts": [SYSTEM_PROMPT]}] + history_db 
    # Adăugăm mesajul curent (deși l-am salvat în DB, Gemini are nevoie de el în lista curentă)
    full_conversation.append({"role": "user", "parts": [prompt]})

    # 4. Generăm răspunsul
    with st.chat_message("AI", avatar="🤖"):
        with st.spinner("GymBro gândește un plan..."):
            try:
                # Folosim generate_content cu istoricul reconstruit
                response = model.generate_content(full_conversation)
                ai_reply = response.text
                st.markdown(ai_reply)
                
                # 5. Salvăm răspunsul AI în DB
                save_message(session_id, "model", ai_reply)
            except Exception as e:
                st.error(f"A apărut o eroare: {e}")

# --- BUTON RESETARE ---
with st.sidebar:
    st.header("Setări")
    if st.button("🗑️ Resetare Conversație", type="primary"):
        clear_history(session_id)
        st.rerun()
    
    st.info("Această aplicație folosește AI pentru a genera sfaturi. Consultă un medic înainte de a începe un efort intens.")
