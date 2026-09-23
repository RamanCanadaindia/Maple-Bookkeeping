const express = require('express');
const cors = require('cors');
const path = require('path');
const { getDb, initDb } = require('./db');
const { encryptApiKey, decryptApiKey, sendResendEmail, compileTemplate } = require('./resendService');
const { runSchedulerCycle, addDays } = require('./scheduler');

const app = express();
const PORT = process.env.PORT || 3000;

app.use(cors());
app.use(express.json());
app.use(express.static(path.join(__dirname, 'public'), {
    setHeaders: (res, filePath) => {
        if (filePath.endsWith('.js') || filePath.endsWith('.html')) {
            res.setHeader('Cache-Control', 'no-store');
        }
    }
}));

// Ensure database is initialized before processing request
app.use(async (req, res, next) => {
    try {
        await initDb();
        next();
    } catch (err) {
        console.error('DB Init Middleware Error:', err);
        next();
    }
});

// Start local server if not running on Vercel
if (!process.env.VERCEL) {
    initDb()
        .then(() => {
            app.listen(PORT, () => {
                console.log(`===================================================`);
                console.log(` Resend Email Reminder System is running locally!`);
                console.log(` URL: http://localhost:${PORT}`);
                console.log(`===================================================`);
            });
        })
        .catch(err => {
            console.error('Failed to initialize database:', err);
        });
}

// API Endpoints

// 1. Dashboard Metrics and Tables
app.get('/api/dashboard', async (req, res) => {
    try {
        const db = await getDb();
        
        const clientCount = (await db.get('SELECT COUNT(*) as count FROM clients')) || { count: 0 };
        const activeCount = (await db.get("SELECT COUNT(*) as count FROM reminders WHERE status = 'Active'")) || { count: 0 };
        const pendingCount = (await db.get("SELECT COUNT(*) as count FROM notifications WHERE status = 'Pending'")) || { count: 0 };
        
        const historyStats = await db.all('SELECT status, COUNT(*) as count FROM email_history GROUP BY status');
        
        let totalLogs = 0;
        let successLogs = 0;
        for (const stat of historyStats) {
            totalLogs += stat.count;
            if (stat.status === 'Sent') {
                successLogs = stat.count;
            }
        }
        const successRate = totalLogs === 0 ? 100 : (successLogs / totalLogs) * 100;

        const upcoming = await db.all(`
            SELECT n.*, c.name as client_name, c.business_name, rt.name as filing_name
            FROM notifications n
            JOIN reminders r ON n.reminder_id = r.id
            JOIN clients c ON r.client_id = c.id
            JOIN reminder_types rt ON r.reminder_type_id = rt.id
            WHERE n.status = 'Pending'
            ORDER BY n.send_date ASC
            LIMIT 30
        `);

        const history = await db.all(`
            SELECT * FROM email_history
            ORDER BY sent_at DESC
            LIMIT 15
        `);

        res.json({
            metrics: {
                totalClients: clientCount.count,
                activeSchedules: activeCount.count,
                pendingNotifications: pendingCount.count,
                successRate: parseFloat(successRate.toFixed(1))
            },
            upcoming,
            history
        });
    } catch (err) {
        res.status(500).json({ error: err.message });
    }
});

// 2. Manual Scheduler Trigger
app.post('/api/scheduler/run', async (req, res) => {
    try {
        const results = await runSchedulerCycle();
        res.json(results);
    } catch (err) {
        res.status(500).json({ error: err.message });
    }
});

