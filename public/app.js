// Global API URL prefix
const API_BASE = '';

// Active states and global references
let globalReminderTypes = [];
let globalClients = [];

document.addEventListener('DOMContentLoaded', () => {
    initNavigation();
    initDashboard();
    initDashboardSearch();
    initCompanyLookup();
    initClients();
    initSchedules();
    initTemplates();
    initSettings();
    
    // Initial page load
    loadDashboardData();
});

/* -------------------------------------------------------------
   Helper Functions (Toasts and Formatting)
   ------------------------------------------------------------- */
function showToast(message, type = 'success') {
    const container = document.getElementById('toast-container');
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    
    let icon = '✅';
    if (type === 'warning') icon = '⚠️';
    if (type === 'danger') icon = '🚨';
    
    toast.innerHTML = `
        <span class="toast-icon">${icon}</span>
        <span class="toast-message">${message}</span>
        <button class="toast-close">&times;</button>
    `;
    
    container.appendChild(toast);
    
    const closeBtn = toast.querySelector('.toast-close');
    closeBtn.addEventListener('click', () => {
        toast.style.transform = 'translateX(120%)';
        toast.style.opacity = '0';
        setTimeout(() => toast.remove(), 300);
    });
    
    setTimeout(() => {
        if (toast.parentElement) {
            toast.style.transform = 'translateX(120%)';
            toast.style.opacity = '0';
            setTimeout(() => toast.remove(), 300);
        }
    }, 4500);
}

function formatDate(dateStr) {
    if (!dateStr) return '-';
    // dateStr is YYYY-MM-DD, convert to standard format
    return dateStr;
}

function formatDateTime(isoStr) {
    if (!isoStr) return '-';
    const d = new Date(isoStr);
    if (isNaN(d.getTime())) return isoStr;
    const y = d.getUTCFullYear();
    const m = String(d.getUTCMonth() + 1).padStart(2, '0');
    const day = String(d.getUTCDate()).padStart(2, '0');
    const hr = String(d.getUTCHours()).padStart(2, '0');
    const min = String(d.getUTCMinutes()).padStart(2, '0');
    const sec = String(d.getUTCSeconds()).padStart(2, '0');
    return `${y}-${m}-${day} ${hr}:${min}:${sec}`;
}

/* -------------------------------------------------------------
   Single Page Application Navigation
   ------------------------------------------------------------- */
function initNavigation() {
    // Sidebar view buttons
    const navButtons = document.querySelectorAll('.nav-btn');
    const sections = document.querySelectorAll('.view-section');
    
    navButtons.forEach(btn => {
        btn.addEventListener('click', () => {
            const targetView = btn.getAttribute('data-view');
            
            navButtons.forEach(b => b.classList.remove('active'));
            sections.forEach(s => s.classList.remove('active'));
            
            btn.classList.add('active');
            document.getElementById(`view-${targetView}`).classList.add('active');
            
            // Route initialization on page display
            if (targetView === 'dashboard') loadDashboardData();
            if (targetView === 'clients') loadClientsData();
            if (targetView === 'company-lookup') loadCompanyLookupData();
            if (targetView === 'schedules') loadSchedulesData();
            if (targetView === 'templates') loadTemplatesData();
            if (targetView === 'quicksend') loadQuickSendData();
            if (targetView === 'settings') loadSettingsData();
        });
    });

    // Sub-tabs navigation
    const tabButtons = document.querySelectorAll('.tab-btn');
    const tabContents = document.querySelectorAll('.tab-content');
    
    tabButtons.forEach(btn => {
        btn.addEventListener('click', () => {
            const targetTab = btn.getAttribute('data-tab');
            const parentSection = btn.closest('.view-section');
            
            parentSection.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
            parentSection.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
            
            btn.classList.add('active');
            document.getElementById(`tab-${targetTab}`).classList.add('active');
        });
    });
}

/* -------------------------------------------------------------
   Dashboard Controller
   ------------------------------------------------------------- */
function initDashboard() {
    const runBtn = document.getElementById('btn-run-scheduler');
    runBtn.addEventListener('click', async () => {
        runBtn.disabled = true;
        runBtn.innerText = 'Checking...';
        
        try {
            const res = await fetch(`${API_BASE}/api/scheduler/run`, { method: 'POST' });
            const data = await res.json();
            
            if (res.ok) {
                if (data.approval_only) {
                    showToast(`Approval-only check completed: ${data.notifications_generated} reminders prepared. No emails were sent.`, 'success');
                } else if (data.rollovers > 0 || data.notifications_generated > 0 || data.sent_success > 0 || data.sent_failed > 0) {
                    showToast(`Scheduler completed: ${data.sent_success} sent, ${data.sent_failed} failed, ${data.notifications_generated} alerts created, ${data.rollovers} rollovers.`, 'success');
                } else {
                    showToast('Scheduler run completed. No pending emails or rollovers processed.', 'info');
                }
                if (data.errors && data.errors.length > 0) {
                    showToast(`Encountered ${data.errors.length} operational warnings during execution.`, 'warning');
                }
                loadDashboardData();
            } else {
                showToast(`Scheduler error: ${data.error || 'Unknown failure'}`, 'danger');
            }
        } catch (err) {
            showToast(`API Connection error: ${err.message}`, 'danger');
        } finally {
            runBtn.disabled = false;
            runBtn.innerText = 'Check for Due Reminders';
        }
    });

    const clearBtn = document.getElementById('btn-clear-history');
    clearBtn.addEventListener('click', async () => {
        if (confirm('Are you sure you want to clear all historical dispatch logs? This cannot be undone.')) {
            try {
                const res = await fetch(`${API_BASE}/api/history/clear`, { method: 'POST' });
                if (res.ok) {
                    showToast('History logs cleared successfully.', 'success');
                    loadDashboardData();
                }
            } catch (err) {
                showToast('Failed to clear logs: ' + err.message, 'danger');
            }
        }
    });
}

async function loadDashboardData() {
    try {
        const res = await fetch(`${API_BASE}/api/dashboard`);
        if (!res.ok) throw new Error('HTTP ' + res.status);
        const data = await res.json();
        
        // Update metric values
        const statClients = document.getElementById('stat-clients');
        if (statClients) statClients.innerText = data.metrics.totalClients;
        const statSched = document.getElementById('stat-schedules');
        if (statSched) statSched.innerText = data.metrics.activeSchedules;
        const statPend = document.getElementById('stat-pending');
        if (statPend) statPend.innerText = data.metrics.pendingNotifications;
        const statSucc = document.getElementById('stat-success');
        if (statSucc) statSucc.innerText = `${data.metrics.successRate}%`;
        
        // Update Upcoming alerts table
        const upcomingTbody = document.querySelector('#table-upcoming tbody');
        if (data.upcoming.length === 0) {
            upcomingTbody.innerHTML = '<tr><td colspan="8" class="empty">No upcoming reminders in the queue. Configure active schedules.</td></tr>';
        } else {
            upcomingTbody.innerHTML = data.upcoming.map(n => `
                <tr>
                    <td><strong>${formatDate(n.send_date)}</strong></td>
                    <td>${n.client_name}</td>
                    <td>${n.business_name || '-'}</td>
                    <td>${n.filing_name}</td>
                    <td>${formatDate(n.due_date)}</td>
                    <td><code>${n.offset_days}</code></td>
                    <td><span class="badge badge-${n.status.toLowerCase()}">${n.status}</span></td>
                    <td>
                        <button onclick="sendNotificationNow(${n.id}, this)" class="btn btn-sm btn-primary">✉️ Send Now</button>
                    </td>
                </tr>
            `).join('');
        }
        
        // Update dispatch history logs table
        const historyTbody = document.querySelector('#table-history tbody');
        if (data.history.length === 0) {
            historyTbody.innerHTML = '<tr><td colspan="6" class="empty">No email history found.</td></tr>';
        } else {
            historyTbody.innerHTML = data.history.map(h => `
                <tr>
                    <td>${formatDateTime(h.sent_at)}</td>
                    <td><code>${h.recipient}</code></td>
                    <td><strong>${h.business_name || h.client_name || '-'}</strong></td>
                    <td>${h.subject}</td>
                    <td><span class="badge badge-${h.status.toLowerCase()}">${h.status}</span></td>
                    <td><span class="help">${h.status === 'Sent' ? (h.message_id || 'Sent successfully') : (h.error_details || 'Unknown Error')}</span></td>
                </tr>
            `).join('');
        }
    } catch (err) {
        showToast('Failed to load dashboard data: ' + err.message, 'danger');
    }
}

