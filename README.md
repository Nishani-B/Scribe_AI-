# 🩺 Scribe AI – Medical SOAP Notes Generator

## Overview

Scribe AI is an intelligent web application that converts doctor-patient conversations into structured **SOAP notes** using AI.

It uses:

* Audio input (or transcript)
* AI (Gemini / OpenAI)
* Outputs structured medical notes

---

## Features

* Authentication (Login/Register)
* Audio Upload & Transcription (Whisper)
* AI-powered SOAP Note Generation
* Clean Dashboard UI
* Fast & responsive frontend

---

## Tech Stack

### Frontend

* HTML, CSS, JavaScript

### Backend

* FastAPI
* Whisper (Speech-to-text)
* Gemini API (AI processing)

---

## Project Structure

```
Scribe ai/
│
├── backend/
│   ├── main.py
│   └── ...
│
├── frontend/
│   └── index.html
│
└── README.md
```

---

## Setup Instructions

### Backend

```bash
cd backend
uvicorn main:app --reload
```

---

### Frontend

```bash
cd frontend
python -m http.server 5500
```

Open:

```
http://localhost:5500
```

---

## Environment Variables

Create `.env` file in backend:

```
GEMINI_API_KEY=AIzaSyD_BCr8ECqz2lM1PWEs_1uSH4KEYcaBPBg
```

---

## Demo Flow

1. Login
2. Upload audio
3. Generate SOAP notes
4. View structured output

---

## Future Improvements

* Real-time voice recording
* Cloud deployment
* PDF export
* Hospital integration

---

## Author

**Nishani Balaji**

---

## Acknowledgements

* OpenAI / Google Gemini
* Whisper AI
* FastAPI
