import os
import sys
# Add parent directory to sys.path so 'app' package imports work when run directly
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from fastapi import FastAPI, File, UploadFile, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
import uuid
import io
import pandas as pd
from typing import Optional, List

from app.parser import (
    parse_lazada,
    parse_shopee,
    parse_tiktok,
    parse_tc_inventory,
    parse_all_file
)
from app.validator import run_validation
from app.report import (
    generate_status_report,
    generate_pid_report,
    generate_bundle_report,
    generate_error_report
)

app = FastAPI(title="Stock and Status Validator API")

# Enable CORS for local development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # For local setup, allow all origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global in-memory cache for reports
REPORT_CACHE = {}

@app.post("/api/validate")
async def validate_data(
    country: str = Form(...),
    marketplace: str = Form(...),
    # Lazada Files
    marketplace_stock_file: Optional[UploadFile] = File(None),
    # Shopee / TikTok common
    stock_file: Optional[UploadFile] = File(None),
    # Shopee specific
    status_file: Optional[UploadFile] = File(None),
    # TikTok specific
    active_status_file: Optional[UploadFile] = File(None),
    inactive_status_file: Optional[UploadFile] = File(None),
    # Shared TC files
    tc_inventory_file: Optional[UploadFile] = File(None),
    all_file: Optional[UploadFile] = File(None),
):
    errors = []
    
    # 1. Check file existence based on Marketplace
    marketplace = marketplace.upper()
    
    # TC Inventory and All File are ALWAYS required
    if not tc_inventory_file:
        errors.append({"file": "TC Inventory File", "row": "N/A", "sku": "N/A", "error": "Missing TC Inventory File"})
    if not all_file:
        errors.append({"file": "All File", "row": "N/A", "sku": "N/A", "error": "Missing All File"})
        
    marketplace_df = pd.DataFrame()
    tc_inventory_df = pd.DataFrame()
    all_file_df = pd.DataFrame()
    
    # Parse TC Files if uploaded
    if tc_inventory_file:
        tc_bytes = await tc_inventory_file.read()
        tc_inventory_df = parse_tc_inventory(tc_bytes, tc_inventory_file.filename, errors)
        
    if all_file:
        all_bytes = await all_file.read()
        all_file_df = parse_all_file(all_bytes, all_file.filename, country, errors)
        
    # Parse Marketplace Files
    if marketplace == "LAZADA":
        if not marketplace_stock_file:
            errors.append({"file": "Marketplace Stock File", "row": "N/A", "sku": "N/A", "error": "Missing Lazada Marketplace Stock File"})
        else:
            laz_bytes = await marketplace_stock_file.read()
            marketplace_df = parse_lazada(laz_bytes, marketplace_stock_file.filename, errors)
            
    elif marketplace == "SHOPEE":
        if not stock_file:
            errors.append({"file": "Stock File", "row": "N/A", "sku": "N/A", "error": "Missing Shopee Stock File"})
        # Note: Status File is required for Shopee status check
        if not status_file:
            errors.append({"file": "Status File", "row": "N/A", "sku": "N/A", "error": "Missing Shopee Status File"})
            
        if stock_file:
            stock_bytes = await stock_file.read()
            status_bytes = await status_file.read() if status_file else None
            status_name = status_file.filename if status_file else ""
            marketplace_df = parse_shopee(stock_bytes, stock_file.filename, status_bytes, status_name, errors)
            
    elif marketplace == "TIKTOK":
        if not stock_file:
            errors.append({"file": "Stock File", "row": "N/A", "sku": "N/A", "error": "Missing TikTok Stock File"})
        if not active_status_file:
            errors.append({"file": "Active Status File", "row": "N/A", "sku": "N/A", "error": "Missing TikTok Active Status File"})
        if not inactive_status_file:
            errors.append({"file": "Inactive Status File", "row": "N/A", "sku": "N/A", "error": "Missing TikTok Inactive Status File"})
            
        if stock_file:
            stock_bytes = await stock_file.read()
            act_bytes = await active_status_file.read() if active_status_file else None
            inact_bytes = await inactive_status_file.read() if inactive_status_file else None
            act_name = active_status_file.filename if active_status_file else ""
            inact_name = inactive_status_file.filename if inactive_status_file else ""
            
            marketplace_df = parse_tiktok(
                stock_bytes, stock_file.filename, 
                act_bytes, act_name, 
                inact_bytes, inact_name, 
                errors
            )
    else:
        raise HTTPException(status_code=400, detail="Invalid marketplace selection")
        
    # Check if there are blocking parsing errors (no data parsed)
    if marketplace_df.empty or tc_inventory_df.empty or all_file_df.empty:
        # Generate session_id to cache the errors list
        session_id = str(uuid.uuid4())
        REPORT_CACHE[session_id] = {
            "status_df": pd.DataFrame(),
            "pid_df": pd.DataFrame(),
            "bundle_df": pd.DataFrame(),
            "errors": errors
        }
        return {
            "success": False,
            "errors": errors,
            "session_id": session_id,
            "summary": {
                "total_sku": 0, "matched": 0, "status_mismatch": 0, "stock_mismatch": 0,
                "bundle_sku_count": 0, "inactive_sku": 0, "need_force_push": 0, "need_status_change": 0
            },
            "results": [],
            "pid_results": [],
            "bundle_results": []
        }
        
    # Run validation
    validation_df, pid_df, bundle_df, summary = run_validation(
        marketplace_df, tc_inventory_df, all_file_df, errors
    )
    
    # Cache the dataframes
    session_id = str(uuid.uuid4())
    REPORT_CACHE[session_id] = {
        "status_df": validation_df,
        "pid_df": pid_df,
        "bundle_df": bundle_df,
        "errors": errors
    }
    
    # Prepare preview records for UI (limit to 500 for responsiveness if large, but UI can paginate)
    results_json = validation_df.to_dict(orient="records")
    pid_json = pid_df.to_dict(orient="records") if not pid_df.empty else []
    bundle_json = bundle_df.to_dict(orient="records") if not bundle_df.empty else []
    
    return {
        "success": True,
        "session_id": session_id,
        "summary": summary,
        "errors": errors,
        "results": results_json,
        "pid_results": pid_json,
        "bundle_results": bundle_json
    }

@app.get("/api/export/{report_type}")
async def export_report(report_type: str, session_id: str):
    """
    Downloads Excel reports from cache.
    report_type can be: status, pid, bundle, errors
    """
    if session_id not in REPORT_CACHE:
        raise HTTPException(status_code=404, detail="Session not found or expired")
        
    cache = REPORT_CACHE[session_id]
    
    if report_type == "status":
        file_bytes = generate_status_report(cache["status_df"])
        filename = f"Status_Validation_Report_{session_id[:8]}.xlsx"
    elif report_type == "pid":
        file_bytes = generate_pid_report(cache["pid_df"])
        filename = f"PID_Validation_Report_{session_id[:8]}.xlsx"
    elif report_type == "bundle":
        file_bytes = generate_bundle_report(cache["bundle_df"])
        filename = f"Bundle_Validation_Report_{session_id[:8]}.xlsx"
    elif report_type == "errors":
        file_bytes = generate_error_report(cache["errors"])
        filename = f"Error_Validation_Report_{session_id[:8]}.xlsx"
    else:
        raise HTTPException(status_code=400, detail="Invalid report type")
        
    return StreamingResponse(
        io.BytesIO(file_bytes),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )

@app.get("/api/health")
def health_check():
    return {"status": "ok"}
