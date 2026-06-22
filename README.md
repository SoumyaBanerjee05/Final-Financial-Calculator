# Morning Coffee Wealth - Financial Calculators + MF SOA Analyzer

Streamlit app with blank calculator inputs and an accuracy-first Mutual Fund SOA Analyzer.

## MF SOA Analyzer rule
The parser only accepts dated transaction rows for:
- SIP Purchase
- Purchase / Lumpsum / Switch In
- Redemption / SWP / Switch Out

A row is accepted only when Amount, NAV and Units pass the validation:

`Amount ≈ NAV × Units`

Narrative text such as remarks, entry load, exit load, riskometer, benchmark, nominee, bank details, disclosures and valuation summaries are rejected.

## Deploy on Streamlit Cloud
Upload these files to the root of your GitHub repo:
- app.py
- requirements.txt
- README.md

Main file path:
`app.py`

## Requirements
Uses only zero-cost packages:
- streamlit
- pandas
- pdfplumber
- PyMuPDF
- openpyxl