/* -------------------------------------------------------------
   Clients Profiles CRUD Controller
   ------------------------------------------------------------- */
function initClients() {
    const addForm = document.getElementById('form-add-client');
    addForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const payload = {
            name: document.getElementById('client-name').value,
            email: document.getElementById('client-email').value,
            phone: document.getElementById('client-phone').value,
            business_name: document.getElementById('client-business').value,
            business_number: document.getElementById('client-bn').value,
            corporation_number: document.getElementById('client-corpnum').value,
            fiscal_year_end: document.getElementById('client-yearend').value,
            gst_reporting_period: document.getElementById('client-gst-period').value,
            payroll_frequency: document.getElementById('client-payroll-freq').value,
            payroll_remitter_type: document.getElementById('client-payroll-type').value,
            bc_anniversary_date: document.getElementById('client-bc-anniversary').value
        };
        
        try {
            const res = await fetch(`${API_BASE}/api/clients`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
            const data = await res.json();
            
            if (res.ok) {
                showToast(`Successfully registered client: ${data.name}`);
                addForm.reset();
                
                // Reload data and switch back to tab 1 (view list)
                await loadClientsData();
                document.querySelector('.tab-btn[data-tab="clients-list"]').click();
            } else {
                showToast(`Failed to register: ${data.error}`, 'danger');
            }
        } catch (err) {
            showToast('API Connection error: ' + err.message, 'danger');
        }
    });

    // Select edit client dropdown trigger
    const editSelect = document.getElementById('select-edit-client');
    const editForm = document.getElementById('form-edit-client');
    
    editSelect.addEventListener('change', () => {
        const id = editSelect.value;
        if (!id) {
            resetEditClientForm();
            return;
        }
        
        const client = globalClients.find(c => c.id === parseInt(id));
        if (client) {
            document.getElementById('edit-client-id').value = client.id;
            document.getElementById('edit-client-name').value = client.name;
            document.getElementById('edit-client-email').value = client.email;
            document.getElementById('edit-client-phone').value = client.phone || '';
            document.getElementById('edit-client-business').value = client.business_name || '';
            document.getElementById('edit-client-yearend').value = client.fiscal_year_end || '';
            
            // Enable form elements
            editForm.classList.remove('disabled-form');
            editForm.querySelectorAll('input, select, button').forEach(el => el.disabled = false);
        }
    });

    // Edit Client Submit
    editForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const id = document.getElementById('edit-client-id').value;
        const payload = {
            name: document.getElementById('edit-client-name').value,
            email: document.getElementById('edit-client-email').value,
            phone: document.getElementById('edit-client-phone').value,
            business_name: document.getElementById('edit-client-business').value,
            fiscal_year_end: document.getElementById('edit-client-yearend').value
        };
        
        try {
            const res = await fetch(`${API_BASE}/api/clients/${id}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
            const data = await res.json();
            
            if (res.ok) {
                showToast(`Updated profile details for client: ${payload.name}`);
                resetEditClientForm();
                await loadClientsData();
                document.querySelector('.tab-btn[data-tab="clients-list"]').click();
            } else {
                showToast(`Failed to update: ${data.error}`, 'danger');
            }
        } catch (err) {
            showToast('API Connection error: ' + err.message, 'danger');
        }
    });

    // Delete Client Button
    const deleteBtn = document.getElementById('btn-delete-client');
    deleteBtn.addEventListener('click', async () => {
        const id = document.getElementById('edit-client-id').value;
        const name = document.getElementById('edit-client-name').value;
        const confirmCheck = document.getElementById('confirm-delete-client');
        
        if (!confirmCheck.checked) {
            showToast('Please check the deletion confirmation checkbox first.', 'warning');
            return;
        }
        
        if (confirm(`CRITICAL WARNING: Are you sure you want to permanently delete the profile for client "${name}" and all of their configured reminder schedules?`)) {
            try {
                const res = await fetch(`${API_BASE}/api/clients/${id}`, { method: 'DELETE' });
                if (res.ok) {
                    showToast(`Client "${name}" has been deleted.`, 'success');
                    resetEditClientForm();
                    await loadClientsData();
                    document.querySelector('.tab-btn[data-tab="clients-list"]').click();
                } else {
                    const data = await res.json();
                    showToast(`Failed to delete client: ${data.error}`, 'danger');
                }
            } catch (err) {
                showToast('API Connection error: ' + err.message, 'danger');
            }
        }
    });
}

function resetEditClientForm() {
    const editForm = document.getElementById('form-edit-client');
    editForm.reset();
    document.getElementById('edit-client-id').value = '';
    document.getElementById('select-edit-client').value = '';
    editForm.classList.add('disabled-form');
    editForm.querySelectorAll('input, button').forEach(el => el.disabled = true);
}

async function loadClientsData() {
    try {
        const res = await fetch(`${API_BASE}/api/clients`);
        if (!res.ok) {
            const errData = await res.json().catch(() => ({}));
            throw new Error(errData.error || ('HTTP ' + res.status));
        }
        const data = await res.json();
        if (!Array.isArray(data)) {
            throw new Error(data && data.error ? data.error : 'Invalid response from server');
        }
        globalClients = data;
        
        // 1. Render Table
        const tbody = document.querySelector('#table-clients tbody');
        if (data.length === 0) {
            tbody.innerHTML = '<tr><td colspan="8" class="empty">No client files registered. Go to "Add Client" tab.</td></tr>';
        } else {
            tbody.innerHTML = data.map((c, idx) => `
                <tr>
                    <td>${idx + 1}</td>
                    <td><strong>${c.name}</strong></td>
                    <td><code>${c.email}</code></td>
                    <td>${c.phone || '-'}</td>
                    <td>${c.business_name || '-'}</td>
                    <td>${c.fiscal_year_end ? `<span class="badge badge-info">${c.fiscal_year_end}</span>` : '-'}</td>
                    <td><span class="badge badge-active">${c.reminders_count || 0} active</span></td>
                    <td>
                        <button onclick="openCompanyLookup(${c.id})" class="btn btn-sm btn-primary">🔍 View Reminders</button>
                    </td>
                </tr>
            `).join('');
        }
        
        // 2. Populate Dropdowns
        const editSelect = document.getElementById('select-edit-client');
        if (editSelect) {
            const defaultOption = '<option value="">-- Choose Client --</option>';
            editSelect.innerHTML = defaultOption + data.map(c => `
                <option value="${c.id}">${c.name} (${c.business_name || 'No Business'})</option>
            `).join('');
        }
        
    } catch (err) {
        showToast('Failed to load client profiles: ' + err.message, 'danger');
        const tbody = document.querySelector('#table-clients tbody');
        if (tbody) {
            tbody.innerHTML = `<tr><td colspan="7" class="empty" style="color: #ef4444;">⚠️ Failed to load clients: ${err.message}</td></tr>`;
        }
    }
}

/* -------------------------------------------------------------
   Filing Schedules Controller
   ------------------------------------------------------------- */
function initSchedules() {
    const addForm = document.getElementById('form-add-schedule');
    addForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const payload = {
            client_id: parseInt(document.getElementById('schedule-client').value),
            reminder_type_id: parseInt(document.getElementById('schedule-type').value),
            start_due_date: document.getElementById('schedule-due-date').value,
            frequency: document.getElementById('schedule-frequency').value,
            status: document.getElementById('schedule-status').value
        };
        
        try {
            const res = await fetch(`${API_BASE}/api/schedules`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
            const data = await res.json();
            
            if (res.ok) {
                showToast('Filing reminder schedule successfully configured!');
                addForm.reset();
                await loadSchedulesData();
                document.querySelector('.tab-btn[data-tab="schedules-list"]').click();
            } else {
                showToast(`Failed to save: ${data.error}`, 'danger');
            }
        } catch (err) {
            showToast('API Connection error: ' + err.message, 'danger');
        }
    });
}

async function loadSchedulesData() {
    try {
        // Fetch schedules
        const res = await fetch(`${API_BASE}/api/schedules`);
        if (!res.ok) {
            const errData = await res.json().catch(() => ({}));
            throw new Error(errData.error || ('HTTP ' + res.status));
        }
        const schedules = await res.json();
        if (!Array.isArray(schedules)) {
            throw new Error(schedules && schedules.error ? schedules.error : 'Invalid schedules response');
        }
        
        // Fetch clients & types if not loaded
        if (!Array.isArray(globalClients) || globalClients.length === 0) {
            try {
                const resClients = await fetch(`${API_BASE}/api/clients`);
                if (resClients.ok) {
                    const cData = await resClients.json();
                    if (Array.isArray(cData)) globalClients = cData;
                }
            } catch (_) {}
        }
        
        try {
            const resTypes = await fetch(`${API_BASE}/api/reminder-types`);
            if (resTypes.ok) {
                const tData = await resTypes.json();
                if (Array.isArray(tData)) globalReminderTypes = tData;
            }
        } catch (_) {}
        
        // 1. Populate Dropdowns in Configure Form
        const clientSelect = document.getElementById('schedule-client');
        if (clientSelect) {
            clientSelect.innerHTML = '<option value="">-- Choose Client --</option>' + (globalClients || []).map(c => `
                <option value="${c.id}">${c.name} (${c.business_name || 'No Business'})</option>
            `).join('');
        }
        
        const typeSelect = document.getElementById('schedule-type');
        if (typeSelect) {
            typeSelect.innerHTML = '<option value="">-- Choose Filing Type --</option>' + (globalReminderTypes || []).map(t => `
                <option value="${t.id}">${t.name}</option>
            `).join('');
        }
        
        // 2. Render schedules list table
        const tbody = document.querySelector('#table-schedules tbody');
        if (!tbody) return;
        if (schedules.length === 0) {
            tbody.innerHTML = '<tr><td colspan="9" class="empty">No schedules configured yet. Go to "Configure Schedule" tab.</td></tr>';
        } else {
            tbody.innerHTML = schedules.map((r, idx) => `
                <tr>
                    <td>${idx + 1}</td>
                    <td><strong>${r.client_name || '-'}</strong></td>
                    <td>${r.business_name || '-'}</td>
                    <td>${r.filing_name || '-'}</td>
                    <td><code>${formatDate(r.start_due_date)}</code></td>
                    <td>${r.frequency || 'Annually'}</td>
                    <td><span class="badge badge-pending">${r.pending_count || 0} pending</span></td>
                    <td><span class="badge badge-${(r.status || 'Active').toLowerCase()}">${r.status || 'Active'}</span></td>
                    <td>
                        <div class="btn-group">
                            <button onclick="toggleScheduleStatus(${r.id}, '${r.status === 'Active' ? 'Paused' : 'Active'}')" class="btn btn-sm btn-secondary">
                                ${r.status === 'Active' ? '⏸️ Pause' : '▶️ Resume'}
                            </button>
                            <button onclick="deleteSchedule(${r.id})" class="btn btn-sm btn-danger">🗑️ Delete</button>
                        </div>
                    </td>
                </tr>
            `).join('');
        }
    } catch (err) {
        showToast('Failed to load schedules: ' + err.message, 'danger');
        const tbody = document.querySelector('#table-schedules tbody');
        if (tbody) {
            tbody.innerHTML = `<tr><td colspan="9" class="empty" style="color: #ef4444;">⚠️ Failed to load schedules: ${err.message}</td></tr>`;
        }
    }
}

async function toggleScheduleStatus(id, newStatus) {
    try {
        const res = await fetch(`${API_BASE}/api/schedules/${id}/status`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ status: newStatus })
        });
        if (res.ok) {
            showToast(`Schedule status updated to ${newStatus}.`);
            loadSchedulesData();
        } else {
            const data = await res.json();
            showToast('Failed to update status: ' + data.error, 'danger');
        }
    } catch (err) {
        showToast('Connection error: ' + err.message, 'danger');
    }
}

async function deleteSchedule(id) {
    if (confirm('Are you sure you want to delete this filing reminder schedule? All pending notifications for this schedule will also be deleted.')) {
        try {
            const res = await fetch(`${API_BASE}/api/schedules/${id}`, { method: 'DELETE' });
            if (res.ok) {
                showToast('Reminder schedule deleted successfully.');
                loadSchedulesData();
            } else {
                const data = await res.json();
                showToast('Failed to delete schedule: ' + data.error, 'danger');
            }
        } catch (err) {
            showToast('Connection error: ' + err.message, 'danger');
        }
    }
}

/* -------------------------------------------------------------
   HTML Templates Editor Controller
   ------------------------------------------------------------- */
function initTemplates() {
    const typeSelect = document.getElementById('select-template-type');
    const form = document.getElementById('form-template');
    const subjectInput = document.getElementById('template-subject');
    const bodyTextarea = document.getElementById('template-body');
    
    typeSelect.addEventListener('change', async () => {
        const id = typeSelect.value;
        if (!id) return;
        
        try {
            const res = await fetch(`${API_BASE}/api/templates/${id}`);
            if (res.ok) {
                const data = await res.json();
                subjectInput.value = data.subject;
                bodyTextarea.value = data.body_html;
                
                updateLiveTemplatePreview();
            }
        } catch (err) {
            showToast('Failed to load template: ' + err.message, 'danger');
        }
    });
    
    // Live update preview on text change
    subjectInput.addEventListener('input', updateLiveTemplatePreview);
    bodyTextarea.addEventListener('input', updateLiveTemplatePreview);
    
    // Form submit
    form.addEventListener('submit', async (e) => {
        e.preventDefault();
        const id = typeSelect.value;
        const payload = {
            subject: subjectInput.value,
            body_html: bodyTextarea.value,
            name: `${typeSelect.options[typeSelect.selectedIndex].text} Template`
        };
        
        try {
            const res = await fetch(`${API_BASE}/api/templates/${id}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
            if (res.ok) {
                showToast('Email template saved successfully.');
            } else {
                const data = await res.json();
                showToast('Failed to save template: ' + data.error, 'danger');
            }
        } catch (err) {
            showToast('Connection error: ' + err.message, 'danger');
        }
    });
}

