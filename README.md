# 🏦 Bank Statement Converter API

A production-ready FastAPI backend that converts bank statement PDFs into structured CSV and Excel files with automatic transaction detection and balance-based debit/credit logic.

## 🚀 Live API
https://bank-statement-converter-moih.onrender.com/docs

## ✨ Features
- Upload multi-page bank statement PDFs
- Extract transactions (date, description, amount, balance)
- Intelligent debit/credit detection using balance logic
- Generate summary (total credit, total debit, opening & closing balance)
- Export results as CSV and Excel
- Supports large statements (200+ transactions)

## 🛠 Tech Stack
- FastAPI
- Python
- pdfplumber
- Pandas
- Uvicorn

## 📤 API Endpoint
`POST /upload`

Upload a bank statement PDF and receive:
- Transaction summary
- Downloadable CSV & Excel files

## 📊 Sample Summary Output
```json
{
  "total_transactions": 283,
  "total_credit": 200664,
  "total_debit": 240011.78,
  "opening_balance": 40149.89,
  "closing_balance": 802.11
}
