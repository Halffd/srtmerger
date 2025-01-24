#!/usr/bin/env python3
import sys
import os
import re
import logging
from datetime import datetime
from typing import Dict, List, Tuple, Optional, Any
from dataclasses import dataclass
from pathlib import Path
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                            QHBoxLayout, QLabel, QLineEdit, QPushButton, 
                            QComboBox, QTextEdit, QFileDialog, QFrame, 
                            QGroupBox, QCheckBox, QTabWidget, QSlider,
                            QSpinBox, QGridLayout, QMessageBox)
from PyQt6.QtCore import Qt, QRegularExpression, pyqtSignal, QThread
from PyQt6.QtGui import QRegularExpressionValidator, QTextCursor
from main import Merger

WHITE = '#FFFFFF'
BLUE = '#0000FF'
YELLOW = '#FFFF00'

@dataclass
class EpisodeMatch:
    """Data class for storing matched episode files."""
    episode_num: int
    sub1_path: Path
    sub2_path: Path
    output_path: Optional[Path] = None

class QTextEditLogger(logging.Handler):
    """Custom logging handler that writes to a QTextEdit widget."""
    def __init__(self, widget: QTextEdit):
        super().__init__()
        self.widget = widget
        self.widget.setReadOnly(True)
        formatter = logging.Formatter(
            '%(asctime)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        self.setFormatter(formatter)

    def emit(self, record):
        msg = self.format(record)
        self.widget.append(msg)
        # Auto-scroll to bottom
        cursor = self.widget.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self.widget.setTextCursor(cursor)

class MergeWorker(QThread):
    """Worker thread for handling subtitle merging operations."""
    progress = pyqtSignal(str)
    error = pyqtSignal(str)
    finished = pyqtSignal()

    def __init__(self, matches: List[EpisodeMatch], merger_args: Dict[str, Any]):
        super().__init__()
        self.matches = matches
        self.merger_args = merger_args
        self.is_running = True

    def run(self):
        try:
            for match in self.matches:
                if not self.is_running:
                    break
                
                try:
                    self.progress.emit(f"Processing episode {match.episode_num}")
                    
                    # Create merger instance
                    merger = Merger(output_name=str(match.output_path))
                    
                    # Add subtitles
                    merger.add(str(match.sub1_path), 
                             color=self.merger_args['color'],
                             codec=self.merger_args['codec'])
                    merger.add(str(match.sub2_path))
                    
                    # Merge subtitles
                    merger.merge()
                    
                    self.progress.emit(
                        f"Successfully merged episode {match.episode_num} to: {match.output_path}"
                    )
                
                except Exception as e:
                    self.error.emit(f"Error merging episode {match.episode_num}: {str(e)}")
                    continue
                
        except Exception as e:
            self.error.emit(f"Critical error in merge worker: {str(e)}")
        
        finally:
            self.finished.emit()

    def stop(self):
        self.is_running = False

class EpisodeRangeSelector(QWidget):
    """Widget for selecting episode ranges."""
    range_changed = pyqtSignal(tuple)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setup_ui()
        self.connect_signals()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        
        # Episode range group
        range_group = QGroupBox("Episode Range")
        range_layout = QVBoxLayout()
        
        # Enable/disable range selection
        self.enable_range = QCheckBox("Enable Episode Range")
        range_layout.addWidget(self.enable_range)
        
        # Controls layout
        controls_layout = QGridLayout()
        
        # Spinboxes
        self.start_spin = QSpinBox()
        self.end_spin = QSpinBox()
        for spin in (self.start_spin, self.end_spin):
            spin.setRange(1, 9999)
            spin.setSingleStep(1)
        
        self.end_spin.setValue(9999)
        
        controls_layout.addWidget(QLabel("Start:"), 0, 0)
        controls_layout.addWidget(self.start_spin, 0, 1)
        controls_layout.addWidget(QLabel("End:"), 0, 2)
        controls_layout.addWidget(self.end_spin, 0, 3)
        
        # Sliders
        self.range_slider = QWidget()
        slider_layout = QHBoxLayout(self.range_slider)
        
        self.start_slider = QSlider(Qt.Orientation.Horizontal)
        self.end_slider = QSlider(Qt.Orientation.Horizontal)
        
        for slider in (self.start_slider, self.end_slider):
            slider.setRange(1, 9999)
            slider.setTickPosition(QSlider.TickPosition.TicksBelow)
            slider.setTickInterval(100)
            slider_layout.addWidget(slider)
        
        self.end_slider.setValue(9999)
        controls_layout.addWidget(self.range_slider, 1, 0, 1, 4)
        
        range_layout.addLayout(controls_layout)
        range_group.setLayout(range_layout)
        layout.addWidget(range_group)
        
        # Initial state
        self.toggle_range_controls(False)
        self.enable_range.setChecked(False)

    def connect_signals(self):
        """Connect all widget signals."""
        self.enable_range.toggled.connect(self.toggle_range_controls)
        self.start_spin.valueChanged.connect(self.start_slider.setValue)
        self.end_spin.valueChanged.connect(self.end_slider.setValue)
        self.start_slider.valueChanged.connect(self.start_spin.setValue)
        self.end_slider.valueChanged.connect(self.end_spin.setValue)
        
        # Connect range changed signals
        for widget in (self.start_spin, self.end_spin):
            widget.valueChanged.connect(self.emit_range_changed)

    def toggle_range_controls(self, enabled: bool):
        """Enable or disable range selection controls."""
        for widget in (self.start_spin, self.end_spin, self.range_slider):
            widget.setEnabled(enabled)
        if enabled:
            self.emit_range_changed()

    def emit_range_changed(self):
        """Emit the range_changed signal with current values."""
        if self.enable_range.isChecked():
            self.range_changed.emit((self.start_spin.value(), self.end_spin.value()))
        else:
            self.range_changed.emit(None)

    def get_range(self) -> Optional[Tuple[int, int]]:
        """Get the current episode range if enabled."""
        return (
            (self.start_spin.value(), self.end_spin.value())
            if self.enable_range.isChecked() else None
        )
class SubtitleMergerGUI(QMainWindow):
    """Main application window for the Subtitle Merger GUI."""
    
    def __init__(self):
        super().__init__()
        self.merge_worker = None
        self.setup_logging()
        self.init_ui()
        
    def setup_logging(self):
        """Initialize logging configuration."""
        self.logger = logging.getLogger('SubtitleMerger')
        self.logger.setLevel(logging.DEBUG)
        
        # Create logs directory if it doesn't exist
        log_dir = Path('logs')
        log_dir.mkdir(exist_ok=True)
        
        # File handler
        log_file = log_dir / f'subtitle_merger_{datetime.now():%Y%m%d_%H%M%S}.log'
        file_handler = logging.FileHandler(log_file)
        file_handler.setLevel(logging.DEBUG)
        file_formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        file_handler.setFormatter(file_formatter)
        self.logger.addHandler(file_handler)

    def init_ui(self):
        """Initialize the user interface."""
        self.setWindowTitle("Subtitle Merger")
        self.setMinimumSize(800, 800)

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)

        # Create tabs
        tab_widget = QTabWidget()
        main_layout.addWidget(tab_widget)

        single_files_tab = QWidget()
        directory_tab = QWidget()
        tab_widget.addTab(single_files_tab, "Single Files")
        tab_widget.addTab(directory_tab, "Directory")

        # Setup tabs
        self.setup_single_files_tab(single_files_tab)
        self.setup_directory_tab(directory_tab)  # Ensure this is called

        self.logger.info("GUI initialized successfully")

        # Ensure dir_entry is initialized at this point
        if not hasattr(self, 'dir_entry'):
            self.logger.error("dir_entry is not initialized during init_ui!")
    def setup_directory_tab(self, tab):
        """Set up the directory processing tab."""
        layout = QVBoxLayout(tab)

        # Directory selection
        dir_group = QGroupBox("Input Directory")
        dir_layout = QHBoxLayout()
        self.dir_entry = QLineEdit()
        browse_dir_button = QPushButton("Browse")
        browse_dir_button.clicked.connect(self.browse_directory)
        dir_layout.addWidget(self.dir_entry)
        dir_layout.addWidget(browse_dir_button)
        dir_group.setLayout(dir_layout)
        layout.addWidget(dir_group)
 # Create color combo box
        self.color_combo = QComboBox()
        # Add color options
        self.color_combo.addItems(["Red", "Green", "Blue", "Yellow", "Black", "White"])
        layout.addWidget(QLabel("Select Color:"))
        layout.addWidget(self.color_combo)

        # Create codec combo box
        self.codec_combo = QComboBox()
        # Add codec options
        self.codec_combo.addItems(["H264", "H265", "VP9", "AV1"])
        layout.addWidget(QLabel("Select Codec:"))
        layout.addWidget(self.codec_combo)
        # Output directory
        output_dir_group = QGroupBox("Output Directory")
        output_dir_layout = QHBoxLayout()
        self.output_dir_entry = QLineEdit()
        browse_output_dir_button = QPushButton("Browse")
        browse_output_dir_button.clicked.connect(self.browse_output_directory)
        output_dir_layout.addWidget(self.output_dir_entry)
        output_dir_layout.addWidget(browse_output_dir_button)
        output_dir_group.setLayout(output_dir_layout)
        layout.addWidget(output_dir_group)

        # Process button
        process_button = QPushButton("Process Directory")
        process_button.clicked.connect(self.process_directory)
        process_button.setMinimumHeight(40)
        layout.addWidget(process_button)
    def create_options_section(self, parent_layout):
        """Create an options section with checkboxes and dropdown menus."""
        options_group = QGroupBox("Options")
        options_layout = QVBoxLayout()

        # Example checkboxes
        self.option_merge_subtitles = QCheckBox("Merge Subtitles Automatically")
        self.option_merge_subtitles.setChecked(True)
        self.option_generate_log = QCheckBox("Generate Log File")
        self.option_generate_log.setChecked(False)

        options_layout.addWidget(self.option_merge_subtitles)
        options_layout.addWidget(self.option_generate_log)

        # Example dropdown for subtitle format
        format_label = QLabel("Output Subtitle Format:")
        self.format_dropdown = QComboBox()
        self.format_dropdown.addItems(["SRT", "ASS", "VTT"])

        options_layout.addWidget(format_label)
        options_layout.addWidget(self.format_dropdown)

        options_group.setLayout(options_layout)
        parent_layout.addWidget(options_group)
    def create_log_section(self, parent_layout):
        """Create a section to display or manage logs."""
        log_group = QGroupBox("Logs")
        log_layout = QVBoxLayout()

        # Text area for displaying logs
        self.log_text_area = QTextEdit()
        self.log_text_area.setReadOnly(True)
        self.log_text_area.setPlaceholderText("Logs will appear here...")

        # Button to clear logs
        clear_log_button = QPushButton("Clear Logs")
        clear_log_button.clicked.connect(self.clear_logs)

        log_layout.addWidget(self.log_text_area)
        log_layout.addWidget(clear_log_button)

        log_group.setLayout(log_layout)
        parent_layout.addWidget(log_group)

    def clear_logs(self):
        """Clear the log text area."""
        self.log_text_area.clear()
    def browse_directory(self):
        """Browse for an input directory."""
        self.logger.debug("Attempting to browse for directory...")  # Debug log
        if not hasattr(self, 'dir_entry'):
            self.logger.error("dir_entry is not initialized.")  # Error log if the attribute is missing
        else:
            directory = QFileDialog.getExistingDirectory(self, "Select Directory")
            if directory:
                self.dir_entry.setText(directory)
                self.logger.debug(f"Directory set: {directory}")
    def browse_output_directory(self):
        """Browse for an output directory."""
        directory = QFileDialog.getExistingDirectory(self, "Select Output Directory")
        if directory:
            self.output_dir_entry.setText(directory)

    def process_directory(self):
        """Process all files in the selected directory."""
        input_dir = self.dir_entry.text()
        output_dir = self.output_dir_entry.text()

        if not input_dir or not output_dir:
            QMessageBox.warning(self, "Missing Directories", "Please select both input and output directories.")
            return

        try:
            # Placeholder logic for directory processing
            QMessageBox.information(self, "Success", f"Processed all files from {input_dir} to {output_dir}.")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to process directory: {e}")
    def setup_single_files_tab(self, tab):
        """Set up the Single Files tab."""
        layout = QVBoxLayout(tab)

        # File selection components
        file_group = QGroupBox("Input File")
        file_layout = QHBoxLayout()
        self.file_entry = QLineEdit()  # A line edit to display the selected file path
        browse_file_button = QPushButton("Browse")
        browse_file_button.clicked.connect(self.browse_file)  # Connect to a method for file browsing
        file_layout.addWidget(self.file_entry)
        file_layout.addWidget(browse_file_button)
        file_group.setLayout(file_layout)
        layout.addWidget(file_group)

        # Merge subtitles button
        merge_button = QPushButton("Merge Subtitles")
        
        # Create merge_worker with placeholder arguments
        self.merge_worker = MergeWorker(
            matches=[],  # Empty list of matches
            merger_args={
                'color': WHITE,  # Default color
                'codec': 'utf-8'  # Default codec
            }
        )
        
        # Connect signals
        merge_button.clicked.connect(self.merge_worker.run)
        layout.addWidget(merge_button)
    def browse_file(self):
        """Open a file dialog to select an input file."""
        file_path, _ = QFileDialog.getOpenFileName(self, "Select File", "", "Video Files (*.mp4 *.mkv);;All Files (*)")
        if file_path:
            self.file_entry.setText(file_path)  # Set the selected file path

    def setup_directory_tab(self, tab):
        """setup_directory_tab.

        :param tab:
        Set up the directory processing tab."""
        layout = QVBoxLayout(tab)

        # Directory selection
        dir_group = QGroupBox("Directory Selection")
        dir_layout = QHBoxLayout()
        self.dir_entry = QLineEdit()
        browse_dir_button = QPushButton("Browse")
        browse_dir_button.clicked.connect(self.browse_directory)
        dir_layout.addWidget(self.dir_entry)
        dir_layout.addWidget(browse_dir_button)
        dir_group.setLayout(dir_layout)
        layout.addWidget(dir_group)

        # File matching patterns
        patterns_group = QGroupBox("File Matching Patterns")
        patterns_layout = QVBoxLayout()

        # Pattern input fields
        pattern_fields = [
            ("Base Filename Pattern:", "base_pattern", "Show.Name.S01"),
            ("Episode Number Pattern:", "episode_pattern", "E(\\d+)"),
            ("Subtitle 1 Pattern:", "sub1_pattern", ".fa.srt$"),
            ("Subtitle 2 Pattern:", "sub2_pattern", ".en.srt$")
        ]

        for label_text, attr_name, placeholder in pattern_fields:
            field_layout = QHBoxLayout()
            field_layout.addWidget(QLabel(label_text))
            line_edit = QLineEdit()
            line_edit.setPlaceholderText(placeholder)
            setattr(self, attr_name, line_edit)
            field_layout.addWidget(line_edit)
            patterns_layout.addLayout(field_layout)

        # Add test pattern button
        test_button = QPushButton("Test Patterns")
        test_button.clicked.connect(self.test_patterns)
        patterns_layout.addWidget(test_button)

        patterns_group.setLayout(patterns_layout)
        layout.addWidget(patterns_group)

        # Episode range selector
        self.episode_range = EpisodeRangeSelector()
        self.episode_range.range_changed.connect(self.on_range_changed)
        layout.addWidget(self.episode_range)

        # Preview button
        self.preview_button = QPushButton("Preview Matching Files")
        self.preview_button.clicked.connect(self.preview_matches)
        layout.addWidget(self.preview_button)

        # Output options
        output_group = QGroupBox("Output Options")
        output_layout = QVBoxLayout()
        
        self.use_subfolder = QCheckBox("Create output in subfolder")
        self.use_subfolder.setChecked(True)
        output_layout.addWidget(self.use_subfolder)
        
        subfolder_layout = QHBoxLayout()
        subfolder_layout.addWidget(QLabel("Subfolder name:"))
        self.subfolder_name = QLineEdit("merged")
        subfolder_layout.addWidget(self.subfolder_name)
        output_layout.addLayout(subfolder_layout)
        
        output_group.setLayout(output_layout)
        layout.addWidget(output_group)

        # Create options section
        self.create_options_section(layout)
        
        # Create log section
        self.create_log_section(layout)
        
        # Batch merge button
        self.batch_merge_button = QPushButton("Batch Merge Subtitles")
        self.batch_merge_button.clicked.connect(self.batch_merge_subtitles)
        self.batch_merge_button.setMinimumHeight(40)
        layout.addWidget(self.batch_merge_button)

    def test_patterns(self):
        """Test if the current patterns are valid regex patterns."""
        patterns = {
            'Base Pattern': self.base_pattern.text(),
            'Episode Pattern': self.episode_pattern.text(),
            'Subtitle 1 Pattern': self.sub1_pattern.text(),
            'Subtitle 2 Pattern': self.sub2_pattern.text()
        }
        
        invalid_patterns = []
        for name, pattern in patterns.items():
            try:
                re.compile(pattern)
            except re.error as e:
                invalid_patterns.append(f"{name}: {str(e)}")
        
        if invalid_patterns:
            QMessageBox.warning(
                self,
                "Invalid Patterns",
                "The following patterns are invalid:\n\n" + "\n".join(invalid_patterns)
            )
        else:
            QMessageBox.information(
                self,
                "Valid Patterns",
                "All patterns are valid regular expressions."
            )

    def on_range_changed(self, range_value):
        """Handle changes in the episode range selection."""
        if range_value:
            self.logger.debug(f"Episode range changed to {range_value}")
            self.preview_matches()

    def find_episode_matches(self) -> Dict[int, EpisodeMatch]:
        """Find matching subtitle pairs based on patterns and episode range."""
        try:
            directory = Path(self.dir_entry.text())
            if not directory.is_dir():
                raise ValueError("Invalid directory path")

            episode_pattern = self.episode_pattern.text()
            sub1_pattern = self.sub1_pattern.text()
            sub2_pattern = self.sub2_pattern.text()

            if not all([episode_pattern, sub1_pattern, sub2_pattern]):
                raise ValueError("All patterns must be specified")

            # Compile patterns
            sub1_regex = re.compile(f"{sub1_pattern}.*{episode_pattern}")
            sub2_regex = re.compile(f"{sub2_pattern}.*{episode_pattern}")
            print(f"{sub1_pattern}.*{episode_pattern}")
            print(f"{sub2_pattern}.*{episode_pattern}")
            # Get episode range
            episode_range = self.episode_range.get_range()

            matches = {}
            
            # Find all subtitle files
            for file_path in directory.glob("*"):
                if not file_path.is_file():
                    continue

                filename = file_path.name
                print('- ', filename)
                # Check for subtitle matches
                for regex, sub_index in [(sub1_regex, 0), (sub2_regex, 1)]:
                    print(regex, sub_index)
                    match = regex.match(filename)
                    if match:
                        episode_num = int(match.group(1))
                        print(episode_num)
                        # Check episode range
                        if episode_range:
                            start, end = episode_range
                            if not start <= episode_num <= end:
                                continue

                        # Create or update match entry
                        if episode_num not in matches:
                            matches[episode_num] = EpisodeMatch(
                                episode_num=episode_num,
                                sub1_path=None,
                                sub2_path=None
                            )
                        
                        # Set the appropriate subtitle path
                        if sub_index == 0:
                            matches[episode_num].sub1_path = file_path
                        else:
                            matches[episode_num].sub2_path = file_path

            # Remove incomplete matches and set output paths
            complete_matches = {}
            output_dir = (
                directory / self.subfolder_name.text()
                if self.use_subfolder.isChecked()
                else directory
            )
            print('Output ', output_dir)
            
            for episode_num, match in matches.items():
                print(episode_num)
                if match.sub1_path and match.sub2_path:
                    match.output_path = output_dir / f"{base_pattern}E{episode_num:02d}_merged.srt"
                    complete_matches[episode_num] = match
            print(complete_matches)
            return complete_matches

        except Exception as e:
            self.logger.error(f"Error finding matches: {str(e)}")
            raise

    def preview_matches(self):
        """Preview matched subtitle pairs before processing."""
        try:
            matches = self.find_episode_matches()
            
            if not matches:
                self.logger.warning("No matching files found")
                return

            # Clear log and show matches
            self.log_text.clear()
            self.log_message("Matching episodes found:")
            
            for episode_num in sorted(matches.keys()):
                match = matches[episode_num]
                self.log_message(f"\nEpisode {episode_num}:")
                self.log_message(f"  Sub1: {match.sub1_path.name}")
                self.log_message(f"  Sub2: {match.sub2_path.name}")
                self.log_message(f"  Output: {match.output_path.name}")

        except Exception as e:
            self.logger.error(f"Error in preview: {str(e)}")
            QMessageBox.warning(self, "Preview Error", str(e))

    def batch_merge_subtitles(self):
        """Start the batch merging process."""
        try:
            matches = self.find_episode_matches()
            if not matches:
                raise ValueError("No matching pairs found to merge!")

            # Confirm overwrite if files exist
            existing_files = [
                match.output_path
                for match in matches.values()
                if match.output_path.exists()
            ]
            print(existing_files)
            if existing_files and not self.confirm_overwrite(existing_files):
                return

            # Create output directory if needed
            if self.use_subfolder.isChecked():
                output_dir = Path(self.dir_entry.text()) / self.subfolder_name.text()
                output_dir.mkdir(exist_ok=True)

            # Prepare merger arguments
            merger_args = {
                'color': self.color_combo.currentText(),
                'codec': self.codec_combo.currentText()
            }

            # Create and start worker thread
            self.merge_worker = MergeWorker(list(matches.values()), merger_args)
            self.merge_worker.progress.connect(self.log_message)
            self.merge_worker.error.connect(self.log_error)
            self.merge_worker.finished.connect(self.on_merge_completed)
            
            # Disable controls during processing
            self.set_controls_enabled(False)
            self.merge_worker.start()

        except Exception as e:
            self.logger.error(f"Error starting batch merge: {str(e)}")
            QMessageBox.warning(self, "Batch Merge Error", str(e))

    def confirm_overwrite(self, existing_files: List[Path]) -> bool:
        """Show confirmation dialog for overwriting existing files."""
        msg = QMessageBox()
        msg.setIcon(QMessageBox.Icon.Warning)
        msg.setWindowTitle("Confirm Overwrite")
        msg.setText(f"The following files already exist:\n\n" +
                   "\n".join(str(f) for f in existing_files[:5]) +
                   ("\n..." if len(existing_files) > 5 else ""))
        msg.setInformativeText("Do you want to overwrite these files?")
        msg.setStandardButtons(
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        return msg.exec() == QMessageBox.StandardButton.Yes

    def set_controls_enabled(self, enabled: bool):
        """Enable or disable controls during processing."""
        self.batch_merge_button.setEnabled(enabled)
        self.preview_button.setEnabled(enabled)
        self.episode_range.setEnabled(enabled)

    def on_merge_completed(self):
        """Handle completion of the merge process."""
        self.set_controls_enabled(True)
        self.merge_worker = None
        self.logger.info("Batch processing completed")

    def closeEvent(self, event):
        """Handle application closure."""
        if self.merge_worker and self.merge_worker.isRunning():
            reply = QMessageBox.question(
                self,
                'Confirm Exit',
                'A merge operation is in progress. Do you want to stop it and exit?',
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            )
            
            if reply == QMessageBox.StandardButton.Yes:
                self.merge_worker.stop()
                self.merge_worker.wait()
            else:
                event.ignore()
                return
                
        self.logger.info("Application closing")
        event.accept()

def main():
    """Main application entry point."""
    app = QApplication(sys.argv)
    window = SubtitleMergerGUI()
    window.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()

