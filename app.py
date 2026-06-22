
from __future__ import annotations
import io, re, math
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any, Optional

import fitz
import pandas as pd
import pdfplumber
import streamlit as st

_ILLEGAL_XLSX_RE = re.compile(r"[\x00-\x08\x0B-\x0C\x0E-\x1F]")

def clean_excel_value(value):
    if isinstance(value, str):
        return _ILLEGAL_XLSX_RE.sub(" ", value)[:32767]
    return value

def clean_dataframe_for_excel(dataframe):
    safe = dataframe.copy()
    for col in safe.columns:
        if safe[col].dtype == "object":
            safe[col] = safe[col].map(clean_excel_value)
    return safe

st.set_page_config(page_title="Morning Coffee Wealth", page_icon="☕", layout="wide")

st.markdown("""
<style>
:root{--navy:#10243f;--gold:#c9a34e;--cream:#fffaf0}
.main .block-container{padding-top:1.5rem;}
.mc-hero{background:linear-gradient(135deg,#10243f,#1f3b63);padding:28px;border-radius:22px;color:white;margin-bottom:18px}
.mc-hero h1{margin:0;font-size:38px}.mc-hero p{margin:6px 0 0;color:#dbeafe}.gold{color:#c9a34e;font-weight:800;letter-spacing:1.5px;text-transform:uppercase}.note{background:#fffaf0;border:1px solid #f2d596;border-radius:14px;padding:14px}.small{font-size:13px;color:#667085}.stButton>button,.stDownloadButton>button{border-radius:10px;font-weight:800}
</style>
<div class="mc-hero"><div class="gold">Morning Coffee Wealth</div><h1>Financial Calculators + MF SOA Analyzer</h1><p>Soumya Banerjee · Mutual Fund Distributor · ARN-351495</p></div>
""", unsafe_allow_html=True)

# ---------- helpers ----------
def money(n):
    try:
        if n is None or not math.isfinite(float(n)): return "₹0"
        return "₹{:,.0f}".format(round(float(n)))
    except Exception: return "₹0"

def pct(n):
    try: return f"{float(n):.2f}%"
    except Exception: return "0.00%"

def monthly_rate(r): return float(r)/100/12

def sip_fv(payment, annual_return, months):
    r=monthly_rate(annual_return)
    if months<=0: return 0
    if abs(r)<1e-12: return payment*months
    return payment*((((1+r)**months-1)/r)*(1+r))

def show_table(rows):
    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)

def blank_number(label, key, help_text=None):
    raw = st.text_input(label, value="", key=key, help=help_text, placeholder="")
    if raw is None or not str(raw).strip():
        return None
    raw = str(raw).replace(",", "").replace("₹", "").replace("%", "").strip()
    try:
        return float(raw)
    except Exception:
        st.error(f"Enter a valid number for {label}.")
        return None

def ready(*values):
    return all(v is not None for v in values)

def wait_msg():
    st.info("Enter values to calculate.")

# ---------- calculators ----------
def sip_calculator():
    st.subheader("SIP Calculator")
    c=st.columns(6)
    p=blank_number("Monthly SIP ₹", "sip_p")
    r=blank_number("Expected return % p.a.", "sip_r")
    y=blank_number("Years", "sip_y")
    m=blank_number("Extra months", "sip_m") or 0
    w=blank_number("Extra weeks", "sip_w") or 0
    missed=blank_number("Missed installments", "sip_missed") or 0
    if not ready(p,r,y): return wait_msg()
    months=max(0, round(y*12+m+w/4.345)); paid=max(0, months-round(missed))
    full=sip_fv(p,r,months); actual=sip_fv(p,r,paid)
    show_table([
        {"Scenario":"Without missed installments","Installments":months,"Invested":money(p*months),"Value":money(full),"Gain":money(full-p*months)},
        {"Scenario":"After missed installments","Installments":paid,"Invested":money(p*paid),"Value":money(actual),"Gain":money(actual-p*paid)},
        {"Scenario":"Impact of missed installments","Installments":round(missed),"Invested":money(p*(months-paid)),"Value impact":money(full-actual),"Gain":"-"},
    ])

def stepup_calculator():
    st.subheader("Step-up SIP Calculator")
    c=st.columns(7)
    start=blank_number("Starting SIP ₹", "step_start")
    step_pct=blank_number("Step-up % yearly", "step_pct") or 0
    step_amt=blank_number("OR step-up amount ₹", "step_amt") or 0
    r=blank_number("Return % p.a.", "step_r")
    y=blank_number("Years", "step_y")
    m=blank_number("Extra months", "step_m") or 0
    missed=blank_number("Missed installments", "step_missed") or 0
    if not ready(start,r,y): return wait_msg()
    months=max(0,round(y*12+m)); paid=max(0,months-round(missed)); mr=monthly_rate(r)
    def run(n):
        corpus=invested=0.0
        for i in range(n):
            yrs=i//12
            pay=start+step_amt*yrs if step_amt>0 else start*((1+step_pct/100)**yrs)
            corpus=(corpus+pay)*(1+mr); invested+=pay
        return invested, corpus
    inv1,fv1=run(months); inv2,fv2=run(paid)
    show_table([
        {"Scenario":"Without missed installments","Invested":money(inv1),"Value":money(fv1),"Gain":money(fv1-inv1)},
        {"Scenario":"After missed installments","Invested":money(inv2),"Value":money(fv2),"Gain":money(fv2-inv2)},
        {"Scenario":"Impact","Invested":money(inv1-inv2),"Value":money(fv1-fv2),"Gain":"-"},
    ])

