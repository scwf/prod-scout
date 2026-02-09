---
name: send-email
description: Send emails and notifications via SMTP with optional file attachments. Supports sharing reports and briefs. Trigger phrases: "Send email", "Share report", "Notify via email", "发送邮件", "邮件通知", "分享报告".
---

# Send Email

## Overview
 
 Send emails via SMTP with configuration managed in `skills/send-email/config.ini`. **Users do not need to provide email configuration details** in the chat, but they must ensure the `[email]` section is configured in the skill's `config.ini` file.
 
 **IMPORTANT**: If the user specifies an HTML file (e.g. "send report.html"), **read the HTML file content and send it as the email body**. Do NOT send the HTML file as an attachment unless the user explicitly asks to "attach" the file.
 
 ## Configuration
 
 The email settings are read from `skills/send-email/config.ini`.
 
 **Example `config.ini` section:**
 ```ini
 [email]
 smtp_server = smtp.gmail.com
 smtp_port = 465
 smtp_username = your_email@gmail.com
 smtp_password = your_app_password
 email_from = your_email@gmail.com
 email_to = recipient1@example.com, recipient2@example.com
 email_cc = 
 email_bcc = 
 ```
 
 Users do NOT need to provide these values in the prompt. Simply invoke the skill with the email content.

## How to Invoke

### Natural Language Triggers
 
 Invoke this skill when the user says things like:
 - "Send an email about X"
 - "Email the report..."
 - "Send notification..."
 - "Email someone about Y"
 - "Send this [file/report] via email"
 - "Forward this as an email"
 - "Email the strategic brief..."
 
### Parameters to Extract
 
 Extract the following information from the user's request and context:
 
 - **Subject**: A brief, clear summary (1-15 words).
 - **Body**: The email content. Can be:
     - Plain text string
     - HTML string
     - **Absolute path to a Markdown (.md) or HTML (.html) file**. passing a file path is highly recommended for reports.
 - **Optional**: 
     - Attachments (list of file paths)
     - CC/BCC recipients
     - HTML flag (auto-set if body is a file path with .md/.html extension)
 

### Execution

Run the email sending script directly via command line.

**⚠️ Windows Encoding Warning**: To avoid encoding issues with Chinese characters in PowerShell/CMD, **ALWAYS use file arguments** (`--subject-file`, `--body-file`) instead of passing strings directly.

**Recommended: Send Markdown Report**
This is the most robust way to send complex reports. The script automatically converts Markdown to styled HTML.

```bash
python skills/send-email/scripts/send_email.py --subject-file "d:\path\to\subject.txt" --body-file "d:\path\to\brief.md"
```

**Alternative: Simple Email**
For simple notifications without attachments.

```bash
python skills/send-email/scripts/send_email.py "Meeting Reminder" "Reminder: Meeting tomorrow at 10:00 AM"
```

**Arguments:**
- `subject` - Email subject (positional, optional if using --subject-file)
- `body` - Email body (positional, optional if using --body-file)
- `--subject-file` - Read subject from UTF-8 file (Required for Chinese)
- `--body-file` - Read body from UTF-8 file OR **Markdown file** (.md).
- `--html` - Send as HTML formatted email (auto-set if body is Markdown)
- `--cc` - Add CC recipients
- `--bcc` - Add BCC recipients
- `--attach` - Attach files (e.g. `python ... --attach report.pdf image.png`)


## Error Handling

Report exact error messages to user for diagnosis:
- **Missing configuration**: Required field not configured
- **Authentication failed**: Username/password or app password issue
- **Connection error**: SMTP server down or port blocked
- **File not found**: Attachment file does not exist
- **Markdown conversion error**: Fallback to plain text if conversion fails
- **SMTP errors**: Generic SMTP exception with details

## Resources

### scripts/send_email.py

Main email sending script with pre-configured SMTP settings and **built-in Markdown to HTML conversion**.

**Key features:**
- Pre-configured Gmail SMTP credentials
- **Auto-conversion of Markdown (.md) files to Premium HTML templates**
- Support for plain text and HTML emails
- CC/BCC recipient support
- File attachment support
- Comprehensive error handling

### scripts/convert_brief.py

Helper module handling the Markdown to HTML transformation with a professional CSS theme.


