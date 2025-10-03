# app/scheduler.py
import logging
import os
import asyncio
from datetime import date, timedelta, datetime
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from app.db import get_db_session_for_company, COMPANY_TO_ENV_MAP
from app.crud import get_all_admins, get_users, generate_user_performance_data
from app.report_generator import create_performance_report_pdf, create_summary_excel_report
from app.email_sender import send_email_with_multiple_attachments
from app.config import UPLOAD_DIRECTORY
import pytz

logger = logging.getLogger(__name__)

async def send_weekly_reports():
    """
    Scheduled job to generate and email a weekly performance report for all users
    to all admins for each company. Runs every Monday.
    """
    logger.info("🚀 Starting scheduled job: send_weekly_reports")
    
    today = date.today()
    end_date = today - timedelta(days=1)
    start_date = today - timedelta(days=7)
    
    date_range_str = f"{start_date.strftime('%d-%b-%Y')} to {end_date.strftime('%d-%b-%Y')}"
    logger.info(f"Generating weekly reports for period: {date_range_str}")
    
    all_companies = list(COMPANY_TO_ENV_MAP.keys())
    
    for company in all_companies:
        logger.info(f"-> Processing company for weekly report: '{company}'")
        db = get_db_session_for_company(company)
        attachment_paths = []
        all_users_report_data = []
        try:
            admins = get_all_admins(db)
            if not admins:
                logger.warning(f"   No admin users found for '{company}'. Skipping.")
                continue

            admin_emails = [admin.email for admin in admins if admin.email]
            if not admin_emails:
                logger.warning(f"   Admin users found for '{company}', but none have email addresses configured. Skipping.")
                continue

            all_users_for_report = get_users(db)
            if not all_users_for_report:
                logger.warning(f"   No users found in the database for '{company}'. Skipping report generation.")
                continue

            # First, gather all data
            for user in all_users_for_report:
                report_data = generate_user_performance_data(db, user.id, start_date, end_date)
                if report_data:
                    all_users_report_data.append((user, report_data))

            # Now, generate files from the gathered data
            if all_users_report_data:
                # Generate individual PDFs
                for user, report_data in all_users_report_data:
                    logger.info(f"   -> Generating weekly PDF report for user: '{user.username}'")
                    pdf_file_path = create_performance_report_pdf(
                        report_data=report_data,
                        username=user.username,
                        start_date=start_date,
                        end_date=end_date,
                        upload_directory=UPLOAD_DIRECTORY
                    )
                    attachment_paths.append(pdf_file_path)

                # Generate the summary Excel file
                logger.info(f"   -> Generating weekly Excel summary for company: '{company}'")
                excel_summary_path = create_summary_excel_report(
                    all_users_data=all_users_report_data,
                    start_date=start_date,
                    end_date=end_date,
                    company_name=company,
                    upload_directory=UPLOAD_DIRECTORY
                )
                if excel_summary_path:
                    attachment_paths.append(excel_summary_path)

            if attachment_paths:
                logger.info(f"   Proceeding to email {len(attachment_paths)} weekly report file(s) to admins.")
                
                email_subject = f"Weekly Performance Reports for {company} - {date_range_str}"
                email_body = (
                    f"Hello,\n\nPlease find the weekly user performance reports for {company} attached.\n\n"
                    f"This email includes individual PDF reports for each user and a consolidated Excel summary.\n\n"
                    f"Report Period: {start_date.strftime('%d %B, %Y')} to {end_date.strftime('%d %B, %Y')}\n\n"
                    f"This is an automated report.\n\n"
                    f"Regards,\nYour CRM System"
                )

                send_email_with_multiple_attachments(
                    recipients=admin_emails,
                    subject=email_subject,
                    body=email_body,
                    attachment_paths=attachment_paths
                )
            else:
                logger.info(f"   No performance data found for any user in '{company}'. No weekly email will be sent.")

        except Exception as e:
            logger.error(f"⚠️ A critical error occurred while processing weekly reports for company '{company}': {e}", exc_info=True)
        finally:
            if db:
                db.close()
            if attachment_paths:
                for path in attachment_paths:
                    if path and os.path.exists(path):
                        try:
                            os.remove(path)
                        except Exception as e:
                            logger.error(f"   Failed to clean up weekly report file {path}: {e}")

    logger.info("✅ Finished scheduled job: send_weekly_reports")


