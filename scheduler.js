const { getDb } = require('./db');
const { decryptApiKey, sendResendEmail, compileTemplate } = require('./resendService');

// First-year safety mode: prepare reminders but require manual approval to send.
// Set APPROVAL_ONLY_MODE=false later to restore automatic dispatch.
const APPROVAL_ONLY_MODE = process.env.APPROVAL_ONLY_MODE !== 'false';

function parseDate(dateStr) {
    const [y, m, d] = dateStr.split('-').map(Number);
    return new Date(y, m - 1, d);
}

function formatDate(dateObj) {
    const y = dateObj.getFullYear();
    const m = String(dateObj.getMonth() + 1).padStart(2, '0');
    const d = String(dateObj.getDate()).padStart(2, '0');
    return `${y}-${m}-${d}`;
}

function addMonths(dateStr, months) {
    const d = parseDate(dateStr);
    const expectedMonth = (d.getMonth() + months) % 12;
    d.setMonth(d.getMonth() + months);
    // Handle month-end overflow (e.g. Jan 31 + 1 month -> Feb 28/29, not March 3)
    if (d.getMonth() !== (expectedMonth < 0 ? expectedMonth + 12 : expectedMonth)) {
        d.setDate(0);
    }
    return formatDate(d);
}

function addDays(dateStr, days) {
    const d = parseDate(dateStr);
    d.setDate(d.getDate() + days);
    return formatDate(d);
}

function calculateNextDueDate(currentDue, frequency) {
    if (frequency === 'Monthly') {
        return addMonths(currentDue, 1);
    } else if (frequency === 'Quarterly') {
        return addMonths(currentDue, 3);
    } else if (frequency === 'Annually') {
        return addMonths(currentDue, 12);
    } else {
        return addDays(currentDue, 30); // Custom fallback
    }
}

async function generateNotifications(db, reminder) {
    if (reminder.status !== 'Active') return 0;
    
    // Fetch reminder type for offsets
    const type = await db.get('SELECT * FROM reminder_types WHERE id = ?', [reminder.reminder_type_id]);
    if (!type) return 0;
    
    const offsets = type.default_offsets.split(',')
        .map(x => parseInt(x.trim(), 10))
        .filter(x => !isNaN(x));
        
    let generatedCount = 0;
    
    for (const offset of offsets) {
        // Check if already exists
        const exists = await db.get(
            `SELECT id FROM notifications 
             WHERE reminder_id = ? AND due_date = ? AND offset_days = ?`,
            [reminder.id, reminder.start_due_date, offset]
        );
        
        if (!exists) {
            const sendDate = addDays(reminder.start_due_date, -offset);
            await db.run(
                `INSERT INTO notifications (reminder_id, due_date, offset_days, send_date, recipient_email, status)
                 VALUES (?, ?, ?, ?, ?, 'Pending')`,
                [reminder.id, reminder.start_due_date, offset, sendDate, reminder.client_email]
            );
            generatedCount++;
        }
    }
    
    return generatedCount;
}

async function rolloverReminderDueDate(db, reminder, todayStr) {
    // Find notifications for this reminder and due date
    const notifications = await db.all(
        'SELECT status FROM notifications WHERE reminder_id = ? AND due_date = ?',
        [reminder.id, reminder.start_due_date]
    );
    
    if (notifications.length === 0) {
        return false; // Not generated yet, let generator handle it
    }
    
    // Check if any is pending
    const anyPending = notifications.some(n => n.status === 'Pending');
    
    // Rollover if all are sent/failed AND today >= due date
    if (!anyPending && todayStr >= reminder.start_due_date) {
        const nextDue = calculateNextDueDate(reminder.start_due_date, reminder.frequency);
        await db.run(
            'UPDATE reminders SET start_due_date = ? WHERE id = ?',
            [nextDue, reminder.id]
        );
        reminder.start_due_date = nextDue; // Update reference
        return true;
    }
    
    return false;
}

