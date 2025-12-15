from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
import os, shutil, re
import pdfplumber
import pandas as pd
from uuid import uuid4

app = FastAPI(title="BankConv API – V3")

# -------------------- CORS (VERY IMPORTANT) --------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # for now (later restrict)
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -------------------- DIRECTORIES --------------------
UPLOAD_DIR = "uploads"
EXPORT_DIR = "exports"
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(EXPORT_DIR, exist_ok=True)

# -------------------- REGEX --------------------
DATE_PATTERN = re.compile(r"\d{2}-\d{2}-\d{4}")
AMOUNT_PATTERN = re.compile(r"([\d,]+\.\d{2})")

# -------------------- CORE LOGIC --------------------
def extract_transactions(text: str):
    lines = text.split("\n")
    txns = []

    for line in lines:
        date_match = DATE_PATTERN.search(line)
        if not date_match:
            continue

        amounts = AMOUNT_PATTERN.findall(line)
        if not amounts:
            continue

        date = date_match.group()
        amount = amounts[-1].replace(",", "")
        balance = None

        if len(amounts) >= 2:
            balance = amounts[-1].replace(",", "")
            amount = amounts[-2].replace(",", "")

        description = line.replace(date, "")
        for a in amounts:
            description = description.replace(a, "")
        description = description.strip()

        txns.append({
            "date": date,
            "description": description,
            "amount": float(amount),
            "balance": float(balance) if balance else None,
            "type": "unknown"
        })

    return txns


def apply_balance_logic(txns):
    prev_balance = None

    for t in txns:
        desc = t["description"].upper()
        bal = t["balance"]

        if " CR" in desc or "/CR/" in desc:
            t["type"] = "credit"
        elif " DR" in desc or "/DR/" in desc:
            t["type"] = "debit"
        elif prev_balance is not None and bal is not None:
            t["type"] = "credit" if bal > prev_balance else "debit"

        prev_balance = bal if bal is not None else prev_balance

    return txns

# -------------------- API --------------------
@app.post("/upload")
async def upload(file: UploadFile = File(...)):
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "Only PDF allowed")

    uid = uuid4().hex
    base = os.path.splitext(file.filename)[0]
    safe = f"{base}_{uid}"

    pdf_path = os.path.join(UPLOAD_DIR, safe + ".pdf")
    with open(pdf_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    text = ""
    with pdfplumber.open(pdf_path) as pdf:
        for p in pdf.pages:
            text += p.extract_text() or ""

    txns = apply_balance_logic(extract_transactions(text))
    if not txns:
        raise HTTPException(400, "No transactions found")

    df = pd.DataFrame(txns)
    df["date"] = pd.to_datetime(df["date"], dayfirst=True, errors="coerce")
    df = df.sort_values("date")

    csv = os.path.join(EXPORT_DIR, safe + ".csv")
    xlsx = os.path.join(EXPORT_DIR, safe + ".xlsx")
    df.to_csv(csv, index=False)
    df.to_excel(xlsx, index=False)

    return {
        "message": "Converted successfully 🚀",
        "total_transactions": len(df),
        "download_csv": f"/download/csv/{safe}",
        "download_excel": f"/download/excel/{safe}"
    }

@app.get("/download/csv/{name}")
def csv(name: str):
    return FileResponse(os.path.join(EXPORT_DIR, name + ".csv"))

@app.get("/download/excel/{name}")
def excel(name: str):
    return FileResponse(os.path.join(EXPORT_DIR, name + ".xlsx"))
