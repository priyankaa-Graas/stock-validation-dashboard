import pandas as pd
import numpy as np
import re

def clean_sku(val):
    """
    Cleans SKU string by stripping whitespace and removing trailing .0 from Excel float representations.
    """
    if pd.isna(val):
        return ""
    s = str(val).strip()
    if s.endswith(".0"):
        s = s[:-2]
    return s

def clean_pid(val):
    """
    Cleans Product ID by stripping whitespace and removing trailing .0.
    """
    if pd.isna(val):
        return ""
    s = str(val).strip()
    if s.endswith(".0"):
        s = s[:-2]
    return s

def normalize_status(val):
    """
    Normalizes status values to 'Active' or 'Inactive'.
    """
    if pd.isna(val):
        return "Inactive"
    s = str(val).strip().lower()
    if s in ['active', 'act', 'y', 'yes', '1', 'true', 'item_status_active']:
        return "Active"
    return "Inactive"

class StockResolver:
    """
    Resolves TC Stock and Reserved Stock for single and bundle SKUs based on the All File.
    Handles '+' bundles and 'X' bundles (e.g. AX2, AX3) recursively.
    """
    def __init__(self, all_df):
        self.stock_map = {}
        self.reserved_map = {}
        
        if all_df is not None and not all_df.empty:
            for _, row in all_df.iterrows():
                sku = clean_sku(row.get('sellerSKU'))
                if sku:
                    tc_stock = pd.to_numeric(row.get('TC Stock'), errors='coerce')
                    reserved = pd.to_numeric(row.get('Reserved Stock'), errors='coerce')
                    self.stock_map[sku] = 0 if pd.isna(tc_stock) else int(tc_stock)
                    self.reserved_map[sku] = 0 if pd.isna(reserved) else int(reserved)

    def get_tc_stock(self, sku):
        sku = clean_sku(sku)
        if not sku:
            return 0
        
        # Check if it is a "+" bundle (e.g., A+B)
        if '+' in sku:
            parts = [clean_sku(p) for p in sku.split('+') if clean_sku(p)]
            if not parts:
                return 0
            # Get TC Stock for each individual SKU in the bundle
            stocks = [self.get_tc_stock(p) for p in parts]
            # Use the lowest stock among them
            return min(stocks) if stocks else 0
        
        # Check if it is a "X" bundle (e.g., AX2, AX3)
        # Regex matching X followed by digits at the end of the string
        match = re.search(r'^(.*)[xX](\d+)$', sku)
        if match:
            base_sku = clean_sku(match.group(1))
            multiplier = int(match.group(2))
            if multiplier > 0:
                base_stock = self.get_tc_stock(base_sku)
                return base_stock // multiplier
            
        return self.stock_map.get(sku, 0)

    def get_reserved_stock(self, sku):
        sku = clean_sku(sku)
        if not sku:
            return 0
        
        # If explicitly found in the map, return it
        if sku in self.reserved_map:
            return self.reserved_map[sku]
            
        if '+' in sku:
            parts = [clean_sku(p) for p in sku.split('+') if clean_sku(p)]
            return sum(self.get_reserved_stock(p) for p in parts)
            
        match = re.search(r'^(.*)[xX](\d+)$', sku)
        if match:
            base_sku = clean_sku(match.group(1))
            multiplier = int(match.group(2))
            if multiplier > 0:
                return self.get_reserved_stock(base_sku) // multiplier
                
        return 0

