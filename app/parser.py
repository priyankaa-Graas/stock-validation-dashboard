import pandas as pd
import numpy as np
import io
import re

def normalize_sku_str(sku):
    """
    SKU Normalization Rules:
    - Convert to string
    - Remove leading/trailing spaces
    - Convert to uppercase
    - Preserve leading zeros
    - Handle numeric and string SKUs correctly
    """
    if pd.isna(sku) or sku is None:
        return ""
    
    # If float and represents integer (e.g. 12345.0), convert to integer first to avoid .0 suffix
    if isinstance(sku, float):
        if sku.is_integer():
            sku = int(sku)
        else:
            sku = str(sku)
            
    sku_str = str(sku).strip()
    return sku_str.upper()

def load_excel_or_csv(file_bytes, filename, skiprows=0):
    """
    Helper to load either Excel (.xlsx, .xls) or CSV files.
    """
    # Use io.BytesIO to read file in memory
    file_io = io.BytesIO(file_bytes)
    if filename.endswith('.csv'):
        # For CSV, read all as string to preserve leading zeros
        return pd.read_csv(file_io, dtype=str, skiprows=skiprows)
    else:
        # For Excel, read all as string to preserve leading zeros
        return pd.read_excel(file_io, dtype=str, skiprows=skiprows)

def find_column_case_insensitive(df, target_names):
    """
    Finds the exact column name in df that matches any of the target names (case-insensitive, stripped).
    """
    df_cols = [str(c).strip().lower() for c in df.columns]
    for target in target_names:
        target_clean = target.strip().lower()
        if target_clean in df_cols:
            idx = df_cols.index(target_clean)
            return df.columns[idx]
    return None

def parse_lazada(file_bytes, filename, errors_list):
    """
    Lazada SG column mapping:
    - Ignore first 4 rows (skiprows=4). Use 5th row as header.
    - SKU = SellerSKU
    - Stock = Quantity
    - Status = status
    """
    try:
        df = load_excel_or_csv(file_bytes, filename, skiprows=4)
        
        col_sku = find_column_case_insensitive(df, ["sellersku", "seller sku"])
        col_stock = find_column_case_insensitive(df, ["quantity", "stock"])
        col_status = find_column_case_insensitive(df, ["status"])
        
        missing = []
        if not col_sku: missing.append("SellerSKU")
        if not col_stock: missing.append("Quantity")
        if not col_status: missing.append("status")
        
        if missing:
            errors_list.append({
                "file": filename,
                "row": "N/A",
                "sku": "N/A",
                "error": f"Missing required columns: {', '.join(missing)}"
            })
            return pd.DataFrame()
            
        data = []
        for idx, row in df.iterrows():
            row_num = idx + 6  # 1-indexed, skipped 4 rows + header is row 5
            raw_sku = row[col_sku]
            sku = normalize_sku_str(raw_sku)
            raw_stock = row[col_stock]
            raw_status = row[col_status]
            
            # Check for blank SKU
            if not sku:
                errors_list.append({
                    "file": filename,
                    "row": row_num,
                    "sku": "BLANK",
                    "error": "Blank SKU detected"
                })
                continue
                
            # Parse stock
            try:
                stock_val = int(float(str(raw_stock).strip())) if not pd.isna(raw_stock) else 0
            except Exception:
                errors_list.append({
                    "file": filename,
                    "row": row_num,
                    "sku": sku,
                    "error": f"Invalid stock value: {raw_stock}"
                })
                stock_val = 0
                
            status_val = str(raw_status).strip()
            
            data.append({
                "sku": sku,
                "product_id": "N/A",
                "marketplace_stock": stock_val,
                "marketplace_status": status_val,
                "row_num": row_num
            })
            
        res_df = pd.DataFrame(data)
        
        # Check for duplicates in SKU
        if not res_df.empty:
            dupes = res_df[res_df.duplicated(subset=['sku'], keep=False)]
            for _, d_row in dupes.iterrows():
                errors_list.append({
                    "file": filename,
                    "row": d_row['row_num'],
                    "sku": d_row['sku'],
                    "error": "Duplicate SKU in marketplace file"
                })
                
        return res_df
    except Exception as e:
        errors_list.append({
            "file": filename,
            "row": "N/A",
            "sku": "N/A",
            "error": f"Failed to parse file: {str(e)}"
        })
        return pd.DataFrame()

