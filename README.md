# DKSH Stock Validator for SG & MY

This is a premium Streamlit web application designed to automate stock and status validation across multiple e-commerce marketplaces (Lazada SG, Shopee SG, TikTok MY) and reconcile them with the core **TC Inventory** and **All File** records.

## 🚀 Key Features

1. **Flexible Ingest Modes**: 
   - **Local File Upload**: Directly upload CSV/Excel files downloaded from Lazada, Shopee, and TikTok seller portals.
   - **GitHub Integration**: Fetch files dynamically from any GitHub repository (public or private) using a GitHub Personal Access Token (PAT), execute validation, and commit the status reports directly back to GitHub.
2. **Bundle SKU Logic Resolution**:
   - **Multi-SKU Bundles (`+` character)**: E.g., `SKU_A+SKU_B` will look up stock for `SKU_A` and `SKU_B` in the All File and resolve the bundle stock using the minimum quantity among the two.
   - **Multiplier Bundles (`X` character)**: E.g., `AX2` or `BX3` will find the base SKU (`A` or `B`), fetch its stock, divide it by the multiplier (`2` or `3`), and round down to the nearest integer.
3. **Lazada SKU Level Validation**: Resolves the exact action required for mismatching stock and status parameters using a complex logic tree that considers:
   - Status checks (Marketplace Status vs TC Status)
   - Stock checks (Marketplace Stock vs TC Stock)
   - Max 0 constraints (Max Quantity = 0 -> Max 0 is 'Yes')
   - Reserved stocks & Available buffers
4. **Shopee & TikTok Product ID Consolidation**:
   - Aggregates e-commerce listing stock by Product ID.
   - Compares consolidated Marketplace stocks with TC stock sums.
   - Outputs clear action indicators.

---

## 🛠️ Installation & Setup

### Prerequisites
Make sure Python 3.8 or higher is installed on your computer.

### Step 1: Install Dependencies
Open your command prompt or terminal in the project directory and run:
```bash
pip install -r requirements.txt
```

### Step 2: Run the Application
Start the Streamlit dashboard by running:
```bash
streamlit run app.py
```
This will automatically launch the app in your default web browser (typically at `http://localhost:8501`).

---

## 📂 Input File Formats & Schemas

### 1. All File (Mandatory)
Contains TC's ground truth stock data.
- **SKU Column**: `sellerSKU`
- **TC Stock Column**: `MyStock-Singapore quantity`
- **Reserved Stock Column**: `MyStock-Singapore reservedQuantity`

### 2. TC Inventory File (Mandatory)
Contains TC Item Status and Max Quantity constraints.
- **SKU Column**: `Custom SKU`
- **TC Status Column**: `Item status`
- **Max Quantity Column**: `Max Quantity` (If value is `0` $\rightarrow$ Max 0 is **Yes**; if blank/NaN $\rightarrow$ **No**)

### 3. Lazada SG File (Optional)
Marketplace product status and quantity list.
- **Header Structure**: Row 1 is treated as the column header, the next 3 rows are skipped automatically.
- **SKU Column**: `SellerSKU`
- **Stock Column**: `Quantity`
- **Status Column**: `status`

### 4. Shopee SG Files (Optional)
- **Stock File**:
  - **SKU Column**: `SKU`
  - **Product ID Column**: `Product ID`
  - **Stock Column**: `Stock`
- **Status File**: Product IDs lists. If a Product ID in the stock file is found in this status file, its Marketplace status is **Active**, otherwise **Inactive**.

### 5. TikTok MY Files (Optional)
- **Stock File**:
  - **SKU Column**: `Seller SKU`
  - **Product ID Column**: `Product ID`
  - **Stock Column**: `Quantity`
- **Active Status File**: Contains active SKUs in the column `Seller SKU`.
- **Inactive Status File**: Contains inactive SKUs in the column `Seller SKU`.

---

## 🧭 Lazada SKU Level Validation Logic Table

| Status Check (`MP == TC`) | Stock Check (`MP == TC`) | Additional Conditions | Recommended Action Required |
| :--- | :--- | :--- | :--- |
| **False** | **True** | TC Stock == 0 | **Change to inactive** |
| **False** | **True** | TC Stock > 1 & Max 0 is 'Yes' | **Change to inactive** |
| **False** | **True** | TC Stock > 1 & Max 0 is 'No' | **Change to active** |
| **True** | **False** | Max 0 is 'Yes' | **Max Already Done** |
| **True** | **False** | Max 0 is 'No' & Reserved Stock > 0 | **Reserved Done** |
| **True** | **False** | Max 0 is 'No', Reserved Stock <= 0 & Buffer > 0 | **Buffer Done** |
| **True** | **False** | Max 0 is 'No', Reserved Stock <= 0 & Buffer < 0 | **Impact/Force Stock Push** |
| **True** | **True** | - | **All Good** |

*(Buffer is computed as `TC Stock - MP Stock`)*

---

## 💻 Technical Structure

- `app.py`: Streamlit front-end entry point containing visual dashboard components, configuration tabs, interactive metrics, and direct GitHub reading/writing actions.
- `validator.py`: Business logic file containing SKU cleaning, recursive bundle stock resolvers, and marketplace-specific data validations.
- `test_validator.py`: Unit tests to verify correct stock calculations and validate boundary logic conditions.
- `requirements.txt`: Python package requirements.
