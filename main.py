from fastapi import FastAPI, UploadFile, File
from fastapi.responses import FileResponse
import os
import shutil
import pdfplumber
import re
import pandas as pd

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

    for line in lines:
        date_match = date_pattern.search(line)
        if not date_match:
            continue

        amounts = amount_pattern.findall(line)
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

        transactions.append({
            "date": date,
            "description": description,
            "amount": amount,
            "balance": balance
        })

    return transactions


def calculate_summary(transactions):
    total_credit = 0.0
    total_debit = 0.0

    for i in range(1, len(transactions)):
        prev = transactions[i - 1]["balance"]
        curr = transactions[i]["balance"]

        if prev is None or curr is None:
            continue

        diff = curr - prev
        if diff > 0:
            total_credit += diff
        else:
            total_debit += abs(diff)

    opening_balance = transactions[0]["balance"] if transactions else 0
    closing_balance = transactions[-1]["balance"] if transactions else 0

    return {
        "total_transactions": len(transactions),
        "total_credit": round(total_credit, 2),
        "total_debit": round(total_debit, 2),
        "opening_balance": opening_balance,
        "closing_balance": closing_balance
    }


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
    summary = calculate_summary(transactions)

    df = pd.DataFrame(transactions)
    base = os.path.splitext(file.filename)[0]

    csv_path = os.path.join(EXPORT_DIR, f"{base}.csv")
    excel_path = os.path.join(EXPORT_DIR, f"{base}.xlsx")

    df.to_csv(csv_path, index=False)
    df.to_excel(excel_path, index=False)

    return {
        "message": "Statement processed successfully ✅",
        "summary": summary,
        "total_transactions": len(transactions),
        "download_csv": f"/download/csv/{base}",
        "download_excel": f"/download/excel/{base}"
    }


@app.get("/download/csv/{name}")
def download_csv(name: str):
    return FileResponse(
        os.path.join(EXPORT_DIR, f"{name}.csv"),
        filename=f"{name}.csv"
    )


@app.get("/download/excel/{name}")
def download_excel(name: str):
    return FileResponse(
        os.path.join(EXPORT_DIR, f"{name}.xlsx"),
        filename=f"{name}.xlsx"
    )