def parse_shopee(stock_bytes, stock_filename, status_bytes, status_filename, errors_list):
    """
    Shopee SG column mapping:
    - Stock File: SKU = SKU, Product ID = Product ID, Stock = Stock
    - Status File: If Product ID exists, Status = Active, Else Inactive.
    """
    try:
        df_stock = load_excel_or_csv(stock_bytes, stock_filename)
        
        col_sku = find_column_case_insensitive(df_stock, ["sku", "seller sku"])
        col_pid = find_column_case_insensitive(df_stock, ["product id", "product_id", "pid"])
        col_stock = find_column_case_insensitive(df_stock, ["stock", "quantity"])
        
        missing = []
        if not col_sku: missing.append("SKU")
        if not col_pid: missing.append("Product ID")
        if not col_stock: missing.append("Stock")
        
        if missing:
            errors_list.append({
                "file": stock_filename,
                "row": "N/A",
                "sku": "N/A",
                "error": f"Missing required columns in Stock file: {', '.join(missing)}"
            })
            return pd.DataFrame()
            
        # Parse Status File
        active_pids = set()
        if status_bytes:
            try:
                df_status = load_excel_or_csv(status_bytes, status_filename)
                col_status_pid = find_column_case_insensitive(df_status, ["product id", "product_id", "pid"])
                
                # Check status column. Wait, some status files have status="Active" explicitly, 
                # but the rule says: "If Product ID exists (in Status File), Status = Active. Else Status = Inactive."
                # So we simply read all Product IDs in the Status File and add them to active_pids!
                if col_status_pid:
                    for _, row in df_status.iterrows():
                        pid_val = str(row[col_status_pid]).strip()
                        if pid_val and not pd.isna(row[col_status_pid]):
                            active_pids.add(pid_val)
                else:
                    errors_list.append({
                        "file": status_filename,
                        "row": "N/A",
                        "sku": "N/A",
                        "error": "Missing 'Product ID' column in Shopee Status File. Assuming all inactive."
                    })
            except Exception as e:
                errors_list.append({
                    "file": status_filename,
                    "row": "N/A",
                    "sku": "N/A",
                    "error": f"Failed to parse Shopee Status File: {str(e)}"
                })
        
        data = []
        for idx, row in df_stock.iterrows():
            row_num = idx + 2  # 1-indexed + header row
            raw_sku = row[col_sku]
            sku = normalize_sku_str(raw_sku)
            raw_pid = row[col_pid]
            pid = str(raw_pid).strip() if not pd.isna(raw_pid) else ""
            raw_stock = row[col_stock]
            
            # Check for blank SKU or PID
            if not sku:
                errors_list.append({
                    "file": stock_filename,
                    "row": row_num,
                    "sku": "BLANK",
                    "error": "Blank SKU detected"
                })
                continue
                
            if not pid:
                errors_list.append({
                    "file": stock_filename,
                    "row": row_num,
                    "sku": sku,
                    "error": "Blank Product ID detected"
                })
                
            # Parse stock
            try:
                stock_val = int(float(str(raw_stock).strip())) if not pd.isna(raw_stock) else 0
            except Exception:
                errors_list.append({
                    "file": stock_filename,
                    "row": row_num,
                    "sku": sku,
                    "error": f"Invalid stock value: {raw_stock}"
                })
                stock_val = 0
                
            # Status check: If Product ID exists in active_pids (from status file)
            status_val = "Active" if pid in active_pids else "Inactive"
            
            data.append({
                "sku": sku,
                "product_id": pid,
                "marketplace_stock": stock_val,
                "marketplace_status": status_val,
                "row_num": row_num
            })
            
        res_df = pd.DataFrame(data)
        
        # Check duplicates
        if not res_df.empty:
            dupes = res_df[res_df.duplicated(subset=['sku'], keep=False)]
            for _, d_row in dupes.iterrows():
                errors_list.append({
                    "file": stock_filename,
                    "row": d_row['row_num'],
                    "sku": d_row['sku'],
                    "error": "Duplicate SKU in Shopee stock file"
                })
                
            dupe_pids = res_df[res_df.duplicated(subset=['product_id', 'sku'], keep=False)]
            # Duplicate Product ID checks can also be captured if needed, but standard is duplicate SKU.
            
        return res_df
    except Exception as e:
        errors_list.append({
            "file": stock_filename,
            "row": "N/A",
            "sku": "N/A",
            "error": f"Failed to parse Shopee Stock file: {str(e)}"
        })
        return pd.DataFrame()

