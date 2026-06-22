
from __future__ import annotations
import io, re, math
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Tuple

import fitz
import pandas as pd
import pdfplumber
import streamlit as st

import re

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


# Auto-generate unique keys for Streamlit number_input widgets.
# This prevents StreamlitDuplicateElementId when different tabs reuse labels like "Years".
from streamlit.delta_generator import DeltaGenerator
_original_number_input = DeltaGenerator.number_input
_number_input_counter = {"count": 0}
def _number_input_with_unique_key(self, *args, **kwargs):
    if kwargs.get("key") is None:
        _number_input_counter["count"] += 1
        label = str(args[0]) if args else str(kwargs.get("label", "number_input"))
        safe_label = re.sub(r"[^a-zA-Z0-9_]+", "_", label).strip("_").lower()[:40]
        kwargs["key"] = f"auto_number_{_number_input_counter['count']}_{safe_label}"
    return _original_number_input(self, *args, **kwargs)
DeltaGenerator.number_input = _number_input_with_unique_key

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
        if not math.isfinite(float(n)): return "₹0"
        return "₹{:,.0f}".format(round(float(n))).replace(",", "_").replace("_", ",")
    except Exception: return "₹0"
def pct(n):
    try: return f"{float(n):.2f}%"
    except Exception: return "0.00%"
def monthly_rate(r): return r/100/12

def sip_fv(payment, annual_return, months):
    r=monthly_rate(annual_return)
    if months<=0: return 0
    if abs(r)<1e-12: return payment*months
    return payment*((((1+r)**months-1)/r)*(1+r))

def show_table(rows):
    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)

# ---------- calculators ----------
def sip_calculator():
    st.subheader("SIP Calculator")
    c=st.columns(6)
    p=c[0].number_input("Monthly SIP ₹", 0.0, value=10000.0, step=1000.0)
    r=c[1].number_input("Expected return % p.a.", value=12.0, step=.25)
    y=c[2].number_input("Years", 0, value=10)
    m=c[3].number_input("Extra months", 0, value=0)
    w=c[4].number_input("Extra weeks", 0, value=0)
    missed=c[5].number_input("Missed installments", 0, value=0)
    months=max(0, round(y*12+m+w/4.345)); paid=max(0, months-missed)
    full=sip_fv(p,r,months); actual=sip_fv(p,r,paid)
    show_table([
        {"Scenario":"Without missed installments","Installments":months,"Invested":money(p*months),"Value":money(full),"Gain":money(full-p*months)},
        {"Scenario":"After missed installments","Installments":paid,"Invested":money(p*paid),"Value":money(actual),"Gain":money(actual-p*paid)},
        {"Scenario":"Impact of missed installments","Installments":missed,"Invested":money(p*(months-paid)),"Value impact":money(full-actual),"Gain":"-"},
    ])

