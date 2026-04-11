from fastapi import FastAPI, Depends, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
import sqlite3, hashlib, jwt, requests, tempfile, os
from datetime import datetime, timedelta
import whisper

model_whisper = whisper.load_model("tiny")
app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

SECRET_KEY = "scribe_secret_key_12345678901234567890"
ALGORITHM = "HS256"
security = HTTPBearer()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODELS = ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-2.0-flash-lite", "gemini-2.5-pro"]

def get_db():
    conn = sqlite3.connect("scribe.db")
    conn.row_factory = sqlite3.Row
    return conn

def hash_password(pwd):
    return hashlib.sha256(pwd.encode()).hexdigest()

def init_db():
    conn = get_db()
    c = conn.cursor()
    c.execute("CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, email TEXT UNIQUE, password TEXT, role TEXT)")
    c.execute("CREATE TABLE IF NOT EXISTS notes (id INTEGER PRIMARY KEY AUTOINCREMENT, patient_name TEXT, subjective TEXT, objective TEXT, assessment TEXT, plan TEXT, raw_transcript TEXT, created_by INTEGER, created_at TEXT DEFAULT CURRENT_TIMESTAMP)")
    for name, email, role in [("Doctor","doctor@scribe.ai","doctor"),("Nurse","nurse@scribe.ai","nurse"),("Admin","admin@scribe.ai","admin"),("Patient","patient@scribe.ai","patient")]:
        try:
            c.execute("INSERT INTO users (name,email,password,role) VALUES (?,?,?,?)", (name,email,hash_password("password123"),role))
        except: pass
    conn.commit(); conn.close()

init_db()

def create_token(data):
    return jwt.encode({**data, "exp": datetime.utcnow() + timedelta(days=7)}, SECRET_KEY, algorithm=ALGORITHM)

def verify_token(credentials: HTTPAuthorizationCredentials = Depends(security)):
    try: return jwt.decode(credentials.credentials, SECRET_KEY, algorithms=[ALGORITHM])
    except: raise HTTPException(status_code=401, detail="Invalid token")

class Login(BaseModel): email: str; password: str
class Signup(BaseModel): name: str; email: str; password: str; role: str = "doctor"
class Generate(BaseModel): transcript: str
class Note(BaseModel): patient_name: str; subjective: str; objective: str; assessment: str; plan: str; raw_transcript: str = ""

@app.post("/login")
def login(data: Login):
    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE email=? AND password=?", (data.email, hash_password(data.password))).fetchone()
    conn.close()
    if not user: raise HTTPException(status_code=401, detail="Invalid credentials")
    return {"token": create_token({"user_id": user["id"], "role": user["role"], "name": user["name"]}), "user": dict(user)}

@app.post("/signup")
def signup(data: Signup):
    conn = get_db()
    try:
        conn.execute("INSERT INTO users (name,email,password,role) VALUES (?,?,?,?)", (data.name,data.email,hash_password(data.password),data.role))
        conn.commit()
    except: raise HTTPException(status_code=400, detail="Email already exists")
    finally: conn.close()
    return {"message": "User created"}

@app.post("/transcribe")
async def transcribe(audio: UploadFile = File(...), user=Depends(verify_token)):
    suffix = os.path.splitext(audio.filename or "audio.wav")[-1] or ".wav"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(await audio.read()); tmp_path = tmp.name
    try: return {"transcript": model_whisper.transcribe(tmp_path)["text"].strip()}
    finally: os.unlink(tmp_path)

@app.get("/list-models")
def list_models():
    if not GEMINI_API_KEY: raise HTTPException(status_code=500, detail="GEMINI_API_KEY not set")
    resp = requests.get("https://generativelanguage.googleapis.com/v1beta/models?key=" + GEMINI_API_KEY, timeout=10)
    if resp.status_code != 200: raise HTTPException(status_code=resp.status_code, detail=resp.text[:400])
    models = [m["name"] for m in resp.json().get("models",[]) if "generateContent" in m.get("supportedGenerationMethods",[])]
    return {"available_models": models}