def stp_calculator():
    st.subheader("STP Calculator")
    c=st.columns(5)
    corpus=blank_number("Source corpus ₹", "stp_corpus")
    mode=c[1].selectbox("STP mode",["Fixed Amount","Percentage of Remaining Corpus","Fixed % of Original Corpus"], index=None, placeholder="Select")
    transfer=blank_number("Transfer amount ₹", "stp_transfer") or 0
    percent=(blank_number("STP percentage %", "stp_percent") or 0)/100
    freq=c[4].selectbox("Frequency",["Monthly","Weekly","Daily"], index=None, placeholder="Select")
    c2=st.columns(3)
    periods=blank_number("No. of periods", "stp_periods")
    sr=(blank_number("Source return % p.a.", "stp_sr") or 0)/100
    tr=(blank_number("Target return % p.a.", "stp_tr") or 0)/100
    if not ready(corpus, periods) or not mode or not freq: return wait_msg()
    ppy={"Daily":365,"Weekly":52,"Monthly":12}[freq]
    source=corpus; target=0.0; total=sg=tg=0.0; last=0.0; base=corpus*percent
    for i in range(1,int(periods)+1):
        before=source; source*=((1+sr)**(1/ppy)); sg+=source-before
        if mode=="Fixed Amount": amt=transfer
        elif mode=="Percentage of Remaining Corpus": amt=source*percent
        else: amt=source if i==int(periods) else base
        amt=min(amt,source); source-=amt; before=target+amt; target=before*((1+tr)**(1/ppy)); tg+=target-before; total+=amt; last=amt
        if source<=.5: source=0; break
    show_table([{"Metric":"Original Source Corpus","Value":money(corpus)}, {"Metric":"Total Transferred","Value":money(total)}, {"Metric":"Final Installment / Sweep","Value":money(last)}, {"Metric":"Source Growth Earned","Value":money(sg)}, {"Metric":"Target Growth Earned","Value":money(tg)}, {"Metric":"Source Balance","Value":money(source)}, {"Metric":"Target Value","Value":money(target)}, {"Metric":"Total Portfolio Value","Value":money(source+target)}])

def lumpsum_calculator():
    st.subheader("Lumpsum Calculator")
    c=st.columns(3)
    p=blank_number("Investment ₹", "lump_p")
    r=blank_number("Return % p.a.", "lump_r")
    y=blank_number("Years", "lump_y")
    if not ready(p,r,y): return wait_msg()
    fv=p*((1+r/100)**y); st.metric("Future Value",money(fv),money(fv-p))

def swp_calculator():
    st.subheader("SWP Calculator")
    corpus=blank_number("Initial corpus ₹", "swp_corpus")
    wd=blank_number("Monthly withdrawal ₹", "swp_wd")
    ret=blank_number("Return % p.a.", "swp_r")
    years=blank_number("Years", "swp_y")
    if not ready(corpus,wd,ret,years): return wait_msg()
    r=monthly_rate(ret); total=0; exhausted=None
    for month in range(1,int(years*12)+1):
        corpus=corpus*(1+r)-wd; total+=wd
        if corpus<=0: corpus=0; exhausted=month; break
    st.metric("Total Withdrawn", money(total)); st.metric("Remaining Corpus", money(corpus));
    if exhausted: st.warning(f"Corpus exhausted after {exhausted} months.")

def goal_calculator():
    st.subheader("Goal SIP Calculator")
    target=blank_number("Target amount ₹", "goal_target")
    ret=blank_number("Return % p.a.", "goal_r")
    years=blank_number("Years to goal", "goal_y")
    if not ready(target,ret,years): return wait_msg()
    r=monthly_rate(ret); n=int(years*12)
    if n <= 0: return st.error("Years to goal must be greater than 0.")
    sip=target/((((1+r)**n-1)/r)*(1+r)) if r else target/n
    st.metric("Required Monthly SIP", money(sip)); st.metric("Target Corpus", money(target))

def retirement_calculator():
    st.subheader("Retirement Calculator")
    age=blank_number("Current age", "ret_age")
    ret=blank_number("Retirement age", "ret_retire")
    life=blank_number("Life expectancy", "ret_life")
    exp=blank_number("Monthly expense today ₹", "ret_exp")
    inf_in=blank_number("Inflation %", "ret_inf")
    post_in=blank_number("Post-retirement return %", "ret_post")
    if not ready(age,ret,life,exp,inf_in,post_in): return wait_msg()
    inf=inf_in/100; post=post_in/100; y=max(0,ret-age); ry=max(0,life-ret); fut_exp=exp*((1+inf)**y); real=((1+post)/(1+inf))-1; ann=fut_exp*12; corpus=ann*ry if abs(real)<1e-6 else ann*(1-(1+real)**(-ry))/real
    st.metric("Monthly Expense at Retirement", money(fut_exp)); st.metric("Required Retirement Corpus", money(corpus)); st.metric("Years to Retirement", int(y))