// Manual Send Trigger for a Specific Notification
app.post('/api/notifications/:id/send', async (req, res) => {
    const { id } = req.params;
    try {
        const db = await getDb();
        
        // 1. Get settings
        const settings = await db.get('SELECT * FROM settings LIMIT 1');
        if (!settings || !settings.resend_api_key) {
            return res.status(400).json({ error: 'Resend API Key is not configured.' });
        }
        const apiKey = decryptApiKey(settings.resend_api_key);
        const fromEmail = settings.resend_from_email || 'reminders@ramanfinancialservices.ca';
        
        // 2. Fetch notification details
        const notif = await db.get(`
            SELECT n.*, r.reminder_type_id, r.frequency, rt.code as reminder_type_code, rt.name as filing_name,
                   c.name as client_name, c.email as client_email, c.phone as client_phone, c.business_name
            FROM notifications n
            JOIN reminders r ON n.reminder_id = r.id
            JOIN clients c ON r.client_id = c.id
            JOIN reminder_types rt ON r.reminder_type_id = rt.id
            WHERE n.id = ?
        `, [id]);
        
        if (!notif) {
            return res.status(404).json({ error: 'Notification alert not found.' });
        }
        
        // 3. Fetch template
        const template = await db.get('SELECT * FROM email_templates WHERE reminder_type_id = ?', [notif.reminder_type_id]);
        if (!template) {
            return res.status(404).json({ error: `Filing template not configured for type: ${notif.filing_name}` });
        }
        
        // 4. Compile template
        const clientObj = {
            name: notif.client_name,
            email: notif.client_email,
            phone: notif.client_phone,
            business_name: notif.business_name
        };
        const compiled = compileTemplate(template.subject, template.body_html, clientObj, notif);
        
        // 5. Dispatch email via Resend
        const result = await sendResendEmail(apiKey, fromEmail, notif.recipient_email, compiled.subject, compiled.bodyHtml);
        
        const timestamp = new Date().toISOString();
        if (result.success) {
            // Update notification status to Sent
            await db.run('UPDATE notifications SET status = "Sent" WHERE id = ?', [id]);
            // Insert history log
            await db.run(
                'INSERT INTO email_history (notification_id, recipient, subject, sent_at, status, message_id) VALUES (?, ?, ?, ?, "Sent", ?)',
                [id, notif.recipient_email, compiled.subject, timestamp, result.messageId]
            );
            res.json({ success: true, messageId: result.messageId });
        } else {
            // Update notification status to Failed
            await db.run('UPDATE notifications SET status = "Failed", error_message = ? WHERE id = ?', [result.error, id]);
            // Insert history log
            await db.run(
                'INSERT INTO email_history (notification_id, recipient, subject, sent_at, status, error_details) VALUES (?, ?, ?, ?, "Failed", ?)',
                [id, notif.recipient_email, compiled.subject, timestamp, result.error]
            );
            res.status(400).json({ error: result.error });
        }
    } catch (err) {
        res.status(500).json({ error: err.message });
    }
});

// 3. Clear History Logs
app.post('/api/history/clear', async (req, res) => {
    try {
        const db = await getDb();
        await db.run('DELETE FROM email_history');
        res.json({ success: true });
    } catch (err) {
        res.status(500).json({ error: err.message });
    }
});

// 4. Clients CRUD
app.get('/api/clients', async (req, res) => {
    try {
        const db = await getDb();
        const clients = await db.all(`
            SELECT c.*, COUNT(r.id) as reminders_count
            FROM clients c
            LEFT JOIN reminders r ON c.id = r.client_id
            GROUP BY c.id
            ORDER BY c.name ASC
        `);
        res.json(clients);
    } catch (err) {
        res.status(500).json({ error: err.message });
    }
});

// Date Calculation Helpers for Auto-Schedules
function calculateNextAnniversaryDate(anniversaryStr) {
    const months = {
        'January': 0, 'February': 1, 'March': 2, 'April': 3, 'May': 4, 'June': 5,
        'July': 6, 'August': 7, 'September': 8, 'October': 9, 'November': 10, 'December': 11
    };
    const parts = anniversaryStr.split(' ');
    const monthName = parts[0];
    const dayNum = parseInt(parts[1] || '1', 10);
    const monthIndex = months[monthName] !== undefined ? months[monthName] : 0;
    
    const today = new Date();
    let year = today.getFullYear();
    let dueDate = new Date(year, monthIndex, dayNum);
    
    if (dueDate < today) {
        dueDate = new Date(year + 1, monthIndex, dayNum);
    }
    
    const y = dueDate.getFullYear();
    const m = String(dueDate.getMonth() + 1).padStart(2, '0');
    const d = String(dueDate.getDate()).padStart(2, '0');
    return `${y}-${m}-${d}`;
}

