"""
Main Tkinter application for DDR (Detailed Diagnostic Report) generation.

UI Controls:
- Select Inspection PDF
- Select Thermal PDF
- Generate Report (runs extraction, merging, LLM processing, PDF generation)
- Status display
- Progress feedback

Orchestrates the complete workflow:
1. PDF selection and validation
2. Text extraction and chunking
3. Structured data extraction via LLM
4. Data merging and validation
5. Final DDR report formatting via LLM
6. Professional PDF generation
"""

import os
import sys
import json
import logging
import threading
import signal
import time
import ctypes
from tkinter import Tk, Label, Button, filedialog, messagebox, StringVar, Frame as TkFrame
from tkinter.ttk import Frame, Progressbar
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Any

from processor import PDFExtractor, TextChunker, DataMerger, DataValidator, DDRReportGenerator
from llm_utils import LLMExtractor, DEFAULT_TIMEOUT, REPORT_GEN_TIMEOUT, TimeoutError

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Timeout configuration
REPORT_TIMEOUT = int(os.getenv("REPORT_TIMEOUT", 300))  # 5 minutes maximum for entire workflow


class DDRApplication:
    """Main Tkinter application for DDR generation."""

    def __init__(self, root: Tk):
        """Initialize the application."""
        self.root = root
        self.root.title("Detailed Diagnostic Report (DDR) Generator")
        self.root.geometry("1000x650")
        self.root.resizable(False, False)
        self.root.configure(bg="#ffffff")
        
        # State
        self.inspection_pdf = None
        self.thermal_pdf = None
        self.merged_data = None
        self.report_thread = None
        self.timeout_timer = None
        self.is_processing = False
        self.should_exit = False
        
        # UI Components
        self.status_var = StringVar(value="Ready")
        self.inspection_label = StringVar(value="No Inspection PDF selected")
        self.thermal_label = StringVar(value="No Thermal PDF selected")
        
        self._build_ui()
        
        # Setup signal handlers for graceful exit
        signal.signal(signal.SIGINT, self._signal_handler)
        
        # Handle window close
        self.root.protocol("WM_DELETE_WINDOW", self._on_closing)

    def _build_ui(self):
        """Build modern UI with two-column layout."""
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        
        # Header Bar
        header = TkFrame(self.root, bg="#1e3a8a", height=80)
        header.grid(row=0, column=0, sticky="ew")
        header.grid_propagate(False)
        
        title = Label(
            header,
            text="📋 Detailed Diagnostic Report Generator",
            font=("Segoe UI", 16, "bold"),
            fg="white",
            bg="#1e3a8a"
        )
        title.pack(side="left", padx=25, pady=20)
        
        subtitle = Label(
            header,
            text="Extract, merge, and generate professional reports from inspection and thermal PDFs",
            font=("Segoe UI", 9),
            fg="#cbd5e1",
            bg="#1e3a8a"
        )
        subtitle.pack(side="left", padx=25)
        
        # Main Content
        content = TkFrame(self.root, bg="#ffffff")
        content.grid(row=1, column=0, sticky="nsew", padx=20, pady=20)
        self.root.rowconfigure(1, weight=1)
        
        # LEFT PANEL - File Selection
        left_panel = TkFrame(content, bg="#f8fafc", relief="flat", bd=0)
        left_panel.pack(side="left", fill="both", expand=True, padx=(0, 15))
        
        # Left Panel Title
        left_title = Label(
            left_panel,
            text="📄 Step 1: Select PDF Files",
            font=("Segoe UI", 12, "bold"),
            fg="#1e3a8a",
            bg="#f8fafc"
        )
        left_title.pack(anchor="w", padx=15, pady=(15, 10))
        
        # Inspection Card
        insp_card = TkFrame(left_panel, bg="white", relief="solid", bd=1)
        insp_card.pack(fill="x", padx=15, pady=10)
        
        Label(
            insp_card,
            text="Inspection Report",
            font=("Segoe UI", 10, "bold"),
            fg="#475569",
            bg="white"
        ).pack(anchor="w", padx=12, pady=(10, 5))
        
        self.inspection_status = Label(
            insp_card,
            textvariable=self.inspection_label,
            text="No file selected",
            font=("Segoe UI", 9),
            fg="#0ea5e9",
            bg="white",
            anchor="w",
            wraplength=280,
            justify="left"
        )
        self.inspection_status.pack(anchor="w", padx=12, pady=(0, 10))
        
        Button(
            insp_card,
            text="📂 Browse Files",
            command=self._select_inspection_pdf,
            font=("Segoe UI", 9, "bold"),
            fg="white",
            bg="#0ea5e9",
            activebackground="#0284c7",
            relief="flat",
            bd=0,
            padx=12,
            pady=8,
            cursor="hand2"
        ).pack(fill="x", padx=12, pady=(0, 12))
        
        # Thermal Card
        thermal_card = TkFrame(left_panel, bg="white", relief="solid", bd=1)
        thermal_card.pack(fill="x", padx=15, pady=10)
        
        Label(
            thermal_card,
            text="Thermal Report",
            font=("Segoe UI", 10, "bold"),
            fg="#475569",
            bg="white"
        ).pack(anchor="w", padx=12, pady=(10, 5))
        
        self.thermal_status = Label(
            thermal_card,
            textvariable=self.thermal_label,
            text="No file selected",
            font=("Segoe UI", 9),
            fg="#0ea5e9",
            bg="white",
            anchor="w",
            wraplength=280,
            justify="left"
        )
        self.thermal_status.pack(anchor="w", padx=12, pady=(0, 10))
        
        Button(
            thermal_card,
            text="📂 Browse Files",
            command=self._select_thermal_pdf,
            font=("Segoe UI", 9, "bold"),
            fg="white",
            bg="#0ea5e9",
            activebackground="#0284c7",
            relief="flat",
            bd=0,
            padx=12,
            pady=8,
            cursor="hand2"
        ).pack(fill="x", padx=12, pady=(0, 12))
        
        # RIGHT PANEL - Controls & Status
        right_panel = TkFrame(content, bg="#f8fafc", relief="flat", bd=0)
        right_panel.pack(side="right", fill="both", expand=True, padx=(15, 0))
        
        # Right Panel Title
        right_title = Label(
            right_panel,
            text="⚙️ Step 2: Generate Report",
            font=("Segoe UI", 12, "bold"),
            fg="#1e3a8a",
            bg="#f8fafc"
        )
        right_title.pack(anchor="w", padx=15, pady=(15, 10))
        
        # Control Card
        ctrl_card = TkFrame(right_panel, bg="white", relief="solid", bd=1)
        ctrl_card.pack(fill="x", padx=15, pady=10)
        
        Label(
            ctrl_card,
            text="Report Generation",
            font=("Segoe UI", 10, "bold"),
            fg="#475569",
            bg="white"
        ).pack(anchor="w", padx=12, pady=(10, 12))
        
        # Generate Button
        self.generate_btn = Button(
            ctrl_card,
            text="✓ Generate Report",
            command=self._generate_report_thread,
            font=("Segoe UI", 10, "bold"),
            fg="white",
            bg="#10b981",
            activebackground="#059669",
            relief="flat",
            bd=0,
            padx=12,
            pady=12,
            cursor="hand2"
        )
        self.generate_btn.pack(fill="x", padx=12, pady=(0, 8))
        
        # Stop Button
        self.exit_btn = Button(
            ctrl_card,
            text="⊘ Stop Process",
            command=self._emergency_exit,
            font=("Segoe UI", 9, "bold"),
            fg="white",
            bg="#ef4444",
            activebackground="#dc2626",
            relief="flat",
            bd=0,
            padx=12,
            pady=10,
            state="disabled",
            cursor="hand2"
        )
        self.exit_btn.pack(fill="x", padx=12, pady=(0, 12))
        
        # Status Card
        status_card = TkFrame(right_panel, bg="white", relief="solid", bd=1)
        status_card.pack(fill="both", expand=True, padx=15, pady=10)
        
        Label(
            status_card,
            text="Status",
            font=("Segoe UI", 10, "bold"),
            fg="#475569",
            bg="white"
        ).pack(anchor="w", padx=12, pady=(10, 8))
        
        self.status_label = Label(
            status_card,
            textvariable=self.status_var,
            font=("Segoe UI", 9),
            fg="#16a34a",
            bg="white",
            anchor="nw",
            justify="left",
            wraplength=280
        )
        self.status_label.pack(anchor="nw", fill="both", expand=True, padx=12, pady=(0, 10))
        
        # Progress bar
        self.progress = Progressbar(status_card, mode='indeterminate')
        self.progress.pack(fill="x", padx=12, pady=(0, 12))

    def _select_inspection_pdf(self):
        """Select inspection PDF file."""
        file_path = filedialog.askopenfilename(
            title="Select Inspection Report PDF",
            filetypes=[("PDF files", "*.pdf"), ("All files", "*.*")]
        )
        if file_path:
            self.inspection_pdf = file_path
            self.inspection_label.set(f"✓ {Path(file_path).name}")
            self.status_label.configure(fg="#16a34a")
            self.status_var.set("✓ Inspection PDF selected")

    def _signal_handler(self, signum, frame):
        """Handle Ctrl+C gracefully."""
        logger.warning("Ctrl+C received - initiating emergency exit")
        self._emergency_exit()
    
    def _on_closing(self):
        """Handle window close button."""
        if self.is_processing:
            response = messagebox.askyesno(
                "Processing Active",
                "Report generation is in progress.\n\n"
                "Are you sure you want to exit?\n"
                "(This will force stop the process)"
            )
            if not response:
                return
        
        self._emergency_exit()
    
    def _emergency_exit(self):
        """Emergency exit - forcefully stops processing and cleans up."""
        logger.warning("EMERGENCY EXIT TRIGGERED")
        
        self.should_exit = True
        self.is_processing = False
        
        # Cancel timeout timer
        self._cancel_timeout_timer()
        
        # Stop progress bar
        try:
            self.progress.stop()
        except:
            pass
        
        # Disable exit button, enable generate button
        self.exit_btn.config(state="disabled")
        self.generate_btn.config(state="normal")
        
        self.status_label.configure(fg="#dc2626")
        self.status_var.set("✗ Process terminated by user")
        logger.info("Emergency exit complete - Ready for new report")
        
        # Check if we should close the window (when called from _on_closing)
        if self.root.winfo_exists():
            self.root.after(500, self.root.quit)

    def _select_thermal_pdf(self):
        """Select thermal PDF file."""
        file_path = filedialog.askopenfilename(
            title="Select Thermal Report PDF",
            filetypes=[("PDF files", "*.pdf"), ("All files", "*.*")]
        )
        if file_path:
            self.thermal_pdf = file_path
            self.thermal_label.set(f"✓ {Path(file_path).name}")
            self.status_label.configure(fg="#16a34a")
            self.status_var.set("✓ Thermal PDF selected")

    def _generate_report_thread(self):
        """Generate report in background thread to prevent UI freeze."""
        if not self._validate_inputs():
            return
        
        self.is_processing = True
        self.should_exit = False
        self.generate_btn.config(state="disabled")
        self.exit_btn.config(state="normal")  # Enable exit button
        self.progress.start()
        
        # Start report generation thread with timeout protection
        self.report_thread = threading.Thread(target=self._generate_report_with_timeout, daemon=True)
        self.report_thread.daemon = True
        self.report_thread.start()
        
        # Set timeout timer
        self._set_timeout_timer()

    def _set_timeout_timer(self):
        """Set a timeout timer for the report generation."""
        # Schedule a check for timeout after REPORT_TIMEOUT seconds
        self.timeout_timer = self.root.after(
            REPORT_TIMEOUT * 1000,
            self._on_report_timeout
        )
    
    def _cancel_timeout_timer(self):
        """Cancel the timeout timer if still running."""
        if self.timeout_timer:
            self.root.after_cancel(self.timeout_timer)
            self.timeout_timer = None
    
    def _on_report_timeout(self):
        """Handle report generation timeout."""
        logger.error(f"Report generation exceeded {REPORT_TIMEOUT} seconds timeout")
        self.status_var.set(f"✗ Timeout: Report generation exceeded {REPORT_TIMEOUT}s limit")
        
        # Force exit the thread
        self.should_exit = True
        
        messagebox.showerror(
            "Timeout Error - Force Exiting",
            f"Report generation took too long (>{REPORT_TIMEOUT}s)\n\n"
            "The process has been forcefully terminated to prevent PC hang.\n\n"
            "Troubleshooting:\n"
            "- Check Internet connection\n"
            "- Verify API key validity\n"
            "- Use smaller PDF files (< 50MB)\n\n"
            "To increase timeout, edit .env:\n"
            "REPORT_TIMEOUT=600  (10 minutes)"
        )
        self.progress.stop()
        self.generate_btn.config(state="normal")
        self.exit_btn.config(state="disabled")
        self.is_processing = False
    
    def _generate_report_with_timeout(self):
        """Wrapper to call report generation with timeout monitoring."""
        try:
            self._generate_report()
        except Exception as e:
            if self.should_exit:
                logger.info("Report generation cancelled by user")
            else:
                logger.error(f"Report generation failed: {e}", exc_info=True)
        finally:
            # Ensure timeout timer is cancelled
            self._cancel_timeout_timer()
            self.is_processing = False
            try:
                self.exit_btn.config(state="disabled")
            except:
                pass
    
    def _validate_inputs(self) -> bool:
        """Validate that both PDFs are selected."""
        if not self.inspection_pdf:
            messagebox.showerror("Error", "Please select an Inspection PDF")
            self.status_var.set("⚠ Missing: Select Inspection PDF")
            return False
        
        if not self.thermal_pdf:
            messagebox.showerror("Error", "Please select a Thermal PDF")
            self.status_var.set("⚠ Missing: Select Thermal PDF")
            return False
        
        if not os.path.exists(self.inspection_pdf):
            messagebox.showerror("Error", f"Inspection PDF not found: {self.inspection_pdf}")
            self.status_var.set("✗ File not found")
            return False
        
        if not os.path.exists(self.thermal_pdf):
            messagebox.showerror("Error", f"Thermal PDF not found: {self.thermal_pdf}")
            self.status_var.set("✗ File not found")
            return False
        
        return True

    def _generate_report(self):
        """Main report generation workflow (runs in background thread)."""
        try:
            self.status_label.configure(fg="#2563eb")
            self.status_var.set("⏳ Step 1/6: Extracting PDFs...")
            
            # Step 1: Extract text from PDFs
            logger.info("=== DDR Report Generation Started ===")
            
            # Check exit flag
            if self.should_exit:
                logger.info("Exit requested during PDF extraction")
                return
            
            inspection_text = PDFExtractor.extract_text(self.inspection_pdf)
            thermal_text = PDFExtractor.extract_text(self.thermal_pdf)
            
            # Step 2: Chunk large texts
            # Check exit flag
            if self.should_exit:
                logger.info("Exit requested after PDF extraction")
                return
            
            self.status_label.configure(fg="#2563eb")
            self.status_var.set("⏳ Step 2/6: Chunking text...")
            
            # Check if texts are unreasonably large (> 2MB combined)
            total_chars = len(inspection_text) + len(thermal_text)
            if total_chars > 2_000_000:
                logger.warning(f"Combined text is very large: {total_chars:,} chars. This may slow processing.")
            
            chunker = TextChunker()
            inspection_chunks = chunker.split_text(inspection_text)
            thermal_chunks = chunker.split_text(thermal_text)
            
            logger.info(f"Inspection chunks: {len(inspection_chunks)}, Thermal chunks: {len(thermal_chunks)}")
            
            # Step 3: Extract structured data from LLM
            # Check exit flag
            if self.should_exit:
                logger.info("Exit requested before LLM extraction")
                return
            
            self.status_label.configure(fg="#2563eb")
            self.status_var.set("⏳ Step 3/6: Extracting findings...")
            logger.info(f"Timeout for LLM extraction: {DEFAULT_TIMEOUT}s")
            
            llm = LLMExtractor()
            
            # Process chunks and collect results
            extraction_results = []
            
            # For efficiency, use first 2 chunks from each to limit API calls and memory
            # Full processing of all chunks would be too slow for typical PDFs
            combined_inspection = "\n".join(inspection_chunks[:min(2, len(inspection_chunks))])
            combined_thermal = "\n".join(thermal_chunks[:min(2, len(thermal_chunks))])
            
            # Safety check: limit combined text size sent to API
            if len(combined_inspection) > 12000:
                combined_inspection = combined_inspection[:12000] + "\n[...truncated...]"
            if len(combined_thermal) > 12000:
                combined_thermal = combined_thermal[:12000] + "\n[...truncated...]"
            
            try:
                extraction_data = llm.extract_structured_data(
                    combined_inspection,
                    combined_thermal
                )
                # Validate extraction before adding
                if not extraction_data or not extraction_data.get("areas"):
                    raise ValueError("LLM extraction returned empty or invalid data")
                extraction_results.append(extraction_data)
            except (TimeoutError, Exception) as e:
                logger.error(f"LLM extraction error: {e}")
                if "timeout" in str(e).lower():
                    raise TimeoutError(f"LLM extraction exceeded timeout: {e}")
                raise
            
            if not extraction_results:
                raise ValueError("No valid extraction results obtained")
            
            # Step 4: Merge findings
            # Check exit flag
            if self.should_exit:
                logger.info("Exit requested before merging")
                return
            
            self.status_label.configure(fg="#2563eb")
            self.status_var.set("⏳ Step 4/6: Merging data...")
            
            self.merged_data = DataMerger.merge_findings(extraction_results)
            
            # Detect conflicts
            for area in self.merged_data["areas"]:
                conflicts = DataMerger.detect_conflicts(area)
                if conflicts:
                    area["conflicts"].extend(conflicts)
            
            # Fill missing fields
            self.merged_data = DataMerger.fill_missing_fields(self.merged_data)
            
            # Validate
            is_valid, issues = DataValidator.validate_completion(self.merged_data)
            if not is_valid:
                logger.warning(f"Validation issues: {issues}")
            
            logger.info(f"Merged data: {json.dumps(self.merged_data, indent=2)}")
            
            # Step 5: Generate final DDR report
            # Check exit flag
            if self.should_exit:
                logger.info("Exit requested before DDR generation")
                return
            
            self.status_label.configure(fg="#2563eb")
            self.status_var.set("⏳ Step 5/6: Generating report...")
            logger.info(f"Timeout for DDR report generation: {REPORT_GEN_TIMEOUT}s")
            
            try:
                ddr_text = llm.generate_ddr_report(self.merged_data)
            except (TimeoutError, Exception) as e:
                logger.error(f"DDR report generation error: {e}")
                if "timeout" in str(e).lower():
                    raise TimeoutError(f"DDR report generation exceeded timeout: {e}")
                raise
            
            logger.info(f"DDR Report generated: {len(ddr_text)} characters")
            
            # Step 6: Generate PDF
            # Check exit flag
            if self.should_exit:
                logger.info("Exit requested before PDF generation")
                return
            
            self.status_label.configure(fg="#2563eb")
            self.status_var.set("⏳ Step 6/6: Creating PDF...")
            
            generator = DDRReportGenerator()
            output_path = generator.generate(ddr_text, self.merged_data)
            
            # Step 7: Complete
            # Check exit flag
            if self.should_exit:
                logger.info("Exit requested before completion")
                return
            
            self.status_label.configure(fg="#16a34a")
            self.status_var.set(f"✓ Complete! Report saved to:\n{output_path}")
            
            if not self.should_exit:
                messagebox.showinfo(
                    "Success",
                    f"DDR Report generated successfully!\n\nSaved to:\n{output_path}"
                )
                logger.info("=== DDR Report Generation Complete ===")
            else:
                logger.info("Exit was requested - report generation was interrupted")
            
        except TimeoutError as e:
            if not self.should_exit:  # If not already exiting
                logger.error(f"Timeout during report generation: {e}")
                self.status_var.set(f"✗ Timeout: {str(e)}")
                messagebox.showerror(
                    "Timeout Error",
                    f"Report generation timed out:\n\n{str(e)}\n\n"
                    "Please check your API key and try again.\n"
                    "You can adjust timeouts in .env file."
                )
        except Exception as e:
            if not self.should_exit:  # If not already exiting
                error_msg = str(e)
                logger.error(f"Error generating report: {e}", exc_info=True)
                self.status_var.set(f"Error: {str(e)}")
                
                # Check for specific error types
                if "GEMINI RATE LIMIT" in error_msg or "rate_limit" in error_msg.lower():
                    messagebox.showerror(
                        "❌ Gemini Rate Limit",
                        error_msg
                    )
                elif "GEMINI" in error_msg or "OPENAI" in error_msg or "insufficient_quota" in error_msg:
                    messagebox.showerror(
                        "❌ API Error",
                        error_msg
                    )
                elif "API" in error_msg or "timeout" in error_msg.lower():
                    messagebox.showerror(
                        "❌ API Error",
                        f"API Error:\n\n{error_msg}\n\n"
                        "Please check:\n"
                        "- Your internet connection\n"
                        "- Your Gemini API key in .env\n"
                        "- Rate limits (60 req/min for free tier)"
                    )
                else:
                    messagebox.showerror("❌ Error", f"Failed to generate report:\n\n{str(e)}")
        
        finally:
            try:
                self.progress.stop()
            except:
                pass
            self.generate_btn.config(state="normal")
            self.exit_btn.config(state="disabled")
            self._cancel_timeout_timer()
            self.is_processing = False


def main():
    """Run the application."""
    root = Tk()
    app = DDRApplication(root)
    root.mainloop()


if __name__ == "__main__":
    main()