def cagr_calculator():
    st.subheader("CAGR Calculator")
    begin=blank_number("Beginning value ₹", "cagr_begin")
    end=blank_number("Ending value ₹", "cagr_end")
    years=blank_number("Years", "cagr_years")
    if not ready(begin,end,years): return wait_msg()
    if begin <= 0 or years <= 0: return st.error("Beginning value and years must be greater than 0.")
    st.metric("CAGR", pct(((end/begin)**(1/years)-1)*100))

def emi_calculator():
    st.subheader("EMI + Prepayment vs Mutual Fund")
    principal=blank_number("Loan outstanding ₹", "emi_principal")
    loan_rate=blank_number("Loan rate %", "emi_rate")
    years=blank_number("Remaining tenure years", "emi_years")
    mfret_in=blank_number("MF return % p.a.", "emi_mfret")
    extra=blank_number("Extra EMI ₹/month", "emi_extra") or 0
    one=blank_number("One-time prepay ₹", "emi_one") or 0
    pre_m=blank_number("Prepay after month", "emi_pre_m") or 1
    rec=blank_number("Recurring annual prepay ₹", "emi_rec") or 0
    tax_in=blank_number("Tax on MF gains %", "emi_tax") or 0
    if not ready(principal, loan_rate, years, mfret_in): return wait_msg()
    rate=loan_rate/100/12; mfret=mfret_in/100; tax=tax_in/100; n=int(years*12)
    if principal <= 0 or n <= 0: return st.error("Loan outstanding and tenure must be greater than 0.")
    emi=principal*rate*(1+rate)**n/(((1+rate)**n)-1) if rate else principal/n
    def sim(prepay):
        bal=principal; month=0; interest=paid=0
        while bal>1 and month<1200:
            month+=1
            if prepay and one and month==int(pre_m): amt=min(one,bal); bal-=amt; paid+=amt
            if prepay and rec and month%12==0: amt=min(rec,bal); bal-=amt; paid+=amt
            intr=bal*rate; pay=min(emi+(extra if prepay else 0), bal+intr); bal-=pay-intr; interest+=intr; paid+=pay
            if bal<=1: break
        return month, interest, paid
    reg=sim(False); prep=sim(True); saved=reg[1]-prep[1]
    mfr=(1+mfret)**(1/12)-1
    fv_extra=extra*((((1+mfr)**n-1)/mfr)*(1+mfr)) if mfr else extra*n
    fv_one=one*((1+mfret)**max(0,(n-int(pre_m)+1)/12)); fv=fv_extra+fv_one; invested=extra*n+one; post=invested+max(0,fv-invested)*(1-tax)
    show_table([
        {"Scenario":"No prepayment","Closure time":f"{reg[0]} months","Total interest":money(reg[1]),"Total paid":money(reg[2])},
        {"Scenario":"With prepayment","Closure time":f"{prep[0]} months","Total interest":money(prep[1]),"Total paid":money(prep[2])},
        {"Scenario":"MF alternative of extra/prepay cash","Closure time":"-","Total interest":"-","Total paid":money(post)},
    ])
    st.info(f"Calculated EMI: {money(emi)} · Interest saved through prepayment: {money(saved)}")

# ---------- MF SOA parser ----------
# Transaction-first engine: only SIP Purchase, Purchase, Redemption / Switch Out.
# It ignores remarks, exit-load sections, scheme objective text, disclosures and valuation-only rows.

DATE_RE = re.compile(
    r"\b(\d{1,2}[-/]\d{1,2}[-/]\d{2,4}|\d{1,2}[-/][A-Za-z]{3,9}[-/]\d{2,4}|\d{1,2}\s+[A-Za-z]{3,9}\s+\d{2,4})\b"
)
FOLIO_RE = re.compile(r"folio\s*(?:no\.?|number|#)?\s*[:\-]?\s*([A-Z0-9][A-Z0-9/\-]{2,})", re.I)
NUM_RE = re.compile(r"[-+]?\(?₹?\d{1,3}(?:,\d{2,3})*(?:\.\d+)?\)?|[-+]?\(?₹?\d+(?:\.\d+)?\)?")

STRICT_TRANSACTION_RE = re.compile(
    r"\b(sip|systematic\s+investment|purchase|fresh\s+purchase|additional\s+purchase|subscription|lumpsum|lump\s+sum|redemption|redeem|repurchase|switch\s*out|switch-out|swp)\b",
    re.I,
)
PURCHASE_RE = re.compile(r"\b(sip|systematic\s+investment|purchase|fresh\s+purchase|additional\s+purchase|subscription|lumpsum|lump\s+sum)\b", re.I)
REDEMPTION_RE = re.compile(r"\b(redemption|redeem|repurchase|switch\s*out|switch-out|swp)\b", re.I)
SIP_RE = re.compile(r"\b(sip|systematic\s+investment)\b", re.I)