function calculateNextT2DueDate(fiscalYearEndStr) {
    const anniversary = calculateNextAnniversaryDate(fiscalYearEndStr);
    const [y, m, d] = anniversary.split('-').map(Number);
    const date = new Date(y, m - 1, d);
    date.setMonth(date.getMonth() + 6);
    
    const expectedMonth = (m - 1 + 6) % 12;
    if (date.getMonth() !== expectedMonth) {
        date.setDate(0);
    }
    
    const finalY = date.getFullYear();
    const finalM = String(date.getMonth() + 1).padStart(2, '0');
    const finalD = String(date.getDate()).padStart(2, '0');
    return `${finalY}-${finalM}-${finalD}`;
}

function calculateGSTHSTDueDate(frequency, fiscalYearEndStr) {
    const today = new Date();
    if (frequency === 'Quarterly') {
        const quarterlyDueDates = [
            { m: 3, d: 30 },
            { m: 6, d: 31 },
            { m: 9, d: 31 },
            { m: 0, d: 31 }
        ];
        
        let bestDate = null;
        for (const item of quarterlyDueDates) {
            let year = today.getFullYear();
            if (item.m === 0 && today.getMonth() >= 10) {
                year += 1;
            }
            const candidate = new Date(year, item.m, item.d);
            if (candidate >= today) {
                if (!bestDate || candidate < bestDate) {
                    bestDate = candidate;
                }
            }
        }
        if (!bestDate) {
            bestDate = new Date(today.getFullYear() + 1, 0, 31);
        }
        const y = bestDate.getFullYear();
        const m = String(bestDate.getMonth() + 1).padStart(2, '0');
        const d = String(bestDate.getDate()).padStart(2, '0');
        return `${y}-${m}-${d}`;
    } else if (frequency === 'Monthly') {
        const nextMonth = new Date(today.getFullYear(), today.getMonth() + 2, 0);
        const y = nextMonth.getFullYear();
        const m = String(nextMonth.getMonth() + 1).padStart(2, '0');
        const d = String(nextMonth.getDate()).padStart(2, '0');
        return `${y}-${m}-${d}`;
    } else {
        if (!fiscalYearEndStr) fiscalYearEndStr = 'December 31';
        const anniversary = calculateNextAnniversaryDate(fiscalYearEndStr);
        const [y, m, d] = anniversary.split('-').map(Number);
        const date = new Date(y, m - 1, d);
        date.setMonth(date.getMonth() + 3);
        
        const expectedMonth = (m - 1 + 3) % 12;
        if (date.getMonth() !== expectedMonth) {
            date.setDate(0);
        }
        const finalY = date.getFullYear();
        const finalM = String(date.getMonth() + 1).padStart(2, '0');
        const finalD = String(date.getDate()).padStart(2, '0');
        return `${finalY}-${finalM}-${finalD}`;
    }
}

function calculatePayrollDueDate() {
    const today = new Date();
    const nextMonth = new Date(today.getFullYear(), today.getMonth() + 1, 15);
    const y = nextMonth.getFullYear();
    const m = String(nextMonth.getMonth() + 1).padStart(2, '0');
    const d = String(nextMonth.getDate()).padStart(2, '0');
    return `${y}-${m}-${d}`;
}