# --- START: NEW FUNCTION FOR MONTHLY REPORTS ---
async def send_monthly_reports():
    """
    Scheduled job to generate and email a monthly performance report for all users
    to all admins for each company. Runs on the 1st of every month.
    """
    logger.info("🚀 Starting scheduled job: send_monthly_reports")
    
    today = date.today()
    # This logic correctly calculates the start and end dates of the previous month
    end_date = today.replace(day=1) - timedelta(days=1)
    start_date = end_date.replace(day=1)
    
    date_range_str = f"{start_date.strftime('%d-%b-%Y')} to {end_date.strftime('%d-%b-%Y')}"
    logger.info(f"Generating monthly reports for period: {date_range_str}")
    
    all_companies = list(COMPANY_TO_ENV_MAP.keys())
    
    for company in all_companies:
        logger.info(f"-> Processing company for monthly report: '{company}'")
        db = get_db_session_for_company(company)
        attachment_paths = []
        all_users_report_data = []
        try:
            admins = get_all_admins(db)
            if not admins:
                logger.warning(f"   No admin users found for '{company}'. Skipping.")
                continue

            admin_emails = [admin.email for admin in admins if admin.email]
            if not admin_emails:
                logger.warning(f"   Admin users found for '{company}', but none have email addresses configured. Skipping.")
                continue

            all_users_for_report = get_users(db)
            if not all_users_for_report:
                logger.warning(f"   No users found in the database for '{company}'. Skipping report generation.")
                continue

            # First, gather all data
            for user in all_users_for_report:
                report_data = generate_user_performance_data(db, user.id, start_date, end_date)
                if report_data:
                    all_users_report_data.append((user, report_data))

            # Now, generate files from the gathered data
            if all_users_report_data:
                # Generate individual PDFs
                for user, report_data in all_users_report_data:
                    logger.info(f"   -> Generating monthly PDF report for user: '{user.username}'")
                    pdf_file_path = create_performance_report_pdf(
                        report_data=report_data,
                        username=user.username,
                        start_date=start_date,
                        end_date=end_date,
                        upload_directory=UPLOAD_DIRECTORY
                    )
                    attachment_paths.append(pdf_file_path)
                
                # Generate the summary Excel file
                logger.info(f"   -> Generating monthly Excel summary for company: '{company}'")
                excel_summary_path = create_summary_excel_report(
                    all_users_data=all_users_report_data,
                    start_date=start_date,
                    end_date=end_date,
                    company_name=company,
                    upload_directory=UPLOAD_DIRECTORY
                )
                if excel_summary_path:
                    attachment_paths.append(excel_summary_path)

            if attachment_paths:
                logger.info(f"   Proceeding to email {len(attachment_paths)} monthly report(s) to admins.")
                
                email_subject = f"Monthly Performance Reports for {company} - {start_date.strftime('%B %Y')}"
                email_body = (
                    f"Hello,\n\nPlease find the monthly user performance reports for {company} attached.\n\n"
                    f"This email includes individual PDF reports for each user and a consolidated Excel summary.\n\n"
                    f"Report Period: {start_date.strftime('%d %B, %Y')} to {end_date.strftime('%d %B, %Y')}\n\n"
                    f"This is an automated report.\n\n"
                    f"Regards,\nYour CRM System"
                )

                send_email_with_multiple_attachments(
                    recipients=admin_emails,
                    subject=email_subject,
                    body=email_body,
                    attachment_paths=attachment_paths
                )
            else:
                logger.info(f"   No performance data found for any user in '{company}'. No monthly email will be sent.")

        except Exception as e:
            logger.error(f"⚠️ A critical error occurred while processing monthly reports for company '{company}': {e}", exc_info=True)
        finally:
            if db:
                db.close()
            if attachment_paths:
                for path in attachment_paths:
                    if path and os.path.exists(path):
                        try:
                            os.remove(path)
                        except Exception as e:
                            logger.error(f"   Failed to clean up monthly report file {path}: {e}")

    logger.info("✅ Finished scheduled job: send_monthly_reports")
# --- END: NEW FUNCTION ---


# Initialize the scheduler
scheduler = AsyncIOScheduler(timezone=str(pytz.timezone('Asia/Kolkata')))

# --- START: MODIFICATION FOR PRODUCTION SCHEDULE ---
# Add the job for the weekly report to run every Monday at 9:00 AM.
scheduler.add_job(send_weekly_reports, 'cron', day_of_week='fri', hour=9, minute=0)
logger.info("--- Weekly report job scheduled to run every Monday at 9:00 AM ---")

# Add the job for the monthly report to run on the 1st day of every month at 9:00 AM.
scheduler.add_job(send_monthly_reports, 'cron', day='1', hour=9, minute=0)
logger.info("--- Monthly report job scheduled to run on the 1st of every month at 9:00 AM ---")
# --- END: MODIFICATION FOR PRODUCTION SCHEDULE ---