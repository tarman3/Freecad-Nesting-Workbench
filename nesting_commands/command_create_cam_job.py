import FreeCAD
import FreeCADGui
from PySide import QtWidgets, QtCore
from nestingworkbench.Tools.Cam import cam_manager


class CAMOptionsDialog(QtWidgets.QDialog):
    """Dialog for selecting which object types to include in CAM job."""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("CAM Job Options")
        self.setMinimumWidth(250)
        
        layout = QtWidgets.QVBoxLayout(self)
        
        # Title label
        title = QtWidgets.QLabel("Select objects to include in CAM job:")
        layout.addWidget(title)
        
        # Checkboxes
        self.parts_checkbox = QtWidgets.QCheckBox("Parts (full cuts)")
        self.parts_checkbox.setChecked(True)
        layout.addWidget(self.parts_checkbox)
        
        self.labels_checkbox = QtWidgets.QCheckBox("Labels (engraving)")
        self.labels_checkbox.setChecked(True)
        layout.addWidget(self.labels_checkbox)
        
        self.silhouettes_checkbox = QtWidgets.QCheckBox("Silhouettes (outlines)")
        self.silhouettes_checkbox.setChecked(False)
        layout.addWidget(self.silhouettes_checkbox)
        
        # Separator
        layout.addSpacing(10)
        
        # Buttons
        button_box = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
        )
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)
    
    def get_options(self):
        """Returns the selected options."""
        return {
            'include_parts': self.parts_checkbox.isChecked(),
            'include_labels': self.labels_checkbox.isChecked(),
            'include_outlines': self.silhouettes_checkbox.isChecked()
        }


class CreateCAMJobCommand:
    """The command to create a CAM job from a layout."""
    def GetResources(self):
        return {
            'Pixmap': 'CNC_Icon.png',
            'MenuText': 'Create CAM Job',
            'ToolTip': 'Creates a CAM job from the selected layout.'
        }

    def Activated(self):
        """This method is executed when the command is activated."""
        selection = FreeCADGui.Selection.getSelection()
        layout_group = None
        if selection:
            selected = selection[0]
            if selected.isDerivedFrom("App::DocumentObjectGroup") and selected.Label.startswith("Layout_"):
                layout_group = selected

        if not layout_group:
            FreeCAD.Console.PrintMessage("Please select a layout group to create a CAM job from.\n")
            return
        
        # Show options dialog
        dialog = CAMOptionsDialog(FreeCADGui.getMainWindow())
        if dialog.exec_() == QtWidgets.QDialog.Accepted:
            options = dialog.get_options()
            
            # Check that at least one option is selected
            if not any(options.values()):
                FreeCAD.Console.PrintWarning("No object types selected. CAM job not created.\n")
                return
            
            cam_manager_instance = cam_manager.CAMManager(layout_group=layout_group)
            cam_manager_instance.create_cam_job(
                include_parts=options['include_parts'],
                include_labels=options['include_labels'],
                include_outlines=options['include_outlines']
            )

    def IsActive(self):
        """Active only if a document is open and a layout group is selected."""
        if not FreeCAD.ActiveDocument: return False
        selection = FreeCADGui.Selection.getSelection()
        if not selection: return False
        selected = selection[0]
        return selected.isDerivedFrom("App::DocumentObjectGroup") and selected.Label.startswith("Layout_")

if FreeCAD.GuiUp:
    FreeCADGui.addCommand('Nesting_CreateCAMJob', CreateCAMJobCommand())
