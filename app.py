import sys
import os
import json
import re
import time
import requests
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QTabWidget, QVBoxLayout, 
                            QHBoxLayout, QTextEdit, QLabel, QComboBox, QPushButton, 
                            QProgressBar, QSpinBox, QSlider, QFileDialog, QStatusBar, 
                            QLineEdit, QGroupBox, QSplitter, QGridLayout, QCheckBox, 
                            QMessageBox)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QSettings
from PyQt5.QtGui import QFont, QTextCursor, QIcon


class SrtParser:
    """
    Class to handle parsing and formatting of SRT subtitle files
    """
    @staticmethod
    def parse_srt(srt_content):
        """Parse SRT content into a list of subtitle entries"""
        # Split the content by double newline to get individual subtitle blocks
        subtitle_blocks = re.split(r'\n\s*\n', srt_content.strip())
        subtitles = []
        
        for block in subtitle_blocks:
            if not block.strip():
                continue
                
            lines = block.strip().split('\n')
            if len(lines) < 3:
                continue
                
            # First line is the subtitle number
            try:
                subtitle_number = int(lines[0].strip())
            except ValueError:
                continue
                
            # Second line is the timestamp
            timestamp_match = re.match(r'(\d{2}:\d{2}:\d{2},\d{3}) --> (\d{2}:\d{2}:\d{2},\d{3})', lines[1])
            if not timestamp_match:
                continue
                
            start_time = timestamp_match.group(1)
            end_time = timestamp_match.group(2)
            
            # Remaining lines are the subtitle text
            subtitle_text = '\n'.join(lines[2:])
            
            subtitles.append({
                'number': subtitle_number,
                'start_time': start_time,
                'end_time': end_time,
                'text': subtitle_text
            })
            
        return subtitles
    
    @staticmethod
    def format_srt(subtitles):
        """Format subtitle entries back to SRT format"""
        srt_content = []
        
        for subtitle in subtitles:
            srt_content.append(f"{subtitle['number']}")
            srt_content.append(f"{subtitle['start_time']} --> {subtitle['end_time']}")
            srt_content.append(f"{subtitle['text']}")
            srt_content.append("")  # Empty line between entries
            
        return '\n'.join(srt_content)
    
    @staticmethod
    def create_batches(subtitles, batch_size):
        """Split subtitles into batches of specified size"""
        return [subtitles[i:i + batch_size] for i in range(0, len(subtitles), batch_size)]


