const crypto = require('crypto');
const fs = require('fs');
const path = require('path');

const KEY_PATH = path.join(__dirname, 'secret.key');

function getEncryptionKey() {
    let key;
    if (!fs.existsSync(KEY_PATH)) {
        key = crypto.randomBytes(32); // 256 bits
        fs.writeFileSync(KEY_PATH, key);
    } else {
        key = fs.readFileSync(KEY_PATH);
    }
    // Hash key with sha256 to guarantee it is exactly 32 bytes
    return crypto.createHash('sha256').update(key).digest();
}

function encryptApiKey(apiKey) {
    if (!apiKey) return '';
    try {
        const key = getEncryptionKey();
        const iv = crypto.randomBytes(16);
        const cipher = crypto.createCipheriv('aes-256-cbc', key, iv);
        let encrypted = cipher.update(apiKey, 'utf8', 'hex');
        encrypted += cipher.final('hex');
        return iv.toString('hex') + ':' + encrypted;
    } catch (err) {
        console.error('Encryption failed:', err);
        return '';
    }
}

function decryptApiKey(encryptedKey) {
    if (!encryptedKey) return '';
    try {
        const parts = encryptedKey.split(':');
        const iv = Buffer.from(parts.shift(), 'hex');
        const encryptedText = Buffer.from(parts.join(':'), 'hex');
        const key = getEncryptionKey();
        const decipher = crypto.createDecipheriv('aes-256-cbc', key, iv);
        let decrypted = decipher.update(encryptedText, 'hex', 'utf8');
        decrypted += decipher.final('utf8');
        return decrypted;
    } catch (err) {
        console.error('Decryption failed:', err);
        return '';
    }
}

async function sendResendEmail(apiKey, fromEmail, toEmail, subject, bodyHtml) {
    const url = 'https://api.resend.com/emails';
    const payload = {
        from: fromEmail,
        to: [toEmail],
        subject: subject,
        html: bodyHtml
    };
    
    // Only add BCC copy if not running in default Resend sandbox onboarding mode,
    // because Resend sandbox mode blocks all dispatches containing non-verified BCC recipients.
    if (!fromEmail.toLowerCase().includes('onboarding@resend.dev')) {
        payload.bcc = ['beedhtaxservices@gmail.com'];
    }
    
    try {
        const response = await fetch(url, {
            method: 'POST',
            headers: {
                'Authorization': `Bearer ${apiKey}`,
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(payload),
            signal: AbortSignal.timeout(15000) // 15s timeout
        });
        
        const responseData = await response.json();
        
        if (response.ok) {
            return { success: true, messageId: responseData.id || 'Sent successfully' };
        } else {
            return { success: false, error: responseData.message || `HTTP ${response.status}` };
        }
    } catch (err) {
        return { success: false, error: err.message || String(err) };
    }
}

function getReportingPeriod(dueDateStr, frequency) {
    if (!dueDateStr) return 'Current Period';
    try {
        const [y, m, d] = dueDateStr.split('-').map(Number);
        const date = new Date(y, m - 1, d);
        
        if (frequency === 'Monthly') {
            // Previous month
            date.setMonth(date.getMonth() - 1);
            const months = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];
            return `${months[date.getMonth()]} ${date.getFullYear()}`;
        } else if (frequency === 'Quarterly') {
            // Previous quarter
            const q = Math.floor(date.getMonth() / 3); // Current quarter (0-3)
            let prevQ = q - 1;
            let prevYear = date.getFullYear();
            if (prevQ < 0) {
                prevQ = 3;
                prevYear -= 1;
            }
            return `Q${prevQ + 1} (${prevYear})`;
        } else if (frequency === 'Annually') {
            // Previous year
            return String(date.getFullYear() - 1);
        } else {
            return `Period Ending ${dueDateStr}`;
        }
    } catch (err) {
        return 'Current Period';
    }
}

function getDocumentList(rtCode) {
    if (rtCode === 'TEST') {
        return `<div style="color: #16a34a; font-weight: 700; line-height: 1.6;">
            ✓ Resend API credentials are valid.<br>
            ✓ Outbound email delivery is operational.<br>
            ✓ SQLite database is active.
        </div>`;
    }
    
    const listStyle = "margin: 0; padding-left: 20px; text-align: left;";
    if (rtCode === 'GST_HST') {
        return `<ul style="${listStyle}">
            <li>Total gross revenues & sales records</li>
            <li>GST/HST collected on sales</li>
            <li>GST/HST paid on business purchases (ITCs)</li>
            <li>All business expenses bank/credit card statements</li>
        </ul>`;
    } else if (rtCode === 'PAYROLL') {
        return `<ul style="${listStyle}">
            <li>Employee hours worked & wage logs</li>
            <li>Details of any salary/bonus changes</li>
            <li>Information on new hires or terminations</li>
        </ul>`;
    } else if (rtCode === 'BC_ANNUAL') {
        return `<ul style="${listStyle}">
            <li>Confirmation of active director details & home addresses</li>
            <li>Current registered office mailing address</li>
            <li>Notice of corporate shares changes, if any</li>
        </ul>`;
    } else {
        return `<ul style="${listStyle}">
            <li>Corporate financial reports (Balance Sheet & Income Statement)</li>
            <li>Full general ledger & trial balances</li>
            <li>Invoices for capital assets purchased or sold</li>
            <li>Prior year CRA Notice of Assessment</li>
        </ul>`;
    }
}

