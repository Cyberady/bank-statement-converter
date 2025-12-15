from fastapi import FastAPI, UploadFile, File
import os
import shutil
import pdfplumber
import re
import pandas as pd
from fastapi.responses import FileResponse

app = FastAPI()

UPLOAD_DIR = "uploads"
EXPORT_DIR = "exports"

os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(EXPORT_DIR, exist_ok=True)


def extract_transactions(text: str):
    lines = text.split("\n")
    transactions = []

    date_pattern = re.compile(r"\d{2}-\d{2}-\d{4}")
    amount_pattern = re.compile(r"([\d,]+\.\d{2})")

    prev_balance = None

    for line in lines:
        date_match = date_pattern.search(line)
        if not date_match:
            continue

        amounts = amount_pattern.findall(line)
        if len(amounts) < 1:
            continue

        date = date_match.group()

        amount = amounts[-1].replace(",", "")
        balance = None
        if len(amounts) >= 2:
            balance = amounts[-1].replace(",", "")
            amount = amounts[-2].replace(",", "")

        description = line.replace(date, "")
        for amt in amounts:
            description = description.replace(amt, "")
        description = description.strip()

        # Step 1: Text based detection
        txn_type = "unknown"
        desc_upper = description.upper()
        if " CR" in desc_upper or "/CR/" in desc_upper:
            txn_type = "credit"
        elif " DR" in desc_upper or "/DR/" in desc_upper:
            txn_type = "debit"

        # Step 2: Balance based detection (SMART PART)
        if balance is not None and prev_balance is not None:
            if balance > prev_balance:
                txn_type = "credit"
            elif balance < prev_balance:
                txn_type = "debit"

        prev_balance = balance

        transactions.append({
            "date": date,
            "description": description,
            "type": txn_type,
            "amount": float(amount),
            "balance": float(balance) if balance else None
        })

    return transactions


@app.post("/upload")
async def upload_pdf(file: UploadFile = File(...)):
    file_path = os.path.join(UPLOAD_DIR, file.filename)

    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    text = ""
    with pdfplumber.open(file_path) as pdf:
        for page in pdf.pages:
            text += page.extract_text() or ""

    transactions = extract_transactions(text)

    df = pd.DataFrame(transactions)

    base_name = os.path.splitext(file.filename)[0]
    csv_path = os.path.join(EXPORT_DIR, f"{base_name}.csv")
    excel_path = os.path.join(EXPORT_DIR, f"{base_name}.xlsx")

    df.to_csv(csv_path, index=False)
    df.to_excel(excel_path, index=False)

    # SUMMARY
    total_credit = df[df["type"] == "credit"]["amount"].sum()
    total_debit = df[df["type"] == "debit"]["amount"].sum()

    opening_balance = df.iloc[0]["balance"]
    closing_balance = df.iloc[-1]["balance"]

    return {
        "message": "Statement processed successfully ✅",
        "summary": {
            "total_transactions": len(df),
            "total_credit": round(total_credit, 2),
            "total_debit": round(total_debit, 2),
            "opening_balance": opening_balance,
            "closing_balance": closing_balance
        },
        "total_transactions": len(df),
        "download_csv": f"/download/csv/{base_name}",
        "download_excel": f"/download/excel/{base_name}"
    }


@app.get("/download/csv/{name}")
def download_csv(name: str):
    return FileResponse(
        path=os.path.join(EXPORT_DIR, f"{name}.csv"),
        filename=f"{name}.csv",
        media_type="text/csv"
    )


@app.get("/download/excel/{name}")
def download_excel(name: str):
    return FileResponse(
        path=os.path.join(EXPORT_DIR, f"{name}.xlsx"),
        filename=f"{name}.xlsx",
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
