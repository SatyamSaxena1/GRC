# Evidence Upload Details - External User

## 🔴 Upload Event

| Property | Value |
|----------|-------|
| **Time** | 2026-09-09 13:30:49 IST |
| **Document Type** | 📄 POLICY |
| **Original Filename** | `PCI-Attestation-2023-03-29T06-16-07.pdf` |
| **File Size** | 89,892 bytes (~90 KB) |
| **MIME Type** | application/pdf |
| **Evidence ID** | `99548815-7e21-4244-a21a-548cabaa37cc` |
| **SHA256** | `726bdb322d7a7b3041e88a69655bcd453821e40b0ec4796ee4869c0653d77243` |
| **Uploader** | Same external user (IP: `2401:4900:1c83:66d4:6949:d793:e9d:1c11`) |
| **Organization** | `80052888-d6a6-4bf9-a1cb-37f9ddddeded` |

---

## 📊 Processing Results

### Status: **READY** ✓
- Document was successfully uploaded
- Processing completed without errors
- Ready for evaluation against frameworks

### Quality Assessment: **0.0 / 5.0** ❌

The document received a FAILING quality score on all dimensions:

| Dimension | Score | Reason |
|-----------|-------|--------|
| **Completeness** | 0/5 | 0 of 10 expected attributes found (missing dates, approver info) |
| **Freshness** | 0/5 | No issue/expiry date found - currency cannot be established |
| **Authenticity** | 0/5 | No approver identified, no approval date, no signature |
| **Scope Coverage** | 0/5 | Document does not state what it covers |
| **Legibility** | 0/5 | **NO TEXT could be extracted from the document** ⚠️ |
| **Corroboration** | 0/5 | Nothing was extracted, so nothing is corroborated |

**Key Finding:** The PDF is unreadable/corrupted or scanned without OCR. The system could not extract any text from it.

---

## 🔍 Extracted Attributes

**All attributes came back NULL/EMPTY:**

```
- approval_date          → null
- approver_role          → null
- effective_date         → null
- systems_covered        → null
- password_min_length    → null
- mfa_required_for       → null
- access_review_frequency_days → null
- encryption_at_rest     → null
- encryption_in_transit  → null
- log_retention_days     → null
```

**Extraction Method:** `none` (because no text could be read)

---

## ⚠️ Control Evaluation Results

The document was evaluated against **CIS-CONTROLS** framework and **FAILED** on all requirements.

### Framework: CIS-CONTROLS

**Clause 3.10-3.11** (Data Protection)
- **Verdict:** ❌ FAIL
- **Gaps Created:** 2
  1. Missing `encryption_at_rest` - Document doesn't state it
  2. Missing `encryption_in_transit` - Document doesn't state it

**Clause 5.1** (Identity Management)
- **Verdict:** ❌ FAIL  
- **Gaps Created:** 3
  1. Missing `approval_date` - Document doesn't state it
  2. Missing `approver_role` - Document doesn't state it
  3. Missing `effective_date` - Document doesn't state it

**Mapped UCO (Unified Compliance Objectives):**
- `UCO-DATA-001` (Data protection)
- `UCO-IAM-001` (Identity & access)
- `UCO-IAM-002` (Access management)

### Total Impact
- **Frameworks Evaluated:** 1 (CIS-CONTROLS)
- **Requirements Checked:** 2
- **Controls Failed:** 2 / 2 (100% failure rate)
- **Gaps Created:** 5 open gaps
- **Auditor Verdicts:** None yet (no review)
- **Locked:** No (not finalized)

---

## 📈 What Happened Next

After uploading, the external user **immediately polled the evidence processing:**

1. ✓ **13:30:49** - Checked `/attributes` - saw all nulls
2. ✓ **13:30:49** - Checked `/status` - confirmed READY
3. ✓ **13:30:49** - Checked `/events` - watched real-time extraction
4. ✓ **13:30:49** - Checked `/history` - saw the processing timeline
5. ✓ **13:30:49** - Checked `/versions` - version 1 was active
6. ✓ **13:30:49** - Checked full `/evidence` detail - all the data
7. ✓ **13:30:51** - Polled `/status` again - checking if complete
8. ✓ **13:30:53** - Polled `/status` again - checking if complete
9. ✓ **13:30:53** - Checked `/attributes` - still all nulls
10. ✓ **13:30:53** - Checked `/history` - timeline still same

**Pattern:** They uploaded a document, then WATCHED it process in real-time, polling to see the extraction results as they came in.

---

## 🤔 Why Did It Fail?

### Likely Reasons:

1. **PDF is Scanned/Image-Based** 
   - The original filename suggests it's a PCI audit attestation report
   - Many attestation reports are scanned PDFs (printer → PDF)
   - System couldn't extract text from images

2. **No OCR Applied**
   - The system tried text extraction and got nothing
   - Would need PyMuPDF + OCR enabled to handle scanned PDFs
   - Current extraction method likely only handles born-digital PDFs

3. **Empty or Corrupted PDF**
   - Less likely but possible - PDF file is 90 KB which is normal size
   - But the system got zero bytes of text

### What They Were Testing:

They were likely testing:
- ✓ Can I upload a PDF successfully? → YES
- ✓ Does the system extract attributes? → YES, tries to
- ✓ Does the system evaluate against frameworks? → YES
- ✓ Does the system create gaps? → YES
- ✓ Can I watch it process in real-time? → YES
- ✓ Can I see the extraction results? → YES (but empty)

**This is a realistic test case** - testing with an actual scanned PCI attestation that needs OCR.

---

## 📍 Storage Location

The PDF is stored at:
```
file://D:\GRC\evidence_storage\tenant\80052888-d6a6-4bf9-a1cb-37f9ddddeded\evidence\99548815-7e21-4244-a21a-548cabaa37cc\v1\PCI-Attestation-2023-03-29T06-16-07.pdf
```

File is accessible and immutable (once uploaded).

---

## 🎯 Summary

| Question | Answer |
|----------|--------|
| Did they upload anything? | **YES** - 1 POLICY document |
| Was it successful? | **YES** - Processing completed (202 Accepted) |
| Was the document readable? | **NO** - Zero text extracted (likely scanned PDF) |
| Did it pass compliance check? | **NO** - Failed all CIS-CONTROLS requirements |
| How many gaps were created? | **5 open gaps** needing remediation |
| Did they monitor it? | **YES** - Polled 10+ times while processing |
| Intent? | **QA Testing** - Testing upload + real-time processing |