def evaluate_sku_logic(mp_status, tc_status, mp_stock, tc_stock, reserved_stock, max_0):
    """
    Evaluates stock and status validation rules for a single SKU.
    Returns: (status_check_bool, stock_check_bool, action_message)
    """
    # Normalize inputs
    norm_mp_status = normalize_status(mp_status)
    norm_tc_status = normalize_status(tc_status)
    
    # Cast to int
    try:
        mp_stock_val = int(float(mp_stock))
    except (ValueError, TypeError):
        mp_stock_val = 0
        
    try:
        tc_stock_val = int(float(tc_stock))
    except (ValueError, TypeError):
        tc_stock_val = 0
        
    try:
        res_stock_val = int(float(reserved_stock))
    except (ValueError, TypeError):
        res_stock_val = 0
        
    # Check max 0 format
    max_0_val = str(max_0).strip().title() # 'Yes' or 'No'
    if max_0_val not in ['Yes', 'No']:
        max_0_val = 'No'

    status_check = (norm_mp_status == norm_tc_status)
    stock_check = (mp_stock_val == tc_stock_val)
    
    action = "Manual review required"
    
    if not status_check and stock_check:
        if tc_stock_val == 0:
            action = "Change to inactive"
        elif tc_stock_val > 1:
            if max_0_val == 'Yes':
                action = "Change to inactive"
            else:
                action = "Change to active"
        elif tc_stock_val == 1:
            if max_0_val == 'Yes':
                action = "Change to inactive"
            else:
                action = "Change to active"
                
    elif status_check and not stock_check:
        if max_0_val == 'Yes':
            action = "Max Already Done"
        else:
            if res_stock_val > 0:
                action = "Reserved Done"
            else:
                buffer = tc_stock_val - mp_stock_val
                if buffer > 0:
                    action = "Buffer Done"
                elif buffer < 0:
                    action = "Impact/Force Stock Push"
                else:
                    action = "All Good"
                    
    elif status_check and stock_check:
        action = "All Good"
        
    return status_check, stock_check, action

def validate_lazada(lazada_df, tc_inv_df, all_df):
    """
    Validates Lazada SG/MY/TH data at the SKU level.
    """
    resolver = StockResolver(all_df)
    
    tc_inv_lookup = {}
    if tc_inv_df is not None and not tc_inv_df.empty:
        for _, row in tc_inv_df.iterrows():
            sku = clean_sku(row.get('Custom SKU'))
            if sku:
                tc_status = normalize_status(row.get('Item status'))
                max_qty_val = row.get('Max Quantity')
                
                if pd.isna(max_qty_val) or str(max_qty_val).strip() == '':
                    max_0 = 'No'
                else:
                    try:
                        max_qty = float(max_qty_val)
                        max_0 = 'Yes' if max_qty == 0 else 'No'
                    except ValueError:
                        max_0 = 'No'
                        
                tc_inv_lookup[sku] = {
                    'tc_status': tc_status,
                    'max_0': max_0
                }
                
    results = []
    for _, row in lazada_df.iterrows():
        sku = clean_sku(row.get('SellerSKU'))
        if not sku:
            # Try lowercase key fallback
            sku = clean_sku(row.get('sellersku'))
            if not sku:
                # Try generic SKU fallback
                sku = clean_sku(row.get('SKU'))
                if not sku:
                    continue
            
        mp_stock = row.get('Quantity', 0)
        # Try generic stock fallback if Quantity doesn't exist
        if 'Quantity' not in row and 'Quantity' not in lazada_df.columns:
            for col in row.index:
                if 'qty' in str(col).lower() or 'stock' in str(col).lower() or 'quantity' in str(col).lower():
                    mp_stock = row[col]
                    break

        mp_status = row.get('status', 'Inactive')
        if 'status' not in row and 'status' not in lazada_df.columns:
            for col in row.index:
                if 'status' in str(col).lower() or 'item status' in str(col).lower():
                    mp_status = row[col]
                    break
        
        tc_info = tc_inv_lookup.get(sku, {'tc_status': 'Inactive', 'max_0': 'No'})
        tc_status = tc_info['tc_status']
        max_0 = tc_info['max_0']
        
        tc_stock = resolver.get_tc_stock(sku)
        reserved_stock = resolver.get_reserved_stock(sku)
        
        status_chk, stock_chk, action = evaluate_sku_logic(
            mp_status=mp_status,
            tc_status=tc_status,
            mp_stock=mp_stock,
            tc_stock=tc_stock,
            reserved_stock=reserved_stock,
            max_0=max_0
        )
        
        buffer = int(tc_stock) - int(mp_stock) if pd.notna(tc_stock) and pd.notna(mp_stock) else 0
        
        results.append({
            'Seller SKU': sku,
            'MP Status (Lazada)': mp_status,
            'TC Status': tc_status,
            'Status Check': status_chk,
            'MP Stock (Lazada)': mp_stock,
            'TC Stock': tc_stock,
            'Reserved Stock': reserved_stock,
            'Max 0': max_0,
            'Stock Check': stock_chk,
            'Buffer (TC - MP)': buffer,
            'Action Required': action
        })
        
    return pd.DataFrame(results)