function compileTemplate(subject, bodyHtml, client, notification) {
    const frequency = notification.frequency || 'Annually';
    const due_date = notification.due_date || '';
    const rt_code = notification.reminder_type_code || '';
    const filing_name = notification.filing_name || 'GST/HST Return';
    const offset = parseInt(notification.offset_days || '0', 10);
    
    // Compute title based on offset
    let reminderTitle = 'Filing Reminder';
    if (rt_code === 'TEST') {
        reminderTitle = 'Connection Test Successful';
    } else {
        if (offset === 30) reminderTitle = '30-Day Notification';
        else if (offset === 14) reminderTitle = '2-Week Warning';
        else if (offset === 7) reminderTitle = '1-Week Warning';
        else if (offset === 3) reminderTitle = 'Urgent 3-Day Notice';
        else if (offset === 0) reminderTitle = 'Due Today Notice';
        else if (offset < 0) reminderTitle = 'OVERDUE FILING NOTICE';
    }
    
    const reportingPeriod = getReportingPeriod(due_date, frequency);
    const documentList = getDocumentList(rt_code);
    
    let compiledSubject = subject;
    
    // Parse offset-specific subject lines if the subject text contains newlines
    if (subject.includes('\n') || subject.includes('\r')) {
        const lines = subject.split(/\r?\n/);
        let matchedLine = null;
        for (const line of lines) {
            const match = line.match(/^([-\d]+):(.*)$/);
            if (match) {
                const o = parseInt(match[1], 10);
                if (o === offset) {
                    matchedLine = match[2].trim();
                    break;
                }
            }
        }
        if (matchedLine !== null) {
            compiledSubject = matchedLine;
        } else {
            // Fallback: strip leading offset prefix from the first line
            compiledSubject = lines[0].replace(/^([-\d]+):/, '').trim();
        }
    }
    
    const replacements = {
        client_name: client.name || '',
        client_email: client.email || '',
        client_phone: client.phone || '',
        business_name: client.business_name || '',
        due_date: due_date,
        offset_days: String(offset),
        send_date: notification.send_date || '',
        
        // Support double-brace UpperCamelCase formatting
        '{{ClientName}}': client.name || '',
        '{{ClientEmail}}': client.email || '',
        '{{ClientPhone}}': client.phone || '',
        '{{BusinessName}}': client.business_name || '',
        '{{DueDate}}': due_date,
        '{{OffsetDays}}': String(offset),
        '{{SendDate}}': notification.send_date || '',
        
        // Support double-brace lowerCamelCase formatting (used in COMMON_HTML_TEMPLATE)
        '{{clientName}}': client.name || '',
        '{{clientEmail}}': client.email || '',
        '{{clientPhone}}': client.phone || '',
        '{{businessName}}': client.business_name || '',
        '{{dueDate}}': due_date,
        '{{offsetDays}}': String(offset),
        '{{sendDate}}': notification.send_date || '',
        
        // Custom fields for the new template design
        '{{logoUrl}}': 'cid:logo',
        '{{whatsappLink}}': 'https://wa.me/16045963388',
        '{{instagramLink}}': 'https://www.instagram.com/ramantaxandaccounting/',
        '{{reminderTitle}}': reminderTitle,
        '{{filingType}}': filing_name,
        '{{reportingPeriod}}': reportingPeriod,
        '{{documentList}}': documentList,
        '{{emailSubject}}': encodeURIComponent(compiledSubject)
    };
    
    let compiledBody = bodyHtml;
    
    for (const [key, val] of Object.entries(replacements)) {
        if (key.startsWith('{{')) {
            compiledSubject = compiledSubject.split(key).join(val);
            compiledBody = compiledBody.split(key).join(val);
        } else {
            const placeholder = `{${key}}`;
            compiledSubject = compiledSubject.split(placeholder).join(val);
            compiledBody = compiledBody.split(placeholder).join(val);
        }
    }
    
    return { subject: compiledSubject, bodyHtml: compiledBody };
}

module.exports = {
    encryptApiKey,
    decryptApiKey,
    sendResendEmail,
    compileTemplate
};
