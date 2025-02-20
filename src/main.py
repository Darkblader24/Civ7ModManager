import sys
import os
import json
import logging
from pathlib import Path
from datetime import datetime
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout,
    QTreeWidget, QLabel, QPushButton, QHBoxLayout,
    QFileDialog, QMessageBox, QMenu, QInputDialog, 
    QProgressBar, QPlainTextEdit, QHeaderView
)
from PyQt6.QtCore import Qt
from PyQt6 import QtCore

from archive import ArchiveHandler
from modinfo import ModInfo
from ui_components import ModTreeItem

import shutil

class Civ7ModManager(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Civilization VII Mod Manager")
        self.setGeometry(100, 100, 1200, 800)
        
        # Define paths
        local_appdata = os.getenv('LOCALAPPDATA')
        if not local_appdata:  # Early return with error if LOCALAPPDATA not found
            error_msg = "Unable to locate LOCALAPPDATA environment variable"
            QMessageBox.critical(self, "Error", error_msg)
            raise EnvironmentError(error_msg)

        self.app_path = Path(__file__).parent
        self.game_mods_path = Path(local_appdata) / "Firaxis Games" / "Sid Meier's Civilization VII" / "Mods"
        self.storage_path = Path(local_appdata) / "Civ7ModManager" / "ModStorage"
        self.profiles_path = Path(local_appdata) / "Civ7ModManager" / "Profiles"
        self.logs_path = Path(local_appdata) / "Civ7ModManager" / "Logs"
        self.lib_path = self.app_path / "lib"
        self.mods = {}
        
        # Create necessary directories
        for path in [self.game_mods_path, self.storage_path, self.profiles_path, self.logs_path]:
            path.mkdir(parents=True, exist_ok=True)

        # Main widget and layout setup
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        layout = QVBoxLayout(main_widget)
        
        # Add path info
        game_path_label = QLabel(f"Game Mods Directory: {self.game_mods_path}")
        storage_path_label = QLabel(f"Mod Storage: {self.storage_path}")
        layout.addWidget(game_path_label)
        layout.addWidget(storage_path_label)
        
        # Add mod count label
        self.mod_count_label = QLabel("Mods: 0 total, 0 enabled")
        layout.addWidget(self.mod_count_label)
        
        # Initialize and setup mod tree widget
        self.mod_tree = QTreeWidget()
        headers = ["Name", "Mod ID", "Version", "Affects Saves", "Has Conflicts", "Author"]
        self.mod_tree.setHeaderLabels(headers)
        header = self.mod_tree.header()
        if header:  # Check if header exists before calling methods
            header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)  # Allow user resizing
            header.setSectionsClickable(True)
            header.sectionClicked.connect(self._handle_sort)
            # Set default column widths
            header.resizeSection(0, 300)  # Name column
            header.resizeSection(1, 200)  # Mod ID column
            header.resizeSection(2, 100)  # Version column
            header.resizeSection(3, 100)  # Affects Saves column
            header.resizeSection(4, 100)  # Has Conflicts column
            header.resizeSection(5, 150)  # Author column
        self.mod_tree.setAlternatingRowColors(True)
        self.mod_tree.setContextMenuPolicy(QtCore.Qt.ContextMenuPolicy.CustomContextMenu)
        self.mod_tree.customContextMenuRequested.connect(self._show_context_menu)
        self.mod_tree.itemChanged.connect(self._on_mod_toggle)
        layout.addWidget(self.mod_tree)
        
        # Add progress bar (hidden by default)
        self.progress_bar = QProgressBar()
        self.progress_bar.hide()
        layout.addWidget(self.progress_bar)
        
        # Add log viewer
        log_label = QLabel("Operation Log:")
        layout.addWidget(log_label)
        self.log_viewer = QPlainTextEdit()
        self.log_viewer.setReadOnly(True)
        self.log_viewer.setMaximumHeight(150)
        layout.addWidget(self.log_viewer)
        
        # Set up logging first
        self._setup_logging()
        
        # Set up remaining class attributes
        self.archive_filter = "Mod Archives (*.zip *.7z *.rar *.r00);;All Files (*.*)"
        self._current_sort_column = 0
        self._current_sort_order = Qt.SortOrder.AscendingOrder
        
        # Buttons layout
        button_layout = QHBoxLayout()
        
        # Add buttons
        refresh_button = QPushButton("Refresh Mod List")
        install_button = QPushButton("Install Mod")
        install_folder_button = QPushButton("Install Folder")  # New button
        save_profile_button = QPushButton("Save Profile")
        load_profile_button = QPushButton("Load Profile")
        enable_all_button = QPushButton("Enable All")  # New button
        disable_all_button = QPushButton("Disable All")  # New button
        deploy_button = QPushButton("Deploy Mods")
        deploy_button.setStyleSheet("background-color: #4CAF50; color: white;")
        clear_log_button = QPushButton("Clear Log")
        
        # Connect button signals
        refresh_button.clicked.connect(self.refresh_mod_list)
        install_button.clicked.connect(self.install_mod)
        install_folder_button.clicked.connect(self.install_mod_folder)  # New connection
        save_profile_button.clicked.connect(self.save_profile)
        load_profile_button.clicked.connect(self.load_profile)
        enable_all_button.clicked.connect(self.enable_all_mods)  # New connection
        disable_all_button.clicked.connect(self.disable_all_mods)  # New connection
        deploy_button.clicked.connect(self.deploy_mods)
        clear_log_button.clicked.connect(self.log_viewer.clear)
        
        # Add buttons to layout
        for button in [refresh_button, install_button, install_folder_button, save_profile_button, 
                      load_profile_button, enable_all_button, disable_all_button,  # Add new buttons
                      deploy_button, clear_log_button]:
            button_layout.addWidget(button)
        
        layout.addLayout(button_layout)
        
        # Initial mod list population
        self.refresh_mod_list()

    def _setup_logging(self):
        """Setup logging configuration"""
        self.logger = logging.getLogger('Civ7ModManager')
        self.logger.setLevel(logging.INFO)
        
        # File handler
        log_file = self.logs_path / f"modmanager_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
        file_handler = logging.FileHandler(log_file)
        file_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
        self.logger.addHandler(file_handler)
        
        # Custom handler for GUI log viewer
        class QtLogHandler(logging.Handler):
            def __init__(self, log_widget):
                super().__init__()
                self.log_widget = log_widget
            
            def emit(self, record):
                msg = self.format(record)
                self.log_widget.appendPlainText(msg)
        
        qt_handler = QtLogHandler(self.log_viewer)
        qt_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))  # Fixed typo in levelname
        self.logger.addHandler(qt_handler)

    def _handle_sort(self, column):
        """Handle column header clicks for sorting"""
        if not self.mod_tree:  # Early return if tree widget is not initialized
            self.logger.warning("Cannot sort: mod tree is not initialized")
            return
            
        if column < 0:  # Early return for invalid column index
            self.logger.warning(f"Cannot sort: invalid column index {column}")
            return
            
        if self._current_sort_column == column:
            # Toggle sort order if clicking the same column
            self._current_sort_order = Qt.SortOrder.DescendingOrder if self._current_sort_order == Qt.SortOrder.AscendingOrder else Qt.SortOrder.AscendingOrder
        else:
            self._current_sort_column = column
            self._current_sort_order = Qt.SortOrder.AscendingOrder
        
        self.mod_tree.sortItems(column, self._current_sort_order)

    def _update_mod_count(self):
        """Update the mod count display"""
        total_mods = len(self.mods)
        enabled_mods = sum(1 for mod in self.mods.values() if mod.enabled)
        self.mod_count_label.setText(f"Mods: {total_mods} total, {enabled_mods} enabled")

    def _on_mod_toggle(self, item, column):
        """Handle mod enable/disable checkbox changes"""
        if not item or column != 0:  # Early return if no item or wrong column
            return
            
        is_enabled = item.checkState(0) == Qt.CheckState.Checked
        folder_name = item.data(0, Qt.ItemDataRole.UserRole)
        if not folder_name:  # Early return if no folder name
            return
            
        mod = self.mods.get(folder_name)
        if not mod:  # Early return if mod not found
            return
            
        mod.enabled = is_enabled
        self._update_mod_count()
        self._update_conflicts()

    def _update_conflicts(self):
        """Update the conflicts status for all mods"""
        # Update enabled mods
        enabled_mods = {name: mod for name, mod in self.mods.items() if mod.enabled}
            
        # Check for conflicts between enabled mods
        for mod_name, mod in self.mods.items():
            mod.conflicts.clear()
            if mod.enabled:
                for other_name, other_mod in enabled_mods.items():
                    if other_name != mod_name:
                        common_files = mod.metadata['affected_files'] & other_mod.metadata['affected_files']
                        for file in common_files:
                            mod.conflicts[other_mod.metadata['display_name']] = file
        
        # Update tree items with conflict status
        for mod_name, mod in self.mods.items():
            item = self.mod_tree.findItems(mod.metadata['display_name'], Qt.MatchFlag.MatchExactly, 0)[0]
            if mod.enabled and mod.conflicts:
                item.setText(4, "Yes")
                item.setForeground(4, Qt.GlobalColor.red)
            else:
                item.setText(4, "No")
                item.setForeground(4, Qt.GlobalColor.white)
                
    def deploy_mods(self):
        """Deploy enabled mods to game directory"""
        try:
            if not self.game_mods_path.exists():  # Early return if game mods path doesn't exist
                error_msg = "Game mods directory does not exist"
                self.logger.error(error_msg)
                QMessageBox.critical(self, "Error", error_msg)
                return
                
            # Ask for confirmation
            reply = QMessageBox.question(
                self,
                "Confirm Deploy",
                "This will clear the game's mod folder and copy all enabled mods. Continue?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            
            if reply == QMessageBox.StandardButton.No:
                return
            
            enabled_mods = [(name, mod) for name, mod in self.mods.items() if mod.enabled]
            total_mods = len(enabled_mods)
            
            self.logger.info(f"Starting deployment of {total_mods} mods")
            self.progress_bar.setMaximum(total_mods + 1)  # +1 for cleanup
            self.progress_bar.setValue(0)
            self.progress_bar.show()
            
            # Clear game mods directory
            self.logger.info("Clearing game mods directory")
            if self.game_mods_path.exists():
                for item in self.game_mods_path.iterdir():
                    if item.is_dir():
                        shutil.rmtree(item)
                    else:
                        item.unlink()
            
            self.progress_bar.setValue(1)
            
            # Copy enabled mods to game directory
            for i, (name, mod) in enumerate(enabled_mods, 2):
                self.logger.info(f"Deploying mod: {name}")
                shutil.copytree(mod.path, self.game_mods_path / name)
                self.progress_bar.setValue(i)
            
            success_msg = f"Successfully deployed {total_mods} mod{'s' if total_mods != 1 else ''} to game directory"
            self.logger.info(success_msg)
            QMessageBox.information(self, "Deploy Complete", success_msg)
            
        except Exception as e:
            error_msg = f"Failed to deploy mods: {str(e)}"
            self.logger.error(error_msg)
            QMessageBox.critical(self, "Deploy Error", error_msg)
        finally:
            self.progress_bar.hide()

    def enable_all_mods(self):
        """Enable all mods in the list"""
        root = self.mod_tree.invisibleRootItem()
        for i in range(root.childCount()):
            item = root.child(i)
            if item:
                folder_name = item.data(0, Qt.ItemDataRole.UserRole)
                if folder_name in self.mods:
                    item.setCheckState(0, Qt.CheckState.Checked)
                    self.mods[folder_name].enabled = True
        self._update_mod_count()
        self._update_conflicts()
        self.logger.info("All mods enabled")

    def disable_all_mods(self):
        """Disable all mods in the list"""
        root = self.mod_tree.invisibleRootItem()
        for i in range(root.childCount()):
            item = root.child(i)
            if item:
                folder_name = item.data(0, Qt.ItemDataRole.UserRole)
                if folder_name in self.mods:
                    item.setCheckState(0, Qt.CheckState.Unchecked)
                    self.mods[folder_name].enabled = False
        self._update_mod_count()
        self._update_conflicts()
        self.logger.info("All mods disabled")

    def refresh_mod_list(self):
        """Refresh the list of mods from storage directory"""
        self.logger.info("Refreshing mod list")
        
        self.mod_tree.clear()
        self.mods.clear()
        self._update_mod_count()
        
        if not self.storage_path.exists():
            self.logger.warning("Storage directory not found!")
            return
            
        try:
            # Count total mods first
            mod_dirs = [d for d in self.storage_path.iterdir() if d.is_dir()]
            if not mod_dirs:  # Early return if no mod directories
                self.logger.info("No mod directories found")
                self.mod_tree.clear()
                self.mods.clear()
                self._update_mod_count()
                return
            
            total_mods = len(mod_dirs)
            
            self.progress_bar.setMaximum(total_mods)
            self.progress_bar.setValue(0)
            self.progress_bar.show()
            
            # Sort mod directories by name
            mod_dirs.sort(key=lambda x: x.name.lower())
            
            for i, mod_item in enumerate(mod_dirs):
                try:
                    mod_info = ModInfo(mod_item)
                    self.mods[mod_info.folder_name] = mod_info
                    
                    tree_item = ModTreeItem(mod_info)
                    tree_item.setData(0, Qt.ItemDataRole.UserRole, mod_info.folder_name)  # Store folder_name for reference
                    self.mod_tree.addTopLevelItem(tree_item)
                    
                    self.logger.info(f"Loaded mod: {mod_info.folder_name}")
                    self.progress_bar.setValue(i + 1)
                except Exception as mod_error:
                    self.logger.error(f"Error loading mod {mod_item.name}: {str(mod_error)}")
            
            # Sort by current sort column and order
            self.mod_tree.sortItems(self._current_sort_column, self._current_sort_order)
            
        except Exception as e:
            error_msg = f"Error reading mods: {str(e)}"
            self.logger.error(error_msg)
        finally:
            self.progress_bar.hide()
            self._update_mod_count()

    def install_mod(self):
        """Install a new mod from an archive file"""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Mod Archive",
            "",
            self.archive_filter
        )
        
        if not file_path:
            return
            
        try:
            if not Path(file_path).exists():
                error_msg = f"Selected file does not exist: {file_path}"
                self.logger.error(error_msg)
                QMessageBox.critical(self, "Error", error_msg)
                return
                
            self.logger.info(f"Installing mod from: {file_path}")
            
            # Get archive type and check support
            archive_type = ArchiveHandler.get_archive_type(file_path)
            if not archive_type:  # Early return if archive type can't be determined
                error_msg = "Could not determine archive type"
                self.logger.error(error_msg)
                QMessageBox.critical(self, "Error", error_msg)
                return
                
            if not ArchiveHandler.is_format_supported(archive_type):
                error_msg = f"Archive format '{archive_type}' is not supported.\n\n"
                if archive_type == 'rar':
                    error_msg += "Please ensure UnRAR.dll is present in the lib folder."
                elif archive_type == '7z':
                    error_msg += "Please ensure py7zr is installed correctly."
                raise ValueError(error_msg)
            
            self.progress_bar.setMaximum(3)  # 3 steps: validate, extract, refresh
            self.progress_bar.setValue(0)
            self.progress_bar.show()
            self.progress_bar.setValue(1)
            
            # Extract the mod folder
            self.logger.info("Extracting mod folder")
            try:
                mod_name = ArchiveHandler.extract_mod_folder(file_path, self.storage_path)
                if not mod_name:
                    raise ValueError("Could not determine mod folder name")
                
                self.logger.info(f"Mod extracted as: {mod_name}")
                self.progress_bar.setValue(2)
                
                QMessageBox.information(self, "Success", f"Mod '{mod_name}' installed successfully!")
                self.refresh_mod_list()
                self.progress_bar.setValue(3)
                
            except Exception as extract_error:
                raise extract_error
            
        except ValueError as ve:
            error_msg = str(ve)
            self.logger.error(f"Validation error: {error_msg}")
            QMessageBox.critical(self, "Error", error_msg)
        except Exception as e:
            error_msg = f"Failed to install mod: {str(e)}"
            self.logger.error(error_msg)
            QMessageBox.critical(self, "Error", error_msg)
        finally:
            self.progress_bar.hide()

    def install_mod_folder(self):
        """Install multiple mods from a folder"""
        folder_path = QFileDialog.getExistingDirectory(
            self,
            "Select Folder Containing Mod Archives",
            ""
        )
        
        if not folder_path:  # Early return if no folder selected
            return
            
        try:
            folder_path = Path(folder_path)
            if not folder_path.exists():  # Early return if folder doesn't exist
                error_msg = f"Selected folder does not exist: {folder_path}"
                self.logger.error(error_msg)
                QMessageBox.critical(self, "Error", error_msg)
                return
                
            if not folder_path.is_dir():  # Early return if not a directory
                error_msg = f"Selected path is not a directory: {folder_path}"
                self.logger.error(error_msg)
                QMessageBox.critical(self, "Error", error_msg)
                return
                
            self.logger.info(f"Installing mods from folder: {folder_path}")
            
            # Find all mod archives in the folder
            mod_files = []
            for ext in ['.zip', '.7z', '.rar', '.r00']:
                mod_files.extend(folder_path.glob(f'*{ext}'))
            
            if not mod_files:  # Early return if no mod files found
                QMessageBox.information(self, "No Mods Found", "No mod archives found in the selected folder.")
                return
            
            total_mods = len(mod_files)
            self.progress_bar.setMaximum(total_mods)
            self.progress_bar.setValue(0)
            self.progress_bar.show()
            
            successful_installs = 0
            failed_installs = []
            
            for i, file_path in enumerate(sorted(mod_files)):
                mod_name = None  # Initialize mod_name first
                try:
                    self.logger.info(f"Installing mod from: {file_path}")
                    
                    # Get archive type and check support
                    archive_type = ArchiveHandler.get_archive_type(str(file_path))
                    if not ArchiveHandler.is_format_supported(archive_type):
                        raise ValueError(f"Archive format '{archive_type}' is not supported for {file_path.name}")
                    
                    # Extract the mod folder
                    mod_name = ArchiveHandler.extract_mod_folder(str(file_path), self.storage_path)
                    if not mod_name:
                        raise ValueError(f"Could not determine mod folder name for {file_path.name}")
                    
                    self.logger.info(f"Successfully installed: {mod_name}")
                    successful_installs += 1
                    
                except Exception as e:
                    self.logger.error(f"Failed to install {file_path.name}: {str(e)}")
                    failed_installs.append((file_path.name, str(e)))
                    # Clean up any partial installation
                    if mod_name and (self.storage_path / mod_name).exists():
                        shutil.rmtree(self.storage_path / mod_name)
                
                self.progress_bar.setValue(i + 1)
            
            # Show results
            result_message = f"Successfully installed {successful_installs} mod{'s' if successful_installs != 1 else ''}"
            if failed_installs:
                result_message += "\n\nFailed installations:"
                for mod_name, error in failed_installs:
                    result_message += f"\n- {mod_name}: {error}"
            
            if successful_installs > 0:
                self.refresh_mod_list()
            
            QMessageBox.information(self, "Installation Complete", result_message)
            
        except Exception as e:
            error_msg = f"Failed to process mod folder: {str(e)}"
            self.logger.error(error_msg)
            QMessageBox.critical(self, "Error", error_msg)
        finally:
            self.progress_bar.hide()

    def save_profile(self):
        """Save current mod configuration as a profile"""
        name, ok = QInputDialog.getText(self, "Save Profile", "Enter profile name:")
        if not ok or not name:  # Early return if cancelled or empty name
            return
            
        try:
            self.logger.info(f"Saving profile: {name}")
            if not self.mods:  # Early return if no mods to save
                self.logger.warning("No mods to save in profile")
                QMessageBox.warning(self, "Warning", "No mods available to save in profile.")
                return
                
            # Get current mod states using folder_name as key
            profile_data = {
                folder_name: mod.enabled
                for folder_name, mod in self.mods.items()
            }
            
            profile_path = self.profiles_path / f"{name}.json"
            with open(profile_path, 'w') as f:
                json.dump(profile_data, f, indent=2)
                
            success_msg = f"Profile '{name}' saved successfully!"
            self.logger.info(success_msg)
            QMessageBox.information(self, "Success", success_msg)
        except Exception as e:
            error_msg = f"Failed to save profile: {str(e)}"
            self.logger.error(error_msg)
            QMessageBox.critical(self, "Error", error_msg)

    def load_profile(self):
        """Load a saved mod profile"""
        profiles = [p.stem for p in self.profiles_path.glob("*.json")]
        if not profiles:
            self.logger.info("No profiles found")
            QMessageBox.information(self, "No Profiles", "No saved profiles found.")
            return
            
        name, ok = QInputDialog.getItem(
            self,
            "Load Profile",
            "Select profile:",
            profiles,
            editable=False
        )
        
        if not ok or not name:  # Early return if no selection
            return
            
        try:
            self.logger.info(f"Loading profile: {name}")
            profile_path = self.profiles_path / f"{name}.json"
            if not profile_path.exists():  # Early return if profile file missing
                error_msg = f"Profile file not found: {profile_path}"
                self.logger.error(error_msg)
                QMessageBox.critical(self, "Error", error_msg)
                return
                
            with open(profile_path, 'r') as f:
                profile_data = json.load(f)
            
            # Update tree items and mod states
            root = self.mod_tree.invisibleRootItem()
            if not root:  # Check if root exists
                return
                
            for i in range(root.childCount()):
                item = root.child(i)
                if not item:  # Skip if item is None
                    continue
                    
                folder_name = item.data(0, Qt.ItemDataRole.UserRole)
                if folder_name in profile_data:
                    should_be_enabled = profile_data[folder_name]
                    item.setCheckState(0, Qt.CheckState.Checked if should_be_enabled else Qt.CheckState.Unchecked)
                    if folder_name in self.mods:
                        self.mods[folder_name].enabled = should_be_enabled
                
            # Update conflict status after loading profile
            self._update_conflicts()
            self._update_mod_count()
                
            success_msg = f"Profile '{name}' loaded successfully!"
            self.logger.info(success_msg)
            QMessageBox.information(self, "Success", success_msg)
        except Exception as e:
            error_msg = f"Failed to load profile: {str(e)}"
            self.logger.error(error_msg)
            QMessageBox.critical(self, "Error", error_msg)

    def _show_context_menu(self, position):
        """Show context menu for mod tree items"""
        if not position or not self.mod_tree:  # Early return if no position or tree
            return
            
        viewport = self.mod_tree.viewport()
        if not viewport:  # Check viewport exists
            return
            
        item = self.mod_tree.itemAt(position)
        if not item:
            return
            
        menu = QMenu()
        view_info_action = menu.addAction("View Mod Info")
        view_conflicts_action = menu.addAction("Check Conflicts")
        goto_location_action = menu.addAction("Go to Mod Location")  # Add new action
        uninstall_action = menu.addAction("Uninstall")
        
        action = menu.exec(viewport.mapToGlobal(position))
        if not action:  # Early return if no action selected
            return
            
        folder_name = item.data(0, Qt.ItemDataRole.UserRole)
        if not folder_name:  # Early return if no folder name
            return
            
        if action == view_info_action:
            self._show_mod_info(folder_name)
        elif action == view_conflicts_action:
            self._check_conflicts(folder_name)
        elif action == goto_location_action:  # Handle new action
            self._goto_mod_location(folder_name)
        elif action == uninstall_action:
            self._uninstall_mod(folder_name)

    def _goto_mod_location(self, folder_name):
        """Open the mod's folder in File Explorer"""
        if not folder_name:  # Early return if no folder name
            return
            
        mod = self.mods.get(folder_name)
        if not mod:  # Early return if mod not found
            return
            
        try:
            os.startfile(str(mod.path))
            self.logger.info(f"Opened mod location: {mod.path}")
        except Exception as e:
            error_msg = f"Failed to open mod location: {str(e)}"
            self.logger.error(error_msg)
            QMessageBox.critical(self, "Error", error_msg)

    def _show_mod_info(self, folder_name):
        """Display mod information"""
        if not folder_name:  # Early return if no folder name
            return
            
        mod = self.mods.get(folder_name)
        if not mod:  # Early return if mod not found
            return
            
        # Create a formatted text layout with sections
        sections = []
        
        # Basic Info Section
        basic_info = [
            ("Mod Name", mod.metadata['display_name']),
            ("Folder", folder_name),
            ("ID", mod.metadata['id']),
            ("Version", mod.metadata['version']),
            ("Authors", mod.metadata['authors']),
            ("Status", 'Enabled' if mod.enabled else 'Disabled'),
            ("Location", str(mod.path)),
            ("Affects Saved Games", 'Yes' if mod.metadata['affects_saves'] else 'No')
        ]
        
        sections.append("Basic Information\n" + "-" * 50 + "\n" + 
                      "\n".join(f"{key}: {value}" for key, value in basic_info))
        
        # Dependencies Section
        if mod.metadata['dependencies']:
            dep_text = "\n\nDependencies\n" + "-" * 50 + "\n"
            for dep in mod.metadata['dependencies']:
                dep_text += f"• {dep['title']} ({dep['id']})\n"
            sections.append(dep_text)
        
        # Affected Files Section
        if mod.metadata['affected_files']:
            files_text = "\nAffected Files\n" + "-" * 50 + "\n"
            for file in sorted(mod.metadata['affected_files']):
                files_text += f"• {file}\n"
            sections.append(files_text)
        
        # Show the info in a larger message box
        msg_box = QMessageBox(self)
        msg_box.setWindowTitle(f"Mod Information - {mod.metadata['display_name']}")
        msg_box.setText("".join(sections))
        msg_box.setTextFormat(Qt.TextFormat.PlainText)
        
        # Make the message box wider and taller
        msg_box.setStyleSheet("QLabel{min-width: 600px; min-height: 400px;}")
        msg_box.exec()

    def _check_conflicts(self, folder_name):
        """Check for conflicts with other enabled mods"""
        mod = self.mods.get(folder_name)
        if not mod:
            self.logger.warning(f"Mod not found: {folder_name}")
            return
        
        if not mod.metadata['affected_files']:
            QMessageBox.warning(
                self,
                "Mod Conflicts",
                f"{mod.metadata['display_name']} has no affected files listed or metadata is missing"
            )
            return
            
        conflicts = []
        for other_folder, other_mod in self.mods.items():
            if other_folder != folder_name:
                # Check for overlapping affected files
                if not other_mod.metadata['affected_files']:  
                    continue
                    
                common_files = mod.metadata['affected_files'] & other_mod.metadata['affected_files']
                if common_files:
                    conflicts.append(f"{other_mod.metadata['display_name']}:\n" + "\n".join(f"  - {file}" for file in sorted(common_files)))
        
        if conflicts:
            QMessageBox.warning(
                self,
                "Mod Conflicts",
                f"Conflicts found for {mod.metadata['display_name']} with enabled mods:\n\n" + "\n".join(conflicts)
            )
        else:
            QMessageBox.information(
                self,
                "Mod Conflicts",
                f"No conflicts found for {mod.metadata['display_name']} with enabled mods"
            )

    def _uninstall_mod(self, folder_name):
        """Uninstall a mod by removing it from storage"""
        mod = self.mods.get(folder_name)
        if not mod:
            return
            
        reply = QMessageBox.question(
            self,
            "Confirm Uninstall",
            f"Are you sure you want to uninstall '{mod.metadata['display_name']}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            try:
                self.logger.info(f"Uninstalling mod: {folder_name}")
                # Remove from storage
                shutil.rmtree(mod.path)
                success_msg = f"Mod '{mod.metadata['display_name']}' uninstalled successfully!"
                self.logger.info(success_msg)
                QMessageBox.information(self, "Success", success_msg)
                self.refresh_mod_list()
            except Exception as e:
                error_msg = f"Failed to uninstall mod: {str(e)}"
                self.logger.error(error_msg)
                QMessageBox.critical(self, "Error", error_msg)

def main():
    app = QApplication(sys.argv)
    window = Civ7ModManager()
    window.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()