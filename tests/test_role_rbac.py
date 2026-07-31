import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from core.database import Base
from core.models import User, Client, UserClientAccess
from services.client_service import get_clients, verify_client_access
from services.auth_service import create_user, update_user_role_and_access

# Setup in-memory SQLite DB for testing RBAC
@pytest.fixture(name="db_session")
def fixture_db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()

def test_rbac_client_retrieval(db_session):
    # 1. Create client records
    c1 = Client(business_name="Client Alpha", fiscal_year_end="Dec 31", status="Active")
    c2 = Client(business_name="Client Beta", fiscal_year_end="Dec 31", status="Active")
    c3 = Client(business_name="Client Gamma", fiscal_year_end="Dec 31", status="Active")
    db_session.add_all([c1, c2, c3])
    db_session.commit()
    
    # 2. Create users
    admin = create_user(db_session, "Admin User", "admin@test.com", "pass123", "Admin")
    accountant = create_user(db_session, "Acct User", "acct@test.com", "pass123", "Accountant")
    bookkeeper = create_user(db_session, "Bookkeeper User", "bk@test.com", "pass123", "Bookkeeper")
    client_user = create_user(db_session, "Client User", "cl@test.com", "pass123", "Client")
    
    # Map Bookkeeper to Client Alpha and Client Beta (many-to-many)
    update_user_role_and_access(db_session, bookkeeper.id, "Bookkeeper", assigned_client_ids=[c1.id, c2.id])
    
    # Map Client User to Client Gamma
    update_user_role_and_access(db_session, client_user.id, "Client", client_id=c3.id)
    
    # 3. Test query filtering for Admin (should see all 3 clients)
    admin_clients = get_clients(db_session, admin)
    assert len(admin_clients) == 3
    assert {c.business_name for c in admin_clients} == {"Client Alpha", "Client Beta", "Client Gamma"}
    
    # 4. Test query filtering for Accountant (should see all 3 clients)
    acct_clients = get_clients(db_session, accountant)
    assert len(acct_clients) == 3
    
    # 5. Test query filtering for Bookkeeper (should see Alpha and Beta)
    bk_clients = get_clients(db_session, bookkeeper)
    assert len(bk_clients) == 2
    assert {c.business_name for c in bk_clients} == {"Client Alpha", "Client Beta"}
    
    # 6. Test query filtering for Client (should see Gamma only)
    cl_clients = get_clients(db_session, client_user)
    assert len(cl_clients) == 1
    assert cl_clients[0].business_name == "Client Gamma"

def test_rbac_client_access_verification(db_session):
    c1 = Client(business_name="Client Alpha", fiscal_year_end="Dec 31", status="Active")
    c2 = Client(business_name="Client Beta", fiscal_year_end="Dec 31", status="Active")
    db_session.add_all([c1, c2])
    db_session.commit()
    
    admin = create_user(db_session, "Admin User", "admin@test.com", "pass123", "Admin")
    bookkeeper = create_user(db_session, "Bookkeeper User", "bk@test.com", "pass123", "Bookkeeper")
    
    # Map Bookkeeper to c1 only
    update_user_role_and_access(db_session, bookkeeper.id, "Bookkeeper", assigned_client_ids=[c1.id])
    
    # Verify access helper responses
    assert verify_client_access(db_session, c1.id, admin) is True
    assert verify_client_access(db_session, c2.id, admin) is True
    
    assert verify_client_access(db_session, c1.id, bookkeeper) is True
    assert verify_client_access(db_session, c2.id, bookkeeper) is False