HARD_IGNORE_RE = re.compile(
    r"remarks|entry\s*load|exit\s*load|w\.?e\.?f\.?|nil\s+if\s+redeemed|date\s+of\s+allotment|"
    r"riskometer|benchmark|scheme\s+objective|investment\s+objective|disclaimer|note\s*:|nominee|bank\s+account|"
    r"registrar|address|email|mobile|pan\s*:|kyc|current\s+value|market\s+value|closing\s+balance|opening\s+balance|"
    r"grand\s+total|total\s+units|valuation|portfolio\s+summary|load\s+structure|expense\s+ratio",
    re.I,
)
SCHEME_HINT = re.compile(r"(fund|scheme|direct|regular|growth|idcw|dividend|equity|debt|hybrid|liquid|overnight|index|small cap|mid cap|large cap|flexi cap|elss|arbitrage)", re.I)
AMC_HINT = re.compile(r"mutual\s+fund|asset\s+management|cams|kfintech|mf\s*central", re.I)

@dataclass
class Txn:
    page: int
    source_engine: str
    amc_or_registrar: str
    folio: str
    scheme: str
    date: str
    transaction: str
    amount: Optional[float]
    nav: Optional[float]
    units: Optional[float]
    raw_text: str
    confidence: float


def sanitize_text(value: Any) -> Any:
    if isinstance(value, str):
        value = _ILLEGAL_XLSX_RE.sub(" ", value)
        value = re.sub(r"\s+", " ", value).strip()
        return value[:32767]
    return value


def clean_num(value):
    if value is None:
        return None
    s = str(value).replace("₹", "").replace(",", "").strip()
    neg = (s.startswith("(") and s.endswith(")")) or s.endswith(" Dr") or s.endswith(" DR")
    s = s.replace("Dr", "").replace("DR", "").strip("() ")
    try:
        n = float(s)
        return -n if neg else n
    except Exception:
        return None


def normalize_date(value):
    s = " ".join(str(value).replace("/", "-").split())
    for fmt in ["%d-%m-%Y", "%d-%m-%y", "%d-%b-%Y", "%d-%b-%y", "%d-%B-%Y", "%d-%B-%y", "%d %b %Y", "%d %b %y", "%d %B %Y", "%d %B %y"]:
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except Exception:
            pass
    return str(value)


def parse_date_obj(value):
    try:
        return datetime.strptime(normalize_date(value), "%Y-%m-%d")
    except Exception:
        return None


def unlock_with_pymupdf(pdf_bytes, password):
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    if doc.needs_pass:
        if not password:
            raise ValueError("This PDF is password protected. Enter the SOA/CAS password and retry.")
        if not doc.authenticate(password):
            raise ValueError("Wrong PDF password.")
    out = io.BytesIO()
    doc.save(out, garbage=4, deflate=True)
    doc.close()
    return out.getvalue()


def detect_context(text, ctx):
    line = sanitize_text(text)
    f = FOLIO_RE.search(line)
    if f:
        ctx["folio"] = f.group(1).strip()
    if AMC_HINT.search(line) and len(line) <= 160:
        ctx["amc_or_registrar"] = line
    if (
        SCHEME_HINT.search(line)
        and len(line) <= 190
        and not DATE_RE.search(line)
        and not HARD_IGNORE_RE.search(line)
        and not re.search(r"statement|account|investor|summary|transaction|service", line, re.I)
    ):
        ctx["scheme"] = line


def classify_transaction(text):
    if REDEMPTION_RE.search(text):
        return "Redemption"
    if SIP_RE.search(text):
        return "SIP Purchase"
    if PURCHASE_RE.search(text):
        return "Purchase"
    return ""


def looks_like_transaction_text(text):
    text = sanitize_text(text)
    if len(text) < 10 or HARD_IGNORE_RE.search(text):
        return False
    if not DATE_RE.search(text):
        return False
    if not STRICT_TRANSACTION_RE.search(text):
        return False
    # Avoid factsheet remarks such as: W.e.f. 05-Sep-2025 if redeemed within 30 days
    if re.search(r"if\s+redeemed|within\s+\d+\s+days|load", text, re.I):
        return False
    return True


def header_key(cell):
    h = re.sub(r"[^a-z0-9]+", "", str(cell or "").lower())
    if "date" in h or "posted" in h or "txn" in h and "date" in h:
        return "date"
    if any(x in h for x in ["transaction", "description", "particular", "activity", "type", "narration"]):
        return "transaction"
    if any(x in h for x in ["amount", "gross", "debit", "credit", "investment"]):
        return "amount"
    if "nav" in h or "price" in h:
        return "nav"
    if "unit" in h or "quantity" in h:
        return "units"
    return ""