async function loadTemplatesData() {
    try {
        const resTypes = await fetch(`${API_BASE}/api/reminder-types`);
        if (!resTypes.ok) {
            const errData = await resTypes.json().catch(() => ({}));
            throw new Error(errData.error || ('HTTP ' + resTypes.status));
        }
        const types = await resTypes.json();
        if (!Array.isArray(types)) {
            throw new Error(types && types.error ? types.error : 'Invalid reminder types response');
        }
        globalReminderTypes = types;
        
        const typeSelect = document.getElementById('select-template-type');
        if (typeSelect) {
            typeSelect.innerHTML = types.map(t => `
                <option value="${t.id}">${t.name}</option>
            `).join('');
            
            // Trigger select change to load the first template
            if (types.length > 0) {
                typeSelect.dispatchEvent(new Event('change'));
            }
        }
    } catch (err) {
        showToast('Failed to load template types: ' + err.message, 'danger');
    }
}

function updateLiveTemplatePreview() {
    const subject = document.getElementById('template-subject').value;
    const bodyHtml = document.getElementById('template-body').value;
    
    const typeSelect = document.getElementById('select-template-type');
    const filingName = typeSelect.options[typeSelect.selectedIndex] ? typeSelect.options[typeSelect.selectedIndex].text : 'GST/HST Return';
    
    // Choose list based on selection
    let rtCode = 'GST_HST';
    if (filingName.includes('Payroll')) rtCode = 'PAYROLL';
    if (filingName.includes('BC Annual')) rtCode = 'BC_ANNUAL';
    if (filingName.includes('Corporation')) rtCode = 'CORP_TAX_T2';
    
    const listStyle = "margin: 0; padding-left: 20px; text-align: left;";
    let documentList = '';
    if (rtCode === 'GST_HST') {
        documentList = `<ul style="${listStyle}">
            <li>Total gross revenues & sales records</li>
            <li>GST/HST collected on sales</li>
            <li>GST/HST paid on business purchases (ITCs)</li>
            <li>All business expenses bank/credit card statements</li>
        </ul>`;
    } else if (rtCode === 'PAYROLL') {
        documentList = `<ul style="${listStyle}">
            <li>Employee hours worked & wage logs</li>
            <li>Details of any salary/bonus changes</li>
            <li>Information on new hires or terminations</li>
        </ul>`;
    } else if (rtCode === 'BC_ANNUAL') {
        documentList = `<ul style="${listStyle}">
            <li>Confirmation of active director details & home addresses</li>
            <li>Current registered office mailing address</li>
            <li>Notice of corporate shares changes, if any</li>
        </ul>`;
    } else {
        documentList = `<ul style="${listStyle}">
            <li>Corporate financial reports (Balance Sheet & Income Statement)</li>
            <li>Full general ledger & trial balances</li>
            <li>Invoices for capital assets purchased or sold</li>
            <li>Prior year CRA Notice of Assessment</li>
        </ul>`;
    }

    let compiledSubj = subject;
    
    // Parse offset-specific subject lines if the subject text contains newlines
    if (subject.includes('\n') || subject.includes('\r')) {
        const lines = subject.split(/\r?\n/);
        // Default to first line for preview (30-day notice)
        compiledSubj = lines[0].replace(/^([-\d]+):/, '').trim();
    }
    
    const replacements = {
        client_name: 'Jane Doe',
        client_email: 'jane.doe@example.com',
        client_phone: '+1 (555) 019-9988',
        business_name: 'Raman Tax & Accounting LLC',
        due_date: '2026-08-31',
        offset_days: '14',
        send_date: '2026-08-17',
        
        // Double brace versions
        '{{ClientName}}': 'Jane Doe',
        '{{ClientEmail}}': 'jane.doe@example.com',
        '{{ClientPhone}}': '+1 (555) 019-9988',
        '{{BusinessName}}': 'Raman Tax & Accounting LLC',
        '{{DueDate}}': '2026-08-31',
        '{{OffsetDays}}': '14',
        '{{SendDate}}': '2026-08-17',
        
        // Custom fields for the new template design
        '{{logoUrl}}': window.location.origin + '/logo.png',
        '{{whatsappLink}}': 'https://wa.me/16045963388',
        '{{instagramLink}}': 'https://www.instagram.com/ramantaxandaccounting/',
        '{{reminderTitle}}': 'Upcoming Filing Due',
        '{{filingType}}': filingName,
        '{{reportingPeriod}}': 'Q2 (2026)',
        '{{documentList}}': documentList,
        '{{emailSubject}}': encodeURIComponent(compiledSubj)
    };
    
    let compiledBody = bodyHtml;
    
    for (const [key, val] of Object.entries(replacements)) {
        if (key.startsWith('{{')) {
            compiledSubj = compiledSubj.split(key).join(val);
            compiledBody = compiledBody.split(key).join(val);
        } else {
            const placeholder = `{${key}}`;
            compiledSubj = compiledSubj.split(placeholder).join(val);
            compiledBody = compiledBody.split(placeholder).join(val);
        }
    }
    
    const prevSubj = document.querySelector('#preview-subject-bar .val');
    if (prevSubj) prevSubj.innerText = compiledSubj;
    
    const iframe = document.getElementById('preview-iframe');
    const doc = iframe.contentDocument || iframe.contentWindow.document;
    doc.open();
    doc.write(compiledBody);
    doc.close();
}

