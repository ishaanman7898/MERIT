"""
MERIT — Gradio interface
Use this if Streamlit is blocked on your school or work network.
Run locally:  python gradio_app.py
Deploy on Hugging Face Spaces: upload this file + requirements_gradio.txt
"""

import json
import smtplib
import time
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

import gradio as gr

CONFIG_FILE = Path("config.json")

# ── Config helpers ────────────────────────────────────────────────────────────

def load_config() -> dict:
    try:
        if CONFIG_FILE.exists():
            return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def save_config(cfg: dict) -> None:
    CONFIG_FILE.write_text(
        json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8"
    )


# ── Campaign HTML default ─────────────────────────────────────────────────────

_DEFAULT_CAMPAIGN_HTML = """\
<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#f5f5f5;font-family:Arial,Helvetica,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0">
    <tr><td align="center" style="padding:32px 16px;">
      <table width="560" cellpadding="0" cellspacing="0"
             style="background:#fff;border-radius:10px;overflow:hidden;
                    box-shadow:0 2px 12px rgba(0,0,0,.08);max-width:100%;">
        <tr>
          <td style="background:#18181b;padding:28px 36px;">
            <p style="margin:0;font-size:20px;font-weight:700;color:#fff;">{{from_name}}</p>
          </td>
        </tr>
        <tr>
          <td style="padding:32px 36px;">
            <p style="margin:0 0 12px;font-size:16px;color:#111;">Hi {{name}},</p>
            <p style="margin:0 0 24px;font-size:14px;color:#555;line-height:1.6;">
              Write your campaign message here. Replace this paragraph with your content.
            </p>
          </td>
        </tr>
        <tr>
          <td style="background:#fafafa;padding:16px 36px;border-top:1px solid #ebebeb;">
            <p style="margin:0;font-size:12px;color:#bbb;">Sent by {{from_name}}</p>
          </td>
        </tr>
      </table>
    </td></tr>
  </table>
</body>
</html>"""


# ── Contact parser ─────────────────────────────────────────────────────────────

def _parse_contacts(raw: str) -> list[dict]:
    contacts = []
    for line in raw.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        if "," in line:
            parts = line.split(",", 1)
            name  = parts[0].strip()
            email = parts[1].strip()
        else:
            name  = line.split("@")[0].strip()
            email = line.strip()
        if "@" in email and "." in email.split("@")[-1]:
            contacts.append({"name": name, "email": email})
    return contacts


# ── Settings functions ────────────────────────────────────────────────────────

def save_settings(from_name, subject, smtp_email, smtp_password, sb_conn_str, sb_db_pass,
                  freeimage_key, imghippo_key):
    cfg = load_config()
    cfg.update({
        "from_name":                    from_name.strip(),
        "subject":                      subject.strip(),
        "smtp_email":                   smtp_email.strip(),
        "smtp_password":                smtp_password.replace(" ", ""),
        "supabase_connection_string":   sb_conn_str.strip(),
        "supabase_db_password":         sb_db_pass.strip(),
        "freeimage_api_key":            freeimage_key.strip(),
        "imghippo_api_key":             imghippo_key.strip(),
        "privacy_acknowledged":         "1",
    })
    save_config(cfg)
    return "Settings saved to config.json."


def load_settings_values():
    cfg = load_config()
    return (
        cfg.get("from_name", ""),
        cfg.get("subject", "Your order is here"),
        cfg.get("smtp_email", ""),
        cfg.get("smtp_password", ""),
        cfg.get("supabase_connection_string", ""),
        cfg.get("supabase_db_password", ""),
        cfg.get("freeimage_api_key", ""),
        cfg.get("imghippo_api_key", ""),
    )


def test_smtp(smtp_email, smtp_password):
    email = smtp_email.strip()
    password = smtp_password.replace(" ", "")
    if not email or not password:
        return "Enter Gmail address and app password first."
    try:
        server = smtplib.SMTP("smtp.gmail.com", 587, timeout=10)
        server.starttls()
        server.login(email, password)
        server.quit()
        return "Gmail connection successful."
    except Exception as e:
        return f"Connection failed: {e}"


# ── Products functions ────────────────────────────────────────────────────────

