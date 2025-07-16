import asyncio
from app.gpt_parser import parse_lead_info

test_message = """There is a new lead. Company name: Saraswati Printers. Contact person name: Himanshu. Contact number: 8878433436. Source: referral. Segment: Retail. Team size: 10. Email: archit@saraswati.com. Remark: Interested in product. assigned to 6261257575"""

parsed = parse_lead_info(test_message)
print("✅ Parsed:", parsed)