function getSingleReminderOffset(defaultOffsets, fallback = 30) {
    const offsets = String(defaultOffsets || '')
        .split(',')
        .map(value => parseInt(value.trim(), 10))
        .filter(value => !Number.isNaN(value));
    return offsets.length > 0 ? Math.max(...offsets) : fallback;
}

app.post('/api/clients', async (req, res) => {
    const { name, email, phone, business_name, business_number, corporation_number, fiscal_year_end, gst_reporting_period, payroll_frequency, payroll_remitter_type, bc_anniversary_date } = req.body;
    if (!name || !email) {
        return res.status(400).json({ error: 'Name and email are required fields.' });
    }
    try {
        const db = await getDb();
        
        // Format business name to pack BN & Corp num cleanly
        let finalBusinessName = business_name ? business_name.trim() : '';
        const bnVal = business_number ? business_number.trim() : '';
        const corpVal = corporation_number ? corporation_number.trim() : '';
        if (bnVal || corpVal) {
            finalBusinessName += ` [BN: ${bnVal}] [Corp: ${corpVal}]`;
        }

        const result = await db.run(
            `INSERT INTO clients (name, email, phone, business_name, fiscal_year_end) VALUES (?, ?, ?, ?, ?)`,
            [name.trim(), email.trim(), phone ? phone.trim() : null, finalBusinessName, fiscal_year_end ? fiscal_year_end.trim() : null]
        );
        const clientId = result.lastID;

        // Auto-create schedules based on the UI wizard options
        const reminderTypes = await db.all('SELECT id, code, default_offsets FROM reminder_types');

        // 1. GST/HST Schedule
        if (gst_reporting_period && gst_reporting_period !== 'None') {
            const gstType = reminderTypes.find(t => t.code === 'GST_HST' || t.code === 'gst_return' || (t.name && t.name.toLowerCase().includes('gst')));
            if (gstType) {
                const dueDate = calculateGSTHSTDueDate(gst_reporting_period, fiscal_year_end);
                const schedResult = await db.run(
                    `INSERT INTO reminders (client_id, reminder_type_id, start_due_date, frequency, status) VALUES (?, ?, ?, ?, 'Active')`,
                    [clientId, gstType.id, dueDate, gst_reporting_period]
                );
                const reminderId = schedResult.lastID;
                
                // Pre-generate GST/HST notifications
                const offset = getSingleReminderOffset(gstType.default_offsets, 30);
                const sendDate = addDays(dueDate, -offset);
                await db.run(
                    `INSERT INTO notifications (reminder_id, due_date, offset_days, send_date, recipient_email, status) VALUES (?, ?, ?, ?, ?, 'Pending')`,
                    [reminderId, dueDate, offset, sendDate, email.trim()]
                );
            }
        }

        // 2. Payroll Schedule
        if (payroll_frequency && payroll_frequency !== 'None') {
            const payrollType = reminderTypes.find(t => t.code === 'PAYROLL' || t.code === 'payroll_remittance' || (t.name && t.name.toLowerCase().includes('payroll')));
            if (payrollType) {
                const dueDate = calculatePayrollDueDate();
                const schedResult = await db.run(
                    `INSERT INTO reminders (client_id, reminder_type_id, start_due_date, frequency, status) VALUES (?, ?, ?, ?, 'Active')`,
                    [clientId, payrollType.id, dueDate, 'Monthly']
                );
                const reminderId = schedResult.lastID;
                
                // Pre-generate Payroll notifications
                const offset = getSingleReminderOffset(payrollType.default_offsets, 7);
                const sendDate = addDays(dueDate, -offset);
                await db.run(
                    `INSERT INTO notifications (reminder_id, due_date, offset_days, send_date, recipient_email, status) VALUES (?, ?, ?, ?, ?, 'Pending')`,
                    [reminderId, dueDate, offset, sendDate, email.trim()]
                );
            }
        }

        // 3. BC Annual Schedule
        if (bc_anniversary_date && bc_anniversary_date !== 'None') {
            const bcType = reminderTypes.find(t => t.code === 'BC_ANNUAL' || t.code === 'annual_report' || (t.name && t.name.toLowerCase().includes('annual')));
            if (bcType) {
                const dueDate = calculateNextAnniversaryDate(bc_anniversary_date);
                const schedResult = await db.run(
                    `INSERT INTO reminders (client_id, reminder_type_id, start_due_date, frequency, status) VALUES (?, ?, ?, ?, 'Active')`,
                    [clientId, bcType.id, dueDate, 'Annually']
                );
                const reminderId = schedResult.lastID;
                
                // Pre-generate BC Annual notifications
                const offset = getSingleReminderOffset(bcType.default_offsets, 30);
                const sendDate = addDays(dueDate, -offset);
                await db.run(
                    `INSERT INTO notifications (reminder_id, due_date, offset_days, send_date, recipient_email, status) VALUES (?, ?, ?, ?, ?, 'Pending')`,
                    [reminderId, dueDate, offset, sendDate, email.trim()]
                );
            }
        }

        // 4. Corporation Tax (T2) Schedule
        if (fiscal_year_end && fiscal_year_end !== 'None' && fiscal_year_end !== '') {
            const t2Type = reminderTypes.find(t => t.code === 'CORP_TAX_T2' || t.code === 'corporate_tax_filing' || (t.name && t.name.toLowerCase().includes('corporate')));
            if (t2Type) {
                const dueDate = calculateNextT2DueDate(fiscal_year_end);
                const schedResult = await db.run(
                    `INSERT INTO reminders (client_id, reminder_type_id, start_due_date, frequency, status) VALUES (?, ?, ?, ?, 'Active')`,
                    [clientId, t2Type.id, dueDate, 'Annually']
                );
                const reminderId = schedResult.lastID;
                
                // Pre-generate T2 notifications
                const offset = getSingleReminderOffset(t2Type.default_offsets, 60);
                const sendDate = addDays(dueDate, -offset);
                await db.run(
                    `INSERT INTO notifications (reminder_id, due_date, offset_days, send_date, recipient_email, status) VALUES (?, ?, ?, ?, ?, 'Pending')`,
                    [reminderId, dueDate, offset, sendDate, email.trim()]
                );
            }
        }

        res.json({ id: clientId, name, email, phone, business_name: finalBusinessName, fiscal_year_end });
    } catch (err) {
        res.status(500).json({ error: err.message });
    }
});