/* -------------------------------------------------------------
   System Settings Controller
   ------------------------------------------------------------- */
function initSettings() {
    const form = document.getElementById('form-settings');
    form.addEventListener('submit', async (e) => {
        e.preventDefault();
        const payload = {
            api_key: document.getElementById('settings-api-key').value,
            from_email: document.getElementById('settings-from-email').value
        };
        
        try {
            const res = await fetch(`${API_BASE}/api/settings`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
            if (res.ok) {
                showToast('Settings saved successfully.');
                document.getElementById('settings-api-key').value = ''; // clear password input
                loadSettingsData();
            } else {
                const data = await res.json();
                showToast('Failed to save settings: ' + data.error, 'danger');
            }
        } catch (err) {
            showToast('Connection error: ' + err.message, 'danger');
        }
    });

    const testForm = document.getElementById('form-test-email');
    testForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const recipient = document.getElementById('test-recipient').value;
        
        try {
            showToast('Sending test email via Resend... Please wait.', 'info');
            const res = await fetch(`${API_BASE}/api/settings/test`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ test_email: recipient })
            });
            const data = await res.json();
            if (res.ok) {
                showToast(`Test connection successful! Message ID: ${data.messageId}`, 'success');
                showEmailSentModal(recipient, data.messageId);
            } else {
                showToast(`Test email failed: ${data.error}`, 'danger');
            }
        } catch (err) {
            showToast('Connection error: ' + err.message, 'danger');
        }
    });
}

async function loadSettingsData() {
    try {
        const res = await fetch(`${API_BASE}/api/settings`);
        if (!res.ok) throw new Error('HTTP ' + res.status);
        const data = await res.json();
        
        const statusBox = document.getElementById('settings-status-box');
        if (data.configured) {
            statusBox.innerHTML = `
                <div class="status-alert success">
                    🔒 Resend API Connection configured and encrypted.
                </div>
            `;
        } else {
            statusBox.innerHTML = `
                <div class="status-alert warning">
                    ⚠️ Resend API Key is not configured yet. Reminders cannot be dispatched.
                </div>
            `;
        }
        
        document.getElementById('settings-from-email').value = data.from_email || 'beedhtaxservices@gmail.com';
        
    } catch (err) {
        showToast('Failed to load settings data: ' + err.message, 'danger');
    }
}

