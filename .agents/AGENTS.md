# Maple Bookkeeping System Properties & Rules

This project-scoped configuration defines the core behavior, formatting rules, and safety constraints for the **🍁 Maple Ledger AI / Canadian Accounting System** project. Any agent working on this codebase must adhere to these guidelines.

---

## 1. Safety and Classification Protection
* **Protect Manual Classifications**: Keyword rules created manually, imported in batch, or automatically matched must **ONLY** target transactions in the Suspense account (category is null, `"Suspense Expense"`, or `"Suspense Revenue"`).
* **Never Overwrite**: Manual classifications made by the user in the transaction grid must be protected and never altered by rules or AI runs under any circumstances.
* **Auto-Apply on Save**: Saving a new rule or batch-importing rules must automatically trigger matching against active suspense transactions immediately, saving the user from having to run bulk matching manually.

---

## 2. Totals and Net Balance Columns
* **General Ledger Summary Rows**: The bottom of General Ledger tables and their exports (Excel and PDF) must include:
  1. a **`TOTAL`** row summing withdrawals, deposits, GST, and ITCs.
  2. a **`NET BALANCE`** row calculating overall Deposits minus Withdrawals.
* **Transactions by Category Grand Totals**: 
  1. UI dashboard must present `Grand Total Withdrawals`, `Grand Total Deposits`, `Grand Net Balance` (Deposits minus Withdrawals), and `Grand Total GST` metrics cards.
  2. Export reports must append both a **`GRAND TOTAL`** and **`GRAND NET BALANCE`** summary row at the very bottom.
* **Running Balance Ledger**: The Reconciliation tab exports must include the running balance column.

---

## 3. Google Sheets Consolidated Export
* **Consolidated Master Document**: Exports to Google Sheets must use a single master spreadsheet (customizable in the UI) to avoid cluttering the user's Google Drive.
* **Multi-Tab Layout**: Individual exports must be written to client/bank-specific tabs (worksheets) within that single master sheet:
  * General Ledger export tab: `[Client Name] - Ledger`
  * Transactions Grouped by Category tab: `[Client Name] - Category`
  * Reconciliation Running Balance tab: `[Account Name] - Running`
* **Service Account Authentication**: Connections must authenticate using the `google_credentials.json` key located in the project root.
* **User-Initiated Share & Ownership**: Because Service Accounts have a 0-byte default quota, sheets must be created manually in the user's personal Drive first and shared with the service account email as an **Editor** to avoid Drive storage quota blockages.

---

## 4. UI Customizations
* **Editable Financial setups**: The list of Linked Financial Ledger Accounts under Client Management is interactive (`st.data_editor`), permitting direct on-screen editing of bank details and types.
