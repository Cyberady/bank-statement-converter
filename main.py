from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import FileResponse
import os
import shutil
import pdfplumber
import re
import pandas as pd
from uuid import uuid4

app = FastAPI(title="Bank Statement Converter API")

UPLOAD_DIR = "uploads"
EXPORT_DIR = "exports"

os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(EXPORT_DIR, exist_ok=True)

DATE_PATTERN = re.compile(r"\d{2}-\d{2}-\d{4}")
AMOUNT_PATTERN = re.compile(r"([\d,]+\.\d{2})")


# -------------------- CORE EXTRACTION --------------------

def extract_transactions(text: str):
    lines = text.split("\n")
    transactions = []

    for line in lines:
        date_match = DATE_PATTERN.search(line)
        if not date_match:
            continue

        amounts = AMOUNT_PATTERN.findall(line)
        if not amounts:
            continue

        date = date_match.group()

        # Default assumption
        amount = amounts[-1].replace(",", "")
        balance = None

        if len(amounts) >= 2:
            balance = amounts[-1].replace(",", "")
            amount = amounts[-2].replace(",", "")

        description = line.replace(date, "")
        for amt in amounts:
            description = description.replace(amt, "")
        description = description.strip()

        transactions.append({
            "date": date,
            "description": description,
            "amount": float(amount),
            "balance": float(balance) if balance else None,
            "type": "unknown"
        })

    return transactions


# -------------------- TYPE DETECTION LOGIC --------------------

def apply_transaction_logic(transactions):
    prev_balance = None

    for txn in transactions:
        desc = txn["description"].upper()
        curr_balance = txn["balance"]

        # 1️⃣ Explicit CR / DR has highest priority
        if " CR" in desc or "/CR/" in desc:
            txn["type"] = "credit"
        elif " DR" in desc or "/DR/" in desc:
            txn["type"] = "debit"

        # 2️⃣ Balance comparison (fallback)
        elif prev_balance is not None and curr_balance is not None:
            if curr_balance > prev_balance:
                txn["type"] = "credit"
            elif curr_balance < prev_balance:
                txn["type"] = "debit"

        prev_balance = curr_balance

    return transactions


# -------------------- API ENDPOINT --------------------

@app.post("/upload")
async def upload_pdf(file: UploadFile = File(...)):
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are allowed")

    file_id = uuid4().hex
    base_name = os.path.splitext(file.filename)[0]
    safe_name = f"{base_name}_{file_id}"

    pdf_path = os.path.join(UPLOAD_DIR, f"{safe_name}.pdf")

    # Save file
    with open(pdf_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    # Extract text
    text = ""
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            text += page.extract_text() or ""

    if not text.strip():
        raise HTTPException(status_code=400, detail="Unable to read PDF text")

    # Process transactions
    transactions = extract_transactions(text)
    transactions = apply_transaction_logic(transactions)

    if not transactions:
        raise HTTPException(status_code=400, detail="No transactions found")

    # DataFrame
    df = pd.DataFrame(transactions)

    # Sort for safety
    df["date"] = pd.to_datetime(df["date"], format="%d-%m-%Y", errors="coerce")
    df = df.sort_values("date").reset_index(drop=True)

    # Export paths
    csv_path = os.path.join(EXPORT_DIR, f"{safe_name}.csv")
    excel_path = os.path.join(EXPORT_DIR, f"{safe_name}.xlsx")

    df.to_csv(csv_path, index=False)
    df.to_excel(excel_path, index=False)

    # Summary (safe)
    total_credit = df[df["type"] == "credit"]["amount"].sum()
    total_debit = df[df["type"] == "debit"]["amount"].sum()

    opening_balance = df.iloc[0]["balance"]
    closing_balance = df.iloc[-1]["balance"]

    return {
        "message": "Statement processed successfully ✅",
        "summary": {
            "total_transactions": len(df),
            "total_credit": round(float(total_credit), 2),
            "total_debit": round(float(total_debit), 2),
            "opening_balance": opening_balance,
            "closing_balance": closing_balance
        },
        "download_csv": f"/download/csv/{safe_name}",
        "download_excel": f"/download/excel/{safe_name}"
    }


# -------------------- DOWNLOAD ENDPOINTS --------------------

@app.get("/download/csv/{name}")
def download_csv(name: str):
    path = os.path.join(EXPORT_DIR, f"{name}.csv")
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(path, filename=f"{name}.csv")


@app.get("/download/excel/{name}")
def download_excel(name: str):
    path = os.path.join(EXPORT_DIR, f"{name}.xlsx")
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(path, filename=f"{name}.xlsx")