def validate_shopee(shopee_stock_df, shopee_status_df, tc_inv_df, all_df):
    """
    Validates Shopee SG/MY/TH data at both the Product ID (Consolidated) level and SKU level.
    """
    resolver = StockResolver(all_df)
    
    active_pids = set()
    if shopee_status_df is not None and not shopee_status_df.empty:
        pid_col = None
        for col in shopee_status_df.columns:
            if 'product id' in str(col).lower() or 'pid' in str(col).lower():
                pid_col = col
                break
        if pid_col is None:
            pid_col = shopee_status_df.columns[0]
            
        for val in shopee_status_df[pid_col]:
            cleaned = clean_pid(val)
            if cleaned:
                active_pids.add(cleaned)
                
    tc_inv_lookup = {}
    if tc_inv_df is not None and not tc_inv_df.empty:
        for _, row in tc_inv_df.iterrows():
            sku = clean_sku(row.get('Custom SKU'))
            if sku:
                tc_status = normalize_status(row.get('Item status'))
                max_qty_val = row.get('Max Quantity')
                if pd.isna(max_qty_val) or str(max_qty_val).strip() == '':
                    max_0 = 'No'
                else:
                    try:
                        max_qty = float(max_qty_val)
                        max_0 = 'Yes' if max_qty == 0 else 'No'
                    except ValueError:
                        max_0 = 'No'
                tc_inv_lookup[sku] = {'tc_status': tc_status, 'max_0': max_0}
                
    sku_details = []
    pid_to_skus = {}
    
    for _, row in shopee_stock_df.iterrows():
        sku = clean_sku(row.get('SKU'))
        pid = clean_pid(row.get('Product ID'))
        if not sku or not pid:
            continue
            
        mp_stock = pd.to_numeric(row.get('Stock'), errors='coerce')
        mp_stock = 0 if pd.isna(mp_stock) else int(mp_stock)
        
        mp_status = "Active" if pid in active_pids else "Inactive"
        
        tc_info = tc_inv_lookup.get(sku, {'tc_status': 'Inactive', 'max_0': 'No'})
        tc_status = tc_info['tc_status']
        max_0 = tc_info['max_0']
        
        tc_stock = resolver.get_tc_stock(sku)
        reserved_stock = resolver.get_reserved_stock(sku)
        
        status_chk, stock_chk, action = evaluate_sku_logic(
            mp_status=mp_status,
            tc_status=tc_status,
            mp_stock=mp_stock,
            tc_stock=tc_stock,
            reserved_stock=reserved_stock,
            max_0=max_0
        )
        
        buffer = tc_stock - mp_stock
        
        sku_details.append({
            'Product ID': pid,
            'SKU': sku,
            'MP Status (Shopee)': mp_status,
            'TC Status': tc_status,
            'Status Check': status_chk,
            'MP Stock (Shopee)': mp_stock,
            'TC Stock': tc_stock,
            'Reserved Stock': reserved_stock,
            'Max 0': max_0,
            'Stock Check': stock_chk,
            'Buffer (TC - MP)': buffer,
            'Action Required': action
        })
        
        if pid not in pid_to_skus:
            pid_to_skus[pid] = []
        pid_to_skus[pid].append({
            'sku': sku,
            'mp_stock': mp_stock,
            'tc_stock': tc_stock
        })
        
    pid_summary = []
    for pid, items in pid_to_skus.items():
        total_mp_stock = sum(item['mp_stock'] for item in items)
        total_tc_stock = sum(item['tc_stock'] for item in items)
        skus_str = ", ".join(item['sku'] for item in items)
        status = "Active" if pid in active_pids else "Inactive"
        match = (total_mp_stock == total_tc_stock)
        
        pid_summary.append({
            'Product ID': pid,
            'Associated SKUs': skus_str,
            'MP Total Stock': total_mp_stock,
            'Consolidated TC Stock': total_tc_stock,
            'Stock Match': match,
            'MP Status': status
        })
        
    return pd.DataFrame(pid_summary), pd.DataFrame(sku_details)