def stepup_calculator():
    st.subheader("Step-up SIP Calculator")
    c=st.columns(7)
    start=c[0].number_input("Starting SIP ₹",0.0,value=10000.0,step=1000.0)
    step_pct=c[1].number_input("Step-up % yearly",0.0,value=10.0,step=.5)
    step_amt=c[2].number_input("OR step-up amount ₹",0.0,value=0.0,step=500.0)
    r=c[3].number_input("Return % p.a.",value=12.0,step=.25,key="step_r")
    y=c[4].number_input("Years",0,value=10,key="step_y")
    m=c[5].number_input("Extra months",0,value=0,key="step_m")
    missed=c[6].number_input("Missed installments",0,value=0,key="step_missed")
    months=max(0,round(y*12+m)); paid=max(0,months-missed); mr=monthly_rate(r)
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
    corpus=c[0].number_input("Source corpus ₹",0.0,value=500000.0,step=10000.0)
    mode=c[1].selectbox("STP mode",["Fixed Amount","Percentage of Remaining Corpus","Fixed % of Original Corpus"])
    transfer=c[2].number_input("Transfer amount ₹",0.0,value=25000.0,step=1000.0)
    percent=c[3].number_input("STP percentage %",0.0,value=5.0,step=.5)/100
    freq=c[4].selectbox("Frequency",["Monthly","Weekly","Daily"])
    c2=st.columns(4)
    periods=c2[0].number_input("No. of periods",0,value=12)
    sr=c2[1].number_input("Source return % p.a.",value=6.0,step=.25)/100
    tr=c2[2].number_input("Target return % p.a.",value=12.0,step=.25)/100
    ppy={"Daily":365,"Weekly":52,"Monthly":12}[freq]
    source=corpus; target=0.0; total=sg=tg=0.0; last=0.0
    base=corpus*percent
    for i in range(1,periods+1):
        before=source; source*=((1+sr)**(1/ppy)); sg+=source-before
        if mode=="Fixed Amount": amt=transfer
        elif mode=="Percentage of Remaining Corpus": amt=source*percent
        else: amt=source if i==periods else base
        amt=min(amt,source); source-=amt; before=target+amt; target=before*((1+tr)**(1/ppy)); tg+=target-before; total+=amt; last=amt
        if source<=.5: source=0; break
    show_table([{"Metric":"Original Source Corpus","Value":money(corpus)}, {"Metric":"Total Transferred","Value":money(total)}, {"Metric":"Final Installment / Sweep","Value":money(last)}, {"Metric":"Source Growth Earned","Value":money(sg)}, {"Metric":"Target Growth Earned","Value":money(tg)}, {"Metric":"Source Balance","Value":money(source)}, {"Metric":"Target Value","Value":money(target)}, {"Metric":"Total Portfolio Value","Value":money(source+target)}])

def lumpsum_calculator():
    st.subheader("Lumpsum Calculator")
    c=st.columns(3); p=c[0].number_input("Investment ₹",0.0,value=100000.0,step=10000.0); r=c[1].number_input("Return % p.a.",value=12.0,step=.25); y=c[2].number_input("Years",0.0,value=10.0,step=.5)
    fv=p*((1+r/100)**y); st.metric("Future Value",money(fv),money(fv-p))

def swp_calculator():
    st.subheader("SWP Calculator")
    c=st.columns(4); corpus=c[0].number_input("Initial corpus ₹",0.0,value=5000000.0,step=100000.0); wd=c[1].number_input("Monthly withdrawal ₹",0.0,value=30000.0,step=1000.0); r=monthly_rate(c[2].number_input("Return % p.a.",value=8.0,step=.25)); years=c[3].number_input("Years",0,value=20)
    total=0; exhausted=None
    for month in range(1,years*12+1):
        corpus=corpus*(1+r)-wd; total+=wd
        if corpus<=0: corpus=0; exhausted=month; break
    st.metric("Total Withdrawn", money(total)); st.metric("Remaining Corpus", money(corpus));
    if exhausted: st.warning(f"Corpus exhausted after {exhausted} months.")

def goal_calculator():
    st.subheader("Goal SIP Calculator")
    c=st.columns(3); target=c[0].number_input("Target amount ₹",0.0,value=5000000.0,step=100000.0); r=monthly_rate(c[1].number_input("Return % p.a.",value=12.0,step=.25)); n=int(c[2].number_input("Years to goal",1,value=10)*12)
    sip=target/((((1+r)**n-1)/r)*(1+r)) if r else target/n
    st.metric("Required Monthly SIP", money(sip)); st.metric("Target Corpus", money(target))

def retirement_calculator():
    st.subheader("Retirement Calculator")
    c=st.columns(6); age=c[0].number_input("Current age",0,value=31); ret=c[1].number_input("Retirement age",0,value=60); life=c[2].number_input("Life expectancy",0,value=85); exp=c[3].number_input("Monthly expense today ₹",0.0,value=50000.0,step=5000.0); inf=c[4].number_input("Inflation %",value=6.0,step=.25)/100; post=c[5].number_input("Post-retirement return %",value=8.0,step=.25)/100
    y=max(0,ret-age); ry=max(0,life-ret); fut_exp=exp*((1+inf)**y); real=((1+post)/(1+inf))-1; ann=fut_exp*12; corpus=ann*ry if abs(real)<1e-6 else ann*(1-(1+real)**(-ry))/real
    st.metric("Monthly Expense at Retirement", money(fut_exp)); st.metric("Required Retirement Corpus", money(corpus)); st.metric("Years to Retirement", y)

