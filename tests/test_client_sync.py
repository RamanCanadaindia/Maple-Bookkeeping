import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from unittest.mock import MagicMock

# Mock Streamlit
mock_st = MagicMock()
mock_st.session_state = {}
sys.modules['streamlit'] = mock_st

from services.client_service import sync_global_active_client

def test_sync_global_active_client_initialization():
    mock_st.session_state.clear()
    client_options = {
        "Raman Tax and Accounting Inc": 10,
        "Raman Bookkeeping Demo Client": 20
    }
    
    # Initialize
    sync_global_active_client("ledger_client_select", client_options)
    
    # Check that global_active_client_id is initialized to first item (10)
    assert mock_st.session_state["global_active_client_id"] == 10
    # Check that widget key is set to first item's name
    assert mock_st.session_state["ledger_client_select"] == "Raman Tax and Accounting Inc"

def test_sync_global_active_client_syncs_existing():
    mock_st.session_state.clear()
    mock_st.session_state["global_active_client_id"] = 20
    
    client_options = {
        "Raman Tax and Accounting Inc": 10,
        "Raman Bookkeeping Demo Client": 20
    }
    
    # Sync from global active ID
    sync_global_active_client("reports_client_select", client_options)
    
    # Widget key value should update to option name for ID 20
    assert mock_st.session_state["reports_client_select"] == "Raman Bookkeeping Demo Client"

def test_sync_global_active_client_callback():
    mock_st.session_state.clear()
    mock_st.session_state["global_active_client_id"] = 10
    
    client_options = {
        "Raman Tax and Accounting Inc": 10,
        "Raman Bookkeeping Demo Client": 20,
        "➕ Register New Client Profile": 0
    }
    
    callback = sync_global_active_client("statement_client_select", client_options)
    
    # Simulate user changing selectbox to index 1 (ID 20)
    mock_st.session_state["statement_client_select"] = "Raman Bookkeeping Demo Client"
    callback()
    
    # Global active ID should be updated to 20
    assert mock_st.session_state["global_active_client_id"] == 20
    
    # Simulate user changing to Register (ID 0)
    mock_st.session_state["statement_client_select"] = "➕ Register New Client Profile"
    callback()
    
    # Global active ID should NOT change to 0, it should remain 20
    assert mock_st.session_state["global_active_client_id"] == 20