def find_header_mapping(table):
    best = None
    for i, row in enumerate(table[:8]):
        mapping = {}
        for j, cell in enumerate(row or []):
            key = header_key(cell)
            if key and key not in mapping:
                mapping[key] = j
        score = sum(k in mapping for k in ["date", "transaction", "amount", "nav", "units"])
        if score >= 3 and "date" in mapping and "transaction" in mapping:
            best = (i, mapping)
            break
    return best


def row_to_line(row):
    return " ".join(sanitize_text(c) for c in row if c is not None and sanitize_text(c))


def parse_table_row(row, mapping, page, ctx, engine):
    def cell(key):
        idx = mapping.get(key)
        if idx is None or idx >= len(row):
            return ""
        return sanitize_text(row[idx])

    full = row_to_line(row)
    if HARD_IGNORE_RE.search(full):
        return None

    date_text = cell("date") or (DATE_RE.search(full).group(1) if DATE_RE.search(full) else "")
    txn_text = cell("transaction") or full
    if not date_text or not STRICT_TRANSACTION_RE.search(txn_text + " " + full):
        return None
    if re.search(r"if\s+redeemed|within\s+\d+\s+days|entry\s*load|exit\s*load|remarks", full, re.I):
        return None

    typ = classify_transaction(txn_text + " " + full)
    if typ not in {"SIP Purchase", "Purchase", "Redemption"}:
        return None

    amount = clean_num(cell("amount"))
    nav = clean_num(cell("nav"))
    units = clean_num(cell("units"))

    if amount is None or nav is None or units is None:
        inferred = infer_from_line(full, typ)
        amount = amount if amount is not None else inferred.get("amount")
        nav = nav if nav is not None else inferred.get("nav")
        units = units if units is not None else inferred.get("units")

    if amount is None and units is None:
        return None
    if typ == "Redemption":
        if amount is not None and amount > 0:
            amount = -amount
        if units is not None and units > 0:
            units = -units

    conf = 0.72 + (0.08 if nav else 0) + (0.08 if units else 0) + (0.05 if amount else 0) + (0.03 if ctx.get("folio") else 0) + (0.04 if ctx.get("scheme") else 0)
    return Txn(page, engine, ctx.get("amc_or_registrar", ""), ctx.get("folio", ""), ctx.get("scheme", ""), normalize_date(date_text), typ, amount, nav, units, full, round(min(conf, 0.99), 2))


def infer_from_line(line, typ):
    # Remove date first; parse only the financial tail after transaction text.
    text = DATE_RE.sub(" ", sanitize_text(line), count=1)
    nums = [n for n in (clean_num(x) for x in NUM_RE.findall(text)) if n is not None]
    nums = [n for n in nums if abs(n) > 0 and abs(n) != 2024 and abs(n) != 2025 and abs(n) != 2026]
    if not nums:
        return {"amount": None, "nav": None, "units": None}

    amount = nav = units = None
    # NAV is usually a decimal between 1 and 10000. Units often has 3 decimals. Amount often >= 10.
    # Common order in SOAs: amount, NAV, units, balance units OR units, amount, NAV.
    tail = nums[-5:]
    if len(tail) >= 3:
        # pick amount as largest absolute rupee-like value; NAV as decimal plausible not equal amount; units via amount/NAV closest if possible
        amount_candidates = [x for x in tail if abs(x) >= 1]
        amount = max(amount_candidates, key=lambda x: abs(x)) if amount_candidates else None
        nav_candidates = [x for x in tail if 1 <= abs(x) <= 10000 and x != amount]
        # prefer NAV that reconstructs an existing unit quantity
        best_nav = None; best_err = 999
        for cand in nav_candidates:
            if amount and cand:
                implied = abs(amount) / abs(cand)
                err = min([abs(abs(v) - implied) / max(1, implied) for v in tail if v not in (amount, cand)] or [999])
                if err < best_err:
                    best_err = err; best_nav = cand
        nav = best_nav or (nav_candidates[0] if nav_candidates else None)
        if amount is not None and nav not in (None, 0):
            implied_units = abs(amount) / abs(nav)
            candidates = [x for x in tail if x not in (amount, nav) and abs(x) > 0]
            if candidates:
                units = min(candidates, key=lambda x: abs(abs(x) - implied_units))
            else:
                units = implied_units
    elif len(tail) == 2:
        amount, units = tail[-2], tail[-1]
    elif len(tail) == 1:
        amount = tail[0]

    if typ == "Redemption":
        if amount is not None and amount > 0: amount = -amount
        if units is not None and units > 0: units = -units
    return {"amount": amount, "nav": nav, "units": units}


