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

function parseYearEndDate(yearEndStr) {
    if (!yearEndStr || typeof yearEndStr !== 'string') return null;
    const str = yearEndStr.trim();
    
    if (/^\d{4}-\d{1,2}-\d{1,2}$/.test(str)) {
        const [y, m, d] = str.split('-').map(Number);
        return new Date(y, m - 1, d);
    }
    
    const monthsMap = {
        'january': 0, 'jan': 0,
        'february': 1, 'feb': 1,
        'march': 2, 'mar': 2,
        'april': 3, 'apr': 3,
        'may': 4,
        'june': 5, 'jun': 5,
        'july': 6, 'jul': 6,
        'august': 7, 'aug': 7,
        'september': 8, 'sep': 8, 'sept': 8,
        'october': 9, 'oct': 9,
        'november': 10, 'nov': 10,
        'december': 11, 'dec': 11
    };
    
    const match = str.match(/([A-Za-z]+)\s*(\d{1,2})?(?:st|nd|rd|th)?,?\s*(\d{4})/i) ||
                  str.match(/(\d{1,2})?\s*([A-Za-z]+),?\s*(\d{4})/i);
    
    if (match) {
        let monthStr, dayNum, yearNum;
        if (isNaN(match[1])) {
            monthStr = match[1].toLowerCase();
            dayNum = match[2] ? parseInt(match[2], 10) : null;
            yearNum = parseInt(match[3], 10);
        } else {
            dayNum = parseInt(match[1], 10);
            monthStr = match[2].toLowerCase();
            yearNum = parseInt(match[3], 10);
        }
        
        const monthIndex = monthsMap[monthStr];
        if (monthIndex !== undefined) {
            const lastDay = new Date(yearNum, monthIndex + 1, 0).getDate();
            const validDay = dayNum ? Math.min(dayNum, lastDay) : lastDay;
            return new Date(yearNum, monthIndex, validDay);
        }
    }

    if (/^\d{4}$/.test(str)) {
        const y = parseInt(str, 10);
        return new Date(y, 11, 31);
    }
    
    const timestamp = Date.parse(str);
    if (!isNaN(timestamp)) {
        return new Date(timestamp);
    }
    return null;
}

function calculateDueDateFromYearEnd(yearEndStr, filingTypeOrCode) {
    const d = parseYearEndDate(yearEndStr);
    if (!d) return null;
    
    const code = (filingTypeOrCode || '').toUpperCase();
    let monthsToAdd = 6; // default 6 months for Corporation Tax T2
    
    if (code.includes('GST') || code.includes('HST')) {
        monthsToAdd = 3;
    } else if (code.includes('BC') || code.includes('ANNUAL')) {
        monthsToAdd = 2;
    } else if (code.includes('T2') || code.includes('CORP') || code.includes('TAX')) {
        monthsToAdd = 6;
    }
    
    const origDay = d.getDate();
    const origMonth = d.getMonth();
    const origYear = d.getFullYear();
    
    const origMonthLastDay = new Date(origYear, origMonth + 1, 0).getDate();
    const isEndOfMonth = origDay >= origMonthLastDay - 2;
    
    const targetDate = new Date(origYear, origMonth + monthsToAdd, 1);
    const lastDayOfTargetMonth = new Date(targetDate.getFullYear(), targetDate.getMonth() + 1, 0).getDate();
    
    const finalDay = isEndOfMonth ? lastDayOfTargetMonth : Math.min(origDay, lastDayOfTargetMonth);
    
    const resultDate = new Date(targetDate.getFullYear(), targetDate.getMonth(), finalDay);
    const y = resultDate.getFullYear();
    const m = String(resultDate.getMonth() + 1).padStart(2, '0');
    const day = String(resultDate.getDate()).padStart(2, '0');
    return `${y}-${m}-${day}`;
}