def load_products():
    cfg = load_config()
    conn_str = cfg.get("supabase_connection_string", "").strip()
    if not conn_str:
        return None, "No Supabase connection string configured. Go to Settings."
    try:
        import pandas as pd
        import psycopg2
        conn = psycopg2.connect(conn_str, connect_timeout=10)
        df = pd.read_sql(
            "SELECT sku, item_name, category, price, stock_left, status "
            "FROM inventory ORDER BY item_name LIMIT 200",
            conn,
        )
        conn.close()
        return df, f"Loaded {len(df)} products."
    except ImportError:
        return None, "psycopg2 not installed. Run: pip install psycopg2-binary"
    except Exception as e:
        return None, f"Error connecting to Supabase: {e}"


# ── Email campaign function ───────────────────────────────────────────────────

def send_campaign(contacts_raw, subject, html_template, progress=gr.Progress()):
    cfg = load_config()
    smtp_email   = cfg.get("smtp_email", "").strip()
    smtp_pass    = cfg.get("smtp_password", "").replace(" ", "")
    from_name    = cfg.get("from_name", "")

    if not smtp_email or not smtp_pass:
        return "No SMTP credentials saved. Go to Settings and save your Gmail details first."

    if not subject.strip():
        return "Subject line is required."

    contacts = _parse_contacts(contacts_raw or "")
    if not contacts:
        return "No valid contacts found. Format: Name, email@example.com (one per line)."

    try:
        server = smtplib.SMTP("smtp.gmail.com", 587, timeout=15)
        server.starttls()
        server.login(smtp_email, smtp_pass)
    except Exception as e:
        return f"Could not connect to Gmail: {e}"

    results = []
    for i, contact in enumerate(contacts):
        progress((i + 1) / len(contacts), desc=f"Sending to {contact['email']}…")

        html = (
            html_template
            .replace("{{name}}", contact["name"])
            .replace("{{from_name}}", from_name)
        )
        plain = f"Hi {contact['name']},\n\nPlease view this email in an HTML-capable client.\n\n{from_name}"

        msg = MIMEMultipart("alternative")
        msg["From"]    = f"{from_name} <{smtp_email}>"
        msg["To"]      = contact["email"]
        msg["Subject"] = subject.strip()
        msg.attach(MIMEText(plain, "plain"))
        msg.attach(MIMEText(html, "html"))

        try:
            server.send_message(msg)
            results.append(f"SENT     {contact['name']} <{contact['email']}>")
        except Exception as e:
            results.append(f"FAILED   {contact['name']} <{contact['email']}> — {e}")

        time.sleep(0.2)

    server.quit()
    sent   = sum(1 for r in results if r.startswith("SENT"))
    failed = len(results) - sent
    summary = f"Campaign complete — {sent} sent, {failed} failed.\n\n"
    return summary + "\n".join(results)


def preview_campaign(name_sample, html_template, from_name_override):
    cfg = load_config()
    from_name = from_name_override.strip() or cfg.get("from_name", "Your VEI Firm")
    return (
        html_template
        .replace("{{name}}", name_sample or "Jane Smith")
        .replace("{{from_name}}", from_name)
    )


# ── Gradio UI ─────────────────────────────────────────────────────────────────

