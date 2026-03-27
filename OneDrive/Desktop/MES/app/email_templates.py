# email_templates.py
# HTML email template generation with 100% inline CSS.
# Gmail strips <style> tags, so every element is styled inline.

import streamlit as st


def _get_accent_color() -> str:
    return st.secrets.get("ACCENT_COLOR", "#1B2A4A")


def _get_gold_color() -> str:
    return st.secrets.get("GOLD_COLOR", "#C9A84C")


def _get_firm_name() -> str:
    return st.secrets.get("FIRM_NAME", "MERIT")


def generate_items_html(items_list: list[dict]) -> str:
    """Build HTML table rows from a list of item dicts.

    Each dict: {name: str, price: float, qty: int}
    Returns <tr> elements with alternating row shading.
    """
    rows = []
    for idx, item in enumerate(items_list):
        name = item.get("name", "")
        price = float(item.get("price", 0))
        qty = int(item.get("qty", 1))
        subtotal = price * qty
        bg = "#f9f9f9" if idx % 2 == 0 else "#ffffff"

        rows.append(
            f'<tr style="background-color:{bg};">'
            f'<td style="padding:10px 12px;border-bottom:1px solid #eee;color:#333;">{name}</td>'
            f'<td style="padding:10px 12px;border-bottom:1px solid #eee;color:#333;text-align:center;">{qty}</td>'
            f'<td style="padding:10px 12px;border-bottom:1px solid #eee;color:#333;text-align:right;">${price:,.2f}</td>'
            f'<td style="padding:10px 12px;border-bottom:1px solid #eee;color:#333;text-align:right;">${subtotal:,.2f}</td>'
            f"</tr>"
        )

    return "\n".join(rows)


def get_fulfillment_email_html(
    first_name: str,
    order_number: str,
    items_rows_html: str,
    order_total: str,
) -> str:
    """Return a complete HTML email string for order fulfillment.

    Uses 100% inline CSS, 600px centered table, and cid:logo for the header image.
    """
    accent = _get_accent_color()
    gold = _get_gold_color()
    firm = _get_firm_name()
    reply_email = st.secrets.get("SMTP_SENDER_EMAIL", "")

    # Format total
    try:
        total_formatted = f"${float(str(order_total).replace('$', '').replace(',', '')):,.2f}"
    except (ValueError, TypeError):
        total_formatted = f"${order_total}"

    return f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"></head>
<body style="margin:0;padding:0;background-color:#f4f4f4;font-family:Arial,Helvetica,sans-serif;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background-color:#f4f4f4;padding:20px 0;">
<tr><td align="center">

<!-- Main container -->
<table role="presentation" width="600" cellpadding="0" cellspacing="0"
       style="max-width:600px;width:100%;background-color:#ffffff;border-radius:8px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,0.08);">

  <!-- Header -->
  <tr>
    <td style="background-color:{accent};padding:28px 20px;text-align:center;">
      <img src="cid:logo" alt="{firm}" style="max-height:60px;margin-bottom:8px;"
           onerror="this.style.display='none'">
      <div style="color:{gold};font-size:22px;font-weight:bold;letter-spacing:0.5px;">{firm}</div>
    </td>
  </tr>

  <!-- Body -->
  <tr>
    <td style="padding:30px 28px;">
      <p style="color:#333;font-size:16px;margin:0 0 8px;">Hi <strong>{first_name}</strong>,</p>
      <p style="color:#555;font-size:15px;line-height:1.6;margin:0 0 24px;">
        Thank you for your order! We're getting everything ready for you.
        Here's a summary of what you ordered:
      </p>

      <!-- Items table -->
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
             style="border-collapse:collapse;margin-bottom:20px;">
        <tr style="background-color:{accent};">
          <td style="padding:10px 12px;color:{gold};font-weight:bold;font-size:13px;text-transform:uppercase;">Product</td>
          <td style="padding:10px 12px;color:{gold};font-weight:bold;font-size:13px;text-transform:uppercase;text-align:center;">Qty</td>
          <td style="padding:10px 12px;color:{gold};font-weight:bold;font-size:13px;text-transform:uppercase;text-align:right;">Unit Price</td>
          <td style="padding:10px 12px;color:{gold};font-weight:bold;font-size:13px;text-transform:uppercase;text-align:right;">Subtotal</td>
        </tr>
        {items_rows_html}
      </table>

      <!-- Order total -->
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
        <tr>
          <td style="padding:14px 12px;text-align:right;border-top:2px solid {accent};">
            <span style="color:{accent};font-size:17px;font-weight:bold;">Order Total: {total_formatted}</span>
          </td>
        </tr>
      </table>
    </td>
  </tr>

  <!-- Footer -->
  <tr>
    <td style="background-color:#f8f8f8;padding:20px 28px;text-align:center;border-top:1px solid #eee;">
      <p style="color:#555;font-size:13px;margin:0 0 4px;">
        <strong>{firm}</strong>
      </p>
      <p style="color:#888;font-size:12px;margin:0 0 8px;">
        Questions? Reply to <a href="mailto:{reply_email}" style="color:{accent};">{reply_email}</a>
      </p>
      <p style="color:#bbb;font-size:11px;margin:0;">Sent via MERIT</p>
    </td>
  </tr>

</table>
<!-- End main container -->

</td></tr>
</table>
</body>
</html>"""
