"""
PDF processing and data merging for DDR generation.

Handles:
- Extract text from PDF using PyMuPDF
- Chunk large texts for LLM processing
- Merge and deduplicate findings
- Detect conflicts between inspection and thermal data
- Validate and clean structured data
- Generate professional DDR PDF reports
"""

import os
import json
import logging
import fitz
from typing import Dict, List, Any, Tuple
from difflib import SequenceMatcher
from datetime import datetime
from pathlib import Path

from reportlab.lib.pagesizes import letter, A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak, Table, TableStyle
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT, TA_JUSTIFY, TA_CENTER

logger = logging.getLogger(__name__)


class PDFExtractor:
    """Extract text from PDF files."""

    @staticmethod
    def extract_text(pdf_path: str, max_size_mb: int = 100) -> str:
        """
        Extract all text from PDF.
        
        Args:
            pdf_path: Path to PDF file
            max_size_mb: Maximum PDF file size in MB (safeguard against huge files)
            
        Returns:
            Full text from PDF
        """
        if not os.path.exists(pdf_path):
            raise FileNotFoundError(f"PDF not found: {pdf_path}")
        
        # Check file size
        file_size_mb = os.path.getsize(pdf_path) / (1024 * 1024)
        if file_size_mb > max_size_mb:
            raise ValueError(
                f"PDF file too large: {file_size_mb:.1f}MB (max: {max_size_mb}MB). "
                f"Please use a smaller PDF or increase MAX_PDF_SIZE_MB in config."
            )
        
        text = ""
        try:
            doc = fitz.open(pdf_path)
            page_count = len(doc)
            logger.info(f"Extracting text from {page_count} pages...")
            
            for page_num, page in enumerate(doc):
                if page_num % 10 == 0:
                    logger.debug(f"Processing page {page_num + 1}/{page_count}")
                
                text += f"\n--- Page {page_num + 1} ---\n"
                text += page.get_text()
            
            doc.close()
            logger.info(f"Extracted {len(text)} characters from {os.path.basename(pdf_path)}")
            
            if len(text) < 50:
                logger.warning(f"Very little text extracted ({len(text)} chars). PDF may be image-only.")
            
            return text
        except Exception as e:
            logger.error(f"Failed to extract text from {pdf_path}: {e}")
            raise


