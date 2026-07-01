import re
import pandas as pd
import numpy as np

def is_bundle_sku(sku):
    """
    Checks if a normalized SKU is a bundle.
    A SKU is a bundle if it contains '+' or matches the pattern '<SKU>X<digits>$'.
    """
    if '+' in sku:
        return True
    if re.search(r'X\d+$', sku):
        return True
    return False

def resolve_bundle_details(sku, tc_stock_map):
    """
    Resolves the bundle components, formula type, individual stocks, and calculates the bundle stock.
    Returns a dict with details:
    {
        "is_bundle": bool,
        "type": str, # "Rule 1 (+)", "Rule 2 (X)", "Hybrid", or "None"
        "components_summary": str, # e.g. "A (Stock: 100), Bx2 (Stock: 50)"
        "components_list": list of dict,
        "calculated_stock": int
    }
    """
    if not is_bundle_sku(sku):
        return {
            "is_bundle": False,
            "type": "None",
            "components_summary": "",
            "components_list": [],
            "calculated_stock": tc_stock_map.get(sku, 0)
        }
        
    parts = sku.split('+')
    components_list = []
    part_stocks = []
    
    has_plus = len(parts) > 1
    has_multiplier = False
    
    for part in parts:
        part = part.strip()
        if not part:
            continue
            
        # Check for X multiplier, e.g. "AX2" -> base SKU "A", multiplier 2
        match = re.match(r'^(.*)X(\d+)$', part)
        if match:
            has_multiplier = True
            base_sku = match.group(1).strip()
            qty = int(match.group(2))
            base_stock = tc_stock_map.get(base_sku, 0)
            calculated = base_stock // qty if qty > 0 else 0
            
            components_list.append({
                "raw_part": part,
                "base_sku": base_sku,
                "multiplier": qty,
                "base_stock": base_stock,
                "calculated_stock": calculated
            })
            part_stocks.append(calculated)
        else:
            base_stock = tc_stock_map.get(part, 0)
            components_list.append({
                "raw_part": part,
                "base_sku": part,
                "multiplier": 1,
                "base_stock": base_stock,
                "calculated_stock": base_stock
            })
            part_stocks.append(base_stock)
            
    # Determine formula type
    if has_plus and has_multiplier:
        formula_type = "Hybrid"
    elif has_plus:
        formula_type = "Rule 1 (+)"
    else:
        formula_type = "Rule 2 (X)"
        
    # Minimum of all part stocks
    calculated_stock = min(part_stocks) if part_stocks else 0
    
    # Create summary string
    summary_parts = []
    for c in components_list:
        if c['multiplier'] > 1:
            summary_parts.append(f"{c['base_sku']}x{c['multiplier']} (TC Stock: {c['base_stock']} -> Bundle: {c['calculated_stock']})")
        else:
            summary_parts.append(f"{c['base_sku']} (TC Stock: {c['base_stock']})")
            
    components_summary = " + ".join(summary_parts)
    
    return {
        "is_bundle": True,
        "type": formula_type,
        "components_summary": components_summary,
        "components_list": components_list,
        "calculated_stock": calculated_stock
    }

def evaluate_validation_rules(row):
    """
    Evaluates the validation logic for a single SKU.
    Input row dict contains:
        marketplace_status, marketplace_stock, tc_status, tc_stock, reserved_stock, max
        
    Calculates:
        status_check: bool
        stock_check: bool
        buffer: int (marketplace_stock - tc_stock)
        recommendation: str
    """
    mp_status = str(row.get('marketplace_status', '')).strip().upper()
    tc_status = str(row.get('tc_status', '')).strip().upper()
    
    mp_stock = int(row.get('marketplace_stock', 0))
    tc_stock = int(row.get('tc_stock', 0))
    reserved = int(row.get('reserved_stock', 0))
    max_val = str(row.get('max', 'No')).strip().upper()
    
    # 1. Checks
    status_check = (mp_status == tc_status)
    stock_check = (mp_stock == tc_stock)
    buffer = mp_stock - tc_stock
    
    recommendation = "All Good"
    
    # 2. Rules Evaluation
    if not status_check and stock_check:
        # Case A: Stock = 0
        if tc_stock == 0:
            recommendation = "Change to Inactive"
        # Case B: Stock > 1 and Max = Yes (we treat >= 1 as > 1)
        elif tc_stock >= 1 and max_val == "YES":
            recommendation = "Change to Inactive"
        # Case C: Stock > 1 and Max = No
        elif tc_stock >= 1 and max_val == "NO":
            recommendation = "Change to Active"
            
    elif status_check and not stock_check:
        # Case D: Max = Yes
        if max_val == "YES":
            recommendation = "Max Already Done"
        # Case E: Reserved Stock > 0
        elif reserved > 0:
            recommendation = "Reserved Done"
        # Case F: Reserved Stock = 0 and Buffer > 0 (Marketplace Stock > TC Stock)
        elif reserved == 0 and buffer > 0:
            recommendation = "Buffer Done"
        # Case G: Reserved Stock = 0 and Buffer < 0 (Marketplace Stock < TC Stock)
        elif reserved == 0 and buffer < 0:
            recommendation = "Impact / Force Stock Push"
            
    elif status_check and stock_check:
        # Case H: All Good
        recommendation = "All Good"
        
    else:
        # Fallback case: Status Check = FALSE and Stock Check = FALSE
        # Custom logic: Determine correct status based on TC stock and Max
        if tc_stock == 0 or max_val == "YES":
            recommendation = "Change to Inactive"
        else:
            recommendation = "Change to Active & Force Push"
            
    return status_check, stock_check, buffer, recommendation