def call_gemini(prompt: str) -> str:
    if not GEMINI_API_KEY:
        raise ValueError("GEMINI_API_KEY not set. In PowerShell run: $env:GEMINI_API_KEY='your_key_here'")
    payload = {"contents": [{"parts": [{"text": prompt}]}]}
    last_error = "no models tried"
    for api_version in ["v1", "v1beta"]:
        for model in GEMINI_MODELS:
            url = "https://generativelanguage.googleapis.com/" + api_version + "/models/" + model + ":generateContent?key=" + GEMINI_API_KEY
            try:
                resp = requests.post(url, json=payload, timeout=30)
                if resp.status_code == 404:
                    last_error = model + " not found on " + api_version; print("[SKIP]", last_error); continue
                if resp.status_code != 200:
                    last_error = "HTTP " + str(resp.status_code) + " " + resp.text[:150]; print("[FAIL]", last_error); continue
                text = resp.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
                print("[OK] model:", api_version + "/" + model)
                return text
            except (KeyError, IndexError):
                last_error = "bad response shape from " + model; print("[FAIL]", last_error); continue
            except Exception as exc:
                last_error = str(exc); print("[FAIL]", model, "->", last_error); continue
    raise RuntimeError("No working Gemini model found. Last error: " + last_error + ". Call GET /list-models to see available models.")

def parse_soap(text: str) -> dict:
    sections = {"subjective": "", "objective": "", "assessment": "", "plan": ""}
    current = None
    for line in text.splitlines():
        stripped = line.strip()
        lower = stripped.lower().lstrip("*#:- ")
        if lower.startswith("subjective"): current = "subjective"; continue
        elif lower.startswith("objective"): current = "objective"; continue
        elif lower.startswith("assessment"): current = "assessment"; continue
        elif lower.startswith("plan"): current = "plan"; continue
        if current and stripped:
            sections[current] += (" " if sections[current] else "") + stripped
    return sections

@app.post("/generate-notes")
def generate(data: Generate, user=Depends(verify_token)):
    if not data.transcript.strip(): raise HTTPException(status_code=422, detail="Transcript is empty")
    prompt = ("You are a senior clinical physician writing SOAP notes.\n\n"
              "Analyze this transcript and write concise SOAP notes.\n"
              "Rules: Do NOT copy verbatim. Use clinical third-person style. "
              "Start each section with its label on its own line. If info missing write: Not documented.\n\n"
              "Transcript:\n'''\n" + data.transcript.strip() + "\n'''\n\n"
              "Subjective:\nObjective:\nAssessment:\nPlan:\n")
    try:
        raw = call_gemini(prompt)
        notes = parse_soap(raw)
        empty = [k for k,v in notes.items() if not v.strip()]
        if empty: print("[WARN] empty sections:", empty, "\nRaw:\n", raw)
        return {"notes": notes}
    except Exception as exc:
        print("[ERROR]", exc)
        raise HTTPException(status_code=500, detail="AI generation failed: " + str(exc))

@app.get("/notes")
def get_notes(user=Depends(verify_token)):
    conn = get_db()
    notes = conn.execute("SELECT * FROM notes ORDER BY id DESC").fetchall()
    conn.close()
    return [dict(n) for n in notes]

@app.post("/save-note")
def save_note(note: Note, user=Depends(verify_token)):
    conn = get_db()
    conn.execute("INSERT INTO notes (patient_name,subjective,objective,assessment,plan,raw_transcript,created_by) VALUES (?,?,?,?,?,?,?)",
                 (note.patient_name,note.subjective,note.objective,note.assessment,note.plan,note.raw_transcript,user["user_id"]))
    conn.commit(); conn.close()
    return {"message": "Saved"}

@app.delete("/notes/{id}")
def delete_note(id: int, user=Depends(verify_token)):
    if user["role"] not in ["doctor","admin"]: raise HTTPException(status_code=403, detail="Not allowed")
    conn = get_db()
    conn.execute("DELETE FROM notes WHERE id=?", (id,))
    conn.commit(); conn.close()
    return {"message": "Deleted"}