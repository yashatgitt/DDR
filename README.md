# DDR Generator - Complete Guide

---

## 📋 Quick Start

### Prerequisites
- Python 3.8+
- Google Gemini API key (FREE - no billing required)

### Setup (5 Minutes)

#### 1. Get API Key
- Go to: https://aistudio.google.com/app/apikey
- Click "Create API Key" and copy it

#### 2. Create .env File
```env
GEMINI_API_KEY=AIzaSy_YOUR_KEY_HERE
API_TIMEOUT=120
REPORT_GEN_TIMEOUT=180
REPORT_TIMEOUT=300
PDF_CHUNK_SIZE=4000
LOG_LEVEL=INFO
```

#### 3. Run Application
```powershell
cd "project location"
.\.venv\Scripts\python.exe main.py
```

---

## 🎯 How to Use

### Simple 3-Step Process

1. **Select Inspection PDF**
   - Click browse button
   - Choose inspection report PDF

2. **Select Thermal PDF**
   - Click browse button
   - Choose thermal report PDF

3. **Click Generate Report**
   - System processes automatically (2-3 minutes)
   - DDR PDF is generated and saved locally

### Process Flow
```
USER SELECTS PDFs
        |
        v
   EXTRACT TEXT
   (from both PDFs)
        |
        v
   SPLIT INTO CHUNKS
   (for AI processing)
        |
        v
   SEND TO GEMINI AI
   (extract findings)
        |
        v
   MERGE FINDINGS
   (combine both reports)
        |
        v
   GENERATE DDR REPORT
   (AI writes analysis)
        |
        v
   CREATE PDF & SAVE
        |
        v
   DONE! Open report
```

---

## 📁 Project Structure

```
assinment/
├── main.py                 # GUI application (Tkinter)
├── processor.py            # PDF extraction & data processing
├── llm_utils.py            # AI integration (Google Gemini)
├── .env                    # Configuration file
├── final.md                # This file
└── output/                 # Generated DDR reports
```

### Key Components

**main.py**
- Tkinter GUI interface
- File selection
- Progress display
- Stop/Cancel functionality

**processor.py**
- PDF text extraction (PyMuPDF)
- Text chunking for API limits
- Data merging from both PDFs
- PDF report generation (ReportLab)

**llm_utils.py**
- Google Gemini API integration
- Structured data extraction
- DDR report generation
- JSON validation & fixing

---

## 📊 What the Output Contains

### Generated DDR Report Includes:

1. **Property Issue Summary** - Overall assessment
2. **Area-Wise Observations** - Findings by location
3. **Probable Root Cause** - Analysis of causes
4. **Severity Assessment** - High/Moderate/Low ratings
5. **Recommended Actions** - Next steps
6. **Missing Information** - Data gaps noted

---


## 🚀 Workflow Timeout Settings

```
Total Workflow: 300 seconds (5 minutes)
├─ Extract PDFs: ~15 seconds
├─ Process Text: ~5 seconds  
├─ AI Analysis: ~45 seconds
├─ Merge Data: ~5 seconds
├─ Generate DDR: ~30 seconds
└─ Create PDF: ~10 seconds
```

If workflow exceeds 300 seconds, it auto-stops and shows error.

---

## 📝 File Requirements

### Inspection PDF
- Must be readable PDF (not scanned image)
- Contains text about property inspection findings
- Max size: 100MB

### Thermal PDF
- Must be readable PDF (not scanned image)
- Contains thermal analysis/readings
- Max size: 100MB

---

## 🔑 Key Features

✅ Automatic PDF text extraction

✅ AI-powered finding analysis (Google Gemini)

✅ Intelligent data merging from dual sources

✅ Professional PDF report generation

✅ Real-time progress display

✅ Emergency stop functionality

✅ Built-in timeout protection

✅ Auto JSON error fixing

✅ Conflict detection

✅ Missing data identification

---

## 🎬 Typical Workflow Example

```
User Opens App
    ↓
Select "inspection_report.pdf"
    ↓
Select "thermal_scan.pdf"
    ↓
Click "Generate Report"
    ↓
[Processing... 2-3 minutes]
Selected Files:
  - Inspection: C:\Reports\inspection.pdf [✓]
  - Thermal: C:\Reports\thermal.pdf [✓]

Progress:
  Extract PDFs ...................... [✓]
  Process Text ...................... [✓]
  AI Analysis ....................... [✓]
  Merge Findings .................... [✓]
  Generate Report ................... [✓]
  Create PDF ........................ [✓]
    ↓
Success! Report saved
```

---



DDR Generator v1.0 
