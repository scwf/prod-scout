#!/usr/bin/env python3
"""
Email Sender Script
Sends emails (text/HTML) with optional attachments via SMTP.
Configuration: skills/send-email/config.ini
"""

import os
import sys
import smtplib
import configparser
import argparse
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
from email.header import Header
from typing import Optional, List

# Default fallback config (empty, relies on config.ini)
DEFAULT_CONFIG = {
    "SMTP_SERVER": "",
    "SMTP_PORT": "",
    "SMTP_USERNAME": "",
    "SMTP_PASSWORD": "",
    "EMAIL_TO": "",
    "EMAIL_CC": "",
    "EMAIL_BCC": "",
    "EMAIL_FROM": "",
}

def get_config() -> dict:
    """Load config from ../config.ini > Environment > Defaults."""
    config = DEFAULT_CONFIG.copy()
    
    # 1. Load from file
    script_dir = os.path.dirname(os.path.abspath(__file__))
    config_path = os.path.join(script_dir, "..", "config.ini")
    
    if os.path.exists(config_path):
        try:
            parser = configparser.ConfigParser()
            parser.read(config_path, encoding='utf-8')
            if 'email' in parser:
                for key in config.keys():
                    val = parser['email'].get(key.lower(), '')
                    if val: config[key] = val
        except Exception as e:
            print(f"Warning: Config load failed: {e}")

    # 2. Load from Env (Override)
    for key in config.keys():
        env_val = os.environ.get(key)
        if env_val: config[key] = env_val
        
    return config

def send_email(subject: str, body: str, html: bool = False, 
               cc: List[str] = None, bcc: List[str] = None, 
               attachments: List[str] = None) -> tuple[bool, str]:
    config = get_config()
    
    # Validate
    if not all([config.get("SMTP_SERVER"), config.get("SMTP_USERNAME"), config.get("SMTP_PASSWORD"), config.get("EMAIL_TO")]):
        return False, "Missing required SMTP configuration in config.ini or environment variables"

    # Recipients
    to_list = [e.strip() for e in config["EMAIL_TO"].split(",") if e.strip()]
    cc_list = cc or [e.strip() for e in config.get("EMAIL_CC", "").split(",") if e.strip()]
    bcc_list = bcc or [e.strip() for e in config.get("EMAIL_BCC", "").split(",") if e.strip()]
    
    sender = config.get("EMAIL_FROM") or config["SMTP_USERNAME"]
    all_recipients = list(set(to_list + cc_list + bcc_list))

    try:
        msg = MIMEMultipart("mixed") if attachments else MIMEMultipart("alternative")
        msg["Subject"] = Header(subject, "utf-8")
        msg["From"] = sender
        msg["To"] = ", ".join(to_list)
        if cc_list: msg["Cc"] = ", ".join(cc_list)


        # Body
        content_part = MIMEText(body, "html" if html else "plain", "utf-8")
        if attachments:
            alt = MIMEMultipart("alternative")
            alt.attach(content_part)
            msg.attach(alt)
        else:
            msg.attach(content_part)

        # Attachments
        if attachments:
            for fpath in attachments:
                if not os.path.exists(fpath): return False, f"File not found: {fpath}"
                with open(fpath, "rb") as f:
                    part = MIMEApplication(f.read(), Name=os.path.basename(fpath))
                part["Content-Disposition"] = f'attachment; filename="{os.path.basename(fpath)}"'
                msg.attach(part)

        # Send
        port = int(config["SMTP_PORT"])
        server_cls = smtplib.SMTP_SSL if port == 465 else smtplib.SMTP
        
        with server_cls(config["SMTP_SERVER"], port, timeout=15) as server:
            if port != 465: server.starttls()
            server.login(config["SMTP_USERNAME"], config["SMTP_PASSWORD"])
            server.send_message(msg, to_addrs=all_recipients)
            
        return True, f"Sent to {len(all_recipients)} recipients"

    except Exception as e:
        return False, str(e)

def main():
    parser = argparse.ArgumentParser(description="Send Email Tool")
    parser.add_argument("subject", nargs="?", help="Subject")
    parser.add_argument("body", nargs="?", help="Body text")
    parser.add_argument("--subject-file", help="File containing subject")
    parser.add_argument("--body-file", help="File containing body (supports .md)")
    parser.add_argument("--html", action="store_true", help="Send as HTML")
    parser.add_argument("--cc", nargs="*", help="CC list")
    parser.add_argument("--bcc", nargs="*", help="BCC list")
    parser.add_argument("--attach", nargs="+", help="Attachment paths")
    args = parser.parse_args()

    # Load Content
    subject = args.subject
    if args.subject_file and os.path.exists(args.subject_file):
        with open(args.subject_file, 'r', encoding='utf-8') as f:
            subject = f.read().strip()
            
    body = args.body
    html_mode = args.html
    
    if args.body_file and os.path.exists(args.body_file):
        # Markdown Conversion Logic
        if args.body_file.lower().endswith('.md'):
            try:
                # Ensure local import works
                sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
                from convert_brief import convert_file
                print(f"Converting Markdown: {args.body_file}")
                body = convert_file(args.body_file)
                html_mode = True
            except Exception as e:
                print(f"MD Conversion failed: {e}, sending raw text")
                with open(args.body_file, 'r', encoding='utf-8') as f: body = f.read()
        else:
            with open(args.body_file, 'r', encoding='utf-8') as f: body = f.read()

    if not subject or not body:
        print("Error: Subject and Body are required.")
        sys.exit(1)

    success, msg = send_email(subject, body, html_mode, args.cc, args.bcc, args.attach)
    if success:
        print(f"SUCCESS: {msg}")
    else:
        print(f"ERROR: {msg}")
        sys.exit(1)

if __name__ == "__main__":
    main()