async function runSchedulerCycle() {
    const db = await getDb();
    const todayStr = formatDate(new Date());
    
    const results = {
        rollovers: 0,
        notifications_generated: 0,
        sent_success: 0,
        sent_failed: 0,
        errors: []
    };
    
    try {
        // 1. Fetch active reminders with client email join
        const activeReminders = await db.all(`
            SELECT r.*, c.email as client_email 
            FROM reminders r
            JOIN clients c ON r.client_id = c.id
            WHERE r.status = 'Active'
        `);
        
        // Process rollovers and generation
        for (const reminder of activeReminders) {
            try {
                const rolled = await rolloverReminderDueDate(db, reminder, todayStr);
                if (rolled) {
                    results.rollovers++;
                }
                
                const generated = await generateNotifications(db, reminder);
                results.notifications_generated += generated;
            } catch (err) {
                results.errors.push(`Error updating reminder ID ${reminder.id}: ${err.message}`);
            }
        }

        if (APPROVAL_ONLY_MODE) {
            results.approval_only = true;
            return results;
        }
        
        // 2. Load settings
        const settings = await db.get('SELECT * FROM settings LIMIT 1');
        if (!settings || !settings.resend_api_key) {
            results.errors.push('Resend API Key is not configured. Email dispatch skipped.');
            return results;
        }
        
        const apiKey = decryptApiKey(settings.resend_api_key);
        const fromEmail = settings.resend_from_email || 'beedhtaxservices@gmail.com';
        
        if (!apiKey) {
            results.errors.push('Could not decrypt Resend API key.');
            return results;
        }
        
        // 3. Query due pending notifications
        const pendingNotifications = await db.all(`
            SELECT n.*, r.reminder_type_id, r.frequency, rt.code as reminder_type_code, rt.name as filing_name,
                   c.name as client_name, c.email as client_email, c.phone as client_phone, c.business_name
            FROM notifications n
            JOIN reminders r ON n.reminder_id = r.id
            JOIN clients c ON r.client_id = c.id
            JOIN reminder_types rt ON r.reminder_type_id = rt.id
            WHERE n.status = 'Pending' AND n.send_date <= ?
        `, [todayStr]);
        
        for (const notif of pendingNotifications) {
            try {
                // Find template
                const template = await db.get(
                    'SELECT * FROM email_templates WHERE reminder_type_id = ?',
                    [notif.reminder_type_id]
                );
                
                let subject, bodyHtml;
                if (!template) {
                    subject = `Notice: Filing due for ${notif.business_name || notif.client_name}`;
                    bodyHtml = `<p>Filing is due on ${notif.due_date}. Days left: ${notif.offset_days}</p>`;
                } else {
                    const compiled = compileTemplate(template.subject, template.body_html, notif, notif);
                    subject = compiled.subject;
                    bodyHtml = compiled.bodyHtml;
                }
                
                const response = await sendResendEmail(apiKey, fromEmail, notif.recipient_email, subject, bodyHtml);
                
                const sentAt = new Date().toISOString();
                
                if (response.success) {
                    await db.run(
                        `UPDATE notifications SET status = 'Sent', error_message = NULL WHERE id = ?`,
                        [notif.id]
                    );
                    await db.run(
                        `INSERT INTO email_history (notification_id, recipient, subject, sent_at, status, message_id)
                         VALUES (?, ?, ?, ?, 'Sent', ?)`,
                        [notif.id, notif.recipient_email, subject, sentAt, response.messageId]
                    );
                    results.sent_success++;
                } else {
                    await db.run(
                        `UPDATE notifications SET status = 'Failed', error_message = ? WHERE id = ?`,
                        [response.error, notif.id]
                    );
                    await db.run(
                        `INSERT INTO email_history (notification_id, recipient, subject, sent_at, status, error_details)
                         VALUES (?, ?, ?, ?, 'Failed', ?)`,
                        [notif.id, notif.recipient_email, subject, sentAt, response.error]
                    );
                    results.sent_failed++;
                }
            } catch (err) {
                await db.run(
                    `UPDATE notifications SET status = 'Failed', error_message = ? WHERE id = ?`,
                    [err.message, notif.id]
                );
                results.sent_failed++;
                results.errors.push(`Dispatch error on notification ID ${notif.id}: ${err.message}`);
            }
        }
    } catch (err) {
        results.errors.push(`Scheduler loop error: ${err.message}`);
    }
    
    return results;
}

module.exports = {
    runSchedulerCycle,
    formatDate,
    parseDate,
    addDays,
    addMonths
};