class TextChunker:
    """Split large texts into chunks for LLM processing."""

    def __init__(self, chunk_size: int = 4000, overlap: int = 300):
        """
        Initialize chunker.
        
        Args:
            chunk_size: Maximum characters per chunk
            overlap: Character overlap between chunks
        """
        self.chunk_size = chunk_size
        self.overlap = overlap

    def split_text(self, text: str) -> List[str]:
        """
        Split text into overlapping chunks.
        
        Args:
            text: Full text to split
            
        Returns:
            List of text chunks
        """
        if len(text) <= self.chunk_size:
            return [text]
        
        chunks = []
        current_pos = 0
        safety_counter = 0
        max_iterations = (len(text) // max(1, self.chunk_size - self.overlap)) + 10
        
        while current_pos < len(text) and safety_counter < max_iterations:
            safety_counter += 1
            
            # Get chunk
            chunk_end = min(current_pos + self.chunk_size, len(text))
            chunk = text[current_pos:chunk_end]
            
            # Try to break at sentence boundary
            if chunk_end < len(text):
                last_period = chunk.rfind(".")
                if last_period > self.chunk_size // 2:  # Found reasonable break point
                    chunk_end = current_pos + last_period + 1
            
            chunk = text[current_pos:chunk_end]
            if chunk.strip():  # Only add non-empty chunks
                chunks.append(chunk.strip())
            
            # Move with overlap - ensure progress
            next_pos = chunk_end - self.overlap
            if next_pos <= current_pos:
                # Safeguard: if not making progress, jump by chunk_size
                next_pos = chunk_end
            current_pos = next_pos
        
        if safety_counter >= max_iterations:
            logger.warning(f"Text chunking hit safety limit. Split into {len(chunks)} chunks")
        
        logger.info(f"Split text into {len(chunks)} chunks (text length: {len(text)})")
        return chunks


class DataMerger:
    """Merge and deduplicate structured data from multiple extractions."""

    @staticmethod
    def merge_findings(data_list: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Merge multiple extraction results.
        
        Combines areas, deduplicates findings, and detects conflicts.
        
        Args:
            data_list: List of extraction result dicts
            
        Returns:
            Merged and deduplicated data
        """
        merged_areas = {}
        
        for data in data_list:
            if not isinstance(data, dict) or "areas" not in data:
                continue
            
            for area in data["areas"]:
                area_name = area.get("area_name", "Unknown").strip()
                
                if area_name not in merged_areas:
                    merged_areas[area_name] = {
                        "area_name": area_name,
                        "inspection_findings": [],
                        "thermal_findings": [],
                        "conflicts": [],
                        "missing_info": []
                    }
                
                # Add and deduplicate findings
                merged_areas[area_name]["inspection_findings"] = \
                    DataMerger._deduplicate_list(
                        merged_areas[area_name]["inspection_findings"] +
                        area.get("inspection_findings", [])
                    )
                
                merged_areas[area_name]["thermal_findings"] = \
                    DataMerger._deduplicate_list(
                        merged_areas[area_name]["thermal_findings"] +
                        area.get("thermal_findings", [])
                    )
                
                merged_areas[area_name]["conflicts"] = \
                    DataMerger._deduplicate_list(
                        merged_areas[area_name]["conflicts"] +
                        area.get("conflicts", [])
                    )
                
                merged_areas[area_name]["missing_info"] = \
                    DataMerger._deduplicate_list(
                        merged_areas[area_name]["missing_info"] +
                        area.get("missing_info", [])
                    )
        
        return {
            "areas": list(merged_areas.values())
        }

    @staticmethod
    def detect_conflicts(area_data: Dict[str, Any]) -> List[str]:
        """
        Detect logical conflicts between inspection and thermal findings.
        
        Args:
            area_data: Single area data dict
            
        Returns:
            List of detected conflicts
        """
        conflicts = []
        inspection = area_data.get("inspection_findings", [])
        thermal = area_data.get("thermal_findings", [])
        
        # Check for contradictory patterns
        contradiction_pairs = [
            ("moisture", "dry"),
            ("wet", "dry"),
            ("mold", "clean"),
            ("damage", "intact"),
            ("high temperature", "low temperature"),
        ]
        
        combined_text = " ".join(inspection + thermal).lower()
        
        for term1, term2 in contradiction_pairs:
            if term1 in combined_text and term2 in combined_text:
                conflicts.append(
                    f"Potential contradiction: '{term1}' and '{term2}' mentioned"
                )
        
        return list(set(conflicts))  # Remove duplicates

    @staticmethod
    def _deduplicate_list(items: List[str]) -> List[str]:
        """
        Remove duplicate and near-duplicate items from list.
        
        Uses fuzzy matching to catch similar items.
        """
        if not items:
            return []
        
        deduplicated = []
        for item in items:
            item = item.strip()
            if not item:
                continue
            
            # Check if similar item already exists
            is_duplicate = False
            for existing in deduplicated:
                similarity = SequenceMatcher(None, item.lower(), existing.lower()).ratio()
                if similarity > 0.85:  # 85% similarity threshold
                    is_duplicate = True
                    break
            
            if not is_duplicate:
                deduplicated.append(item)
        
        return deduplicated

    @staticmethod
    def fill_missing_fields(data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Ensure all expected fields exist; fill empty ones with 'Not Available'.
        Validates structure before modifying.
        """
        if not isinstance(data, dict):
            return {"areas": []}
        
        if "areas" not in data:
            data["areas"] = []
        
        if not isinstance(data["areas"], list):
            data["areas"] = []
        
        valid_areas = []
        for area in data["areas"]:
            if not isinstance(area, dict):
                logger.warning(f"Skipping invalid area (not a dict): {area}")
                continue
            
            for field in ["inspection_findings", "thermal_findings", "conflicts", "missing_info"]:
                if field not in area or not isinstance(area[field], list):
                    area[field] = []
            
            if not area.get("area_name") or not isinstance(area.get("area_name"), str):
                area["area_name"] = "Unknown Area"
            
            valid_areas.append(area)
        
        data["areas"] = valid_areas
        return data


class DataValidator:
    """Validate extracted and merged data."""

    @staticmethod
    def validate_completion(data: Dict[str, Any]) -> Tuple[bool, List[str]]:
        """
        Validate data completeness and consistency.
        
        Returns:
            (is_valid, list_of_issues)
        """
        issues = []
        
        if not isinstance(data, dict):
            issues.append("Data is not a dictionary")
            return False, issues
        
        if "areas" not in data:
            issues.append("Missing 'areas' key")
            return False, issues
        
        if not isinstance(data["areas"], list) or len(data["areas"]) == 0:
            issues.append("No areas found in data")
            return False, issues
        
        for idx, area in enumerate(data["areas"]):
            if not area.get("area_name"):
                issues.append(f"Area {idx} missing area_name")
            
            has_content = (
                area.get("inspection_findings") or
                area.get("thermal_findings") or
                area.get("missing_info")
            )
            if not has_content:
                issues.append(f"Area '{area.get('area_name')}' has no findings")
        
        return len(issues) == 0, issues


class DDRReportGenerator:
    """Generate professional multi-page DDR PDF reports using ReportLab."""

    def __init__(self, output_filename: str = "DDR_Report.pdf"):
        """
        Initialize PDF report generator.
        
        Args:
            output_filename: Name of output PDF file
        """
        self.output_filename = output_filename
        self.styles = getSampleStyleSheet()
        self._setup_custom_styles()

    def _setup_custom_styles(self):
        """Setup custom styles for professional appearance."""
        # Title style
        self.styles.add(ParagraphStyle(
            name='CustomTitle',
            parent=self.styles['Heading1'],
            fontSize=24,
            textColor=colors.HexColor('#1f4788'),
            spaceAfter=30,
            alignment=TA_CENTER,
            fontName='Helvetica-Bold'
        ))
        
        # Section heading
        self.styles.add(ParagraphStyle(
            name='SectionHeading',
            parent=self.styles['Heading2'],
            fontSize=14,
            textColor=colors.HexColor('#2E5C8A'),
            spaceAfter=12,
            spaceBefore=12,
            fontName='Helvetica-Bold',
            borderColor=colors.HexColor('#2E5C8A'),
            borderWidth=2,
            borderPadding=10,
            backColor=colors.HexColor('#E8EEF7')
        ))
        
        # Area subsection
        self.styles.add(ParagraphStyle(
            name='AreaHeading',
            parent=self.styles['Heading3'],
            fontSize=12,
            textColor=colors.HexColor('#2E5C8A'),
            spaceAfter=8,
            spaceBefore=8,
            fontName='Helvetica-Bold'
        ))
        
        # Body text with justification
        self.styles.add(ParagraphStyle(
            name='CustomBody',
            parent=self.styles['BodyText'],
            fontSize=11,
            alignment=TA_JUSTIFY,
            spaceAfter=10,
            leading=14
        ))
        
        # Bullet style
        self.styles.add(ParagraphStyle(
            name='BulletStyle',
            parent=self.styles['Normal'],
            fontSize=11,
            leftIndent=20,
            spaceAfter=6,
            leading=12
        ))

    def generate(self, ddr_text: str, merged_data: Dict[str, Any]) -> str:
        """
        Generate professional DDR PDF report.
        
        Args:
            ddr_text: Full DDR report text from LLM
            merged_data: Structured data for reference
            
        Returns:
            Path to generated PDF file
        """
        # Get output path
        output_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            self.output_filename
        )
        
        # Create document
        doc = SimpleDocTemplate(
            output_path,
            pagesize=letter,
            rightMargin=0.75*inch,
            leftMargin=0.75*inch,
            topMargin=0.75*inch,
            bottomMargin=0.75*inch
        )
        
        # Build story
        story = []
        
        # Header
        story.append(Paragraph("DETAILED DIAGNOSTIC REPORT (DDR)", self.styles['CustomTitle']))
        story.append(Paragraph(
            f"<i>Generated on {datetime.now().strftime('%B %d, %Y at %H:%M:%S')}</i>",
            self.styles['Normal']
        ))
        story.append(Spacer(1, 0.3*inch))
        
        # Parse DDR text into sections
        sections = self._parse_ddr_sections(ddr_text)
        
        for section_title, section_content in sections:
            # Add section heading
            if section_title:
                story.append(Paragraph(section_title, self.styles['SectionHeading']))
            
            # Add section content with proper formatting
            paragraphs = self._format_section_content(section_content)
            for para in paragraphs:
                story.append(para)
                story.append(Spacer(1, 0.1*inch))
            
            # Add some space between sections
            story.append(Spacer(1, 0.2*inch))
        
        # Footer with reference data
        story.append(PageBreak())
        story.append(Paragraph("APPENDIX: EXTRACTED DATA", self.styles['SectionHeading']))
        story.append(Spacer(1, 0.2*inch))
        
        # Add structured data as reference
        for area in merged_data.get("areas", []):
            story.append(Paragraph(f"Area: {area.get('area_name', 'Unknown')}", self.styles['AreaHeading']))
            
            if area.get("inspection_findings"):
                story.append(Paragraph("Inspection Findings:", self.styles['Normal']))
                for finding in area["inspection_findings"]:
                    story.append(Paragraph(f"• {finding}", self.styles['BulletStyle']))
                story.append(Spacer(1, 0.1*inch))
            
            if area.get("thermal_findings"):
                story.append(Paragraph("Thermal Findings:", self.styles['Normal']))
                for finding in area["thermal_findings"]:
                    story.append(Paragraph(f"• {finding}", self.styles['BulletStyle']))
                story.append(Spacer(1, 0.1*inch))
            
            if area.get("conflicts"):
                story.append(Paragraph("Identified Conflicts:", self.styles['Normal']))
                for conflict in area["conflicts"]:
                    story.append(Paragraph(
                        f"• <b>⚠ {conflict}</b>",
                        self.styles['BulletStyle']
                    ))
                story.append(Spacer(1, 0.1*inch))
            
            story.append(Spacer(1, 0.2*inch))
        
        # Build PDF
        try:
            doc.build(story)
            logger.info(f"PDF report generated: {output_path}")
            return output_path
        except Exception as e:
            logger.error(f"Failed to generate PDF: {e}")
            raise

    def _parse_ddr_sections(self, ddr_text: str) -> List[Tuple[str, str]]:
        """
        Parse DDR text into sections.
        
        Returns list of (section_title, section_content) tuples.
        Robust to variations in formatting.
        """
        sections = []
        
        # Define section headers to look for (with flexible patterns)
        section_patterns = [
            ("PROPERTY ISSUE SUMMARY", "Property Issue Summary"),
            ("AREA-WISE OBSERVATIONS", "Area-Wise Observations"),
            ("PROBABLE ROOT CAUSE", "Probable Root Cause"),
            ("SEVERITY ASSESSMENT", "Severity Assessment"),
            ("RECOMMENDED ACTIONS", "Recommended Actions"),
            ("ADDITIONAL NOTES", "Additional Notes"),
            ("MISSING OR UNCLEAR INFORMATION", "Missing or Unclear Information")
        ]
        
        # Split by section headers - try both uppercase and formatted versions
        text_upper = ddr_text.upper()
        found_sections = []
        
        for pattern_upper, pattern_display in section_patterns:
            header_pos = text_upper.find(pattern_upper)
            if header_pos != -1:
                found_sections.append((header_pos, len(pattern_upper), pattern_display))
        
        # Sort by position
        found_sections.sort(key=lambda x: x[0])
        
        # Extract content between headers
        for idx, (pos, length, display_name) in enumerate(found_sections):
            start = pos + length
            
            # Find next section start
            if idx + 1 < len(found_sections):
                next_pos = found_sections[idx + 1][0]
            else:
                next_pos = len(ddr_text)
            
            content = ddr_text[start:next_pos].strip()
            if content:  # Only add if there's actual content
                sections.append((display_name, content))
        
        # If no sections found, treat entire text as one section
        if not sections and ddr_text.strip():
            sections.append(("REPORT", ddr_text.strip()))
        
        return sections

    def _format_section_content(self, content: str) -> List[Any]:
        """
        Format section content into Platypus objects.
        
        Handles bullet points, paragraphs, etc.
        """
        paragraphs = []
        
        # Split by newlines and process
        lines = content.strip().split('\n')
        
        current_paragraph = ""
        
        for line in lines:
            line = line.strip()
            
            if not line:
                # Empty line - flush current paragraph
                if current_paragraph:
                    paragraphs.append(
                        Paragraph(current_paragraph, self.styles['CustomBody'])
                    )
                    current_paragraph = ""
            
            elif line.startswith('•') or line.startswith('-') or line.startswith('*'):
                # Bullet point
                # Flush current paragraph first
                if current_paragraph:
                    paragraphs.append(
                        Paragraph(current_paragraph, self.styles['CustomBody'])
                    )
                    current_paragraph = ""
                
                # Add bullet
                bullet_text = line[1:].strip()
                paragraphs.append(
                    Paragraph(f"• {bullet_text}", self.styles['BulletStyle'])
                )
            
            elif line.startswith('Area:') or line.startswith('area:'):
                # Area header
                if current_paragraph:
                    paragraphs.append(
                        Paragraph(current_paragraph, self.styles['CustomBody'])
                    )
                    current_paragraph = ""
                
                paragraphs.append(Paragraph(line, self.styles['AreaHeading']))
            
            else:
                # Regular text - accumulate
                if current_paragraph:
                    current_paragraph += " " + line
                else:
                    current_paragraph = line
        
        # Flush any remaining paragraph
        if current_paragraph:
            paragraphs.append(
                Paragraph(current_paragraph, self.styles['CustomBody'])
            )
        
        return paragraphs
