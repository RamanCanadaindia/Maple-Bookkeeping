from datetime import datetime
from typing import List, Dict, Any

def detect_internal_transfers(transactions: List[Dict[str, Any]], bank_accounts_map: Dict[int, str]) -> List[Dict[str, Any]]:
    """
    Identifies internal offsetting transfers between a client's own mapped accounts.
    e.g. withdrawal from Checking, deposit to Credit Card on the same or nearby date.
    """
    # Create copy to mutate
    tx_list = [dict(tx) for tx in transactions]
    
    # 3-day buffer window for clearance delays
    max_days_diff = 3
    
    # Track which items have been matched to prevent double matching
    matched_indices = set()
    
    for i in range(len(tx_list)):
        if i in matched_indices:
            continue
            
        tx_a = tx_list[i]
        amount_a = float(tx_a.get("amount", 0.0))
        date_a = tx_a.get("date")
        acc_a_id = tx_a.get("account_id")
        
        if amount_a == 0.0 or not isinstance(date_a, datetime):
            continue
            
        for j in range(i + 1, len(tx_list)):
            if j in matched_indices:
                continue
                
            tx_b = tx_list[j]
            amount_b = float(tx_b.get("amount", 0.0))
            date_b = tx_b.get("date")
            acc_b_id = tx_b.get("account_id")
            
            if amount_b == 0.0 or not isinstance(date_b, datetime) or acc_a_id == acc_b_id:
                continue
                
            # Must be opposing signs (+100.0 and -100.0)
            if abs(amount_a + amount_b) < 0.01: 
                days_diff = abs((date_a - date_b).days)
                if days_diff <= max_days_diff:
                    # Found match! Flag as transfers
                    matched_indices.add(i)
                    matched_indices.add(j)
                    
                    acc_a_name = bank_accounts_map.get(acc_a_id, "Linked Account")
                    acc_b_name = bank_accounts_map.get(acc_b_id, "Linked Account")
                    
                    tx_list[i]["is_transfer"] = True
                    tx_list[i]["transfer_linked_acc"] = acc_b_name
                    tx_list[i]["category"] = "Internal Transfer"
                    
                    tx_list[j]["is_transfer"] = True
                    tx_list[j]["transfer_linked_acc"] = acc_a_name
                    tx_list[j]["category"] = "Internal Transfer"
                    break
                    
    return tx_list