def cagr_calculator():
    st.subheader("CAGR Calculator")
    c=st.columns(3); begin=c[0].number_input("Beginning value ₹",0.01,value=100000.0); end=c[1].number_input("Ending value ₹",0.01,value=300000.0); years=c[2].number_input("Years",0.01,value=5.0)
    st.metric("CAGR", pct(((end/begin)**(1/years)-1)*100))

def emi_calculator():
    st.subheader("EMI + Prepayment vs Mutual Fund")
    c=st.columns(4); principal=c[0].number_input("Loan outstanding ₹",0.0,value=3000000.0,step=100000.0); rate=c[1].number_input("Loan rate %",value=8.5,step=.1)/100/12; years=c[2].number_input("Remaining tenure years",1,value=20); mfret=c[3].number_input("MF return % p.a.",value=12.0,step=.25)/100
    c2=st.columns(5); extra=c2[0].number_input("Extra EMI ₹/month",0.0,value=5000.0,step=500.0); one=c2[1].number_input("One-time prepay ₹",0.0,value=0.0,step=10000.0); pre_m=c2[2].number_input("Prepay after month",1,value=1); rec=c2[3].number_input("Recurring prepay ₹",0.0,value=0.0,step=1000.0); tax=c2[4].number_input("Tax on MF gains %",0.0,value=12.5,step=.5)/100
    n=int(years*12); emi=principal*rate*(1+rate)**n/(((1+rate)**n)-1) if rate and n else 0
    def sim(prepay):
        bal=principal; month=0; interest=paid=0
        while bal>1 and month<1200:
            month+=1
            if prepay and one and month==pre_m: amt=min(one,bal); bal-=amt; paid+=amt
            if prepay and rec and month%12==0: amt=min(rec,bal); bal-=amt; paid+=amt
            intr=bal*rate; pay=min(emi+(extra if prepay else 0), bal+intr); bal-=pay-intr; interest+=intr; paid+=pay
            if bal<=1: break
        return month, interest, paid
    reg=sim(False); prep=sim(True); saved=reg[1]-prep[1]
    mfr= (1+mfret)**(1/12)-1
    fv_extra=extra*((((1+mfr)**n-1)/mfr)*(1+mfr)) if mfr else extra*n
    fv_one=one*((1+mfret)**max(0,(n-pre_m+1)/12))
    fv=fv_extra+fv_one; invested=extra*n+one; post=invested+max(0,fv-invested)*(1-tax)
    show_table([
        {"Scenario":"No prepayment","Closure time":f"{reg[0]} months","Total interest":money(reg[1]),"Total paid":money(reg[2])},
        {"Scenario":"With prepayment","Closure time":f"{prep[0]} months","Total interest":money(prep[1]),"Total paid":money(prep[2])},
        {"Scenario":"MF alternative of extra/prepay cash","Closure time":"-","Total interest":"-","Total paid":money(post)},
    ])
    st.info(f"Calculated EMI: {money(emi)} · Interest saved through prepayment: {money(saved)}")

# ---------- MF SOA parser ----------
DATE_RE = re.compile(r"\b(\d{1,2}[-/]\d{1,2}[-/]\d{2,4}|\d{1,2}[-/][A-Za-z]{3,9}[-/]\d{2,4}|\d{1,2}\s+[A-Za-z]{3,9}\s+\d{2,4})\b")
NUM_RE = re.compile(r"[-+]?\(?\d{1,3}(?:,\d{2,3})*(?:\.\d+)?\)?|[-+]?\(?\d+(?:\.\d+)?\)?")
TXN_WORDS = re.compile(r"purchase|subscription|redemption|redeem|switch|sip|stp|swp|systematic|idcw|dividend|bonus|allotment|lumpsum|reinvest|payout|stamp\s*duty|load|tax|fee|segregated|consolidation", re.I)
FINANCIAL_HINTS = re.compile(r"amount|nav|units|price|balance|transaction|date|credit|debit", re.I)
IGNORE_WORDS = re.compile(r"opening balance|closing balance|current value|market value|cost value|grand total|total current|nominee|bank account|registrar|email|mobile|address|pan\s*[:]|kyc|disclaimer|riskometer|benchmark|page\s+\d+", re.I)
SCHEME_HINT = re.compile(r"(direct|regular|growth|idcw|dividend|plan|fund|scheme|equity|debt|hybrid|liquid|overnight|index|small cap|mid cap|large cap|flexi cap|elss|balanced|arbitrage|gilt|money market|contra|value)", re.I)
AMC_HINT = re.compile(r"mutual\s+fund|asset\s+management|amc|cams|kfintech|kfin", re.I)
FOLIO_RE = re.compile(r"folio\s*(?:no\.?|number|#)?\s*[:\-]?\s*([A-Z0-9][A-Z0-9/\-]{2,})", re.I)