app.put('/api/clients/:id', async (req, res) => {
    const { id } = req.params;
    const { name, email, phone, business_name, fiscal_year_end } = req.body;
    if (!name || !email) {
        return res.status(400).json({ error: 'Name and email are required fields.' });
    }
    try {
        const db = await getDb();
        await db.run(
            `UPDATE clients SET name = ?, email = ?, phone = ?, business_name = ?, fiscal_year_end = ? WHERE id = ?`,
            [name.trim(), email.trim(), phone ? phone.trim() : null, business_name ? business_name.trim() : null, fiscal_year_end ? fiscal_year_end.trim() : null, id]
        );
        res.json({ success: true });
    } catch (err) {
        res.status(500).json({ error: err.message });
    }
});

app.delete('/api/clients/:id', async (req, res) => {
    const { id } = req.params;
    try {
        const db = await getDb();
        await db.run('DELETE FROM clients WHERE id = ?', [id]);
        res.json({ success: true });
    } catch (err) {
        res.status(500).json({ error: err.message });
    }
});

// 5. Schedules CRUD
app.get('/api/schedules', async (req, res) => {
    try {
        const db = await getDb();
        const schedules = await db.all(`
            SELECT r.*, c.name as client_name, c.business_name, rt.name as filing_name,
                   (SELECT COUNT(*) FROM notifications WHERE reminder_id = r.id AND status = 'Pending') as pending_count
            FROM reminders r
            JOIN clients c ON r.client_id = c.id
            JOIN reminder_types rt ON r.reminder_type_id = rt.id
            ORDER BY c.name ASC
        `);
        res.json(schedules);
    } catch (err) {
        res.status(500).json({ error: err.message });
    }
});