def validate_tiktok(tiktok_active_df, tiktok_inactive_df, tc_inv_df, all_df):
    """
    Validates TikTok SG/MY/TH data at both the Product ID (Consolidated) level and SKU level.
    Combines Active and Inactive stock files.
    """
    resolver = StockResolver(all_df)
    
    # 1. Gather all TikTok items from both active and inactive reports
    tiktok_items = []
    
    if tiktok_active_df is not None and not tiktok_active_df.empty:
        sku_col = None
        for col in tiktok_active_df.columns:
            if 'seller sku' in str(col).lower() or 'sku' in str(col).lower():
                sku_col = col
                break
        if sku_col is None:
            sku_col = tiktok_active_df.columns[0]
            
        pid_col = None
        for col in tiktok_active_df.columns:
            if 'product id' in str(col).lower() or 'pid' in str(col).lower():
                pid_col = col
                break
        if pid_col is None:
            pid_col = tiktok_active_df.columns[1] if len(tiktok_active_df.columns) > 1 else tiktok_active_df.columns[0]
            
        qty_col = None
        for col in tiktok_active_df.columns:
            if 'quantity' in str(col).lower() or 'qty' in str(col).lower() or 'stock' in str(col).lower():
                qty_col = col
                break
        if qty_col is None:
            qty_col = tiktok_active_df.columns[2] if len(tiktok_active_df.columns) > 2 else tiktok_active_df.columns[0]

        for _, row in tiktok_active_df.iterrows():
            sku = clean_sku(row.get(sku_col))
            pid = clean_pid(row.get(pid_col))
            qty_val = pd.to_numeric(row.get(qty_col), errors='coerce')
            qty = 0 if pd.isna(qty_val) else int(qty_val)
            
            if sku:
                tiktok_items.append({
                    'sku': sku,
                    'pid': pid,
                    'mp_stock': qty,
                    'mp_status': 'Active'
                })
                
    if tiktok_inactive_df is not None and not tiktok_inactive_df.empty:
        sku_col = None
        for col in tiktok_inactive_df.columns:
            if 'seller sku' in str(col).lower() or 'sku' in str(col).lower():
                sku_col = col
                break
        if sku_col is None:
            sku_col = tiktok_inactive_df.columns[0]
            
        pid_col = None
        for col in tiktok_inactive_df.columns:
            if 'product id' in str(col).lower() or 'pid' in str(col).lower():
                pid_col = col
                break
        if pid_col is None:
            pid_col = tiktok_inactive_df.columns[1] if len(tiktok_inactive_df.columns) > 1 else tiktok_inactive_df.columns[0]
            
        qty_col = None
        for col in tiktok_inactive_df.columns:
            if 'quantity' in str(col).lower() or 'qty' in str(col).lower() or 'stock' in str(col).lower():
                qty_col = col
                break
        if qty_col is None:
            qty_col = tiktok_inactive_df.columns[2] if len(tiktok_inactive_df.columns) > 2 else tiktok_inactive_df.columns[0]

        for _, row in tiktok_inactive_df.iterrows():
            sku = clean_sku(row.get(sku_col))
            pid = clean_pid(row.get(pid_col))
            qty_val = pd.to_numeric(row.get(qty_col), errors='coerce')
            qty = 0 if pd.isna(qty_val) else int(qty_val)
            
            if sku:
                tiktok_items.append({
                    'sku': sku,
                    'pid': pid,
                    'mp_stock': qty,
                    'mp_status': 'Inactive'
                })

    # Deduplicate tiktok_items by SKU, prioritizing Active status
    sku_to_item = {}
    for item in tiktok_items:
        s = item['sku']
        if s not in sku_to_item:
            sku_to_item[s] = item
        else:
            # If duplicate exists, prioritize "Active"
            if sku_to_item[s]['mp_status'] == 'Inactive' and item['mp_status'] == 'Active':
                sku_to_item[s] = item
    tiktok_items = list(sku_to_item.values())

    # 2. Build TC Inventory Lookup
    tc_inv_lookup = {}
    if tc_inv_df is not None and not tc_inv_df.empty:
        for _, row in tc_inv_df.iterrows():
            sku = clean_sku(row.get('Custom SKU'))
            if sku:
                tc_status = normalize_status(row.get('Item status'))
                max_qty_val = row.get('Max Quantity')
                if pd.isna(max_qty_val) or str(max_qty_val).strip() == '':
                    max_0 = 'No'
                else:
                    try:
                        max_qty = float(max_qty_val)
                        max_0 = 'Yes' if max_qty == 0 else 'No'
                    except ValueError:
                        max_0 = 'No'
                tc_inv_lookup[sku] = {'tc_status': tc_status, 'max_0': max_0}
                
    sku_details = []
    pid_to_skus = {}
    
    # Process combined items
    for item in tiktok_items:
        sku = item['sku']
        pid = item['pid']
        mp_stock = item['mp_stock']
        mp_status = item['mp_status']
        
        tc_info = tc_inv_lookup.get(sku, {'tc_status': 'Inactive', 'max_0': 'No'})
        tc_status = tc_info['tc_status']
        max_0 = tc_info['max_0']
        
        tc_stock = resolver.get_tc_stock(sku)
        reserved_stock = resolver.get_reserved_stock(sku)
        
        status_chk, stock_chk, action = evaluate_sku_logic(
            mp_status=mp_status,
            tc_status=tc_status,
            mp_stock=mp_stock,
            tc_stock=tc_stock,
            reserved_stock=reserved_stock,
            max_0=max_0
        )
        
        buffer = tc_stock - mp_stock
        
        sku_details.append({
            'Product ID': pid,
            'SKU': sku,
            'MP Status (TikTok)': mp_status,
            'TC Status': tc_status,
            'Status Check': status_chk,
            'MP Stock (TikTok)': mp_stock,
            'TC Stock': tc_stock,
            'Reserved Stock': reserved_stock,
            'Max 0': max_0,
            'Stock Check': stock_chk,
            'Buffer (TC - MP)': buffer,
            'Action Required': action
        })
        
        if pid not in pid_to_skus:
            pid_to_skus[pid] = []
        pid_to_skus[pid].append({
            'sku': sku,
            'mp_stock': mp_stock,
            'tc_stock': tc_stock,
            'mp_status': mp_status
        })
        
    # Consolidate by Product ID
    pid_summary = []
    for pid, items in pid_to_skus.items():
        total_mp_stock = sum(item['mp_stock'] for item in items)
        total_tc_stock = sum(item['tc_stock'] for item in items)
        skus_str = ", ".join(item['sku'] for item in items)
        
        has_active_sku = any(item['mp_status'] == 'Active' for item in items)
        status = "Active" if has_active_sku else "Inactive"
        
        match = (total_mp_stock == total_tc_stock)
        
        pid_summary.append({
            'Product ID': pid,
            'Associated SKUs': skus_str,
            'MP Total Stock': total_mp_stock,
            'Consolidated TC Stock': total_tc_stock,
            'Stock Match': match,
            'MP Status': status
        })
        
    return pd.DataFrame(pid_summary), pd.DataFrame(sku_details)