@dataclass
class Txn:
    page:int; source_engine:str; amc_or_registrar:str; folio:str; scheme:str; date:str; transaction:str; amount:Optional[float]; nav:Optional[float]; units:Optional[float]; balance_units:Optional[float]; raw_text:str; confidence:float

def clean_num(value):
    if value is None: return None
    s=str(value).strip().replace(',',''); neg=s.startswith('(') and s.endswith(')'); s=s.strip('()')
    try: return -float(s) if neg else float(s)
    except: return None

def normalize_date(value):
    s=' '.join(value.replace('/','-').split())
    for fmt in ["%d-%m-%Y","%d-%m-%y","%d-%b-%Y","%d-%b-%y","%d-%B-%Y","%d-%B-%y","%d %b %Y","%d %b %y","%d %B %Y","%d %B %y"]:
        try: return datetime.strptime(s,fmt).strftime('%Y-%m-%d')
        except: pass
    return value

def unlock_with_pymupdf(pdf_bytes,password):
    doc=fitz.open(stream=pdf_bytes,filetype='pdf')
    if doc.needs_pass:
        if not password: raise ValueError('This PDF is password protected. Enter the SOA/CAS password and retry.')
        if not doc.authenticate(password): raise ValueError('Wrong PDF password.')
    out=io.BytesIO(); doc.save(out,garbage=4,deflate=True); doc.close(); return out.getvalue()

def detect_context(line,ctx):
    text=' '.join(str(line).split())
    f=FOLIO_RE.search(text)
    if f: ctx['folio']=f.group(1).strip()
    if AMC_HINT.search(text) and len(text)<=140: ctx['amc_or_registrar']=text
    if SCHEME_HINT.search(text) and len(text)<=180 and not DATE_RE.search(text) and not re.search(r"statement|transaction|account|investor|address|service|summary|total|nominee|disclaimer",text,re.I): ctx['scheme']=text

def classify(raw,txn):
    t=(txn or raw).lower()
    if 'redemption' in t or 'redeem' in t or 'swp' in t: return 'Redemption / SWP'
    if 'switch' in t and 'out' in t: return 'Switch Out'
    if 'switch' in t and 'in' in t: return 'Switch In'
    if 'sip' in t or 'systematic investment' in t: return 'SIP Purchase'
    if 'stp' in t: return 'STP'
    if 'purchase' in t or 'subscription' in t or 'lumpsum' in t: return 'Purchase'
    if 'dividend' in t or 'idcw' in t: return 'IDCW / Dividend'
    if 'stamp' in t: return 'Stamp Duty'
    if 'bonus' in t: return 'Bonus'
    return txn.strip() or 'Transaction'

def infer_values(nums, raw):
    amount=nav=units=bal=None
    tail=nums[-4:]
    if len(tail)>=4: amount,nav,units,bal=tail[-4],tail[-3],tail[-2],tail[-1]
    elif len(tail)==3: amount,nav,units=tail
    elif len(tail)==2: amount,units=tail
    elif len(tail)==1: amount=tail[0]
    if re.search(r"redemption|redeem|switch\s*out|swp",raw,re.I):
        if amount and amount>0: amount=-amount
        if units and units>0: units=-units
    return amount,nav,units,bal