def parse_text_line(line, page, ctx, engine):
    line = sanitize_text(line)
    if not looks_like_transaction_text(line):
        return None
    typ = classify_transaction(line)
    if typ not in {"SIP Purchase", "Purchase", "Redemption"}:
        return None
    date_text = DATE_RE.search(line).group(1)
    vals = infer_from_line(line, typ)
    if vals["amount"] is None and vals["units"] is None:
        return None
    conf = 0.52 + (0.1 if vals["nav"] else 0) + (0.1 if vals["units"] else 0) + (0.08 if vals["amount"] else 0) + (0.05 if ctx.get("folio") else 0) + (0.05 if ctx.get("scheme") else 0)
    return Txn(page, engine, ctx.get("amc_or_registrar", ""), ctx.get("folio", ""), ctx.get("scheme", ""), normalize_date(date_text), typ, vals["amount"], vals["nav"], vals["units"], line, round(min(conf, 0.92), 2))


def extract_with_pymupdf(pdf_bytes):
    txns = []
    ctx = {"amc_or_registrar": "", "folio": "", "scheme": ""}
    pages_text = 0
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    for i, page in enumerate(doc, start=1):
        text = page.get_text("text") or ""
        if len(text.strip()) > 50:
            pages_text += 1
        for line in text.splitlines():
            detect_context(line, ctx)
            t = parse_text_line(line, i, ctx, "PyMuPDF-text")
            if t: txns.append(t)
        for block in page.get_text("blocks") or []:
            line = block[4] if len(block) >= 5 else ""
            detect_context(line, ctx)
            t = parse_text_line(line, i, ctx, "PyMuPDF-block")
            if t: txns.append(t)
    pages = len(doc)
    doc.close()
    return txns, {"pages": pages, "pymupdf_pages_with_text": pages_text}


def extract_with_pdfplumber(pdf_bytes):
    txns = []
    ctx = {"amc_or_registrar": "", "folio": "", "scheme": ""}
    pages_text = 0
    table_rows_seen = 0
    transaction_tables = 0
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for i, page in enumerate(pdf.pages, start=1):
            text = page.extract_text(x_tolerance=1.5, y_tolerance=3) or ""
            if len(text.strip()) > 50:
                pages_text += 1
            for line in text.splitlines():
                detect_context(line, ctx)
                t = parse_text_line(line, i, ctx, "pdfplumber-text")
                if t: txns.append(t)
            try:
                tables = page.extract_tables(table_settings={
                    "vertical_strategy": "text", "horizontal_strategy": "text",
                    "snap_tolerance": 3, "join_tolerance": 3, "intersection_tolerance": 5,
                    "min_words_vertical": 2, "min_words_horizontal": 1,
                }) or []
            except Exception:
                tables = []
            for table in tables:
                header = find_header_mapping(table)
                if not header:
                    continue
                transaction_tables += 1
                header_idx, mapping = header
                for row in table[header_idx + 1:]:
                    table_rows_seen += 1
                    if not row:
                        continue
                    line = row_to_line(row)
                    detect_context(line, ctx)
                    t = parse_table_row(row, mapping, i, ctx, "pdfplumber-table")
                    if t: txns.append(t)
    return txns, {"pdfplumber_pages_with_text": pages_text, "table_rows_seen": table_rows_seen, "transaction_tables": transaction_tables}


@st.cache_data(show_spinner=False)
def extract_transactions(pdf_bytes, password):
    unlocked = unlock_with_pymupdf(pdf_bytes, password)
    a, ma = extract_with_pymupdf(unlocked)
    b, mb = extract_with_pdfplumber(unlocked)
    rank = {"pdfplumber-table": 4, "pdfplumber-text": 3, "PyMuPDF-block": 2, "PyMuPDF-text": 1}
    unique = {}
    for t in a + b:
        # Deduplicate same economic transaction across engines. Do not use raw_text in key.
        key = (t.folio, t.scheme, t.date, t.transaction, round(t.amount or 0, 2), round(t.nav or 0, 6), round(t.units or 0, 6))
        if key not in unique or rank.get(t.source_engine, 0) > rank.get(unique[key].source_engine, 0):
            unique[key] = t
    rows = sorted(unique.values(), key=lambda x: (x.folio, x.scheme, x.date, x.transaction, x.page))
    meta = {**ma, **mb, "transactions_found": len(rows), "engines_used": "PyMuPDF + pdfplumber + pandas", "low_text_warning": ma.get("pymupdf_pages_with_text", 0) == 0 and mb.get("pdfplumber_pages_with_text", 0) == 0}
    return [asdict(r) for r in rows], meta


def weighted_average_nav(df):
    p = df[df["transaction"].isin(["SIP Purchase", "Purchase"])].copy()
    p["amount_abs"] = pd.to_numeric(p["amount"], errors="coerce").abs()
    p["units_abs"] = pd.to_numeric(p["units"], errors="coerce").abs()
    p = p[(p["amount_abs"] > 0) & (p["units_abs"] > 0)]
    if p.empty:
        return None
    return float(p["amount_abs"].sum() / p["units_abs"].sum())