def parse_tiktok(stock_bytes, stock_filename, active_bytes, active_filename, inactive_bytes, inactive_filename, errors_list):
    """
    TikTok Malaysia column mapping:
    - Stock File: SKU = Seller SKU, Product ID = Product ID, Stock = Quantity
    - Active File: Seller SKU. If SKU exists in Active file, Status = Active.
    - Inactive File: Seller SKU. If SKU exists in Inactive file, Status = Inactive.
    """
    try:
        df_stock = load_excel_or_csv(stock_bytes, stock_filename)
        
        col_sku = find_column_case_insensitive(df_stock, ["seller sku", "sku", "sellersku"])
        col_pid = find_column_case_insensitive(df_stock, ["product id", "product_id", "pid"])
        col_stock = find_column_case_insensitive(df_stock, ["quantity", "stock"])
        
        missing = []
        if not col_sku: missing.append("Seller SKU")
        if not col_pid: missing.append("Product ID")
        if not col_stock: missing.append("Quantity")
        
        if missing:
            errors_list.append({
                "file": stock_filename,
                "row": "N/A",
                "sku": "N/A",
                "error": f"Missing required columns in Stock file: {', '.join(missing)}"
            })
            return pd.DataFrame()
            
        # Parse Active File
        active_skus = set()
        if active_bytes:
            try:
                df_active = load_excel_or_csv(active_bytes, active_filename)
                col_act_sku = find_column_case_insensitive(df_active, ["seller sku", "sku", "sellersku"])
                if col_act_sku:
                    for _, row in df_active.iterrows():
                        sku_val = normalize_sku_str(row[col_act_sku])
                        if sku_val:
                            active_skus.add(sku_val)
                else:
                    errors_list.append({
                        "file": active_filename,
                        "row": "N/A",
                        "sku": "N/A",
                        "error": "Missing 'Seller SKU' column in TikTok Active status file."
                    })
            except Exception as e:
                errors_list.append({
                    "file": active_filename,
                    "row": "N/A",
                    "sku": "N/A",
                    "error": f"Failed to parse TikTok Active file: {str(e)}"
                })
                
        # Parse Inactive File
        inactive_skus = set()
        if inactive_bytes:
            try:
                df_inactive = load_excel_or_csv(inactive_bytes, inactive_filename)
                col_inact_sku = find_column_case_insensitive(df_inactive, ["seller sku", "sku", "sellersku"])
                if col_inact_sku:
                    for _, row in df_inactive.iterrows():
                        sku_val = normalize_sku_str(row[col_inact_sku])
                        if sku_val:
                            inactive_skus.add(sku_val)
                else:
                    errors_list.append({
                        "file": inactive_filename,
                        "row": "N/A",
                        "sku": "N/A",
                        "error": "Missing 'Seller SKU' column in TikTok Inactive status file."
                    })
            except Exception as e:
                errors_list.append({
                    "file": inactive_filename,
                    "row": "N/A",
                    "sku": "N/A",
                    "error": f"Failed to parse TikTok Inactive file: {str(e)}"
                })
                
        data = []
        for idx, row in df_stock.iterrows():
            row_num = idx + 2
            raw_sku = row[col_sku]
            sku = normalize_sku_str(raw_sku)
            raw_pid = row[col_pid]
            pid = str(raw_pid).strip() if not pd.isna(raw_pid) else ""
            raw_stock = row[col_stock]
            
            if not sku:
                errors_list.append({
                    "file": stock_filename,
                    "row": row_num,
                    "sku": "BLANK",
                    "error": "Blank SKU detected"
                })
                continue
                
            if not pid:
                errors_list.append({
                    "file": stock_filename,
                    "row": row_num,
                    "sku": sku,
                    "error": "Blank Product ID detected"
                })
                
            try:
                stock_val = int(float(str(raw_stock).strip())) if not pd.isna(raw_stock) else 0
            except Exception:
                errors_list.append({
                    "file": stock_filename,
                    "row": row_num,
                    "sku": sku,
                    "error": f"Invalid stock value: {raw_stock}"
                })
                stock_val = 0
                
            # Status resolution
            status_val = "Inactive"
            if sku in active_skus:
                status_val = "Active"
            elif sku in inactive_skus:
                status_val = "Inactive"
            else:
                # Default to Inactive, but add warning / info log
                status_val = "Inactive"
                
            data.append({
                "sku": sku,
                "product_id": pid,
                "marketplace_stock": stock_val,
                "marketplace_status": status_val,
                "row_num": row_num
            })
            
        res_df = pd.DataFrame(data)
        
        # Check duplicates
        if not res_df.empty:
            dupes = res_df[res_df.duplicated(subset=['sku'], keep=False)]
            for _, d_row in dupes.iterrows():
                errors_list.append({
                    "file": stock_filename,
                    "row": d_row['row_num'],
                    "sku": d_row['sku'],
                    "error": "Duplicate SKU in TikTok stock file"
                })
                
        return res_df
    except Exception as e:
        errors_list.append({
            "file": stock_filename,
            "row": "N/A",
            "sku": "N/A",
            "error": f"Failed to parse TikTok stock file: {str(e)}"
        })
        return pd.DataFrame()

