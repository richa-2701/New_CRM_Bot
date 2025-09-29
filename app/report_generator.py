# app/report_generator.py
import os
import uuid
import logging
from datetime import date
from fpdf import FPDF
import matplotlib.pyplot as plt
import io

# We pass UPLOAD_DIRECTORY in as a parameter, so no import from webhook is needed.

logger = logging.getLogger(__name__)

# Define consistent colors for charts
ACTIVITY_BAR_COLOR = '#4285F4' # Google Blue
LEAD_OUTCOME_COLORS = ['#34A853', '#EA4335', '#9E9E9E'] # Green (Won), Red (Lost), Grey (In Progress)

class ReportPDF(FPDF):
    def header(self):
        self.set_font('Helvetica', 'B', 16)
        self.cell(0, 10, 'User Performance Report', 0, 1, 'C')
        self.ln(5)

    def footer(self):
        self.set_y(-15)
        self.set_font('Helvetica', 'I', 8)
        self.cell(0, 10, f'Page {self.page_no()}', 0, 0, 'C')

def create_performance_report_pdf(report_data: dict, username: str, start_date: date, end_date: date, upload_directory: str) -> str:
    """
    Generates a PDF report from the performance data and saves it to a file.
    Returns the file path.
    """
    pdf = ReportPDF('P', 'mm', 'A4')
    pdf.add_page()
    page_margin = 15
    
    # --- Sub-Header ---
    pdf.set_font('Helvetica', 'B', 12)
    pdf.cell(0, 10, f"User: {username}", 0, 0, 'L')
    pdf.set_font('Helvetica', '', 12)
    date_range_str = f"{start_date.strftime('%d %b, %Y')} to {end_date.strftime('%d %b, %Y')}"
    pdf.cell(0, 10, f"Period: {date_range_str}", 0, 1, 'R')
    pdf.ln(8)

    # --- KPI Section (Already corrected and looks good) ---
    pdf.set_font('Helvetica', 'B', 14)
    pdf.cell(0, 10, 'Key Performance Indicators', 0, 1, 'L')
    pdf.set_font('Helvetica', '', 11)
    
    kpis = report_data['kpi_summary']
    kpi_items = {
        "New Leads Assigned": kpis['new_leads_assigned'],
        "Meetings Completed": kpis['meetings_completed'],
        "Demos Completed": kpis['demos_completed'],
        "Activities Logged": kpis['activities_logged'],
        "Deals Won": kpis['deals_won'],
        "Conversion Rate": f"{kpis['conversion_rate']}%"
    }
    
    key_col_width = 70
    value_col_width = 30
    
    for title, value in kpi_items.items():
        pdf.set_font('Helvetica', 'B', 11)
        pdf.cell(key_col_width, 8, title, 0, 0, 'L')
        pdf.set_font('Helvetica', '', 11)
        pdf.cell(value_col_width, 8, str(value), 0, 1, 'R')
    
    pdf.ln(10)

    # --- Vertical Bar Chart (Already corrected and looks good) ---
    try:
        activity_data = report_data['visualizations']['activity_volume']
        if any(item['value'] > 0 for item in activity_data):
            pdf.set_font('Helvetica', 'B', 14)
            pdf.cell(0, 10, 'Activity Volume', 0, 1, 'L')
            
            labels = [item['name'].replace(" Scheduled", " Sched.").replace(" Completed", " Comp.") for item in activity_data]
            values = [item['value'] for item in activity_data]
            
            fig, ax = plt.subplots(figsize=(8, 5))
            bars = ax.bar(labels, values, color=ACTIVITY_BAR_COLOR)
            ax.set_ylabel('Count')
            ax.set_title('Comparison of Key Activities')
            ax.spines['top'].set_visible(False)
            ax.spines['right'].set_visible(False)
            plt.xticks(rotation=25, ha='right')

            for bar in bars:
                yval = bar.get_height()
                ax.text(bar.get_x() + bar.get_width()/2.0, yval, int(yval), va='bottom', ha='center') 

            plt.tight_layout()

            img_buffer = io.BytesIO()
            plt.savefig(img_buffer, format='PNG', dpi=300)
            img_buffer.seek(0)
            plt.close(fig)

            pdf.image(img_buffer, x=page_margin, w=pdf.w - (page_margin * 2))
            pdf.ln(5)
    except Exception as e:
        logger.error(f"Failed to generate activity bar chart: {e}")

    pdf.add_page()
    current_y = pdf.get_y()

    # --- Pie Chart (Already corrected and looks good) ---
    try:
        outcome_data = report_data['visualizations']['lead_outcome']
        if any(item['value'] > 0 for item in outcome_data):
            pdf.set_font('Helvetica', 'B', 14)
            pdf.cell(0, 10, 'Lead Outcome', 0, 1, 'L')

            chart_data = [item for item in outcome_data if item['value'] > 0]
            labels = [item['name'] for item in chart_data]
            values = [item['value'] for item in chart_data]
            
            fig, ax = plt.subplots(figsize=(7, 5))
            wedges, texts, autotexts = ax.pie(values, autopct='%1.1f%%', startangle=90, colors=LEAD_OUTCOME_COLORS, pctdistance=0.85)
            plt.setp(autotexts, size=10, weight="bold", color="white")
            
            centre_circle = plt.Circle((0,0),0.70,fc='white')
            fig.gca().add_artist(centre_circle)
            
            ax.axis('equal')  
            ax.set_title('Status of Leads Assigned in Period')
            
            legend_labels = [f"{l} ({v})" for l, v in zip(labels, values)]
            ax.legend(wedges, legend_labels, title="Outcomes", loc="center left", bbox_to_anchor=(1, 0, 0.5, 1))

            plt.tight_layout()

            img_buffer = io.BytesIO()
            plt.savefig(img_buffer, format='PNG', dpi=300)
            img_buffer.seek(0)
            plt.close(fig)

            pdf.image(img_buffer, x=page_margin, w=pdf.w - (page_margin * 2))
            pdf.ln(10)
            current_y = pdf.get_y()
    except Exception as e:
        logger.error(f"Failed to generate lead outcome pie chart: {e}")

    # --- Deals Won Table ---
    deals = report_data['tables']['deals_won']
    if deals:
        pdf.set_y(current_y + 10)
        pdf.set_font('Helvetica', 'B', 14)
        pdf.cell(0, 10, 'Deals Won Details', 0, 1, 'L')
        
        pdf.set_font('Helvetica', 'B', 10)
        pdf.set_fill_color(220, 220, 220)
        col_widths = [80, 40, 40, 30]
        headers = ['Client Name', 'Source', 'Converted Date', 'Time to Close (Days)']
        for i, header in enumerate(headers):
            pdf.cell(col_widths[i], 7, header, 1, 0, 'C', 1)
        pdf.ln()

        pdf.set_font('Helvetica', '', 10)
        pdf.set_fill_color(245, 245, 245)
        fill = False
        for deal in deals:
            # --- START: THIS IS THE FIX ---
            # 'deal['converted_date']' is a date object from the API.
            # We must format it into a string before passing it to the cell.
            converted_date_str = deal['converted_date'].strftime('%d-%m-%Y')
            
            pdf.cell(col_widths[0], 6, deal['client_name'], 1, 0, 'L', fill)
            pdf.cell(col_widths[1], 6, str(deal['source']), 1, 0, 'L', fill)
            pdf.cell(col_widths[2], 6, converted_date_str, 1, 0, 'C', fill)
            pdf.cell(col_widths[3], 6, str(deal['time_to_close']), 1, 0, 'C', fill)
            pdf.ln()
            fill = not fill
            # --- END: THIS IS THE FIX ---

    # --- Save PDF to a unique file ---
    file_name = f"report_{username}_{uuid.uuid4().hex[:8]}.pdf"
    file_path = os.path.join(upload_directory, file_name)
    pdf.output(file_path)
    logger.info(f"✅ Performance report generated and saved to: {file_path}")
    
    return file_path