def make_summary(df, current_nav=None, as_of_date=None):
    work = df.copy()
    for col in ["amount", "nav", "units"]:
        work[col] = pd.to_numeric(work.get(col), errors="coerce")
    purchases = work[work["transaction"].isin(["SIP Purchase", "Purchase"])]
    redemptions = work[work["transaction"].eq("Redemption")]
    total_purchase = purchases["amount"].abs().sum()
    total_redemption = redemptions["amount"].abs().sum()
    net_units = work["units"].sum(skipna=True)
    avg_nav = weighted_average_nav(work)
    current_value = float(net_units * current_nav) if current_nav and net_units else None
    cagr_val = calculate_cagr_from_nav(work, current_nav, as_of_date) if current_nav else None
    return pd.DataFrame([{
        "purchase_amount": total_purchase,
        "redemption_amount": total_redemption,
        "net_invested_cashflow": total_purchase - total_redemption,
        "net_units": net_units,
        "weighted_average_purchase_nav": avg_nav,
        "current_nav": current_nav,
        "current_value": current_value,
        "cagr_from_weighted_purchase_nav": cagr_val,
        "transactions": len(work),
        "average_confidence": work["confidence"].mean() if "confidence" in work else None,
    }])


def calculate_cagr_from_nav(df, current_nav, as_of_date=None):
    p = df[df["transaction"].isin(["SIP Purchase", "Purchase"])].copy()
    if p.empty or not current_nav:
        return None
    p["date_obj"] = pd.to_datetime(p["date"], errors="coerce")
    p["units_abs"] = pd.to_numeric(p["units"], errors="coerce").abs()
    p = p.dropna(subset=["date_obj", "units_abs"])
    p = p[p["units_abs"] > 0]
    if p.empty:
        return None
    avg_nav = weighted_average_nav(df)
    if not avg_nav or avg_nav <= 0:
        return None
    end = pd.to_datetime(as_of_date) if as_of_date else pd.Timestamp.today()
    weighted_days = ((end - p["date_obj"]).dt.days * p["units_abs"]).sum() / p["units_abs"].sum()
    years = weighted_days / 365.25
    if years <= 0:
        return None
    return ((float(current_nav) / avg_nav) ** (1 / years) - 1) * 100


def rolling_returns_from_transaction_nav(df):
    nav_df = df[df["nav"].notna()].copy()
    nav_df["date_obj"] = pd.to_datetime(nav_df["date"], errors="coerce")
    nav_df["nav"] = pd.to_numeric(nav_df["nav"], errors="coerce")
    nav_df = nav_df.dropna(subset=["date_obj", "nav"]).sort_values("date_obj")
    nav_df = nav_df[nav_df["nav"] > 0].drop_duplicates("date_obj", keep="last")
    out = []
    for years in [1, 2, 3, 5]:
        returns = []
        days = int(round(years * 365.25))
        for _, end_row in nav_df.iterrows():
            target = end_row["date_obj"] - pd.Timedelta(days=days)
            eligible = nav_df[nav_df["date_obj"] <= target]
            if eligible.empty:
                continue
            start_row = eligible.iloc[-1]
            actual_gap = (end_row["date_obj"] - start_row["date_obj"]).days / 365.25
            if actual_gap < years * 0.75:
                continue
            rr = ((end_row["nav"] / start_row["nav"]) ** (1 / actual_gap) - 1) * 100
            returns.append(rr)
        out.append({"Period": f"{years} Year", "Observations": len(returns), "Average Rolling Return": None if not returns else sum(returns) / len(returns)})
    return pd.DataFrame(out)


def excel_bytes(df, summary, rolling):
    out = io.BytesIO()
    safe_df = clean_dataframe_for_excel(df.applymap(sanitize_text))
    safe_summary = clean_dataframe_for_excel(summary.applymap(sanitize_text))
    safe_rolling = clean_dataframe_for_excel(rolling.applymap(sanitize_text))
    with pd.ExcelWriter(out, engine="openpyxl") as w:
        safe_df.to_excel(w, index=False, sheet_name="Transactions")
        safe_summary.to_excel(w, index=False, sheet_name="Summary")
        safe_rolling.to_excel(w, index=False, sheet_name="Rolling Returns")
        for ws in w.book.worksheets:
            ws.freeze_panes = "A2"
            for col in ws.columns:
                ml = max(len(str(cell.value or "")) for cell in list(col)[:200])
                ws.column_dimensions[col[0].column_letter].width = min(max(ml + 2, 10), 55)
    return out.getvalue()