function showEmailSentModal(recipient, messageId) {
    const elRecip = document.getElementById('modal-recipient');
    if (elRecip) elRecip.innerText = recipient || 'Recipient';
    const elMsg = document.getElementById('modal-msg-id');
    if (elMsg) elMsg.innerText = messageId || 'Sent successfully';
    const modal = document.getElementById('email-confirm-modal');
    if (modal) modal.classList.add('active');
}

function closeEmailSentModal() {
    const modal = document.getElementById('email-confirm-modal');
    if (modal) modal.classList.remove('active');
}

async function sendNotificationNow(id, btnElement, optionalClientId) {
    if (!confirm('Approve and send this reminder now? A BCC copy will also be sent to beedhtaxservices@gmail.com.')) {
        return;
    }

    if (btnElement) {
        btnElement.disabled = true;
        btnElement.innerText = 'Sending...';
    }
    try {
        const res = await fetch(`${API_BASE}/api/notifications/${id}/send`, { method: 'POST' });
        const data = await res.json();
        if (res.ok) {
            showToast('Reminder email successfully dispatched to customer!', 'success');
            showEmailSentModal('Customer Email', data.messageId);
            await loadDashboardData();
            if (optionalClientId) {
                await loadCompanyActivity(optionalClientId);
            } else if (currentLookupClientId) {
                await loadCompanyActivity(currentLookupClientId);
            }
        } else {
            showToast('Failed to send reminder: ' + (data.error || 'Unknown error'), 'danger');
            if (btnElement) {
                btnElement.disabled = false;
                btnElement.innerText = '✉️ Send Now';
            }
        }
    } catch (err) {
        showToast('Connection error: ' + err.message, 'danger');
        if (btnElement) {
            btnElement.disabled = false;
            btnElement.innerText = '✉️ Send Now';
        }
    }
}

let quickSendInitialized = false;
let rawTemplates = {}; // Cache raw database templates by reminder_type_id
let templateRepairInProgress = false;

function initQuickSend() {
    if (quickSendInitialized) return;
    quickSendInitialized = true;
    
    const clientSelect = document.getElementById('quicksend-client');
    const typeSelect = document.getElementById('quicksend-type');
    const dueDateInput = document.getElementById('quicksend-duedate');
    const periodInput = document.getElementById('quicksend-period');
    const subjectInput = document.getElementById('quicksend-subject');
    const bodyTextarea = document.getElementById('quicksend-body');
    const form = document.getElementById('form-quicksend');
    
    // Live update preview on inputs
    clientSelect.addEventListener('change', updateQuickSendPreview);
    typeSelect.addEventListener('change', handleTemplateChange);
    dueDateInput.addEventListener('change', () => {
        // Calculate period based on duedate and selected frequency
        const typeId = typeSelect.value;
        const type = globalReminderTypes.find(t => t.id === parseInt(typeId));
        const freq = type ? (type.code === 'GST_HST' ? 'Quarterly' : (type.code === 'PAYROLL' ? 'Monthly' : 'Annually')) : 'Annually';
        periodInput.value = calculatePeriod(dueDateInput.value, freq);
        updateQuickSendPreview();
    });
    periodInput.addEventListener('input', updateQuickSendPreview);
    subjectInput.addEventListener('input', updateQuickSendPreview);
    bodyTextarea.addEventListener('input', updateQuickSendPreview);
    
    form.addEventListener('submit', handleQuickSendSubmit);
}

async function loadQuickSendData() {
    initQuickSend();
    
    // Populate clients dropdown
    if (globalClients.length === 0) {
        const resClients = await fetch(`${API_BASE}/api/clients`);
        globalClients = await resClients.json();
    }
    const clientSelect = document.getElementById('quicksend-client');
    clientSelect.innerHTML = '<option value="">-- Choose Client --</option>' + globalClients.map(c => `
        <option value="${c.id}">${c.name} (${c.business_name || 'No Business'})</option>
    `).join('');
    
    // Populate template types dropdown
    if (globalReminderTypes.length === 0) {
        const resTypes = await fetch(`${API_BASE}/api/reminder-types`);
        globalReminderTypes = await resTypes.json();
    }
    const typeSelect = document.getElementById('quicksend-type');
    typeSelect.innerHTML = '<option value="">-- Choose Filing Type --</option>' + globalReminderTypes.map(t => `
        <option value="${t.id}">${t.name}</option>
    `).join('');
    
    // Reset fields
    document.getElementById('form-quicksend').reset();
    document.getElementById('quicksend-iframe').contentWindow.document.open();
    document.getElementById('quicksend-iframe').contentWindow.document.write('');
    document.getElementById('quicksend-iframe').contentWindow.document.close();
    const qsSubj = document.querySelector('#quicksend-subject-bar .val');
    if (qsSubj) qsSubj.innerText = '';
}

async function handleTemplateChange() {
    const typeId = document.getElementById('quicksend-type').value;
    if (!typeId) {
        document.getElementById('quicksend-subject').value = '';
        document.getElementById('quicksend-body').value = '';
        updateQuickSendPreview();
        return;
    }
    
    try {
        const res = await fetch(`${API_BASE}/api/templates/${typeId}`);
        if (res.ok) {
            const data = await res.json();
            if (!data.body_html || data.body_html.length < 100 || !data.body_html.includes('<')) {
                throw new Error('The selected template does not contain valid HTML. Open HTML Templates and save the full design again.');
            }
            rawTemplates[typeId] = data;
            
            // Load into fields
            document.getElementById('quicksend-subject').value = data.subject;
            document.getElementById('quicksend-body').value = data.body_html;
            
            // Default due date to today + 30 days
            const d = new Date();
            d.setDate(d.getDate() + 30);
            const y = d.getFullYear();
            const m = String(d.getMonth() + 1).padStart(2, '0');
            const day = String(d.getDate()).padStart(2, '0');
            document.getElementById('quicksend-duedate').value = `${y}-${m}-${day}`;
            
            // Default period based on type
            const type = globalReminderTypes.find(t => t.id === parseInt(typeId));
            const freq = type ? (type.code === 'GST_HST' ? 'Quarterly' : (type.code === 'PAYROLL' ? 'Monthly' : 'Annually')) : 'Annually';
            document.getElementById('quicksend-period').value = calculatePeriod(`${y}-${m}-${day}`, freq);
            
            updateQuickSendPreview();
        }
    } catch (err) {
        showToast('Failed to load template base: ' + err.message, 'danger');
    }
}

function calculatePeriod(dueDateStr, frequency) {
    if (!dueDateStr) return 'Current Period';
    try {
        const [y, m, d] = dueDateStr.split('-').map(Number);
        const date = new Date(y, m - 1, d);
        if (frequency === 'Monthly') {
            date.setMonth(date.getMonth() - 1);
            const months = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];
            return `${months[date.getMonth()]} ${date.getFullYear()}`;
        } else if (frequency === 'Quarterly') {
            const q = Math.floor(date.getMonth() / 3);
            let prevQ = q - 1;
            let prevYear = date.getFullYear();
            if (prevQ < 0) {
                prevQ = 3;
                prevYear -= 1;
            }
            return `Q${prevQ + 1} (${prevYear})`;
        } else if (frequency === 'Annually') {
            return String(date.getFullYear() - 1);
        }
        return `Period Ending ${dueDateStr}`;
    } catch (err) {
        return 'Current Period';
    }
}