app.post('/api/schedules', async (req, res) => {
    const { client_id, reminder_type_id, start_due_date, frequency, status } = req.body;
    if (!client_id || !reminder_type_id || !start_due_date) {
        return res.status(400).json({ error: 'Client, filing type, and due date are required.' });
    }
    try {
        const db = await getDb();
        
        // Check if schedule already exists
        const existing = await db.get(
            'SELECT id FROM reminders WHERE client_id = ? AND reminder_type_id = ?',
            [client_id, reminder_type_id]
        );
        
        let reminderId;
        if (existing) {
            reminderId = existing.id;
            await db.run(
                `UPDATE reminders SET start_due_date = ?, frequency = ?, status = ? WHERE id = ?`,
                [start_due_date, frequency, status, reminderId]
            );
        } else {
            const result = await db.run(
                `INSERT INTO reminders (client_id, reminder_type_id, start_due_date, frequency, status)
                 VALUES (?, ?, ?, ?, ?)`,
                [client_id, reminder_type_id, start_due_date, frequency, status]
            );
            reminderId = result.lastID;
        }
        
        // Regenerate notifications immediately if active
        if (status === 'Active') {
            const reminder = await db.get(`
                SELECT r.*, c.email as client_email 
                FROM reminders r
                JOIN clients c ON r.client_id = c.id
                WHERE r.id = ?
            `, [reminderId]);
            
            if (reminder) {
                const { default_offsets } = await db.get('SELECT default_offsets FROM reminder_types WHERE id = ?', [reminder_type_id]);
                const offsets = default_offsets.split(',').map(x => parseInt(x.trim(), 10)).filter(x => !isNaN(x));
                
                for (const offset of offsets) {
                    const exists = await db.get(
                        'SELECT id FROM notifications WHERE reminder_id = ? AND due_date = ? AND offset_days = ?',
                        [reminderId, start_due_date, offset]
                    );
                    if (!exists) {
                        const sendDate = addDays(start_due_date, -offset);
                        await db.run(
                            `INSERT INTO notifications (reminder_id, due_date, offset_days, send_date, recipient_email, status)
                             VALUES (?, ?, ?, ?, ?, 'Pending')`,
                            [reminderId, start_due_date, offset, sendDate, reminder.client_email]
                        );
                    }
                }
            }
        }
        
        res.json({ success: true, id: reminderId });
    } catch (err) {
        res.status(500).json({ error: err.message });
    }
});

app.put('/api/schedules/:id/status', async (req, res) => {
    const { id } = req.params;
    const { status } = req.body;
    try {
        const db = await getDb();
        await db.run('UPDATE reminders SET status = ? WHERE id = ?', [status, id]);
        
        if (status === 'Active') {
            const reminder = await db.get(`
                SELECT r.*, c.email as client_email 
                FROM reminders r
                JOIN clients c ON r.client_id = c.id
                WHERE r.id = ?
            `, [id]);
            
            if (reminder) {
                const { default_offsets } = await db.get('SELECT default_offsets FROM reminder_types WHERE id = ?', [reminder.reminder_type_id]);
                const offsets = default_offsets.split(',').map(x => parseInt(x.trim(), 10)).filter(x => !isNaN(x));
                
                for (const offset of offsets) {
                    const exists = await db.get(
                        'SELECT id FROM notifications WHERE reminder_id = ? AND due_date = ? AND offset_days = ?',
                        [id, reminder.start_due_date, offset]
                    );
                    if (!exists) {
                        const sendDate = addDays(reminder.start_due_date, -offset);
                        await db.run(
                            `INSERT INTO notifications (reminder_id, due_date, offset_days, send_date, recipient_email, status)
                             VALUES (?, ?, ?, ?, ?, 'Pending')`,
                            [id, reminder.start_due_date, offset, sendDate, reminder.client_email]
                        );
                    }
                }
            }
        }
        res.json({ success: true });
    } catch (err) {
        res.status(500).json({ error: err.message });
    }
});