def parse_line(line,page,ctx,engine):
    raw=' '.join(str(line).split())
    if len(raw)<12 or IGNORE_WORDS.search(raw): return None
    dm=DATE_RE.search(raw)
    if not dm or not (TXN_WORDS.search(raw) or FINANCIAL_HINTS.search(raw)): return None
    rest=raw[dm.end():].strip(' -:|')
    nstr=NUM_RE.findall(rest); nums=[x for x in (clean_num(n) for n in nstr) if x is not None]
    if not nums and not TXN_WORDS.search(rest): return None
    first=len(rest)
    for n in nstr:
        p=rest.find(n)
        if p>=0: first=min(first,p)
    txn_text=rest[:first].strip(' -:|') or 'Transaction'
    typ=classify(raw,txn_text); amount,nav,units,bal=infer_values(nums,raw)
    conf=.4 + (.2 if TXN_WORDS.search(raw) else 0)+(.1 if amount is not None else 0)+(.1 if nav is not None else 0)+(.1 if units is not None else 0)+(.05 if ctx.get('folio') else 0)+(.05 if ctx.get('scheme') else 0)
    return Txn(page,engine,ctx.get('amc_or_registrar',''),ctx.get('folio',''),ctx.get('scheme',''),normalize_date(dm.group(1)),typ,amount,nav,units,bal,raw,round(min(conf,.98),2))

def row_to_line(row): return ' '.join(str(c).strip() for c in row if c is not None and str(c).strip() and str(c).lower()!='nan')

def extract_with_pymupdf(pdf_bytes):
    txns=[]; ctx={'amc_or_registrar':'','folio':'','scheme':''}; pages_text=0; doc=fitz.open(stream=pdf_bytes,filetype='pdf')
    for i,page in enumerate(doc,start=1):
        text=page.get_text('text') or ''
        if len(text.strip())>50: pages_text+=1
        for line in text.splitlines(): detect_context(line,ctx); t=parse_line(line,i,ctx,'PyMuPDF'); txns += [t] if t else []
        for block in page.get_text('blocks') or []:
            line=' '.join(str(block[4] if len(block)>=5 else '').split()); detect_context(line,ctx); t=parse_line(line,i,ctx,'PyMuPDF-blocks'); txns += [t] if t else []
    pages=len(doc); doc.close(); return txns, {'pages':pages,'pymupdf_pages_with_text':pages_text}

def extract_with_pdfplumber(pdf_bytes):
    txns=[]; ctx={'amc_or_registrar':'','folio':'','scheme':''}; pages_text=0; table_rows=0
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for i,page in enumerate(pdf.pages,start=1):
            text=page.extract_text(x_tolerance=1.5,y_tolerance=3) or ''
            if len(text.strip())>50: pages_text+=1
            for line in text.splitlines(): detect_context(line,ctx); t=parse_line(line,i,ctx,'pdfplumber-text'); txns += [t] if t else []
            try: tables=page.extract_tables(table_settings={'vertical_strategy':'text','horizontal_strategy':'text','snap_tolerance':3,'join_tolerance':3,'intersection_tolerance':5,'min_words_vertical':2,'min_words_horizontal':1}) or []
            except Exception: tables=[]
            for table in tables:
                for row in table:
                    table_rows+=1; line=row_to_line(row); detect_context(line,ctx); t=parse_line(line,i,ctx,'pdfplumber-table'); txns += [t] if t else []
    return txns, {'pdfplumber_pages_with_text':pages_text,'table_rows_seen':table_rows}

@st.cache_data(show_spinner=False)
def extract_transactions(pdf_bytes,password):
    unlocked=unlock_with_pymupdf(pdf_bytes,password)
    a,ma=extract_with_pymupdf(unlocked); b,mb=extract_with_pdfplumber(unlocked)
    rank={'pdfplumber-table':4,'pdfplumber-text':3,'PyMuPDF-blocks':2,'PyMuPDF':1}; unique={}
    for t in a+b:
        key=(t.page,t.folio,t.scheme,t.date,t.transaction,t.amount,t.nav,t.units,t.balance_units,t.raw_text[:100])
        if key not in unique or rank.get(t.source_engine,0)>rank.get(unique[key].source_engine,0): unique[key]=t
    rows=sorted(unique.values(), key=lambda x:(x.folio,x.scheme,x.date,x.page,x.transaction))
    meta={**ma,**mb,'transactions_found':len(rows),'engines_used':'PyMuPDF + pdfplumber + pandas','low_text_warning':ma.get('pymupdf_pages_with_text',0)==0 and mb.get('pdfplumber_pages_with_text',0)==0}
    return [asdict(r) for r in rows], meta