def parse_tc_inventory(file_bytes, filename, errors_list):
    """
    TC Inventory column mapping:
    - SKU = Custom SKU
    - TC Status = Item status
    - Max Quantity: If equal to 0 -> Max = Yes, if blank/NaN -> Max = No. 
      Any other values will default to Max = No.
    """
    try:
        df = load_excel_or_csv(file_bytes, filename)
        
        col_sku = find_column_case_insensitive(df, ["custom sku", "sku", "sellersku"])
        col_status = find_column_case_insensitive(df, ["item status", "status"])
        col_max_qty = find_column_case_insensitive(df, ["max quantity", "max_quantity"])
        
        missing = []
        if not col_sku: missing.append("Custom SKU")
        if not col_status: missing.append("Item status")
        if not col_max_qty: missing.append("Max Quantity")
        
        if missing:
            errors_list.append({
                "file": filename,
                "row": "N/A",
                "sku": "N/A",
                "error": f"Missing required columns in TC Inventory: {', '.join(missing)}"
            })
            return pd.DataFrame()
            
        data = []
        for idx, row in df.iterrows():
            row_num = idx + 2
            raw_sku = row[col_sku]
            sku = normalize_sku_str(raw_sku)
            raw_status = row[col_status]
            raw_max_qty = row[col_max_qty]
            
            if not sku:
                errors_list.append({
                    "file": filename,
                    "row": row_num,
                    "sku": "BLANK",
                    "error": "Blank SKU in TC Inventory file"
                })
                continue
                
            # Max logic
            # "If Max Quantity equals 0 -> Max = Yes. If blank -> Max = No."
            max_val = "No"
            if pd.isna(raw_max_qty) or str(raw_max_qty).strip() == "":
                max_val = "No"
            else:
                try:
                    val_float = float(str(raw_max_qty).strip())
                    if val_float == 0.0:
                        max_val = "Yes"
                    else:
                        max_val = "No"
                except Exception:
                    max_val = "No"
                    
            status_val = str(raw_status).strip()
            
            data.append({
                "sku": sku,
                "tc_status": status_val,
                "max": max_val,
                "row_num": row_num
            })
            
        res_df = pd.DataFrame(data)
        
        # Check duplicates
        if not res_df.empty:
            dupes = res_df[res_df.duplicated(subset=['sku'], keep=False)]
            for _, d_row in dupes.iterrows():
                errors_list.append({
                    "file": filename,
                    "row": d_row['row_num'],
                    "sku": d_row['sku'],
                    "error": "Duplicate SKU in TC Inventory file"
                })
                
        return res_df
    except Exception as e:
        errors_list.append({
            "file": filename,
            "row": "N/A",
            "sku": "N/A",
            "error": f"Failed to parse TC Inventory file: {str(e)}"
        })
        return pd.DataFrame()