app.delete('/api/schedules/:id', async (req, res) => {
    const { id } = req.params;
    try {
        const db = await getDb();
        await db.run('DELETE FROM reminders WHERE id = ?', [id]);
        res.json({ success: true });
    } catch (err) {
        res.status(500).json({ error: err.message });
    }
});

// 6. Reminder Types (for select boxes)
app.get('/api/reminder-types', async (req, res) => {
    try {
        const db = await getDb();
        const types = await db.all('SELECT * FROM reminder_types ORDER BY name ASC');
        res.json(types);
    } catch (err) {
        res.status(500).json({ error: err.message });
    }
});

// 7. Templates API
app.get('/api/templates/:typeId', async (req, res) => {
    const { typeId } = req.params;
    const numTypeId = parseInt(typeId, 10);
    try {
        const db = await getDb();
        let template = await db.get('SELECT * FROM email_templates WHERE reminder_type_id = ?', [numTypeId]);
        if (!template) {
            template = {
                reminder_type_id: numTypeId,
                name: 'Default Template',
                subject: 'Filing Reminder: {business_name}',
                body_html: '<h3>Reminder</h3><p>Filing is due on {due_date}. Days left: {offset_days}</p>'
            };
        }
        res.json(template);
    } catch (err) {
        res.status(500).json({ error: err.message });
    }
});

app.put('/api/templates/:typeId', async (req, res) => {
    const { typeId } = req.params;
    const numTypeId = parseInt(typeId, 10);
    const { subject, body_html, name } = req.body;
    try {
        const db = await getDb();
        const existing = await db.get('SELECT id FROM email_templates WHERE reminder_type_id = ?', [numTypeId]);
        
        if (existing) {
            await db.run(
                'UPDATE email_templates SET subject = ?, body_html = ?, name = ? WHERE reminder_type_id = ?',
                [subject, body_html, name, numTypeId]
            );
        } else {
            await db.run(
                'INSERT INTO email_templates (reminder_type_id, name, subject, body_html) VALUES (?, ?, ?, ?)',
                [numTypeId, name, subject, body_html]
            );
        }
        res.json({ success: true });
    } catch (err) {
        res.status(500).json({ error: err.message });
    }
});

// 8. Settings API
app.get('/api/settings', async (req, res) => {
    try {
        const db = await getDb();
        const settings = await db.get('SELECT * FROM settings LIMIT 1');
        if (!settings) {
            return res.json({ configured: false, from_email: 'reminders@ramanfinancialservices.ca' });
        }
        const hasKey = !!settings.resend_api_key;
        res.json({
            configured: hasKey,
            from_email: settings.resend_from_email
        });
    } catch (err) {
        res.status(500).json({ error: err.message });
    }
});

app.post('/api/settings', async (req, res) => {
    const { api_key, from_email } = req.body;
    try {
        const db = await getDb();
        const settings = await db.get('SELECT id FROM settings LIMIT 1');
        
        let encryptedKey = null;
        if (api_key) {
            encryptedKey = encryptApiKey(api_key.trim());
        }
        
        if (settings) {
            if (encryptedKey !== null) {
                await db.run(
                    'UPDATE settings SET resend_api_key = ?, resend_from_email = ? WHERE id = ?',
                    [encryptedKey, from_email.trim(), settings.id]
                );
            } else {
                await db.run(
                    'UPDATE settings SET resend_from_email = ? WHERE id = ?',
                    [from_email.trim(), settings.id]
                );
            }
        } else {
            await db.run(
                'INSERT INTO settings (resend_api_key, resend_from_email) VALUES (?, ?)',
                [encryptedKey, from_email.trim()]
            );
        }
        res.json({ success: true });
    } catch (err) {
        res.status(500).json({ error: err.message });
    }
});