function updateQuickSendPreview() {
    const clientId = document.getElementById('quicksend-client').value;
    const typeId = document.getElementById('quicksend-type').value;
    const subject = document.getElementById('quicksend-subject').value;
    const bodyField = document.getElementById('quicksend-body');
    let bodyHtml = bodyField.value;
    const dueDate = document.getElementById('quicksend-duedate').value;
    const period = document.getElementById('quicksend-period').value;

    // Browsers can restore stale textarea text after a refresh. If that happens,
    // replace it with the saved HTML template instead of previewing plain text.
    const bodyLooksLikeHtml = bodyHtml.length >= 100 && bodyHtml.includes('<');
    if (typeId && !bodyLooksLikeHtml) {
        const cachedTemplate = rawTemplates[typeId];
        if (cachedTemplate && cachedTemplate.body_html && cachedTemplate.body_html.length >= 100 && cachedTemplate.body_html.includes('<')) {
            bodyHtml = cachedTemplate.body_html;
            bodyField.value = bodyHtml;
        } else {
            const qsSubj = document.querySelector('#quicksend-subject-bar .val');
            if (qsSubj) qsSubj.innerText = 'Loading saved template...';
            const iframe = document.getElementById('quicksend-iframe');
            const doc = iframe.contentDocument || iframe.contentWindow.document;
            doc.open();
            doc.write('');
            doc.close();

            if (!templateRepairInProgress) {
                templateRepairInProgress = true;
                handleTemplateChange().finally(() => {
                    templateRepairInProgress = false;
                });
            }
            return;
        }
    }
    
    const client = globalClients.find(c => c.id === parseInt(clientId)) || {
        name: 'Client Name',
        email: 'client@example.com',
        phone: '',
        business_name: 'Business Name'
    };
    
    const type = globalReminderTypes.find(t => t.id === parseInt(typeId));
    const filingName = type ? type.name : 'GST/HST Return';
    const rtCode = type ? type.code : 'GST_HST';
    
    // Calculate list style
    const listStyle = "margin: 0; padding-left: 20px; text-align: left;";
    let documentList = '';
    if (rtCode === 'GST_HST') {
        documentList = `<ul style="${listStyle}">
            <li>Total gross revenues & sales records</li>
            <li>GST/HST collected on sales</li>
            <li>GST/HST paid on business purchases (ITCs)</li>
            <li>All business expenses bank/credit card statements</li>
        </ul>`;
    } else if (rtCode === 'PAYROLL') {
        documentList = `<ul style="${listStyle}">
            <li>Employee hours worked & wage logs</li>
            <li>Details of any salary/bonus changes</li>
            <li>Information on new hires or terminations</li>
        </ul>`;
    } else if (rtCode === 'BC_ANNUAL') {
        documentList = `<ul style="${listStyle}">
            <li>Confirmation of active director details & home addresses</li>
            <li>Current registered office mailing address</li>
            <li>Notice of corporate shares changes, if any</li>
        </ul>`;
    } else {
        documentList = `<ul style="${listStyle}">
            <li>Corporate financial reports (Balance Sheet & Income Statement)</li>
            <li>Full general ledger & trial balances</li>
            <li>Invoices for capital assets purchased or sold</li>
            <li>Prior year CRA Notice of Assessment</li>
        </ul>`;
    }

    let compiledSubj = subject;
    if (subject.includes('\n') || subject.includes('\r')) {
        const lines = subject.split(/\r?\n/);
        // Default to first line for preview
        compiledSubj = lines[0].replace(/^([-\d]+):/, '').trim();
    }
    
    const replacements = {
        client_name: client.name,
        client_email: client.email,
        client_phone: client.phone || '',
        business_name: client.business_name || '',
        due_date: dueDate || '2026-08-31',
        offset_days: '30',
        send_date: 'Today',
        
        // Double brace UpperCamelCase versions
        '{{ClientName}}': client.name,
        '{{ClientEmail}}': client.email,
        '{{ClientPhone}}': client.phone || '',
        '{{BusinessName}}': client.business_name || '',
        '{{DueDate}}': dueDate || '2026-08-31',
        '{{OffsetDays}}': '30',
        '{{SendDate}}': 'Today',
        
        // Double brace lowerCamelCase versions (used in COMMON_HTML_TEMPLATE)
        '{{clientName}}': client.name,
        '{{clientEmail}}': client.email,
        '{{clientPhone}}': client.phone || '',
        '{{businessName}}': client.business_name || '',
        '{{dueDate}}': dueDate || '2026-08-31',
        '{{offsetDays}}': '30',
        '{{sendDate}}': 'Today',
        
        // Custom fields
        '{{logoUrl}}': window.location.origin + '/logo.png',
        '{{whatsappLink}}': 'https://wa.me/16045963388',
        '{{instagramLink}}': 'https://www.instagram.com/ramantaxandaccounting/',
        '{{reminderTitle}}': 'Friendly Filing Reminder',
        '{{filingType}}': filingName,
        '{{reportingPeriod}}': period || 'Q2 (2026)',
        '{{documentList}}': documentList,
        '{{emailSubject}}': encodeURIComponent(compiledSubj)
    };
    
    let compiledBody = bodyHtml;
    
    for (const [key, val] of Object.entries(replacements)) {
        if (key.startsWith('{{')) {
            compiledSubj = compiledSubj.split(key).join(val);
            compiledBody = compiledBody.split(key).join(val);
        } else {
            const placeholder = `{${key}}`;
            compiledSubj = compiledSubj.split(placeholder).join(val);
            compiledBody = compiledBody.split(placeholder).join(val);
        }
    }
    
    const qsSubj = document.querySelector('#quicksend-subject-bar .val');
    if (qsSubj) qsSubj.innerText = compiledSubj;
    
    const iframe = document.getElementById('quicksend-iframe');
    const doc = iframe.contentDocument || iframe.contentWindow.document;
    doc.open();
    doc.write(compiledBody);
    doc.close();
}