def make_summary(df):
    work=df.copy(); work['amount']=pd.to_numeric(work.get('amount'),errors='coerce'); work['units']=pd.to_numeric(work.get('units'),errors='coerce')
    return work.groupby(['folio','scheme'],dropna=False).agg(transactions=('date','count'), total_inflow_outflow=('amount','sum'), net_units=('units','sum'), latest_date=('date','max'), average_confidence=('confidence','mean')).reset_index()

def excel_bytes(df,summary):
    out=io.BytesIO()
    safe_df = clean_dataframe_for_excel(df)
    safe_summary = clean_dataframe_for_excel(summary)
    with pd.ExcelWriter(out,engine='openpyxl') as w:
        safe_df.to_excel(w,index=False,sheet_name='Transactions')
        safe_summary.to_excel(w,index=False,sheet_name='Summary')
        for ws in w.book.worksheets:
            ws.freeze_panes='A2'
            for col in ws.columns:
                ml=max(len(str(cell.value or '')) for cell in list(col)[:200]); ws.column_dimensions[col[0].column_letter].width=min(max(ml+2,10),55)
    return out.getvalue()

def soa_analyzer():
    st.subheader('Mutual Fund SOA Analyzer')
    st.caption('Zero-cost parser using PyMuPDF, pdfplumber, pandas and openpyxl. No Camelot, Tabula, Java or Ghostscript.')
    uploaded=st.file_uploader('Upload AMC / CAMS / KFintech / MF Central statement PDF', type=['pdf'])
    password=st.text_input('PDF password, if protected', type='password')
    if not uploaded:
        st.info('Upload a folio-based mutual fund Statement of Account PDF to start.'); return
    try:
        with st.spinner('Extracting transaction rows from PDF...'):
            rows, meta=extract_transactions(uploaded.read(), password or None)
    except Exception as e:
        st.error(str(e)); return
    c=st.columns(4); c[0].metric('Pages',meta.get('pages',0)); c[1].metric('Text pages',max(meta.get('pymupdf_pages_with_text',0),meta.get('pdfplumber_pages_with_text',0))); c[2].metric('Table rows scanned',meta.get('table_rows_seen',0)); c[3].metric('Transactions found',meta.get('transactions_found',0))
    if meta.get('low_text_warning'): st.warning('This looks like a scanned/image PDF. Upload the original AMC/CAMS/KFin generated PDF for best results.')
    if not rows: st.warning('No financial transaction rows were detected. Try a detailed transaction SOA/CAS PDF instead of a valuation-only statement.'); return
    df=pd.DataFrame(rows); df=clean_dataframe_for_excel(df); cols=['folio','scheme','date','transaction','amount','nav','units','balance_units','amc_or_registrar','page','source_engine','confidence','raw_text']; df=df[[x for x in cols if x in df.columns]+[x for x in df.columns if x not in cols]]
    st.dataframe(df,width="stretch",hide_index=True)
    summary=make_summary(df); st.subheader('Folio / Scheme Summary'); st.dataframe(summary,width="stretch",hide_index=True)
    c1,c2=st.columns(2); c1.download_button('Download CSV',df.to_csv(index=False).encode(), 'mf_soa_transactions.csv','text/csv', width="stretch"); c2.download_button('Download Excel',excel_bytes(df,summary),'mf_soa_transactions.xlsx','application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',width="stretch")
    with st.expander('Accuracy note'):
        st.write('Indian mutual fund SOA formats differ across AMCs, CAMS, KFintech and MF Central. Always reconcile exported rows with the original statement before client-facing reporting.')

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