with gr.Blocks(title="MERIT — Gradio", theme=gr.themes.Soft()) as demo:

    gr.Markdown("""
# MERIT — Mass Email & Inventory Tool
**Gradio version** — use this if Streamlit is blocked on your network.
For the full-featured version, try the Streamlit app first.
    """)

    with gr.Tabs():

        # ── Email Campaigns ──────────────────────────────────────────────────
        with gr.Tab("Email Campaigns"):
            gr.Markdown("### Send a broadcast email to a list of contacts")
            gr.Markdown(
                "Paste contacts below (one per line). "
                "Format: `Name, email@example.com` or just `email@example.com`. "
                "Use `{{name}}` and `{{from_name}}` in your HTML template."
            )

            with gr.Row():
                with gr.Column(scale=1):
                    camp_contacts = gr.Textbox(
                        label="Contacts",
                        placeholder="Jane Smith, jane@example.com\nJohn Doe, john@example.com\nanother@example.com",
                        lines=10,
                    )
                    camp_subject = gr.Textbox(
                        label="Subject Line",
                        placeholder="Important update from your VEI firm",
                    )

                with gr.Column(scale=1):
                    camp_html = gr.Textbox(
                        label="HTML Template",
                        value=_DEFAULT_CAMPAIGN_HTML,
                        lines=12,
                    )

            with gr.Row():
                camp_preview_name = gr.Textbox(
                    label="Preview — recipient name",
                    value="Jane Smith",
                    scale=2,
                )
                camp_preview_from = gr.Textbox(
                    label="Preview — from name (leave blank to use saved setting)",
                    placeholder="Acme VEI",
                    scale=2,
                )
                camp_preview_btn = gr.Button("Preview HTML", scale=1)

            camp_preview_out = gr.HTML(label="Email Preview")
            camp_preview_btn.click(
                preview_campaign,
                inputs=[camp_preview_name, camp_html, camp_preview_from],
                outputs=camp_preview_out,
            )

            camp_send_btn = gr.Button("Send Campaign", variant="primary")
            camp_log = gr.Textbox(label="Send Log", lines=15, interactive=False)
            camp_send_btn.click(
                send_campaign,
                inputs=[camp_contacts, camp_subject, camp_html],
                outputs=camp_log,
            )

        # ── Product Catalog ──────────────────────────────────────────────────
        with gr.Tab("Product Catalog"):
            gr.Markdown("### Live product catalog from Supabase")
            gr.Markdown("Reads from the `inventory` table in your Supabase database. Configure the connection in Settings.")

            prod_refresh_btn = gr.Button("Load Products", variant="primary")
            prod_status      = gr.Textbox(label="Status", interactive=False)
            prod_table       = gr.Dataframe(label="Products", interactive=False)

            prod_refresh_btn.click(
                load_products,
                outputs=[prod_table, prod_status],
            )

        # ── Settings ─────────────────────────────────────────────────────────
        with gr.Tab("Settings"):
            gr.Markdown("### Configure MERIT")
            gr.Markdown(
                "Settings are saved to `config.json` in the same folder as this file. "
                "Click **Load Saved Settings** to restore previously saved values."
            )

            with gr.Row():
                with gr.Column():
                    gr.Markdown("**Sender Identity**")
                    s_from_name  = gr.Textbox(label="From Name (your VEI firm name)", placeholder="Acme VEI")
                    s_subject    = gr.Textbox(label="Default Subject Line", placeholder="Your order is here")

                    gr.Markdown("**Gmail SMTP**")
                    s_smtp_email = gr.Textbox(label="Gmail Address", placeholder="yourfirm@gmail.com")
                    s_smtp_pass  = gr.Textbox(label="App Password (16 chars, spaces OK)", type="password")

                with gr.Column():
                    gr.Markdown("**Supabase Database**")
                    s_sb_conn    = gr.Textbox(
                        label="Connection String",
                        placeholder="postgresql://postgres:PASSWORD@db.xxxx.supabase.co:5432/postgres",
                    )
                    s_sb_pass    = gr.Textbox(label="Database Password", type="password")

                    gr.Markdown("**Image Hosting**")
                    s_freeimage  = gr.Textbox(label="Freeimage.host API Key")
                    s_imghippo   = gr.Textbox(label="Imghippo API Key")

            with gr.Row():
                s_save_btn  = gr.Button("Save Settings", variant="primary")
                s_load_btn  = gr.Button("Load Saved Settings")
                s_test_btn  = gr.Button("Test Gmail Connection")

            s_status = gr.Textbox(label="Status", interactive=False)

            s_save_btn.click(
                save_settings,
                inputs=[s_from_name, s_subject, s_smtp_email, s_smtp_pass,
                        s_sb_conn, s_sb_pass, s_freeimage, s_imghippo],
                outputs=s_status,
            )

            s_load_btn.click(
                load_settings_values,
                outputs=[s_from_name, s_subject, s_smtp_email, s_smtp_pass,
                         s_sb_conn, s_sb_pass, s_freeimage, s_imghippo],
            )

            s_test_btn.click(
                test_smtp,
                inputs=[s_smtp_email, s_smtp_pass],
                outputs=s_status,
            )

        # ── Privacy ───────────────────────────────────────────────────────────
        with gr.Tab("Privacy & Data"):
            gr.Markdown("""
### How MERIT stores your data

MERIT is a self-hosted app that **you** deploy. When you enter credentials, here is exactly where they go:

| Where | Details |
|---|---|
| **config.json** | Saved locally in the app folder — you own this file |
| **Supabase** | Your product and inventory data lives in **your** Supabase project |

### What MERIT does NOT do

- Does **not** transmit your API keys or passwords to any third party
- Does **not** have a central server — no "MERIT cloud" receives your data
- Does **not** log, collect, or share your customer data or order information
- The only outgoing connections are: Gmail SMTP (to send emails), Supabase/Neon (your own database), and image hosting services (Freeimage.host / Imghippo)

### In plain English

Your credentials stay on the machine running this app and in your own Supabase database. No one else can see them.
            """)


if __name__ == "__main__":
    demo.launch()