def parse_all_file(file_bytes, filename, country, errors_list):
    """
    All File column mapping:
    - SKU = SellerSKU
    - TC Stock = MyStock-{Country} quantity
    - Reserved Stock = MyStock-{Country} reservedQuantity
    """
    try:
        df = load_excel_or_csv(file_bytes, filename)
        
        col_sku = find_column_case_insensitive(df, ["sellersku", "seller sku", "sku"])
        
        # Target country-specific columns
        country_clean = country.strip().capitalize() # e.g. Singapore or Malaysia
        
        # Look for headers containing the country and keywords
        col_stock = None
        col_reserved = None
        
        # Compile patterns
        stock_patterns = [
            f"mystock-{country_clean.lower()} quantity",
            f"mystock-{country_clean.lower()}_quantity",
            "mystock-.* quantity",
            "mystock-.*_quantity",
            "quantity",
            "stock"
        ]
        
        reserved_patterns = [
            f"mystock-{country_clean.lower()} reservedquantity",
            f"mystock-{country_clean.lower()}_reservedquantity",
            "mystock-.* reservedquantity",
            "mystock-.*_reservedquantity",
            "reservedquantity",
            "reserved stock"
        ]
        
        # Direct check first
        col_stock = find_column_case_insensitive(df, [f"MyStock-{country_clean} quantity", "sellersku_quantity"])
        col_reserved = find_column_case_insensitive(df, [f"MyStock-{country_clean} reservedQuantity", "sellersku_reserved"])
        
        # Regex check if not found
        if not col_stock or not col_reserved:
            for col in df.columns:
                col_str = str(col).strip().lower()
                if not col_stock:
                    if f"mystock-{country_clean.lower()}" in col_str and "quantity" in col_str:
                        col_stock = col
                    elif "mystock-" in col_str and "quantity" in col_str:
                        col_stock = col
                if not col_reserved:
                    if f"mystock-{country_clean.lower()}" in col_str and "reserved" in col_str:
                        col_reserved = col
                    elif "mystock-" in col_str and "reserved" in col_str:
                        col_reserved = col
                        
        # Fallbacks
        if not col_stock:
            col_stock = find_column_case_insensitive(df, ["mystock quantity", "quantity", "stock"])
        if not col_reserved:
            col_reserved = find_column_case_insensitive(df, ["mystock reservedquantity", "reserved quantity", "reserved"])
            
        missing = []
        if not col_sku: missing.append("SellerSKU")
        if not col_stock: missing.append(f"MyStock-{country_clean} quantity")
        if not col_reserved: missing.append(f"MyStock-{country_clean} reservedQuantity")
        
        if missing:
            errors_list.append({
                "file": filename,
                "row": "N/A",
                "sku": "N/A",
                "error": f"Missing required columns in All File: {', '.join(missing)}"
            })
            return pd.DataFrame()
            
        data = []
        for idx, row in df.iterrows():
            row_num = idx + 2
            raw_sku = row[col_sku]
            sku = normalize_sku_str(raw_sku)
            raw_stock = row[col_stock]
            raw_reserved = row[col_reserved]
            
            if not sku:
                errors_list.append({
                    "file": filename,
                    "row": row_num,
                    "sku": "BLANK",
                    "error": "Blank SKU in All File"
                })
                continue
                
            try:
                stock_val = int(float(str(raw_stock).strip())) if not pd.isna(raw_stock) else 0
            except Exception:
                errors_list.append({
                    "file": filename,
                    "row": row_num,
                    "sku": sku,
                    "error": f"Invalid stock value in All File: {raw_stock}"
                })
                stock_val = 0
                
            try:
                reserved_val = int(float(str(raw_reserved).strip())) if not pd.isna(raw_reserved) else 0
            except Exception:
                errors_list.append({
                    "file": filename,
                    "row": row_num,
                    "sku": sku,
                    "error": f"Invalid reserved stock value in All File: {raw_reserved}"
                })
                reserved_val = 0
                
            data.append({
                "sku": sku,
                "tc_stock": stock_val,
                "reserved_stock": reserved_val,
                "row_num": row_num
            })
            
        res_df = pd.DataFrame(data)
        
        # Check duplicates
        if not res_df.empty:
            dupes = res_df[res_df.duplicated(subset=['sku'], keep=False)]
            for _, d_row in dupes.iterrows():
                errors_list.append({
                    "file": filename,
                    "row": d_row['row_num'],
                    "sku": d_row['sku'],
                    "error": "Duplicate SKU in All File"
                })
                
        return res_df
    except Exception as e:
        errors_list.append({
            "file": filename,
            "row": "N/A",
            "sku": "N/A",
            "error": f"Failed to parse All File: {str(e)}"
        })
        return pd.DataFrame()