async function handleQuickSendSubmit(e) {
    e.preventDefault();
    
    const clientId = document.getElementById('quicksend-client').value;
    const client = globalClients.find(c => c.id === parseInt(clientId));
    if (!client) {
        showToast('Please select a client.', 'warning');
        return;
    }
    
    const subject = document.getElementById('quicksend-subject').value;
    const bodyHtml = document.getElementById('quicksend-body').value;
    const dueDate = document.getElementById('quicksend-duedate').value;
    const period = document.getElementById('quicksend-period').value;
    
    // Calculate compiled subject & body to send directly to backend
    const typeId = document.getElementById('quicksend-type').value;
    const type = globalReminderTypes.find(t => t.id === parseInt(typeId));
    const filingName = type ? type.name : 'GST/HST Return';
    const rtCode = type ? type.code : 'GST_HST';
    
    const listStyle = "margin: 0; padding-left: 20px; text-align: left;";
    let documentList = '';
    if (rtCode === 'GST_HST') {
        documentList = `<ul style="${listStyle}">
            <li>Total gross revenues & sales records</li>
            <li>GST/HST collected on sales</li>
            <li>GST/HST paid on business purchases (ITCs)</li>
            <li>All business expenses bank/credit card statements</li>
        </ul>`;
    } else if (rtCode === 'PAYROLL') {
        documentList = `<ul style="${listStyle}">
            <li>Employee hours worked & wage logs</li>
            <li>Details of any salary/bonus changes</li>
            <li>Information on new hires or terminations</li>
        </ul>`;
    } else if (rtCode === 'BC_ANNUAL') {
        documentList = `<ul style="${listStyle}">
            <li>Confirmation of active director details & home addresses</li>
            <li>Current registered office mailing address</li>
            <li>Notice of corporate shares changes, if any</li>
        </ul>`;
    } else {
        documentList = `<ul style="${listStyle}">
            <li>Corporate financial reports (Balance Sheet & Income Statement)</li>
            <li>Full general ledger & trial balances</li>
            <li>Invoices for capital assets purchased or sold</li>
            <li>Prior year CRA Notice of Assessment</li>
        </ul>`;
    }

    let compiledSubj = subject;
    if (subject.includes('\n') || subject.includes('\r')) {
        const lines = subject.split(/\r?\n/);
        compiledSubj = lines[0].replace(/^([-\d]+):/, '').trim();
    }
    
    const replacements = {
        client_name: client.name,
        client_email: client.email,
        client_phone: client.phone || '',
        business_name: client.business_name || '',
        due_date: dueDate || '2026-08-31',
        offset_days: '30',
        send_date: 'Today',
        
        // UpperCamelCase versions
        '{{ClientName}}': client.name,
        '{{ClientEmail}}': client.email,
        '{{ClientPhone}}': client.phone || '',
        '{{BusinessName}}': client.business_name || '',
        '{{DueDate}}': dueDate || '2026-08-31',
        '{{OffsetDays}}': '30',
        '{{SendDate}}': 'Today',
        
        // lowerCamelCase versions (used in COMMON_HTML_TEMPLATE)
        '{{clientName}}': client.name,
        '{{clientEmail}}': client.email,
        '{{clientPhone}}': client.phone || '',
        '{{businessName}}': client.business_name || '',
        '{{dueDate}}': dueDate || '2026-08-31',
        '{{offsetDays}}': '30',
        '{{sendDate}}': 'Today',
        
        '{{logoUrl}}': 'cid:logo', // Server uses cid:logo for real emails
        '{{whatsappLink}}': 'https://wa.me/16045963388',
        '{{instagramLink}}': 'https://www.instagram.com/ramantaxandaccounting/',
        '{{reminderTitle}}': 'Friendly Filing Reminder',
        '{{filingType}}': filingName,
        '{{reportingPeriod}}': period || 'Q2 (2026)',
        '{{documentList}}': documentList,
        '{{emailSubject}}': encodeURIComponent(compiledSubj)
    };
    
    let compiledBody = bodyHtml;
    
    for (const [key, val] of Object.entries(replacements)) {
        if (key.startsWith('{{')) {
            compiledSubj = compiledSubj.split(key).join(val);
            compiledBody = compiledBody.split(key).join(val);
        } else {
            const placeholder = `{${key}}`;
            compiledSubj = compiledSubj.split(placeholder).join(val);
            compiledBody = compiledBody.split(placeholder).join(val);
        }
    }
    
    const btn = document.getElementById('btn-quicksend-submit');
    btn.disabled = true;
    btn.innerText = 'Sending email...';
    
    try {
        const res = await fetch(`${API_BASE}/api/quick-send`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                to_email: client.email,
                subject: compiledSubj,
                body_html: compiledBody
            })
        });
        
        const data = await res.json();
        if (res.ok) {
            showToast(`Custom filing reminder successfully sent to ${client.name}!`, 'success');
            showEmailSentModal(`${client.name} (${client.email})`, data.messageId);
            document.getElementById('form-quicksend').reset();
            document.getElementById('quicksend-iframe').contentWindow.document.open();
            document.getElementById('quicksend-iframe').contentWindow.document.write('');
            document.getElementById('quicksend-iframe').contentWindow.document.close();
            const qsSubj = document.querySelector('#quicksend-subject-bar .val');
            if (qsSubj) qsSubj.innerText = '';
        } else {
            showToast('Failed to send custom email: ' + (data.error || 'Unknown error'), 'danger');
        }
    } catch (err) {
        showToast('Connection error: ' + err.message, 'danger');
    } finally {
        btn.disabled = false;
        btn.innerText = '🚀 Send Email Now';
    }
}


/* -------------------------------------------------------------
   Company Search & Lookup Controller
   ------------------------------------------------------------- */
let currentLookupClientId = null;

function initCompanyLookup() {
    const searchInput = document.getElementById('lookup-search-input');
    const autocompleteList = document.getElementById('lookup-autocomplete-list');
    const clientSelect = document.getElementById('lookup-client-select');

    if (clientSelect) {
        clientSelect.addEventListener('change', () => {
            const clientId = clientSelect.value;
            if (clientId) {
                openCompanyLookup(parseInt(clientId, 10));
            }
        });
    }

    if (searchInput) {
        searchInput.addEventListener('input', () => {
            const query = searchInput.value.trim().toLowerCase();
            if (!query) {
                autocompleteList.style.display = 'none';
                return;
            }

            const matches = globalClients.filter(c => {
                const bName = (c.business_name || '').toLowerCase();
                const cName = (c.name || '').toLowerCase();
                const email = (c.email || '').toLowerCase();
                const bn = (c.business_number || '').toLowerCase();
                return bName.includes(query) || cName.includes(query) || email.includes(query) || bn.includes(query);
            });

            if (matches.length === 0) {
                autocompleteList.innerHTML = '<div style="padding: 12px 16px; color: var(--text-muted); font-size: 0.9rem;">No matching companies or clients found.</div>';
                autocompleteList.style.display = 'block';
            } else {
                autocompleteList.innerHTML = matches.map(c => `
                    <div class="autocomplete-item" data-id="${c.id}">
                        <div>
                            <div class="comp-title">🏢 ${c.business_name || c.name}</div>
                            <div class="comp-sub">👤 ${c.name} &bull; ✉️ ${c.email}</div>
                        </div>
                        <span class="badge badge-info">View Reminders &rarr;</span>
                    </div>
                `).join('');
                autocompleteList.style.display = 'block';

                autocompleteList.querySelectorAll('.autocomplete-item').forEach(item => {
                    item.addEventListener('click', () => {
                        const id = parseInt(item.getAttribute('data-id'), 10);
                        autocompleteList.style.display = 'none';
                        searchInput.value = '';
                        openCompanyLookup(id);
                    });
                });
            }
        });

        document.addEventListener('click', (e) => {
            if (!searchInput.contains(e.target) && !autocompleteList.contains(e.target)) {
                autocompleteList.style.display = 'none';
            }
        });
    }
}

async function loadCompanyLookupData() {
    if (globalClients.length === 0) {
        await loadClientsData();
    }
    
    // Populate select
    const select = document.getElementById('lookup-client-select');
    if (select) {
        select.innerHTML = '<option value="">-- Select Registered Company --</option>' + 
            globalClients.map(c => `<option value="${c.id}" ${currentLookupClientId === c.id ? 'selected' : ''}>${c.business_name || c.name} (Contact: ${c.name})</option>`).join('');
    }

    // Populate quick chips
    const chipsContainer = document.getElementById('lookup-chips-container');
    if (chipsContainer) {
        chipsContainer.innerHTML = '<span style="font-size: 0.8rem; color: var(--text-muted); font-weight: 600;">Quick Pick:</span>' + 
            globalClients.map(c => `
                <span class="company-chip ${currentLookupClientId === c.id ? 'active' : ''}" onclick="openCompanyLookup(${c.id})">
                    🏢 ${c.business_name || c.name}
                </span>
            `).join('');
    }

    // If a company is already selected, refresh its activity
    if (currentLookupClientId) {
        await loadCompanyActivity(currentLookupClientId);
    }
}