class KoboldCppClient:
    """
    Client for communicating with KoboldCPP backend server
    """
    def __init__(self, server_url="http://localhost:5001"):
        self.server_url = server_url
        self.api_endpoint = f"{server_url}/api/v1/generate"
        self.connected = False
    
    def set_server_url(self, url):
        """Update the server URL"""
        self.server_url = url
        self.api_endpoint = f"{url}/api/v1/generate"
    
    def test_connection(self):
        """Test connection to the KoboldCPP server"""
        try:
            response = requests.get(f"{self.server_url}/api/v1/model", timeout=5)
            if response.status_code == 200:
                self.connected = True
                return True, response.json()
            else:
                self.connected = False
                return False, f"Server responded with status code: {response.status_code}"
        except requests.exceptions.RequestException as e:
            self.connected = False
            return False, str(e)
    
    def translate_text(self, text, source_lang, target_lang):
        """Send translation request to KoboldCPP server"""
        if not self.connected:
            return False, "Not connected to server"
        
        # Format the prompt using the specified chat template with clearer instructions
        prompt = f"<bos><start_of_turn>user\nTranslate the following text from {source_lang} to {target_lang}. Provide only one translation per entry. Do not include alternative translations or explanations:\n\n{text}<end_of_turn>\n<start_of_turn>model\n"
        
        # Use the specific LLM settings provided
        payload = {
            "prompt": prompt,
            "max_new_tokens": len(text) * 3,  # Estimate: translation might be up to 2x longer
            "temperature": 1.0,  # Fixed as specified
            "top_k": 64,         # Fixed as specified
            "top_p": 0.95,       # Fixed as specified
            "stop_sequence": ["<end_of_turn>", "<start_of_turn>"]  # Stop at the end of the model's response
        }
        
        try:
            response = requests.post(self.api_endpoint, json=payload, timeout=600) # set larger timeout if needed
            if response.status_code == 200:
                result = response.json()
                translation = result.get('results', [{}])[0].get('text', '')
                
                # Clean up any trailing stop tokens if they were included
                for stop_seq in payload["stop_sequence"]:
                    if translation.endswith(stop_seq):
                        translation = translation[:-len(stop_seq)]
                
                # Clean up the translation by removing alternative translations
                # This is a safety measure in case the model still outputs alternatives
                cleaned_translation = self._clean_translation(translation)
                
                return True, cleaned_translation.strip()
            else:
                return False, f"Server responded with status code: {response.status_code}"
        except requests.exceptions.RequestException as e:
            return False, str(e)

    def _clean_translation(self, text):
        """Clean up the translation by removing alternative translations and other artifacts"""
        # Replace alternatives separated by slash
        cleaned_text = re.sub(r'\s*/\s*', '\n', text)
        
        # Remove any lines that start with "Output:" or similar
        cleaned_text = re.sub(r'^Output:\s*', '', cleaned_text, flags=re.MULTILINE)
        
        # Remove any bracketed numbers that might appear at the start of lines (if they're not part of the translation)
        # but be careful not to remove subtitle numbers in the format [123]
        lines = cleaned_text.split('\n')
        processed_lines = []
        
        for line in lines:
            # Skip empty lines
            if not line.strip():
                processed_lines.append(line)
                continue
                
            # Check if this is a subtitle marker line
            subtitle_marker_match = re.match(r'^\s*\[(\d+)\]\s*(.*?)$', line)
            if subtitle_marker_match:
                subtitle_num = subtitle_marker_match.group(1)
                content = subtitle_marker_match.group(2)
                # Only keep the subtitle number and content, no alternatives
                processed_lines.append(f"[{subtitle_num}] {content}")
            else:
                # Regular line, just add it
                processed_lines.append(line)
        
        return '\n'.join(processed_lines)


    # In the TranslationWorker class, update the _translate_subtitles method to handle 
    # the case where the model might not maintain the [number] format correctly:

    def _translate_subtitles(self):
        """Translate subtitle batches"""
        batches = SrtParser.create_batches(self.subtitles, self.batch_size)
        translated_subtitles = []
        
        for batch_index, batch in enumerate(batches):
            if self.abort:
                self.translation_finished.emit(False, "Translation aborted")
                return
                
            # Create a combined text for translation while preserving subtitle info
            batch_text = ""
            for subtitle in batch:
                batch_text += f"[{subtitle['number']}] {subtitle['text']}\n\n"
            
            # Translate the batch
            success, translated_text = self.client.translate_text(
                batch_text, self.source_lang, self.target_lang
            )
            
            if not success:
                self.translation_finished.emit(False, f"Translation failed: {translated_text}")
                return
            
            # Parse translated text back into subtitle format
            translated_batch = []
            current_subtitles = batch.copy()
            
            # Improved pattern matching to extract subtitle numbers and translated content
            translated_parts = re.findall(r'\[(\d+)\]\s*(.*?)(?=\[\d+\]|\Z)', translated_text + "\n", re.DOTALL)
            
            # If we couldn't extract anything with the pattern, try a more direct approach
            if not translated_parts:
                # Fall back to simply assigning translations based on order
                lines = translated_text.split('\n')
                non_empty_lines = [line for line in lines if line.strip()]
                
                # If we have roughly the same number of non-empty lines as subtitles,
                # we can attempt a direct mapping
                if 0.5 <= len(non_empty_lines) / len(current_subtitles) <= 2.0:
                    # Simple case: one line per subtitle
                    if len(non_empty_lines) == len(current_subtitles):
                        for i, subtitle in enumerate(current_subtitles):
                            translated_subtitle = subtitle.copy()
                            translated_subtitle['text'] = non_empty_lines[i].strip()
                            translated_batch.append(translated_subtitle)
                    else:
                        # More complex: try to join lines that belong together
                        combined_lines = []
                        current_line = ""
                        
                        for line in non_empty_lines:
                            if re.match(r'^[A-Z]', line) and current_line:  # New sentence starts with capital letter
                                combined_lines.append(current_line)
                                current_line = line
                            else:
                                if current_line:
                                    current_line += " " + line
                                else:
                                    current_line = line
                        
                        if current_line:
                            combined_lines.append(current_line)
                        
                        # Now map these combined lines to subtitles as best we can
                        for i, subtitle in enumerate(current_subtitles):
                            translated_subtitle = subtitle.copy()
                            if i < len(combined_lines):
                                translated_subtitle['text'] = combined_lines[i].strip()
                            else:
                                # If we run out of translated lines, keep the original
                                translated_subtitle['text'] = subtitle['text']
                            translated_batch.append(translated_subtitle)
            else:
                # Process the matched subtitle numbers and translated content
                for subtitle_num_str, translated_text_content in translated_parts:
                    try:
                        subtitle_num = int(subtitle_num_str)
                        
                        # Find the corresponding subtitle in the batch
                        for subtitle in current_subtitles:
                            if subtitle['number'] == subtitle_num:
                                translated_subtitle = subtitle.copy()
                                translated_subtitle['text'] = translated_text_content.strip()
                                translated_batch.append(translated_subtitle)
                                break
                    except ValueError:
                        continue
            
            # If some subtitles weren't found in the translated text, add them with original text
            batch_numbers = [subtitle['number'] for subtitle in translated_batch]
            for subtitle in current_subtitles:
                if subtitle['number'] not in batch_numbers:
                    translated_batch.append(subtitle)
            
            # Sort by subtitle number
            translated_batch.sort(key=lambda x: x['number'])
            
            translated_subtitles.extend(translated_batch)
            self.batch_completed.emit(batch_index, translated_batch)
            self.progress_updated.emit(int((batch_index + 1) / len(batches) * 100))
            
            # Delay between batches if configured
            if self.delay > 0 and batch_index < len(batches) - 1:
                time.sleep(self.delay)
        
        # Format all translated subtitles back to SRT
        translated_srt = SrtParser.format_srt(translated_subtitles)
        self.translation_finished.emit(True, translated_srt)


