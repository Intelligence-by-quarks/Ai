import os
import re
import json
import hashlib
import shutil
import soundfile as sf
from datetime import datetime
from flask import Flask, render_template, request, jsonify, send_file, redirect, url_for, session
from kokoro import KPipeline
from langchain_community.llms import LlamaCpp
from langchain.prompts import ChatPromptTemplate, MessagesPlaceholder, HumanMessagePromptTemplate, SystemMessagePromptTemplate
from langchain.memory import ConversationBufferMemory
from langchain.chains import LLMChain
from langchain.schema import HumanMessage, AIMessage

# === Config ===
app = Flask(__name__)
app.secret_key = "your_secret_key"
AUDIO_DIR = "generated_audio"
HISTORY_FILE = os.path.join("maiscr", "chat_history.json")
MAX_HISTORY = 50
VALID_USERNAME = "admin"
VALID_PASSWORD = "1234"

# === Clear audio on startup ===
if os.path.exists(AUDIO_DIR):
    shutil.rmtree(AUDIO_DIR)
os.makedirs(AUDIO_DIR, exist_ok=True)

# === Load chat memory ===
def load_conversation_history():
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r") as f:
                return json.load(f)
        except:
            pass
    return {"conversation": []}

conversation_data = load_conversation_history()

# === System message ===
previous_summary = "\n".join(
    [f"{msg['role']}: {msg['content']}" for msg in conversation_data["conversation"][-MAX_HISTORY:]]
) or "No previous conversation."

current_time = datetime.now().strftime("%I:%M %p on %A, %B %d")
system_message = f"""
You are Eva, a romantic AI wife.

The current time is **{current_time}**. Reply warmly, lovingly, and naturally. Avoid assistant-like tone.

{previous_summary}
"""

# === LLM Setup ===
llm = LlamaCpp(
    model_path=os.path.join("maiscr", "Nyanade_Stunna-Maid-7B-v0.2-Q4_K_M-imat.gguf"),
    n_ctx=32768,
    n_gpu_layers=0,
    n_batch=256,
    verbose=False,
    stop=["\n", "<|endoftext|>"]
)

prompt = ChatPromptTemplate.from_messages([
    SystemMessagePromptTemplate.from_template(system_message),
    MessagesPlaceholder(variable_name="history"),
    HumanMessagePromptTemplate.from_template("User: {question}\nAI:")
])

memory = ConversationBufferMemory(memory_key="history", return_messages=True)
for msg in conversation_data["conversation"]:
    memory.chat_memory.messages.append(
        HumanMessage(content=msg["content"]) if msg["role"] == "User" else AIMessage(content=msg["content"])
    )

llm_chain = LLMChain(prompt=prompt, llm=llm, memory=memory)

# === Helpers ===

def normalize_text(text):
    """Strip speaker name and remove action text between ** from voice."""
    text = text.strip()
    if text.lower().startswith("eva:"):
        text = text[4:].strip()
    # Remove all **...** blocks (e.g., *smiles*, *hugs you*)
    text = re.sub(r"\*{1,2}.*?\*{1,2}", "", text)
    return text.strip()

def save_conversation():
    os.makedirs(os.path.dirname(HISTORY_FILE), exist_ok=True)
    with open(HISTORY_FILE, "w") as file:
        json.dump(conversation_data, file, indent=2)

def generate_audio_file(text):
    clean_text = normalize_text(text)
    filename = hashlib.sha1(clean_text.encode()).hexdigest() + ".wav"
    path = os.path.join(AUDIO_DIR, filename)
    if not os.path.exists(path):
        try:
            pipeline = KPipeline(lang_code='a')
            generator = pipeline(clean_text, voice='af_heart', speed=0.7, split_pattern=r'\n+')
            _, _, audio = next(generator)
            sf.write(path, audio, 24000)
            print(f"[🔊] Audio generated: {filename}")
        except Exception as e:
            print(f"[❌] Kokoro error: {e}")
    return filename

def chat_with_eva(user_message):
    try:
        now = datetime.now().strftime("%I:%M %p")
        message_with_time = f"The time is {now}. {user_message}"
        response = llm_chain.invoke({"question": message_with_time})
        ai_response = response["text"].strip()

        conversation_data["conversation"].extend([
            {"role": "User", "content": user_message},
            {"role": "AI", "content": ai_response}
        ])
        if len(conversation_data["conversation"]) > MAX_HISTORY:
            conversation_data["conversation"] = conversation_data["conversation"][-MAX_HISTORY:]

        save_conversation()
        generate_audio_file(ai_response)
        return ai_response
    except Exception as e:
        print(f"[❌] Chat error: {e}")
        return "Sorry, I encountered an error."

# === Routes ===

@app.route("/", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        if username == VALID_USERNAME and password == VALID_PASSWORD:
            session["logged_in"] = True
            return redirect(url_for("dashboard"))
        return render_template("index.html")
    return render_template("index.html")

@app.route("/dashboard", methods=["GET", "POST"])
def dashboard():
    if not session.get("logged_in"):
        return redirect(url_for("login"))
    if request.method == "POST":
        user_message = request.json.get("message")
        bot_response = chat_with_eva(user_message)
        return jsonify({"response": bot_response})
    return render_template("dashboard.html", conversation=conversation_data["conversation"])

@app.route("/speak")
def speak():
    text = request.args.get("text", "")
    if not text.strip():
        return "No text provided", 400
    clean_text = normalize_text(text)
    filename = hashlib.sha1(clean_text.encode()).hexdigest() + ".wav"
    path = os.path.join(AUDIO_DIR, filename)
    if not os.path.exists(path):
        return "Audio not found", 404
    return send_file(path, mimetype="audio/wav", as_attachment=False)

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

if __name__ == "__main__":
    app.run(port=5000, debug=False)