function getReportingPeriod(dueDateStr, frequency, client = {}, rtCode = '', customYearEnd = '') {
    if (customYearEnd && typeof customYearEnd === 'string' && customYearEnd.trim()) {
        return customYearEnd.trim();
    }
    
    if (!dueDateStr) return 'Current Year End';
    try {
        const [y, m, d] = dueDateStr.split('-').map(Number);
        const date = new Date(y, m - 1, d);
        
        // If it's a Corporation Tax Return (T2) or Annual Filing:
        if (rtCode === 'CORP_TAX_T2' || rtCode.includes('T2') || frequency === 'Annually') {
            if (client && client.fiscal_year_end) {
                const fye = client.fiscal_year_end.trim();
                // If fiscal_year_end already has a year (e.g. "2026-03-31" or "March 31, 2026")
                if (/\d{4}/.test(fye)) {
                    return fye;
                }
                // If fiscal_year_end is like "March 31" or "December 31":
                const fyeMonthMatch = fye.match(/([A-Za-z]+)\s*(\d+)?/);
                if (fyeMonthMatch) {
                    const monthsMap = {
                        'january': 0, 'february': 1, 'march': 2, 'april': 3, 'may': 4, 'june': 5,
                        'july': 6, 'august': 7, 'september': 8, 'october': 9, 'november': 10, 'december': 11
                    };
                    const fyeM = monthsMap[fyeMonthMatch[1].toLowerCase()];
                    if (fyeM !== undefined) {
                        let fyeYear = y;
                        if ((m - 1) < fyeM) {
                            fyeYear = y - 1;
                        }
                        return `${fye}, ${fyeYear}`;
                    }
                }
                return `${fye}, ${y}`;
            }
            
            // Default annual fallback: 6 months before due date for T2
            if (rtCode === 'CORP_TAX_T2' || rtCode.includes('T2')) {
                const fyeDate = new Date(y, m - 1 - 6, d);
                const monthNames = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];
                return `${monthNames[fyeDate.getMonth()]} ${fyeDate.getDate()}, ${fyeDate.getFullYear()}`;
            }
            return String(y);
        } else if (frequency === 'Monthly') {
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
        } else {
            return `Period Ending ${dueDateStr}`;
        }
    } catch (err) {
        return 'Current Year End';
    }
}

function getDocumentList(rtCode) {
    if (rtCode === 'TEST') {
        return `<div style="color: #16a34a; font-weight: 700; line-height: 1.6;">
            ✓ Resend API credentials are valid.<br>
            ✓ Outbound email delivery is operational.<br>
            ✓ Database is active.
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
    } else if (rtCode === 'INSURANCE_POLICY' || rtCode === 'INSURANCE' || rtCode.includes('INSUR')) {
        return `<ul style="${listStyle}">
            <li>Current insurance policy schedule & certificate</li>
            <li>Insurance renewal notice & premium quote</li>
            <li>Details of any updated assets, properties, or vehicles</li>
            <li>Claims history or coverage modification requests</li>
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

function compileTemplate(subject, bodyHtml, client = {}, notification = {}, customYearEnd = '', customDueDate = '') {
    const frequency = notification.frequency || 'Annually';
    const rt_code = notification.reminder_type_code || '';
    const filing_name = notification.filing_name || 'GST/HST Return';
    const offset = parseInt(notification.offset_days || '0', 10);
    const finalYearEnd = customYearEnd || notification.custom_year_end || notification.year_end || (client.fiscal_year_end ? client.fiscal_year_end : '');
    
    // Auto-calculate due date from Year End if custom Year End or custom Due Date is provided
    let due_date = customDueDate || notification.due_date || '';
    if (!customDueDate && finalYearEnd) {
        const computedDue = calculateDueDateFromYearEnd(finalYearEnd, filing_name || rt_code);
        if (computedDue) {
            due_date = computedDue;
        }
    }
    
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
    
    const reportingPeriod = getReportingPeriod(due_date, frequency, client, rt_code, finalYearEnd);
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
        
        // Custom fields for the template design
        '{{logoUrl}}': 'cid:logo',
        '{{whatsappLink}}': 'https://wa.me/16045963388',
        '{{instagramLink}}': 'https://www.instagram.com/ramantaxandaccounting/',
        '{{reminderTitle}}': reminderTitle,
        '{{filingType}}': filing_name,
        '{{reportingPeriod}}': reportingPeriod,
        '{{yearEnd}}': reportingPeriod,
        '{{YearEnd}}': reportingPeriod,
        year_end: reportingPeriod,
        reporting_period: reportingPeriod,
        '{{documentList}}': documentList,
        '{{emailSubject}}': encodeURIComponent(compiledSubject)
    };
    
    // Automatically normalize "Reporting period" in HTML table to "Year end"
    let compiledBody = bodyHtml.replace(/Reporting\s+period/gi, 'Year end');
    
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

    // Ensure any existing raw YYYY-MM-DD date in the compiled subject or due date table cell is updated to due_date
    if (notification.due_date && due_date && notification.due_date !== due_date) {
        compiledSubject = compiledSubject.split(notification.due_date).join(due_date);
        compiledBody = compiledBody.split(notification.due_date).join(due_date);
    }
    
    return { subject: compiledSubject, bodyHtml: compiledBody, yearEnd: reportingPeriod, dueDate: due_date };
}

module.exports = {
    encryptApiKey,
    decryptApiKey,
    sendResendEmail,
    compileTemplate,
    getReportingPeriod,
    calculateDueDateFromYearEnd,
    parseYearEndDate
};