class TranslationWorker(QThread):
    """
    Worker thread for performing translations in the background
    """
    progress_updated = pyqtSignal(int)
    batch_completed = pyqtSignal(int, list)
    translation_finished = pyqtSignal(bool, str)
    
    def __init__(self, client, subtitles=None, text=None, source_lang="English", 
                 target_lang="Finnish", batch_size=10, delay=1):
        super().__init__()
        self.client = client
        self.subtitles = subtitles
        self.text = text
        self.source_lang = source_lang
        self.target_lang = target_lang
        self.batch_size = batch_size
        self.delay = delay
        self.abort = False
    
    def run(self):
        """Run the translation task"""
        if self.subtitles:  # SRT translation mode
            self._translate_subtitles()
        else:  # Free text translation mode
            self._translate_text()
    
    def _translate_subtitles(self):
        """Translate subtitle batches"""
        batches = SrtParser.create_batches(self.subtitles, self.batch_size)
        translated_subtitles = []
        
        for batch_index, batch in enumerate(batches):
            if self.abort:
                self.translation_finished.emit(False, "Translation aborted")
                return
                
            # Create a combined text for translation while preserving subtitle info
            batch_text = ""
            for subtitle in batch:
                batch_text += f"[{subtitle['number']}] {subtitle['text']}\n\n"
            
            # Translate the batch
            success, translated_text = self.client.translate_text(
                batch_text, self.source_lang, self.target_lang
            )
            
            if not success:
                self.translation_finished.emit(False, f"Translation failed: {translated_text}")
                return
            
            # Parse translated text back into subtitle format
            # This is a simplified approach - we're assuming the translations maintain 
            # the [number] format at the beginning of each subtitle
            translated_batch = []
            current_subtitles = batch.copy()
            
            # Split the translated text by the subtitle number pattern
            translated_parts = re.split(r'\[(\d+)\]', translated_text)
            
            # The first element is usually empty, so we ignore it
            i = 1
            while i < len(translated_parts) - 1:
                subtitle_num = int(translated_parts[i])
                translated_text_content = translated_parts[i + 1].strip()
                
                # Find the corresponding subtitle in the batch
                for subtitle in current_subtitles:
                    if subtitle['number'] == subtitle_num:
                        translated_subtitle = subtitle.copy()
                        translated_subtitle['text'] = translated_text_content
                        translated_batch.append(translated_subtitle)
                        break
                
                i += 2
            
            # If some subtitles weren't found in the translated text, add them with original text
            batch_numbers = [subtitle['number'] for subtitle in translated_batch]
            for subtitle in current_subtitles:
                if subtitle['number'] not in batch_numbers:
                    translated_batch.append(subtitle)
            
            # Sort by subtitle number
            translated_batch.sort(key=lambda x: x['number'])
            
            translated_subtitles.extend(translated_batch)
            self.batch_completed.emit(batch_index, translated_batch)
            self.progress_updated.emit(int((batch_index + 1) / len(batches) * 100))
            
            # Delay between batches if configured
            if self.delay > 0 and batch_index < len(batches) - 1:
                time.sleep(self.delay)
        
        # Format all translated subtitles back to SRT
        translated_srt = SrtParser.format_srt(translated_subtitles)
        self.translation_finished.emit(True, translated_srt)
    
    def _translate_text(self):
        """Translate free-form text"""
        if self.abort:
            self.translation_finished.emit(False, "Translation aborted")
            return
            
        success, translated_text = self.client.translate_text(
            self.text, self.source_lang, self.target_lang
        )
        
        self.progress_updated.emit(100)
        self.translation_finished.emit(success, translated_text)
    
    def stop(self):
        """Stop the translation task"""
        self.abort = True