def soa_analyzer():
    st.subheader("Mutual Fund SOA Analyzer")
    st.caption("Strict transaction parser: extracts only SIP Purchase, Purchase and Redemption rows with Amount, NAV and Units. Ignores remarks/load/disclosure text.")
    uploaded = st.file_uploader("Upload AMC / CAMS / KFintech / MF Central statement PDF", type=["pdf"])
    password = st.text_input("PDF password, if protected", type="password")
    cnav_col, date_col = st.columns(2)
    nav_raw = cnav_col.text_input("Current NAV for CAGR/current value", value="", key="soa_current_nav", placeholder="")
    current_nav = float(nav_raw.replace(",", "")) if nav_raw.strip() else 0.0
    date_raw = date_col.text_input("Current NAV date (YYYY-MM-DD)", value="", key="soa_current_date", placeholder="")
    try:
        as_of_date = pd.to_datetime(date_raw).date() if date_raw.strip() else datetime.today().date()
    except Exception:
        st.error("Enter Current NAV date in YYYY-MM-DD format."); return
    if not uploaded:
        st.info("Upload a detailed folio-based mutual fund Statement of Account PDF to start.")
        return
    try:
        with st.spinner("Reading PDF and extracting only purchase/SIP/redemption transactions..."):
            rows, meta = extract_transactions(uploaded.read(), password or None)
    except Exception as e:
        st.error(str(e))
        return
    c = st.columns(5)
    c[0].metric("Pages", meta.get("pages", 0))
    c[1].metric("Text pages", max(meta.get("pymupdf_pages_with_text", 0), meta.get("pdfplumber_pages_with_text", 0)))
    c[2].metric("Transaction tables", meta.get("transaction_tables", 0))
    c[3].metric("Rows scanned", meta.get("table_rows_seen", 0))
    c[4].metric("Transactions found", meta.get("transactions_found", 0))
    if meta.get("low_text_warning"):
        st.warning("This looks like a scanned/image PDF. Upload the original AMC/CAMS/KFin generated PDF for best results.")
    if not rows:
        st.warning("No SIP Purchase, Purchase or Redemption transaction rows were detected. Upload a detailed transaction SOA/CAS PDF, not a valuation-only statement.")
        return

    df = pd.DataFrame(rows)
    for col in ["amount", "nav", "units"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df[df["transaction"].isin(["SIP Purchase", "Purchase", "Redemption"])]
    df = df.sort_values(["folio", "scheme", "date", "transaction"])
    cols = ["folio", "scheme", "date", "transaction", "amount", "nav", "units", "page", "source_engine", "confidence", "raw_text"]
    df = df[[x for x in cols if x in df.columns] + [x for x in df.columns if x not in cols]]
    df = clean_dataframe_for_excel(df.applymap(sanitize_text))

    st.subheader("Extracted Financial Transactions")
    st.dataframe(df, width="stretch", hide_index=True)

    summary = make_summary(df, current_nav if current_nav > 0 else None, as_of_date)
    rolling = rolling_returns_from_transaction_nav(df)
    st.subheader("Summary")
    s = summary.copy()
    display_s = s.copy()
    for col in ["purchase_amount", "redemption_amount", "net_invested_cashflow", "current_value"]:
        if col in display_s: display_s[col] = display_s[col].map(lambda x: money(x) if pd.notna(x) else "")
    for col in ["weighted_average_purchase_nav", "current_nav"]:
        if col in display_s: display_s[col] = display_s[col].map(lambda x: "" if pd.isna(x) or x is None else f"{float(x):.4f}")
    if "cagr_from_weighted_purchase_nav" in display_s:
        display_s["cagr_from_weighted_purchase_nav"] = display_s["cagr_from_weighted_purchase_nav"].map(lambda x: "" if pd.isna(x) or x is None else pct(x))
    st.dataframe(display_s, width="stretch", hide_index=True)

    st.subheader("1Y / 2Y / 3Y / 5Y Rolling Returns")
    roll_display = rolling.copy()
    roll_display["Average Rolling Return"] = roll_display["Average Rolling Return"].map(lambda x: "Not enough NAV observations" if pd.isna(x) or x is None else pct(x))
    st.dataframe(roll_display, width="stretch", hide_index=True)
    st.caption("Rolling returns are calculated from NAV values found in the SOA transaction rows. For exact rolling returns, the app would need historical daily NAV data.")

    c1, c2 = st.columns(2)
    c1.download_button("Download CSV", df.to_csv(index=False).encode(), "mf_soa_transactions.csv", "text/csv", width="stretch")
    c2.download_button("Download Excel", excel_bytes(df, summary, rolling), "mf_soa_analysis.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", width="stretch")
    with st.expander("Parser rule used"):
        st.write("The SOA Analyzer now keeps only rows with a valid date and transaction keyword: SIP/Systematic Investment, Purchase/Subscription/Lumpsum, Redemption/Redeem/Repurchase/SWP/Switch Out. It rejects rows containing Remarks, Entry Load, Exit Load, W.e.f., riskometer, benchmark, nominee, bank, disclaimer and valuation-summary text.")



# ---------- UI routing ----------
tabs=st.tabs(['SIP','Step-up SIP','STP','EMI vs MF','Lumpsum','SWP','Goal SIP','Retirement','CAGR','MF SOA Analyzer'])
with tabs[0]: sip_calculator()
with tabs[1]: stepup_calculator()
with tabs[2]: stp_calculator()
with tabs[3]: emi_calculator()
with tabs[4]: lumpsum_calculator()
with tabs[5]: swp_calculator()
with tabs[6]: goal_calculator()
with tabs[7]: retirement_calculator()
with tabs[8]: cagr_calculator()
with tabs[9]: soa_analyzer()

st.markdown('<div class="small">Disclaimer: Calculators are for illustration only. Mutual fund investments are subject to market risks. Read all scheme-related documents carefully.</div>', unsafe_allow_html=True)
