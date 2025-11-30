"""
PDF Generator Module
Generates PDF files from TasksForPDF sheet
"""
import logging
import os
import tempfile
import requests
from io import BytesIO
from typing import List, Dict, Optional
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from PIL import Image as PILImage
import os

logger = logging.getLogger(__name__)


class PDFGenerator:
    """Generates PDF files from order data"""
    
    def __init__(self):
        """Initialize PDF generator"""
        self.temp_dir = tempfile.mkdtemp()
        # Register Unicode font for Russian characters
        # Use built-in CID fonts that support Cyrillic
        self.unicode_font_name = None
        try:
            # Try different Unicode CID fonts that support Cyrillic
            font_options = ['HeiseiMin-W3', 'HeiseiKakuGo-W5', 'KozMinPro-Regular']
            for font_name in font_options:
                try:
                    pdfmetrics.registerFont(UnicodeCIDFont(font_name))
                    self.unicode_font_name = font_name
                    logger.info(f"Registered Unicode font: {font_name}")
                    break
                except Exception:
                    continue
            if not self.unicode_font_name:
                logger.warning("Could not register Unicode font, using default")
        except Exception as e:
            logger.warning(f"Error registering Unicode font: {e}")
        logger.info(f"PDF generator initialized with temp dir: {self.temp_dir}")
    
    def _download_image(self, image_url: str) -> Optional[BytesIO]:
        """
        Download image from URL
        
        Args:
            image_url: Image URL
            
        Returns:
            BytesIO object with image data or None
        """
        if not image_url or not image_url.strip():
            return None
        
        try:
            response = requests.get(image_url, timeout=10)
            response.raise_for_status()
            
            # Verify it's an image
            img = PILImage.open(BytesIO(response.content))
            
            # Convert to RGB if necessary (for JPEG)
            if img.mode in ('RGBA', 'LA', 'P'):
                rgb_img = PILImage.new('RGB', img.size, (255, 255, 255))
                if img.mode == 'P':
                    img = img.convert('RGBA')
                rgb_img.paste(img, mask=img.split()[-1] if img.mode in ('RGBA', 'LA') else None)
                img = rgb_img
            
            # Save to BytesIO
            img_bytes = BytesIO()
            img.save(img_bytes, format='JPEG', quality=85)
            img_bytes.seek(0)
            
            return img_bytes
        except Exception as e:
            logger.warning(f"Error downloading image from {image_url}: {e}")
            return None
    
    def generate_pdf_from_tasks(
        self,
        tasks: List[Dict],
        output_path: str,
        title: str = "Заказы",
    ) -> bool:
        """
        Generate PDF from tasks list
        
        Args:
            tasks: List of task dictionaries with keys:
                   order_id, photo_url, product_name, article, sticker
            output_path: Path to save PDF file
            title: PDF title
            
        Returns:
            True if successful, False otherwise
        """
        try:
            logger.info(f"Starting PDF generation for {len(tasks)} tasks")
            if not tasks:
                logger.warning("No tasks provided for PDF generation")
                return False
            
            doc = SimpleDocTemplate(
                output_path,
                pagesize=A4,
                rightMargin=15*mm,
                leftMargin=15*mm,
                topMargin=20*mm,
                bottomMargin=15*mm,
            )
            
            # Container for PDF elements
            elements = []
            
            # Styles with Unicode support
            styles = getSampleStyleSheet()
            # Use Unicode font for Russian characters if available
            unicode_font = self.unicode_font_name or 'Helvetica'
            
            title_style = ParagraphStyle(
                'CustomTitle',
                parent=styles['Heading1'],
                fontSize=18,
                textColor=colors.HexColor('#1a1a1a'),
                spaceAfter=30,
                alignment=TA_CENTER,
                fontName=unicode_font,
            )
            
            normal_style = ParagraphStyle(
                'NormalUnicode',
                parent=styles['Normal'],
                fontName=unicode_font,
                encoding='utf-8',
            )
            
            # Sort tasks by article (Артикул продавца) in alphabetical order
            def get_sort_key(task):
                article = str(task.get('article', '')).strip()
                return article.lower() if article else ''
            
            sorted_tasks = sorted(tasks, key=get_sort_key)
            logger.info(f"Generating PDF with {len(sorted_tasks)} tasks")
            
            # Add title
            title_para = Paragraph(str(title), title_style)
            elements.append(title_para)
            elements.append(Spacer(1, 12))
            
            # Escape and encode text properly for Unicode
            def safe_text(text):
                """Ensure text is properly encoded for PDF"""
                if not text:
                    return ''
                # Ensure it's a string and properly encoded
                if isinstance(text, bytes):
                    text = text.decode('utf-8')
                return str(text)
            
            # Process tasks (already sorted) - wrap in try-except to catch errors
            tasks_processed = 0
            for idx, task in enumerate(sorted_tasks, 1):
                try:
                    order_id = str(task.get('order_id', ''))
                    photo_url = str(task.get('photo_url', '')).strip()
                    product_name = str(task.get('product_name', '')).strip()
                    article = str(task.get('article', '')).strip()
                    sticker = str(task.get('sticker', '')).strip()
                    
                    # Skip tasks with empty order_id
                    if not order_id or order_id == 'None' or order_id == '':
                        logger.warning(f"Skipping task {idx} with empty order_id")
                        continue
                    
                    logger.info(f"Processing task {idx}/{len(sorted_tasks)}: order_id={order_id}, article={article}")
                    
                    # Download and add image if available
                    if photo_url:
                        try:
                            img_data = self._download_image(photo_url)
                            if img_data:
                                # Resize image to fit on page (max width 150mm)
                                img = Image(img_data, width=150*mm, height=150*mm, kind='proportional')
                                elements.append(img)
                                elements.append(Spacer(1, 5))
                        except Exception as e:
                            logger.warning(f"Error adding image for order {order_id}: {e}")
                            # Continue without image
                    
                    # Use Paragraph for Unicode support
                    order_data_formatted = [
                        [Paragraph(safe_text('№ задания:'), normal_style), Paragraph(safe_text(order_id), normal_style)],
                        [Paragraph(safe_text('Наименование:'), normal_style), Paragraph(safe_text(product_name or 'Не указано'), normal_style)],
                        [Paragraph(safe_text('Артикул продавца:'), normal_style), Paragraph(safe_text(article or 'Не указано'), normal_style)],
                        [Paragraph(safe_text('Стикер:'), normal_style), Paragraph(safe_text(sticker or 'Не указано'), normal_style)],
                    ]
                    
                    table = Table(order_data_formatted, colWidths=[50*mm, 120*mm])
                    table.setStyle(TableStyle([
                        ('BACKGROUND', (0, 0), (0, -1), colors.grey),
                        ('TEXTCOLOR', (0, 0), (-1, -1), colors.black),
                        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                        ('FONTSIZE', (0, 0), (-1, -1), 10),
                        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
                        ('TOPPADDING', (0, 0), (-1, -1), 8),
                        ('GRID', (0, 0), (-1, -1), 1, colors.black),
                    ]))
                    
                    elements.append(table)
                    tasks_processed += 1
                    
                    # Add separator between orders (except last one)
                    if idx < len(sorted_tasks):
                        elements.append(Spacer(1, 15))
                        elements.append(Paragraph("_" * 80, normal_style))
                        elements.append(Spacer(1, 15))
                        
                except Exception as e:
                    logger.error(f"Error processing task {idx} (order_id={task.get('order_id', 'unknown')}): {e}")
                    # Continue with next task instead of failing completely
                    continue
            
            logger.info(f"Successfully processed {tasks_processed} out of {len(sorted_tasks)} tasks for PDF")
            
            # Build PDF
            doc.build(elements)
            logger.info(f"Successfully generated PDF: {output_path}")
            return True
            
        except Exception as e:
            logger.error(f"Error generating PDF: {e}")
            return False
    
    def cleanup(self):
        """Cleanup temporary files"""
        try:
            import shutil
            if os.path.exists(self.temp_dir):
                shutil.rmtree(self.temp_dir)
        except Exception as e:
            logger.warning(f"Error cleaning up temp directory: {e}")