class TranslationApp(QMainWindow):
    """
    Main application window
    """
    def __init__(self):
        super().__init__()
        self.client = KoboldCppClient()
        self.worker = None
        self.original_subtitles = []
        self.translated_subtitles = []
        self.settings = QSettings("TranslationApp", "KoboldTranslator")
        
        self.init_ui()
        self.load_settings()
    
    def init_ui(self):
        """Initialize the user interface"""
        self.setWindowTitle("Translation Application")
        self.setMinimumSize(900, 600)
        
        # Main widget and layout
        main_widget = QWidget()
        main_layout = QVBoxLayout()
        
        # Server connection section
        server_group = QGroupBox("KoboldCPP Server Connection")
        server_layout = QGridLayout()
        
        self.server_url_input = QLineEdit("http://localhost:5001")
        self.connect_button = QPushButton("Connect")
        self.connection_status = QLabel("Not Connected")
        self.connection_status.setStyleSheet("color: red;")
        
        server_layout.addWidget(QLabel("Server URL:"), 0, 0)
        server_layout.addWidget(self.server_url_input, 0, 1)
        server_layout.addWidget(self.connect_button, 0, 2)
        server_layout.addWidget(QLabel("Status:"), 1, 0)
        server_layout.addWidget(self.connection_status, 1, 1)
        
        server_group.setLayout(server_layout)
        
        # Tab widget for translation modes
        self.tab_widget = QTabWidget()
        self.free_text_tab = QWidget()
        self.subtitle_tab = QWidget()
        
        self.init_free_text_tab()
        self.init_subtitle_tab()
        
        self.tab_widget.addTab(self.free_text_tab, "Free Text Translation")
        self.tab_widget.addTab(self.subtitle_tab, "Subtitle Translation")
        
        # Settings section
        settings_group = QGroupBox("Translation Settings")
        settings_layout = QGridLayout()
        
        self.delay_spinbox = QSpinBox()
        self.delay_spinbox.setMinimum(0)
        self.delay_spinbox.setMaximum(10)
        self.delay_spinbox.setValue(1)
        self.delay_spinbox.setSuffix(" seconds")
        
        settings_layout.addWidget(QLabel("Delay Between Batches:"), 1, 0)
        settings_layout.addWidget(self.delay_spinbox, 1, 1)
        
        settings_group.setLayout(settings_layout)
        
        # Status bar
        self.statusBar = QStatusBar()
        self.setStatusBar(self.statusBar)
        
        # Add all components to main layout
        main_layout.addWidget(server_group)
        main_layout.addWidget(self.tab_widget)
        main_layout.addWidget(settings_group)
        
        main_widget.setLayout(main_layout)
        self.setCentralWidget(main_widget)
        
        # Connect signals
        self.connect_button.clicked.connect(self.test_connection)
    
    def init_free_text_tab(self):
        """Initialize the free text translation tab"""
        layout = QVBoxLayout()
        
        # Language selection
        lang_layout = QHBoxLayout()
        self.source_lang_combo = QComboBox()
        self.target_lang_combo = QComboBox()
        
        # Add commonly used languages
        languages = ["English", "Finnish", "French", "German", "Chinese", "Japanese", 
                     "Korean", "Russian", "Italian", "Portuguese", "Spanish"]
        for lang in languages:
            self.source_lang_combo.addItem(lang)
            self.target_lang_combo.addItem(lang)
        
        # Default to English -> Finnish
        self.source_lang_combo.setCurrentText("English")
        self.target_lang_combo.setCurrentText("Finnish")
        
        lang_layout.addWidget(QLabel("Source Language:"))
        lang_layout.addWidget(self.source_lang_combo)
        lang_layout.addWidget(QLabel("Target Language:"))
        lang_layout.addWidget(self.target_lang_combo)
        
        # Text areas
        splitter = QSplitter(Qt.Vertical)
        
        source_widget = QWidget()
        source_layout = QVBoxLayout()
        source_layout.addWidget(QLabel("Source Text:"))
        self.source_text_edit = QTextEdit()
        source_layout.addWidget(self.source_text_edit)
        self.char_count_label = QLabel("Characters: 0")
        source_layout.addWidget(self.char_count_label)
        source_widget.setLayout(source_layout)
        
        target_widget = QWidget()
        target_layout = QVBoxLayout()
        target_layout.addWidget(QLabel("Translated Text:"))
        self.target_text_edit = QTextEdit()
        self.target_text_edit.setReadOnly(True)
        target_layout.addWidget(self.target_text_edit)
        self.copy_button = QPushButton("Copy to Clipboard")
        target_layout.addWidget(self.copy_button)
        target_widget.setLayout(target_layout)
        
        splitter.addWidget(source_widget)
        splitter.addWidget(target_widget)
        
        # Translation controls
        controls_layout = QHBoxLayout()
        self.translate_button = QPushButton("Translate")
        self.translate_button.setEnabled(False)
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        
        controls_layout.addWidget(self.translate_button)
        controls_layout.addWidget(self.progress_bar)
        
        # Add all components to layout
        layout.addLayout(lang_layout)
        layout.addWidget(splitter)
        layout.addLayout(controls_layout)
        
        self.free_text_tab.setLayout(layout)
        
        # Connect signals
        self.source_text_edit.textChanged.connect(self.update_char_count)
        self.translate_button.clicked.connect(self.translate_free_text)
        self.copy_button.clicked.connect(self.copy_translated_text)
    
    def init_subtitle_tab(self):
        """Initialize the subtitle translation tab"""
        layout = QVBoxLayout()
        
        # Language selection (same as free text tab)
        lang_layout = QHBoxLayout()
        self.srt_source_lang_combo = QComboBox()
        self.srt_target_lang_combo = QComboBox()
        
        # Add commonly used languages
        languages = ["English", "Finnish", "French", "German", "Chinese", "Japanese", 
                     "Korean", "Russian", "Italian", "Portuguese", "Spanish"]
        for lang in languages:
            self.srt_source_lang_combo.addItem(lang)
            self.srt_target_lang_combo.addItem(lang)
        
        # Default to English -> Finnish
        self.srt_source_lang_combo.setCurrentText("English")
        self.srt_target_lang_combo.setCurrentText("Finnish")
        
        lang_layout.addWidget(QLabel("Source Language:"))
        lang_layout.addWidget(self.srt_source_lang_combo)
        lang_layout.addWidget(QLabel("Target Language:"))
        lang_layout.addWidget(self.srt_target_lang_combo)
        
        # Batch settings
        batch_layout = QHBoxLayout()
        batch_layout.addWidget(QLabel("Batch Size:"))
        self.batch_size_spinbox = QSpinBox()
        self.batch_size_spinbox.setMinimum(1)
        self.batch_size_spinbox.setMaximum(50)
        self.batch_size_spinbox.setValue(10)
        batch_layout.addWidget(self.batch_size_spinbox)
        
        # Text areas
        splitter = QSplitter(Qt.Vertical)
        
        source_widget = QWidget()
        source_layout = QVBoxLayout()
        file_buttons_layout = QHBoxLayout()
        self.import_button = QPushButton("Import SRT")
        file_buttons_layout.addWidget(self.import_button)
        source_layout.addLayout(file_buttons_layout)
        
        source_layout.addWidget(QLabel("Source SRT:"))
        self.srt_source_text_edit = QTextEdit()
        self.srt_source_text_edit.setFont(QFont("Courier New", 10))
        source_layout.addWidget(self.srt_source_text_edit)
        self.srt_stats_label = QLabel("Entries: 0")
        source_layout.addWidget(self.srt_stats_label)
        source_widget.setLayout(source_layout)
        
        target_widget = QWidget()
        target_layout = QVBoxLayout()
        export_buttons_layout = QHBoxLayout()
        self.export_button = QPushButton("Export Translated SRT")
        export_buttons_layout.addWidget(self.export_button)
        target_layout.addLayout(export_buttons_layout)
        
        target_layout.addWidget(QLabel("Translated SRT:"))
        self.srt_target_text_edit = QTextEdit()
        self.srt_target_text_edit.setFont(QFont("Courier New", 10))
        self.srt_target_text_edit.setReadOnly(True)
        target_layout.addWidget(self.srt_target_text_edit)
        target_widget.setLayout(target_layout)
        
        splitter.addWidget(source_widget)
        splitter.addWidget(target_widget)
        
        # Translation controls
        controls_layout = QHBoxLayout()
        self.srt_translate_button = QPushButton("Translate SRT")
        self.srt_translate_button.setEnabled(False)
        self.stop_button = QPushButton("Stop")
        self.stop_button.setEnabled(False)
        self.srt_progress_bar = QProgressBar()
        
        controls_layout.addWidget(self.srt_translate_button)
        controls_layout.addWidget(self.stop_button)
        controls_layout.addWidget(self.srt_progress_bar)
        
        # Add all components to layout
        layout.addLayout(lang_layout)
        layout.addLayout(batch_layout)
        layout.addWidget(splitter)
        layout.addLayout(controls_layout)
        
        self.subtitle_tab.setLayout(layout)
        
        # Connect signals
        self.import_button.clicked.connect(self.import_srt)
        self.export_button.clicked.connect(self.export_srt)
        self.srt_translate_button.clicked.connect(self.translate_srt)
        self.stop_button.clicked.connect(self.stop_translation)
        self.srt_source_text_edit.textChanged.connect(self.update_srt_stats)
    

    
    def update_char_count(self):
        """Update the character count label for free text tab"""
        text = self.source_text_edit.toPlainText()
        char_count = len(text)
        self.char_count_label.setText(f"Characters: {char_count}")
        
        # Enable/disable translate button based on text availability and connection status
        self.translate_button.setEnabled(char_count > 0 and self.client.connected)
    
    def update_srt_stats(self):
        """Update the subtitle statistics"""
        text = self.srt_source_text_edit.toPlainText()
        if not text.strip():
            self.srt_stats_label.setText("Entries: 0")
            self.srt_translate_button.setEnabled(False)
            return
            
        try:
            subtitles = SrtParser.parse_srt(text)
            self.original_subtitles = subtitles
            self.srt_stats_label.setText(f"Entries: {len(subtitles)}")
            self.srt_translate_button.setEnabled(len(subtitles) > 0 and self.client.connected)
        except Exception as e:
            self.srt_stats_label.setText(f"Error: {str(e)}")
            self.srt_translate_button.setEnabled(False)
    
    
    def test_connection(self):
        """Test the connection to the KoboldCPP server"""
        self.statusBar.showMessage("Testing connection...")
        self.connect_button.setEnabled(False)
        
        server_url = self.server_url_input.text().strip()
        if not server_url:
            self.show_error("Server URL cannot be empty")
            self.connect_button.setEnabled(True)
            return
            
        self.client.set_server_url(server_url)
        success, message = self.client.test_connection()
        
        if success:
            self.connection_status.setText("Connected")
            self.connection_status.setStyleSheet("color: green;")
            self.statusBar.showMessage(f"Connected to KoboldCPP server. Model: {message.get('model', 'Unknown')}", 5000)
            
            # Enable translation buttons if text is available
            if self.source_text_edit.toPlainText():
                self.translate_button.setEnabled(True)
            if self.original_subtitles:
                self.srt_translate_button.setEnabled(True)
        else:
            self.connection_status.setText("Connection Failed")
            self.connection_status.setStyleSheet("color: red;")
            self.show_error(f"Failed to connect: {message}")
        
        self.connect_button.setEnabled(True)
    
    def translate_free_text(self):
        """Handle free text translation"""
        if not self.client.connected:
            self.show_error("Not connected to server")
            return
            
        text = self.source_text_edit.toPlainText()
        if not text.strip():
            self.show_error("No text to translate")
            return
            
        source_lang = self.source_lang_combo.currentText()
        target_lang = self.target_lang_combo.currentText()

        
        # Update UI for translation in progress
        self.translate_button.setEnabled(False)
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(True)
        self.statusBar.showMessage("Translating...")
        
        # Create and start worker thread
        self.worker = TranslationWorker(
            client=self.client,
            text=text,
            source_lang=source_lang,
            target_lang=target_lang
        )
        
        self.worker.progress_updated.connect(self.update_progress)
        self.worker.translation_finished.connect(self.handle_free_text_translation_finished)
        self.worker.start()
    
    def translate_srt(self):
        """Handle SRT translation"""
        if not self.client.connected:
            self.show_error("Not connected to server")
            return
            
        if not self.original_subtitles:
            self.show_error("No subtitles to translate")
            return
            
        source_lang = self.srt_source_lang_combo.currentText()
        target_lang = self.srt_target_lang_combo.currentText()
        batch_size = self.batch_size_spinbox.value()
        delay = self.delay_spinbox.value()

        
        # Update UI for translation in progress
        self.srt_translate_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.srt_progress_bar.setValue(0)
        self.statusBar.showMessage("Translating subtitles...")
        
        # Clear previous translation
        self.srt_target_text_edit.clear()
        self.translated_subtitles = []
        
        # Create and start worker thread
        self.worker = TranslationWorker(
            client=self.client,
            subtitles=self.original_subtitles,
            source_lang=source_lang,
            target_lang=target_lang,
            batch_size=batch_size,
            delay=delay
        )
        
        self.worker.progress_updated.connect(self.update_srt_progress)
        self.worker.batch_completed.connect(self.handle_batch_completed)
        self.worker.translation_finished.connect(self.handle_srt_translation_finished)
        self.worker.start()
    
    def stop_translation(self):
        """Stop the current translation process"""
        if self.worker and self.worker.isRunning():
            self.worker.stop()
            self.statusBar.showMessage("Translation stopping...")
    
    def update_progress(self, value):
        """Update progress bar for free text translation"""
        self.progress_bar.setValue(value)
    
    def update_srt_progress(self, value):
        """Update progress bar for SRT translation"""
        self.srt_progress_bar.setValue(value)
    
    def handle_batch_completed(self, batch_index, translated_batch):
        """Handle completed batch of translated subtitles"""
        self.translated_subtitles.extend(translated_batch)
        
        # Update the text area with current progress
        partial_srt = SrtParser.format_srt(self.translated_subtitles)
        self.srt_target_text_edit.setText(partial_srt)
        
        # Move cursor to end
        cursor = self.srt_target_text_edit.textCursor()
        cursor.movePosition(QTextCursor.End)
        self.srt_target_text_edit.setTextCursor(cursor)
        
        self.statusBar.showMessage(f"Completed batch {batch_index + 1}, entries: {len(translated_batch)}")
    
    def handle_free_text_translation_finished(self, success, result):
        """Handle completion of free text translation"""
        self.progress_bar.setVisible(False)
        self.translate_button.setEnabled(True)
        
        if success:
            self.target_text_edit.setText(result)
            self.statusBar.showMessage("Translation completed", 5000)
        else:
            self.show_error(f"Translation failed: {result}")
            self.statusBar.showMessage("Translation failed", 5000)
    
    def handle_srt_translation_finished(self, success, result):
        """Handle completion of SRT translation"""
        self.stop_button.setEnabled(False)
        self.srt_translate_button.setEnabled(len(self.original_subtitles) > 0 and self.client.connected)
        
        if success:
            self.srt_target_text_edit.setText(result)
            self.statusBar.showMessage("SRT translation completed", 5000)
        else:
            self.show_error(f"SRT translation failed: {result}")
            self.statusBar.showMessage("SRT translation failed", 5000)
    
    def import_srt(self):
        """Import SRT file from disk"""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Open SRT File", "", "SRT Files (*.srt);;All Files (*)"
        )
        
        if file_path:
            try:
                with open(file_path, 'r', encoding='utf-8') as file:
                    srt_content = file.read()
                
                self.srt_source_text_edit.setText(srt_content)
                self.statusBar.showMessage(f"Imported {file_path}", 5000)
            except Exception as e:                                
                self.show_error(f"Error importing file: {str(e)}")
    
    def export_srt(self):
        """Export translated SRT file to disk"""
        translated_text = self.srt_target_text_edit.toPlainText()
        if not translated_text.strip():
            self.show_error("No translated content to export")
            return
            
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Save Translated SRT", "", "SRT Files (*.srt);;All Files (*)"
        )
        
        if file_path:
            try:
                # Add .srt extension if not present
                if not file_path.lower().endswith('.srt'):
                    file_path += '.srt'
                    
                with open(file_path, 'w', encoding='utf-8') as file:
                    file.write(translated_text)
                
                self.statusBar.showMessage(f"Saved to {file_path}", 5000)
            except Exception as e:
                self.show_error(f"Error exporting file: {str(e)}")
    
    def copy_translated_text(self):
        """Copy translated text to clipboard"""
        translated_text = self.target_text_edit.toPlainText()
        if translated_text:
            clipboard = QApplication.clipboard()
            clipboard.setText(translated_text)
            self.statusBar.showMessage("Copied to clipboard", 3000)
    
    def show_error(self, message):
        """Show error message dialog"""
        QMessageBox.critical(self, "Error", message)
    
    def load_settings(self):
        """Load application settings"""
        server_url = self.settings.value("server_url", "http://localhost:5001")
        source_lang = self.settings.value("source_lang", "English")
        target_lang = self.settings.value("target_lang", "Finnish")
        batch_size = self.settings.value("batch_size", 10, int)
        delay = self.settings.value("delay", 1, int)
        
        self.server_url_input.setText(server_url)
        
        # Free text settings
        self.source_lang_combo.setCurrentText(source_lang)
        self.target_lang_combo.setCurrentText(target_lang)
        
        # SRT settings
        self.srt_source_lang_combo.setCurrentText(source_lang)
        self.srt_target_lang_combo.setCurrentText(target_lang)
        self.batch_size_spinbox.setValue(batch_size)
        self.delay_spinbox.setValue(delay)
    
    def save_settings(self):
        """Save application settings"""
        self.settings.setValue("server_url", self.server_url_input.text())
        self.settings.setValue("source_lang", self.source_lang_combo.currentText())
        self.settings.setValue("target_lang", self.target_lang_combo.currentText())
        self.settings.setValue("batch_size", self.batch_size_spinbox.value())
        self.settings.setValue("delay", self.delay_spinbox.value())
    
    def closeEvent(self, event):
        """Override close event to save settings"""
        self.save_settings()
        
        # Stop any ongoing translation
        if self.worker and self.worker.isRunning():
            self.worker.stop()
            self.worker.wait()
        
        event.accept()


def main():
    """Application entry point"""
    app = QApplication(sys.argv)
    window = TranslationApp()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
