from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
import os, shutil, re
import pdfplumber
import pandas as pd
from uuid import uuid4

app = FastAPI(title="BankConv API – V4.2 (CA Format + Summary)")

# -------------------- CORS --------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # restrict later
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

# -------------------- EXTRACTION --------------------
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

        particulars = line.replace(date, "")
        for a in amounts:
            particulars = particulars.replace(a, "")
        particulars = particulars.strip()

        txns.append({
            "date": date,
            "particulars": particulars,
            "amount": amount,
            "balance": balance,
            "type": "unknown"
        })

    return txns

# -------------------- CA DEBIT / CREDIT LOGIC --------------------
def apply_ca_logic(txns):
    prev_balance = None

    for t in txns:
        desc = t["particulars"].upper()
        bal = t["balance"]

        if " CR" in desc or "/CR/" in desc:
            t["type"] = "credit"
        elif " DR" in desc or "/DR/" in desc:
            t["type"] = "debit"
        elif prev_balance is not None and bal is not None:
            t["type"] = "credit" if bal > prev_balance else "debit"

        prev_balance = bal if bal is not None else prev_balance

        # CA columns
        if t["type"] == "credit":
            t["credit"] = t["amount"]
            t["debit"] = 0.0
        elif t["type"] == "debit":
            t["debit"] = t["amount"]
            t["credit"] = 0.0
        else:
            t["debit"] = 0.0
            t["credit"] = 0.0

        del t["amount"]
        del t["type"]

    return txns

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

    txns = apply_ca_logic(extract_transactions(text))
    if not txns:
        raise HTTPException(400, "No transactions found")

    df = pd.DataFrame(txns)
    df["date"] = pd.to_datetime(df["date"], dayfirst=True, errors="coerce")
    df = df.sort_values("date").reset_index(drop=True)

    # -------------------- CA SUMMARY --------------------
    total_debit = df["debit"].sum()
    total_credit = df["credit"].sum()

    debit_count = (df["debit"] > 0).sum()
    credit_count = (df["credit"] > 0).sum()

    balances = df["balance"].dropna()
    opening_balance = balances.iloc[0] if not balances.empty else None
    closing_balance = balances.iloc[-1] if not balances.empty else None

    net_change = (
        closing_balance - opening_balance
        if opening_balance is not None and closing_balance is not None
        else None
    )

    # -------------------- EXPORT --------------------
    csv_path = os.path.join(EXPORT_DIR, safe + ".csv")
    xlsx_path = os.path.join(EXPORT_DIR, safe + ".xlsx")

    df.to_csv(csv_path, index=False)
    df.to_excel(xlsx_path, index=False)

    return {
        "message": "Converted in CA Format ✅",
        "summary": {
            "total_transactions": len(df),
            "total_debit": round(total_debit, 2),
            "total_credit": round(total_credit, 2),
            "debit_count": int(debit_count),
            "credit_count": int(credit_count),
            "opening_balance": opening_balance,
            "closing_balance": closing_balance,
            "net_change": net_change,
            "period": {
                "from": str(df["date"].min().date()),
                "to": str(df["date"].max().date())
            }
        },
        "download_csv": f"/download/csv/{safe}",
        "download_excel": f"/download/excel/{safe}"
    }

# -------------------- DOWNLOAD --------------------
@app.get("/download/csv/{name}")
def download_csv(name: str):
    path = os.path.join(EXPORT_DIR, name + ".csv")
    if not os.path.exists(path):
        raise HTTPException(404, "CSV not found")
    return FileResponse(path, media_type="text/csv", filename=name + ".csv")


@app.get("/download/excel/{name}")
def download_excel(name: str):
    path = os.path.join(EXPORT_DIR, name + ".xlsx")
    if not os.path.exists(path):
        raise HTTPException(404, "Excel not found")
    return FileResponse(
        path,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=name + ".xlsx"
    )