app.post('/api/settings/test', async (req, res) => {
    const { test_email } = req.body;
    if (!test_email) {
        return res.status(400).json({ error: 'Test recipient email is required.' });
    }
    try {
        const db = await getDb();
        const settings = await db.get('SELECT * FROM settings LIMIT 1');
        if (!settings || !settings.resend_api_key) {
            return res.status(400).json({ error: 'Please configure and save your Resend API Key first.' });
        }
        
        const apiKey = decryptApiKey(settings.resend_api_key);
        const fromEmail = settings.resend_from_email || 'reminders@ramanfinancialservices.ca';
        
        // Fetch any email template from the database to reuse the HTML design layout
        const template = await db.get('SELECT body_html FROM email_templates LIMIT 1');
        
        let bodyHtml;
        const subject = 'Resend Connection Test - Standalone Reminders';
        
        if (template && template.body_html) {
            // Mock connection test data to compile in the HTML design layout
            const mockClient = {
                name: 'Administrator',
                email: test_email,
                business_name: 'Raman Tax & Accounting Inc.'
            };
            const mockNotif = {
                due_date: 'N/A',
                offset_days: 0,
                send_date: 'N/A',
                frequency: 'N/A',
                reminder_type_code: 'TEST',
                filing_name: 'System Connection Test'
            };
            const compiled = compileTemplate(subject, template.body_html, mockClient, mockNotif);
            bodyHtml = compiled.bodyHtml;
        } else {
            bodyHtml = `
                <div style="font-family: Arial, sans-serif; padding: 20px;">
                    <h3>Connection Successful!</h3>
                    <p>Your Node.js standalone client reminder system has successfully connected to the Resend API.</p>
                    <p>Credentials validated.</p>
                </div>
            `;
        }
        
        const response = await sendResendEmail(apiKey, fromEmail, test_email.trim(), subject, bodyHtml);
        if (response.success) {
            res.json({ success: true, messageId: response.messageId });
        } else {
            res.status(400).json({ error: response.error });
        }
    } catch (err) {
        res.status(500).json({ error: err.message });
    }
});

// 9. Quick Send API
app.post('/api/quick-send', async (req, res) => {
    const { to_email, subject, body_html } = req.body;
    if (!to_email || !subject || !body_html) {
        return res.status(400).json({ error: 'Recipient email, subject, and body HTML are required.' });
    }
    try {
        const db = await getDb();
        const settings = await db.get('SELECT * FROM settings LIMIT 1');
        if (!settings || !settings.resend_api_key) {
            return res.status(400).json({ error: 'Please configure and save your Resend API Key first.' });
        }
        
        const apiKey = decryptApiKey(settings.resend_api_key);
        const fromEmail = settings.resend_from_email || 'reminders@ramanfinancialservices.ca';
        
        const response = await sendResendEmail(apiKey, fromEmail, to_email.trim(), subject.trim(), body_html);
        const timestamp = new Date().toISOString();
        if (response.success) {
            await db.run(
                'INSERT INTO email_history (notification_id, recipient, subject, sent_at, status, message_id) VALUES (NULL, ?, ?, ?, "Sent", ?)',
                [to_email.trim(), subject.trim(), timestamp, response.messageId]
            );
            res.json({ success: true, messageId: response.messageId });
        } else {
            await db.run(
                'INSERT INTO email_history (notification_id, recipient, subject, sent_at, status, error_details) VALUES (NULL, ?, ?, ?, "Failed", ?)',
                [to_email.trim(), subject.trim(), timestamp, response.error]
            );
            res.status(400).json({ error: response.error });
        }
    } catch (err) {
        res.status(500).json({ error: err.message });
    }
});

module.exports = app;