async function openCompanyLookup(clientId) {
    currentLookupClientId = clientId;

    // Switch view to company-lookup
    const navBtn = document.querySelector('.nav-btn[data-view="company-lookup"]');
    if (navBtn) {
        document.querySelectorAll('.nav-btn').forEach(b => b.classList.remove('active'));
        document.querySelectorAll('.view-section').forEach(s => s.classList.remove('active'));
        navBtn.classList.add('active');
        document.getElementById('view-company-lookup').classList.add('active');
    }

    // Update chips & select
    document.querySelectorAll('.company-chip').forEach(ch => ch.classList.remove('active'));
    const select = document.getElementById('lookup-client-select');
    if (select) select.value = clientId;

    await loadCompanyActivity(clientId);
}

async function loadCompanyActivity(clientId) {
    try {
        const res = await fetch(`${API_BASE}/api/clients/${clientId}/activity`);
        if (!res.ok) throw new Error('HTTP ' + res.status);
        const data = await res.json();

        const client = data.client;
        document.getElementById('lookup-empty-prompt').style.display = 'none';
        document.getElementById('lookup-company-details').style.display = 'block';

        // Update chips active state
        document.querySelectorAll('.company-chip').forEach(ch => {
            if (ch.textContent.includes(client.business_name || client.name)) {
                ch.classList.add('active');
            } else {
                ch.classList.remove('active');
            }
        });

        // Profile summary card
        document.getElementById('lookup-comp-name').innerText = client.business_name || client.name;
        document.getElementById('lookup-comp-contact').innerText = client.name;
        document.getElementById('lookup-comp-email').innerText = client.email;
        document.getElementById('lookup-comp-phone').innerText = client.phone || '-';
        document.getElementById('lookup-comp-yearend').innerText = client.fiscal_year_end || '-';
        if (client.business_number) {
            document.getElementById('lookup-comp-bn-wrapper').style.display = 'inline';
            document.getElementById('lookup-comp-bn').innerText = client.business_number;
        } else {
            document.getElementById('lookup-comp-bn-wrapper').style.display = 'none';
        }

        // Summary Stat Counter Pills
        document.getElementById('lookup-stat-due').innerText = data.totalDue;
        document.getElementById('lookup-stat-sent').innerText = data.totalSent;
        document.getElementById('lookup-stat-schedules').innerText = data.totalSchedules;

        document.getElementById('lookup-due-badge').innerText = `${data.totalDue} Pending`;
        document.getElementById('lookup-sent-badge').innerText = `${data.totalSent} Dispatched`;

        // 1. Due Reminders Table
        const dueTbody = document.querySelector('#table-lookup-due tbody');
        if (data.due.length === 0) {
            dueTbody.innerHTML = '<tr><td colspan="6" class="empty" style="color: var(--color-success); font-weight: 500;">🎉 No reminders currently due for this company. All filings are up to date!</td></tr>';
        } else {
            dueTbody.innerHTML = data.due.map(n => `
                <tr>
                    <td><strong>${formatDate(n.send_date)}</strong></td>
                    <td><strong>${n.filing_name}</strong></td>
                    <td>${formatDate(n.due_date)}</td>
                    <td><code>${n.offset_days} days</code></td>
                    <td><span class="badge badge-warning">${n.status}</span></td>
                    <td>
                        <button onclick="sendNotificationNow(${n.id}, this, ${clientId})" class="btn btn-sm btn-primary">✉️ Send Now</button>
                    </td>
                </tr>
            `).join('');
        }

        // 2. Sent Reminders (Dispatch History) Table
        const sentTbody = document.querySelector('#table-lookup-sent tbody');
        if (data.history.length === 0) {
            sentTbody.innerHTML = '<tr><td colspan="5" class="empty">No emails dispatched yet to this company.</td></tr>';
        } else {
            sentTbody.innerHTML = data.history.map(h => `
                <tr>
                    <td>${formatDateTime(h.sent_at)}</td>
                    <td><code>${h.recipient}</code></td>
                    <td><strong>${h.subject}</strong></td>
                    <td><span class="badge badge-${h.status.toLowerCase()}">${h.status}</span></td>
                    <td><span class="help">${h.status === 'Sent' ? (h.message_id || 'Sent successfully') : (h.error_details || 'Failed')}</span></td>
                </tr>
            `).join('');
        }

        // 3. Configured Filing Schedules Table
        const schedTbody = document.querySelector('#table-lookup-schedules tbody');
        if (data.schedules.length === 0) {
            schedTbody.innerHTML = '<tr><td colspan="4" class="empty">No recurring filing schedules configured for this company.</td></tr>';
        } else {
            schedTbody.innerHTML = data.schedules.map(s => `
                <tr>
                    <td><strong>${s.filing_name}</strong></td>
                    <td><span class="badge badge-info">${s.frequency}</span></td>
                    <td>${formatDate(s.start_due_date)}</td>
                    <td><span class="badge badge-${(s.status || 'Active').toLowerCase()}">${s.status || 'Active'}</span></td>
                </tr>
            `).join('');
        }

    } catch (err) {
        showToast('Failed to load company activity: ' + err.message, 'danger');
    }
}

/* -------------------------------------------------------------
   Dashboard Quick Filter Controller
   ------------------------------------------------------------- */
function initDashboardSearch() {
    const dashSearchInput = document.getElementById('input-dash-search-company');
    const clearBtn = document.getElementById('btn-dash-clear-search');
    const goLookupBtn = document.getElementById('btn-dash-go-lookup');

    if (!dashSearchInput) return;

    dashSearchInput.addEventListener('input', () => {
        const query = dashSearchInput.value.trim().toLowerCase();
        if (clearBtn) clearBtn.style.display = query ? 'inline-block' : 'none';

        // Filter Upcoming Queue table
        const upcomingRows = document.querySelectorAll('#table-upcoming tbody tr');
        upcomingRows.forEach(row => {
            if (row.classList.contains('empty') || row.classList.contains('loading')) return;
            const text = row.innerText.toLowerCase();
            row.style.display = text.includes(query) ? '' : 'none';
        });

        // Filter History table
        const historyRows = document.querySelectorAll('#table-history tbody tr');
        historyRows.forEach(row => {
            if (row.classList.contains('empty') || row.classList.contains('loading')) return;
            const text = row.innerText.toLowerCase();
            row.style.display = text.includes(query) ? '' : 'none';
        });
    });

    if (clearBtn) {
        clearBtn.addEventListener('click', () => {
            dashSearchInput.value = '';
            clearBtn.style.display = 'none';
            document.querySelectorAll('#table-upcoming tbody tr, #table-history tbody tr').forEach(r => r.style.display = '');
        });
    }

    if (goLookupBtn) {
        goLookupBtn.addEventListener('click', () => {
            const query = dashSearchInput.value.trim().toLowerCase();
            let matchedClient = null;
            if (query && globalClients.length > 0) {
                matchedClient = globalClients.find(c => {
                    return (c.business_name || '').toLowerCase().includes(query) ||
                           (c.name || '').toLowerCase().includes(query);
                });
            }
            if (matchedClient) {
                openCompanyLookup(matchedClient.id);
            } else if (globalClients.length > 0) {
                openCompanyLookup(globalClients[0].id);
            } else {
                document.querySelector('.nav-btn[data-view="company-lookup"]').click();
            }
        });
    }
}
