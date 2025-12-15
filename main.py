from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
import os, shutil, re
import pdfplumber
import pandas as pd
from uuid import uuid4

app = FastAPI(title="BankConv API – CA Format V4")

# -------------------- CORS --------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # later restrict
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

# -------------------- CORE EXTRACTION --------------------
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

        amount = float(amounts[-1].replace(",", ""))
        balance = None
        if len(amounts) >= 2:
            balance = float(amounts[-1].replace(",", ""))
            amount = float(amounts[-2].replace(",", ""))

        description = line.replace(date, "")
        for a in amounts:
            description = description.replace(a, "")
        description = description.strip()

        txns.append({
            "date": date,
            "description": description,
            "raw_amount": amount,
            "balance": balance,
            "type": "unknown"
        })

    return txns

# -------------------- TRANSACTION LOGIC (CA-GRADE) --------------------
def apply_transaction_logic(txns):
    prev_balance = None

    for t in txns:
        desc = t["description"].upper()
        bal = t["balance"]

        # Priority 1: CR / DR text
        if " CR" in desc or "/CR/" in desc:
            t["type"] = "credit"
        elif " DR" in desc or "/DR/" in desc:
            t["type"] = "debit"

        # Priority 2: Balance comparison
        elif prev_balance is not None and bal is not None:
            if bal > prev_balance:
                t["type"] = "credit"
            elif bal < prev_balance:
                t["type"] = "debit"

        prev_balance = bal if bal is not None else prev_balance

    return txns

# -------------------- CA FORMAT BUILDER --------------------
def build_ca_dataframe(txns):
    rows = []

    for t in txns:
        debit = t["raw_amount"] if t["type"] == "debit" else ""
        credit = t["raw_amount"] if t["type"] == "credit" else ""

        rows.append({
            "Date": t["date"],
            "Particulars": t["description"],
            "Debit": debit,
            "Credit": credit,
            "Balance": t["balance"]
        })

    df = pd.DataFrame(rows)

    df["Date"] = pd.to_datetime(df["Date"], dayfirst=True, errors="coerce")
    df = df.sort_values("Date").reset_index(drop=True)

    return df

# -------------------- API --------------------
@app.post("/upload")
async def upload(file: UploadFile = File(...)):
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "Only PDF files allowed")

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

    if not text.strip():
        raise HTTPException(400, "Unable to read PDF text")

    txns = extract_transactions(text)
    txns = apply_transaction_logic(txns)

    if not txns:
        raise HTTPException(400, "No transactions found")

    df = build_ca_dataframe(txns)

    csv_path = os.path.join(EXPORT_DIR, safe + ".csv")
    xlsx_path = os.path.join(EXPORT_DIR, safe + ".xlsx")
    df.to_csv(csv_path, index=False)
    df.to_excel(xlsx_path, index=False)

    return {
        "message": "Converted successfully (CA Format) 💼📊",
        "total_transactions": len(df),
        "download_csv": f"/download/csv/{safe}",
        "download_excel": f"/download/excel/{safe}"
    }

# -------------------- DOWNLOAD --------------------
@app.get("/download/csv/{name}")
def csv(name: str):
    path = os.path.join(EXPORT_DIR, name + ".csv")
    if not os.path.exists(path):
        raise HTTPException(404, "File not found")
    return FileResponse(path, filename=name + ".csv")

@app.get("/download/excel/{name}")
def excel(name: str):
    path = os.path.join(EXPORT_DIR, name + ".xlsx")
    if not os.path.exists(path):
        raise HTTPException(404, "File not found")
    return FileResponse(path, filename=name + ".xlsx")