def run_validation(marketplace_df, tc_inventory_df, all_file_df, errors_list):
    """
    Main validation engine:
    - Merges files on SKU.
    - Resolves bundle SKUs.
    - Performs SKU-level validation.
    - Performs PID-level validation (if Shopee/TikTok).
    - Summarizes dashboard metrics.
    """
    if marketplace_df.empty:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), {}
        
    # Build maps from TC Inventory and All File for fast lookup
    tc_status_map = {}
    tc_max_map = {}
    if not tc_inventory_df.empty:
        for _, row in tc_inventory_df.iterrows():
            sku = row['sku']
            tc_status_map[sku] = row['tc_status']
            tc_max_map[sku] = row['max']
            
    tc_stock_map = {}
    reserved_stock_map = {}
    if not all_file_df.empty:
        for _, row in all_file_df.iterrows():
            sku = row['sku']
            tc_stock_map[sku] = row['tc_stock']
            reserved_stock_map[sku] = row['reserved_stock']
            
    # Process each marketplace row
    records = []
    bundle_records = []
    
    for _, row in marketplace_df.iterrows():
        sku = row['sku']
        mp_stock = row['marketplace_stock']
        mp_status = row['marketplace_status']
        pid = row['product_id']
        
        # 1. Resolve TC Status & Max (from TC Inventory)
        # Note: If it's a bundle SKU, status might be missing in TC Inventory. 
        # We can map it if it exists or default to "Active" / "N/A"
        tc_status = tc_status_map.get(sku, "Inactive")
        max_val = tc_max_map.get(sku, "No")
        
        # 2. Resolve Stock and Reserved Stock
        is_bundle = is_bundle_sku(sku)
        
        if is_bundle:
            bundle_res = resolve_bundle_details(sku, tc_stock_map)
            tc_stock = bundle_res['calculated_stock']
            # Reserved Stock for bundle: let's treat it as 0 or calculate if components have reserved stock
            # Usually reserved stock is 0 for bundles, or we look it up. Let's look up or default to 0.
            reserved_stock = reserved_stock_map.get(sku, 0)
            
            # Save bundle details for Bundle SKU Report
            bundle_records.append({
                "bundle_sku": sku,
                "marketplace_stock": mp_stock,
                "calculated_tc_stock": tc_stock,
                "type": bundle_res['type'],
                "components_summary": bundle_res['components_summary']
            })
        else:
            tc_stock = tc_stock_map.get(sku, 0)
            reserved_stock = reserved_stock_map.get(sku, 0)
            
        # 3. Evaluate Validation Rules
        row_eval = {
            "marketplace_status": mp_status,
            "marketplace_stock": mp_stock,
            "tc_status": tc_status,
            "tc_stock": tc_stock,
            "reserved_stock": reserved_stock,
            "max": max_val
        }
        
        status_check, stock_check, buffer, recommendation = evaluate_validation_rules(row_eval)
        
        records.append({
            "sku": sku,
            "product_id": pid,
            "marketplace_status": mp_status,
            "tc_status": tc_status,
            "marketplace_stock": mp_stock,
            "tc_stock": tc_stock,
            "reserved_stock": reserved_stock,
            "max": max_val,
            "status_check": status_check,
            "stock_check": stock_check,
            "buffer": buffer,
            "recommendation": recommendation,
            "is_bundle": is_bundle
        })
        
    validation_df = pd.DataFrame(records)
    bundle_df = pd.DataFrame(bundle_records)
    
    # PID Level Validation (if Product ID is not "N/A" and there are valid PIDs)
    pid_df = pd.DataFrame()
    if not validation_df.empty and 'product_id' in validation_df.columns:
        valid_pids_df = validation_df[validation_df['product_id'] != "N/A"]
        if not valid_pids_df.empty:
            # Group records by Product ID
            # Consolidate TC Stock by Product ID, and Marketplace Stock by Product ID
            pid_grouped = valid_pids_df.groupby('product_id').agg({
                'marketplace_stock': 'sum',
                'tc_stock': 'sum'
            }).reset_index()
            
            pid_grouped['stock_check'] = pid_grouped['marketplace_stock'] == pid_grouped['tc_stock']
            pid_grouped['recommendation'] = pid_grouped.apply(
                lambda r: "All Good" if r['stock_check'] else "Mismatch / Force Stock Push",
                axis=1
            )
            pid_df = pid_grouped
            
    # Calculate Dashboard Summary Metrics
    summary = {
        "total_sku": 0,
        "matched": 0,
        "status_mismatch": 0,
        "stock_mismatch": 0,
        "bundle_sku_count": 0,
        "inactive_sku": 0,
        "need_force_push": 0,
        "need_status_change": 0
    }
    
    if not validation_df.empty:
        summary["total_sku"] = len(validation_df)
        summary["matched"] = len(validation_df[(validation_df['status_check'] == True) & (validation_df['stock_check'] == True)])
        summary["status_mismatch"] = len(validation_df[validation_df['status_check'] == False])
        summary["stock_mismatch"] = len(validation_df[validation_df['stock_check'] == False])
        summary["bundle_sku_count"] = len(validation_df[validation_df['is_bundle'] == True])
        summary["inactive_sku"] = len(validation_df[validation_df['marketplace_status'].str.upper() == "INACTIVE"])
        
        # Need Force Push: recommendation is "Impact / Force Stock Push" or contains "Force Push"
        summary["need_force_push"] = len(validation_df[validation_df['recommendation'].str.contains("Force Stock Push|Force Push", case=False, na=False)])
        
        # Need Status Change: recommendation is "Change to Active" or "Change to Inactive"
        summary["need_status_change"] = len(validation_df[validation_df['recommendation'].str.contains("Change to Active|Change to Inactive", case=False, na=False)])
        
    return validation_df, pid_df, bundle_df, summary
